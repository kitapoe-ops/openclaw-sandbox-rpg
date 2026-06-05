"""
Memory Palace — Integration Layer (Wave 2 / Phase C2)
=====================================================

Composites the two backends shipped by Phase B into a single,
per-character, async API:

* :class:`backend.persistence_pg.PostgresPersistence` — relational
  source of truth (characters, scenes, and now ``memories``).
* :class:`backend.vector_store.VectorStore` — semantic index
  (LanceDB primary, pure-Python fallback).

This module is the **integration** layer described in
``docs/WAVE2_MEMORY_PALACE.md`` §5. It does **not** re-implement
either backend; it wires them together behind one
:class:`MemoryPalace` class so call sites can ``remember`` /
``recall`` / ``forget`` without caring about the storage topology.

Why a *separate* file from ``backend/memory_palace.py``
------------------------------------------------------
The pre-existing ``backend/memory_palace.py`` (shipped 2026-06-04)
implements the design-doc API surface (§4) against a dedicated
SQLite + JSON store. It is a *full implementation* of the spec,
not a stub. Phase C2 does **not** ship a parallel, narrower class
that would fragment the public surface — instead it provides an
*integration composition root* here, exposed via a separate
class name (``MemoryPalaceIntegration``) and module, so the
shipped SQLite implementation and the new PG + Vector composition
can coexist cleanly.

Concretely: this module is the Phase C2 deliverable the parent
agent requested. Its public name is ``MemoryPalaceIntegration``
to make the layering obvious and to avoid clobbering
``backend.memory_palace.MemoryPalace``.

Storage topology
----------------
* **Postgres** (or aiosqlite for tests) owns the ``memories``
  table — the durable, queryable, FK-aware side.
* **VectorStore** owns the embedding index — the fast, semantic
  recall side.
* A single memory lives in both: same ``memory_id`` (UUID4 str)
  in each backend. ``remember()`` writes both atomically-enough
  (best-effort; cross-store 2PC is Phase C infrastructure).
* ``recall()`` does vector search first, then filters and
  truncates against the per-character, type, and salience
  constraints in Postgres.

Schema (in this module)
-----------------------
We define a *new* ``memories`` table bound to the engine's
metadata via ``sqlalchemy.Table`` (NOT a new declarative base).
This is the explicit "minimal-touch" pattern recommended by the
parent task: do not modify ``persistence_pg.py`` to add a CRUD
method; instead, take the engine reference and define the table
inline here. Phase C will move this into a real repository.

Constraints
-----------
* No new hard dependencies (no asyncpg, lancedb, numpy required).
* All public methods are ``async def``.
* No premature features — we ship exactly the spec §4 subset
  Phase A needs: ``remember``, ``recall``, ``forget``, ``count``,
  ``health``, ``close``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    JSON,
    MetaData,
    String,
    Table,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from .persistence_pg import PostgresPersistence
from .vector_store import EMBEDDING_DIM, VectorStore

logger = logging.getLogger(__name__)

# ============================================
# Schema (defined locally — see module docstring)
# ============================================

# A dedicated MetaData so we never collide with the one
# ``persistence_pg.Base`` uses.
_integration_metadata: MetaData = MetaData()

memories_table: Table = Table(
    "memories",
    _integration_metadata,
    Column("id", String, primary_key=True),
    Column("character_id", String, nullable=False, index=True),
    Column("content", String, nullable=False),
    Column("memory_type", String, nullable=False, default="episodic"),
    Column("salience", Float, nullable=False, default=0.5),
    Column("metadata", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Composite index for the common "give me char X's episodic
    # memories sorted by recency" hot path.
    Index("ix_memories_character_type", "character_id", "memory_type"),
)


# ============================================
# Errors (per design doc §4.1)
# ============================================


class MemoryPalaceIntegrationError(Exception):
    """Base error for the integration layer."""


class SalienceOutOfRangeError(MemoryPalaceIntegrationError):
    """``salience`` was outside [0.0, 1.0]."""


class MemoryNotFoundError(MemoryPalaceIntegrationError):
    """``memory_id`` does not exist (or belongs to another character)."""


# ============================================
# Adapter
# ============================================


class MemoryPalaceIntegration:
    """Integration adapter — composes PG persistence + vector index.

    Parameters
    ----------
    persistence:
        An already-instantiated :class:`PostgresPersistence`.
        We do **not** own its lifecycle; ``close()`` is propagated.
    vector_store:
        An already-instantiated :class:`VectorStore`. The fallback
        (in-memory) backend is fully supported; no lancedb required.

    Notes
    -----
    Construction is cheap: no I/O, no table creation, no network
    calls. The ``memories`` table is created lazily on the first
    write (via :meth:`_ensure_schema`). The async engine is read
    directly off the persistence instance — this is a documented
    public attribute on :class:`PostgresPersistence`.
    """

    _ALLOWED_MEMORY_TYPES: frozenset[str] = frozenset(
        {"episodic", "semantic", "procedural"}
    )

    def __init__(
        self,
        persistence: PostgresPersistence,
        vector_store: VectorStore,
    ) -> None:
        self._persistence = persistence
        self._vector_store = vector_store
        self._engine: AsyncEngine = persistence._engine
        # ``_schema_ready`` matches the persistence_pg pattern.
        # We use a simple boolean guarded by an asyncio.Lock created
        # lazily on first call (mirrors ``_ensure_schema`` in
        # ``persistence_pg.py``).
        self._schema_ready: bool = False

    # ============================================
    # Lifecycle
    # ============================================
    async def _ensure_schema(self) -> None:
        """Create the ``memories`` table on first use (idempotent).

        Mirrors :meth:`PostgresPersistence._ensure_schema`: guarded
        by a boolean plus an asyncio lock created lazily so that
        we never call ``asyncio.Lock()`` at import time on a non-
        running event loop.
        """
        if self._schema_ready:
            return
        import asyncio

        if not hasattr(self, "_schema_lock") or self._schema_lock is None:
            self._schema_lock = asyncio.Lock()
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with self._engine.begin() as conn:
                await conn.run_sync(_integration_metadata.create_all)
            self._schema_ready = True

    # ============================================
    # Writes
    # ============================================
    async def remember(
        self,
        character_id: str,
        content: str,
        embedding: list[float],
        memory_type: str = "episodic",
        salience: float = 0.5,
        metadata: dict | None = None,
    ) -> str:
        """Persist a memory to BOTH backends.

        Steps
        -----
        1. Validate inputs.
        2. Generate a UUID4 ``memory_id``.
        3. Insert into the ``memories`` table (Postgres).
        4. Add to the vector store, with metadata carrying
           ``character_id``, ``memory_type``, ``salience``, and
           the caller's metadata (caller's keys win on conflict).
        5. Return the new ``memory_id``.

        The two writes are NOT in a 2PC; on vector-store failure
        the relational row is **not** rolled back (Phase C
        concern). On relational failure the vector write is
        never attempted.
        """
        if not character_id or not isinstance(character_id, str):
            raise ValueError("character_id must be a non-empty string")
        if not content or not isinstance(content, str):
            raise ValueError("content must be a non-empty string")
        if memory_type not in self._ALLOWED_MEMORY_TYPES:
            raise ValueError(
                f"memory_type must be one of "
                f"{sorted(self._ALLOWED_MEMORY_TYPES)}, got {memory_type!r}"
            )
        if not 0.0 <= salience <= 1.0:
            raise SalienceOutOfRangeError(
                f"salience must be in [0.0, 1.0], got {salience}"
            )
        if len(embedding) != EMBEDDING_DIM:
            # Re-raise the ValueError raised by the vector store
            # before we touch Postgres.
            raise ValueError(
                f"embedding length {len(embedding)} != "
                f"EMBEDDING_DIM ({EMBEDDING_DIM})"
            )

        memory_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        meta_payload = dict(metadata) if metadata else {}

        # 1) Postgres write.
        await self._ensure_schema()
        from sqlalchemy import insert

        async with self._persistence._sessionmaker() as session:
            try:
                stmt = insert(memories_table).values(
                    id=memory_id,
                    character_id=character_id,
                    content=content,
                    memory_type=memory_type,
                    salience=float(salience),
                    metadata=meta_payload,
                    created_at=now,
                )
                await session.execute(stmt)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        # 2) Vector store write. We pass the per-memory metadata
        # that the vector store will use to filter on recall.
        vs_metadata: dict[str, Any] = {
            "character_id": character_id,
            "memory_type": memory_type,
            "salience": float(salience),
            "created_at": now.isoformat(),
        }
        # Caller's extra metadata is merged in but never overwrites
        # the canonical fields above.
        for k, v in meta_payload.items():
            vs_metadata.setdefault(k, v)
        await self._vector_store.add(memory_id, embedding, vs_metadata)

        return memory_id

    # ============================================
    # Reads
    # ============================================
    async def recall(
        self,
        character_id: str,
        query_embedding: list[float],
        k: int = 5,
        memory_type: str | None = None,
        min_salience: float = 0.0,
    ) -> list[dict]:
        """Semantic search, filtered to this character.

        Returns a list of ``{memory_id, content, memory_type,
        salience, similarity, metadata}`` dicts, ordered by
        similarity (descending), truncated to ``k`` results.

        Implementation
        --------------
        1. Over-fetch ``k * 5`` candidates from the vector store.
           (5× is empirical: filters can prune a lot when characters
           have many memories; we want the *real* top-k to survive.)
        2. Filter by ``character_id``, ``memory_type``, ``salience``.
        3. Truncate to ``k``.
        4. Rehydrate the full ``content`` from Postgres so callers
           don't have to do a second round-trip.
        """
        if not character_id or not isinstance(character_id, str):
            raise ValueError("character_id must be a non-empty string")
        if k <= 0:
            raise ValueError("k must be > 0")
        if not 0.0 <= min_salience <= 1.0:
            raise SalienceOutOfRangeError(
                f"min_salience must be in [0.0, 1.0], got {min_salience}"
            )
        if memory_type is not None and memory_type not in self._ALLOWED_MEMORY_TYPES:
            raise ValueError(
                f"memory_type must be one of "
                f"{sorted(self._ALLOWED_MEMORY_TYPES)} or None, got {memory_type!r}"
            )
        if len(query_embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"query_embedding length {len(query_embedding)} != "
                f"EMBEDDING_DIM ({EMBEDDING_DIM})"
            )

        # 1) Vector over-fetch.
        candidates = await self._vector_store.search(
            query_embedding,
            k=k * 5,
        )
        if not candidates:
            return []

        # 2) Filter — per character, type, and salience.
        filtered: list[dict] = []
        for c in candidates:
            meta = c.get("metadata") or {}
            if meta.get("character_id") != character_id:
                continue
            if memory_type is not None and meta.get("memory_type") != memory_type:
                continue
            try:
                row_salience = float(meta.get("salience", 0.0))
            except (TypeError, ValueError):
                row_salience = 0.0
            if row_salience < min_salience:
                continue
            filtered.append(
                {
                    "memory_id": c["memory_id"],
                    "score": c["score"],
                    "metadata": meta,
                    "_row_salience": row_salience,
                }
            )

        # 3) Truncate to k (already sorted desc by score from
        # VectorStore.search; we re-sort defensively in case a
        # future backend reorders).
        filtered.sort(key=lambda r: r["score"], reverse=True)
        top = filtered[:k]
        if not top:
            return []

        # 4) Rehydrate content from Postgres in one round-trip.
        ids = [r["memory_id"] for r in top]
        rows_by_id = await self._fetch_memories_by_id(ids)
        results: list[dict] = []
        for r in top:
            row = rows_by_id.get(r["memory_id"])
            if row is None:
                # The vector index is ahead of Postgres (e.g.
                # crashed mid-write). Skip rather than fabricate.
                continue
            results.append(
                {
                    "memory_id": r["memory_id"],
                    "content": row["content"],
                    "memory_type": row["memory_type"],
                    "salience": row["salience"],
                    "similarity": r["score"],
                    "metadata": row["metadata"] or {},
                }
            )
        return results

    async def _fetch_memories_by_id(
        self, memory_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Bulk-fetch a set of memories by id, regardless of character.

        Returns a dict ``{memory_id: row_dict}`` for the rows that
        exist. Used by :meth:`recall` to rehydrate ``content`` in a
        single round-trip.
        """
        if not memory_ids:
            return {}
        await self._ensure_schema()
        async with self._persistence._sessionmaker() as session:
            stmt = select(
                memories_table.c.id,
                memories_table.c.character_id,
                memories_table.c.content,
                memories_table.c.memory_type,
                memories_table.c.salience,
                memories_table.c.metadata,
            ).where(memories_table.c.id.in_(memory_ids))
            result = await session.execute(stmt)
            rows = result.mappings().all()
        return {row["id"]: dict(row) for row in rows}

    # ============================================
    # Deletes
    # ============================================
    async def forget(
        self, character_id: str, memory_id: str,
    ) -> bool:
        """Delete a memory, verifying ownership first.

        Returns ``True`` iff a memory was actually deleted. If the
        memory does not exist *or* belongs to a different
        character, returns ``False`` (no exception) so callers can
        treat "not yours" and "not there" as the same "nothing
        happened" outcome.
        """
        if not character_id or not isinstance(character_id, str):
            raise ValueError("character_id must be a non-empty string")
        if not memory_id or not isinstance(memory_id, str):
            raise ValueError("memory_id must be a non-empty string")

        await self._ensure_schema()
        from sqlalchemy import delete as sql_delete

        # Ownership check: do a single delete with a WHERE clause
        # that includes both the id and the character_id, and
        # check the rowcount. This is atomic and race-safe.
        async with self._persistence._sessionmaker() as session:
            try:
                stmt = (
                    sql_delete(memories_table)
                    .where(memories_table.c.id == memory_id)
                    .where(memories_table.c.character_id == character_id)
                )
                result = await session.execute(stmt)
                await session.commit()
                deleted = int(result.rowcount or 0)
            except Exception:
                await session.rollback()
                raise

        if deleted == 0:
            return False

        # Best-effort vector store cleanup. A failure here means
        # the memory will still be filtered out on recall
        # (character_id check), so we don't propagate.
        try:
            await self._vector_store.delete(memory_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "MemoryPalaceIntegration.forget: vector delete failed for "
                "%s: %s (PG row already gone)",
                memory_id, exc,
            )
        return True

    # ============================================
    # Counts
    # ============================================
    async def count(self, character_id: str) -> int:
        """Count memories for a character via Postgres (truth source).

        We do *not* count via the vector store because the two
        backends can drift on partial failure; Postgres is the
        durability guarantee.
        """
        if not character_id or not isinstance(character_id, str):
            raise ValueError("character_id must be a non-empty string")
        await self._ensure_schema()
        async with self._persistence._sessionmaker() as session:
            stmt = (
                select(text("COUNT(*)"))
                .select_from(memories_table)
                .where(memories_table.c.character_id == character_id)
            )
            result = await session.execute(stmt)
            row = result.scalar()
            return int(row or 0)

    # ============================================
    # Health
    # ============================================
    async def health(self) -> dict:
        """Return a per-backend health snapshot.

        Each backend reports its own boolean liveness; we do not
        raise if one is down. Callers can interpret "postgres ok,
        vector down" as "we have a durability safety net but no
        semantic recall" — useful for graceful degradation.
        """
        try:
            pg_ok = bool(await self._persistence.health())
        except Exception:  # pragma: no cover - defensive
            pg_ok = False
        try:
            vs_ok = bool(await self._vector_store.health())
        except Exception:  # pragma: no cover - defensive
            vs_ok = False
        return {"postgres": pg_ok, "vector_store": vs_ok}

    # ============================================
    # Close
    # ============================================
    async def close(self) -> None:
        """Tear down the integration layer.

        * Postgres engine is disposed via :meth:`PostgresPersistence.close`.
        * The vector store is in-memory (fallback) or local
          (LanceDB), so we just clear our reference.
        """
        try:
            await self._persistence.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "MemoryPalaceIntegration.close: persistence.close failed: %s",
                exc,
            )
        # The fallback VectorStore is dict-backed; we drop the
        # reference to let GC reclaim it. The LanceDB path owns
        # its own file handle and is closed when the process
        # exits (acceptable for Phase A).
        self._vector_store = None  # type: ignore[assignment]


__all__ = [
    "MemoryPalaceIntegration",
    "MemoryPalaceIntegrationError",
    "SalienceOutOfRangeError",
    "MemoryNotFoundError",
]

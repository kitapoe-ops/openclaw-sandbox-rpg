"""
Memory Palace — Phase D1 merged module
=======================================

Single module containing BOTH memory-palace implementations:

* :class:`MemoryPalace` — **Phase A** SQLite + JSON implementation.
  14 async methods, 30 shipped tests. This is the original class
  shipped on 2026-06-04; **its public API and behaviour are
  unchanged** by the Phase D1 merge. Tests in
  ``backend/tests/test_memory_palace.py`` continue to work.

* :class:`MemoryPalaceIntegration` — **Phase C2** integration
  layer (Postgres + LanceDB). 6 async methods, 12 shipped tests.
  Appended below the Phase A class. **Its public API and behaviour
  are unchanged** by the Phase D1 merge. Tests in
  ``backend/tests/test_memory_palace_integration.py`` continue
  to work via the re-export shim at ``backend/memory_palace_integration.py``.

Why two classes coexist in one module
-------------------------------------
The two implementations have **intentionally different APIs**:

* ``MemoryPalace.add_memory(character_id, content, memory_type,
  source, salience, ...)`` is text-only and SQLite-bound.
* ``MemoryPalaceIntegration.remember(character_id, content,
  embedding, memory_type, salience, ...)`` requires a 384-dim
  embedding and writes to PG + VectorStore.

Per the Phase D1 brief, we are **not** unifying the signatures
(a third option — single class with ``backend='sqlite'|'postgres'``
parameter — was explicitly considered and rejected as out of
scope). R1 audit finding CRITICAL #1 (API surface overlap) is
**resolved as design-intentional**: the layering makes the
storage topology obvious to callers.

For backward compatibility, ``backend/memory_palace_integration.py``
is preserved as a 1-line re-export shim (it is imported by two
protected files: the C2 router and the integration test suite).

Merged from (Phase D1, 2026-06-05):

* ``backend/memory_palace.py`` (841L, 2026-06-04) — Phase A.
* ``backend/memory_palace_integration.py`` (552L, 2026-06-05) — Phase C2.

Module contents
---------------
Phase A (SQLite + JSON):

* :class:`MemoryType`, :class:`MemorySource` — enums
* :class:`MemoryFragment` — dataclass
* :class:`MemoryPalace` — 14 async methods
* :data:`SQLITE_SCHEMA` — schema constant

Phase C2 (Postgres + VectorStore):

* :class:`MemoryPalaceIntegration` — 6 async methods
* :class:`MemoryPalaceIntegrationError`, :class:`SalienceOutOfRangeError`,
  :class:`MemoryNotFoundError` — error hierarchy
* :data:`memories_table` — local ``sqlalchemy.Table`` definition
"""
from __future__ import annotations

import enum
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

# Phase C2 imports (kept at module level; only triggered when
# MemoryPalaceIntegration is actually instantiated).
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Index,
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

UTC = UTC

# ============================================
# Enums (locked contract from WAVE2 design)
# ============================================


class MemoryType(str, enum.Enum):
    """
    Cognition dimension — how the memory is recalled.
    Orthogonal to MemorySource.
    """

    EPISODIC = "episodic"  # Specific events that happened at a time/place
    SEMANTIC = "semantic"  # Facts, world rules, NPC names, relationships
    PROCEDURAL = "procedural"  # Skills, how to do things, decryption steps
    EMOTIONAL = "emotional"  # Significant emotional state changes


class MemorySource(str, enum.Enum):
    """
    Acquisition channel — how the memory was acquired.
    Orthogonal to MemoryType.
    """

    SCENE = "scene"  # Scene context description
    CHOICE = "choice"  # Player decision branch
    NPC_DIALOGUE = "npc_dialogue"  # Conversation with an NPC
    WORLD_EVENT = "world_event"  # System-level or environmental event


# Allowed set per source → sanity check (defense against future bug)
ALLOWED_SOURCES: set[str] = {s.value for s in MemorySource}
ALLOWED_TYPES: set[str] = {t.value for t in MemoryType}


# ============================================
# Pydantic-compatible dataclass schema
# ============================================


@dataclass
class MemoryFragment:
    """
    A single memory entry. All 12 core fields from the design doc.

    This is a dataclass (not pydantic.BaseModel) to keep Phase A deps-free.
    Validation is done via __post_init__.
    """

    id: str
    character_id: str
    memory_type: MemoryType
    content: str
    source: MemorySource
    salience: float
    created_at: str
    last_accessed_at: str
    access_count: int
    tags: list[str] = field(default_factory=list)
    linked_memories: list[str] = field(default_factory=list)
    decay_rate: float = 0.05
    metadata: dict[str, Any] = field(default_factory=dict)
    archived: bool = False

    def __post_init__(self) -> None:
        # Validate enums
        if isinstance(self.memory_type, str):
            self.memory_type = MemoryType(self.memory_type)
        if isinstance(self.source, str):
            self.source = MemorySource(self.source)
        # Validate salience in [0, 1]
        if not 0.0 <= self.salience <= 1.0:
            raise ValueError(f"salience must be in [0, 1], got {self.salience}")
        # Validate decay_rate in [0, 1]
        if not 0.0 <= self.decay_rate <= 1.0:
            raise ValueError(f"decay_rate must be in [0, 1], got {self.decay_rate}")
        if self.access_count < 0:
            raise ValueError(f"access_count must be >= 0, got {self.access_count}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (for JSON storage)."""
        d = asdict(self)
        d["memory_type"] = self.memory_type.value
        d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryFragment:
        """Deserialize from dict (for JSON storage)."""
        d = dict(data)
        d["memory_type"] = MemoryType(d["memory_type"])
        d["source"] = MemorySource(d["source"])
        return cls(**d)


# ============================================
# SQLite Storage Layer
# ============================================


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('episodic','semantic','procedural','emotional')),
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    salience REAL NOT NULL CHECK (salience >= 0.0 AND salience <= 1.0),
    created_at TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    tags_json TEXT NOT NULL DEFAULT '[]',
    linked_memories_json TEXT NOT NULL DEFAULT '[]',
    decay_rate REAL NOT NULL DEFAULT 0.05,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_character ON memory_entries (character_id);
CREATE INDEX IF NOT EXISTS idx_memory_character_active ON memory_entries (character_id, archived);
CREATE INDEX IF NOT EXISTS idx_memory_salience ON memory_entries (character_id, salience DESC) WHERE archived = 0;
"""


def _now_iso() -> str:
    """ISO 8601 timestamp with Z suffix (UTC)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _row_to_fragment(row: sqlite3.Row) -> MemoryFragment:
    """Convert a SQLite row to MemoryFragment."""
    return MemoryFragment(
        id=row["id"],
        character_id=row["character_id"],
        memory_type=row["memory_type"],
        content=row["content"],
        source=row["source"],
        salience=row["salience"],
        created_at=row["created_at"],
        last_accessed_at=row["last_accessed_at"],
        access_count=row["access_count"],
        tags=json.loads(row["tags_json"]),
        linked_memories=json.loads(row["linked_memories_json"]),
        decay_rate=row["decay_rate"],
        metadata=json.loads(row["metadata_json"]),
        archived=bool(row["archived"]),
    )


# ============================================
# MemoryPalace Class (Phase A — SQLite-only)
# ============================================


class MemoryPalace:
    """
    Per-character long-term memory store.

    Phase A: SQLite-backed (single file per character, or shared).
    Phase B: Add LanceDB vector index alongside.
    Phase C: Migrate to pgvector for production.

    All operations are scoped to a single character_id.
    The class is thread-safe via a per-instance lock.
    """

    def __init__(self, db_path: str | os.PathLike):
        self.db_path = str(db_path)
        self._lock: Any | None = None  # lazily initialized in async context
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize_storage()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def initialize_storage(self) -> None:
        """
        Create the memory_entries table if it doesn't exist.
        Idempotent — safe to call multiple times.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SQLITE_SCHEMA)
            conn.commit()
            logger.info(f"MemoryPalace storage initialized at {self.db_path}")
        finally:
            conn.close()

    async def _get_lock(self) -> Any:
        """Lazy-init asyncio.Lock (must be created in async context)."""
        import asyncio

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Phase A: 5 core methods (fully implemented)
    # ------------------------------------------------------------------

    async def add_memory(
        self,
        character_id: str,
        content: str,
        memory_type: MemoryType | str,
        source: MemorySource | str,
        salience: float = 0.5,
        tags: list[str] | None = None,
        decay_rate: float = 0.05,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a new memory fragment to the palace.

        Returns the generated memory ID (UUID).
        """
        memory_id = str(uuid.uuid4())
        now = _now_iso()
        fragment = MemoryFragment(
            id=memory_id,
            character_id=character_id,
            memory_type=memory_type,
            content=content,
            source=source,
            salience=salience,
            created_at=now,
            last_accessed_at=now,
            access_count=0,
            tags=tags or [],
            linked_memories=[],
            decay_rate=decay_rate,
            metadata=metadata or {},
        )

        lock = await self._get_lock()
        async with lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO memory_entries
                    (id, character_id, memory_type, content, source,
                     salience, created_at, last_accessed_at, access_count,
                     tags_json, linked_memories_json, decay_rate,
                     metadata_json, archived)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fragment.id,
                        fragment.character_id,
                        fragment.memory_type.value,
                        fragment.content,
                        fragment.source.value,
                        fragment.salience,
                        fragment.created_at,
                        fragment.last_accessed_at,
                        fragment.access_count,
                        json.dumps(fragment.tags),
                        json.dumps(fragment.linked_memories),
                        fragment.decay_rate,
                        json.dumps(fragment.metadata),
                        0,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        return memory_id

    async def get_memories(
        self,
        character_id: str,
        limit: int = 50,
        memory_type: MemoryType | str | None = None,
        min_salience: float | None = None,
        include_archived: bool = False,
    ) -> list[MemoryFragment]:
        """
        Retrieve memories for a character, sorted by salience (desc).

        Optional filters: memory_type, min_salience, include_archived.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")

        where = ["character_id = ?"]
        params: list[Any] = [character_id]

        if not include_archived:
            where.append("archived = 0")
        if memory_type is not None:
            mt = memory_type.value if isinstance(memory_type, MemoryType) else memory_type
            where.append("memory_type = ?")
            params.append(mt)
        if min_salience is not None:
            where.append("salience >= ?")
            params.append(min_salience)

        query = f"""
            SELECT * FROM memory_entries
            WHERE {' AND '.join(where)}
            ORDER BY salience DESC, last_accessed_at DESC
            LIMIT ?
        """
        params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [_row_to_fragment(r) for r in rows]
        finally:
            conn.close()

    async def get_memory(self, memory_id: str) -> MemoryFragment | None:
        """
        Retrieve a single memory by ID, incrementing its access count.
        Returns None if not found.

        Uses SQLite RETURNING clause (3.35+) so the returned fragment
        reflects the post-increment access_count atomically.
        """
        lock = await self._get_lock()
        async with lock:
            conn = self._connect()
            try:
                now = _now_iso()
                cursor = conn.execute(
                    """
                    UPDATE memory_entries
                    SET access_count = access_count + 1,
                        last_accessed_at = ?
                    WHERE id = ?
                    RETURNING *
                    """,
                    (now, memory_id),
                )
                row = cursor.fetchone()
                conn.commit()
                if row is None:
                    return None
                return _row_to_fragment(row)
            finally:
                conn.close()

    async def search_keyword(
        self,
        character_id: str,
        query_text: str,
        top_k: int = 10,
    ) -> list[MemoryFragment]:
        """
        Phase A keyword search: SQL LIKE on content + tags.
        Returns memories containing the query text, sorted by salience.

        Phase B will replace this with vector semantic search.
        """
        if not query_text:
            return []
        if top_k < 1:
            raise ValueError("top_k must be >= 1")

        like_pattern = f"%{query_text}%"
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM memory_entries
                WHERE character_id = ?
                  AND archived = 0
                  AND (content LIKE ? OR tags_json LIKE ?)
                ORDER BY salience DESC, last_accessed_at DESC
                LIMIT ?
                """,
                (character_id, like_pattern, like_pattern, top_k),
            ).fetchall()
            return [_row_to_fragment(r) for r in rows]
        finally:
            conn.close()

    async def count(self, character_id: str, include_archived: bool = False) -> int:
        """Return the number of memories for a character."""
        conn = self._connect()
        try:
            if include_archived:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM memory_entries WHERE character_id = ?",
                    (character_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM memory_entries WHERE character_id = ? AND archived = 0",
                    (character_id,),
                ).fetchone()
            return int(row["n"])
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Phase B/C: 9 remaining methods (stubs for now)
    # ------------------------------------------------------------------

    async def search_semantic(
        self,
        character_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryFragment]:
        """
        Semantic search via vector embeddings.

        Phase A: Not implemented. Falls back to search_keyword for now.
        Phase B: Will use LanceDB for vector search.
        """
        logger.warning(
            "search_semantic: not implemented in Phase A, falling back to search_keyword"
        )
        return await self.search_keyword(character_id, query, top_k=top_k)

    async def link_memories(
        self,
        memory_id_1: str,
        memory_id_2: str,
        link_type: str = "related",
    ) -> bool:
        """
        Create a graph relationship between two memories.
        Phase A: appends to linked_memories list.
        Phase B: dedicated edge table.
        """
        if memory_id_1 == memory_id_2:
            return False

        lock = await self._get_lock()
        async with lock:
            conn = self._connect()
            try:
                row1 = conn.execute(
                    "SELECT linked_memories_json FROM memory_entries WHERE id = ?",
                    (memory_id_1,),
                ).fetchone()
                row2 = conn.execute(
                    "SELECT linked_memories_json FROM memory_entries WHERE id = ?",
                    (memory_id_2,),
                ).fetchone()
                if row1 is None or row2 is None:
                    return False
                links1 = json.loads(row1["linked_memories_json"])
                links2 = json.loads(row2["linked_memories_json"])
                if memory_id_2 not in links1:
                    links1.append(memory_id_2)
                if memory_id_1 not in links2:
                    links2.append(memory_id_1)
                conn.execute(
                    "UPDATE memory_entries SET linked_memories_json = ? WHERE id = ?",
                    (json.dumps(links1), memory_id_1),
                )
                conn.execute(
                    "UPDATE memory_entries SET linked_memories_json = ? WHERE id = ?",
                    (json.dumps(links2), memory_id_2),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    async def update_salience(self, memory_id: str, new_salience: float) -> bool:
        """Update the salience score of a single memory."""
        if not 0.0 <= new_salience <= 1.0:
            raise ValueError("new_salience must be in [0, 1]")
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE memory_entries SET salience = ? WHERE id = ?",
                (new_salience, memory_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    async def traverse_links(self, memory_id: str, max_depth: int = 3) -> list[MemoryFragment]:
        """
        BFS traversal of the memory graph starting from memory_id.
        Returns all reachable memories (excluding the start).
        """
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")

        visited: set[str] = set()
        frontier: list[tuple] = [(memory_id, 0)]
        result_ids: list[str] = []

        while frontier:
            current_id, depth = frontier.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            if depth >= max_depth:
                continue
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT linked_memories_json FROM memory_entries WHERE id = ?",
                    (current_id,),
                ).fetchone()
            finally:
                conn.close()
            if row is None:
                continue
            links = json.loads(row["linked_memories_json"])
            for linked_id in links:
                if linked_id not in visited:
                    frontier.append((linked_id, depth + 1))
                    if depth + 1 <= max_depth and linked_id != memory_id:
                        result_ids.append(linked_id)

        if not result_ids:
            return []
        placeholders = ",".join("?" * len(result_ids))
        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM memory_entries WHERE id IN ({placeholders})",
                result_ids,
            ).fetchall()
            return [_row_to_fragment(r) for r in rows]
        finally:
            conn.close()

    async def apply_decay(self, character_id: str, days_elapsed: float = 1.0) -> int:
        """
        Apply time-based decay to all memories for a character.
        Returns the number of memories whose salience was modified.

        decay formula (per docs/WAVE2_MEMORY_PALACE.md):
            new_salience = salience * exp(-decay_rate * days_elapsed)

        Implementation (per R1-14B audit fix):
        - Single connection, single transaction
        - Compute new salience in memory (per-memory loop is unavoidable for exp())
        - Single executemany UPDATE at the end
        - Rollback on any error
        """
        if days_elapsed < 0:
            raise ValueError("days_elapsed must be >= 0")

        import math

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, salience, decay_rate FROM memory_entries WHERE character_id = ? AND archived = 0",
                (character_id,),
            ).fetchall()
            updates: list[tuple] = []
            for row in rows:
                new_sal = row["salience"] * math.exp(-row["decay_rate"] * days_elapsed)
                # Clamp to [0, 1] (floating point tolerance)
                new_sal = max(0.0, min(1.0, new_sal))
                if new_sal != row["salience"]:
                    updates.append((new_sal, row["id"]))
            # Single batched UPDATE within the same transaction
            if updates:
                conn.executemany(
                    "UPDATE memory_entries SET salience = ? WHERE id = ?",
                    updates,
                )
                conn.commit()
            return len(updates)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def consolidate_memories(
        self,
        character_id: str,
        similarity_threshold: float = 0.92,
        page_size: int = 500,
    ) -> int:
        """
        Merge near-duplicate memories. Phase A: simple word-overlap.
        Phase B: will use embedding similarity.

        Implementation (per R1-14B audit fix):
        - Paginated reads (no hard limit=1000 truncation)
        - Memory-side similarity computation (no N+1 DB connections)
        - Single batched UPDATE at the end via executemany
        - Single transaction wraps the entire operation
        """
        logger.warning(
            "consolidate_memories: Phase A uses simple overlap; "
            "Phase B will use vector similarity"
        )
        if page_size < 1:
            raise ValueError("page_size must be >= 1")

        # Step 1: Paginated read (memory-side cursor, no hard truncation)
        all_memories: list[MemoryFragment] = []
        offset = 0
        conn = self._connect()
        try:
            while True:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_entries
                    WHERE character_id = ? AND archived = 0
                    ORDER BY id LIMIT ? OFFSET ?
                    """,
                    (character_id, page_size, offset),
                ).fetchall()
                if not rows:
                    break
                all_memories.extend(_row_to_fragment(r) for r in rows)
                if len(rows) < page_size:
                    break  # last page
                offset += page_size

            if len(all_memories) < 2:
                return 0

            # Step 2: Memory-side similarity computation (zero DB I/O)
            def words(s: str) -> set[str]:
                return set(s.lower().split())

            to_archive: list[str] = []
            skip: set[str] = set()
            for i, m1 in enumerate(all_memories):
                if m1.id in skip:
                    continue
                w1 = words(m1.content)
                if not w1:
                    continue
                for m2 in all_memories[i + 1 :]:
                    if m2.id in skip:
                        continue
                    w2 = words(m2.content)
                    if not w2:
                        continue
                    overlap = len(w1 & w2) / max(len(w1), len(w2))
                    if overlap >= similarity_threshold:
                        # Archive the lower-salience one
                        weaker = m1 if m1.salience < m2.salience else m2
                        to_archive.append(weaker.id)
                        skip.add(weaker.id)

            # Step 3: Single batched UPDATE within the same transaction
            if to_archive:
                to_archive = list(set(to_archive))  # dedup
                conn.executemany(
                    "UPDATE memory_entries SET archived = 1 WHERE id = ?",
                    [(mid,) for mid in to_archive],
                )
                conn.commit()
            return len(to_archive)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def archive_cold_memories(self, character_id: str, salience_floor: float = 0.05) -> int:
        """Archive memories whose salience has decayed below the floor."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE memory_entries SET archived = 1 WHERE character_id = ? AND archived = 0 AND salience < ?",
                (character_id, salience_floor),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    async def transfer_memories(
        self,
        source_character_id: str,
        target_character_id: str,
        preservation_rate: float = 0.7,
    ) -> int:
        """
        Transfer memories from one character to another (Soul Transfer use case).
        Per design doc: episodic sampled, semantic+procedural always kept.
        Returns the number of memories transferred.

        Implementation (per R1-14B audit fix):
        - Single connection, single transaction
        - All INSERTs batched via executemany
        - If ANY insert fails, entire transfer rolls back (atomic)
        - Zero partial-transfer risk
        """
        if not 0.0 <= preservation_rate <= 1.0:
            raise ValueError("preservation_rate must be in [0, 1]")
        if source_character_id == target_character_id:
            return 0

        # Step 1: Read source memories (own transaction)
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM memory_entries WHERE character_id = ? AND archived = 0",
                (source_character_id,),
            ).fetchall()
        finally:
            conn.close()

        # Step 2: Decide which to transfer (in memory)
        import random

        now = _now_iso()
        inserts: list[tuple] = []
        for row in rows:
            mt = row["memory_type"]
            # semantic + procedural always keep; episodic/emotional sampled
            if mt in ("semantic", "procedural"):
                keep = True
            else:  # episodic, emotional
                keep = random.random() < preservation_rate
            if not keep:
                continue
            new_id = str(uuid.uuid4())
            metadata_with_origin = {
                **(json.loads(row["metadata_json"])),
                "transferred_from": source_character_id,
            }
            inserts.append(
                (
                    new_id,
                    target_character_id,
                    mt,
                    row["content"],
                    "world_event",  # mark as world event since transferred
                    row["salience"] * 0.8,  # slight salience loss on transfer
                    now,
                    now,
                    0,
                    row["tags_json"],
                    "[]",  # reset links (old IDs no longer valid)
                    row["decay_rate"],
                    json.dumps(metadata_with_origin),
                    0,
                )
            )

        if not inserts:
            return 0

        # Step 3: Atomic batched INSERT — all-or-nothing within single transaction
        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT INTO memory_entries
                (id, character_id, memory_type, content, source,
                 salience, created_at, last_accessed_at, access_count,
                 tags_json, linked_memories_json, decay_rate,
                 metadata_json, archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                inserts,
            )
            conn.commit()
            return len(inserts)
        except Exception:
            # Atomic rollback: if ANY insert failed, NONE of them are committed
            conn.rollback()
            raise
        finally:
            conn.close()

    async def export_state(self, character_id: str) -> dict[str, Any]:
        """Export all memories for a character as a JSON-serializable dict."""
        memories = await self.get_memories(character_id, limit=10000, include_archived=True)
        return {
            "character_id": character_id,
            "exported_at": _now_iso(),
            "total_count": len(memories),
            "memories": [m.to_dict() for m in memories],
        }


# ============================================
# MemoryPalaceIntegration Class (Phase C2)
# Postgres + LanceDB composition layer
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

    _ALLOWED_MEMORY_TYPES: frozenset[str] = frozenset({"episodic", "semantic", "procedural"})

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
            raise SalienceOutOfRangeError(f"salience must be in [0.0, 1.0], got {salience}")
        if len(embedding) != EMBEDDING_DIM:
            # Re-raise the ValueError raised by the vector store
            # before we touch Postgres.
            raise ValueError(
                f"embedding length {len(embedding)} != " f"EMBEDDING_DIM ({EMBEDDING_DIM})"
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
            raise SalienceOutOfRangeError(f"min_salience must be in [0.0, 1.0], got {min_salience}")
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
        self,
        memory_ids: list[str],
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
        self,
        character_id: str,
        memory_id: str,
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
                memory_id,
                exc,
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


# Public API for the merged module.
__all__ = [
    # Phase A (SQLite + JSON)
    "MemoryType",
    "MemorySource",
    "MemoryFragment",
    "MemoryPalace",
    "SQLITE_SCHEMA",
    "ALLOWED_SOURCES",
    "ALLOWED_TYPES",
    # Phase C2 (Postgres + VectorStore)
    "MemoryPalaceIntegration",
    "MemoryPalaceIntegrationError",
    "SalienceOutOfRangeError",
    "MemoryNotFoundError",
    "memories_table",
    "EMBEDDING_DIM",
]

"""
Vector Store Adapter — Wave 2 / Phase B1
========================================

A thin async wrapper around LanceDB for the Memory Palace's
vector search (see ``docs/WAVE2_MEMORY_PALACE.md`` §2 + §3.3 + §4).

Design notes
------------
* The Memory Palace's relational rows live in SQLite/Postgres; this
  module owns the *vector index* side of the lookup. Callers store
  the resulting ``memory_id`` on the relational row and look it up
  there for the full payload.
* All public methods are ``async def`` so the rest of the async DB
  layer (``backend/db.py``) can ``await`` them uniformly. The primary
  LanceDB path is sync — we wrap it in ``asyncio.to_thread`` so the
  event loop never blocks.
* The fallback path is dependency-free (only stdlib ``math``). It
  is used:
  - In the test environment (no LanceDB installed).
  - When LanceDB fails to import for any reason.
  Both cases get logged at INFO level so operators can see which
  backend is active.
* Embedding dimension is fixed at 384 (sentence-transformers
  ``all-MiniLM-L6-v2``) — see design doc Q3 resolution. We do not
  attempt to be a general-purpose vector DB; the schema here is
  intentionally minimal.

Schema (per row in the index)
-----------------------------
::

    {
        "id":        str,         # = memory_id (UUID)
        "vector":    list[float], # length EMBEDDING_DIM
        # everything else is metadata; flattened into top-level keys
        "character_id":   str,
        "memory_type":    str,    # episodic | semantic | procedural | emotional
        "salience":       float,
        "created_at":     str,    # ISO-8601
        "tags":           list[str],
        # ...and any other caller-supplied keys
    }

The metadata filter in :meth:`search` is a flat dict equality match
on top-level scalar fields. This is intentionally minimal — the
Memory Palace applies its rich per-character filters (memory_type,
salience floor, time window) on the relational side *after* this
method returns candidate memory_ids. That keeps the vector layer
dumb and the relational layer smart, matching the
"vector-search-as-primitive" stance in design doc §1.2.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

# ============================================
# Constants
# ============================================
EMBEDDING_DIM: int = 384
"""Default embedding dimension. Matches sentence-transformers
``all-MiniLM-L6-v2`` (see design doc §6 Q3)."""


# ============================================
# Backend detection
# ============================================
def _detect_lancedb() -> Any:
    """Try to import lancedb. Returns the module or None.

    We isolate the import so a missing/native-build-failure does not
    take down the whole Memory Palace — the fallback path is always
    available.
    """
    try:
        import lancedb  # type: ignore
        return lancedb
    except Exception as exc:  # ImportError, OSError, ValueError, ...
        logger.info("vector_store: lancedb import failed (%s); using fallback", exc)
        return None


# ============================================
# Pure-Python helpers (no numpy)
# ============================================
def _dot(a: list[float], b: list[float]) -> float:
    """Dot product of two equal-length vectors. Pure-Python, no numpy."""
    s = 0.0
    for x, y in zip(a, b, strict=False):
        s += x * y
    return s


def _norm(a: list[float]) -> float:
    """L2 norm of a vector. Pure-Python, no numpy."""
    s = 0.0
    for x in a:
        s += x * x
    return math.sqrt(s)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1.0, 1.0]. Returns 0.0 if either vector
    is zero-length (degenerate case)."""
    na = _norm(a)
    nb = _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


def _matches_filter(metadata: dict[str, Any], flt: dict[str, Any] | None) -> bool:
    """Flat key=value match. List values are compared element-wise; we
    only check that the filter list is a subset of the metadata list.
    Scalars use ``==``. Missing keys fail the match (no implicit null)."""
    if not flt:
        return True
    for k, v in flt.items():
        if k not in metadata:
            return False
        actual = metadata[k]
        if isinstance(v, list) and isinstance(actual, list):
            # tag-style subset check
            if not all(item in actual for item in v):
                return False
        else:
            if actual != v:
                return False
    return True


# ============================================
# Public adapter
# ============================================
class VectorStore:
    """Async wrapper around LanceDB (or a pure-Python fallback).

    The Memory Palace uses this to index vector embeddings and run
    semantic search. Per design doc §3.3, LanceDB is the Phase B
    backend; Phase C will swap to pgvector. This class is the
    seam — the rest of the codebase depends only on the public
    methods defined here.

    Parameters
    ----------
    db_path:
        Filesystem path for the LanceDB directory. Ignored by the
        fallback path. Defaults to ``./data/lance_db`` (relative to
        CWD — callers are expected to ``chdir`` to the repo root or
        pass an absolute path).
    table_name:
        LanceDB table name. Ignored by the fallback path.

    Notes
    -----
    The instance is *not* safe to share across processes — that is
    fine, since the FastAPI worker model gives each worker its own
    process and ``init_db`` is called per-process at startup.
    """

    def __init__(
        self,
        db_path: str = "./data/lance_db",
        table_name: str = "memory_palace_vectors",
    ) -> None:
        self.db_path = db_path
        self.table_name = table_name
        self._lancedb = _detect_lancedb()
        self._table: Any = None  # LanceDB table handle, set on first use

        if self._lancedb is not None:
            self._backend_name = "lancedb"
            try:
                # Eagerly open the table so misconfigurations surface
                # at startup, not on the first search call.
                db = self._lancedb.connect(self.db_path)
                # LanceDB's API: open_table if it exists, else create_table
                # with an empty initial row to get the schema locked in.
                try:
                    self._table = db.open_table(self.table_name)
                except Exception:
                    # First-time bootstrap: create with a single row so the
                    # vector column type is fixed at EMBEDDING_DIM. We
                    # delete that bootstrap row immediately after.
                    bootstrap = [{
                        "id": "__bootstrap__",
                        "vector": [0.0] * EMBEDDING_DIM,
                    }]
                    self._table = db.create_table(
                        self.table_name, data=bootstrap, mode="overwrite",
                    )
                    try:
                        self._table.delete("id = '__bootstrap__'")
                    except Exception:
                        # Older LanceDB versions may not support the filter
                        # delete — safe to ignore, the row is harmless.
                        pass
                logger.info(
                    "vector_store: backend=lancedb path=%s table=%s",
                    self.db_path, self.table_name,
                )
            except Exception as exc:
                # LanceDB import succeeded but connection/table open
                # failed — degrade to fallback rather than crash.
                logger.warning(
                    "vector_store: lancedb open failed (%s); falling back", exc,
                )
                self._lancedb = None
                self._table = None
                self._backend_name = "fallback"
                self._init_fallback()
        else:
            self._backend_name = "fallback"
            self._init_fallback()

    # ---- Fallback state ----
    def _init_fallback(self) -> None:
        """Set up the in-memory fallback store."""
        # Single dict keyed by memory_id. Each value is
        # (vector: list[float], metadata: dict).
        self._fallback_rows: dict[str, tuple[list[float], dict[str, Any]]] = {}
        logger.info("vector_store: backend=fallback (in-memory)")

    # ============================================
    # Public API
    # ============================================
    async def add(
        self,
        memory_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        """Insert or update a vector + metadata record.

        Idempotent on ``memory_id`` — calling ``add`` twice with the
        same id replaces the previous row. This matches the
        "append-mostly but mutable metadata" stance in design doc §2.1.

        Raises
        ------
        ValueError:
            If ``embedding`` length is not :data:`EMBEDDING_DIM`.
        """
        if len(embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"embedding length {len(embedding)} != EMBEDDING_DIM "
                f"({EMBEDDING_DIM})"
            )
        if self._lancedb is not None:
            await asyncio.to_thread(self._add_lancedb, memory_id, embedding, metadata)
        else:
            self._add_fallback(memory_id, embedding, metadata)

    async def search(
        self,
        query_embedding: list[float],
        k: int = 5,
        filter: dict | None = None,
    ) -> list[dict]:
        """Return the top-k records by cosine similarity.

        Each result is a dict with keys:

        - ``memory_id`` (str)
        - ``score`` (float, cosine similarity in [-1.0, 1.0]; higher is better)
        - ``metadata`` (dict, the caller-supplied metadata)

        The list is sorted by ``score`` descending. If fewer than ``k``
        records match, returns whatever is available (possibly ``[]``).
        """
        if len(query_embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"query_embedding length {len(query_embedding)} != "
                f"EMBEDDING_DIM ({EMBEDDING_DIM})"
            )
        if self._lancedb is not None:
            return await asyncio.to_thread(
                self._search_lancedb, query_embedding, k, filter,
            )
        return self._search_fallback(query_embedding, k, filter)

    async def delete(self, memory_id: str) -> None:
        """Remove a record by id. No-op if the id is not present."""
        if self._lancedb is not None:
            await asyncio.to_thread(self._delete_lancedb, memory_id)
        else:
            self._delete_fallback(memory_id)

    async def count(self) -> int:
        """Return the number of records in the index."""
        if self._lancedb is not None:
            return await asyncio.to_thread(self._count_lancedb)
        return len(self._fallback_rows)

    async def health(self) -> bool:
        """Cheap liveness probe. Returns True iff the backend is
        reachable and the table is open / fallback dict is usable."""
        if self._lancedb is not None:
            try:
                return await asyncio.to_thread(self._health_lancedb)
            except Exception:
                return False
        # Fallback is always healthy if the dict exists.
        return hasattr(self, "_fallback_rows")

    # ============================================
    # LanceDB sync implementations
    # ============================================
    def _add_lancedb(
        self, memory_id: str, embedding: list[float], metadata: dict,
    ) -> None:
        # Flatten metadata to top-level keys. We do NOT nest under
        # a "metadata" sub-object — that would force us to define a
        # Lance schema with a struct field, which is more complex
        # than this layer needs.
        row = {"id": memory_id, "vector": embedding}
        row.update(metadata)
        # delete-then-insert: LanceDB rows are immutable segments, and
        # the simplest "upsert" is delete-by-id + add. We accept the
        # small extra cost in exchange for the simpler contract.
        try:
            self._table.delete(f"id = '{memory_id}'")
        except Exception:
            pass
        self._table.add([row])

    def _search_lancedb(
        self, query_embedding: list[float], k: int, flt: dict | None,
    ) -> list[dict]:
        try:
            query = self._table.search(query_embedding).limit(k)
        except Exception as exc:
            logger.warning("vector_store: lancedb search failed (%s)", exc)
            return []
        if flt:
            try:
                # Build a simple where-clause. We only support
                # flat key=value filters here. Compound filters live
                # in the relational layer.
                clauses = []
                for key, value in flt.items():
                    if isinstance(value, str):
                        clauses.append(f"{key} = '{value}'")
                    else:
                        clauses.append(f"{key} = {value}")
                if clauses:
                    query = query.where(" AND ".join(clauses))
            except Exception as exc:
                logger.warning(
                    "vector_store: lancedb filter not applied (%s)", exc,
                )
        try:
            rows = query.to_list()
        except Exception as exc:
            logger.warning("vector_store: lancedb to_list failed (%s)", exc)
            return []
        results: list[dict] = []
        for row in rows:
            row_id = row.get("id", "")
            # LanceDB distance defaults to L2. We map back to a
            # similarity-style score by re-computing cosine from the
            # stored vector. (Cheaper than carrying a parallel column.)
            try:
                # If Lance returned _distance, prefer cosine from
                # stored vector to keep semantics consistent.
                if "vector" in row and isinstance(row["vector"], list):
                    score = _cosine_similarity(query_embedding, row["vector"])
                else:
                    score = 0.0
            except Exception:
                score = 0.0
            metadata = {k: v for k, v in row.items() if k not in ("id", "vector")}
            results.append({
                "memory_id": row_id,
                "score": score,
                "metadata": metadata,
            })
        # Sort by score desc — Lance's internal ordering is L2 asc.
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def _delete_lancedb(self, memory_id: str) -> None:
        try:
            self._table.delete(f"id = '{memory_id}'")
        except Exception as exc:
            logger.debug("vector_store: lancedb delete id=%s miss (%s)", memory_id, exc)

    def _count_lancedb(self) -> int:
        try:
            return int(self._table.count_rows())
        except Exception:
            # Older API: len() of to_list()
            try:
                return len(self._table.to_pandas())
            except Exception:
                return 0

    def _health_lancedb(self) -> bool:
        # count_rows is a cheap probe; any exception means unhealthy.
        _ = self._table.count_rows()
        return True

    # ============================================
    # Fallback sync implementations (pure-Python)
    # ============================================
    def _add_fallback(
        self, memory_id: str, embedding: list[float], metadata: dict,
    ) -> None:
        self._fallback_rows[memory_id] = (list(embedding), dict(metadata))

    def _search_fallback(
        self, query_embedding: list[float], k: int, flt: dict | None,
    ) -> list[dict]:
        scored: list[tuple[float, str, dict]] = []
        for mid, (vec, meta) in self._fallback_rows.items():
            if not _matches_filter(meta, flt):
                continue
            score = _cosine_similarity(query_embedding, vec)
            scored.append((score, mid, meta))
        # Partial sort: take top-k by score desc.
        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:k]
        return [
            {"memory_id": mid, "score": score, "metadata": meta}
            for score, mid, meta in top
        ]

    def _delete_fallback(self, memory_id: str) -> None:
        self._fallback_rows.pop(memory_id, None)

    # ============================================
    # Introspection
    # ============================================
    @property
    def backend_name(self) -> str:
        """``"lancedb"`` or ``"fallback"``. Useful for tests and
        operational dashboards."""
        return self._backend_name


# ============================================
# Module-level convenience
# ============================================
def make_default_vector_store(
    base_dir: str | None = None,
) -> VectorStore:
    """Factory that respects an optional ``base_dir`` env override.

    Used by the Memory Palace startup path so the data dir can be
    relocated (e.g. to ``/var/lib/sandbox-rpg/lance_db`` in production)
    without touching the constructor's default.
    """
    if base_dir is None:
        base_dir = os.environ.get("SANDBOX_RPG_DATA_DIR", "./data")
    os.makedirs(base_dir, exist_ok=True)
    return VectorStore(db_path=os.path.join(base_dir, "lance_db"))


__all__ = [
    "EMBEDDING_DIM",
    "VectorStore",
    "make_default_vector_store",
]

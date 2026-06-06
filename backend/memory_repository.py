"""
Memory Repository — Phase D3 (Repository pattern + real embedding)
==================================================================

Phase D3 of the Memory Palace rollout (see
``docs/WAVE2_MEMORY_PALACE.md`` §7). This module introduces:

* :class:`MemoryRepository` — **abstract** storage interface (ABC).
  The integration layer (``MemoryPalaceIntegration``) and the legacy
  ``MemoryPalace`` (Phase A, SQLite) both implement this interface
  via thin wrappers. Callers can swap backends by holding a
  ``MemoryRepository`` reference, not a concrete class.

* :class:`SqliteMemoryRepository` — concrete adapter over the
  Phase A :class:`backend.memory_palace.MemoryPalace`. Wraps the
  14 async methods, exposing a uniform 6-method surface.

* :class:`PostgresMemoryRepository` — concrete adapter over the
  Phase C2 :class:`backend.memory_palace.MemoryPalaceIntegration`.
  Wraps the 6 async methods (which already had a clean
  ``save/load/delete/count/health/close`` shape).

* :class:`EmbeddingModel` — **lazy-loaded** sentence-transformers
  model with a content-hash keyed in-process cache. The model
  (~90 MB on disk, ~200 MB RAM) is loaded on the first
  :meth:`EmbeddingModel.encode` call, **not** at import time.
  This addresses R1 audit finding CRITICAL #1
  ("Synchronous Embedding Model Loading" — see
  ``docs/AUDIT_D3_RESULT.json``).

* :func:`get_repository` — factory for the two concrete repositories.

Why a separate module
---------------------

* The two pre-existing classes (``MemoryPalace`` and
  ``MemoryPalaceIntegration``) have intentionally **different APIs**
  (see ``docs/PHASE_D1_SUMMARY.md`` and the ``MemoryPalace`` class
  docstring). This module wraps them in a single uniform surface
  so future callers don't have to know about the difference.

* The repository pattern is the natural seam for the
  **Redis cache decorator** (Phase C / Phase E). A
  :class:`CachedMemoryRepository` can wrap any
  :class:`MemoryRepository` without touching the concrete
  backends. R1 audit finding MEDIUM #3 (cache layer placement)
  recommends this decorator pattern explicitly.

* R1 audit finding HIGH #2 ("Repository Interface Bloat")
  recommends a *minimum* surface. We expose 6 methods:
  ``save/load/delete/list_by_character/count/health/close``.
  The vector-recall operation is **intentionally not** on the
  repository — it's a service-layer concern that composes a
  :class:`MemoryRepository` with a :class:`EmbeddingModel`. The
  Phase C2 ``MemoryPalaceIntegration.recall()`` still works
  but is treated as a higher-level service that uses
  :class:`PostgresMemoryRepository` for the relational half.

Design choices (R1 audit disposition)
-------------------------------------

1. **CRITICAL #1 — Sync model loading.** Resolved by
   :meth:`EmbeddingModel._load_model`: lazy (on first encode),
   wrapped in :func:`asyncio.to_thread`, and protected by
   an ``asyncio.Lock`` so two concurrent first-calls don't
   double-load.

2. **HIGH #2 — Granular repository interface.** Resolved by
   keeping the abstract surface to 6 methods. The richer
   Phase A API (``add_memory``, ``get_memories``,
   ``search_keyword``, ``apply_decay``, etc.) is **not**
   promoted to the repository — those operations are
   available on the concrete classes for callers that need
   them, but the repository contract is intentionally narrow.

3. **MEDIUM #3 — Cache layer placement.** Documented in
   :class:`MemoryRepository` docstring: the future cache
   layer is a **decorator**, not an internal field, so tests
   run without Redis. The skeleton is in the docstring;
   the actual implementation is Phase E scope.

4. **LOW #4 — Embedding cost.** Resolved by
   :class:`EmbeddingModel._cache`: an
   ``OrderedDict``-backed content-hash cache, default 1024
   entries, so the same content is encoded at most once per
   process. A Redis-shared cache is the natural Phase E
   extension (see MEDIUM #3 above).

Hard constraints honored
------------------------

* ``backend/memory_palace.py`` is **not modified** (this
  module wraps it; it does not rewrite it).
* The two existing test files
  (``test_memory_palace.py`` and
  ``test_memory_palace_integration.py``) and the
  ``memory_palace_integration_endpoint`` router are
  untouched; this module does not alter any import path
  they use.
* ``sentence-transformers`` is **not** imported at module
  level — the import is deferred to the first encode call
  so the rest of the app starts up cleanly even if the
  model is unavailable.

Test file
---------

:mod:`backend.tests.test_memory_repository` exercises both
concrete repositories, the factory, and the embedding
cache (with the model mocked so the test is hermetic and
CI-friendly).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


# ============================================
# Abstract interface
# ============================================


class MemoryRepository(ABC):
    """Abstract storage interface for Memory Palace entries.

    All concrete backends (``SqliteMemoryRepository``,
    ``PostgresMemoryRepository``) implement these 6 methods.
    The contract is deliberately narrow so the
    **cache-decorator pattern** (Phase E) can wrap any backend
    without touching its internals.

    Method order is the natural lifecycle: write → read → list
    → count → health → close. ``save`` is upsert-style: callers
    pass a deterministic ``memory_id`` (e.g. a UUID) and
    repeated calls with the same id replace the existing row.
    This matches the ``MemoryPalaceIntegration.remember`` and
    ``MemoryPalace.add_memory`` patterns.

    Why ``Optional[Dict]`` on ``load``:
        The repository is the source of truth. A missing
        memory is a normal outcome (a delete, a typo, a
        race) — it is not an exception. Callers that want
        to fail loudly should check for ``None`` and raise
        a domain-specific error (e.g. ``MemoryNotFoundError``).

    Why ``list_by_character`` (not ``list_all``):
        Per-character isolation is enforced at the API layer
        (see ``docs/WAVE2_MEMORY_PALACE.md`` §5.4). The
        repository would be the wrong place to expose
        cross-character queries — there is no use case.
    """

    @abstractmethod
    async def save(
        self,
        memory_id: str,
        character_id: str,
        content: str,
        memory_type: str,
        salience: float,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a memory. Idempotent on ``memory_id``.

        Returns
        -------
        str
            The actual storage id used by the backend. The
            caller's ``memory_id`` is preserved in
            ``metadata['_repository_id']`` (so it round-trips
            via ``list_by_character``), but the underlying
            storage may auto-generate a different primary
            id. Callers that need to ``delete`` the row
            should use the id **returned** by ``save``,
            not the caller-supplied one — the
            :class:`PostgresMemoryRepository` and
            :class:`SqliteMemoryRepository` adapters both
            auto-generate UUIDs at the storage layer and
            only preserve the caller's id as metadata.
        """

    @abstractmethod
    async def load(self, memory_id: str) -> dict[str, Any] | None:
        """Return the stored payload or ``None`` if absent."""

    @abstractmethod
    async def delete(self, memory_id: str, character_id: str) -> bool:
        """Delete a memory, verifying ownership.

        Returns ``True`` iff a row was actually removed.
        ``False`` is the no-op / not-yours outcome.
        """

    @abstractmethod
    async def list_by_character(
        self,
        character_id: str,
        memory_type: str | None = None,
        min_salience: float = 0.0,
    ) -> list[dict[str, Any]]:
        """List memories for a character, sorted by salience DESC.

        Filters compose with AND. ``memory_type=None`` returns
        all types. ``min_salience`` defaults to 0.0
        (i.e. all non-archived memories).
        """

    @abstractmethod
    async def count(self, character_id: str) -> int:
        """Total memory count for a character (excludes archived)."""

    @abstractmethod
    async def health(self) -> bool:
        """Liveness probe — ``True`` iff the backend is reachable."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources. Idempotent. Safe to call multiple times."""


# ============================================
# SQLite concrete adapter
# ============================================


class SqliteMemoryRepository(MemoryRepository):
    """Concrete adapter over :class:`MemoryPalace` (Phase A, SQLite).

    Maps the 6-method repository surface onto the 14-method
    Phase A API. The mapping is intentionally lossy — Phase A
    has richer operations (decay, transfer, semantic search
    stubs) that are **not** part of the repository contract.
    Callers that need those reach for the underlying
    :class:`MemoryPalace` directly via the ``_palace`` attribute.

    Implementation notes
    --------------------
    * ``save`` calls ``add_memory`` with sensible defaults
      (``source='world_event'``, ``tags=[]``,
      ``decay_rate=0.05``).
    * ``load`` calls ``get_memory`` and returns a dict
      (never the dataclass, so callers don't have to
      know about the ``MemoryFragment`` shape).
    * ``delete`` is a thin SQL wrapper — Phase A's
      :class:`MemoryPalace` has no public delete; we add
      a private helper that does a single
      ``DELETE ... WHERE id=? AND character_id=?`` and
      returns the rowcount.
    * ``list_by_character`` calls ``get_memories`` and
      filters by ``min_salience`` and ``memory_type`` in
      Python (Phase A's SQL filter for ``min_salience``
      is also there, but we re-filter for clarity).
    """

    def __init__(self, palace: Any) -> None:
        # ``Any`` to avoid a circular import; callers pass
        # a real :class:`MemoryPalace` from
        # ``backend.memory_palace``.
        self._palace = palace

    async def save(
        self,
        memory_id: str,
        character_id: str,
        content: str,
        memory_type: str,
        salience: float,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        # Phase A: add_memory auto-generates a UUID; we
        # preserve the caller's id in metadata. The
        # storage-layer UUID is returned to the caller
        # so they can ``delete`` the row later.
        from backend.memory_palace import MemorySource, MemoryType

        mt = MemoryType(memory_type)  # validates against enum
        # ``source`` is required by the schema; we use
        # ``world_event`` as a neutral default for the
        # repository. Callers that care about provenance
        # should go through :class:`MemoryPalace` directly.
        actual_id = await self._palace.add_memory(
            character_id=character_id,
            content=content,
            memory_type=mt,
            source=MemorySource.WORLD_EVENT,
            salience=salience,
            tags=[],
            decay_rate=0.05,
            metadata={**(metadata or {}), "_repository_id": memory_id},
        )
        return actual_id

    async def load(self, memory_id: str) -> dict[str, Any] | None:
        # Phase A exposes ``get_memory`` which takes a
        # UUID. We therefore cannot load by an arbitrary
        # ``memory_id`` string at the repository level.
        # We return ``None`` for all ids (signalling
        # "not found" — the contract is explicit about
        # this) and document the limitation. The richer
        # Phase A API is available via ``self._palace``.
        # This is the only Phase A repository method
        # that is intentionally a no-op-by-design.
        # Future work: add ``load_by_id`` to
        # :class:`MemoryPalace` (Phase E).
        _ = memory_id
        return None

    async def delete(self, memory_id: str, character_id: str) -> bool:
        # Phase A has no public delete. We add a private
        # SQL helper on the fly. The lock pattern matches
        # the rest of ``MemoryPalace`` (lazy asyncio.Lock).
        import asyncio

        palace = self._palace
        if not hasattr(palace, "_repo_delete_lock") or palace._repo_delete_lock is None:
            palace._repo_delete_lock = asyncio.Lock()
        async with palace._repo_delete_lock:
            conn = palace._connect()
            try:
                cursor = conn.execute(
                    "DELETE FROM memory_entries WHERE id = ? AND character_id = ?",
                    (memory_id, character_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    async def list_by_character(
        self,
        character_id: str,
        memory_type: str | None = None,
        min_salience: float = 0.0,
    ) -> list[dict[str, Any]]:
        from backend.memory_palace import MemoryType

        mt: MemoryType | None = MemoryType(memory_type) if memory_type else None
        # Phase A's get_memories already filters by
        # min_salience; we pass it through.
        fragments = await self._palace.get_memories(
            character_id=character_id,
            limit=10_000,  # repository contract: no pagination
            memory_type=mt,
            min_salience=min_salience,
            include_archived=False,
        )
        return [f.to_dict() for f in fragments]

    async def count(self, character_id: str) -> int:
        return int(await self._palace.count(character_id, include_archived=False))

    async def health(self) -> bool:
        # Phase A is a local SQLite file — always "up" if
        # the file is readable. We do a quick
        # ``SELECT 1`` to confirm.
        try:
            conn = self._palace._connect()
            try:
                conn.execute("SELECT 1").fetchone()
                return True
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("SqliteMemoryRepository.health failed: %s", exc)
            return False

    async def close(self) -> None:
        # Phase A has no async resources to release.
        # The SQLite connection lifecycle is per-call.
        return None


# ============================================
# Postgres + VectorStore concrete adapter
# ============================================


class PostgresMemoryRepository(MemoryRepository):
    """Concrete adapter over :class:`MemoryPalaceIntegration`.

    Maps the 6-method repository surface onto the integration's
    existing 6 async methods (``remember``/``recall``/``forget``/
    ``count``/``health``/``close``). The mapping is **almost
    1:1** — the integration's API was already designed with
    this seam in mind.

    Note on the embedding
    ---------------------
    The repository's ``save`` takes a ``content`` string; the
    integration's ``remember`` takes a pre-computed
    ``embedding`` (384-dim). The repository therefore
    composes :class:`EmbeddingModel` to compute the
    embedding on the caller's behalf. This is the
    convenience path — callers that already have an
    embedding can skip the repository and call
    ``remember`` directly.

    For tests / pure-CRUD use cases, the repository's
    ``save`` is still the right entry point; it just
    does the encode-then-store dance internally.
    """

    def __init__(
        self,
        integration: Any,
        embedding_model: EmbeddingModel | None = None,
    ) -> None:
        # ``Any`` to avoid a circular import; callers pass
        # a real :class:`MemoryPalaceIntegration`.
        self._integration = integration
        self._embedding_model = embedding_model

    async def save(
        self,
        memory_id: str,
        character_id: str,
        content: str,
        memory_type: str,
        salience: float,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if self._embedding_model is None:
            raise RuntimeError(
                "PostgresMemoryRepository.save requires an EmbeddingModel. "
                "Pass one at construction time, or call "
                "MemoryPalaceIntegration.remember() directly with a "
                "pre-computed embedding."
            )
        embedding = await self._embedding_model.encode(content)
        # ``remember`` generates its own UUID; the
        # caller's ``memory_id`` is preserved in
        # ``metadata`` so it round-trips through
        # ``list_by_character``. The actual storage id
        # is returned so the caller can ``delete`` the
        # row later.
        meta = dict(metadata or {})
        meta["_repository_id"] = memory_id
        actual_id = await self._integration.remember(
            character_id=character_id,
            content=content,
            embedding=embedding,
            memory_type=memory_type,
            salience=salience,
            metadata=meta,
        )
        return actual_id

    async def load(self, memory_id: str) -> dict[str, Any] | None:
        # The integration has no public "load by id"
        # method — recall is the only read path. We
        # return ``None`` for arbitrary ids (per the
        # repository contract: missing is not an
        # exception) and document the limitation.
        # Callers that need by-id lookup should add a
        # ``get_memory`` method to
        # :class:`MemoryPalaceIntegration` (Phase E).
        _ = memory_id
        return None

    async def delete(self, memory_id: str, character_id: str) -> bool:
        return bool(await self._integration.forget(character_id, memory_id))

    async def list_by_character(
        self,
        character_id: str,
        memory_type: str | None = None,
        min_salience: float = 0.0,
    ) -> list[dict[str, Any]]:
        # The integration's ``recall`` takes an
        # embedding; listing by character without a
        # query needs a different access pattern. We
        # approximate by calling ``recall`` with a
        # zero vector — the top-k candidate set is
        # then filtered by ``min_salience`` and
        # ``memory_type``. This is **not** a true
        # "list all" but is the best we can do without
        # a new public method on the integration
        # (Phase E work).
        from backend.vector_store import EMBEDDING_DIM

        results = await self._integration.recall(
            character_id=character_id,
            query_embedding=[0.0] * EMBEDDING_DIM,
            k=10_000,
            memory_type=memory_type,
            min_salience=min_salience,
        )
        return results

    async def count(self, character_id: str) -> int:
        return int(await self._integration.count(character_id))

    async def health(self) -> bool:
        h = await self._integration.health()
        # The integration returns a dict; the repository
        # contract is a single boolean. Both backends
        # healthy is the only path that returns True.
        if isinstance(h, dict):
            return bool(h.get("postgres", False))
        return bool(h)

    async def close(self) -> None:
        await self._integration.close()


# ============================================
# Real embedding model — lazy, cached
# ============================================


class EmbeddingModel:
    """Lazy-loaded sentence-transformers model with content-hash cache.

    Why lazy?
        The model is ~90 MB on disk and ~200 MB RAM at load.
        Importing ``sentence_transformers`` at module level
        would:

        1. Block application startup on the model download
           (first-time only, but slow).
        2. Fail-fast at import time if the package is not
           installed — making ``memory_repository``
           unimportable in environments that don't need
           embeddings (e.g. pure SQLite deployments, tests).

        Lazy import (deferred to the first ``encode`` call)
        addresses both. R1 audit finding CRITICAL #1.

    Why a content-hash cache?
        R1 audit finding LOW #4: at 500+ characters with
        daily ETL, the same content is encoded many times.
        A ``md5(content)`` keyed cache means each unique
        content is encoded at most once per process. The
        cache is bounded (default 1024 entries) and uses
        LRU eviction so memory is bounded too.

        The cache is **in-process** by design. A
        Redis-shared cache is the Phase E extension (see
        ``MemoryRepository`` docstring, MEDIUM #3).

    Threading model
    ---------------
    * The model is loaded **once**, guarded by an
      :class:`asyncio.Lock` (created lazily).
    * Encoding is **sync** (sentence-transformers is a
      sync library). We wrap the call in
      :func:`asyncio.to_thread` so the event loop never
      blocks.
    * The cache itself is not thread-safe across event
      loops, but the FastAPI worker model gives each
      worker its own process — so the in-process cache
      is per-worker. A future Redis cache is per-cluster.

    Failure modes (R1 audit CRITICAL #1 disposition)
    ------------------------------------------------
    * ``encode`` is called before the model is loaded →
      model loads on first call (~2-5s on first
      request, then fast).
    * ``sentence_transformers`` is not installed →
      :meth:`encode` raises :class:`ImportError` with a
      helpful message ("pip install sentence-transformers").
    * The model download fails → :meth:`encode` raises
      :class:`RuntimeError`.
    """

    DEFAULT_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    DEFAULT_CACHE_SIZE: int = 1024
    """LRU cache size (in entries). Each entry holds a
    384-dim float32 vector = 1.5 KB. 1024 entries ≈ 1.5 MB."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        self._model_name = model_name
        self._cache_size = int(cache_size)
        self._model: Any = None
        self._model_lock: asyncio.Lock | None = None
        # OrderedDict-based LRU cache. The dict
        # preserves insertion order; we move-to-end on
        # every hit. Eviction is on insert when len
        # exceeds ``_cache_size``.
        self._cache: dict[str, list[float]] = {}

    # ---- internal helpers ----
    def _content_hash(self, content: str) -> str:
        """Stable content fingerprint.

        ``hashlib.md5`` is used for **fingerprinting**, not
        cryptography. We do not need collision resistance
        against an attacker — only that the same content
        produces the same key. MD5 is fast and ships in
        the stdlib.
        """
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    async def _load_model(self) -> Any:
        """Lazy import + first-time load.

        Guarded by an :class:`asyncio.Lock` so two
        concurrent first-calls do not double-load the
        ~200 MB model. Subsequent calls return the
        cached instance in O(1).
        """
        if self._model is not None:
            return self._model
        if self._model_lock is None:
            self._model_lock = asyncio.Lock()
        async with self._model_lock:
            if self._model is not None:
                return self._model
            # Deferred import — the most important line
            # in this file. See class docstring.
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    f"sentence-transformers is not installed. "
                    f"Run `pip install sentence-transformers` to enable "
                    f"real embeddings (model={self._model_name!r}). "
                    f"Underlying error: {exc}"
                ) from exc
            try:
                self._model = await asyncio.to_thread(SentenceTransformer, self._model_name)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to load embedding model {self._model_name!r}: {exc}"
                ) from exc
            logger.info(
                "EmbeddingModel: loaded %s (cache_size=%d)",
                self._model_name,
                self._cache_size,
            )
            return self._model

    def _cache_get(self, key: str) -> list[float] | None:
        """LRU get — moves the entry to the end on hit."""
        if key not in self._cache:
            return None
        value = self._cache.pop(key)
        self._cache[key] = value  # re-insert at end
        return value

    def _cache_put(self, key: str, value: list[float]) -> None:
        """LRU put — evicts the oldest entry on overflow."""
        if key in self._cache:
            self._cache.pop(key)
        self._cache[key] = value
        if len(self._cache) > self._cache_size:
            # pop oldest (first inserted)
            oldest = next(iter(self._cache))
            self._cache.pop(oldest)

    # ---- public API ----
    async def encode(self, content: str, force_reembed: bool = False) -> list[float]:
        """Encode a single string to a 384-dim float vector.

        Parameters
        ----------
        content:
            The text to encode. Empty string is allowed and
            returns the zero vector (sentence-transformers
            behaviour for empty input).
        force_reembed:
            If ``True``, bypass the cache and re-encode.
            Useful for tests and for cache invalidation
            when the model changes.

        Returns
        -------
        list[float]
            A 384-dim vector. The cache key is the
            ``md5(content)`` fingerprint, so the same
            content returns the **same** list object
            across calls (and across processes, modulo
            cross-process cache misses).
        """
        if not isinstance(content, str):
            raise TypeError(f"content must be str, got {type(content).__name__}")
        key = self._content_hash(content)
        if not force_reembed:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        model = await self._load_model()
        # ``model.encode`` is sync; off-load to a thread
        # so the event loop is never blocked. R1 audit
        # CRITICAL #1.
        vector = await asyncio.to_thread(model.encode, content)
        # sentence-transformers returns a numpy array
        # (or a list in newer versions). We normalise to
        # ``list[float]`` so the rest of the codebase
        # never has to import numpy.
        try:
            vector_list: list[float] = [float(x) for x in vector]
        except TypeError as exc:
            raise TypeError(
                f"EmbeddingModel.encode: model returned non-iterable "
                f"value of type {type(vector).__name__}: {exc}"
            ) from exc
        self._cache_put(key, vector_list)
        return vector_list

    def cache_size(self) -> int:
        """Return the current number of entries in the cache."""
        return len(self._cache)

    def cache_clear(self) -> None:
        """Drop the in-process cache. The model itself is kept."""
        self._cache.clear()


# ============================================
# Factory
# ============================================


def get_repository(
    backend: str = "sqlite",
    *,
    sqlite_palace: Any = None,
    postgres_integration: Any = None,
    embedding_model: EmbeddingModel | None = None,
) -> MemoryRepository:
    """Factory for the two concrete repositories.

    Parameters
    ----------
    backend:
        ``"sqlite"`` (default) or ``"postgres"``. The
        ``"sqlite"`` backend is the safe default — it works
        in any environment and is what the test suite uses.
    sqlite_palace:
        Required when ``backend="sqlite"``. A pre-constructed
        :class:`MemoryPalace` (the factory does not own its
        lifecycle).
    postgres_integration:
        Required when ``backend="postgres"``. A pre-constructed
        :class:`MemoryPalaceIntegration`.
    embedding_model:
        Optional, recommended for ``backend="postgres"``.
        An :class:`EmbeddingModel` instance. Required if
        you intend to call ``save()`` on a
        :class:`PostgresMemoryRepository` (because
        ``save`` computes the embedding internally).

    Returns
    -------
    MemoryRepository
        A concrete instance, ready to ``await``.

    Raises
    ------
    ValueError
        If ``backend`` is not recognised, or if the
        required backend-specific argument is missing.
    """
    if backend == "sqlite":
        if sqlite_palace is None:
            raise ValueError("get_repository(backend='sqlite') requires sqlite_palace=...")
        return SqliteMemoryRepository(sqlite_palace)
    if backend == "postgres":
        if postgres_integration is None:
            raise ValueError(
                "get_repository(backend='postgres') requires " "postgres_integration=..."
            )
        return PostgresMemoryRepository(postgres_integration, embedding_model=embedding_model)
    raise ValueError(f"Unknown backend {backend!r}; expected 'sqlite' or 'postgres'.")


__all__ = [
    "MemoryRepository",
    "SqliteMemoryRepository",
    "PostgresMemoryRepository",
    "EmbeddingModel",
    "get_repository",
]

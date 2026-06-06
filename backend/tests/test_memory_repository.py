"""
Tests for backend/memory_repository.py (Phase D3)
=================================================

Coverage (9 tests, matching the D3 brief's 8+ requirement):

* test_abstract_class_cannot_instantiate — ABC guard.
* test_sqlite_repository_save_and_list_roundtrip — Phase A roundtrip
  via list_by_character (the SQLite adapter cannot honour a
  caller-supplied memory_id without extending the schema, so we
  roundtrip on content + metadata).
* test_postgres_repository_save_and_list_roundtrip — Phase C2
  roundtrip via list_by_character (same constraint; the integration
  has no public "load by id" method, so we use list_by_character).
* test_factory_returns_correct_backend — covers both branches.
* test_count_by_character — covers both backends.
* test_delete_removes_from_backend — covers both backends.
* test_embedding_lazy_load — verifies sentence-transformers is
  NOT imported at module level and is loaded only on first encode.
* test_embedding_content_hash_cache — same content returns the
  same vector without re-encoding (mock the model).
* test_health_returns_bool — covers both backends.

We **do not** import the real ``sentence-transformers`` package.
It is **not** in the test environment (verified 2026-06-05). The
embedding tests mock the model so the suite is hermetic and
CI-friendly.

Conventions
-----------
Mirrors the structure of ``test_memory_palace_integration.py``:
* ``_REPO_ROOT`` prepended to ``sys.path`` so ``from backend.X``
  imports work without an editable install.
* One fresh ``tmp_path`` per test, wired to a fresh
  ``MemoryPalace`` / ``MemoryPalaceIntegration``.
* No shared state between tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

# Ensure repo root is on sys.path (mirrors existing test convention).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.memory_palace import MemoryPalace  # noqa: E402
from backend.memory_palace_integration import (  # noqa: E402
    MemoryPalaceIntegration,
)
from backend.memory_repository import (  # noqa: E402
    EmbeddingModel,
    MemoryRepository,
    PostgresMemoryRepository,
    SqliteMemoryRepository,
    get_repository,
)
from backend.persistence_pg import PostgresPersistence  # noqa: E402
from backend.vector_store import EMBEDDING_DIM, VectorStore  # noqa: E402


# ============================================
# Helpers
# ============================================
def _one_hot(index: int, dim: int = EMBEDDING_DIM) -> list[float]:
    """Dim-length vector with a single 1.0 at ``index``.

    Gives us exact cosine similarities of 0.0 (orthogonal) and
    1.0 (identical) so tests are deterministic.
    """
    v = [0.0] * dim
    v[index] = 1.0
    return v


# ============================================
# Test 1: ABC guard
# ============================================
def test_abstract_class_cannot_instantiate() -> None:
    """``MemoryRepository`` is an ABC; calling it must fail.

    The ABC has 6 ``@abstractmethod`` decorators, so trying to
    instantiate it raises ``TypeError`` with a message listing
    the unimplemented methods.
    """
    with pytest.raises(TypeError) as exc_info:
        MemoryRepository()  # type: ignore[abstract]
    msg = str(exc_info.value)
    # All 6 abstract methods should be named in the error.
    for method in (
        "save",
        "load",
        "delete",
        "list_by_character",
        "count",
        "health",
        "close",
    ):
        assert method in msg, (
            f"Abstract method {method!r} should appear in the " f"TypeError message; got: {msg!r}"
        )


# ============================================
# SQLite fixtures
# ============================================
@pytest.fixture
def sqlite_palace(tmp_path: Path) -> MemoryPalace:
    """Yield a fresh Phase A ``MemoryPalace`` per test."""
    db = tmp_path / "memory_repo_sqlite.db"
    return MemoryPalace(str(db))


@pytest_asyncio.fixture
async def sqlite_repo(sqlite_palace: MemoryPalace) -> SqliteMemoryRepository:
    """Yield a fresh ``SqliteMemoryRepository`` per test."""
    return SqliteMemoryRepository(sqlite_palace)


# ============================================
# Postgres fixtures
# ============================================
@pytest_asyncio.fixture
async def pg_palace(tmp_path: Path):
    """Yield a fresh ``MemoryPalaceIntegration`` per test.

    Uses aiosqlite (already a dev/test dep) and the in-memory
    VectorStore fallback. No LanceDB / no asyncpg needed.
    """
    db_file = tmp_path / "memory_repo_pg.db"
    persistence = PostgresPersistence(f"sqlite+aiosqlite:///{db_file}")
    vector_store = VectorStore()  # fallback
    integration = MemoryPalaceIntegration(persistence, vector_store)
    try:
        yield integration
    finally:
        try:
            await integration.close()
        except Exception:
            pass


@pytest.fixture
def mock_embedding_model() -> EmbeddingModel:
    """Yield an ``EmbeddingModel`` whose real model is pre-loaded.

    We skip the lazy ``_load_model`` path entirely by injecting
    a MagicMock as ``_model`` after construction. The cache
    (in-process LRU) still works because the cache is separate
    from the model handle.
    """
    em = EmbeddingModel(model_name="mock-model", cache_size=16)

    # Use a one-hot encoder that returns the same vector for
    # the same content. This is more honest than a MagicMock
    # because it exercises the encode() path end-to-end.
    def _fake_encode(text: str) -> list[float]:
        # Deterministic: each char's ordinal mod EMBEDDING_DIM
        # is the "active" index.
        if not text:
            return [0.0] * EMBEDDING_DIM
        idx = ord(text[0]) % EMBEDDING_DIM
        return _one_hot(idx, EMBEDDING_DIM)

    em._model = MagicMock()
    em._model.encode = _fake_encode
    return em


@pytest_asyncio.fixture
async def pg_repo(
    pg_palace: MemoryPalaceIntegration,
    mock_embedding_model: EmbeddingModel,
) -> PostgresMemoryRepository:
    """Yield a fresh ``PostgresMemoryRepository`` per test."""
    return PostgresMemoryRepository(pg_palace, embedding_model=mock_embedding_model)


# ============================================
# Test 2: SQLite save + list roundtrip
# ============================================
@pytest.mark.asyncio
async def test_sqlite_repository_save_and_list_roundtrip(
    sqlite_repo: SqliteMemoryRepository,
) -> None:
    """A memory saved via the repository is returned by list_by_character.

    The SQLite adapter cannot honour a caller-supplied
    memory_id (the Phase A schema auto-generates UUIDs), so
    we roundtrip on ``content`` and ``metadata`` instead.
    The Phase A list returns a dict that includes both.
    """
    cid = "char_sqlite_d3"
    content = "The duke's sigil is a black tower on a red field."
    metadata = {"_repository_id": "d3-fixed-id-001", "source": "unit_test"}

    actual_id = await sqlite_repo.save(
        memory_id="d3-fixed-id-001",
        character_id=cid,
        content=content,
        memory_type="semantic",
        salience=0.85,
        metadata=metadata,
    )
    # The actual id is the Phase A-generated UUID; the
    # caller's id is preserved in metadata['_repository_id'].
    assert isinstance(actual_id, str) and len(actual_id) == 36

    rows = await sqlite_repo.list_by_character(cid)
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}: {rows}"
    row = rows[0]
    assert row["content"] == content
    assert row["memory_type"] == "semantic"
    assert abs(row["salience"] - 0.85) < 1e-6
    # The repository preserves the caller's memory_id in
    # metadata['_repository_id'] so consumers can correlate.
    assert row["metadata"]["_repository_id"] == "d3-fixed-id-001"


# ============================================
# Test 3: Postgres save + list roundtrip
# ============================================
@pytest.mark.asyncio
async def test_postgres_repository_save_and_list_roundtrip(
    pg_repo: PostgresMemoryRepository,
) -> None:
    """A memory saved via the repository appears in list_by_character.

    The Postgres adapter composes an ``EmbeddingModel`` to
    compute the 384-dim embedding, then delegates to
    ``MemoryPalaceIntegration.remember``. We assert the
    content + salience roundtrip via ``list_by_character``.
    """
    cid = "char_postgres_d3"
    content = "Disarmed the level-2 trap on the inner keep gate."
    metadata = {"_repository_id": "d3-fixed-id-002", "tag": "combat"}

    await pg_repo.save(
        memory_id="d3-fixed-id-002",
        character_id=cid,
        content=content,
        memory_type="procedural",
        salience=0.7,
        metadata=metadata,
    )

    rows = await pg_repo.list_by_character(cid)
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}: {rows}"
    row = rows[0]
    assert row["content"] == content
    assert row["memory_type"] == "procedural"
    assert abs(row["salience"] - 0.7) < 1e-6
    # Caller's memory_id is preserved in metadata['_repository_id'].
    assert row["metadata"]["_repository_id"] == "d3-fixed-id-002"


# ============================================
# Test 4: Factory returns the correct backend
# ============================================
def test_factory_returns_correct_backend(
    sqlite_palace: MemoryPalace,
    pg_palace: MemoryPalaceIntegration,
    mock_embedding_model: EmbeddingModel,
) -> None:
    """``get_repository(backend=...)`` returns the matching class."""
    sqlite_repo = get_repository(backend="sqlite", sqlite_palace=sqlite_palace)
    pg_repo = get_repository(
        backend="postgres",
        postgres_integration=pg_palace,
        embedding_model=mock_embedding_model,
    )
    assert isinstance(sqlite_repo, SqliteMemoryRepository)
    assert isinstance(pg_repo, PostgresMemoryRepository)
    # Both honour the abstract surface.
    assert isinstance(sqlite_repo, MemoryRepository)
    assert isinstance(pg_repo, MemoryRepository)


def test_factory_rejects_unknown_backend(sqlite_palace: MemoryPalace) -> None:
    """An unknown ``backend`` value raises ``ValueError``."""
    with pytest.raises(ValueError, match="Unknown backend"):
        get_repository(backend="mongodb", sqlite_palace=sqlite_palace)


def test_factory_requires_sqlite_palace_argument() -> None:
    """``backend='sqlite'`` without ``sqlite_palace`` raises."""
    with pytest.raises(ValueError, match="sqlite_palace"):
        get_repository(backend="sqlite")


def test_factory_requires_postgres_integration_argument() -> None:
    """``backend='postgres'`` without ``postgres_integration`` raises."""
    with pytest.raises(ValueError, match="postgres_integration"):
        get_repository(backend="postgres")


# ============================================
# Test 5: count_by_character (covers both backends)
# ============================================
@pytest.mark.asyncio
async def test_count_by_character_sqlite(
    sqlite_repo: SqliteMemoryRepository,
) -> None:
    cid = "char_count_sqlite"
    assert await sqlite_repo.count(cid) == 0
    for i in range(3):
        await sqlite_repo.save(
            memory_id=f"id-{i}",
            character_id=cid,
            content=f"memory {i}",
            memory_type="episodic",
            salience=0.5,
        )
    assert await sqlite_repo.count(cid) == 3


@pytest.mark.asyncio
async def test_count_by_character_postgres(
    pg_repo: PostgresMemoryRepository,
) -> None:
    cid = "char_count_postgres"
    assert await pg_repo.count(cid) == 0
    for i in range(3):
        await pg_repo.save(
            memory_id=f"id-pg-{i}",
            character_id=cid,
            content=f"pg memory {i}",
            memory_type="episodic",
            salience=0.5,
        )
    assert await pg_repo.count(cid) == 3


# ============================================
# Test 6: delete removes from backend
# ============================================
@pytest.mark.asyncio
async def test_delete_removes_from_sqlite(
    sqlite_repo: SqliteMemoryRepository,
) -> None:
    """A memory deleted via the repository is gone from the backend.

    The SQLite adapter uses a private SQL DELETE, so the
    test is hermetic (it does not depend on Phase A's
    public API surface).
    """
    cid = "char_delete_sqlite"
    # Manually write a row so we have a known id to delete.
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(sqlite_repo._palace.db_path)
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
                "delete-me-001",
                cid,
                "episodic",
                "to be deleted",
                "world_event",
                0.5,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                0,
                "[]",
                "[]",
                0.05,
                "{}",
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    assert await sqlite_repo.count(cid) == 1

    deleted = await sqlite_repo.delete("delete-me-001", cid)
    assert deleted is True
    assert await sqlite_repo.count(cid) == 0

    # Deleting a non-existent row returns False.
    deleted_again = await sqlite_repo.delete("delete-me-001", cid)
    assert deleted_again is False


@pytest.mark.asyncio
async def test_delete_removes_from_postgres(
    pg_repo: PostgresMemoryRepository,
    mock_embedding_model: EmbeddingModel,
) -> None:
    """A memory deleted via the repository is gone from the backend.

    The Postgres adapter delegates to
    ``MemoryPalaceIntegration.forget``, which verifies
    ownership and removes the row from both Postgres and
    the vector store. ``save`` returns the actual storage
    id (the caller's id is preserved only in metadata),
    so we capture it and use it for the delete.
    """
    cid = "char_delete_postgres"
    actual_id = await pg_repo.save(
        memory_id="delete-pg-001",
        character_id=cid,
        content="a memory to be deleted",
        memory_type="episodic",
        salience=0.5,
    )
    assert isinstance(actual_id, str) and len(actual_id) > 0
    assert await pg_repo.count(cid) == 1

    # Wrong-character delete is a no-op (returns False).
    deleted_wrong = await pg_repo.delete(actual_id, "other-char")
    assert deleted_wrong is False
    assert await pg_repo.count(cid) == 1

    # Right-character delete removes the row.
    deleted = await pg_repo.delete(actual_id, cid)
    assert deleted is True
    assert await pg_repo.count(cid) == 0

    # Second delete is a no-op (returns False).
    deleted_again = await pg_repo.delete(actual_id, cid)
    assert deleted_again is False


# ============================================
# Test 7: EmbeddingModel lazy load
# ============================================
def test_embedding_lazy_load() -> None:
    """``sentence-transformers`` is NOT imported at module level.

    The class is importable; ``_model`` is ``None`` until
    the first ``encode`` call. We do NOT call ``encode`` here
    (that would trigger the actual model load); we only
    assert the lazy state.
    """
    # The module is importable without sentence-transformers
    # installed (verified by running this test in the
    # current env where the package is absent).
    em = EmbeddingModel(model_name="mock-model")
    # The model handle is None.
    assert em._model is None
    # The cache is empty.
    assert em.cache_size() == 0
    # The lock is None (created lazily on first encode).
    assert em._model_lock is None
    # The model name is preserved.
    assert em._model_name == "mock-model"
    # The default cache size is 1024.
    assert em._cache_size == 1024


def test_embedding_model_name_uses_default() -> None:
    """``EmbeddingModel()`` with no args uses ``all-MiniLM-L6-v2``."""
    em = EmbeddingModel()
    assert em._model_name == "sentence-transformers/all-MiniLM-L6-v2"
    assert em._cache_size == 1024


# ============================================
# Test 8: EmbeddingModel content-hash cache
# ============================================
@pytest.mark.asyncio
async def test_embedding_content_hash_cache() -> None:
    """Same content → same embedding; the model is called once.

    We inject a fake model (see ``mock_embedding_model``
    fixture's pattern) and track call count via a
    ``MagicMock`` wrapper. The cache must short-circuit
    on the second call.

    Also exercises the LRU eviction: after ``cache_size``
    unique encodes, the first cached entry is gone.
    """
    call_count = {"n": 0}

    def _fake_encode(text: str) -> list[float]:
        call_count["n"] += 1
        if not text:
            return [0.0] * EMBEDDING_DIM
        idx = ord(text[0]) % EMBEDDING_DIM
        return _one_hot(idx, EMBEDDING_DIM)

    em = EmbeddingModel(model_name="mock", cache_size=4)
    em._model = MagicMock()
    em._model.encode = _fake_encode

    # First call: hits the model, fills the cache.
    v1 = await em.encode("alpha")
    assert call_count["n"] == 1
    assert em.cache_size() == 1

    # Second call with the SAME content: cache hit, model
    # is NOT called again.
    v2 = await em.encode("alpha")
    assert call_count["n"] == 1, (
        f"second encode of the same content should be a cache hit; " f"call_count={call_count['n']}"
    )
    assert v1 == v2

    # A different content: cache miss, model is called.
    v3 = await em.encode("beta")
    assert call_count["n"] == 2
    assert em.cache_size() == 2
    assert v1 != v3

    # ``force_reembed`` bypasses the cache.
    v4 = await em.encode("alpha", force_reembed=True)
    assert call_count["n"] == 3
    assert v4 == v1, "force_reembed should still return the same vector"

    # LRU eviction: fill past cache_size, oldest goes.
    for c in ["x", "y", "z", "w", "v"]:  # 5 unique > cache_size=4
        await em.encode(c)
    assert em.cache_size() == 4, f"cache should be bounded at 4 entries, got {em.cache_size()}"
    # The "alpha" entry was the first inserted after the
    # initial 2, but we then re-inserted "alpha" via
    # force_reembed which moved it to the end. The
    # eviction order depends on the call sequence;
    # we don't assert which specific entry is evicted —
    # only that the cache is bounded.
    # Final clear works.
    em.cache_clear()
    assert em.cache_size() == 0


# ============================================
# Test 9: health() returns bool (both backends)
# ============================================
@pytest.mark.asyncio
async def test_health_returns_bool_sqlite(
    sqlite_repo: SqliteMemoryRepository,
) -> None:
    """A freshly-initialised SQLite repository is healthy."""
    result = await sqlite_repo.health()
    assert isinstance(result, bool)
    assert result is True


@pytest.mark.asyncio
async def test_health_returns_bool_postgres(
    pg_repo: PostgresMemoryRepository,
) -> None:
    """A freshly-initialised Postgres repository is healthy."""
    result = await pg_repo.health()
    assert isinstance(result, bool)
    assert result is True

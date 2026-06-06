"""
Tests for backend/memory_palace_integration.py
==============================================

Phase C2 — Memory Palace Phase A integration tests.

Covers the 10 cases from the parent task brief:

1. test_remember_returns_memory_id                — id is a valid uuid4 string
2. test_remember_persists_to_postgres             — count() reflects the new memory
3. test_remember_indexes_in_vector_store          — vector_store.count() increments
4. test_recall_returns_top_k_by_similarity        — orthogonal embeddings, top hit == query
5. test_recall_filters_by_character_id            — char_A cannot see char_B's memories
6. test_recall_filters_by_memory_type             — episodic vs semantic filter
7. test_recall_filters_by_min_salience            — low vs high salience
8. test_forget_removes_from_both_backends         — gone from PG count AND vector_store
9. test_forget_rejects_other_characters_memory    — char_A cannot delete char_B's memory
10. test_health_reports_both_backends             — dict with both booleans

Each test gets a FRESH ``MemoryPalaceIntegration`` wired to a fresh
aiosqlite PG + fallback VectorStore. We do NOT share state between
tests — this prevents order-dependence and lets pytest-xdist run
them in parallel if ever desired.

We mirror the conventions of ``test_persistence_pg.py`` and
``test_vector_store.py``: PRAGMA foreign_keys=ON is enabled on the
aiosqlite connection (in case future columns gain FK constraints;
currently ``memories.id`` is a string PK with no FK to ``characters``
because the integration is a Phase-A composition, not a relational
schema migration).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure repo root is on sys.path (mirrors existing test convention).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.memory_palace_integration import (  # noqa: E402
    MemoryPalaceIntegration,
    SalienceOutOfRangeError,
)
from backend.persistence_pg import PostgresPersistence  # noqa: E402
from backend.vector_store import EMBEDDING_DIM, VectorStore  # noqa: E402


# ============================================
# Helpers
# ============================================
def _one_hot(index: int, dim: int = EMBEDDING_DIM) -> list[float]:
    """Return a dim-length vector with a single 1.0 at ``index``.

    These give us **exact** cosine similarities of 0.0 or 1.0:
    ``_cos(orthogonal unit vectors) == 0`` and
    ``_cos(same unit vector) == 1``. That makes the "top hit is
    the same one" assertion deterministic.
    """
    v = [0.0] * dim
    v[index] = 1.0
    return v


# ============================================
# Fixtures
# ============================================
@pytest_asyncio.fixture
async def palace(tmp_path: Path):
    """Yield a fresh ``MemoryPalaceIntegration`` per test.

    Both backends are scratch instances:
    * PostgresPersistence → aiosqlite file under ``tmp_path`` (cleaned
      up automatically by pytest).
    * VectorStore → in-process fallback (no LanceDB required; the
      env lacks it, and the fallback path is fully supported).
    """
    db_file = tmp_path / "integration_test.db"
    persistence = PostgresPersistence(f"sqlite+aiosqlite:///{db_file}")
    vector_store = VectorStore()  # uses fallback
    integration = MemoryPalaceIntegration(persistence, vector_store)
    try:
        yield integration
    finally:
        # Defensive: even if a test crashed mid-write, make sure
        # the engine is disposed so the aiosqlite file handle is
        # released. pytest will then remove tmp_path.
        try:
            await integration.close()
        except Exception:
            pass


# ============================================
# Tests
# ============================================
class TestRemember:
    """Tests 1-3: remember() — id format + dual-backend persistence."""

    @pytest.mark.asyncio
    async def test_remember_returns_memory_id(self, palace: MemoryPalaceIntegration) -> None:
        """A successful remember() returns a string that parses as a UUID4."""
        mem_id = await palace.remember(
            character_id="char_alice",
            content="Defeated the bandit captain.",
            embedding=_one_hot(0),
            memory_type="episodic",
            salience=0.7,
        )
        assert isinstance(mem_id, str)
        # Must be a valid UUID4 — this catches a class of bugs where
        # callers accidentally return an int or a row id from PG.
        parsed = uuid.UUID(mem_id)
        assert parsed.version == 4

    @pytest.mark.asyncio
    async def test_remember_persists_to_postgres(self, palace: MemoryPalaceIntegration) -> None:
        """After remember(), count() for the character returns 1."""
        assert await palace.count("char_alice") == 0
        await palace.remember(
            character_id="char_alice",
            content="Met the merchant.",
            embedding=_one_hot(1),
            memory_type="semantic",
            salience=0.4,
        )
        assert await palace.count("char_alice") == 1

    @pytest.mark.asyncio
    async def test_remember_indexes_in_vector_store(self, palace: MemoryPalaceIntegration) -> None:
        """After remember(), vector_store.count() increments by 1.

        We assert against the *raw* vector store (held in the
        integration) so we know the embedding was actually
        indexed and not just stashed in Postgres.
        """
        assert await palace._vector_store.count() == 0
        await palace.remember(
            character_id="char_alice",
            content="Visited the chapel.",
            embedding=_one_hot(2),
            memory_type="episodic",
            salience=0.6,
        )
        assert await palace._vector_store.count() == 1


class TestRecall:
    """Tests 4-7: recall() — ranking + filtering semantics."""

    @pytest.mark.asyncio
    async def test_recall_returns_top_k_by_similarity(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """With 3 orthogonal embeddings, querying with one of them
        returns that memory as the top hit (cosine sim == 1.0)."""
        # Three memories, each on a unique axis. The axes are
        # pairwise orthogonal so the top hit must be exact.
        m_a = await palace.remember(
            character_id="char_alice",
            content="memory A: chapel",
            embedding=_one_hot(10),
        )
        await palace.remember(
            character_id="char_alice",
            content="memory B: tavern",
            embedding=_one_hot(20),
        )
        await palace.remember(
            character_id="char_alice",
            content="memory C: forest",
            embedding=_one_hot(30),
        )
        # Query with the chapel vector → chapel should be the top hit.
        results = await palace.recall(
            character_id="char_alice",
            query_embedding=_one_hot(10),
            k=3,
        )
        assert len(results) >= 1
        assert results[0]["memory_id"] == m_a
        assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-9)
        # And the other two should be tied at exactly 0.0.
        sims = sorted(r["similarity"] for r in results)
        assert sims[0] == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.asyncio
    async def test_recall_filters_by_character_id(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """memories stored under char_B must not leak into char_A's recall."""
        # char_B has a memory that *should not* appear in char_A's
        # results, even though we query with an embedding close
        # (identical, in fact) to char_B's memory.
        await palace.remember(
            character_id="char_bob",
            content="bob's secret",
            embedding=_one_hot(5),
            salience=0.9,
        )
        await palace.remember(
            character_id="char_alice",
            content="alice's own memory",
            embedding=_one_hot(50),
            salience=0.9,
        )
        # Query with bob's vector — char_B would get a perfect hit,
        # char_A must get only char_A's memory.
        results = await palace.recall(
            character_id="char_alice",
            query_embedding=_one_hot(5),
            k=10,
        )
        ids = {r["memory_id"] for r in results}
        # No bob content should appear.
        for r in results:
            assert r["memory_type"] in {"episodic", "semantic", "procedural"}
            # Each result's character_id isn't directly in the
            # return shape (per spec), but we can sanity-check
            # that we got exactly 1 result (alice's memory) by
            # checking there is no overlap with bob's data.
        # A more direct check: re-run as bob and verify the
        # perfect-hit is there.
        results_bob = await palace.recall(
            character_id="char_bob",
            query_embedding=_one_hot(5),
            k=10,
        )
        assert len(results_bob) == 1
        assert results_bob[0]["similarity"] == pytest.approx(1.0, abs=1e-9)
        # And for alice — bob's perfect-hit is filtered out, so
        # we get back at most alice's own memory (sim == 0.0
        # against bob's axis).
        assert all(r["similarity"] == pytest.approx(0.0, abs=1e-9) for r in results)

    @pytest.mark.asyncio
    async def test_recall_filters_by_memory_type(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """Filtering by memory_type restricts results to that type only."""
        # Two memories on the same axis but different types.
        # Querying on the same axis with type=episodic should
        # return ONLY the episodic one, not the semantic one.
        epi_id = await palace.remember(
            character_id="char_alice",
            content="episodic: saw the duke",
            embedding=_one_hot(7),
            memory_type="episodic",
            salience=0.5,
        )
        sem_id = await palace.remember(
            character_id="char_alice",
            content="semantic: duke's sigil is a black tower",
            embedding=_one_hot(7),
            memory_type="semantic",
            salience=0.5,
        )
        # No filter — both come back, in some order (score is
        # identical, so the relative order is the vector store's
        # internal order; we assert the SET).
        unfiltered = await palace.recall(
            character_id="char_alice",
            query_embedding=_one_hot(7),
            k=5,
        )
        unfiltered_ids = {r["memory_id"] for r in unfiltered}
        assert unfiltered_ids == {epi_id, sem_id}

        # With memory_type=episodic — only the episodic one.
        episodic = await palace.recall(
            character_id="char_alice",
            query_embedding=_one_hot(7),
            k=5,
            memory_type="episodic",
        )
        assert len(episodic) == 1
        assert episodic[0]["memory_id"] == epi_id
        assert episodic[0]["memory_type"] == "episodic"

        # With memory_type=semantic — only the semantic one.
        semantic = await palace.recall(
            character_id="char_alice",
            query_embedding=_one_hot(7),
            k=5,
            memory_type="semantic",
        )
        assert len(semantic) == 1
        assert semantic[0]["memory_type"] == "semantic"

    @pytest.mark.asyncio
    async def test_recall_filters_by_min_salience(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """min_salience excludes low-salience rows from results."""
        high_id = await palace.remember(
            character_id="char_alice",
            content="high salience",
            embedding=_one_hot(11),
            salience=0.9,
        )
        await palace.remember(
            character_id="char_alice",
            content="low salience",
            embedding=_one_hot(11),
            salience=0.1,
        )
        # With no salience floor — both.
        unfiltered = await palace.recall(
            character_id="char_alice",
            query_embedding=_one_hot(11),
            k=5,
        )
        assert len(unfiltered) == 2
        # With min_salience=0.5 — only the high-salience one.
        filtered = await palace.recall(
            character_id="char_alice",
            query_embedding=_one_hot(11),
            k=5,
            min_salience=0.5,
        )
        assert len(filtered) == 1
        assert filtered[0]["memory_id"] == high_id
        assert filtered[0]["salience"] == pytest.approx(0.9, abs=1e-9)


class TestForget:
    """Tests 8-9: forget() — both-backend delete + ownership check."""

    @pytest.mark.asyncio
    async def test_forget_removes_from_both_backends(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """forget() removes the row from PG AND the embedding from VS."""
        mem_id = await palace.remember(
            character_id="char_alice",
            content="ephemeral",
            embedding=_one_hot(99),
        )
        # Pre-condition: both backends have it.
        assert await palace.count("char_alice") == 1
        assert await palace._vector_store.count() == 1

        # Act.
        deleted = await palace.forget("char_alice", mem_id)

        # Post-condition: both backends are clean.
        assert deleted is True
        assert await palace.count("char_alice") == 0
        assert await palace._vector_store.count() == 0

    @pytest.mark.asyncio
    async def test_forget_rejects_other_characters_memory(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """char_A cannot delete char_B's memory — must return False."""
        bob_mem = await palace.remember(
            character_id="char_bob",
            content="bob's private memory",
            embedding=_one_hot(101),
        )
        # char_A attempts to delete bob's memory.
        deleted = await palace.forget("char_alice", bob_mem)

        # Must be False, AND bob's memory must still be there.
        assert deleted is False
        assert await palace.count("char_bob") == 1
        # Vector store should still have it too (forget should
        # not have touched it on a rejected delete).
        assert await palace._vector_store.count() == 1


class TestHealth:
    """Test 10: health() reports both backends."""

    @pytest.mark.asyncio
    async def test_health_reports_both_backends(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """A healthy integration reports both backends True."""
        h = await palace.health()
        assert isinstance(h, dict)
        assert set(h.keys()) == {"postgres", "vector_store"}
        assert h["postgres"] is True
        assert h["vector_store"] is True


# ============================================
# Bonus: input-validation tests (cheap coverage
# that catches a class of regressions if a future
# refactor drops the guard).
# ============================================
class TestInputValidation:
    """Sanity guards: bad input should raise, not silently coerce."""

    @pytest.mark.asyncio
    async def test_salience_out_of_range_raises(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """salience > 1.0 raises SalienceOutOfRangeError."""
        with pytest.raises(SalienceOutOfRangeError):
            await palace.remember(
                character_id="char_alice",
                content="bad salience",
                embedding=_one_hot(0),
                salience=1.5,
            )

    @pytest.mark.asyncio
    async def test_wrong_embedding_dim_raises(
        self,
        palace: MemoryPalaceIntegration,
    ) -> None:
        """Wrong-dim embedding raises ValueError BEFORE touching PG."""
        with pytest.raises(ValueError):
            await palace.remember(
                character_id="char_alice",
                content="bad dim",
                embedding=[0.0] * 128,  # 128 != 384
            )

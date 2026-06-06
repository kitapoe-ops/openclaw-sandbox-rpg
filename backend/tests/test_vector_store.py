"""
Unit tests for ``backend.vector_store.VectorStore`` — Phase B1.

These tests run against the **fallback** backend (the test env does
not have ``lancedb`` installed). One test (``test_fallback_when_lancedb_missing``)
specifically exercises the auto-detect path with a mocked import failure
to prove the adapter still works in either branch.

Test conventions
----------------
* pytest + pytest-asyncio (already in requirements.txt).
* Each test gets a fresh ``VectorStore`` instance — no shared state,
  no fixtures that mutate globals.
* We use isolated, deterministic unit vectors (one-hot in a 384-dim
  space) so cosine similarities are exact 0.0 or 1.0.
"""
from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch

import pytest

# Ensure repo root is on sys.path (mirrors test_db_race.py convention)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.vector_store import EMBEDDING_DIM, VectorStore  # noqa: E402


# ============================================
# Helpers
# ============================================
def _one_hot(index: int, dim: int = EMBEDDING_DIM) -> list[float]:
    """Return a dim-length vector with a single 1.0 at ``index``."""
    v = [0.0] * dim
    v[index] = 1.0
    return v


# ============================================
# Tests
# ============================================
class TestVectorStore:
    """Phase B1: 5 required tests + a couple of sanity checks."""

    @pytest.mark.asyncio
    async def test_add_and_count(self) -> None:
        """Adding two distinct memories increments the count to 2,
        and the same id twice (idempotent) leaves the count at 1."""
        vs = VectorStore()
        assert await vs.count() == 0
        await vs.add("m1", _one_hot(0), {"character_id": "alice"})
        assert await vs.count() == 1
        await vs.add("m2", _one_hot(1), {"character_id": "bob"})
        assert await vs.count() == 2
        # Re-adding m1 is an upsert — count stays at 2.
        await vs.add("m1", _one_hot(0), {"character_id": "alice"})
        assert await vs.count() == 2

    @pytest.mark.asyncio
    async def test_search_returns_top_k(self) -> None:
        """Three memories with distinct unit vectors; a query for
        index 7's direction must return m7 first with score 1.0,
        and the second result must have a smaller (still-defined) score."""
        vs = VectorStore()
        await vs.add("m1", _one_hot(1), {"character_id": "alice"})
        await vs.add("m7", _one_hot(7), {"character_id": "alice"})
        await vs.add("m3", _one_hot(3), {"character_id": "bob"})

        results = await vs.search(_one_hot(7), k=2)
        assert len(results) == 2
        # The exact-match row should be ranked first.
        assert results[0]["memory_id"] == "m7"
        # Exact cosine of identical unit vectors is 1.0.
        assert results[0]["score"] == pytest.approx(1.0)
        # Score of the runner-up is strictly less than the winner.
        assert results[1]["score"] < results[0]["score"]
        # Each result carries the metadata we stored.
        assert results[0]["metadata"]["character_id"] == "alice"

    @pytest.mark.asyncio
    async def test_search_with_filter(self) -> None:
        """A filter on ``character_id`` restricts the candidate set
        to matching rows only — rows that don't match must not appear
        in the top-k even if they would be the best cosine match."""
        vs = VectorStore()
        # Insert the *best* vector under character_id=bob, but query
        # filtered to character_id=alice. Bob's row must be excluded.
        await vs.add("bob-best", _one_hot(42), {"character_id": "bob"})
        await vs.add("alice-1", _one_hot(1), {"character_id": "alice"})
        await vs.add("alice-2", _one_hot(2), {"character_id": "alice"})

        results = await vs.search(
            _one_hot(42),
            k=5,
            filter={"character_id": "alice"},
        )
        ids = [r["memory_id"] for r in results]
        assert "bob-best" not in ids
        assert "alice-1" in ids
        assert "alice-2" in ids

    @pytest.mark.asyncio
    async def test_delete_removes_record(self) -> None:
        """After delete, count drops by one and search no longer
        returns the deleted memory_id."""
        vs = VectorStore()
        await vs.add("m1", _one_hot(0), {"character_id": "alice"})
        await vs.add("m2", _one_hot(1), {"character_id": "alice"})
        assert await vs.count() == 2

        await vs.delete("m1")
        assert await vs.count() == 1

        results = await vs.search(_one_hot(0), k=5)
        ids = [r["memory_id"] for r in results]
        assert "m1" not in ids
        # m2 still present.
        assert "m2" in ids

        # Deleting a non-existent id is a no-op, not an error.
        await vs.delete("does-not-exist")
        assert await vs.count() == 1

    @pytest.mark.asyncio
    async def test_fallback_when_lancedb_missing(self) -> None:
        """Force the import-failure branch and prove the adapter
        still serves add/search/delete/count/health correctly.

        Strategy: import the module fresh, then patch
        ``backend.vector_store._detect_lancedb`` to return None
        *before* ``VectorStore.__init__`` runs.
        """
        # Re-import the module so we get a clean reference to the
        # private detector. (We don't reset global state — the test
        # is read-only on the class itself.)
        from backend import vector_store as vs_mod

        # Sanity: in this env lancedb isn't installed, so the
        # default is already fallback. The point of the patch is
        # to prove *the contract* survives an import failure,
        # regardless of the actual env state.
        with patch.object(vs_mod, "_detect_lancedb", return_value=None):
            vs = VectorStore()
            assert vs.backend_name == "fallback"

            await vs.add("solo", _one_hot(5), {"character_id": "carol"})
            assert await vs.count() == 1

            results = await vs.search(_one_hot(5), k=1)
            assert len(results) == 1
            assert results[0]["memory_id"] == "solo"
            assert results[0]["score"] == pytest.approx(1.0)

            await vs.delete("solo")
            assert await vs.count() == 0

            assert await vs.health() is True


# ============================================
# Bonus sanity checks (still pass under either backend)
# ============================================
class TestVectorStoreContract:
    """Lightweight contract checks the Memory Palace relies on."""

    @pytest.mark.asyncio
    async def test_embedding_dim_constant_matches_constructor_contract(self) -> None:
        """A wrong-dim embedding must raise ValueError, not silently truncate."""
        vs = VectorStore()
        with pytest.raises(ValueError):
            await vs.add("bad", [0.0] * 100, {"character_id": "x"})
        with pytest.raises(ValueError):
            await vs.search([0.0] * 100, k=1)

    @pytest.mark.asyncio
    async def test_health_is_bool(self) -> None:
        vs = VectorStore()
        result = await vs.health()
        assert isinstance(result, bool)
        assert result is True

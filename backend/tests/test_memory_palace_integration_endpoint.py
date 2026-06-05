"""
Tests for backend/memory_palace_integration_endpoint.py
=======================================================

Phase C2 — FastAPI endpoint coverage for the integration layer.

These tests use ``httpx.AsyncClient`` + ``ASGITransport`` so we
hit the router in-process without spinning up uvicorn. The same
pattern was used by Phase B2's scheduler endpoint test.

The 5 required cases from the parent task brief:

1. test_remember_endpoint_returns_memory_id    — 200 + valid uuid4
2. test_recall_endpoint_returns_results        — 200 + non-empty list
3. test_forget_endpoint_returns_success         — 200 + deleted=True
4. test_recall_filters_by_character_id         — char_B's data hidden from char_A
5. test_health_endpoint_returns_both_backends_status — dict shape

The integration singleton is replaced per-test via
:func:`set_integration` so we get a fresh, isolated
``MemoryPalaceIntegration`` (and a fresh aiosqlite file) for each
test, and we restore the previous singleton in teardown to avoid
order-dependence across test files.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure repo root on sys.path.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.memory_palace_integration import MemoryPalaceIntegration  # noqa: E402
from backend.memory_palace_integration_endpoint import (  # noqa: E402
    router as memory_router,
    set_integration,
)
from backend.persistence_pg import PostgresPersistence  # noqa: E402
from backend.vector_store import EMBEDDING_DIM, VectorStore  # noqa: E402


# ============================================
# Helpers
# ============================================
def _one_hot(index: int, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic unit vector (see unit tests for rationale)."""
    v = [0.0] * dim
    v[index] = 1.0
    return v


# ============================================
# Fixtures
# ============================================
@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Yield an ``AsyncClient`` bound to the router with a fresh
    :class:`MemoryPalaceIntegration` wired to a per-test aiosqlite
    file.

    The router is mounted on a throwaway ``FastAPI()`` instance (we
    do not depend on the production ``main:app`` because that
    would require the full lifespan / DB / demo-mode dance).
    """
    from fastapi import FastAPI

    db_file = tmp_path / "endpoint_test.db"
    persistence = PostgresPersistence(f"sqlite+aiosqlite:///{db_file}")
    vector_store = VectorStore()  # fallback
    integration = MemoryPalaceIntegration(persistence, vector_store)

    # Inject the singleton. Save the previous value (if any) so
    # we can restore it in teardown — this prevents one test
    # file from polluting another.
    prev = None
    import backend.memory_palace_integration_endpoint as ep_mod
    prev = ep_mod._integration
    set_integration(integration)

    app = FastAPI()
    app.include_router(memory_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        try:
            yield ac
        finally:
            # Teardown: close the engine, clear the singleton,
            # restore whatever was there before this test.
            try:
                await integration.close()
            except Exception:
                pass
            set_integration(prev)


# ============================================
# Tests
# ============================================
class TestRememberEndpoint:
    @pytest.mark.asyncio
    async def test_remember_endpoint_returns_memory_id(
        self, client: AsyncClient,
    ) -> None:
        """POST /memory/remember returns 200 with a uuid4 memory_id."""
        resp = await client.post(
            "/memory/remember",
            json={
                "character_id": "char_alice",
                "content": "Visited the chapel.",
                "embedding": _one_hot(0),
                "memory_type": "episodic",
                "salience": 0.6,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "memory_id" in body
        parsed = uuid.UUID(body["memory_id"])
        assert parsed.version == 4


class TestRecallEndpoint:
    @pytest.mark.asyncio
    async def test_recall_endpoint_returns_results(
        self, client: AsyncClient,
    ) -> None:
        """POST /memory/recall returns a list of result dicts."""
        # Seed two memories.
        await client.post(
            "/memory/remember",
            json={
                "character_id": "char_alice",
                "content": "mem A",
                "embedding": _one_hot(0),
            },
        )
        await client.post(
            "/memory/remember",
            json={
                "character_id": "char_alice",
                "content": "mem B",
                "embedding": _one_hot(10),
            },
        )
        # Query with the A vector.
        resp = await client.post(
            "/memory/recall",
            json={
                "character_id": "char_alice",
                "query_embedding": _one_hot(0),
                "k": 5,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "results" in body
        assert isinstance(body["results"], list)
        assert len(body["results"]) >= 1
        # Top hit must have all the spec'd keys.
        top = body["results"][0]
        for k in ("memory_id", "content", "memory_type", "salience", "similarity", "metadata"):
            assert k in top, f"missing {k!r} in result {top!r}"

    @pytest.mark.asyncio
    async def test_recall_filters_by_character_id(
        self, client: AsyncClient,
    ) -> None:
        """Recall as char_A does not return char_B's memories."""
        # char_B has a memory on axis 5.
        await client.post(
            "/memory/remember",
            json={
                "character_id": "char_bob",
                "content": "bob's secret",
                "embedding": _one_hot(5),
                "salience": 0.9,
            },
        )
        # char_A has a memory on a different axis.
        await client.post(
            "/memory/remember",
            json={
                "character_id": "char_alice",
                "content": "alice's memory",
                "embedding": _one_hot(50),
                "salience": 0.9,
            },
        )
        # Query as char_A with bob's axis — must NOT surface bob's
        # content (or memory_id).
        resp = await client.post(
            "/memory/recall",
            json={
                "character_id": "char_alice",
                "query_embedding": _one_hot(5),
                "k": 10,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # alice's memory comes back (sim == 0.0 against axis 5);
        # bob's memory is filtered out.
        for r in body["results"]:
            assert r["content"] == "alice's memory"


class TestForgetEndpoint:
    @pytest.mark.asyncio
    async def test_forget_endpoint_returns_success(
        self, client: AsyncClient,
    ) -> None:
        """DELETE /memory/{char}/{mem} returns 200 with deleted=True."""
        # Seed.
        r = await client.post(
            "/memory/remember",
            json={
                "character_id": "char_alice",
                "content": "ephemeral",
                "embedding": _one_hot(0),
            },
        )
        assert r.status_code == 200
        memory_id = r.json()["memory_id"]
        # Forget.
        d = await client.delete(f"/memory/char_alice/{memory_id}")
        assert d.status_code == 200, d.text
        body = d.json()
        assert body["deleted"] is True
        assert body["character_id"] == "char_alice"
        assert body["memory_id"] == memory_id

    @pytest.mark.asyncio
    async def test_forget_endpoint_404_on_wrong_owner(
        self, client: AsyncClient,
    ) -> None:
        """Forgetting another character's memory returns 404."""
        r = await client.post(
            "/memory/remember",
            json={
                "character_id": "char_bob",
                "content": "bob's private",
                "embedding": _one_hot(0),
            },
        )
        bob_mem = r.json()["memory_id"]
        # char_A tries to delete bob's memory.
        d = await client.delete(f"/memory/char_alice/{bob_mem}")
        assert d.status_code == 404
        assert "not found" in d.json()["detail"].lower()


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_endpoint_returns_both_backends_status(
        self, client: AsyncClient,
    ) -> None:
        """GET /memory/health returns 200 with both booleans True."""
        resp = await client.get("/memory/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == {"postgres", "vector_store"}
        assert body["postgres"] is True
        assert body["vector_store"] is True

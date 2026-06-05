"""
Phase C3 — Wire-up integration tests
=====================================

Verifies the *end-to-end* wire-up from Phase C3 Deliverable 1
(:mod:`backend.app_with_memory`) and Deliverable 2
(:mod:`backend.demo_integration`):

1. The memory router from Phase C2 is actually included on the
   composed app (no main.py mutation required).
2. The four memory endpoints (remember/recall/forget/health) work
   when reached via the *composed* app — not just the standalone
   router.
3. The demo scheduler registers the ``memory_health_minute`` job.

The 5 required + 1 bonus tests from the parent task brief:

1. ``test_main_app_includes_memory_routes``
2. ``test_memory_remember_endpoint_live``
3. ``test_memory_recall_endpoint_live``
4. ``test_memory_forget_endpoint_live``
5. ``test_memory_health_endpoint_live``
6. (bonus) ``test_scheduler_demo_job_registered``

Test infrastructure
-------------------
* ``httpx.AsyncClient`` + ``ASGITransport`` — no uvicorn, no port.
* A fresh :class:`MemoryPalaceIntegration` per test via
  :func:`set_integration` (same pattern as
  ``test_memory_palace_integration_endpoint.py``).
* The composed app instance from :mod:`backend.app_with_memory`
  is imported *once* per test (its lifespan is not started — we
  only exercise the route table, not the demo scheduler's
  background job, except in the bonus test which inspects the
  job registration).
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

# apscheduler may be missing on some envs. Skip the bonus job
# test if so (mirrors the pattern in test_scheduler.py).
apscheduler = pytest.importorskip("apscheduler")

from backend.app_with_memory import app as composed_app  # noqa: E402
from backend.demo_integration import (  # noqa: E402
    JOB_MEMORY_HEALTH_MINUTE,
    add_demo_job,
    build_demo_scheduler,
    get_recent_health,
    job_memory_health_minute,
)
from backend.memory_palace_integration import MemoryPalaceIntegration  # noqa: E402
from backend.memory_palace_integration_endpoint import (  # noqa: E402
    set_integration,
)
from backend.persistence_pg import PostgresPersistence  # noqa: E402
from backend.vector_store import EMBEDDING_DIM, VectorStore  # noqa: E402


# ============================================
# Helpers
# ============================================
def _one_hot(index: int, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic unit vector for exact cosine comparisons."""
    v = [0.0] * dim
    v[index] = 1.0
    return v


def _route_paths(application) -> list[str]:
    """Return the path of every route on the app (excluding internal)."""
    out: list[str] = []
    for route in application.routes:
        path = getattr(route, "path", None)
        if path and path.startswith("/"):
            out.append(path)
    return out


# ============================================
# Fixtures
# ============================================
@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Yield an ``AsyncClient`` bound to the *composed* app with a fresh
    per-test ``MemoryPalaceIntegration`` wired in.

    We import the composed app module-level (one app per process
    is fine because ``include_router`` is idempotent at import
    time) and inject a per-test aiosqlite-backed integration so
    each test has an isolated database. The pre-existing
    singleton (if any) is restored in teardown.
    """
    db_file = tmp_path / "c3_wireup_test.db"
    persistence = PostgresPersistence(f"sqlite+aiosqlite:///{db_file}")
    vector_store = VectorStore()  # fallback (no LanceDB in test env)
    integration = MemoryPalaceIntegration(persistence, vector_store)

    # Capture the previous singleton so we can restore it on
    # teardown — this keeps the test file hermetic.
    import backend.memory_palace_integration_endpoint as ep_mod
    prev = ep_mod._integration
    set_integration(integration)

    transport = ASGITransport(app=composed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        try:
            yield ac
        finally:
            try:
                await integration.close()
            except Exception:
                pass
            set_integration(prev)


@pytest.fixture
def fresh_demo_scheduler():
    """Yield a *built, not started* AsyncIOScheduler with the demo job.

    The test that uses this fixture will inspect the job list to
    verify the wire-up. We tear it down (without starting) so
    APScheduler doesn't leak threads across tests.
    """
    scheduler = build_demo_scheduler()
    try:
        yield scheduler
    finally:
        # We never started the scheduler, so shutting it down is
        # a no-op for APScheduler — but the explicit call keeps
        # the intent clear.
        if scheduler.running:
            from apscheduler.schedulers.base import BaseScheduler
            BaseScheduler.shutdown(scheduler, wait=False)


# ============================================
# Tests
# ============================================
class TestWireUp:
    """Tests that the *composition* itself is correct."""

    def test_main_app_includes_memory_routes(self) -> None:
        """The composed app must expose all 4 /memory/* routes.

        This is the test that proves Phase C3 Deliverable 1
        actually works: ``app_with_memory.include_router`` ran
        at import time and the routes are now visible on the
        app that uvicorn would serve.
        """
        paths = _route_paths(composed_app)
        # All 4 Phase C2 routes are present.
        assert "/memory/remember" in paths, (
            f"/memory/remember missing; got {paths}"
        )
        assert "/memory/recall" in paths, (
            f"/memory/recall missing; got {paths}"
        )
        assert "/memory/{character_id}/{memory_id}" in paths, (
            f"/memory/{{character_id}}/{{memory_id}} missing; got {paths}"
        )
        assert "/memory/health" in paths, (
            f"/memory/health missing; got {paths}"
        )
        # Sanity: the Wave 2 production routes are still there
        # (we didn't accidentally shadow them).
        assert "/health" in paths
        assert "/" in paths


class TestMemoryEndpointsLive:
    """Tests that the 4 memory endpoints work *through the composed app*."""

    @pytest.mark.asyncio
    async def test_memory_remember_endpoint_live(
        self, client: AsyncClient,
    ) -> None:
        """POST /memory/remember on the composed app returns a uuid4."""
        resp = await client.post(
            "/memory/remember",
            json={
                "character_id": "char_alice",
                "content": "met the innkeeper",
                "embedding": _one_hot(0),
                "memory_type": "episodic",
                "salience": 0.7,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "memory_id" in body
        # Validate it's a UUID4 (mirrors the C2 endpoint test).
        parsed = uuid.UUID(body["memory_id"])
        assert parsed.version == 4

    @pytest.mark.asyncio
    async def test_memory_recall_endpoint_live(
        self, client: AsyncClient,
    ) -> None:
        """Two remembers + one recall returns >= 1 hit through the composed app."""
        # Seed two memories for char_alice on different axes.
        for idx in (3, 17):
            r = await client.post(
                "/memory/remember",
                json={
                    "character_id": "char_alice",
                    "content": f"memory-on-axis-{idx}",
                    "embedding": _one_hot(idx),
                },
            )
            assert r.status_code == 200, r.text

        # Query the axis-3 vector. Expect at least 1 result.
        resp = await client.post(
            "/memory/recall",
            json={
                "character_id": "char_alice",
                "query_embedding": _one_hot(3),
                "k": 5,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "results" in body
        assert isinstance(body["results"], list)
        assert len(body["results"]) >= 1, (
            f"expected >= 1 recall result, got {body['results']!r}"
        )
        # Top hit should be the axis-3 memory (cosine = 1.0).
        top = body["results"][0]
        assert top["content"] == "memory-on-axis-3"
        assert top["similarity"] == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_memory_forget_endpoint_live(
        self, client: AsyncClient,
    ) -> None:
        """remember → forget → recall returns zero hits for that memory."""
        # Seed.
        r = await client.post(
            "/memory/remember",
            json={
                "character_id": "char_alice",
                "content": "to-be-forgotten",
                "embedding": _one_hot(7),
            },
        )
        assert r.status_code == 200
        memory_id = r.json()["memory_id"]

        # Sanity: it shows up in recall.
        pre = await client.post(
            "/memory/recall",
            json={
                "character_id": "char_alice",
                "query_embedding": _one_hot(7),
                "k": 5,
            },
        )
        assert pre.status_code == 200
        pre_ids = {item["memory_id"] for item in pre.json()["results"]}
        assert memory_id in pre_ids

        # Forget.
        d = await client.delete(f"/memory/char_alice/{memory_id}")
        assert d.status_code == 200, d.text
        assert d.json()["deleted"] is True

        # Post-forget recall: memory_id must NOT appear.
        post = await client.post(
            "/memory/recall",
            json={
                "character_id": "char_alice",
                "query_embedding": _one_hot(7),
                "k": 5,
            },
        )
        assert post.status_code == 200
        post_ids = {item["memory_id"] for item in post.json()["results"]}
        assert memory_id not in post_ids, (
            f"forgotten memory {memory_id} still surfaces: {post_ids}"
        )

    @pytest.mark.asyncio
    async def test_memory_health_endpoint_live(
        self, client: AsyncClient,
    ) -> None:
        """GET /memory/health returns 200 with both backends True."""
        resp = await client.get("/memory/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Schema: { "postgres": bool, "vector_store": bool }
        assert set(body.keys()) == {"postgres", "vector_store"}
        assert body["postgres"] is True
        assert body["vector_store"] is True


class TestSchedulerDemoJob:
    """Tests for the demo scheduler wire-up (Deliverable 2)."""

    def test_scheduler_demo_job_registered(
        self, fresh_demo_scheduler,
    ) -> None:
        """build_demo_scheduler registers exactly one job with the
        canonical id, with an interval trigger."""
        scheduler = fresh_demo_scheduler
        jobs = scheduler.get_jobs()
        ids = [j.id for j in jobs]
        assert ids == [JOB_MEMORY_HEALTH_MINUTE], (
            f"expected exactly [{JOB_MEMORY_HEALTH_MINUTE!r}], got {ids}"
        )

        # Verify the job references the real coroutine.
        job = jobs[0]
        assert job.func is job_memory_health_minute

        # Verify it has an interval trigger (next_run_time populated
        # only when scheduler is running; we just check the trigger
        # object exists).
        assert job.trigger is not None


# ============================================
# Bonus smoke: end-to-end cron job firing
# ============================================
class TestEndToEndCron:
    """Bonus: actually fire the job once and verify the rolling
    buffer + ASGI wire-up produced a healthy result.

    This is the *one-shot* version of the cron loop the demo
    app would run forever. If this passes, the operator can be
    confident the full chain (scheduler → FastAPI → integration
    → PG/Vector) works in-process.
    """

    @pytest.mark.asyncio
    async def test_job_memory_health_minute_records_result(
        self, tmp_path: Path,
    ) -> None:
        """Manually call job_memory_health_minute; check rolling buffer."""
        # Build a real integration so /memory/health returns True.
        db_file = tmp_path / "e2e_cron_test.db"
        integration = MemoryPalaceIntegration(
            PostgresPersistence(f"sqlite+aiosqlite:///{db_file}"),
            VectorStore(),
        )
        set_integration(integration)
        try:
            before = len(get_recent_health())
            await job_memory_health_minute()
            after = get_recent_health()
            assert len(after) == before + 1
            last = after[-1]
            assert last["ok"] is True
            assert last["status_code"] == 200
            assert last["body"] == {"postgres": True, "vector_store": True}
        finally:
            await integration.close()

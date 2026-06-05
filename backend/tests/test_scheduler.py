"""
Tests for backend.scheduler (Phase B2 — APScheduler cron backbone).

If `apscheduler` is not installed, every test is skipped (per task spec:
"do NOT fail"). Otherwise we assert:

  1. build_scheduler() registers exactly 3 jobs with the expected IDs
  2. The scheduler is NOT started at build time
  3. The 3 job functions are coroutine functions (async def)
  4. create_app_with_scheduler() returns a FastAPI app whose lifespan
     actually starts and stops the scheduler (verified via httpx ASGI
     transport)
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

# Skip the entire module if apscheduler is not installed.
apscheduler = pytest.importorskip("apscheduler")

from fastapi import FastAPI  # noqa: E402

from backend.scheduler import (  # noqa: E402
    JOB_SENTINEL_DAILY,
    JOB_DASHBOARD_REFRESH,
    JOB_HEARTBEAT,
    build_scheduler,
    create_app_with_scheduler,
    job_dashboard_refresh,
    job_heartbeat,
    job_sentinel_daily,
)


# ============================================
# 1. build_scheduler registers exactly 3 jobs
# ============================================
def test_build_scheduler_has_3_jobs():
    sched = build_scheduler()

    job_ids = {job.id for job in sched.get_jobs()}

    assert job_ids == {JOB_SENTINEL_DAILY, JOB_DASHBOARD_REFRESH, JOB_HEARTBEAT}, (
        f"Expected the 3 cron job IDs, got {job_ids}"
    )

    # Sanity: each job has a cron trigger
    for job in sched.get_jobs():
        assert job.trigger is not None, f"Job {job.id} has no trigger"


# ============================================
# 2. Scheduler is NOT started at build time
# ============================================
def test_scheduler_not_started_at_build_time():
    sched = build_scheduler()

    assert sched.running is False, (
        "build_scheduler() must return a scheduler that has NOT been started; "
        "starting is the lifespan's job"
    )

    # And: get_jobs() is callable on a non-running scheduler
    jobs = sched.get_jobs()
    assert len(jobs) == 3


# ============================================
# 3. Job functions are async (coroutine functions)
# ============================================
def test_job_functions_are_async():
    for fn in (job_sentinel_daily, job_dashboard_refresh, job_heartbeat):
        assert inspect.iscoroutinefunction(fn), (
            f"{fn.__name__} must be `async def` (coroutine function), "
            f"got {type(fn).__name__}"
        )


# ============================================
# 4. create_app_with_scheduler lifespan starts/stops the scheduler
# ============================================
@pytest.mark.asyncio
async def test_create_app_with_scheduler_lifespan():
    """Drive the FastAPI lifespan directly and use httpx.ASGITransport
    for the in-app HTTP call.

    Note: httpx 0.28's `ASGITransport` does NOT trigger the ASGI lifespan
    protocol (no `lifespan=` parameter). We therefore invoke the lifespan
    ourselves: enter the `app.router.lifespan_context` context, do the
    HTTP call, then exit. This proves both startup (`scheduler.start()`)
    and shutdown (`scheduler.shutdown()`) actually happen.
    """
    from httpx import ASGITransport, AsyncClient

    app: FastAPI = create_app_with_scheduler()

    # Sanity checks before lifespan
    assert isinstance(app.state.scheduler.running, bool)
    assert app.state.scheduler.running is False

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        # Inside the lifespan: scheduler should be running
        assert app.state.scheduler.running is True, (
            "Lifespan startup should have called scheduler.start(); "
            f"running={app.state.scheduler.running}"
        )

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["running"] is True, (
                "Scheduler should be running while the app is up; "
                f"got body={body}"
            )
            assert {j["id"] for j in body["jobs"]} == {
                JOB_SENTINEL_DAILY,
                JOB_DASHBOARD_REFRESH,
                JOB_HEARTBEAT,
            }

    # After exiting the lifespan context, shutdown should have stopped it
    assert app.state.scheduler.running is False, (
        "Scheduler should be stopped after the lifespan context exits"
    )

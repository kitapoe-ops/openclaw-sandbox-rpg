"""
APScheduler Cron Backbone (Phase B2)
=====================================
FastAPI lifespan-integrated AsyncIOScheduler managing 3 background jobs:

  * `sentinel_daily`     — 09:00 Asia/Shanghai daily
  * `dashboard_refresh`  — every 4 hours on the hour
  * `heartbeat`          — every 10 minutes

Design notes
------------
* Uses APScheduler v3.x (`AsyncIOScheduler`) — NOT v4 (API churn).
* The scheduler is built with `build_scheduler()` (not started yet) so tests
  and `create_app_with_scheduler()` can register additional jobs or inspect
  state before the event loop starts.
* `create_app_with_scheduler()` is a *separate* factory from the Wave-2
  `create_app()` in `main.py`. Mount it via:

      uvicorn backend.scheduler:app

  or compose with other routers as needed. We deliberately do not mutate
  `main.py` — that file is owned by Wave 2.
* Job functions are async no-op stubs that just log. The next phase will
  wire them to real work (sentinel ETL, dashboard cache invalidation,
  heartbeat ping to the R1 audit client).
* If `apscheduler` is missing for any reason, importing this module still
  succeeds (we wrap the import); `build_scheduler()` and
  `create_app_with_scheduler()` then raise a clear error. The companion
  test file uses `pytest.importorskip("apscheduler")` so CI fails gracefully.

Hard-constraint compliance
--------------------------
This file does NOT import or modify:
    backend.character / scene / action / world / main / uvicorn_launcher
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.jobstores.memory import MemoryJobStore
    from apscheduler.executors.asyncio import AsyncIOExecutor
    _APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when dep missing
    AsyncIOScheduler = None  # type: ignore[assignment]
    CronTrigger = None  # type: ignore[assignment]
    MemoryJobStore = None  # type: ignore[assignment]
    AsyncIOExecutor = None  # type: ignore[assignment]
    _APSCHEDULER_AVAILABLE = False

from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ============================================
# Job ID constants — single source of truth
# ============================================
JOB_SENTINEL_DAILY = "sentinel_daily"
JOB_DASHBOARD_REFRESH = "dashboard_refresh"
JOB_HEARTBEAT = "heartbeat"

# Schedules (cron expressions) — kept here so tests can reference them.
SCHED_SENTINEL_DAILY = {"hour": 9, "minute": 0, "timezone": "Asia/Shanghai"}
SCHED_DASHBOARD_REFRESH = {"minute": 0}  # 0 */4 * * * — every 4h on the hour
SCHED_HEARTBEAT = {"minute": "*/10"}      # */10 * * * * — every 10 minutes


# ============================================
# Job stubs — async no-ops that just log
# ============================================
async def job_sentinel_daily() -> None:
    """09:00 Asia/Shanghai daily — run the Sentinel ETL pipeline.

    Wave B3 will wire this to the sentinel agent. For now: log only.
    """
    logger.info("[scheduler] sentinel_daily fired (stub)")


async def job_dashboard_refresh() -> None:
    """Every 4 hours on the hour — refresh dashboard caches.

    Wave B3 will invalidate Redis dashboard keys here. For now: log only.
    """
    logger.info("[scheduler] dashboard_refresh fired (stub)")


async def job_heartbeat() -> None:
    """Every 10 minutes — emit heartbeat ping to R1 audit client.

    Wave B3 will call `r1_audit_client.heartbeat()`. For now: log only.
    """
    logger.info("[scheduler] heartbeat fired (stub)")


# ============================================
# Scheduler factory
# ============================================
def _require_apscheduler() -> None:
    """Raise a clear error if APScheduler v3 is not importable."""
    if not _APSCHEDULER_AVAILABLE:
        raise RuntimeError(
            "apscheduler v3.x is required for backend.scheduler. "
            "Install with: pip install 'apscheduler>=3.10,<4.0'"
        )


def build_scheduler() -> "AsyncIOScheduler":
    """Build an `AsyncIOScheduler` with the 3 jobs registered, NOT started.

    Returns
    -------
    AsyncIOScheduler
        Scheduler instance with 3 jobs (`sentinel_daily`, `dashboard_refresh`,
        `heartbeat`) attached via `CronTrigger`. Caller is responsible for
        calling `.start()` inside an active event loop (we do that from the
        FastAPI `lifespan` context manager in `create_app_with_scheduler`).

    Raises
    ------
    RuntimeError
        If apscheduler v3 is not installed.
    """
    _require_apscheduler()

    scheduler = AsyncIOScheduler(
        jobstores={"default": MemoryJobStore()},
        executors={"default": AsyncIOExecutor()},
        timezone="Asia/Shanghai",
    )

    scheduler.add_job(
        job_sentinel_daily,
        CronTrigger.from_crontab("0 9 * * *", timezone="Asia/Shanghai"),
        id=JOB_SENTINEL_DAILY,
        name="Sentinel Daily ETL (09:00 SGT)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        job_dashboard_refresh,
        CronTrigger.from_crontab("0 */4 * * *"),
        id=JOB_DASHBOARD_REFRESH,
        name="Dashboard Refresh (every 4h)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        job_heartbeat,
        CronTrigger.from_crontab("*/10 * * * *"),
        id=JOB_HEARTBEAT,
        name="Heartbeat Ping (every 10min)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    logger.info(
        "[scheduler] Built AsyncIOScheduler with 3 jobs: %s",
        [JOB_SENTINEL_DAILY, JOB_DASHBOARD_REFRESH, JOB_HEARTBEAT],
    )
    return scheduler


# ============================================
# FastAPI app factory (separate from main.create_app)
# ============================================
@asynccontextmanager
async def _scheduler_lifespan(app: FastAPI):
    """Lifespan that starts the scheduler on app startup, shuts it down cleanly."""
    scheduler: Optional["AsyncIOScheduler"] = getattr(app, "state", None)
    scheduler = getattr(scheduler, "scheduler", None) if scheduler else None
    if scheduler is None:
        # Fall back to the well-known attribute name set in create_app_with_scheduler
        scheduler = app.state.scheduler  # type: ignore[attr-defined]

    assert scheduler is not None, "Scheduler must be attached to app.state.scheduler"
    assert not scheduler.running, "Scheduler must not be running before lifespan starts"

    logger.info("[scheduler] lifespan startup — starting AsyncIOScheduler")
    scheduler.start()
    try:
        yield
    finally:
        logger.info("[scheduler] lifespan shutdown — stopping AsyncIOScheduler")
        # We are already inside the event loop, so we can call the base
        # shutdown synchronously (which flips `state` to STATE_STOPPED
        # immediately). AsyncIOScheduler.shutdown() defers via
        # call_soon_threadsafe, which is unnecessary here and would leave
        # `running` returning True until the next loop tick.
        from apscheduler.schedulers.base import BaseScheduler
        BaseScheduler.shutdown(scheduler, wait=False)


def create_app_with_scheduler() -> FastAPI:
    """FastAPI app factory that wires the AsyncIOScheduler via `lifespan`.

    This is a *separate* factory from the Wave-2 `create_app()` in
    `backend/main.py`. It exists so the cron backbone can be enabled
    independently of the main app (different entrypoint, different tests).

    Mount it via:

        uvicorn backend.scheduler:app

    Returns
    -------
    FastAPI
        App with the scheduler attached to `app.state.scheduler` and a
        lifespan context manager that starts/stops it cleanly.
    """
    _require_apscheduler()

    app = FastAPI(
        title="OpenClaw Sandbox RPG — Scheduler",
        version="0.4.0",
        description="APScheduler cron backbone (Phase B2)",
        lifespan=_scheduler_lifespan,
    )

    # Attach the (un-started) scheduler to app.state.
    app.state.scheduler = build_scheduler()

    @app.get("/health")
    async def health():
        sched: "AsyncIOScheduler" = app.state.scheduler
        jobs_info = []
        for job in sched.get_jobs():
            # APScheduler 3.x: `next_run_time` is a property that raises
            # if the scheduler isn't running. Guard so /health is safe
            # to call pre-startup too.
            next_run_iso: Optional[str] = None
            if sched.running:
                try:
                    nrt = job.next_run_time
                    if nrt is not None:
                        next_run_iso = nrt.isoformat()
                except Exception:  # pragma: no cover - defensive
                    next_run_iso = None
            jobs_info.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": next_run_iso,
                }
            )
        return {
            "status": "ok",
            "running": sched.running,
            "jobs": jobs_info,
        }

    return app


# Convenience module-level app for `uvicorn backend.scheduler:app`
app = create_app_with_scheduler() if _APSCHEDULER_AVAILABLE else None  # type: ignore[assignment]


__all__ = [
    "JOB_SENTINEL_DAILY",
    "JOB_DASHBOARD_REFRESH",
    "JOB_HEARTBEAT",
    "SCHED_SENTINEL_DAILY",
    "SCHED_DASHBOARD_REFRESH",
    "SCHED_HEARTBEAT",
    "job_sentinel_daily",
    "job_dashboard_refresh",
    "job_heartbeat",
    "build_scheduler",
    "create_app_with_scheduler",
    "app",
]

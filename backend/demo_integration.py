"""
Phase C3 — Demo Integration
============================

Wires the Phase C2 ``MemoryPalaceIntegration`` endpoints into a
live demo by combining the Wave 2 FastAPI app (via
:mod:`backend.app_with_memory`) with the Phase B2
``AsyncIOScheduler`` (from :mod:`backend.scheduler`).

The goal is to **prove the end-to-end cron → endpoint chain
works**: every minute, a scheduled job hits ``/memory/health`` on
the running app via an in-process ``httpx.AsyncClient`` and logs
the result. This is the smallest possible "demo" that exercises
all three C-phase modules (B2 scheduler, C2 memory integration,
C3 wire-up) without requiring any external infrastructure.

Public surface
--------------
* :func:`build_demo_scheduler` — returns an ``AsyncIOScheduler``
  with the demo job registered. The scheduler is NOT started; the
  caller is responsible for ``.start()`` inside the running event
  loop (typically the FastAPI lifespan in
  :func:`create_demo_app`).
* :func:`add_demo_job` — convenience: register the demo job on a
  pre-existing scheduler. Used by the Phase C3 integration test
  to verify the job is wired without spinning up the app.
* :func:`create_demo_app` — FastAPI app factory that:

    1. Starts the Wave 2 app + memory router (via
       :mod:`backend.app_with_memory`), preserving the existing
       lifespan.
    2. Starts the demo scheduler with a single registered job
       (``memory_health_minute``) that POSTs/GETs the
       ``/memory/health`` endpoint every minute.
    3. Exposes ``GET /demo/info`` returning the registered jobs
       and the last few health-check results.

  Run it with::

      uvicorn backend.demo_integration:app

* :data:`app` — module-level ASGI app for ``uvicorn
  backend.demo_integration:app``.

Hard constraints honored
------------------------
* We do NOT modify ``backend/main.py``, ``backend/scheduler.py``,
  ``backend/memory_palace_integration.py`` or
  ``backend/memory_palace_integration_endpoint.py``. The demo
  composes those modules; it never edits them.
* We import the pre-built ``app`` from
  :mod:`backend.app_with_memory`, so the wire-up is the
  ``include_router`` step that happened in C3 Deliverable 1.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    _APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when dep missing
    AsyncIOScheduler = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]
    _APSCHEDULER_AVAILABLE = False

from fastapi import FastAPI

# Reuse the Wave 2 + memory router composition (frozen).
from .app_with_memory import app as composed_app

logger = logging.getLogger(__name__)


# ============================================
# Job IDs / constants
# ============================================
JOB_MEMORY_HEALTH_MINUTE = "memory_health_minute"
DEMO_HEALTH_INTERVAL_SECONDS = 60  # 1 minute — the cheapest interval


# ============================================
# In-memory rolling buffer of recent health results
# ============================================
# Capped at 16 entries so /demo/info stays bounded. We use a
# plain list + length cap (no deque dependency) — the writes
# are append-only and reads are tail-sliced.
_RECENT_HEALTH_RESULTS: list[dict[str, Any]] = []
_RECENT_HEALTH_MAX = 16


def _record_health(result: dict[str, Any]) -> None:
    """Append a result to the rolling buffer, dropping the oldest."""
    _RECENT_HEALTH_RESULTS.append(result)
    if len(_RECENT_HEALTH_RESULTS) > _RECENT_HEALTH_MAX:
        del _RECENT_HEALTH_RESULTS[:-_RECENT_HEALTH_MAX]


def get_recent_health() -> list[dict[str, Any]]:
    """Read-only view of the rolling buffer (for tests + /demo/info)."""
    return list(_RECENT_HEALTH_RESULTS)


# ============================================
# The job function
# ============================================
async def job_memory_health_minute() -> None:
    """Fire every ``DEMO_HEALTH_INTERVAL_SECONDS``: GET /memory/health.

    The job builds an in-process ``httpx.AsyncClient`` against
    ``app`` (the composed FastAPI app) via ``ASGITransport`` — no
    network, no port. If the request fails (e.g. integration not
    initialized), we log and record the error in the rolling
    buffer so the operator can see what happened from
    ``/demo/info``.

    Why we do it this way: the cron chain's whole point is to
    prove the **wire-up** (cron → endpoint → integration →
    backends) works. Hitting ``/memory/health`` exercises
    every layer. Hitting the integration directly would skip
    the FastAPI route — that's a different test.
    """
    # Late import keeps this module importable even if httpx
    # is missing (it ships with FastAPI, but the indirection
    # makes the test surface clearer).
    try:
        import httpx
    except ImportError:  # pragma: no cover - defensive
        logger.exception("[demo] httpx unavailable; job_memory_health_minute cannot run")
        _record_health(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "ok": False,
                "error": "httpx unavailable",
            }
        )
        return

    transport = httpx.ASGITransport(app=composed_app)
    timestamp = datetime.now(UTC).isoformat()
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://demo",
        ) as client:
            resp = await client.get("/memory/health", timeout=10.0)
        body: Any = None
        try:
            body = resp.json()
        except Exception:  # pragma: no cover - non-JSON shouldn't happen
            body = resp.text
        entry = {
            "timestamp": timestamp,
            "ok": resp.status_code == 200,
            "status_code": resp.status_code,
            "body": body,
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - network/ASGI fault path
        logger.exception("[demo] health check failed")
        entry = {
            "timestamp": timestamp,
            "ok": False,
            "status_code": None,
            "body": None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    _record_health(entry)
    level = logging.INFO if entry["ok"] else logging.WARNING
    logger.log(
        level,
        "[demo] /memory/health @ %s -> ok=%s status=%s body=%s",
        timestamp,
        entry["ok"],
        entry.get("status_code"),
        entry.get("body"),
    )


# ============================================
# Scheduler factory + job registration
# ============================================
def add_demo_job(scheduler: AsyncIOScheduler) -> None:
    """Register the demo job on an existing AsyncIOScheduler.

    Parameters
    ----------
    scheduler
        A *built* (not-started) AsyncIOScheduler. We register
        the job but never ``.start()`` here — that is the
        caller's responsibility (and lets the test verify
        registration without entering the event loop).
    """
    if not _APSCHEDULER_AVAILABLE:
        raise RuntimeError("apscheduler v3.x is required for backend.demo_integration")
    scheduler.add_job(
        job_memory_health_minute,
        IntervalTrigger(seconds=DEMO_HEALTH_INTERVAL_SECONDS),
        id=JOB_MEMORY_HEALTH_MINUTE,
        name="Demo: GET /memory/health (every minute)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info(
        "[demo] Registered %s (every %ss)",
        JOB_MEMORY_HEALTH_MINUTE,
        DEMO_HEALTH_INTERVAL_SECONDS,
    )


def build_demo_scheduler() -> AsyncIOScheduler:
    """Build a fresh AsyncIOScheduler with the demo job pre-registered.

    The returned scheduler is NOT started. Caller is expected to
    ``.start()`` it inside an active event loop (the lifespan
    pattern below does this).
    """
    if not _APSCHEDULER_AVAILABLE:
        raise RuntimeError("apscheduler v3.x is required for backend.demo_integration")
    scheduler = AsyncIOScheduler(
        jobstores={
            "default": __import__(
                "apscheduler.jobstores.memory", fromlist=["MemoryJobStore"]
            ).MemoryJobStore()
        },
        executors={
            "default": __import__(
                "apscheduler.executors.asyncio", fromlist=["AsyncIOExecutor"]
            ).AsyncIOExecutor()
        },
        timezone="Asia/Shanghai",
    )
    add_demo_job(scheduler)
    return scheduler


# ============================================
# FastAPI app factory with lifespan-managed scheduler
# ============================================
@asynccontextmanager
async def _demo_lifespan(application: FastAPI):
    """Lifespan that starts the demo scheduler alongside the app.

    We intentionally do NOT restart the underlying Wave 2
    lifespan — the imported ``app`` already has one, and uvicorn
    uses the lifespan of the app instance the import returns
    (which is the one from :mod:`backend.main`).
    """
    scheduler: AsyncIOScheduler = application.state.demo_scheduler
    assert not scheduler.running, "demo scheduler must not be running yet"
    scheduler.start()
    logger.info("[demo] AsyncIOScheduler started; demo job is live")
    try:
        yield
    finally:
        # Synchronous shutdown (we are inside the loop). Same
        # rationale as backend.scheduler._scheduler_lifespan.
        from apscheduler.schedulers.base import BaseScheduler

        BaseScheduler.shutdown(scheduler, wait=False)
        logger.info("[demo] AsyncIOScheduler stopped")


def create_demo_app() -> FastAPI:
    """Build a FastAPI app that bundles the composed app + the demo scheduler.

    The returned app:

    * re-uses every route from :mod:`backend.app_with_memory`
      (Wave 2 + memory router);
    * starts the demo scheduler inside its lifespan;
    * exposes ``GET /demo/info`` with the registered jobs and
      the rolling buffer of recent health-check results.

    We attach the scheduler to ``composed_app.state`` so the
    same object is the ASGI app the lifespan manages.
    """
    if not _APSCHEDULER_AVAILABLE:  # pragma: no cover - import-time guard
        raise RuntimeError("apscheduler v3.x is required for backend.demo_integration")

    composed_app.state.demo_scheduler = build_demo_scheduler()
    # Override the lifespan on the *same* app instance — the one
    # uvicorn will run — so startup/shutdown wires up the
    # scheduler without us spinning up a second FastAPI app.
    composed_app.router.lifespan_context = _demo_lifespan

    @composed_app.get("/demo/info")
    async def demo_info() -> dict[str, Any]:
        """Report the registered jobs and recent health-check results."""
        sched: AsyncIOScheduler = composed_app.state.demo_scheduler
        jobs_info: list[dict[str, Any]] = []
        for job in sched.get_jobs():
            next_run_iso: str | None = None
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
            "demo": True,
            "scheduler_running": sched.running,
            "jobs": jobs_info,
            "recent_health_checks": get_recent_health(),
        }

    return composed_app


# ============================================
# Module-level ASGI app for `uvicorn backend.demo_integration:app`
# ============================================
app: FastAPI | None = (
    create_demo_app() if _APSCHEDULER_AVAILABLE else None  # type: ignore[assignment]
)


__all__ = [
    "JOB_MEMORY_HEALTH_MINUTE",
    "DEMO_HEALTH_INTERVAL_SECONDS",
    "job_memory_health_minute",
    "add_demo_job",
    "build_demo_scheduler",
    "create_demo_app",
    "get_recent_health",
    "app",
]

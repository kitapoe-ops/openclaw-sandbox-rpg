"""
Demo Mode Toggle
=================
If DATABASE_URL is not reachable OR no postgres available,
fall back to in-memory demo mode using scenes_demo.py data.
This lets you run the backend with ZERO infrastructure for testing.

Public Cache Invalidation API (Phase E5, replaces importlib.reload hack):
    - reset_demo_mode_cache() — clear the cached DB probe result so the next
      call to is_demo_mode() or _test_db_connection() re-probes the database.
      Idempotent. This is the recommended way to invalidate the cache at
      runtime (e.g. after a DB schema change, after a config reload, or in
      test setup/teardown). DO NOT use importlib.reload — it has side effects
      beyond cache reset (e.g. clobbers any monkey-patched functions, breaks
      in-flight references held by other modules, leaves stale logger config).
    - cache_status() — return current cache state for observability/debugging.
      Reports whether the cache is populated, the cached value, and the unix
      timestamp of the last reset_demo_mode_cache() call (None if never reset
      in this process, or if the cache was only populated via _test_db_connection()).
"""
import logging
import os
import time as _time_module
from typing import Any

logger = logging.getLogger(__name__)


DEMO_MODE_FLAG = os.getenv("DEMO_MODE", "auto").lower()

# Cache the DB connection probe so it only runs once per process.
# This avoids:
#   1. Repeated slow DB probes on every /health request
#   2. RuntimeWarning: coroutine 'check' was never awaited
#      (caused by `asyncio.run()` being called from inside a running
#      event loop when is_demo_mode() is invoked from async handlers
#      like main.py's /health endpoint, which the FastAPI TestClient
#      exercises via an anyio BlockingPortal).
# Cache is also crucial because the DB probe is async — it cannot be
# re-run safely from within a running event loop.
_db_reachable_cache: bool | None = None

# Unix timestamp (float, seconds since epoch) of the last successful call to
# reset_demo_mode_cache(). None if the cache has never been reset in this
# process (i.e. only populated by _test_db_connection() / is_demo_mode()).
# This is purely an observability field — read via cache_status(). It is NOT
# updated by _test_db_connection() when the cache is populated, only by the
# explicit reset function. This separation lets callers distinguish between a
# fresh process (no reset, no probe yet) and a process that has been reset and
# is awaiting re-probe (reset happened, but cache is None again until next probe).
_last_reset_ts: float | None = None


def reset_demo_mode_cache() -> None:
    """
    Public API to reset the demo_mode module-level cache.

    Clears the cached DB probe result so the next call to is_demo_mode()
    or _test_db_connection() re-probes the database. Idempotent.

    This is the recommended way to invalidate the cache at runtime
    (e.g. after a DB schema change, after a config reload, or in
    test setup/teardown). DO NOT use importlib.reload — it has side
    effects beyond cache reset (clobbers monkey-patches, breaks
    in-flight references, leaves stale logger config, etc.).

    The internal ``_last_reset_ts`` timestamp is updated to the current
    unix time on each call, so the reset history is observable via
    cache_status().

    Returns:
        None
    """
    global _db_reachable_cache, _last_reset_ts
    _db_reachable_cache = None
    _last_reset_ts = _time_module.time()


def cache_status() -> dict[str, Any]:
    """
    Return current cache state for observability/debugging.

    Returns:
        dict with keys:
          - "cached": bool — True if _db_reachable_cache is not None
            (a probe has completed at least once in this process or
            after the last reset).
          - "value": bool | None — the cached probe result. None if
            the cache is empty (process has never probed, or the cache
            was reset and not yet re-populated).
          - "last_reset": float | None — unix timestamp of the last
            successful reset_demo_mode_cache() call. None if the cache
            has never been reset in this process (i.e. only populated
            via _test_db_connection() / is_demo_mode()).

    This function does not perform a DB probe and has no side effects.
    It is safe to call from any context, including inside a running
    event loop.
    """
    return {
        "cached": _db_reachable_cache is not None,
        "value": _db_reachable_cache,
        "last_reset": _last_reset_ts,
    }


def is_demo_mode() -> bool:
    """
    Determine if we should run in demo mode (no DB).

    DEMO_MODE env values:
      - "true"  : always demo mode
      - "false" : always use DB
      - "auto"  : try DB first, fall back to demo if connection fails
    """
    flag = os.getenv("DEMO_MODE", "auto").lower()
    if flag == "true":
        return True
    if flag == "false":
        return False
    # auto: try to detect DB availability
    return not _test_db_connection()


def _test_db_connection() -> bool:
    """
    Try to connect to PostgreSQL. Returns True if reachable.
    Uses synchronous psycopg2.connect to avoid any event loop conflict.
    """
    global _db_reachable_cache
    if _db_reachable_cache is not None:
        return _db_reachable_cache

    try:
        import psycopg2

        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://rpg_user:1891879700000@localhost/sandbox_rpg",
        )
        # Convert asyncpg scheme to psycopg2 compatible scheme
        if db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        
        # Probe database with a short timeout (3 seconds) to prevent blocking
        conn = psycopg2.connect(db_url, connect_timeout=3)
        conn.close()
        _db_reachable_cache = True
        return True
    except Exception as e:
        logger.debug(f"DB connection test failed: {e}")
        _db_reachable_cache = False
        return False


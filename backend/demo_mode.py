"""
Demo Mode Toggle
=================
If DATABASE_URL is not reachable OR no postgres available,
fall back to in-memory demo mode using scenes_demo.py data.
This lets you run the backend with ZERO infrastructure for testing.
"""
import os
import logging
from typing import Optional

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
_db_reachable_cache: Optional[bool] = None


def is_demo_mode() -> bool:
    """
    Determine if we should run in demo mode (no DB).

    DEMO_MODE env values:
      - "true"  : always demo mode
      - "false" : always use DB
      - "auto"  : try DB first, fall back to demo if connection fails
    """
    if DEMO_MODE_FLAG == "true":
        return True
    if DEMO_MODE_FLAG == "false":
        return False
    # auto: try to detect DB availability
    return not _test_db_connection()


def _test_db_connection() -> bool:
    """
    Try to connect to PostgreSQL. Returns True if reachable.

    Result is cached per process to avoid the runtime warning that
    arises when `asyncio.run` is invoked from inside a running event
    loop (e.g. from FastAPI's async /health handler when called via
    the TestClient / anyio BlockingPortal).
    """
    global _db_reachable_cache
    if _db_reachable_cache is not None:
        return _db_reachable_cache

    # If a loop is already running in this thread, we cannot safely
    # call `asyncio.run` (it raises RuntimeError). In that case we
    # conservatively assume the DB is unreachable, but only as a
    # default for the first call — subsequent calls hit the cache.
    try:
        import asyncio
        asyncio.get_running_loop()
        # Loop is running — cannot probe synchronously. Default to
        # "unreachable" (demo mode) and cache the result.
        logger.debug(
            "DB connection probe skipped: a running event loop was "
            "detected in this thread. Assuming demo mode."
        )
        _db_reachable_cache = False
        return False
    except RuntimeError:
        # No running loop — safe to use asyncio.run below.
        pass

    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        async def check():
            engine = create_async_engine(
                os.getenv("DATABASE_URL", "postgresql+asyncpg://rpg_user:***password@localhost/sandbox_rpg"),
                pool_pre_ping=False,
            )
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                return True
            except Exception:
                return False
            finally:
                await engine.dispose()

        result = asyncio.run(check())
        _db_reachable_cache = result
        return result
    except Exception as e:
        logger.debug(f"DB connection test failed: {e}")
        _db_reachable_cache = False
        return False

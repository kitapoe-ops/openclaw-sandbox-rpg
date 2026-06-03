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
    """Try to connect to PostgreSQL. Returns True if reachable."""
    try:
        import asyncio
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

        return asyncio.run(check())
    except Exception as e:
        logger.debug(f"DB connection test failed: {e}")
        return False

"""
Database engine + session factory
====================================
- Uses `settings.database_url` (PostgreSQL/asyncpg in production)
- Falls back to SQLite (`aiosqlite`) for dev/test when Postgres is unreachable
- Exposes `init_db()` and `get_session()` async context manager

Concurrency:
- `init_db()` is safe to call from many coroutines/workers at once.
- An `asyncio.Lock` + `_init_done` flag serialize the heavy work, so only the
  first caller actually creates the engine and runs `create_all()`. Latecomers
  see `_init_done == True` and return immediately.
- On failure, `_init_done` stays False so the next caller can retry.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .orm import Base

logger = logging.getLogger(__name__)


# ============================================
# Default fallback URL (dev / test)
# ============================================

DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./sandbox_rpg.db"


# ============================================
# Engine / session factory
# ============================================

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_active_url: Optional[str] = None
_fallback_active: bool = False

# ============================================
# Concurrency guards for init_db()
# ============================================
# `asyncio.Lock` MUST be created inside a running event loop, so we lazy-init
# it on first call. `_init_done` is a fast-path flag: once the first caller
# finishes successfully, every subsequent caller short-circuits without
# touching the lock at all. On failure `_init_done` stays False, allowing
# retry on the next call.

_init_lock: Optional[asyncio.Lock] = None
_init_done: bool = False


def _resolve_url() -> str:
    """
    Determine the database URL to use.

    Order:
    1. `SANDBOX_DATABASE_URL` env var (explicit override)
    2. `settings.database_url` (Postgres by default)
    3. SQLite fallback (if Postgres connection fails on first use)

    Returns the URL string only — actual connection test happens at engine init.
    """
    env_url = os.environ.get("SANDBOX_DATABASE_URL")
    if env_url:
        return env_url
    return settings.database_url


async def _try_create_engine(url: str) -> Optional[AsyncEngine]:
    """
    Try to create an async engine for the given URL. If it fails (e.g. Postgres
    unreachable), return None so the caller can fall back to SQLite.
    """
    try:
        engine = create_async_engine(url, echo=False, future=True)
        # Quick connectivity probe
        async with engine.connect() as conn:
            await conn.run_sync(lambda sync_conn: None)
        return engine
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB engine init failed for %s: %s", url, exc)
        try:
            await engine.dispose()  # type: ignore[name-defined]
        except Exception:
            pass
        return None


def init_db_sync() -> None:
    """
    Synchronous table creation — used at process startup / alembic bootstrap.
    Creates the schema for whatever engine is currently active (or a fresh
    SQLite one if none). Idempotent.
    """
    global _engine, _session_factory, _active_url, _fallback_active

    if _engine is None:
        url = _resolve_url()
        connect_args: dict = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_async_engine(url, echo=False, future=True, connect_args=connect_args)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
        _active_url = url
        _fallback_active = url.startswith("sqlite")

    # Create tables synchronously via a one-shot engine if needed
    from sqlalchemy import create_engine
    sync_url = _active_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url, future=True)
    try:
        Base.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()


async def init_db() -> None:
    """
    Async initialization. Picks Postgres if available, else falls back to SQLite.
    Creates the schema.

    Concurrency:
    - Safe to call from many coroutines/workers concurrently.
    - First caller runs the actual setup under an `asyncio.Lock`; later callers
      see `_init_done == True` and return immediately.
    - On failure `_init_done` stays False so the next call can retry.
    """
    global _engine, _session_factory, _active_url, _fallback_active
    global _init_lock, _init_done

    # Fast path: already initialized, no need to acquire the lock at all.
    if _init_done and _engine is not None:
        return

    # Lazy-init the lock (must be created inside a running event loop).
    if _init_lock is None:
        _init_lock = asyncio.Lock()

    async with _init_lock:
        # Re-check inside the lock: another coroutine may have just finished.
        if _init_done and _engine is not None:
            return

        url = _resolve_url()

        # Try primary (Postgres) first, fall back to SQLite
        engine: Optional[AsyncEngine] = None
        if not url.startswith("sqlite"):
            engine = await _try_create_engine(url)
            if engine is None:
                logger.warning("Falling back to SQLite at %s", DEFAULT_SQLITE_URL)
                url = DEFAULT_SQLITE_URL
                engine = await _try_create_engine(url)
                if engine is None:
                    raise RuntimeError(f"Could not create engine for {url}")
                _fallback_active = True
            else:
                _fallback_active = False
        else:
            engine = await _try_create_engine(url)
            if engine is None:
                raise RuntimeError(f"Could not create engine for {url}")
            _fallback_active = True

        _engine = engine
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
        _active_url = url

        # Create tables. `create_all` is idempotent (skips existing tables).
        try:
            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception:
            # Reset partial state so the next caller can retry cleanly.
            try:
                if _engine is not None:
                    await _engine.dispose()
            except Exception:
                pass
            _engine = None
            _session_factory = None
            _active_url = None
            _fallback_active = False
            # Do NOT set _init_done=True on failure — allow retry.
            raise

        _init_done = True
        logger.info("Database initialized successfully at %s", _active_url)


def reset_init_state() -> None:
    """
    Reset the init state flag. Intended for tests that need to re-run
    `init_db()` after a failure or after `dispose_engine()`.
    Does NOT touch the engine itself — call `dispose_engine()` for that.
    """
    global _init_done
    _init_done = False


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Async context manager yielding an AsyncSession. Auto-initializes the
    engine on first use. Rolls back on exception, commits on clean exit.
    """
    if _engine is None or _session_factory is None:
        await init_db()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_active_url() -> Optional[str]:
    """Return the URL the engine is currently configured for (None if not init'd)."""
    return _active_url


def is_fallback_active() -> bool:
    """True if the engine is using the SQLite fallback."""
    return _fallback_active


async def dispose_engine() -> None:
    """Cleanly close the engine (mainly for tests)."""
    global _engine, _session_factory, _active_url, _fallback_active
    global _init_lock, _init_done
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _active_url = None
    _fallback_active = False
    # Also clear the init flag AND the lock so a subsequent init_db() actually
    # runs in a fresh event loop. (asyncio.Lock objects are bound to the loop
    # that created them; pytest-asyncio uses a new loop per test by default.)
    _init_done = False
    _init_lock = None


__all__ = [
    "init_db",
    "init_db_sync",
    "get_session",
    "get_active_url",
    "is_fallback_active",
    "dispose_engine",
    "reset_init_state",
    "DEFAULT_SQLITE_URL",
]

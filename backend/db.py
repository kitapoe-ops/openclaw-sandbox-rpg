"""
Database Session Layer (v3.5 — real SQLAlchemy 2.0 async)
==========================================================
Implements the API contract for Q6 three-step decoupled transactions.

Uses SQLAlchemy 2.0 async + asyncpg.
Connection string built from POSTGRES_* env vars (matches .env.example).
"""
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, AsyncIterator
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

logger = logging.getLogger(__name__)


# ============================================
# Build connection URL from POSTGRES_* env vars
# ============================================
def _build_database_url() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "sandbox_rpg")
    user = os.getenv("POSTGRES_USER", "rpg_user")
    password = os.getenv("POSTGRES_PASSWORD", "dev_password")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = _build_database_url()

# ============================================
# Engine + Session factory
# ============================================
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Avoid zombie connections
    pool_recycle=300,    # Recycle connections every 5 min
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# ============================================
# Context managers for Q6 transaction control
# ============================================
@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """
    Short transaction context manager.
    Use for SINGLE-TABLE writes (Q6 Step 1: write PENDING, Q6 Step 4: status updates).

    Auto-commits on success, auto-rollbacks on exception.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    """
    Long transaction context manager.
    Use for MULTI-TABLE atomic writes (Q6 Step 3: write LLM result).

    Caller must commit explicitly OR let exception trigger rollback.
    All writes within the block are atomic.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # Caller decides when to commit
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ============================================
# Schema (placeholder — load from schema.sql on startup)
# ============================================
import asyncio

# Init lock + flag for race-safe idempotent initialization
_init_lock: Optional[asyncio.Lock] = None
_init_done: bool = False


def reset_init_state() -> None:
    """Reset initialization state. For testing only."""
    global _init_done
    _init_done = False


async def init_db():
    """
    Create all tables on startup. Safe to call concurrently from multiple
    workers / coroutines — uses asyncio.Lock + idempotency flag to prevent
    duplicate initialization (which would deadlock on connection pool).
    In production, use Alembic migrations instead.
    """
    global _init_lock, _init_done

    if _init_lock is None:
        _init_lock = asyncio.Lock()

    async with _init_lock:
        if _init_done:
            return  # Already initialized, no-op

        try:
            # Import models to register them with Base
            from . import models  # noqa: F401
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            _init_done = True
            logger.info("Database tables created (or already exist)")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            # Do NOT set _init_done=True on failure — allow retry
            raise


# ============================================
# Convenience functions (used by game_socket.py)
# ============================================
async def execute_query(query: str, params: dict = None) -> list:
    """Execute a raw SQL query and return results as list of dicts."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(query), params or {})
        return [dict(row._mapping) for row in result]


async def execute_scalar(query: str, params: dict = None) -> Any:
    """Execute a query and return the first scalar value."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(query), params or {})
        return result.scalar()


# TODO: Implement high-level methods that game_socket.py expects:
# - get_character_state(character_id)
# - get_action_status(action_id)
# - create_action_history(...)
# - update_action_history(...)
# - apply_state_changes(character_id, state_changes)
# - update_character_scene(character_id, new_scene_id)
# - apply_world_parameter_changes(changes)
# - get_latest_action(character_id)
# - recover_interrupted_actions()

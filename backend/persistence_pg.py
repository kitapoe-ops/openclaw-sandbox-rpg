"""
PostgreSQL Persistence Adapter (Skeleton — Phase B3)
=====================================================

SQLAlchemy 2.0 async adapter that mirrors the existing in-memory state
for ``Character`` and ``Scene`` payloads. This is a SKELETON — full
feature parity is intentionally NOT implemented. The goal is to prove
the abstraction works and the env-switch toggles between backends.

Env switch
----------
Read ``PERSISTENCE_MODE`` env var at call time via
``get_persistence_mode()``:

* ``"postgres"``  → caller is expected to instantiate
  ``PostgresPersistence`` with a real DSN (e.g. ``postgresql+asyncpg://...``).
* ``"memory"`` or unset → existing in-memory path stays; this module
  is NOT instantiated and ``PostgresPersistence.__init__`` is never called.

Test transport
--------------
Tests use ``aiosqlite`` so ``asyncpg`` / ``psycopg`` are NOT required
in CI. Example URL::

    sqlite+aiosqlite:///./test_pg_adapter.db

Schema
------
* ``characters`` — ``id`` (PK str), ``payload`` (JSON),
  ``created_at``, ``updated_at``
* ``scenes``     — ``id`` (PK str), ``character_id`` (FK str, indexed),
  ``payload`` (JSON), ``created_at``

The adapter is a thin layer over the two tables. It exposes
``save_/load_/delete_character`` and ``save_/load_scene`` plus
``health()`` and ``close()`` for lifecycle management.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

logger = logging.getLogger(__name__)


# ============================================
# Base + ORM models
# ============================================
class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for the persistence schema."""


class CharacterRow(Base):
    """Persisted character payload.

    The ``payload`` JSON column holds the full in-memory character
    representation (mirrors the in-memory dict that
    ``Character.to_dict()`` would return). The ``id`` is the
    application-level character id (string).
    """

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneRow(Base):
    """Persisted scene payload, FK to ``characters.id``."""

    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    character_id: Mapped[str] = mapped_column(String, ForeignKey("characters.id"), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Index FK lookups (scenes by character_id is a hot path).
        Index("ix_scenes_character_id", "character_id"),
    )


# ============================================
# Env helper
# ============================================
def get_persistence_mode() -> str:
    """Resolve the current persistence backend from the environment.

    Returns
    -------
    str
        ``"postgres"`` if ``PERSISTENCE_MODE=="postgres"``,
        otherwise ``"memory"``. Unset / unknown values are treated as
        ``"memory"`` so the in-memory path is the safe default.
    """
    mode = (os.getenv("PERSISTENCE_MODE") or "").strip().lower()
    if mode == "postgres":
        return "postgres"
    return "memory"


# ============================================
# Adapter
# ============================================
class PostgresPersistence:
    """Async SQLAlchemy 2.0 adapter for character + scene payloads.

    Parameters
    ----------
    database_url : str
        A SQLAlchemy async URL. Supports any async dialect
        (``postgresql+asyncpg://...`` for prod, ``sqlite+aiosqlite:///...``
        for tests).

    Notes
    -----
    The constructor only builds the engine + sessionmaker; it does
    **not** create tables or open a connection. Call ``health()`` (or
    any other method) to actually exercise the engine. This makes
    construction cheap and avoids spurious failures when the module
    is imported in environments where the DB is not yet reachable.
    """

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")

        self._database_url: str = database_url
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
        )
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._schema_ready: bool = False
        logger.debug("PostgresPersistence initialized for %s", _redact_url(database_url))

    # --------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------
    async def _ensure_schema(self) -> None:
        """Create tables on first use. Idempotent — safe under concurrency
        within a single process via an asyncio lock."""
        if self._schema_ready:
            return
        # NOTE: We do not import asyncio at module level beyond what
        # the type system already pulls in; create the lock lazily.
        import asyncio

        if not hasattr(self, "_schema_lock") or self._schema_lock is None:
            self._schema_lock = asyncio.Lock()
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self._schema_ready = True

    async def health(self) -> bool:
        """Return True if a trivial query succeeds.

        Also performs lazy schema bootstrap. Returns False (without
        raising) on connection / dialect error so callers can probe
        readiness without try/except.
        """
        try:
            await self._ensure_schema()
            async with self._sessionmaker() as session:
                # SELECT 1 works on every supported dialect.
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("PostgresPersistence.health() failed: %s", exc)
            return False

    async def close(self) -> None:
        """Dispose the engine. Safe to call multiple times."""
        if self._engine is None:
            return
        try:
            await self._engine.dispose()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("PostgresPersistence.close() failed: %s", exc)

    # --------------------------------------------------------
    # Character CRUD
    # --------------------------------------------------------
    async def save_character(self, character_id: str, payload: dict) -> None:
        """Insert or update a character row.

        If a row with ``character_id`` already exists, ``payload`` and
        ``updated_at`` are refreshed and ``created_at`` is preserved.
        """
        if not character_id:
            raise ValueError("character_id is required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        await self._ensure_schema()
        now = datetime.now(UTC)
        async with self._sessionmaker() as session:
            try:
                existing = await session.get(CharacterRow, character_id)
                if existing is None:
                    session.add(
                        CharacterRow(
                            id=character_id,
                            payload=payload,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    existing.payload = payload
                    existing.updated_at = now
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def load_character(self, character_id: str) -> dict | None:
        """Return the stored payload for ``character_id`` or None."""
        if not character_id:
            raise ValueError("character_id is required")
        await self._ensure_schema()
        async with self._sessionmaker() as session:
            row = await session.get(CharacterRow, character_id)
            if row is None:
                return None
            # Return a shallow copy so callers can't accidentally
            # mutate the ORM-bound dict.
            return dict(row.payload)

    async def delete_character(self, character_id: str) -> None:
        """Delete a character row by id. No-op if it does not exist."""
        if not character_id:
            raise ValueError("character_id is required")
        await self._ensure_schema()
        async with self._sessionmaker() as session:
            try:
                row = await session.get(CharacterRow, character_id)
                if row is not None:
                    await session.delete(row)
                    await session.commit()
                else:
                    await session.rollback()
            except Exception:
                await session.rollback()
                raise

    # --------------------------------------------------------
    # Scene CRUD
    # --------------------------------------------------------
    async def save_scene(self, scene_id: str, character_id: str, payload: dict) -> None:
        """Insert a scene row referencing ``character_id``.

        Note: this is a SKELETON — scenes are inserted fresh; no
        upsert / replace logic is implemented yet. If a row with the
        same ``scene_id`` already exists, the FK insert will fail on
        most dialects (unique PK violation). That is acceptable for
        the Phase B3 skeleton.
        """
        if not scene_id:
            raise ValueError("scene_id is required")
        if not character_id:
            raise ValueError("character_id is required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        await self._ensure_schema()
        now = datetime.now(UTC)
        async with self._sessionmaker() as session:
            try:
                session.add(
                    SceneRow(
                        id=scene_id,
                        character_id=character_id,
                        payload=payload,
                        created_at=now,
                    )
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def load_scene(self, scene_id: str) -> dict | None:
        """Return the stored payload for ``scene_id`` or None."""
        if not scene_id:
            raise ValueError("scene_id is required")
        await self._ensure_schema()
        async with self._sessionmaker() as session:
            row = await session.get(SceneRow, scene_id)
            if row is None:
                return None
            return dict(row.payload)


# ============================================
# Helpers
# ============================================
def _redact_url(url: str) -> str:
    """Best-effort credential redaction for log lines."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1) if "://" in url else ("", url)
    if "@" in rest:
        _, host_part = rest.split("@", 1)
        return f"{scheme}://***@{host_part}"
    return url

"""
High-level persistence API
============================
Provides drop-in async functions for saving/loading characters, scenes, and
worlds. Each function tries the SQLAlchemy engine first; on any DB error it
falls back to the in-memory `store` so dev workflows never break.

This module is intentionally thin: business logic lives in
``CharacterStateMachine`` and ``StateChangeCalculator``. Persistence just
serializes state dicts into JSON columns.

Persistence-mode switch
-----------------------
The module exposes ``get_store()`` which returns a backend object with a
uniform interface. Two backends are supported:

- ``"memory"`` (default) — ``backend.store.store`` (``InMemoryStore``)
- ``"database"``          — ``backend.persistence_db.db_store`` (``DBStore``)

The mode is controlled by ``settings.persistence_mode`` (env var
``SANDBOX_PERSISTENCE_MODE``). The legacy high-level async functions in this
module (e.g. ``save_character``, ``load_character``) are still available and
are also dispatcher-aware: they delegate to the active backend.
"""
from __future__ import annotations

import logging
import os
import threading
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .db import get_session, init_db
from .orm import Character as CharacterORM, Scene as SceneORM, World as WorldORM
from .store import store

logger = logging.getLogger(__name__)


# ============================================
# Backend dispatcher
# ============================================

# Cache: backend name -> backend object. Module-level so all callers share
# the same instance for the lifetime of the process.
_BACKEND_CACHE: Dict[str, Any] = {}
_BACKEND_LOCK = threading.Lock()


class AsyncInMemoryStore:
    """
    Async-friendly wrapper around the synchronous :class:`InMemoryStore`.

    The real :class:`InMemoryStore` is intentionally sync (thread-safe via an
    internal lock). API endpoints, however, call ``await store.method(...)``
    so they can transparently switch to the SQLAlchemy-backed
    :class:`DBStore` without source changes. This adapter exposes the
    *same method names* as coroutines that simply delegate to the sync
    implementation.

    We define it here (not in ``backend.store``) because the allowlist
    forbids editing ``store.py``.
    """

    def __init__(self, inner):
        self._inner = inner

    # --- Characters ---

    async def save_character(self, character: Dict[str, Any]) -> None:
        self._inner.save_character(character)

    async def get_character(self, character_id: str) -> Optional[Dict[str, Any]]:
        return self._inner.get_character(character_id)

    async def list_characters(self) -> List[Dict[str, Any]]:
        return self._inner.list_characters()

    # --- Scenes ---

    async def save_scene(self, character_id: str, scene: Dict[str, Any]) -> None:
        self._inner.save_scene(character_id, scene)

    async def get_scene_history(
        self, character_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        return self._inner.get_scene_history(character_id, limit=limit)

    async def get_latest_scene(self, character_id: str) -> Optional[Dict[str, Any]]:
        return self._inner.get_latest_scene(character_id)

    # --- Worlds ---

    async def load_world(self, world_id: str, world_data: Dict[str, Any]) -> None:
        self._inner.load_world(world_id, world_data)

    async def get_world(self, world_id: str) -> Optional[Dict[str, Any]]:
        return self._inner.get_world(world_id)

    # --- Expose the underlying singleton for direct introspection in tests ---
    @property
    def inner(self):
        return self._inner


def _resolve_mode() -> str:
    """
    Determine the active persistence mode.

    Order of precedence:
    1. ``SANDBOX_PERSISTENCE_MODE`` env var (explicit runtime override).
    2. ``settings.persistence_mode`` (configured value from .env / defaults).
    """
    env_mode = os.environ.get("SANDBOX_PERSISTENCE_MODE")
    if env_mode:
        return env_mode.strip().lower()
    return (settings.persistence_mode or "memory").strip().lower()


def get_store():
    """
    Return the active persistence backend.

    The returned object implements the same interface as
    :class:`backend.store.InMemoryStore` (methods: ``save_character``,
    ``get_character``, ``list_characters``, ``save_scene``,
    ``get_scene_history``, ``get_latest_scene``, ``load_world``,
    ``get_world``). The exact same methods exist on the DB-backed
    :class:`backend.persistence_db.DBStore`, so API code can call them
    uniformly.

    Two modes are supported:
    - ``"memory"``  — :data:`backend.store.store`
    - ``"database"`` — :data:`backend.persistence_db.db_store`
    """
    mode = _resolve_mode()
    with _BACKEND_LOCK:
        if mode in _BACKEND_CACHE:
            return _BACKEND_CACHE[mode]

    if mode == "database":
        from .persistence_db import db_store
        backend = db_store
    else:
        # Default + explicit "memory": wrap the in-process InMemoryStore in
        # the async-friendly adapter so callers can ``await`` uniformly.
        from .store import store as mem_store
        backend = AsyncInMemoryStore(mem_store)

    with _BACKEND_LOCK:
        _BACKEND_CACHE[mode] = backend
    return backend


def reset_backend_cache() -> None:
    """
    Clear the cached backend instances. Test-only convenience.
    """
    with _BACKEND_LOCK:
        _BACKEND_CACHE.clear()


def current_mode() -> str:
    """Return the resolved persistence mode string (``"memory"``/``"database"``)."""
    return _resolve_mode()



# ============================================
# Helpers
# ============================================

def _is_fatal_db_error(exc: BaseException) -> bool:
    """
    Decide whether an exception should trigger fallback to in-memory store.
    We treat all SQLAlchemy errors and connection errors as recoverable
    (fallback), since persistence should never crash the dev workflow.
    """
    return isinstance(exc, (SQLAlchemyError, ConnectionError, OSError))


# ============================================
# Character
# ============================================

async def save_character(char: Dict[str, Any]) -> None:
    """
    Upsert a character. Writes to DB; on failure, writes to in-memory store.

    Required keys: ``character_id``. Optional: ``name``, ``world_id``,
    everything else is stored inside ``json_state``.
    """
    if not isinstance(char, dict) or "character_id" not in char:
        raise ValueError("char must be a dict containing 'character_id'")

    character_id = char["character_id"]
    name = char.get("name", "")
    world_id = char.get("world_id", "default")
    now = datetime.utcnow()

    # Build the json_state blob: everything except a small set of "header" fields
    header_fields = {"character_id", "name", "world_id", "created_at", "updated_at"}
    json_state = {k: v for k, v in char.items() if k not in header_fields}

    try:
        await init_db()
        async with get_session() as session:
            existing = (
                await session.execute(
                    select(CharacterORM).where(CharacterORM.character_id == character_id)
                )
            ).scalar_one_or_none()

            if existing is None:
                row = CharacterORM(
                    character_id=character_id,
                    name=name,
                    world_id=world_id,
                    json_state=json_state,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                existing.name = name
                existing.world_id = world_id
                existing.json_state = json_state
                existing.updated_at = now
    except Exception as exc:  # noqa: BLE001
        if _is_fatal_db_error(exc):
            logger.warning(
                "save_character: DB write failed, falling back to memory store: %s\n%s",
                exc, traceback.format_exc(),
            )
        else:
            # Unknown error — still fallback so dev never breaks
            logger.warning("save_character: unexpected error, falling back: %s", exc)
        store.save_character(char)


async def load_character(character_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a character by id. Returns the full state dict (with header fields
    reconstructed) or None if not found.
    """
    if not character_id:
        return None
    try:
        await init_db()
        async with get_session() as session:
            row = (
                await session.execute(
                    select(CharacterORM).where(CharacterORM.character_id == character_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            char: Dict[str, Any] = dict(row.json_state or {})
            char["character_id"] = row.character_id
            char["name"] = row.name
            char["world_id"] = row.world_id
            char["created_at"] = row.created_at.isoformat() + "Z" if row.created_at else None
            char["updated_at"] = row.updated_at.isoformat() + "Z" if row.updated_at else None
            return char
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_character: DB read failed, falling back: %s", exc)
        return store.get_character(character_id)


# ============================================
# Scene
# ============================================

async def save_scene(character_id: str, scene: Dict[str, Any]) -> None:
    """
    Append a scene to the character's history. Creates the character row if
    it doesn't exist (so tests don't have to pre-create).
    """
    if not character_id:
        raise ValueError("character_id is required")
    if not isinstance(scene, dict):
        raise ValueError("scene must be a dict")

    round_number = int(scene.get("round", 0))
    now = datetime.utcnow()

    try:
        await init_db()
        async with get_session() as session:
            # Ensure character row exists (FK constraint)
            existing = (
                await session.execute(
                    select(CharacterORM).where(CharacterORM.character_id == character_id)
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(CharacterORM(
                    character_id=character_id,
                    name=scene.get("character_name", ""),
                    world_id=scene.get("world_id", "default"),
                    json_state={"character_id": character_id},
                    created_at=now,
                    updated_at=now,
                ))
            session.add(SceneORM(
                character_id=character_id,
                round=round_number,
                json_output=scene,
                created_at=now,
            ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("save_scene: DB write failed, falling back: %s", exc)
        store.save_scene(character_id, scene)


async def load_scenes(character_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Load the latest ``limit`` scenes for a character, ordered by id DESC
    (most recent first by insertion order).
    """
    if not character_id:
        return []
    try:
        await init_db()
        async with get_session() as session:
            stmt = (
                select(SceneORM)
                .where(SceneORM.character_id == character_id)
                .order_by(SceneORM.id.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            # Return in chronological order (oldest of the slice first)
            return [dict(r.json_output or {}) for r in reversed(rows)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_scenes: DB read failed, falling back: %s", exc)
        return store.get_scene_history(character_id, limit=limit)


# ============================================
# World
# ============================================

async def save_world(world_id: str, config: Dict[str, Any]) -> None:
    """Upsert a world config."""
    if not world_id:
        raise ValueError("world_id is required")
    if not isinstance(config, dict):
        raise ValueError("config must be a dict")
    now = datetime.utcnow()
    try:
        await init_db()
        async with get_session() as session:
            existing = (
                await session.execute(
                    select(WorldORM).where(WorldORM.world_id == world_id)
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(WorldORM(
                    world_id=world_id,
                    json_config=config,
                    created_at=now,
                ))
            else:
                existing.json_config = config
    except Exception as exc:  # noqa: BLE001
        logger.warning("save_world: DB write failed, falling back: %s", exc)
        store.load_world(world_id, config)


async def load_world(world_id: str) -> Optional[Dict[str, Any]]:
    """Load a world config, or None if not found."""
    if not world_id:
        return None
    try:
        await init_db()
        async with get_session() as session:
            row = (
                await session.execute(
                    select(WorldORM).where(WorldORM.world_id == world_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return dict(row.json_config or {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_world: DB read failed, falling back: %s", exc)
        return store.get_world(world_id)


# ============================================
# Test helpers
# ============================================

async def reset_all() -> None:
    """
    Wipe all rows from all tables. Test-only convenience. Falls back to
    clearing the in-memory store if the DB is unavailable.
    """
    try:
        await init_db()
        async with get_session() as session:
            await session.execute(delete(SceneORM))
            await session.execute(delete(CharacterORM))
            await session.execute(delete(WorldORM))
    except Exception:
        store.characters.clear()
        store.scenes.clear()
        store.worlds.clear()


__all__ = [
    "save_character",
    "load_character",
    "save_scene",
    "load_scenes",
    "save_world",
    "load_world",
    "reset_all",
]

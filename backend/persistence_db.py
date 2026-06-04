"""
DBStore - SQLAlchemy-backed persistence backend
================================================
Mirror of ``backend.store.InMemoryStore`` for the "database" persistence
mode. Provides the same synchronous-style method names as ``InMemoryStore``
so the API endpoints can be written against one uniform interface, while
the implementations are async-friendly and backed by the real
``characters`` / ``scenes`` / ``worlds`` tables.

The high-level ``backend.persistence`` module already provides
``save_character`` / ``load_character`` / ``save_scene`` / ``load_scenes``
/ ``save_world`` / ``load_world`` (async). ``DBStore`` exposes the same
operations under the names used by ``InMemoryStore`` (e.g.
``save_character``, ``get_character``, ``save_scene``,
``get_scene_history``, ``get_latest_scene``, ``load_world``,
``get_world``, ``list_characters``) so the API endpoints can switch
backends with no source change other than ``store = get_store()``.

This module deliberately does NOT do its own connection management: it
delegates to ``backend.db`` and ``backend.orm`` for the engine, session
factory, and table definitions.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .db import get_session, init_db
from .orm import Character as CharacterORM, Scene as SceneORM, World as WorldORM

logger = logging.getLogger(__name__)


# ============================================
# Header fields: small set of keys that live as their own columns
# in the ``characters`` table. Everything else goes into ``json_state``.
# ============================================
_CHARACTER_HEADER_FIELDS = {
    "character_id",
    "name",
    "world_id",
    "created_at",
    "updated_at",
}


def _split_character(char: Dict[str, Any]) -> Dict[str, Any]:
    """Pull out the header fields from a full character dict."""
    return {
        "character_id": char.get("character_id"),
        "name": char.get("name", ""),
        "world_id": char.get("world_id", "default"),
        "json_state": {k: v for k, v in char.items() if k not in _CHARACTER_HEADER_FIELDS},
    }


def _row_to_character(row: CharacterORM) -> Dict[str, Any]:
    """Reassemble a full character dict from a Character row."""
    char: Dict[str, Any] = dict(row.json_state or {})
    char["character_id"] = row.character_id
    char["name"] = row.name
    char["world_id"] = row.world_id
    char["created_at"] = row.created_at.isoformat() + "Z" if row.created_at else None
    char["updated_at"] = row.updated_at.isoformat() + "Z" if row.updated_at else None
    return char


# ============================================
# DBStore
# ============================================
class DBStore:
    """
    SQLAlchemy-backed character/scene/world store.

    Method names mirror ``InMemoryStore`` so the API layer is backend-agnostic.
    All write/read methods are coroutines so the API can ``await`` them.
    """

    # ---------------- Characters ----------------

    async def save_character(self, character: Dict[str, Any]) -> None:
        """Upsert a character. Replaces the row, preserving the same id."""
        if not isinstance(character, dict) or "character_id" not in character:
            raise ValueError("character must be a dict containing 'character_id'")
        character_id = character["character_id"]
        now = datetime.utcnow()
        header = _split_character(character)
        try:
            await init_db()
            async with get_session() as session:
                existing = (
                    await session.execute(
                        select(CharacterORM).where(CharacterORM.character_id == character_id)
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(CharacterORM(
                        character_id=character_id,
                        name=header["name"],
                        world_id=header["world_id"],
                        json_state=header["json_state"],
                        created_at=now,
                        updated_at=now,
                    ))
                else:
                    existing.name = header["name"]
                    existing.world_id = header["world_id"]
                    existing.json_state = header["json_state"]
                    existing.updated_at = now
        except SQLAlchemyError as exc:
            logger.error("DBStore.save_character failed: %s", exc)
            raise

    async def get_character(self, character_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a character by id, or None if missing."""
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
                return _row_to_character(row)
        except SQLAlchemyError as exc:
            logger.error("DBStore.get_character failed: %s", exc)
            raise

    async def list_characters(self) -> List[Dict[str, Any]]:
        """Return every character in the store."""
        try:
            await init_db()
            async with get_session() as session:
                rows = (await session.execute(select(CharacterORM))).scalars().all()
                return [_row_to_character(r) for r in rows]
        except SQLAlchemyError as exc:
            logger.error("DBStore.list_characters failed: %s", exc)
            raise

    # ---------------- Scenes ----------------

    async def _ensure_character_row(
        self, session, character_id: str, name: str = "", world_id: str = "default"
    ) -> None:
        """Insert a placeholder character row if none exists (so FK is satisfied)."""
        existing = (
            await session.execute(
                select(CharacterORM).where(CharacterORM.character_id == character_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            now = datetime.utcnow()
            session.add(CharacterORM(
                character_id=character_id,
                name=name,
                world_id=world_id,
                json_state={"character_id": character_id},
                created_at=now,
                updated_at=now,
            ))

    async def save_scene(self, character_id: str, scene: Dict[str, Any]) -> None:
        """Append a scene row to the character's history."""
        if not character_id:
            raise ValueError("character_id is required")
        if not isinstance(scene, dict):
            raise ValueError("scene must be a dict")
        round_number = int(scene.get("round", 0))
        now = datetime.utcnow()
        try:
            await init_db()
            async with get_session() as session:
                await self._ensure_character_row(
                    session,
                    character_id,
                    name=scene.get("character_name", ""),
                    world_id=scene.get("world_id", "default"),
                )
                session.add(SceneORM(
                    character_id=character_id,
                    round=round_number,
                    json_output=scene,
                    created_at=now,
                ))
        except SQLAlchemyError as exc:
            logger.error("DBStore.save_scene failed: %s", exc)
            raise

    async def get_scene_history(
        self, character_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Return the last ``limit`` scenes for a character (oldest-first)."""
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
                return [dict(r.json_output or {}) for r in reversed(rows)]
        except SQLAlchemyError as exc:
            logger.error("DBStore.get_scene_history failed: %s", exc)
            raise

    async def get_latest_scene(self, character_id: str) -> Optional[Dict[str, Any]]:
        """Return the most recent scene for a character, or None."""
        if not character_id:
            return None
        try:
            await init_db()
            async with get_session() as session:
                stmt = (
                    select(SceneORM)
                    .where(SceneORM.character_id == character_id)
                    .order_by(SceneORM.id.desc())
                    .limit(1)
                )
                row = (await session.execute(stmt)).scalars().first()
                if row is None:
                    return None
                return dict(row.json_output or {})
        except SQLAlchemyError as exc:
            logger.error("DBStore.get_latest_scene failed: %s", exc)
            raise

    # ---------------- Worlds ----------------

    async def load_world(self, world_id: str, world_data: Dict[str, Any]) -> None:
        """Upsert a world config blob keyed by world_id."""
        if not world_id:
            raise ValueError("world_id is required")
        if not isinstance(world_data, dict):
            raise ValueError("world_data must be a dict")
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
                        json_config=world_data,
                        created_at=now,
                    ))
                else:
                    existing.json_config = world_data
        except SQLAlchemyError as exc:
            logger.error("DBStore.load_world failed: %s", exc)
            raise

    async def get_world(self, world_id: str) -> Optional[Dict[str, Any]]:
        """Return a world config by id, or None."""
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
        except SQLAlchemyError as exc:
            logger.error("DBStore.get_world failed: %s", exc)
            raise


# ============================================
# Module-level singleton (mirrors ``store`` in backend.store)
# ============================================
db_store = DBStore()


__all__ = ["DBStore", "db_store"]

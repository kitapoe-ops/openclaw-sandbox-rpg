"""
SQLAlchemy ORM Models
======================
Persistent storage layer for Sandbox RPG.

NOTE on file name: The task spec said ``backend/models.py``, but a placeholder
package ``backend/models/`` already existed (empty ``__init__.py``, no
importers) and shadowed any sibling ``models.py``. The allowlist forbade
modifying that package, so the ORM models live in ``backend/orm.py`` instead.
All imports go through ``from backend.orm import ...``.

Three tables:
- characters: full character_state JSON blob keyed by character_id
- scenes: per-round scene_output JSON blobs, linked to character
- worlds: world config JSON blobs, keyed by world_id

The `json_state` / `json_output` / `json_config` columns are dialect-agnostic
JSON. On PostgreSQL this becomes JSONB; on SQLite it becomes TEXT (still
transparently handled by SQLAlchemy's `JSON` type).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, ForeignKey, DateTime, JSON, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ============================================
# Base
# ============================================

class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ============================================
# Tables
# ============================================

class Character(Base):
    """Persistent character state (full state dict in json_state column)."""
    __tablename__ = "characters"

    character_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    world_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default", index=True)
    json_state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    scenes: Mapped[list["Scene"]] = relationship(
        "Scene", back_populates="character", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "world_id": self.world_id,
            "json_state": self.json_state,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }


class Scene(Base):
    """Per-round scene output (full scene dict in json_output column)."""
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("characters.character_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    json_output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    character: Mapped["Character"] = relationship("Character", back_populates="scenes")

    __table_args__ = (
        # Composite index for "latest N scenes for character" queries
        Index("ix_scenes_character_round", "character_id", "round"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "character_id": self.character_id,
            "round": self.round,
            "json_output": self.json_output,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }


class World(Base):
    """World configuration (full YAML/JSON config in json_config column)."""
    __tablename__ = "worlds"

    world_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    json_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "world_id": self.world_id,
            "json_config": self.json_config,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }


__all__ = ["Base", "Character", "Scene", "World"]

"""
SQLAlchemy ORM Models
========================
Maps to deploy/sql/schema.sql tables.
Used by backend/db.py for type-safe queries.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .db import Base


# ============================================
# Enums
# ============================================
class ExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


# ============================================
# Models
# ============================================
class World(Base):
    __tablename__ = "worlds"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    version = Column(String(32), nullable=False)
    config = Column(JSONB, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Scene(Base):
    __tablename__ = "scenes"

    id = Column(String(128), primary_key=True)
    world_id = Column(String(64), ForeignKey("worlds.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    location_tag = Column(String(64))
    environment_tags = Column(JSONB, nullable=False, default=list)
    active_npcs = Column(JSONB, nullable=False, default=list)
    atmosphere = Column(String(32), nullable=False, default="peaceful")
    is_dynamic = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class CharacterState(Base):
    __tablename__ = "character_states"

    character_id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    world_id = Column(String(64), ForeignKey("worlds.id"), nullable=False)
    current_scene_id = Column(String(128), ForeignKey("scenes.id"), nullable=False)
    semantic_profile = Column(JSONB, nullable=False)
    is_npc_mode = Column(Boolean, nullable=False, default=False)
    is_alive = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ActionHistory(Base):
    __tablename__ = "action_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_id = Column(String(64), ForeignKey("character_states.character_id"), nullable=False)
    scene_id = Column(String(128), ForeignKey("scenes.id"), nullable=False)
    round_number = Column(Integer, nullable=False)
    player_choice = Column(JSONB, nullable=False)
    execution_status = Column(
        Enum(ExecutionStatus, name="execution_status"),
        nullable=False,
        default=ExecutionStatus.PENDING,
    )
    submitted_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    llm_narrative_output = Column(Text)
    llm_choices_output = Column(JSONB)
    llm_state_changes = Column(JSONB)
    error_message = Column(Text)
    interrupted_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class WorldParameterState(Base):
    __tablename__ = "world_parameter_states"

    id = Column(String(128), primary_key=True)
    world_id = Column(String(64), ForeignKey("worlds.id"), nullable=False)
    parameter_id = Column(String(128), nullable=False)
    current_level = Column(Integer, nullable=False, default=0)
    last_change_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_change_reason = Column(Text)
    daily_change_count = Column(Integer, nullable=False, default=0)


class WorldEvent(Base):
    __tablename__ = "world_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    world_id = Column(String(64), ForeignKey("worlds.id"), nullable=False)
    event_type = Column(String(32), nullable=False)
    description = Column(Text, nullable=False)
    affected_locations = Column(JSONB, nullable=False, default=list)
    affected_npcs = Column(JSONB, nullable=False, default=list)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

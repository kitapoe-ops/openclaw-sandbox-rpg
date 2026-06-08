"""
Unit tests for the active_threads database column in CharacterState model
========================================================================

Verifies that:
1. active_threads defaults to an empty dictionary ({}) when not specified.
2. active_threads can store structured JSON (tropes tracking, escalation levels, statuses).
3. The schema contract handles serialization and deserialization seamlessly via SQLite (aiosqlite) / Postgres.
"""
from __future__ import annotations

import os
import sys

# Ensure repo root is on sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "TEXT"

from backend.db import Base
from backend.models import CharacterState, World, Scene


@pytest_asyncio.fixture
async def db_session():
    """Yield an AsyncSession bound to an in-memory SQLite database with initialized schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    # Create tables defined in models.py
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    sessionmaker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with sessionmaker() as session:
        yield session
        
    await engine.dispose()


@pytest_asyncio.fixture
async def setup_world_and_scene(db_session: AsyncSession):
    """Seed a dummy world and scene required as foreign keys for character_states."""
    world = World(
        id="test_world",
        name="Test Forgotten Realms",
        version="1.0",
        config={},
        is_active=True
    )
    scene = Scene(
        id="test_scene",
        world_id="test_world",
        name="Tavern",
        description="A warm tavern",
        location_tag="tavern",
        environment_tags=[],
        active_npcs=[],
        atmosphere="peaceful"
    )
    db_session.add(world)
    db_session.add(scene)
    await db_session.commit()
    return "test_world", "test_scene"


@pytest.mark.asyncio
class TestActiveThreadsColumn:
    async def test_active_threads_default_value(self, db_session: AsyncSession, setup_world_and_scene):
        """Verifies that active_threads defaults to an empty dictionary ({}) when not specified."""
        world_id, scene_id = setup_world_and_scene
        
        char = CharacterState(
            character_id="char_player_default_threads",
            name="Default Hero",
            world_id=world_id,
            current_scene_id=scene_id,
            semantic_profile={"health": "healthy", "stamina": "full", "morale": "high"},
            is_npc_mode=False,
            is_alive=True
        )
        db_session.add(char)
        await db_session.commit()
        
        # Reload character from database
        stmt = select(CharacterState).where(CharacterState.character_id == "char_player_default_threads")
        result = await db_session.execute(stmt)
        loaded_char = result.scalar_one()
        
        assert loaded_char.active_threads == {}
        assert isinstance(loaded_char.active_threads, dict)

    async def test_active_threads_read_write(self, db_session: AsyncSession, setup_world_and_scene):
        """Verifies that active_threads can store, persist and reload structured trope seed data."""
        world_id, scene_id = setup_world_and_scene
        
        trope_data = {
            "trope_scapegoat_01": {
                "status": "Evaded",
                "escalation_level": 3,
                "seeded_round": 1,
                "meta": {
                    "evade_consequence": "通緝令已發酵，賞金獵人正在追蹤"
                }
            }
        }
        
        char = CharacterState(
            character_id="char_player_with_threads",
            name="Karma Hero",
            world_id=world_id,
            current_scene_id=scene_id,
            semantic_profile={"health": "healthy"},
            is_npc_mode=False,
            is_alive=True,
            active_threads=trope_data
        )
        db_session.add(char)
        await db_session.commit()
        
        # Reload character from database
        stmt = select(CharacterState).where(CharacterState.character_id == "char_player_with_threads")
        result = await db_session.execute(stmt)
        loaded_char = result.scalar_one()
        
        assert loaded_char.active_threads == trope_data
        assert loaded_char.active_threads["trope_scapegoat_01"]["status"] == "Evaded"
        assert loaded_char.active_threads["trope_scapegoat_01"]["escalation_level"] == 3
        
        # Test updating the existing active_threads dict
        # In SQLAlchemy, changing a dict in-place might require flag_modified
        # or overwriting the dict field to trigger updates. Overwriting is safest.
        updated_trope = dict(loaded_char.active_threads)
        updated_trope["trope_scapegoat_01"]["escalation_level"] = 4
        loaded_char.active_threads = updated_trope
        await db_session.commit()
        
        # Reload again to verify update persisted
        result = await db_session.execute(stmt)
        reloaded_char = result.scalar_one()
        assert reloaded_char.active_threads["trope_scapegoat_01"]["escalation_level"] == 4

"""
Tests for the high-level persistence layer (save/load character, scene, world
+ fallback to in-memory store on DB failure).
"""
from __future__ import annotations

import os
import sys
import asyncio
import pytest
import pytest_asyncio

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================
# DB environment fixtures
# ============================================

@pytest_asyncio.fixture
async def fresh_db(monkeypatch, tmp_path):
    """Per-test SQLite DB; resets engine + in-memory store between tests."""
    db_path = tmp_path / "persistence_test.db"
    monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    from backend import db as db_mod
    from backend import store as store_mod
    await db_mod.dispose_engine()
    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()
    yield db_path
    await db_mod.dispose_engine()
    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()


@pytest_asyncio.fixture
async def fresh_memory(monkeypatch, tmp_path):
    """
    Fixture that points persistence at a *broken* DB path so we exercise the
    fallback to the in-memory store. The in-memory store is wiped at the end.
    """
    # Point at a path we cannot create (so the engine init will fail)
    bad_path = "/this/path/should/not/exist/cannot_create.db"
    monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite+aiosqlite:///{bad_path}")
    from backend import db as db_mod
    from backend import store as store_mod
    # Force the engine to be re-created on next use
    await db_mod.dispose_engine()
    # Monkey-patch _try_create_engine to return None (simulating Postgres down)
    orig_try = db_mod._try_create_engine
    async def _always_fail(url):
        return None
    monkeypatch.setattr(db_mod, "_try_create_engine", _always_fail)
    # And make the default SQLite URL a writable temp file
    monkeypatch.setattr(db_mod, "DEFAULT_SQLITE_URL",
                        f"sqlite+aiosqlite:///{tmp_path / 'fallback.db'}")
    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()
    yield
    await db_mod.dispose_engine()
    store_mod.store.characters.clear()
    store_mod.store.scenes.clear()
    store_mod.store.worlds.clear()


def _make_character(character_id: str = "char_001", **extras) -> dict:
    base = {
        "character_id": character_id,
        "name": "Alice",
        "world_id": "w1",
        "physical": {"stamina_level": "fresh", "health_status": "healthy"},
        "mental": {"morale_level": "neutral"},
        "inventory": {"items": [{"item_id": "potion", "quantity": 2}]},
        "memories": ["start"],
        "relationships": {"npc_a": "neutral"},
    }
    base.update(extras)
    return base


def _make_scene(round_num: int, character_id: str = "char_001") -> dict:
    return {
        "round": round_num,
        "character_id": character_id,
        "narrative": f"Scene at round {round_num}",
        "choices": [
            {"id": "opt_01", "text": "do A", "intent_category": "environment", "attitude_options": []},
        ],
        "state_change_computed": {"stamina": {"old": "fresh", "new": "slight_breath"}},
    }


# ============================================
# Roundtrip tests
# ============================================

class TestPersistenceRoundtrip:
    @pytest.mark.asyncio
    async def test_persistence_roundtrip(self, fresh_db):
        """Save a character, load it back, verify equality on header + nested state."""
        from backend import persistence
        char = _make_character()
        await persistence.save_character(char)
        loaded = await persistence.load_character("char_001")
        assert loaded is not None
        assert loaded["character_id"] == "char_001"
        assert loaded["name"] == "Alice"
        assert loaded["world_id"] == "w1"
        assert loaded["physical"]["stamina_level"] == "fresh"
        assert loaded["mental"]["morale_level"] == "neutral"
        assert loaded["inventory"]["items"] == [{"item_id": "potion", "quantity": 2}]
        assert loaded["memories"] == ["start"]
        assert loaded["relationships"] == {"npc_a": "neutral"}

    @pytest.mark.asyncio
    async def test_persistence_update_existing(self, fresh_db):
        """Saving the same character_id twice should update, not duplicate."""
        from backend import persistence
        from backend.db import get_active_url
        from sqlalchemy import select, func
        from backend.orm import Character as CharacterORM
        from backend.db import get_session

        await persistence.save_character(_make_character(name="Alice1"))
        await persistence.save_character(_make_character(name="Alice2"))
        loaded = await persistence.load_character("char_001")
        assert loaded["name"] == "Alice2"

        # Confirm only one row
        async with get_session() as session:
            count = (await session.execute(
                select(func.count()).select_from(CharacterORM)
                .where(CharacterORM.character_id == "char_001")
            )).scalar_one()
        assert count == 1

    @pytest.mark.asyncio
    async def test_persistence_load_missing_returns_none(self, fresh_db):
        from backend import persistence
        loaded = await persistence.load_character("does_not_exist")
        assert loaded is None


class TestPersistenceSceneHistory:
    @pytest.mark.asyncio
    async def test_persistence_scene_history(self, fresh_db):
        """Save 3 scenes, load with limit=2 → expect 2 returned."""
        from backend import persistence
        for r in (1, 2, 3):
            await persistence.save_scene("char_001", _make_scene(round_num=r))
        latest_two = await persistence.load_scenes("char_001", limit=2)
        assert len(latest_two) == 2
        # Newest 2 first by insertion order, then we return chronologically
        # So we expect rounds 2 and 3 (ascending)
        rounds = [s["round"] for s in latest_two]
        assert rounds == [2, 3]

    @pytest.mark.asyncio
    async def test_persistence_scene_history_default_limit(self, fresh_db):
        """Default limit is 20 — fewer scenes → all returned."""
        from backend import persistence
        for r in range(1, 4):
            await persistence.save_scene("char_001", _make_scene(round_num=r))
        scenes = await persistence.load_scenes("char_001")
        assert len(scenes) == 3

    @pytest.mark.asyncio
    async def test_persistence_scene_history_no_scenes(self, fresh_db):
        from backend import persistence
        scenes = await persistence.load_scenes("nobody")
        assert scenes == []


class TestPersistenceWorldRoundtrip:
    @pytest.mark.asyncio
    async def test_persistence_world_roundtrip(self, fresh_db):
        from backend import persistence
        config = {
            "world_meta": {"name": "TestWorld", "version": "1.0"},
            "physical_rules": ["gravity", "no_magic"],
            "npcs": ["npc_a", "npc_b"],
        }
        await persistence.save_world("w1", config)
        loaded = await persistence.load_world("w1")
        assert loaded == config

    @pytest.mark.asyncio
    async def test_persistence_world_overwrite(self, fresh_db):
        from backend import persistence
        await persistence.save_world("w1", {"v": 1})
        await persistence.save_world("w1", {"v": 2})
        loaded = await persistence.load_world("w1")
        assert loaded == {"v": 2}

    @pytest.mark.asyncio
    async def test_persistence_load_missing_world(self, fresh_db):
        from backend import persistence
        loaded = await persistence.load_world("does_not_exist")
        assert loaded is None


# ============================================
# Fallback tests
# ============================================

class TestPersistenceFallback:
    @pytest.mark.asyncio
    async def test_persistence_fallback_to_memory(self, fresh_memory, caplog):
        """
        Force every DB engine creation to fail, then call save_character.
        The save should fall back to the in-memory store and not raise.
        """
        import logging
        from backend import persistence, store

        char = _make_character()
        with caplog.at_level(logging.WARNING, logger="backend.persistence"):
            await persistence.save_character(char)

        # The in-memory store should now contain the character
        assert "char_001" in store.store.characters
        loaded_mem = store.store.get_character("char_001")
        assert loaded_mem is not None
        assert loaded_mem["name"] == "Alice"

        # load_character should also be able to find it (via the same fallback)
        loaded = await persistence.load_character("char_001")
        assert loaded is not None
        assert loaded["character_id"] == "char_001"

    @pytest.mark.asyncio
    async def test_persistence_fallback_scene(self, fresh_memory):
        """Scenes also fall back to the in-memory store."""
        from backend import persistence, store
        await persistence.save_scene("c1", _make_scene(1, "c1"))
        history = await persistence.load_scenes("c1")
        assert len(history) == 1
        assert history[0]["round"] == 1

    @pytest.mark.asyncio
    async def test_persistence_fallback_world(self, fresh_memory):
        """Worlds also fall back to the in-memory store."""
        from backend import persistence, store
        await persistence.save_world("w1", {"foo": "bar"})
        loaded = await persistence.load_world("w1")
        assert loaded == {"foo": "bar"}


# ============================================
# Reset helper
# ============================================

class TestPersistenceReset:
    @pytest.mark.asyncio
    async def test_reset_all(self, fresh_db):
        from backend import persistence
        await persistence.save_character(_make_character())
        await persistence.save_scene("char_001", _make_scene(1))
        await persistence.save_world("w1", {"x": 1})
        await persistence.reset_all()
        assert await persistence.load_character("char_001") is None
        assert await persistence.load_scenes("char_001") == []
        assert await persistence.load_world("w1") is None

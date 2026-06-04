"""
Unit tests for ``CharacterStateMachine.apply_round`` and related logic.

We use an in-memory SQLite (via aiosqlite) as the persistence backend so the
state machine's save_character() call doesn't fail. The persistence layer's
fallback to the in-memory store would also work, but using real SQLite gives
us extra confidence that roundtrips are clean.

Each test uses a fresh DB file to avoid cross-test contamination.
"""
from __future__ import annotations

import os
import sys
import asyncio
import tempfile
import pytest
import pytest_asyncio

# Ensure the backend package is on sys.path even if pytest is run from
# a different cwd.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================
# DB environment: use a per-test temp SQLite file
# ============================================

@pytest_asyncio.fixture
async def fresh_db(monkeypatch, tmp_path):
    """Per-test SQLite DB; cleans up the engine after the test.

    Persistence is NOT mocked by default ??tests that don't care about DB
    writes can ignore the I/O overhead, and tests that assert persistence
    get the real deal. Tests that need to suppress I/O can opt in via the
    `silent_persist` fixture.
    """
    db_path = tmp_path / "state_machine_test.db"
    monkeypatch.setenv("SANDBOX_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    # Reset the module-level engine cache so each test gets a clean slate
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
async def silent_persist(monkeypatch):
    """
    Suppress persistence I/O for state machine tests that don't assert it.
    The state machine's _persist_sync would otherwise schedule background
    tasks that race with test teardown, producing pytest-asyncio warnings.
    """
    from backend import store as store_mod

    async def _fake_save(char):
        store_mod.store.save_character(char)

    # Patch via the module's __dict__ so the state machine (which imports
    # the module rather than the function) picks up the fake.
    import backend.persistence as _pers_mod
    monkeypatch.setattr(_pers_mod, "save_character", _fake_save)
    yield
    # monkeypatch.undo is automatic


def _fresh_initial_state(character_id: str = "char_test_001") -> dict:
    """Minimal valid character state for tests."""
    return {
        "character_id": character_id,
        "name": "TestHero",
        "world_id": "default",
        "physical": {
            "stamina_level": "fresh",
            "health_status": "healthy",
            "active_effects": [],
        },
        "mental": {"morale_level": "neutral"},
        "inventory": {"items": []},
        "memories": [],
        "relationships": {},
    }


def _make_scene_output(
    stamina_new: str = "fresh",
    health_new: str = "healthy",
    morale_new: str = "neutral",
    new_status_tags=None,
    removed_status_tags=None,
    items_consumed=None,
    new_memories=None,
    relationship_changes=None,
) -> dict:
    """Build a scene_output dict in the format SceneAgent would produce."""
    return {
        "round": 1,
        "character_id": "char_test_001",
        "narrative": "Test scene",
        "choices": [],
        "state_change_computed": {
            "stamina": {"old": "fresh", "new": stamina_new, "reason": "test-reason"},
            "health": {"old": "healthy", "new": health_new, "reason": "test-reason"},
            "morale": {"old": "neutral", "new": morale_new, "reason": "test-reason"},
            "new_status_tags": new_status_tags or [],
            "removed_status_tags": removed_status_tags or [],
            "items_consumed": items_consumed or [],
            "new_memories": new_memories or [],
            "relationship_changes": relationship_changes or [],
            "blocked": [],
        },
    }


# ============================================
# Tests
# ============================================

class TestApplyRoundBasic:
    """Sanity tests for the basic apply_round flow."""

    @pytest.mark.asyncio
    async def test_apply_round_basic(self, silent_persist):
        """stamina_delta=1 ??fresh becomes slight_breath."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(stamina_new="slight_breath")
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert new_state["physical"]["stamina_level"] == "slight_breath"
        assert sm.round == 1

    @pytest.mark.asyncio
    async def test_apply_round_returns_dict(self, silent_persist):
        """apply_round returns the new state as a dict."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output()
        out = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert isinstance(out, dict)
        assert out["character_id"] == "char_test_001"


class TestApplyRoundStatusTags:
    """Tag add / remove / mutex eviction."""

    @pytest.mark.asyncio
    async def test_apply_round_add_tag(self, silent_persist):
        """A new tag is appended to active_effects."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(new_status_tags=["wounded"])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert "wounded" in new_state["physical"]["active_effects"]

    @pytest.mark.asyncio
    async def test_apply_round_remove_tag(self, silent_persist):
        """A removed tag is dropped."""
        from backend.state_machine import CharacterStateMachine
        init = _fresh_initial_state()
        init["physical"]["active_effects"] = ["wounded", "poisoned"]
        sm = CharacterStateMachine("char_test_001", init)
        scene = _make_scene_output(removed_status_tags=["poisoned"])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert "poisoned" not in new_state["physical"]["active_effects"]
        assert "wounded" in new_state["physical"]["active_effects"]

    @pytest.mark.asyncio
    async def test_apply_round_max_tags_mutex(self, silent_persist):
        """With 8 tags, adding a 9th high-priority tag evicts the lowest."""
        from backend.state_machine import CharacterStateMachine
        init = _fresh_initial_state()
        # 8 tags, all priority 5, except "t_low" which is priority 1
        init["physical"]["active_effects"] = [
            "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t_low",
        ]
        sm = CharacterStateMachine("char_test_001", init)
        for name, prio in [
            ("t1", 5), ("t2", 5), ("t3", 5), ("t4", 5),
            ("t5", 5), ("t6", 5), ("t7", 5), ("t_low", 1),
        ]:
            sm.tag_priorities[name] = prio

        scene = _make_scene_output(new_status_tags=[
            {"name": "NEW_HIGH", "priority": 10},
        ])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        effects = new_state["physical"]["active_effects"]
        # Lowest-priority tag evicted
        assert "t_low" not in effects
        # New high-priority tag added
        assert "NEW_HIGH" in effects
        # 8 total
        assert len(effects) == 8
        # Priority recorded
        assert sm.tag_priorities["NEW_HIGH"] == 10
        assert "t_low" not in sm.tag_priorities

    @pytest.mark.asyncio
    async def test_apply_round_add_existing_tag_updates_priority(self, silent_persist):
        """Adding a tag already present just refreshes its priority."""
        from backend.state_machine import CharacterStateMachine
        init = _fresh_initial_state()
        init["physical"]["active_effects"] = ["t1"]
        sm = CharacterStateMachine("char_test_001", init)
        sm.tag_priorities["t1"] = 5

        scene = _make_scene_output(new_status_tags=[{"name": "t1", "priority": 9}])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert new_state["physical"]["active_effects"] == ["t1"]
        assert sm.tag_priorities["t1"] == 9


class TestApplyRoundItems:
    """Item consumption (quantity decrement + removal at zero)."""

    @pytest.mark.asyncio
    async def test_apply_round_consume_item(self, silent_persist):
        """Consuming 1 of 3 potions leaves 2."""
        from backend.state_machine import CharacterStateMachine
        init = _fresh_initial_state()
        init["inventory"]["items"] = [{"item_id": "potion", "quantity": 3}]
        sm = CharacterStateMachine("char_test_001", init)
        scene = _make_scene_output(items_consumed=[{"item_id": "potion", "quantity": 1}])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        items = new_state["inventory"]["items"]
        assert len(items) == 1
        assert items[0]["item_id"] == "potion"
        assert items[0]["quantity"] == 2

    @pytest.mark.asyncio
    async def test_apply_round_consume_to_zero(self, silent_persist):
        """Consuming the last potion removes it from inventory."""
        from backend.state_machine import CharacterStateMachine
        init = _fresh_initial_state()
        init["inventory"]["items"] = [{"item_id": "potion", "quantity": 1}]
        sm = CharacterStateMachine("char_test_001", init)
        scene = _make_scene_output(items_consumed=[{"item_id": "potion", "quantity": 1}])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert new_state["inventory"]["items"] == []

    @pytest.mark.asyncio
    async def test_apply_round_consume_unknown_item_noop(self, silent_persist):
        """Consuming an item not in inventory is a silent no-op."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(items_consumed=[{"item_id": "ghost", "quantity": 1}])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert new_state["inventory"]["items"] == []


class TestApplyRoundMemories:
    """Memory addition (with dedup)."""

    @pytest.mark.asyncio
    async def test_apply_round_add_memory(self, silent_persist):
        """A new memory is appended."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(new_memories=["met the merchant"])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert "met the merchant" in new_state["memories"]

    @pytest.mark.asyncio
    async def test_apply_round_memory_dedup(self, silent_persist):
        """Duplicate memories are not re-added."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(new_memories=["event A", "event A", "event B"])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert new_state["memories"].count("event A") == 1
        assert new_state["memories"].count("event B") == 1


class TestApplyRoundRelationships:
    """Relationship level update + validation."""

    @pytest.mark.asyncio
    async def test_apply_round_update_relationship(self, silent_persist):
        """A valid relationship level is written."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(relationship_changes=[
            {"npc_id": "npc_a", "level": "friendly"},
        ])
        new_state = sm.apply_round({"character_id": "char_test_001"}, scene)
        assert new_state["relationships"]["npc_a"] == "friendly"

    @pytest.mark.asyncio
    async def test_apply_round_invalid_relationship(self, silent_persist):
        """An invalid level raises ValueError."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(relationship_changes=[
            {"npc_id": "npc_a", "level": "madly_in_love"},
        ])
        with pytest.raises(ValueError) as exc_info:
            sm.apply_round({"character_id": "char_test_001"}, scene)
        assert "madly_in_love" in str(exc_info.value)
        # State was not corrupted (rolls back partially ??relationships dict unchanged)
        assert "npc_a" not in sm.state.get("relationships", {})

    @pytest.mark.asyncio
    async def test_apply_round_relationship_promotion(self, silent_persist):
        """Going from neutral ??friendly ??trusted works."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.state["relationships"]["npc_a"] = "neutral"
        for level in ("friendly", "trusted", "devoted"):
            scene = _make_scene_output(relationship_changes=[
                {"npc_id": "npc_a", "level": level},
            ])
            sm.apply_round({"character_id": "char_test_001"}, scene)
        assert sm.state["relationships"]["npc_a"] == "devoted"


class TestApplyRoundPersistence:
    """After apply_round, the new state is persisted."""

    @pytest.mark.asyncio
    async def test_apply_round_persists_to_db(self, fresh_db):
        """Reload the character from DB and verify it's the new state."""
        from backend.state_machine import CharacterStateMachine
        from backend import persistence
        # init_db() will run on first save_character call (fresh_db already
        # points SANDBOX_DATABASE_URL at a per-test tmp file).
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        scene = _make_scene_output(
            stamina_new="slight_breath",
            new_status_tags=["wounded"],
        )
        sm.apply_round({"character_id": "char_test_001"}, scene)
        # Wait for the background save task scheduled by _persist_sync to drain
        import asyncio
        await asyncio.sleep(0.1)
        # Explicit re-save to guarantee completion
        await persistence.save_character(sm.state)
        loaded = await persistence.load_character("char_test_001")
        assert loaded is not None
        assert loaded["physical"]["stamina_level"] == "slight_breath"
        assert "wounded" in loaded["physical"]["active_effects"]


class TestAddRemoveStatusTagDirect:
    """Direct API on CharacterStateMachine for adding / removing tags."""

    @pytest.mark.asyncio
    async def test_add_status_tag(self, silent_persist):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        assert sm.add_status_tag("wounded", priority=7) is True
        assert "wounded" in sm.state["physical"]["active_effects"]
        assert sm.tag_priorities["wounded"] == 7

    @pytest.mark.asyncio
    async def test_remove_status_tag(self, silent_persist):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.add_status_tag("wounded")
        assert sm.remove_status_tag("wounded") is True
        assert "wounded" not in sm.state["physical"]["active_effects"]

    @pytest.mark.asyncio
    async def test_remove_missing_tag(self, silent_persist):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        assert sm.remove_status_tag("never_added") is False

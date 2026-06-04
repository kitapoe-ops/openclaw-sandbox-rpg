"""
Tier 1 engine tests for v3.7 CharacterStateMachine.

These tests verify the core state machine logic WITHOUT requiring
backend.store or backend.persistence — they test the engine layer
in isolation against the v3.7 main codebase.
"""
import pytest
from datetime import datetime, timezone

UTC = timezone.utc


def _fresh_initial_state():
    """Return a clean character state for testing."""
    return {
        "character_id": "char_test_001",
        "name": "Test Hero",
        "world_id": "test_world",
        "physical": {
            "stamina_level": "fresh",
            "health_status": "healthy",
            "active_effects": [],
        },
        "mental": {
            "morale_level": "neutral",
        },
        "attitude": {},
        "inventory": {"items": []},
        "memories": [],
        "relationships": {},
    }


class TestAddRemoveStatusTagDirect:
    """Direct API on CharacterStateMachine for adding / removing tags."""

    def test_add_status_tag(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        assert sm.add_status_tag("wounded", priority=7) is True
        assert "wounded" in sm.state["physical"]["active_effects"]

    def test_remove_status_tag(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.add_status_tag("wounded")
        assert sm.remove_status_tag("wounded") is True
        assert "wounded" not in sm.state["physical"]["active_effects"]

    def test_remove_missing_tag(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        assert sm.remove_status_tag("never_added") is False

    def test_add_existing_tag(self):
        """Adding an existing tag refreshes priority."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.add_status_tag("wounded", priority=5)
        sm.add_status_tag("wounded", priority=10)  # update priority
        # Still only 1 entry
        assert sm.state["physical"]["active_effects"].count("wounded") == 1

    def test_max_8_tags_with_mutex(self):
        """When 8 tags present, adding a 9th evicts the lowest-priority."""
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        for i in range(8):
            sm.add_status_tag(f"tag_{i}", priority=i)
        # All 8 tags present
        assert len(sm.state["physical"]["active_effects"]) == 8
        # Add 9th with priority 99
        sm.add_status_tag("important", priority=99)
        # Now 8 tags remain, lowest-priority one evicted
        assert len(sm.state["physical"]["active_effects"]) == 8
        assert "important" in sm.state["physical"]["active_effects"]
        # The lowest-priority (tag_0, priority 0) should be gone
        assert "tag_0" not in sm.state["physical"]["active_effects"]


class TestApplyRoundBasic:
    """apply_round: basic state changes."""

    def test_apply_round_stamina_change(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        result = sm.apply_round(
            player_input={"choice": {"option_id": "opt_01"}},
            scene_output={
                "state_changes": {
                    "stamina": {"old": "fresh", "new": "slight_breath", "reason": "長途行軍"},
                }
            },
        )
        assert result["physical"]["stamina_level"] == "slight_breath"

    def test_apply_round_health_change(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.apply_round(
            player_input={"choice": {"option_id": "opt_01"}},
            scene_output={
                "state_changes": {
                    "health": {"old": "healthy", "new": "wounded", "reason": "戰鬥受傷"},
                }
            },
        )
        assert sm.state["physical"]["health_status"] == "wounded"

    def test_apply_round_morale_change(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.apply_round(
            player_input={"choice": {"option_id": "opt_01"}},
            scene_output={
                "state_changes": {
                    "morale": {"old": "neutral", "new": "anxious", "reason": "目睹慘劇"},
                }
            },
        )
        assert sm.state["mental"]["morale_level"] == "anxious"


class TestApplyRoundItems:
    """apply_round: item consumption."""

    def test_consume_item_partial(self):
        from backend.state_machine import CharacterStateMachine
        state = _fresh_initial_state()
        state["inventory"] = {"items": [{"item_id": "potion", "quantity": 3}]}
        sm = CharacterStateMachine("char_test_001", state)
        sm.apply_round(
            player_input={},
            scene_output={"state_changes": {"items_consumed": [{"item_id": "potion", "quantity": 1}]}},
        )
        items = sm.state["inventory"]["items"]
        potion = next(i for i in items if i["item_id"] == "potion")
        assert potion["quantity"] == 2

    def test_consume_item_to_zero_removed(self):
        from backend.state_machine import CharacterStateMachine
        state = _fresh_initial_state()
        state["inventory"] = {"items": [{"item_id": "potion", "quantity": 1}]}
        sm = CharacterStateMachine("char_test_001", state)
        sm.apply_round(
            player_input={},
            scene_output={"state_changes": {"items_consumed": [{"item_id": "potion", "quantity": 1}]}},
        )
        assert not any(i["item_id"] == "potion" for i in sm.state["inventory"]["items"])

    def test_consume_unknown_item_noop(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        # Should not raise
        sm.apply_round(
            player_input={},
            scene_output={"state_changes": {"items_consumed": [{"item_id": "ghost", "quantity": 1}]}},
        )
        assert sm.state["inventory"]["items"] == []


class TestApplyRoundMemories:
    """apply_round: memory accumulation."""

    def test_add_memory(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.apply_round(
            player_input={},
            scene_output={"state_changes": {"new_memories": ["第一次冒險"]}},
        )
        assert "第一次冒險" in sm.state["memories"]

    def test_add_multiple_memories(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.apply_round(
            player_input={},
            scene_output={"state_changes": {"new_memories": ["mem1", "mem2", "mem3"]}},
        )
        assert sm.state["memories"] == ["mem1", "mem2", "mem3"]


class TestApplyRoundRelationships:
    """apply_round: relationship updates."""

    def test_update_relationship(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.apply_round(
            player_input={},
            scene_output={
                "state_changes": {
                    "relationship_changes": [{"npc_id": "npc_merchant", "new": "friendly"}]
                }
            },
        )
        assert sm.state["relationships"]["npc_merchant"] == "friendly"

    def test_invalid_relationship_silently_ignored(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        # Should not raise (no enforcement at apply_round level)
        sm.apply_round(
            player_input={},
            scene_output={
                "state_changes": {
                    "relationship_changes": [{"npc_id": "npc_x", "new": "banana"}]
                }
            },
        )
        assert sm.state["relationships"]["npc_x"] == "banana"


class TestStateChangeSchema:
    """Verify state_changes schema is {old, new, reason} format."""

    def test_v37_supports_new_format(self):
        from backend.state_machine import CharacterStateMachine
        sm = CharacterStateMachine("char_test_001", _fresh_initial_state())
        sm.apply_round(
            player_input={},
            scene_output={
                "state_changes": {
                    "stamina": {"old": "fresh", "new": "slight_breath", "reason": "test"},
                    "health": {"old": "healthy", "new": "wounded", "reason": "test"},
                }
            },
        )
        assert sm.state["physical"]["stamina_level"] == "slight_breath"
        assert sm.state["physical"]["health_status"] == "wounded"


class TestPhysicsLockTier1:
    """Tier 1: physics_lock core tests (no LLM rewrite)."""

    def test_basic_validation(self):
        from backend.physics_lock import PhysicsLock
        lock = PhysicsLock()
        state = {"physical": {"active_effects": []}}
        is_valid, reason = lock.validate_choice("用劍斬向敵人", state)
        assert is_valid is True
        assert reason == ""

    def test_forbidden_action(self):
        from backend.physics_lock import PhysicsLock
        lock = PhysicsLock()
        state = {"physical": {"active_effects": ["雙腿嚴重骨折"]}}
        is_valid, reason = lock.validate_choice("狂奔逃離現場", state)
        assert is_valid is False
        assert "雙腿嚴重骨折" in reason

    def test_validate_choices_batch_sync(self):
        """v3.7 PhysicsLock.validate_choices is sync (no LLM rewrite path yet)."""
        from backend.physics_lock import PhysicsLock
        lock = PhysicsLock()
        state = {"physical": {"active_effects": ["左臂骨折"]}}
        choices = [
            {"id": "opt_01", "text": "用雙手握劍攻擊"},
            {"id": "opt_02", "text": "用單手握劍"},
        ]
        # Sync call (not async)
        validated = lock.validate_choices(choices, state)
        assert validated[0].get("physics_lock_rewritten") is True
        assert validated[1].get("physics_lock_rewritten") is None

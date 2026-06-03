"""
Unit tests for PhysicsLock v2.0.
"""
import pytest
from backend.physics_lock import PhysicsLock


class TestPhysicsLock:
    """Test physics lock validation."""

    def test_no_active_effects(self):
        lock = PhysicsLock()
        state = {"physical": {"active_effects": []}}
        is_valid, reason = lock.validate_choice("用劍斬向敵人", state)
        assert is_valid is True
        assert reason == ""

    def test_forbidden_action_detected(self):
        lock = PhysicsLock()
        state = {"physical": {"active_effects": ["雙腿嚴重骨折"]}}
        is_valid, reason = lock.validate_choice("狂奔逃離現場", state)
        assert is_valid is False
        assert "雙腿嚴重骨折" in reason

    def test_multiple_active_effects(self):
        lock = PhysicsLock()
        state = {"physical": {"active_effects": ["失明", "聾啞"]}}
        is_valid, reason = lock.validate_choice("觀察周圍環境", state)
        assert is_valid is False

    def test_custom_rules(self):
        custom = {"custom_state": ["custom_forbidden_action"]}
        lock = PhysicsLock(custom_rules=custom)
        state = {"physical": {"active_effects": ["custom_state"]}}
        is_valid, reason = lock.validate_choice("custom_forbidden_action here", state)
        assert is_valid is False

    def test_validate_choices_batch(self):
        lock = PhysicsLock()
        state = {"physical": {"active_effects": ["左臂骨折"]}}
        choices = [
            {"id": "opt_01", "text": "用雙手握劍攻擊"},
            {"id": "opt_02", "text": "用單手揮劍"},
            {"id": "opt_03", "text": "投擲匕首"},
        ]
        validated = lock.validate_choices(choices, state)
        # opt_01 and opt_03 should be flagged
        assert validated[0].get("physics_lock_rewritten") is True
        assert validated[1].get("physics_lock_rewritten") is None
        assert validated[2].get("physics_lock_rewritten") is True

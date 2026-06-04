"""
Unit tests for SemanticGradient + StateChangeCalculator.
"""
import pytest
from backend.semantic_gradient import (
    SemanticGradient,
    StateChangeCalculator,
    StateChange,
    DEFAULT_STAMINA_LEVELS,
    DEFAULT_HEALTH_LEVELS,
    DEFAULT_MORALE_LEVELS,
)


# ============================================
# SemanticGradient core tests
# ============================================

class TestSemanticGradient:
    """Test semantic gradient transitions."""

    def test_initialization(self):
        g = SemanticGradient(["a", "b", "c", "d"], current="b")
        assert g.current == "b"
        assert g.current_index == 1

    def test_shift_up(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="fresh")
        assert g.shift(+1) is True
        assert g.current == "slight_breath"

    def test_shift_down(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="muscle_ache")
        assert g.shift(-1) is True
        assert g.current == "slight_breath"

    def test_prevent_skipping(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="fresh")
        # Try to skip from fresh to muscle_ache (+2)
        assert g.shift(+2) is False
        assert g.current == "fresh"

    def test_safe_environment_bonus(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="muscle_ache")
        # In safe environment, can shift -2
        assert g.shift(-2, environment="safe") is True
        assert g.current == "fresh"

    def test_collapse_irreversible(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted", "collapse"], current="collapse")
        # Cannot recover from collapse
        assert g.shift(-1) is False
        assert g.current == "collapse"

    def test_out_of_bounds(self):
        g = SemanticGradient(["a", "b", "c"], current="a")
        # Cannot go below index 0
        assert g.shift(-1) is False
        assert g.current == "a"

        # Cannot go beyond last index
        g2 = SemanticGradient(["a", "b", "c"], current="c")
        assert g2.shift(+1) is False
        assert g2.current == "c"

    def test_to_dict(self):
        g = SemanticGradient(["a", "b", "c", "d"], current="b")
        d = g.to_dict()
        assert d == {"current": "b", "current_index": 1, "max_level": 3}


# ============================================
# StateChangeCalculator tests
# ============================================

class TestStateChangeCalculator:
    """Test the 5-step state change calculation."""

    def _make_state(self, stamina="fresh", health="healthy", morale="neutral", tags=None):
        return {
            "character_id": "char_001",
            "physical": {
                "stamina": stamina,
                "health": health,
                "active_effects": tags or [],
            },
            "mental": {"morale": morale},
        }

    def test_zero_delta(self):
        """No LLM-suggested changes = no change."""
        calc = StateChangeCalculator()
        state = self._make_state()
        result = calc.calculate(
            character_state=state,
            player_input={"choice": {"option_id": "opt_01"}},
            scene_output={"state_changes": {}, "location": {}},
        )
        assert result.stamina_old == "fresh"
        assert result.stamina_new == "fresh"
        assert result.health_new == "healthy"
        assert result.morale_new == "neutral"
        assert result.blocked == []

    def test_normal_shift(self):
        """LLM suggests +1 stamina (consumption), applied normally."""
        calc = StateChangeCalculator()
        state = self._make_state(stamina="fresh")
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={"state_changes": {"stamina_delta": 1}, "location": {}},
        )
        assert result.stamina_new == "slight_breath"
        assert result.blocked == []

    def test_skip_blocked(self):
        """LLM suggests +3 stamina; should be clamped to +1."""
        calc = StateChangeCalculator()
        state = self._make_state(stamina="fresh")
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={"state_changes": {"stamina_delta": 3}, "location": {}},
        )
        # fresh → slight_breath (clamped to +1)
        assert result.stamina_new == "slight_breath"
        assert len(result.blocked) == 1
        assert result.blocked[0]["field"] == "stamina"
        assert result.blocked[0]["attempted_delta"] == 3

    def test_safe_env_recovery_bonus(self):
        """Safe env + -2 delta = allowed (recovery bonus extends to -2)."""
        calc = StateChangeCalculator()
        state = self._make_state(stamina="muscle_ache")
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {"stamina_delta": -2},
                "location": {"environment": "safe"},
            },
        )
        # muscle_ache → fresh (safe env allows -2)
        assert result.stamina_new == "fresh"
        # No block because safe env extends max_shift to 2
        assert result.blocked == []

    def test_unsafe_blocks_recovery(self):
        """Unsafe env: -2 is blocked, clamped to -1."""
        calc = StateChangeCalculator()
        state = self._make_state(stamina="muscle_ache")
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {"stamina_delta": -2},
                "location": {"environment": "unsafe"},
            },
        )
        # muscle_ache → slight_breath (clamped to -1)
        assert result.stamina_new == "slight_breath"
        assert len(result.blocked) == 1
        assert result.blocked[0]["attempted_delta"] == -2

    def test_collapse_protection(self):
        """Stamina should not exceed 'collapse' level."""
        calc = StateChangeCalculator()
        state = self._make_state(stamina="exhausted")
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={"state_changes": {"stamina_delta": 5}, "location": {}},
        )
        # exhausted → collapse (clamped to +1)
        assert result.stamina_new == "collapse"
        assert result.blocked[0]["attempted_delta"] == 5

    def test_multi_axis_changes(self):
        """Multiple axes can change in one round."""
        calc = StateChangeCalculator()
        state = self._make_state(stamina="fresh", health="healthy", morale="neutral")
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {
                    "stamina_delta": 1,   # consumption
                    "health_delta": 1,    # damage
                    "morale_delta": -1,   # recovery
                },
                "location": {},
            },
        )
        assert result.stamina_new == "slight_breath"
        assert result.health_new == "wounded"
        assert result.morale_new == "calm"
        assert result.blocked == []

    def test_tag_addition(self):
        """New status tags are added."""
        calc = StateChangeCalculator()
        state = self._make_state(tags=["左臂骨折"])
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {
                    "new_status_tags": ["右臂骨折", "輕微瘀傷"],
                },
                "location": {},
            },
        )
        assert "右臂骨折" in result.new_status_tags
        assert "輕微瘀傷" in result.new_status_tags

    def test_tag_limit_enforced(self):
        """Adding too many tags is trimmed, with block entry."""
        calc = StateChangeCalculator(world_parameter_config={"max_tags_per_character": 8})
        state = self._make_state(tags=[f"tag_{i}" for i in range(7)])
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {
                    "new_status_tags": ["tag_new_1", "tag_new_2", "tag_new_3"],
                },
                "location": {},
            },
        )
        # 7 + 3 = 10 > 8, should allow only 1
        assert len(result.new_status_tags) == 1
        assert result.new_status_tags[0] == "tag_new_1"
        assert any("active_effects" in b.get("field", "") for b in result.blocked)

    def test_world_config_override(self):
        """Custom world config can override default levels."""
        custom_config = {
            "semantic_states": {
                "stamina": ["vibrant", "tired", "drowsy"],
            }
        }
        calc = StateChangeCalculator(world_parameter_config=custom_config)
        state = self._make_state(stamina="vibrant")
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={"state_changes": {"stamina_delta": 1}, "location": {}},
        )
        assert result.stamina_new == "tired"

    def test_to_dict_serialization(self):
        """StateChange.to_dict() should produce schema-compliant output."""
        calc = StateChangeCalculator()
        state = self._make_state()
        result = calc.calculate(
            character_state=state,
            player_input={},
            scene_output={
                "state_changes": {"stamina_delta": 1, "new_memories": ["第一次冒險"]},
                "location": {},
            },
        )
        d = result.to_dict()
        # Schema-compliant shape: {old, new, reason} on each axis
        for axis in ("stamina", "health", "morale"):
            assert axis in d
            assert set(d[axis].keys()) >= {"old", "new", "reason"}
            assert isinstance(d[axis]["reason"], str) and d[axis]["reason"]
        # The stamina change is the one that actually moved
        assert d["stamina"]["old"] == "fresh"
        assert d["stamina"]["new"] == "slight_breath"
        # Collections are preserved
        assert "第一次冒險" in d["new_memories"]
        assert d["character_id"] == "char_001"
        # No legacy _delta fields leak into output
        for bad in ("stamina_delta", "health_delta", "morale_delta"):
            assert bad not in d

"""
Semantic Gradient Manager
==========================
Core state machine for semantic state transitions.
No numbers — only semantic bucket labels.

Reference: docs/SCHEMAS/character_state.schema.json
           docs/SCHEMAS/world_parameter.yaml (semantic_states section)
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ============================================
# Default Semantic Levels
# ============================================

class StaminaLevel(str, Enum):
    FRESH = "fresh"
    SLIGHT_BREATH = "slight_breath"
    MUSCLE_ACHE = "muscle_ache"
    EXHAUSTED = "exhausted"
    COLLAPSE = "collapse"


class HealthLevel(str, Enum):
    HEALTHY = "healthy"
    WOUNDED = "wounded"
    SEVERELY_WOUNDED = "severely_wounded"
    DYING = "dying"
    DEAD = "dead"


class MoraleLevel(str, Enum):
    ELATED = "elated"
    CALM = "calm"
    NEUTRAL = "neutral"
    ANXIOUS = "anxious"
    DESPAIR = "despair"


# ============================================
# Semantic Gradient Class
# ============================================

@dataclass
class SemanticGradient:
    """
    A semantic gradient enforces:
    - No skipping levels (max ±1 per round)
    - Safe environment allows -2 (recovery)
    - Collapse is irreversible (triggers soul transfer)

    Usage:
        stamina = SemanticGradient([...], current="fresh")
        stamina.shift(-1, environment="unsafe")  # fresh → slight_breath
    """
    levels: list[str]
    current: str
    max_shift_per_round: int = 1
    safe_environment_bonus: int = 1

    def __post_init__(self):
        if self.current not in self.levels:
            raise ValueError(f"Current level '{self.current}' not in levels {self.levels}")
        self._current_index = self.levels.index(self.current)

    @property
    def current_index(self) -> int:
        return self._current_index

    def shift(self, delta: int, environment: str = "neutral") -> bool:
        """
        Attempt to shift the semantic level.
        Returns True if successful, False if blocked.
        """
        max_shift = self.max_shift_per_round
        if environment == "safe" and delta < 0:
            # Recovery in safe environment
            max_shift += self.safe_environment_bonus

        if abs(delta) > max_shift:
            return False  # Prevent level skipping

        new_index = self._current_index + delta
        if new_index < 0 or new_index >= len(self.levels):
            return False  # Out of bounds

        # Collapse is irreversible
        if self.levels[self._current_index] == "collapse" and delta < 0:
            return False

        self._current_index = new_index
        self.current = self.levels[new_index]
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "current_index": self._current_index,
            "max_level": len(self.levels) - 1,
        }


# ============================================
# State Change Calculator
# ============================================

@dataclass
class StateChange:
    """Result of a state calculation."""
    character_id: str
    stamina_old: str
    stamina_new: str
    health_old: str
    health_new: str
    morale_old: str
    morale_new: str
    new_status_tags: list[str] = field(default_factory=list)
    removed_status_tags: list[str] = field(default_factory=list)
    items_consumed: list[dict[str, Any]] = field(default_factory=list)
    new_memories: list[str] = field(default_factory=list)
    relationship_changes: list[dict[str, Any]] = field(default_factory=list)


class StateChangeCalculator:
    """
    Calculates state changes based on player action + environment.
    Used by Sub Agent.

    Implements the 5-step calculation:
    1. Read player_input.choice.option_id
    2. Read scene_output.state_changes (LLM-suggested)
    3. Validate against semantic gradient rules (±1 per round, env bonus)
    4. Apply shifts (clamped, with safe env recovery bonus)
    5. Return StateChange
    """

    def __init__(self, world_parameter_config: dict[str, Any] = None):
        self.world_config = world_parameter_config or {}
        # Per-world max shift override
        self.max_shift = self.world_config.get("max_shift_per_semantic_level", 1)
        # Per-world tag limit
        self.max_tags = self.world_config.get("max_tags_per_character", 8)

    def calculate(
        self,
        character_state: dict[str, Any],
        player_input: dict[str, Any],
        scene_output: dict[str, Any],
    ) -> StateChange:
        """
        Calculate state changes for a round.

        Returns StateChange with all changes computed + blocked list.
        """
        # Step 1: Extract current state
        physical = character_state.get("physical", {})
        mental = character_state.get("mental", {})

        stamina_old = physical.get("stamina_level", "fresh")
        health_old = physical.get("health_status", "healthy")
        morale_old = mental.get("morale_level", "neutral")

        # Step 2: Extract LLM-suggested deltas
        llm_changes = scene_output.get("state_changes", {})

        # Support both legacy _delta format and new {old, new, reason} format
        if "stamina_delta" in llm_changes:
            stamina_delta = int(llm_changes.get("stamina_delta", 0))
        elif "stamina" in llm_changes and isinstance(llm_changes["stamina"], dict):
            # Compute delta from {old, new}
            old = llm_changes["stamina"].get("old", stamina_old)
            new = llm_changes["stamina"].get("new", stamina_old)
            stamina_delta = self._compute_delta(old, new, list(StaminaLevel))
        else:
            stamina_delta = 0

        if "health_delta" in llm_changes:
            health_delta = int(llm_changes.get("health_delta", 0))
        elif "health" in llm_changes and isinstance(llm_changes["health"], dict):
            old = llm_changes["health"].get("old", health_old)
            new = llm_changes["health"].get("new", health_old)
            health_delta = self._compute_delta(old, new, list(HealthLevel))
        else:
            health_delta = 0

        if "morale_delta" in llm_changes:
            morale_delta = int(llm_changes.get("morale_delta", 0))
        elif "morale" in llm_changes and isinstance(llm_changes["morale"], dict):
            old = llm_changes["morale"].get("old", morale_old)
            new = llm_changes["morale"].get("new", morale_old)
            morale_delta = self._compute_delta(old, new, list(MoraleLevel))
        else:
            morale_delta = 0

        # Step 3: Determine environment
        location = scene_output.get("location", {})
        env = location.get("environment", "neutral") if isinstance(location, dict) else "neutral"

        # Step 4: Apply shifts with ±max_shift clamping
        stamina_new = self._apply_axis(stamina_old, stamina_delta, list(StaminaLevel), "stamina", env)
        health_new = self._apply_axis(health_old, health_delta, list(HealthLevel), "health", env)
        morale_new = self._apply_axis(morale_old, morale_delta, list(MoraleLevel), "morale", env)

        # Step 5: Build StateChange
        return StateChange(
            character_id=character_state.get("character_id", "unknown"),
            stamina_old=stamina_old,
            stamina_new=stamina_new,
            health_old=health_old,
            health_new=health_new,
            morale_old=morale_old,
            morale_new=morale_new,
            new_status_tags=llm_changes.get("new_status_tags", []),
            removed_status_tags=llm_changes.get("removed_status_tags", []),
            items_consumed=llm_changes.get("items_consumed", []),
            new_memories=llm_changes.get("new_memories", []),
            relationship_changes=llm_changes.get("relationship_changes", []),
        )

    def _compute_delta(self, old: str, new: str, levels: list[str]) -> int:
        """Compute signed delta between two semantic levels."""
        if old not in levels or new not in levels:
            return 0
        return levels.index(new) - levels.index(old)

    def _apply_axis(
        self,
        old: str,
        delta: int,
        levels: list[str],
        field: str,
        environment: str = "neutral",
    ) -> str:
        """Apply one axis shift, clamping to ±max_shift (with safe env recovery bonus)."""
        if delta == 0 or old not in levels:
            return old
        axis_max = self.max_shift
        if environment == "safe" and delta < 0:
            axis_max += 1  # safe env recovery bonus
        clamped_delta = max(-axis_max, min(axis_max, delta))
        new_idx = max(0, min(len(levels) - 1, levels.index(old) + clamped_delta))
        return levels[new_idx]

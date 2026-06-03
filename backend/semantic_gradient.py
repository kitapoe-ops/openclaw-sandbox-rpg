"""
Semantic Gradient Manager
==========================
Core state machine for semantic state transitions.
No numbers — only semantic bucket labels.

Reference: docs/SCHEMAS/character_state.schema.json
           docs/SCHEMAS/world_parameter.yaml (semantic_states section)
"""
from typing import List, Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass, field


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
    levels: List[str]
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

    def to_dict(self) -> Dict[str, Any]:
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
    new_status_tags: List[str] = field(default_factory=list)
    removed_status_tags: List[str] = field(default_factory=list)
    items_consumed: List[Dict[str, Any]] = field(default_factory=list)
    new_memories: List[str] = field(default_factory=list)
    relationship_changes: List[Dict[str, Any]] = field(default_factory=list)


class StateChangeCalculator:
    """
    Calculates state changes based on player action + environment.
    Used by Sub Agent.

    TODO: Implement action-specific state change rules.
    """

    def __init__(self, world_parameter_config: Dict[str, Any]):
        self.world_config = world_parameter_config

    def calculate(
        self,
        character_state: Dict[str, Any],
        player_input: Dict[str, Any],
        scene_output: Dict[str, Any],
    ) -> StateChange:
        """
        Calculate state changes for a round.
        Returns StateChange object.
        """
        # TODO: Implement calculation logic
        # 1. Read player_input.choice.option_id
        # 2. Read scene_output.state_changes (LLM-suggested)
        # 3. Validate against semantic gradient rules
        # 4. Apply ±1 level rule
        # 5. Check environment (safe/unsafe) for recovery bonus
        # 6. Return StateChange
        raise NotImplementedError("TODO: Implement state change calculation")

"""
Semantic Gradient Manager
==========================
Core state machine for semantic state transitions.
No numbers — only semantic bucket labels.

Reference: docs/SCHEMAS/character_state.schema.json
           docs/SCHEMAS/world_parameter.yaml (semantic_states section)
"""
from typing import List, Optional, Dict, Any, Union
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
# Default Gradient Configurations
# ============================================

DEFAULT_STAMINA_LEVELS = [e.value for e in StaminaLevel]
DEFAULT_HEALTH_LEVELS = [e.value for e in HealthLevel]
DEFAULT_MORALE_LEVELS = [e.value for e in MoraleLevel]


# ============================================
# Reason Lookup Table
# ============================================
#
# Maps (field, delta_sign, environment) to a short Chinese reason string that
# explains *why* a semantic state changed. Used by StateChange.to_dict() to
# populate the schema-required `reason` field of every state transition.
#
# The reason table is intentionally small and conservative — the goal is to
# produce a non-empty, sensible Chinese string, not a poetic explanation.
# Production deployments may extend this with world-specific keys via
# ``StateChangeCalculator(world_parameter_config={...})`` (see
# ``extra_reason_table`` constructor arg).
#
# Sign convention (matches the rest of this module):
#   delta > 0  -> consumption / damage  (state worsens, index increases)
#   delta < 0  -> recovery              (state improves, index decreases)
#   delta == 0 -> unchanged             (no entry produced; reason still
#                                        emitted as "no_change" to satisfy
#                                        the schema's required `reason` key)

DEFAULT_REASON_TABLE: Dict[str, Dict[str, str]] = {
    "stamina": {
        "worsen_neutral": "持續消耗",
        "worsen_unsafe": "劇烈消耗",
        "worsen_safe": "輕度消耗",
        "recover_neutral": "短暫休息",
        "recover_safe": "安全環境恢復",
        "recover_unsafe": "勉強恢復",
        "no_change": "無變化",
    },
    "health": {
        "worsen_neutral": "戰鬥傷害",
        "worsen_unsafe": "嚴重戰鬥傷害",
        "worsen_safe": "輕微傷害",
        "recover_neutral": "自然康復",
        "recover_safe": "安全環境康復",
        "recover_unsafe": "勉強康復",
        "no_change": "無變化",
    },
    "morale": {
        "worsen_neutral": "士氣受挫",
        "worsen_unsafe": "恐懼加深",
        "worsen_safe": "輕微不安",
        "recover_neutral": "心情平復",
        "recover_safe": "安全環境平復",
        "recover_unsafe": "勉強平復",
        "no_change": "無變化",
    },
}


def _lookup_reason(
    field: str,
    delta: int,
    environment: str,
    reason_table: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    """
    Look up a Chinese reason string for a (field, delta, environment) tuple.

    Falls back gracefully: unknown field or direction returns a generic
    "狀態變化" string so the output is always schema-compliant (the schema
    marks ``reason`` as optional in the ``properties`` block, but the
    frontend expects a non-empty value).
    """
    table = reason_table or DEFAULT_REASON_TABLE
    field_table = table.get(field, {})
    if delta == 0:
        key = "no_change"
    elif delta > 0:
        key = f"worsen_{environment}"
    else:
        key = f"recover_{environment}"
    if key not in field_table:
        # Fallback: try a generic bucket, then a hard default
        fallback = f"{'worsen' if delta > 0 else 'recover' if delta < 0 else 'no_change'}_neutral"
        return field_table.get(fallback, "狀態變化")
    return field_table[key]


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
    """
    Result of a state calculation.

    Field layout follows ``docs/SCHEMAS/scene_output.schema.json``:
        state_changes.stamina  = {"old": str, "new": str, "reason": str}
        state_changes.health   = {"old": str, "new": str, "reason": str}
        state_changes.morale   = {"old": str, "new": str, "reason": str}

    Top-level fields store the old/new *and* the reason string separately so
    that ``to_dict()`` can build the schema-compliant structure without
    losing any information. ``reason`` is auto-generated by
    ``StateChangeCalculator`` via the ``_lookup_reason`` helper; callers may
    override it after construction if they need a more specific narrative.
    """
    character_id: str
    stamina_old: str
    stamina_new: str
    health_old: str
    health_new: str
    morale_old: str
    morale_new: str
    stamina_reason: str = ""
    health_reason: str = ""
    morale_reason: str = ""
    new_status_tags: List[str] = field(default_factory=list)
    removed_status_tags: List[str] = field(default_factory=list)
    items_consumed: List[Dict[str, Any]] = field(default_factory=list)
    new_memories: List[str] = field(default_factory=list)
    relationship_changes: List[Dict[str, Any]] = field(default_factory=list)
    blocked: List[Dict[str, Any]] = field(default_factory=list)
    """
    blocked: list of attempted state changes that were rejected by ±1 rule.
    Format: [{"field": "stamina", "attempted_delta": 2, "old": "fresh", "new": "exhausted", "reason": "shift too large"}]
    """

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to schema-compliant shape.

        Output matches ``scene_output.schema.json``'s ``state_changes`` block
        exactly: stamina/health/morale are nested ``{old, new, reason}``
        dicts, and the top-level collections (new_status_tags, etc.) sit
        alongside them.
        """
        return {
            "character_id": self.character_id,
            "stamina": {
                "old": self.stamina_old,
                "new": self.stamina_new,
                "reason": self.stamina_reason,
            },
            "health": {
                "old": self.health_old,
                "new": self.health_new,
                "reason": self.health_reason,
            },
            "morale": {
                "old": self.morale_old,
                "new": self.morale_new,
                "reason": self.morale_reason,
            },
            "new_status_tags": self.new_status_tags,
            "removed_status_tags": self.removed_status_tags,
            "items_consumed": self.items_consumed,
            "new_memories": self.new_memories,
            "relationship_changes": self.relationship_changes,
            "blocked": self.blocked,
        }


def _coerce_level(value: str, allowed: List[str], field_name: str) -> str:
    """Coerce a string to a known level; raise ValueError if unknown."""
    if value not in allowed:
        raise ValueError(
            f"Invalid {field_name} level '{value}'. Allowed: {allowed}"
        )
    return value


def _delta_to_new(old: str, delta: int, levels: List[str], max_shift: int = 1) -> str:
    """
    Compute new level from old + delta, respecting ±max_shift rule.

    Sign convention (matches sub_agent_prompt.md):
    - Positive delta = consumption/damage (worsens state, idx increases)
    - Negative delta = recovery (improves state, idx decreases)

    If |delta| exceeds max_shift, clamps delta to ±max_shift.
    Then clamps result to [0, len(levels)-1] (boundary protection).
    Returns the new level (always; never raises).
    """
    if old not in levels:
        return old
    idx = levels.index(old)
    # Step 1: Clamp delta to ±max_shift (the semantic gradient rule)
    clamped_delta = max(-max_shift, min(max_shift, delta))
    # Step 2: Apply delta, then clamp result to valid index range
    new_idx = idx + clamped_delta
    new_idx = max(0, min(len(levels) - 1, new_idx))
    return levels[new_idx]


def _environment_value(env: Union[str, Dict[str, Any]]) -> str:
    """
    Normalize environment to a string. Accepts:
    - string: "safe" / "neutral" / "unsafe"
    - dict: {"type": "safe", ...}
    Returns: "safe" / "neutral" / "unsafe"
    """
    if isinstance(env, str):
        return env
    if isinstance(env, dict):
        return env.get("type", "neutral")
    return "neutral"


class StateChangeCalculator:
    """
    Calculates state changes based on player action + environment.
    Used by Sub Agent.

    Implements the 5-step calculation:
    1. Read player_input.choice.option_id + attitude_selections
    2. Read scene_output.state_changes (LLM-suggested)
    3. Validate against semantic gradient rules (±1 per round, env bonus)
    4. Apply shifts (clamped, with safe env recovery bonus)
    5. Return StateChange

    INPUT vs OUTPUT contract
    ------------------------
    The calculator's ``calculate()`` method accepts a *delta* style input
    (LLM suggests ``stamina_delta: int``, ``health_delta: int``,
    ``morale_delta: int``) because that is what the prompt asks the LLM to
    produce. Internally, it converts these deltas into the schema-compliant
    output shape ``{old, new, reason}`` so that ``StateChange.to_dict()``
    matches ``docs/SCHEMAS/scene_output.schema.json`` exactly.
    """

    def __init__(
        self,
        world_parameter_config: Optional[Dict[str, Any]] = None,
        extra_reason_table: Optional[Dict[str, Dict[str, str]]] = None,
    ):
        """
        Args:
            world_parameter_config: Optional world config dict with semantic_states override.
            extra_reason_table: Optional per-world override of the default
                reason lookup table. Keys are field names ("stamina", "health",
                "morale"), values are dicts mapping ``worsen_*`` /
                ``recover_*`` / ``no_change`` keys to Chinese reason strings.
                Missing keys fall back to ``DEFAULT_REASON_TABLE``.
        """
        self.world_config = world_parameter_config or {}
        # Allow world config to override default levels
        semantic_states = self.world_config.get("semantic_states", {})
        self.stamina_levels = semantic_states.get("stamina", DEFAULT_STAMINA_LEVELS)
        self.health_levels = semantic_states.get("health", DEFAULT_HEALTH_LEVELS)
        self.morale_levels = semantic_states.get("morale", DEFAULT_MORALE_LEVELS)
        # Per-world max shift override
        self.max_shift = self.world_config.get("max_shift_per_semantic_level", 1)
        # Per-world tag limit
        self.max_tags = self.world_config.get("max_tags_per_character", 8)
        # Reason table: world config can extend the default
        self.reason_table: Dict[str, Dict[str, str]] = {
            field: {**DEFAULT_REASON_TABLE.get(field, {}), **(extra or {})}
            for field, extra in (extra_reason_table or {}).items()
        }

    def calculate(
        self,
        character_state: Dict[str, Any],
        player_input: Dict[str, Any],
        scene_output: Dict[str, Any],
    ) -> StateChange:
        """
        Calculate state changes for a round.

        Args:
            character_state: Current character state (from character_state.schema.json)
            player_input: Player's choice submission (player_input.schema.json)
            scene_output: LLM's scene output (scene_output.schema.json), includes
                         state_changes: {"stamina_delta": int, "health_delta": int, ...}

        Returns:
            StateChange with all changes computed + blocked list
        """
        # ===== Step 1: Extract current state =====
        physical = character_state.get("physical", {})
        mental = character_state.get("mental", {})

        stamina_old = _coerce_level(
            physical.get("stamina", "fresh"),
            self.stamina_levels,
            "stamina",
        )
        health_old = _coerce_level(
            physical.get("health", "healthy"),
            self.health_levels,
            "health",
        )
        morale_old = _coerce_level(
            mental.get("morale", "neutral"),
            self.morale_levels,
            "morale",
        )

        # ===== Step 2: Extract LLM-suggested deltas =====
        # LLM should output scene_output.state_changes = {"stamina_delta": int, ...}
        llm_changes = scene_output.get("state_changes", {})

        stamina_delta = int(llm_changes.get("stamina_delta", 0))
        health_delta = int(llm_changes.get("health_delta", 0))
        morale_delta = int(llm_changes.get("morale_delta", 0))

        # ===== Step 3: Determine environment for recovery bonus =====
        location = scene_output.get("location", {})
        environment = _environment_value(location.get("environment", "neutral"))

        # Safe env recovery bonus
        effective_max_shift = self.max_shift
        if environment == "safe":
            # Only recovery (negative delta) gets bonus
            pass  # applied per-axis below

        # ===== Step 4: Apply shifts with ±max_shift clamping =====
        blocked = []

        def _apply_axis(
            old: str,
            delta: int,
            levels: List[str],
            field: str,
        ) -> str:
            """Apply one axis shift, recording blocked attempts."""
            nonlocal blocked
            if delta == 0:
                return old
            # Compute effective max shift for this axis
            axis_max = self.max_shift
            if environment == "safe" and delta < 0:
                axis_max += 1  # safe env recovery bonus
            if abs(delta) > axis_max:
                blocked.append({
                    "field": field,
                    "attempted_delta": delta,
                    "old": old,
                    "would_be_new": _delta_to_new(old, delta, levels, abs(delta)),
                    "actual_new": _delta_to_new(old, delta, levels, axis_max),
                    "reason": f"shift ±{abs(delta)} exceeds max ±{axis_max} (env={environment})",
                })
            return _delta_to_new(old, delta, levels, axis_max)

        stamina_new = _apply_axis(stamina_old, stamina_delta, self.stamina_levels, "stamina")
        health_new = _apply_axis(health_old, health_delta, self.health_levels, "health")
        morale_new = _apply_axis(morale_old, morale_delta, self.morale_levels, "morale")

        # ===== Step 5: Compute tag / item / memory / relationship changes =====
        new_tags = llm_changes.get("new_status_tags", [])
        removed_tags = llm_changes.get("removed_status_tags", [])
        items_consumed = llm_changes.get("items_consumed", [])
        new_memories = llm_changes.get("new_memories", [])
        rel_changes = llm_changes.get("relationship_changes", [])

        # Validate tag limit (will be applied by CharacterStateMachine)
        current_tags = physical.get("active_effects", [])
        if len(current_tags) + len(new_tags) > self.max_tags:
            blocked.append({
                "field": "active_effects",
                "reason": f"adding {len(new_tags)} tags would exceed max {self.max_tags}",
                "current_count": len(current_tags),
                "would_add": len(new_tags),
            })
            # Trim new_tags to fit
            allowed = max(0, self.max_tags - len(current_tags))
            new_tags = new_tags[:allowed]

        return StateChange(
            character_id=character_state.get("character_id", "unknown"),
            stamina_old=stamina_old,
            stamina_new=stamina_new,
            health_old=health_old,
            health_new=health_new,
            morale_old=morale_old,
            morale_new=morale_new,
            stamina_reason=_lookup_reason(
                "stamina", stamina_delta, environment, self.reason_table
            ),
            health_reason=_lookup_reason(
                "health", health_delta, environment, self.reason_table
            ),
            morale_reason=_lookup_reason(
                "morale", morale_delta, environment, self.reason_table
            ),
            new_status_tags=new_tags,
            removed_status_tags=removed_tags,
            items_consumed=items_consumed,
            new_memories=new_memories,
            relationship_changes=rel_changes,
            blocked=blocked,
        )

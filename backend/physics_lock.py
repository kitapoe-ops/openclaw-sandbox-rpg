"""
Physics Lock v2.0
==================
Validates player choices against character state.
Refuses to disable players; preserves intent and lets LLM improvise.

Reference: docs/PROMPTS/scene_agent_prompt.md (Physics Lock section)
"""
from typing import Dict, Any, List, Tuple


# ============================================
# Default Physics Lock Rules
# ============================================
# Override via worlds/<world_id>/physics_lock_rules.yaml

DEFAULT_FORBIDDEN_ACTIONS = {
    "雙腿嚴重骨折": ["狂奔", "跳躍", "攀爬", "衝刺", "疾跑"],
    "左臂骨折": ["雙手握劍", "投擲", "格擋"],
    "右臂骨折": ["雙手握劍", "寫字", "投擲"],
    "雙臂骨折": ["擁抱", "格擋", "投擲", "握手"],
    "失明": ["觀察", "瞄準", "閱讀", "搜索"],
    "聾啞": ["聆聽", "呼叫", "對話"],
    "中毒": ["劇烈運動", "戰鬥"],
    "暈眩": ["瞄準", "精細操作"],
}


class PhysicsLock:
    """
    Physics Lock v2.0 — validates physical consistency.

    IMPORTANT: We do NOT disable players. If a choice is physically
    impossible, we preserve the player's INTENT and let the LLM
    improvise ("you tried to run, but your legs wouldn't move").

    TODO: Implement full validation + rewrite logic.
    """

    def __init__(self, custom_rules: Dict[str, List[str]] = None):
        self.rules = {**DEFAULT_FORBIDDEN_ACTIONS}
        if custom_rules:
            self.rules.update(custom_rules)

    def validate_choice(
        self,
        choice_text: str,
        character_state: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Validate a single choice against character state.
        Returns (is_valid, reason).
        """
        active_effects = character_state.get("physical", {}).get("active_effects", [])

        for effect in active_effects:
            if effect in self.rules:
                forbidden = self.rules[effect]
                for action in forbidden:
                    if action in choice_text:
                        return False, f"Effect '{effect}' forbids action '{action}'"

        return True, ""

    def validate_choices(
        self,
        choices: List[Dict[str, Any]],
        character_state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Validate all 4 choices. Rewrite any that violate physics.
        Returns validated + rewritten choices.
        """
        validated = []
        for choice in choices:
            is_valid, reason = self.validate_choice(choice["text"], character_state)
            if not is_valid:
                # TODO: Rewrite the choice to preserve player intent
                # For now, just flag it
                choice["physics_lock_rewritten"] = True
                choice["physics_lock_reason"] = reason
            validated.append(choice)
        return validated

    def generate_rewrite_hint(
        self,
        original_text: str,
        forbidden_action: str,
        character_effect: str,
    ) -> str:
        """
        Generate a hint for the LLM to rewrite the choice.
        Preserves player intent while acknowledging the limitation.
        """
        return (
            f"Player wants to: {original_text}\n"
            f"But character has: {character_effect}\n"
            f"Suggested action: {forbidden_action}\n"
            f"Rewrite to preserve intent while acknowledging limitation.\n"
            f"Example: 'You try to [original], but [body part] won't cooperate...'"
        )

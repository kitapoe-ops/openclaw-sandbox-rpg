"""
Physics Lock v2.0
==================
Validates player choices against character state.
Refuses to disable players; preserves intent and lets LLM improvise.

Reference: docs/PROMPTS/scene_agent_prompt.md (Physics Lock section)
"""
from typing import Dict, Any, List, Tuple, Optional
import logging

from .llm_client import llm_client, LLMRole

logger = logging.getLogger(__name__)


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


# ============================================
# Rewrite System Prompt
# ============================================

REWRITE_SYSTEM_PROMPT = """你係物理邏輯鎖 v2.0 嘅重寫 Agent。

## 規則
1. **絕對唔可以禁用玩家** — 玩家嘅意圖必須保留
2. 物理上做唔到嘅動作，**重寫**成「你嘗試做 [原動作]，但 [身體狀況] 令你無法完成」嘅格式
3. 保留原選擇嘅**意圖方向**，但加返身體限制嘅描寫
4. 文字長度維持原選擇嘅 60-80%（唔好加新劇情）
5. 用繁體中文（香港口語）
6. 只 return 重寫後嘅文字，唔好加解釋

## 範例

原選擇：「狂奔逃離現場」+ 雙腿嚴重骨折
重寫：「你勉強撐起身體想跑，但雙腿一軟，重重摔回地上。你只能用手肘拖著身體緩慢爬行...」

原選擇：「用雙手握劍攻擊」+ 左臂骨折
重寫：「你本能地伸出左手想握劍，但劇痛從左臂傳來。你改用單手顫抖地舉起長劍...」

## 輸出格式
純文字，唔好 JSON，唔加引號。
"""


class PhysicsLock:
    """
    Physics Lock v2.0 — validates physical consistency.

    IMPORTANT: We do NOT disable players. If a choice is physically
    impossible, we preserve the player's INTENT and let the LLM
    improvise ("you tried to run, but your legs wouldn't move").
    """

    def __init__(
        self,
        custom_rules: Dict[str, List[str]] = None,
        use_llm_rewrite: bool = True,
        rewrite_use_local: bool = False,
    ):
        """
        Args:
            custom_rules: Override default forbidden actions
            use_llm_rewrite: If True, call LLM to rewrite. If False, just flag.
            rewrite_use_local: If True, use local Qwen for rewrite (cost saving)
        """
        self.rules = {**DEFAULT_FORBIDDEN_ACTIONS}
        if custom_rules:
            self.rules.update(custom_rules)
        self.use_llm_rewrite = use_llm_rewrite
        self.rewrite_use_local = rewrite_use_local

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

    def _find_violation(
        self,
        choice_text: str,
        character_state: Dict[str, Any],
    ) -> Optional[Tuple[str, str]]:
        """
        Find the first physics violation. Returns (effect, forbidden_action) or None.
        """
        active_effects = character_state.get("physical", {}).get("active_effects", [])

        for effect in active_effects:
            if effect in self.rules:
                forbidden = self.rules[effect]
                for action in forbidden:
                    if action in choice_text:
                        return (effect, action)
        return None

    async def rewrite_choice(
        self,
        original_text: str,
        character_effect: str,
        forbidden_action: str,
    ) -> str:
        """
        Call LLM to rewrite a single choice.
        Returns the rewritten text.
        """
        user_message = (
            f"原選擇：{original_text}\n"
            f"角色狀態：{character_effect}\n"
            f"被禁止嘅動作：{forbidden_action}\n"
            f"請重寫呢個選擇，保留玩家意圖但加入身體限制。"
        )

        try:
            rewritten = await llm_client.chat(
                role=LLMRole.SCENE_AGENT,  # Physics rewrite is a sub-task of scene
                system_prompt=REWRITE_SYSTEM_PROMPT,
                user_message=user_message,
                use_local=self.rewrite_use_local,
                temperature=0.7,
                max_tokens=200,
            )
            # Strip any quotes / whitespace
            rewritten = rewritten.strip().strip('"').strip("「」").strip()
            return rewritten
        except Exception as e:
            logger.error(f"LLM rewrite failed: {e}, falling back to template")
            return self._fallback_rewrite(original_text, character_effect, forbidden_action)

    def _fallback_rewrite(
        self,
        original_text: str,
        character_effect: str,
        forbidden_action: str,
    ) -> str:
        """
        Template-based fallback when LLM is unavailable.
        """
        return (
            f"你嘗試「{original_text}」，"
            f"但身體嘅{character_effect}令你無法完成「{forbidden_action}」呢個動作..."
        )

    async def validate_choices(
        self,
        choices: List[Dict[str, Any]],
        character_state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Validate all choices. Rewrite any that violate physics via LLM.
        Returns validated + rewritten choices.
        """
        import copy
        validated = []

        for choice in choices:
            choice_copy = copy.deepcopy(choice)
            violation = self._find_violation(choice_copy["text"], character_state)

            if violation is not None:
                effect, action = violation
                choice_copy["physics_lock_rewritten"] = True
                choice_copy["physics_lock_original"] = choice["text"]
                choice_copy["physics_lock_reason"] = f"Effect '{effect}' forbids action '{action}'"

                if self.use_llm_rewrite:
                    choice_copy["text"] = await self.rewrite_choice(
                        choice["text"], effect, action
                    )
                else:
                    choice_copy["text"] = self._fallback_rewrite(
                        choice["text"], effect, action
                    )

            validated.append(choice_copy)

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

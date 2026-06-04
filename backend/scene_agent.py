"""
Scene Agent Runtime
====================
Builds the Scene Agent prompt from world/character state,
calls LLM, parses JSON output, and validates against schema.

Reference: docs/PROMPTS/scene_agent_prompt.md
           docs/SCHEMAS/scene_output.schema.json
"""
from typing import Dict, Any, Optional, List
import json
import logging
import re

from .llm_client import llm_client, LLMRole
from .world_lore_db import WorldLoreDB
from .physics_lock import PhysicsLock
from .semantic_gradient import StateChangeCalculator

logger = logging.getLogger(__name__)


# ============================================
# Scene Agent Prompt Template
# ============================================

SCENE_AGENT_SYSTEM_PROMPT = """你係「{world_name}」嘅沙盒執行者，負責即時敘事同選項生成。

## 永恆世界守則
{eternal_rules}

## 任務

### 步驟 1：生成場景敘事（200-2000 字）
- 包含感官細節（視覺、聽覺、嗅覺、觸覺、溫度）
- 反映角色狀態（但唔明寫數字）
  - ❌「你體力 30/100」
  - ✅「你嘅膝蓋開始打顫」
- 反映態度組合（透過動作、語氣、視線）
- 反映當前世界參數
- 遵守物理邏輯鎖（角色狀態 vs 動作）
- 語言風格：繁體中文（香港口語化）、第二人稱「你」

### 步驟 2：計算狀態變化
- 狀態變化用 ±1 級平移
- 跳級禁止（fresh → exhausted = 違規）
- 安全環境恢復可 ±2

### 步驟 3：生成 4 個中性選項
- 必須從 World Lore DB 檢索（標記 lore_source）
- ❌ 不可自由發明唔存在嘅物品 / NPC / 地點
- 4 個選項覆蓋 4 個維度：物品互動 / NPC 互動 / 環境觀察 / 等待
- ❌ 不可包含明顯利益 / 風險詞彙（寶藏 / 死亡 / 必死 / 必定 / 神奇）
- ✅ 每個選項 10-60 字
- ✅ 表面價值相等

### 步驟 4：副 Agent 細微事件
- 簡短 1-2 句、唔影響主敘事

## 物理邏輯鎖 v2.0
唔好 disable 玩家，保留玩家意圖，演繹「想做但做唔到」。

## 輸出格式
**只輸出合法 JSON**，唔好加任何解釋或 markdown 圍欄。

```json
{{
  "round": <int>,
  "character_id": "<string>",
  "narrative": "<200-2000 字>",
  "state_changes": {{
    "stamina": {{"old": "<string>", "new": "<string>", "reason": "<string>"}},
    "health":  {{"old": "<string>", "new": "<string>", "reason": "<string>"}},
    "morale":  {{"old": "<string>", "new": "<string>", "reason": "<string>"}},
    "new_status_tags": [...],
    "removed_status_tags": [...],
    "items_consumed": [...],
    "new_memories": [...],
    "relationship_changes": [...]
  }},
  "choices": [
    {{
      "id": "opt_01",
      "text": "...",
      "intent_category": "item_interaction|npc_interaction|environment|delay",
      "attitude_options": [
        {{"dimension": "...", "level": "...", "effect": "..."}}
      ]
    }},
    ... (exactly 4)
  ],
  "minor_event": {{
    "id": "...",
    "description": "...",
    "narrative_impact": "none|subtle"
  }}
}}
```
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON object from LLM output. Handles:
    - Bare JSON
    - JSON wrapped in ```json ... ``` blocks
    - JSON with surrounding prose
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try first { ... last }
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _normalize_state_changes(
    raw_changes: Dict[str, Any],
    character_state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Coerce an LLM-emitted ``state_changes`` block into the schema-compliant
    shape.  Handles two formats:

    1. **Schema format (preferred)**
       ``{"stamina": {"old": "fresh", "new": "slight_breath", "reason": "..."}, ...}``
       — passed through after light validation.

    2. **Legacy delta format**
       ``{"stamina_delta": 1, "health_delta": 0, "morale_delta": -1, ...}``
       — converted by reading the character's current levels and applying
       the deltas to compute ``{old, new, reason}``. Reason is auto-filled
       with a generic Chinese string when missing.

    The returned dict always has stamina/health/morale as nested
    ``{old, new, reason}`` dicts, plus the optional collections
    (new_status_tags, removed_status_tags, items_consumed, new_memories,
    relationship_changes) at the top level. This matches
    ``docs/SCHEMAS/scene_output.schema.json`` exactly.

    The function is **defensive** — it never raises on malformed input. Any
    field that can't be coerced is left as a sensible default (``old`` and
    ``new`` taken from the current character state, ``reason`` set to
    "無變化" or "狀態變化").
    """
    if not isinstance(raw_changes, dict):
        raw_changes = {}

    physical = character_state.get("physical", {}) or {}
    mental = character_state.get("mental", {}) or {}

    # Current levels — source of truth for the "old" side of the conversion.
    current_stamina = (
        physical.get("stamina")
        or physical.get("stamina_level")
        or "fresh"
    )
    current_health = (
        physical.get("health")
        or physical.get("health_status")
        or "healthy"
    )
    current_morale = (
        mental.get("morale")
        or mental.get("morale_level")
        or "neutral"
    )

    def _has_nested(d: Dict[str, Any], key: str) -> bool:
        """True if ``d[key]`` is a dict with at least an ``old`` or ``new`` field."""
        v = d.get(key)
        return isinstance(v, dict) and ("old" in v or "new" in v)

    def _apply_axis(
        field: str,
        current: str,
        delta_key: str,
    ) -> Dict[str, str]:
        """
        Convert one axis (stamina / health / morale) to the {old, new, reason}
        shape. If the LLM already produced a nested dict, use it as-is (with
        a missing ``reason`` filled in). Otherwise, treat the input as a
        delta and apply ±1 to the current level.
        """
        if _has_nested(raw_changes, field):
            block = dict(raw_changes[field])  # copy so we don't mutate
            old_val = block.get("old") or current
            new_val = block.get("new") or current
            reason = block.get("reason")
            if not reason or not str(reason).strip():
                # Best-effort: infer a generic reason from old→new direction
                if old_val == new_val:
                    reason = "無變化"
                else:
                    reason = "狀態變化"
            block = {"old": old_val, "new": new_val, "reason": reason}
            return block

        # Legacy delta path
        try:
            delta = int(raw_changes.get(delta_key, 0) or 0)
        except (TypeError, ValueError):
            delta = 0
        if delta == 0:
            return {"old": current, "new": current, "reason": "無變化"}
        # Without the gradient's level list we can't be precise, but the
        # downstream StateChangeCalculator will clamp the delta anyway.
        # We just emit current → current with a generic reason so the schema
        # stays valid; the calculator will overwrite the new value correctly.
        return {"old": current, "new": current, "reason": "狀態變化"}

    normalized: Dict[str, Any] = {
        "stamina": _apply_axis("stamina", current_stamina, "stamina_delta"),
        "health": _apply_axis("health", current_health, "health_delta"),
        "morale": _apply_axis("morale", current_morale, "morale_delta"),
    }

    # Pass-through the optional collections. Normalize types defensively.
    def _coerce_str_list(value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(x) for x in value if x is not None]
        return [str(value)]

    def _coerce_dict_list(value: Any) -> List[Dict[str, Any]]:
        if not value:
            return []
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    normalized["new_status_tags"] = _coerce_str_list(
        raw_changes.get("new_status_tags")
    )
    normalized["removed_status_tags"] = _coerce_str_list(
        raw_changes.get("removed_status_tags")
    )
    normalized["items_consumed"] = _coerce_dict_list(
        raw_changes.get("items_consumed")
    )
    normalized["new_memories"] = _coerce_str_list(
        raw_changes.get("new_memories")
    )
    normalized["relationship_changes"] = _coerce_dict_list(
        raw_changes.get("relationship_changes")
    )

    return normalized


def _build_eternal_rules(eternal_rules: list) -> str:
    if not eternal_rules:
        return "（無永恆規則）"
    return "\n".join(f"- {r}" for r in eternal_rules)


def _format_attitude(attitude: Dict[str, str]) -> str:
    if not attitude:
        return "（無）"
    return "\n".join(f"- {k}: {v}" for k, v in attitude.items())


def _format_inventory(inventory: Dict[str, Any]) -> str:
    if not inventory:
        return "（空）"
    items = inventory.get("items", [])
    if not items:
        return "（空）"
    return ", ".join(f"{i['item_id']} x{i.get('quantity', 1)}" for i in items)


class SceneAgent:
    """
    Scene Agent runtime: orchestrates a single round.

    Flow:
    1. Build system prompt (with world + character state)
    2. Call LLM
    3. Parse JSON output
    4. Apply PhysicsLock to choices
    5. Run StateChangeCalculator
    6. Return validated scene_output
    """

    def __init__(
        self,
        world_lore: WorldLoreDB,
        physics_lock: Optional[PhysicsLock] = None,
        state_calculator: Optional[StateChangeCalculator] = None,
    ):
        self.world_lore = world_lore
        self.physics_lock = physics_lock or PhysicsLock(use_llm_rewrite=True)
        self.state_calculator = state_calculator or StateChangeCalculator()

    async def generate_scene(
        self,
        character_state: Dict[str, Any],
        player_input: Dict[str, Any],
        world_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a scene for the given character.

        Returns a scene_output dict, validated.
        """
        # Build system prompt
        world_meta = self.world_lore.world_parameters.get("__meta__", {}) or {}
        world_name = world_meta.get("name", "未知世界")
        eternal = getattr(self.world_lore, "eternal_rules", [])

        system_prompt = SCENE_AGENT_SYSTEM_PROMPT.format(
            world_name=world_name,
            eternal_rules=_build_eternal_rules(eternal),
        )

        # Build user message with current state
        user_message = self._build_user_message(character_state, world_state)

        # Call LLM
        try:
            raw = await llm_client.chat(
                role=LLMRole.SCENE_AGENT,
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=0.8,
                max_tokens=2500,
            )
        except Exception as e:
            logger.error(f"Scene Agent LLM call failed: {e}")
            return self._fallback_scene(character_state, player_input, reason=str(e))

        # Parse JSON
        scene_output = _extract_json(raw)
        if scene_output is None:
            logger.error(f"Scene Agent returned non-JSON: {raw[:500]}")
            return self._fallback_scene(character_state, player_input, reason="non_json_llm_output")

        # Validate minimal schema
        scene_output = self._validate_scene_output(scene_output, character_state)

        # Normalize LLM-emitted state_changes to the schema format
        # (handles both nested {old,new,reason} and legacy _delta inputs).
        scene_output["state_changes"] = _normalize_state_changes(
            scene_output.get("state_changes", {}),
            character_state,
        )

        # Apply PhysicsLock to choices
        scene_output["choices"] = await self.physics_lock.validate_choices(
            scene_output.get("choices", []),
            character_state,
        )

        # Run StateChangeCalculator
        state_change = self.state_calculator.calculate(
            character_state=character_state,
            player_input=player_input,
            scene_output=scene_output,
        )
        scene_output["state_change_computed"] = state_change.to_dict()
        if state_change.blocked:
            scene_output["state_changes_blocked"] = state_change.blocked

        return scene_output

    def _build_user_message(
        self,
        character_state: Dict[str, Any],
        world_state: Dict[str, Any],
    ) -> str:
        """Build user message with character + world context."""
        location_id = character_state.get("current_location", "unknown")
        location = self.world_lore.get_location(location_id) or {}
        npcs = self.world_lore.get_npcs_in_location(location_id)
        items = self.world_lore.get_items_in_location(location_id)

        ctx = {
            "character": {
                "id": character_state.get("character_id"),
                "name": character_state.get("name"),
                "stamina_level": character_state.get("physical", {}).get("stamina_level", "fresh"),
                "health_status": character_state.get("physical", {}).get("health_status", "healthy"),
                "active_effects": character_state.get("physical", {}).get("active_effects", []),
                "morale_level": character_state.get("mental", {}).get("morale_level", "neutral"),
                "attitude": _format_attitude(character_state.get("attitude", {})),
                "inventory": _format_inventory(character_state.get("inventory", {})),
            },
            "location": {
                "id": location_id,
                "name": location.get("name", "未知"),
                "description": location.get("description", ""),
                "atmosphere": location.get("atmosphere", ""),
            },
            "npcs_present": [{"id": n.get("id"), "name": n.get("name")} for n in npcs],
            "items_present": [{"id": i.get("id"), "name": i.get("name")} for i in items],
            "time": world_state.get("current_time", "未知"),
            "weather": world_state.get("weather", "未知"),
        }
        return json.dumps(ctx, ensure_ascii=False, indent=2)

    def _validate_scene_output(
        self,
        scene_output: Dict[str, Any],
        character_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Fill in missing required fields, enforce structure."""
        scene_output.setdefault("round", 1)
        scene_output.setdefault("character_id", character_state.get("character_id"))
        scene_output.setdefault("narrative", "（敘事生成失敗）")
        scene_output.setdefault("state_changes", {})
        scene_output.setdefault("choices", [])
        scene_output.setdefault("minor_event", {})

        # Ensure exactly 4 choices
        choices = scene_output["choices"]
        if len(choices) < 4:
            # Pad with generic choices
            for i in range(len(choices), 4):
                choices.append({
                    "id": f"opt_{i+1:02d}",
                    "text": "環顧四周",
                    "intent_category": "environment",
                    "attitude_options": [],
                })
        elif len(choices) > 4:
            choices = choices[:4]
        scene_output["choices"] = choices

        return scene_output

    def _fallback_scene(
        self,
        character_state: Dict[str, Any],
        player_input: Dict[str, Any],
        reason: str = "unknown",
    ) -> Dict[str, Any]:
        """Return a minimal valid scene when LLM fails."""
        return {
            "round": player_input.get("round", 1),
            "character_id": character_state.get("character_id"),
            "narrative": "（敘事生成暫時無法提供，請稍後再試。）",
            "state_changes": {
                "stamina": {"old": "fresh", "new": "fresh", "reason": "無變化"},
                "health":  {"old": "healthy", "new": "healthy", "reason": "無變化"},
                "morale":  {"old": "neutral", "new": "neutral", "reason": "無變化"},
                "new_status_tags": [],
                "removed_status_tags": [],
                "items_consumed": [],
                "new_memories": [],
                "relationship_changes": [],
            },
            "choices": [
                {"id": "opt_01", "text": "環顧四周", "intent_category": "environment", "attitude_options": []},
                {"id": "opt_02", "text": "向前走", "intent_category": "environment", "attitude_options": []},
                {"id": "opt_03", "text": "查看背包", "intent_category": "item_interaction", "attitude_options": []},
                {"id": "opt_04", "text": "等待片刻", "intent_category": "delay", "attitude_options": []},
            ],
            "minor_event": {
                "id": "evt_fallback",
                "description": "空氣中傳來微弱的風聲",
                "narrative_impact": "subtle",
            },
            "_fallback_reason": reason,
        }

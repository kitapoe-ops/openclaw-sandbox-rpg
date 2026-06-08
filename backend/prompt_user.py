"""
User prompt module (2026-06-08)
===============================

The 5-module user prompt structure for the LLM narrative call. This is
the **user message** side of the chat, not the system prompt (which
lives in :mod:`backend.prompt_builder`).

The 5 modules:

1. **Hard Facts** — character identity, health, equipped items, scene NPCs
2. **Karma & Traces** — active escalation threads, other-player footprints
3. **Trigger Action** — the player's verb + target + args
4. **Director's Constraints** — trope directive + writing rules
5. **Output Requirements** — JSON shape (narrative + state_mutations + choices)

Output JSON contract (2A = preserve F3 + add choices):
- ``narrative``        (str)  — 1-3 sentence second-person description
- ``state_mutations``  (dict) — F1/F3 Pydantic strict; required for audit
- ``choices``          (list) — 4 follow-up options, each with direction + vignette
                              where direction ∈ {combat, social, explore, creative}

The user-prompt builders below can be called independently of the
system prompt, so the developer can inspect each module's content
via the Prompt Inspector (see :mod:`backend.api.prompt_inspector`).
"""
from __future__ import annotations

import logging
from typing import Any

from .state_machine import SemanticState

logger = logging.getLogger(__name__)


# User prompt template (5 modules)
USER_PROMPT_TEMPLATE: str = """你是 OpenClaw Sandbox RPG 的敘事渲染引擎。請嚴格根據以下客觀狀態與劇本指令進行渲染。

### [模塊 1：硬性物理與狀態 (Hard Facts)]
Character: {character_id} (HP: {health_status})
Equipped Items & Tags: {inventory_with_physical_tags} (例如: 勇者之劍 [沉重, 鋒利])
Scene NPCs: {scene_npc_states}

### [模塊 2：世界因果與痕跡 (Karma & Traces)]
Active Threads: {active_escalation_threads} (例如: 通緝令發酵中)
Environmental Traces: {other_player_footprints} (例如: 地上有上一手玩家留下的血跡)

### [模塊 3：玩家本回合行動 (Trigger Action)]
Player Action: {verb} {target} {args_str}

### [模塊 4：劇本與寫作鐵律 (Director's Constraints)]
Trope / Plot Beat: {current_trope_directive}
Writing Rules:
1. Show, Don't Tell：絕對禁止使用「緊張、害怕、恐怖」等直接情緒詞。
2. Physical Reality：行動與結果必須嚴格符合 [模塊 1] 中道具的物理標籤，嚴禁捏造不存在的魔法效果或裝備或道具。

### [模塊 5：強制輸出格式 (Output Requirements)]
1. Narrative: 用 1-3 句第二人稱 (你) 渲染玩家行動的結果及場景變化。
2. Choices: 必須生成 4 個後續選項，嚴格對應上一個回答的後續。
3. Risks: 每一個選項中只能文字描述，不可提供數字。

請以 JSON 格式輸出：
```json
{{
 "narrative": "...",
 "state_mutations": {{"target": "...", "add_state": [...], "remove_state": [...], "reason": "..."}},
 "choices": [
  {{"direction": "combat", "vignette": "..."}},
  {{"direction": "social", "vignette": "..."}},
  {{"direction": "explore", "vignette": "..."}},
  {{"direction": "creative", "vignette": "..."}}
 ]
}}
```"""


# Allowed choice directions (for F3 contract validation)
ALLOWED_CHOICE_DIRECTIONS = ("combat", "social", "explore", "creative")


# --------------------------------------------------------------------------
# Section formatters
# --------------------------------------------------------------------------


def _format_health_status(current_state: SemanticState) -> str:
    """Derive a textual health status from the semantic-state tags.

    Per F1 audit invariant #4, character state is a list of free-form
    CJK tags. Death-critical tags (``死亡``, ``瀕死``) take priority;
    otherwise we surface the first 1-2 health-relevant tags.

    Returns
    -------
    str
        A short text label, e.g. "健康", "瀕死", "右手骨折 + 失血".
        Never returns a numeric HP value (F1 invariant: no HP / MP).
    """
    tags = list(getattr(current_state, "tags", []) or [])
    if not tags:
        return "健康"
    death_critical = [t for t in tags if t in ("死亡", "瀕死", "瀕死狀態", "dying", "dead")]
    if death_critical:
        return death_critical[0]
    # Surface the first 2 health-relevant tags (anything not purely spatial/social)
    return " + ".join(tags[:2]) if len(tags) > 1 else tags[0]


def _format_inventory_with_physical_tags(current_state: SemanticState, world_db: Any = None) -> str:
    """Render equipped items with their physical tags.

    HIDDEN 2026-06-08: the items/equipment system is disabled at the
    prompt level (see :mod:`backend.prompt_builder`). This formatter
    returns a placeholder that preserves the *physical constraint
    contract* (the Writing Rules in module 4 still reference physical
    tags), but does not inject any actual item data.

    Returns
    -------
    str
        A short placeholder + the physical-rules reminder, e.g.
        ``"(無裝備 — 系統已關閉。物理約束仍然適用: 不得捏造不存在的魔法效果或裝備或道具。"``
    """
    return "(無裝備 — 系統已關閉。物理約束仍然適用: " "不得捏造不存在的魔法效果或裝備或道具。)"


def _format_scene_npc_states(scene_context: dict[str, Any] | None) -> str:
    """Render the current scene's NPCs and their high-level states.

    Pulls from ``scene_context['npcs']`` (list of dicts with at least
    ``npc_id`` + ``name`` + optional ``status`` / ``location``) if
    present. Falls back to a placeholder when scene context is
    unavailable.

    Parameters
    ----------
    scene_context : dict | None
        The scene context dict from :func:`action_processor._scene_context_fn`.
        Expected shape::

            {
                "scene_id": "...",
                "summary": "...",
                "npcs": [
                    {"npc_id": "...", "name": "Eldrin",
                     "status": "hostile", "location": "tavern"},
                    ...
                ],
                "location_tag": "tavern",
            }

    Returns
    -------
    str
        Human-readable NPC list, e.g.::

            "Eldrin (hostile, 酒館內) / Mira (neutral, 酒館內)"
    """
    if scene_context is None:
        return "(無 scene context — NPC 狀態未知)"
    npcs = scene_context.get("npcs") or []
    if not npcs:
        return "(場景內無 NPC)"
    parts: list[str] = []
    for npc in npcs[:6]:  # cap at 6 to keep prompt bounded
        name = npc.get("name") or npc.get("npc_id") or "?"
        status = npc.get("status") or "neutral"
        location = npc.get("location") or scene_context.get("location_tag") or ""
        if location:
            parts.append(f"{name} ({status}, {location})")
        else:
            parts.append(f"{name} ({status})")
    return " / ".join(parts)


def _format_active_escalation_threads(current_state: SemanticState) -> str:
    """Render active trope threads as escalation summaries.

    Reads ``current_state.active_threads`` (a dict of
    ``trope_id → {status, escalation_level, ...}``) and produces a
    short narrative phrase per active thread, e.g.
    ``"通緝令發酵中 (escalation=2)"``.

    Returns
    -------
    str
        One line per active thread, joined by `` / ``.
    """
    threads = getattr(current_state, "active_threads", {}) or {}
    if not threads:
        return "(無 active threads)"
    parts: list[str] = []
    # Lazy import to avoid circular import at module load
    try:
        from .trope_router import TropeRouter

        router = TropeRouter()
    except Exception:
        router = None

    for tid, data in threads.items():
        if data.get("status") not in ("Active", "Evaded"):
            continue
        name = tid
        if router is not None:
            trope_def = router.get_trope_by_id(tid)
            if trope_def:
                name = trope_def.get("trope_name") or tid
        level = data.get("escalation_level", 0)
        status = data.get("status")
        if status == "Evaded":
            parts.append(f"{name} (已迴避, level={level})")
        else:
            parts.append(f"{name} (發酵中, level={level})")
    if not parts:
        return "(無 active threads)"
    return " / ".join(parts)


def _format_other_player_footprints(scene_context: dict[str, Any] | None) -> str:
    """Render *environmental* traces left by other players in the same scene.

    This is a *scene-level* observation, not a per-character memory
    access. The audit invariant in :mod:`backend.memory_isolation`
    (one character cannot read another character's memories) is
    **preserved** — footprints are public environmental metadata
    (blood, drag-marks, footprints, broken items), not private
    memories.

    Reads ``scene_context['footprints']`` (list of dicts with at
    least ``marker`` + optional ``actor`` / ``turn``) if present.

    Returns
    -------
    str
        e.g. ``"地上有血跡 (來自 Bob, 3 回合前) / 門板被砍出一道深痕 (來自 Alice)"``
    """
    if scene_context is None:
        return "(無環境痕跡)"
    fps = scene_context.get("footprints") or []
    if not fps:
        return "(場景內無其他玩家痕跡)"
    parts: list[str] = []
    for fp in fps[:6]:  # cap at 6
        marker = fp.get("marker") or fp.get("description") or "?"
        actor = fp.get("actor")
        turn = fp.get("turn")
        if actor and turn is not None:
            parts.append(f"{marker} (來自 {actor}, {turn} 回合前)")
        elif actor:
            parts.append(f"{marker} (來自 {actor})")
        else:
            parts.append(marker)
    return " / ".join(parts)


def _format_trope_directive(current_state: SemanticState) -> str:
    """Compose the active trope's plot_beat + tonal_focus as a directive.

    Reads ``current_state.active_threads`` and uses the first active
    thread to look up its trope definition. If no active thread or
    no trope definition, returns a placeholder.

    Returns
    -------
    str
        e.g. ``"嘲諷升級 (plot_beat: 路人乙被當眾羞辱, tonal_focus: 喜劇反轉)"``
    """
    threads = getattr(current_state, "active_threads", {}) or {}
    if not threads:
        return "(無 trope directive)"
    try:
        from .trope_router import TropeRouter

        router = TropeRouter()
    except Exception:
        return "(trope router unavailable)"

    for tid, data in threads.items():
        if data.get("status") not in ("Active", "Evaded"):
            continue
        trope_def = router.get_trope_by_id(tid)
        if not trope_def:
            continue
        name = trope_def.get("trope_name") or tid
        directive = trope_def.get("narrative_directive") or {}
        plot_beat = directive.get("plot_beat") or ""
        tonal_focus = directive.get("tonal_focus") or ""
        if plot_beat and tonal_focus:
            return f"{name} (plot_beat: {plot_beat}, tonal_focus: {tonal_focus})"
        if plot_beat:
            return f"{name} (plot_beat: {plot_beat})"
        return f"{name}"
    return "(無 active trope)"


# --------------------------------------------------------------------------
# Public builder
# --------------------------------------------------------------------------


def build_user_prompt(
    character_id: str,
    current_state: SemanticState,
    verb: str,
    target: str | None,
    args_str: str,
    scene_context: dict[str, Any] | None = None,
    world_db: Any = None,
) -> str:
    """Build the full 5-module user prompt.

    Parameters
    ----------
    character_id : str
        The character's unique id.
    current_state : SemanticState
        The character's current state (for tags, active_threads, inventory).
    verb : str
        The action verb (e.g. "attack", "talk", "move").
    target : str | None
        The action target, or ``None`` if not applicable.
    args_str : str
        Human-readable args string (e.g. " with weapon=sword").
    scene_context : dict | None
        Scene context from the action processor (npcs, footprints, location).
    world_db : Any
        World lore DB (kept for API symmetry with system-prompt builder).

    Returns
    -------
    str
        The fully rendered 5-module user prompt, ready to send as the
        ``user_message`` in the LLM chat call.
    """
    return USER_PROMPT_TEMPLATE.format(
        character_id=character_id,
        health_status=_format_health_status(current_state),
        inventory_with_physical_tags=_format_inventory_with_physical_tags(current_state, world_db),
        scene_npc_states=_format_scene_npc_states(scene_context),
        active_escalation_threads=_format_active_escalation_threads(current_state),
        other_player_footprints=_format_other_player_footprints(scene_context),
        verb=verb,
        target=(target or "(nothing)"),
        args_str=args_str,
        current_trope_directive=_format_trope_directive(current_state),
    )


def build_user_prompt_sections(
    character_id: str,
    current_state: SemanticState,
    verb: str,
    target: str | None,
    args_str: str,
    scene_context: dict[str, Any] | None = None,
    world_db: Any = None,
) -> dict[str, str]:
    """Return the per-section breakdown of the 5-module user prompt.

    Useful for the Prompt Inspector (developer can see what each
    section would render to without re-constructing the whole
    template).
    """
    return {
        "character_id": character_id,
        "health_status": _format_health_status(current_state),
        "inventory_with_physical_tags": _format_inventory_with_physical_tags(
            current_state, world_db
        ),
        "scene_npc_states": _format_scene_npc_states(scene_context),
        "active_escalation_threads": _format_active_escalation_threads(current_state),
        "other_player_footprints": _format_other_player_footprints(scene_context),
        "verb": verb,
        "target": (target or "(nothing)"),
        "args_str": args_str,
        "current_trope_directive": _format_trope_directive(current_state),
    }

"""
Prompt Builder v1.0 — Top-of-prompt current state (Phase F4, 2026-06-05)
=======================================================================

Builds LLM system prompts with the **current character state** ALWAYS
prepended at the top, regardless of Memory Palace retrieval results.

Why this exists
---------------
The semantic state (Phase F1) lives in the database and is updated by
``StateMutation`` every turn. The Memory Palace (Phase C2) provides
**long-term, vector-indexed** memory retrieval.

The problem: the LLM can attend to both, but the *current* state is
the "absolute current reality" — the rules in the audit §3 (D1)
explicitly say the LLM must not generate narrative that contradicts
the character's current state, even if the retrieved memory is
out-of-date. If we leave the current state to chance (i.e. rely on
Memory Palace to surface it), the LLM can forget it after a few
turns, especially in long contexts.

The solution: **always prepend** the current state to the system
prompt as a separate, top-of-prompt section. The LLM sees it on
every call, regardless of what the Memory Palace retrieved.

Design contract
---------------
* **State is always at the top.** Order is: state → memory → action
  context → format rules. The LLM cannot "scroll past" the state.
* **Bounded length.** The state section is capped at
  ``MAX_STATE_SECTION_LENGTH`` (500 chars) to keep the system prompt
  cache-friendly across turns. A character with 100 tags gets a
  truncated section, not a 5 KB blob.
* **Memory section is best-effort.** If the Memory Palace is
  unavailable or raises, the section falls back to a placeholder
  string. The state section is **never** replaced or hidden by a
  memory failure.
* **CJK-first.** The template is in Traditional Chinese (Cantonese
  flavor) to match the game domain. Tag formatting uses 「...」
  brackets for visual separation.

Integration
-----------
This module is consumed by Phase F3, which unfreezes
``backend/api/action_processor.py`` and rewires the prompt-building
step to use ``PromptBuilder.build()`` instead of the inline
``NARRATIVE_PROMPT_TEMPLATE``. F4 does NOT modify action_processor.py
— the deliverable is a self-contained, fully-testable builder.

Module contents
---------------
* :class:`PromptBuilder` — the main builder. Inject memory_palace
  and memory_isolation_guard at construction time; call
  ``build()`` to get the system prompt string.
* :class:`PromptBuilderError` — base for builder errors.

Constants
---------
* ``MAX_STATE_SECTION_LENGTH = 500`` — hard cap on the state
  section (chars, not tokens).
* ``MAX_TAGS_DISPLAYED = 7`` — defensive display cap. The state
  machine allows up to 8 tags (``MAX_TAGS_PER_CHARACTER``); we
  display 7 to keep the section compact. (8 with 「...」 brackets
  is ~16 chars per tag × 8 = 128 chars max, well under 500.)
* ``MAX_MEMORY_DISPLAY_LENGTH = 200`` — per-memory truncation cap.
* ``DEFAULT_TOP_K_MEMORIES = 5`` — how many memories to recall.

Test coverage
-------------
10 tests in ``backend/tests/test_prompt_builder.py`` cover the 5
template sections, bounded length, CJK handling, memory fallback,
and the "state is always above memory" invariant.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.state_machine import (
    SemanticState,
)

logger = logging.getLogger(__name__)


# ============================================
# Configuration constants
# ============================================

# Hard cap on the state section length (chars). Defends against
# pathological states (100+ tags). The state machine itself caps at
# 8 tags × 15 chars, but we keep a separate 500-char display cap so
# future states (longer, narrative-style) don't bloat the prompt.
MAX_STATE_SECTION_LENGTH: int = 500

# Display cap. State machine allows 8; we display 7 + "等 N 個"
# tail if there's overflow. This is a UI choice, not a correctness
# bound — the LLM still receives the underlying state via the
# state_mutations contract.
MAX_TAGS_DISPLAYED: int = 7

# Per-memory truncation cap for the memory section.
MAX_MEMORY_DISPLAY_LENGTH: int = 200

# Default top-k for Memory Palace recall. Matches the brief.
DEFAULT_TOP_K_MEMORIES: int = 5


# ============================================
# Errors
# ============================================


class PromptBuilderError(Exception):
    """Base for prompt-builder errors. The builder itself doesn't
    raise (it falls back gracefully on every external failure); this
    class is reserved for caller-side contract violations (e.g.
    passing a non-string character_id)."""


# ============================================
# PromptBuilder
# ============================================


class PromptBuilder:
    """Builds LLM system prompts with current state at the top.

    The "absolute current reality" rule: the character's current
    state is ALWAYS at the top of the system prompt, regardless of
    Memory Palace retrieval results. The LLM cannot forget the
    current state across turns.

    Construction
    ------------
    Both ``memory_palace`` and ``memory_isolation_guard`` are
    optional. If absent, the corresponding section falls back to a
    placeholder string. This keeps the builder testable without
    wiring the full C2 / E6 stack.

    ``memory_palace`` (when wired) must expose an async ``recall()``
    method matching the ``MemoryPalaceIntegration`` signature:

        async def recall(character_id, query_embedding, k=5,
                         memory_type=None, min_salience=0.0) -> list[dict]

    ``memory_isolation_guard`` is accepted for future use (F3 will
    pass the real ``MemoryIsolationGuard`` from
    ``backend.memory_isolation``); the F4 builder does not yet call
    it — memory section is a flat list of the character's own
    memories. Cross-character access is gated elsewhere.

    Usage
    -----
    >>> builder = PromptBuilder(memory_palace=palace)
    >>> prompt = builder.build(
    ...     character_id="alice",
    ...     current_state=alice_state,
    ...     action_context={"verb": "attack", "target": "goblin"},
    ... )
    >>> text = await llm_client.generate(system_prompt=prompt,
    ...                                   user_message="...")
    """

    # 6-section system prompt template (Chinese, Cantonese flavor).
    # Sections in order:
    #   1. Role / "absolute current reality" rule
    #   2. Character current state (always at the top of the data)
    #   3. Character current equipment & physical constraints
    #   4. Memory Palace retrieval
    #   5. Action context
    #   6. Output format + important rules
    SYSTEM_PROMPT_TEMPLATE: str = """你是一個文字冒險遊戲的 AI 主持人。當前角色的身體狀態是「絕對當前現實」,必須在每個回合都遵守。

# 角色當前狀態 (語意標籤,最多 7 個,每個不超過 15 字)

{state_section}

# 角色當前裝備與物理約束

{equipment_section}

# 故事套路約束

{trope_section}

# 角色記憶摘要 (由 Memory Palace 檢索)

{memory_section}

# 動作上下文

{action_context_section}

# 輸出格式要求

- 你必須輸出一個結構化 JSON 回應
- 包含 "narrative" 欄位 (劇情文字) 和 "state_mutations" 欄位 (語意狀態變更)
- "state_mutations" 必須遵守 Phase F1 嘅 StateMutation 契約 (Pydantic strict)
- 不得違反角色當前狀態 (例如「右手骨折」角色不得「揮劍」)

# 重要規則

- 角色身體狀態係純文字語意,沒有 HP / MP 等數值
- 死亡狀態(標籤 "死亡" / "瀕死") 嘅角色無法執行 any 主動動作
- 跨角色嘅 memory access 受到 MemoryIsolationGuard 保護
"""

    def __init__(
        self,
        memory_palace: Any = None,
        memory_isolation_guard: Any = None,
        top_k_memories: int = DEFAULT_TOP_K_MEMORIES,
    ) -> None:
        self._memory_palace = memory_palace
        self._memory_isolation_guard = memory_isolation_guard
        self._top_k = int(top_k_memories) if top_k_memories > 0 else DEFAULT_TOP_K_MEMORIES

    # ---------------------- public API ----------------------

    async def build(
        self,
        character_id: str,
        current_state: SemanticState,
        action_context: dict[str, Any],
        world_db: Any = None,
    ) -> str:
        """Build the system prompt for an LLM call.

        Returns a complete system prompt string. The state section
        is ALWAYS at the top of the data, regardless of Memory
        Palace results. If anything in the chain fails, the section
        falls back to a placeholder string — but the state section
        itself is constructed from the in-memory ``current_state``
        and never depends on external services.

        Async because the Memory Palace ``recall()`` is async (it
        hits Postgres + a vector store). The state and action
        sections are constructed synchronously; only the memory
        section is awaited.

        Parameters
        ----------
        character_id : str
            The character's unique id. Used for Memory Palace recall.
        current_state : SemanticState
            The character's current semantic state. Required; the
            state section is built from ``current_state.tags``.
        action_context : dict
            The action being processed. Expected keys:
              - "verb" (str)        — the action verb (e.g. "attack")
              - "target" (str|None) — the action target (e.g. "goblin")
              - "args" (dict|None)  — optional extra args
              - "query_embedding" (list[float], optional) — embedding
                for Memory Palace recall. If absent, recall is
                skipped (no query embedding → no useful result).
        world_db : Any, optional
            The WorldLoreDB instance. Used to fetch item physical tags.

        Returns
        -------
        str
            The full system prompt, ready to be passed to
            ``LLMClient.generate(system_prompt=..., user_message=...)``.
        """
        if not isinstance(character_id, str) or not character_id.strip():
            raise PromptBuilderError(f"character_id must be a non-empty str, got {character_id!r}")
        if not isinstance(current_state, SemanticState):
            raise PromptBuilderError(
                f"current_state must be a SemanticState, got " f"{type(current_state).__name__}"
            )
        if not isinstance(action_context, dict):
            raise PromptBuilderError(
                f"action_context must be a dict, got " f"{type(action_context).__name__}"
            )

        state_section = self._format_state_section(current_state)
        equipment_section = self._format_equipment_section(current_state, world_db)
        trope_section = self._format_trope_section(current_state)
        # Memory section is async (recall is async); await it.
        memory_section = await self._format_memory_section(character_id, action_context)
        action_context_section = self._format_action_context(action_context)

        return self.SYSTEM_PROMPT_TEMPLATE.format(
            state_section=state_section,
            equipment_section=equipment_section,
            trope_section=trope_section,
            memory_section=memory_section,
            action_context_section=action_context_section,
        )

    # ---------------------- internals ----------------------

    def _format_state_section(self, current_state: SemanticState) -> str:
        """Format the state section. Bounded to ``MAX_STATE_SECTION_LENGTH``.

        The state section is the "absolute current reality" — it
        must always be present and bounded. Even an empty state
        shows the "(無當前狀態 — 健康)" placeholder so the LLM has
        a positive signal that it considered the state.
        """
        tags = current_state.tags or []
        if not tags:
            return "(無當前狀態 — 健康)"

        # Display cap: show the first MAX_TAGS_DISPLAYED tags.
        # If there are more, append a tail marker so the LLM knows
        # the display is truncated (the underlying state has more).
        if len(tags) > MAX_TAGS_DISPLAYED:
            displayed_tags = tags[:MAX_TAGS_DISPLAYED]
            tail = f" ... (還有 {len(tags) - MAX_TAGS_DISPLAYED} 個未顯示)"
        else:
            displayed_tags = tags
            tail = ""

        formatted = " | ".join(f"「{tag}」" for tag in displayed_tags) + tail
        if len(formatted) > MAX_STATE_SECTION_LENGTH:
            # Defensive truncation: the state machine itself caps at
            # 8 tags × 15 chars = 120 chars, but a future world could
            # relax that. We truncate to the hard cap with an
            # ellipsis to keep the prompt cacheable.
            formatted = formatted[: MAX_STATE_SECTION_LENGTH - 3] + "..."
        return formatted

    def _format_equipment_section(self, current_state: SemanticState, world_db: Any = None) -> str:
        """Format current equipped items and their physical constraints."""
        if world_db is None:
            return "(無裝備物理約束資訊)"

        items = current_state.inventory.get("items", [])
        equipped_items = [i for i in items if i.get("equipped") is True]
        if not equipped_items:
            return "(無當前裝備)"

        lines = []
        TAG_TRANSLATIONS = {
            "sharp": "鋒利",
            "light": "輕巧",
            "metallic": "金屬製",
            "heavy": "沉重",
            "conductive": "導電",
            "holy_damage": "神聖傷害",
            "flexible": "柔韌",
            "protective": "防護",
            "flammable": "易燃",
            "magical": "魔法屬性",
            "fragile": "易碎",
            "holy_property": "神聖屬性"
        }

        for eq in equipped_items:
            item_id = eq.get("item_id")
            item_data = world_db.get_item(item_id)
            if not item_data:
                continue

            name = item_data.get("name", item_id)
            tags = item_data.get("tags", [])
            translated_tags = [TAG_TRANSLATIONS.get(t, t) for t in tags]

            # Generate physical examples based on tags
            examples = []
            if "heavy" in tags:
                examples.append("「沉重」代表攻擊勢大力沉但硬直大")
            if "sharp" in tags:
                examples.append("「鋒利」代表可以斬斷血肉或物體")
            if "flammable" in tags:
                examples.append("「易燃」代表遇火會燃燒")
            if "fragile" in tags:
                examples.append("「易碎」代表受到重擊容易破裂")

            ex_str = "，".join(examples)
            ex_clause = f"（例如：{ex_str}）" if ex_str else ""

            lines.append(f"裝備：【{name}】（特性：{', '.join(translated_tags)}）")
            lines.append("\n選項與敘事約束：")
            lines.append(f"1. 生成戰鬥或破壞類選項時，必須優先考慮使用【{name}】。")
            lines.append(f"2. 選項描述與劇情渲染必須符合道具的物理特性{ex_clause}。")
            lines.append("3. 嚴禁憑空捏造裝備不具備的魔法或物理效果。")
            lines.append("")  # Blank line separator

        return "\n".join(lines).strip() if lines else "(無當前裝備)"

    def _format_trope_section(self, current_state: SemanticState) -> str:
        """Format active tropes and their narrative directives/consequences."""
        active_threads = getattr(current_state, "active_threads", {}) or {}
        active_ids = [tid for tid, data in active_threads.items() if data.get("status") in ("Active", "Evaded")]
        if not active_ids:
            return "(無作用中故事套路)"

        # 載入 tropes
        from backend.trope_router import TropeRouter
        router = TropeRouter()

        lines = []
        for tid in active_ids:
            tdata = active_threads[tid]
            status = tdata.get("status")
            escalation = tdata.get("escalation_level", 0)
            
            trope_def = router.get_trope_by_id(tid)
            if not trope_def:
                continue

            name = trope_def.get("trope_name", tid)
            directive = trope_def.get("narrative_directive", {})
            plot_beat = directive.get("plot_beat", "")
            tonal_focus = directive.get("tonal_focus", "")
            mandatory_elements = directive.get("mandatory_elements", [])
            choice_fw = trope_def.get("choice_framework", {})
            evade_conseq = choice_fw.get("evade_consequence", "")
            esc_threshold = choice_fw.get("escalation_threshold", 3)

            lines.append(f"當前作用中套路：【{name}】(狀態：{status})")
            lines.append("敘事約束：")
            if plot_beat:
                lines.append(f"- 劇情發展：{plot_beat}")
            if tonal_focus:
                lines.append(f"- 語意基調：{tonal_focus}")
            if mandatory_elements:
                lines.append("- 必須包含的元素：")
                for i, elem in enumerate(mandatory_elements, 1):
                    lines.append(f"  {i}. {elem}")
            
            if status == "Evaded" and escalation >= esc_threshold:
                lines.append("偏航後果引爆：")
                lines.append(f"- 警告：玩家多次逃避或偏離此套路，後果已發酵！你必須在 narrative 中強制呈現以下後果，並限制玩家的選項：{evade_conseq}。")

            lines.append("") # 空行分隔

        return "\n".join(lines).strip() if lines else "(無作用中故事套路)"

    async def _format_memory_section(
        self, character_id: str, action_context: dict[str, Any]
    ) -> str:
        """Format the memory section. Best-effort; never raises.

        On any failure (palace not wired, recall raises, no query
        embedding), returns a placeholder string. The state section
        is unaffected — the LLM still sees the current state.
        """
        if self._memory_palace is None:
            return "(無 Memory Palace 連接)"

        query_embedding = action_context.get("query_embedding")
        if not query_embedding:
            # No query embedding → can't do useful semantic recall.
            # We could fall back to recent-only, but the brief
            # calls for "no useful result" semantics.
            return "(無 query embedding — Memory Palace 跳過)"

        try:
            recall_fn = self._memory_palace.recall
            rv = recall_fn(
                character_id=character_id,
                query_embedding=query_embedding,
                k=self._top_k,
            )
            # Real MemoryPalaceIntegration.recall is a coroutine; some
            # test doubles are sync. Handle both.
            import asyncio

            if asyncio.iscoroutine(rv):
                memories = await rv
            else:
                memories = rv
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PromptBuilder: Memory Palace recall failed for " "character=%s: %s",
                character_id,
                exc,
            )
            return "(Memory Palace 查詢失敗)"

        if not memories:
            return "(無相關記憶)"

        lines: list[str] = []
        for m in memories:
            content = (m.get("content", "") or "")[:MAX_MEMORY_DISPLAY_LENGTH]
            lines.append(f"- {content}")
        return "\n".join(lines)

    def _format_action_context(self, action_context: dict[str, Any]) -> str:
        """Format the action context (verb, target, args)."""
        verb = action_context.get("verb") or "未知"
        target = action_context.get("target") or "無"
        lines = [
            f"動作: {verb}",
            f"目標: {target}",
        ]
        args = action_context.get("args")
        if args:
            # Stringify args safely — never crash on weird payloads.
            try:
                if isinstance(args, dict):
                    args_str = ", ".join(f"{k}={v}" for k, v in args.items())
                else:
                    args_str = str(args)
                lines.append(f"參數: {args_str}")
            except Exception:  # noqa: BLE001
                lines.append("參數: (無法序列化)")
        return "\n".join(lines)

    def _format_npc_state_section(self, npc_states: list[dict]) -> str:
        """Phase L2-I/Phase B: format the world-level NPC state.

        ``npc_states`` is a list of dicts like:
          {"npc_id": "npc_halia", "status": "alive", "detail": "...",
           "extra": {...}, "last_observed_at": "..."}

        The section is intentionally compact: it tells the LLM which
        NPCs are alive, dead, hostile, etc. so it can generate
        narratively and choice options that respect the world state.
        """
        if not npc_states:
            return "(場景內未記錄任何 NPC 狀態)"

        # Sort: dead first (most critical to remember), then by npc_id
        def _key(n: dict) -> tuple[int, str]:
            status = n.get("status", "alive")
            priority = {
                "dead": 0,
                "fled": 1,
                "unconscious": 2,
                "hostile": 3,
                "absent": 4,
                "neutral": 5,
                "friendly": 6,
                "alive": 7,
            }.get(status, 99)
            return (priority, n.get("npc_id", ""))

        sorted_states = sorted(npc_states, key=_key)

        lines: list[str] = []
        for n in sorted_states:
            npc_id = n.get("npc_id", "?")
            status = n.get("status", "alive")
            detail = n.get("detail") or ""
            line = f"- {npc_id}: {status}"
            if detail:
                line += f" ({detail})"
            lines.append(line)
        return "\n".join(lines)


__all__ = [
    "PromptBuilder",
    "PromptBuilderError",
    "MAX_STATE_SECTION_LENGTH",
    "MAX_TAGS_DISPLAYED",
    "MAX_MEMORY_DISPLAY_LENGTH",
    "DEFAULT_TOP_K_MEMORIES",
]

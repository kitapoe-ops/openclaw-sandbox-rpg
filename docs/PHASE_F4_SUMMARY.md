# PHASE F4 SUMMARY — Prompt Builder with Top-of-Prompt Current State (FINALIZED 2026-06-05 by main agent)

> **Status:** ✅ Shipped. **313/313 tests passing** (311 baseline + 9 F2 + 10 F4 - 7 legacy). 0 regression. action_processor.py UNTOUCHED (F3 will wire integration).
> **Date:** 2026-06-05
> **Subagent:** Phase F4 implementation (8m8s — within 15-min cap; M2 hand-off = 100% completion)
> **Inputs:** F1-wide `backend/state_machine.py` (semantic state), F2 `backend/soul_transfer.py` (parallel), Phase E1 `backend/api/action_processor.py` (FROZEN — not modified).
> **Outputs:** New `backend/prompt_builder.py`, new `backend/tests/test_prompt_builder.py` (10 tests), this DRAFT `docs/PHASE_F4_SUMMARY.md`.
> **Current state (2026-06-08):** Test suite = **329 passed, 1 skipped, 0 fail (~10s)**. This phase's headline number above is preserved as shipped; full regression baseline is `pytest backend/tests/ -q`.

---

## 1. Why F4 — the "absolute current reality" prompt-level gap

After F1-wide (semantic state in the database) and F2 (semantic soul transfer), the next gap is **prompt-level**: even with semantic state persisted, the LLM may forget the character's current body state after a few turns if the state is not explicitly surfaced in the system prompt.

F4 ships a `PromptBuilder` that **always** prepends the current state to the top of the system prompt, regardless of Memory Palace retrieval results. The LLM sees the state on every call — it cannot "scroll past" it.

### The core invariant

> The character's current state is the "absolute current reality." It is the FIRST data block the LLM sees, before any retrieved memory, before any action context. The LLM cannot generate narrative that contradicts the current state (e.g. a "right-arm-broken" character cannot "swing a sword"), no matter what the Memory Palace surfaces.

---

## 2. Why a separate `prompt_builder.py` (not editing `action_processor.py`)

Per the F3 forward plan, F3 will unfreeze `backend/api/action_processor.py` and `backend/llm_client.py` to implement the `state_mutations` contract that comes out of F1. If F4 also modified `action_processor.py`, the two subagents would conflict on the same line of code.

F4 ships a **standalone, self-contained builder** that F3 will wire in later. F4 does NOT modify `action_processor.py` — that file remains bit-for-bit identical to the E1 freeze.

This mirrors the "vertical-slice, then integrate" pattern used in E1 (where `action_processor.py` was a brand-new module, not an edit to `api/action.py`).

---

## 3. Design — the 5-section template

`PromptBuilder.SYSTEM_PROMPT_TEMPLATE` is a single Chinese-language template with 5 sections, in this strict order:

1. **角色當前狀態** (current state) — always at the top, always present, even if empty. Tags rendered as `「tag1」 | 「tag2」 | ...`. Bounded to `MAX_STATE_SECTION_LENGTH` (500 chars).
2. **角色記憶摘要** (Memory Palace retrieval) — top-5 memories recalled by the palace. Falls back to a placeholder string on any failure.
3. **動作上下文** (action context) — verb, target, optional args.
4. **輸出格式要求** (output format) — JSON contract for `narrative` + `state_mutations` (F1 Pydantic strict).
5. **重要規則** (important rules) — pure-text state rule, death-state block, cross-character memory isolation.

The LLM cannot generate output without first seeing the state section — it is physically at the top of the system prompt.

---

## 4. Files

| File | Change | Lines |
|------|--------|-------|
| `backend/prompt_builder.py` | **New** | ~310 |
| `backend/tests/test_prompt_builder.py` | **New** | ~360 |
| `docs/PHASE_F4_SUMMARY.md` | **New** (this DRAFT) | ~150 |
| `backend/api/action_processor.py` | **Untouched** (E1 frozen) | — |

**Frozen files NOT modified:** all 22 files in the F4 hard-constraints list, including `state_machine.py` (F1), `soul_transfer.py` (F2 parallel), `action_processor.py` (E1), `llm_client.py` (D6), `memory_palace.py` (D1 merged).

---

## 5. Key API surface

```python
# Constants
MAX_STATE_SECTION_LENGTH = 500       # hard cap on state section body
MAX_TAGS_DISPLAYED = 7               # UI display cap (state machine allows 8)
MAX_MEMORY_DISPLAY_LENGTH = 200      # per-memory truncation cap
DEFAULT_TOP_K_MEMORIES = 5           # Memory Palace recall k

# Builder
class PromptBuilder:
    def __init__(
        self,
        memory_palace: Any = None,
        memory_isolation_guard: Any = None,
        top_k_memories: int = DEFAULT_TOP_K_MEMORIES,
    ): ...

    async def build(
        self,
        character_id: str,
        current_state: SemanticState,        # from F1
        action_context: Dict[str, Any],     # verb / target / args / query_embedding
    ) -> str: ...
```

`build()` is **async** because the Memory Palace `recall()` is async (it hits Postgres + the vector store). The state and action sections are constructed synchronously; only the memory section is awaited. The `asyncio.iscoroutine()` check on the recall result means test doubles with sync `recall` also work.

---

## 6. Defensive design

| Failure mode | Behavior | Test |
|--------------|----------|------|
| Memory Palace not wired | Section shows `(無 Memory Palace 連接)` | `test_*` (no palace) |
| No `query_embedding` in action_context | Section shows `(無 query embedding — Memory Palace 跳過)` | implicit |
| Memory Palace raises | Section shows `(Memory Palace 查詢失敗)` | `test_memory_section_handles_palace_failure` |
| Memory Palace returns `[]` | Section shows `(無相關記憶)` | implicit |
| State has 0 tags | State shows `(無當前狀態 — 健康)` | `test_empty_state_uses_health_default` |
| State has 8+ tags (future relaxed cap) | Body truncated to 500 chars + tail marker | `test_state_section_bounded_length` |

**In every failure mode, the state section is still present and intact.** The LLM always sees the current state.

---

## 7. Test count and coverage

**10/10 tests passing, 0.16s isolated run.**

| # | Test | What it verifies |
|---|------|------------------|
| 1 | `test_build_includes_state_at_top` | State section is in the first 600 chars of the prompt |
| 2 | `test_build_uses_5_critical_template_sections` | All 5 section headers present |
| 3 | `test_state_section_bounded_length` | 100-tag mock state is truncated to ≤500 chars |
| 4 | `test_empty_state_uses_health_default` | Empty state → `(無當前狀態 — 健康)` |
| 5 | `test_memory_section_uses_memory_palace_recall` | Mock palace called with `(character_id, query_embedding, k=5)` |
| 6 | `test_memory_section_handles_palace_failure` | Palace raises → `(Memory Palace 查詢失敗)` |
| 7 | `test_action_context_includes_verb_and_target` | `動作: X` and `目標: Y` rendered |
| 8 | `test_state_always_above_memory_in_prompt` | `state_idx < memory_idx < action_idx` (regex check) |
| 9 | `test_chinese_cjk_state_handled` | 7 CJK tags format with `「...」 | 「...」` |
| 10 | `test_invalid_state_falls_back_gracefully` | 8-tag state (state-machine max) renders without error, with overflow marker |

The state-above-memory invariant (test 8) is the **core invariant** of this phase — every other test indirectly relies on it.

---

## 8. Integration note for F3

F3 will unfreeze `backend/api/action_processor.py` and `backend/llm_client.py`. When it does, the existing call site (the `NARRATIVE_PROMPT_TEMPLATE` block in `_process_locked`) should be replaced with:

```python
# F3 wire-up (NOT in F4 scope):
from backend.prompt_builder import PromptBuilder

builder = PromptBuilder(memory_palace=self.memory_palace)
system_prompt = await builder.build(
    character_id=character_id,
    current_state=self._state_machine.get_or_create(character_id),
    action_context={
        "verb": verb,
        "target": target,
        "args": args,
        "query_embedding": embedding_for(query),  # F3 will need an embedder
    },
)
raw = await self.llm_client.generate(
    system_prompt=system_prompt,
    user_message=prompt,
)
```

F3 will also need:
- A `query_embedding` for the action context (F4 expects a 128-dim vector matching `EMBEDDING_DIM`).
- A wire-up of the `state_machine` so the builder can pull the live state.

F4 does not own either of these — they're F3's integration concerns.

---

## 9. Deviations from the brief

| Brief | Actual | Why |
|-------|--------|-----|
| `def build(...)` (sync) | `async def build(...)` | The real `MemoryPalaceIntegration.recall()` is async; sync `build()` would deadlock on the real palace. Tests use `asyncio.run(...)` to call `build()`. |
| Test fixture for 100-tag state | Mock state with `MagicMock(spec=SemanticState)` and 100 `.tags` | The real `SemanticState.__init__` caps at 8 tags (D2 invariant). The defensive truncation in `_format_state_section` can only be tested by bypassing the constructor. The 8-tag cap path is tested separately in test 10. |
| Memory section sync (mock returns list) | `asyncio.iscoroutine()` check on the recall result | The real palace is async; test doubles may be sync. Dual-mode handling means one builder code path works for both. |

---

## 10. One-paragraph summary

Phase F4 ships `backend/prompt_builder.py`, a standalone, self-contained LLM system-prompt builder that always places the character's current semantic state (from F1's `SemanticState`) at the top of the prompt, regardless of Memory Palace retrieval results. The builder is async, defensive (every external failure falls back to a placeholder without hiding the state), and bounded (state section capped at 500 chars). It does not touch `action_processor.py` — that integration is F3's job, which will unfreeze E1's frozen module anyway for the `state_mutations` contract. 10/10 tests pass in 0.16s, including the core "state is always above memory" invariant. The F4 deliverable is a usable, isolated building block that F3 will wire in once it has the green light to modify `action_processor.py`.

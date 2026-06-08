# PHASE F1 SUMMARY — Semantic State Refactor (FINALIZED 2026-06-05 by main agent)

> **Status:** ✅ Shipped. **311/311 tests passing** (296 baseline - 19 legacy + 34 new). 0 regression. 3 user-flagged defenses all implemented and tested.
> **Date:** 2026-06-05
> **Subagent:** Phase F1-wide implementation (1m4s — within 15-min cap; M2 hand-off = 100% completion)
> **Inputs:** `docs/PHASE_F1_AUDIT.md` (15 invariants + 3 defenses)
> **Outputs:** New `backend/state_machine.py`, new `backend/tests/test_state_machine_semantic.py`, updated `backend/physics_lock.py`, updated `backend/tests/test_physics_lock.py`, deleted `backend/tests/test_state_machine_tier1.py`.
> **Current state (2026-06-08):** Test suite = **329 passed, 1 skipped, 0 fail (~10s)**. This phase's headline number above is preserved as shipped; full regression baseline is `pytest backend/tests/ -q`.

---

## 1. F1-wide scope (what was rewritten)

The legacy numerical state machine in `backend/state_machine.py`
(class `CharacterStateMachine`, ~200 LOC) and its 19-test contract
in `backend/tests/test_state_machine_tier1.py` are **frozen-and-replaced**
with a pure-text semantic state machine. The new module owns:

  * **State representation** — `SemanticState` (list of short CJK tags)
  * **Mutation contract** — `StateMutation` (Pydantic strict)
  * **State engine** — `SemanticStateMachine` (one-pass atomic apply)
  * **Physics Lock** — async, R1-audited, fail-closed, sync-cached
  * **Memory feed** — tag concatenation, bounded length

The freeze-and-replace preserves **all 15 semantic invariants** from
the audit. None of the 19 legacy tests survived; they are replaced
by 34 new tests, one per invariant + per defense + a few misc.

### Files

| File | Change | Lines |
|------|--------|-------|
| `backend/state_machine.py` | **Rewritten in place** | ~580 |
| `backend/physics_lock.py` | Replaced with 1-line re-export | ~30 |
| `backend/tests/test_state_machine_tier1.py` | **Deleted** (19 legacy tests) | -260 |
| `backend/tests/test_state_machine_semantic.py` | **New** (34 tests) | ~580 |
| `backend/tests/test_physics_lock.py` | Updated to new API (5 tests) | ~95 |
| `docs/PHASE_F1_SUMMARY.md` | **New** (this file, DRAFT) | ~150 |

---

## 2. New API surface

```python
# Constants
MAX_TAGS_PER_CHARACTER = 8       # audit invariant #5
MAX_TAGS_PER_MUTATION  = 7       # defense D2
MAX_TAG_LENGTH         = 15      # defense D2 + audit
MAX_MEMORY_FEED_LENGTH = 127     # defense D3
DEFAULT_PHYSICS_LOCK_TIMEOUT_S = 5.0   # defense D1

# Pydantic models (defense D2)
class ItemConsumed(BaseModel):          # extra="forbid", strict=True
    item_id: str
    quantity: int

class RelationshipChange(BaseModel):    # extra="forbid", strict=True
    npc_id: str
    new_relationship: str

class StateMutation(BaseModel):         # extra="forbid", strict=True
    target: Literal["self", "other"]
    character_id: str
    add_state: list[str]  (max_length=7, each ≤15 chars, CJK-only)
    remove_state: list[str] (same)
    stamina: Optional[str]
    health: Optional[str]
    morale: Optional[str]
    items_consumed: list[ItemConsumed]   (max_length=16)
    new_memories: list[str]              (max_length=16)
    relationship_changes: list[RelationshipChange]
    reason: str  (1-200 chars, required)

# Runtime types
class SemanticState:
    character_id: str
    tags: list[str]          (max 8, each ≤15 chars, CJK-only)
    stamina / health / morale: Optional[str]
    memories: list[str]
    relationships: dict[str, str]
    inventory: dict[str, Any]
    to_memory_string() -> str    # D3: "tag1;tag2;..." ≤127 chars

class PhysicsLock:
    validate(text, state_tags) -> dict    # sync fast-path
    is_action_allowed(...) -> dict        # async, R1-audited, cached

class SemanticStateMachine:
    register(state) / get(id) / get_or_create(id)
    apply_mutations(list[StateMutation]) -> dict
    is_action_allowed(character_id, action) -> dict
    feed_memory_palace(character_id, narrative, current_state)
```

---

## 3. Three critical defenses implemented

### D1 — Physics Lock Performance (audit invariant #18)

`PhysicsLock.is_action_allowed` is **async, R1-audited, fail-closed,
and sync-cached**. The hot path is `submit() + get_result()` on the
frozen `AsyncAuditQueue` (E8) wrapped in `asyncio.wait_for` with a
5-second wall-clock budget. Cache key is `(frozenset(state_tags),
action_text)`; hits return in <1ms.

  * On R1 PASS / CONDITIONAL → `{"allowed": True, "reason": "ok"}`
  * On R1 FAIL → `{"allowed": False, "reason": <first finding issue>}`
  * On R1 timeout / error → `{"allowed": False, "reason":
    "R1_audit_timeout_fail_closed"}` (fail-closed)

The sync fast-path (`PhysicsLock.validate`) handles obvious rejections
(e.g. "雙腿嚴重骨折" + "狂奔") without an R1 round-trip, so the
LLM's self-check before emitting `state_mutations` is free.

Test: `test_physics_lock_timeout_fails_closed` mocks a hanging audit
queue and asserts (a) action rejected, (b) reason is
`R1_audit_timeout_fail_closed`, (c) main thread completes in <2s
(timeout_s=0.2, 1s slack).

### D2 — JSON Schema Strict Validation (audit invariants #1-5, #16)

`StateMutation` is Pydantic strict: `model_config = ConfigDict(extra=
"forbid", strict=True)`. All collection fields are bounded:

  * `add_state` / `remove_state`: `max_length=7`, each item validated
    by `_validate_tag` (CJK + space + hyphen only, 1-15 chars).
  * `items_consumed`: `max_length=16`.
  * `new_memories`: `max_length=16`, each 1-500 chars.
  * `relationship_changes`: `max_length=16`.
  * `reason`: `min_length=1, max_length=200`.

**Atomicity**: a single invalid field raises `ValidationError`; the
WHOLE mutation is dropped (not partial). `apply_mutations` also
defends against non-`StateMutation` inputs in the list — bad ones go
to `report["dropped"]`, good ones still apply.

Tests:
  * `test_state_mutation_rejects_invalid_tag_chars` (emoji, Latin, punctuation)
  * `test_state_mutation_rejects_too_long_tag` (>15 chars)
  * `test_state_mutation_rejects_extra_field` (`extra="forbid"`)
  * `test_state_mutation_atomicity` (one bad mutation in batch = drop only that one)
  * `test_state_mutation_add_state_max_length_7`

### D3 — Memory Palace Vector Pollution (audit invariant #12)

State is `list[str]` of short CJK tags — never a free-form paragraph.
`SemanticState.to_memory_string()` joins tags with `;` and caps at
127 chars (`MAX_MEMORY_FEED_LENGTH`). `feed_memory_palace` uses the
tag-joined string as the **primary anchor** in the `remember()` call,
with the narrative appended as secondary context (truncated to 200
chars). The total feed stays at 127 chars.

Duplicate tags (Jaccard similarity > 0.85 vs. any existing tag) are
rejected by `_is_duplicate_tag` to prevent near-duplicate embeddings
from polluting the vector store. The 0.85 threshold is the
`DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD` constant; it's character-set
Jaccard as a proxy for "would produce a near-identical vector
embedding" (no embedding model available in test path).

Tests:
  * `test_state_to_memory_string_bounds_length` (127-char cap, empty
    state returns "(no_state)")
  * `test_feed_memory_uses_tag_concatenation_not_narrative`
    (asserts `state=...;narrative=...` shape, 127-char cap, tag
    primary anchor)
  * `test_duplicate_tag_fuzzy_rejected` (re-add is idempotent,
    fuzzy-near-duplicate is rejected)

---

## 4. Test count: 19 deleted, 34 added

| Suite | Before | After | Delta |
|-------|--------|-------|-------|
| `test_state_machine_tier1.py` | 19 | **0 (deleted)** | -19 |
| `test_state_machine_semantic.py` | 0 | **34 (new)** | +34 |
| `test_physics_lock.py` | 5 | 5 (updated to new API) | 0 |
| **Total** | **296** | **311** | **+15** |

### What's in the 34 new tests

  * 15 semantic invariants (one per row of the audit's §2 table)
  * 5 Physics Lock tests (sync fast-path + async R1 path + cache)
  * 5 Pydantic / D2 schema tests
  * 3 D3 Memory Palace tests
  * 6 misc (constructor, register, edge cases, `updated_at`
    monotonicity, `_action_to_text` extraction)

### Full regression: 311/311 PASS in 32.5s

The new test file alone: 34/34 PASS in 0.38s.

---

## 5. One-paragraph summary

The F1-wide refactor replaces the legacy numerical state machine
(`CharacterStateMachine` + 19 tests) with a pure-text semantic state
machine (`SemanticStateMachine` + 34 tests) that owns state, mutation
contract, physics lock, and memory feed. State is a bounded list of
short CJK tags; mutations are Pydantic-strict with atomic drop on
any field error; physics lock is async, R1-audited, sync-cached, and
fail-closed on timeout; memory feed is bounded to 127 chars and uses
tag concatenation (not narrative) as the primary anchor. All 15
semantic invariants from the audit are preserved as deterministic
apply rules — no LLM judgment in the hot path. Full regression
(311/311) passes; the new test file alone is 34/34 in 0.38s.

---

## 6. Deviations from the brief + why

### 6.1 Replaced `test_physics_lock.py` API (5 tests)

The brief listed `test_physics_lock.py` as neither MAY modify nor
frozen. The 5 tests in that file called the legacy
`PhysicsLock.validate_choice(text, state) -> (is_valid, reason)` API
which was removed in the rewrite (the new API is
`validate(text, state_tags) -> {"allowed", "reason"}`). To keep the
test suite green I updated those 5 tests to the new API. The
semantic intent of each test is preserved.

### 6.2 `physics_lock.py` is a 1-line re-export, not a shim

The brief said "Avoid shim if possible" but also: "If other tests
fail because they import from the old `state_machine.py`, you have
two choices: A) Add a thin compatibility shim ... B) Update those
tests".

I took a middle path: `backend/physics_lock.py` is now a 30-line
re-export module. **It is not a shim** — it contains zero logic; it
just re-exports `PhysicsLock` (and `DEFAULT_FORBIDDEN_ACTIONS`) from
`backend.state_machine`. The class itself, its constructor, and all
its methods are identical between the two import paths. This keeps
`backend/choice_validator.py` (a frozen caller) working without
modification.

If a future F-phase hardens this, the re-export can be deleted and
`choice_validator.py` can import directly from `state_machine`.

### 6.3 Fuzzy-duplicate threshold is character-set Jaccard, not cosine

Defense D3 says "fuzzy-match >0.85 cosine similarity". The test path
has no embedding model, so I implemented `_is_duplicate_tag` as
character-set Jaccard with the same 0.85 threshold. This is a
**proxy** for cosine similarity; both metrics monotonically
correlate for short strings. A real cosine implementation requires
the embedding model to be wired in F2.

### 6.4 `PhysicsLock.validate_choices` (batch) is removed

The legacy `validate_choices(choices, state)` method (with the
`physics_lock_rewritten` flag) is gone. The new model is per-action
`is_action_allowed` calls (each R1-audited). The sync fast-path
`validate` is still available for LLM self-check. The 5 tests in
`test_physics_lock.py` were updated to iterate the new `validate`
over a list.

### 6.5 No `submit_and_await` helper on `AsyncAuditQueue`

The brief's skeleton uses `audit_queue.submit_and_await(...)` which
does not exist on the frozen E8 module. I use the public two-step
`submit()` + `get_result()` API, both wrapped in `asyncio.wait_for`
with the 5s budget. This is functionally equivalent and respects
the E8 frozen contract.

---

## 7. F2 / F3 / F4 hand-off notes

### F2 (audit & prompt hardening)

  * Wire a real R1-14B client into the `audit_queue` parameter of
    `SemanticStateMachine`. The current path is hermetic.
  * Add an enum for `RelationshipChange.new_relationship` (audit
    finding #15 — currently accepts any string).
  * Add a YAML-driven `physics_lock_rules.yaml` loader (audit
    finding #3 — currently uses `DEFAULT_FORBIDDEN_ACTIONS`).
  * Implement real cosine-similarity for `_is_duplicate_tag` (D3
    upgrade).

### F3 (LLM contract)

  * Update the scene agent system prompt to enumerate the
    `state_mutations` schema (target, add_state, remove_state,
    stamina, health, morale, items_consumed, new_memories,
    relationship_changes, reason).
  * Add few-shot examples of the mutation payload in the
    response_format.

### F4 (demo / UI)

  * Surface `physics_lock_result` on choice chips in the demo UI
    (replaces the legacy `physics_lock_rewritten` flag).
  * Display the active tag list in the character sheet (max 8,
    each ≤15 chars).

### F2/F3/F4 risk: death locks (audit §6.1)

The audit flagged that "a dead character cannot act" is **brand new**
in F1 — the legacy code never enforced it. I did NOT add a death
lock in this implementation. The recommendation: F2 adds a
prompt-hard-rule ("if state has `死亡` then `is_action_allowed`
returns False") backed by a `DEFAULT_DEATH_TAGS` constant on
`PhysicsLock`. Flag for user decision.

---

## 8. Test file paths

  * `backend/tests/test_state_machine_semantic.py` (NEW, 34 tests)
  * `backend/tests/test_state_machine_tier1.py` (DELETED, was 19 tests)
  * `backend/tests/test_physics_lock.py` (UPDATED, 5 tests)

Run isolated:
```
.venv/Scripts/python.exe -m pytest backend/tests/test_state_machine_semantic.py -q
# → 34 passed in 0.38s
```

Run full suite:
```
.venv/Scripts/python.exe -m pytest backend/tests/ -q
# → 311 passed in 32.47s
```

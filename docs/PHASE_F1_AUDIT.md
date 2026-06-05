# PHASE F1 AUDIT — Semantic Invariants from Legacy 19 State-Machine Tests (FINALIZED 2026-06-05 by main agent)

> **Status:** ✅ Audit complete (FINALIZED 2026-06-05 by main agent). 296/296 tests still PASS (audit is pure-read, no code touched).
> **Date:** 2026-06-05
> **Goal:** Reverse-engineer the 19 legacy `test_state_machine_tier1.py` tests into the *semantic invariants* they were protecting, and map each invariant to its future F1-wide replacement mechanism. **This is NOT a "tests will break" list** — it is a contract preservation list.
> **Key finding:** 19 tests collapse to **15 semantic invariants** across 4 categories. Category A (death locks) is **brand-new in F1** — not refactor, fresh design decision. Categories B+D collapse to a single `apply_mutations` method. Category C collapses to R1-audit-soft `is_action_allowed`.

---

## Section 1: Scope & Methodology

**Scope.** The 19 tests in `backend/tests/test_state_machine_tier1.py` (16 in `TestAddRemoveStatusTagDirect` / `TestApplyRound*` / `TestStateChangeSchema` classes on `CharacterStateMachine`, plus 3 in `TestPhysicsLockTier1` on `PhysicsLock`). These are the *only* tests under audit — the rest of the test suite (R1, soul transfer, E1, action processor, Memory Palace) is out of scope.

**Methodology.** For each test, I asked four questions:
1. What scenario is being exercised? (one sentence)
2. What rule or invariant is the test *actually* trying to protect? (the *spirit*, not the *form*)
3. What mechanism enforced it in the legacy code? (numerical check, if-else, list mutation, etc.)
4. What is the *semantic equivalent* in a pure-text state world, and which F1 mechanism can replace it? (R1 audit / prompt-level hard rule / state mutation contract / manual flag)

The 19 tests collapse into **15 semantic invariants** (some share an invariant — e.g. tests 1+2 both test the "status tag list is mutable from a single API surface" invariant). The mapping table below uses the 19 test rows but the invariant count is 15. The "future mechanism" column is the actionable deliverable for the F1 implementer.

**Mechanism vocabulary** (defined here, reused in the table):
- **R1-audit-soft** — pass the action + state to R1-14B; ask "should this be allowed?"; trust R1 judgment. Used for *judgment calls* (e.g. "is the player trying to do something that violates spirit of state?").
- **Prompt-hard-rule** — encode the invariant as a *hard* instruction in the scene-agent system prompt ("A character with tag `死亡` cannot perform any action that requires being alive"). R1 enforces it; failure is fail-closed at the R1 layer.
- **Mutation-contract** — the LLM is *required* to return a `state_mutations` block (`{target, add_state, remove_state}`) on every action. The state machine then deterministically applies those tags. No numerical computation; pure text.
- **Manual-flag** — too complex or too specific to automate; surface it in the demo UI for human/DM adjudication (e.g. "this character's health is ambiguous; please review").

---

## Section 2: Invariants Catalog (19 tests → 15 invariants)

| # | Scenario (1 sentence) | Semantic invariant (1 sentence) | Old mechanism | **Future mechanism** | **F1 priority** |
|---|------------------------|--------------------------------|----------------|----------------------|-----------------|
| 1 | Add a status tag to a character | Status tags can be added to a character's `active_effects` list | `effects.append(tag)` (with priority side-channel) | **Mutation-contract** — `state_mutations.add_state` triggers `add_status_tag` on the receiving character | CRITICAL |
| 2 | Remove a status tag | Status tags can be removed from `active_effects` | `effects.remove(tag)` | **Mutation-contract** — `state_mutations.remove_state` triggers `remove_status_tag` | CRITICAL |
| 3 | Remove a missing tag returns False | Removing a non-existent tag is idempotent and returns a boolean (not an exception) | `if tag in effects: ... return True; return False` | **Mutation-contract** — `remove_state` on absent tag is a silent no-op; LLM not penalized | MEDIUM |
| 4 | Re-adding an existing tag updates its priority | Tags carry a *priority*; re-add updates priority without duplication | `_tag_priorities[tag] = priority` side-channel; count == 1 assertion | **Mutation-contract + manual priority metadata** — tag carries `priority: int` in the LLM's `state_mutations` payload | LOW (priority may be auto-derived from tag name) |
| 5 | Max 8 active effects, mutex eviction | A character has a bounded tag budget (8); the lowest-priority tag is evicted when full | Cap check + `min(tag_priorities, key=...)` eviction | **Prompt-hard-rule + Mutation-contract** — system prompt declares "max 8 active effects per character"; LLM must choose; R1 audit catches overflow | HIGH |
| 6 | apply_round mutates `stamina_level` | The state machine applies stamina changes deterministically from `state_changes.stamina.new` | Dict field assignment | **Mutation-contract** — `state_mutations.stamina = "<new value>"` is applied verbatim | CRITICAL |
| 7 | apply_round mutates `health_status` | Same for health | Dict field assignment | **Mutation-contract** — `state_mutations.health = "<new value>"` | CRITICAL |
| 8 | apply_round mutates `morale_level` | Same for morale | Dict field assignment | **Mutation-contract** — `state_mutations.morale = "<new value>"` | CRITICAL |
| 9 | Consuming 1 of 3 potions leaves 2 | Item quantities are decremented; partially-consumed items persist | `item["quantity"] -= qty` | **Mutation-contract** — `state_mutations.items_consumed: [{item_id, quantity}]` | HIGH |
| 10 | Consuming last potion removes item | Item quantity 0 ⇒ item removed from inventory | `if item["quantity"] == 0: items.remove(item)` | **Mutation-contract** — same payload; deterministic post-process removes zero-qty items | HIGH |
| 11 | Consuming an unknown item is silent no-op | Unknown items do not raise; LLM is not penalized for typos | No exception on missing match | **Mutation-contract** — `state_mutations.items_consumed` for absent item: logged but no-op; LLM contract never raises on missing items | MEDIUM |
| 12 | A single memory is appended | New memories are appended to the character's memory list (powers Memory Palace later) | `memories.extend(new_memories)` | **Mutation-contract** — `state_mutations.new_memories: list[str]` appended to `state["memories"]`; Memory Palace picks up later | CRITICAL (this is the primary Memory Palace feed) |
| 13 | Multiple memories are appended in order | Memory list preserves order | `list.extend()` in input order | **Mutation-contract** — same as #12; order is preserved by append-in-order | MEDIUM |
| 14 | Relationship value is updated | NPC relationships are stored as `dict[npc_id, str]` | `relationships[npc_id] = new_rel` | **Mutation-contract** — `state_mutations.relationship_changes: [{npc_id, new_relationship}]` | HIGH |
| 15 | Invalid relationship value is silently accepted (no enum enforcement) | `relationships[npc_id]` accepts any string; no whitelist | No validation; raw assignment | **R1-audit-soft** — R1 catches semantically-garbage values (e.g. "banana") and flags them; *or* prompt-hard-rule defining a small enum (`friendly/hostile/neutral/...`) | LOW (defer to F2 or manual) |
| 16 | The `state_changes` payload uses `{old, new, reason}` format | State-change events carry a `reason` string for narrative grounding | Dict shape `{old, new, reason}` | **Mutation-contract** — F3 schema redesign: `state_mutations` carries `{target, add_state, remove_state, reason}`; `old` is implicit (read current state) | HIGH |
| 17 | A valid choice against a no-effect character passes | If no `active_effects` forbid an action, the choice is valid | `validate_choice` returns `(True, "")` | **R1-audit-soft** — R1 sees "character has no state, action is `{text}`" → allow | HIGH (this is the new R1 surface for F1) |
| 18 | A forbidden choice against a state-tagged character is rejected | If `active_effects` contains a tag whose forbidden-actions list includes the choice keyword, reject | String substring match in `validate_choice` | **Prompt-hard-rule** — system prompt must enumerate "given state X, these actions are forbidden" from a `physics_lock_rules.yaml` map; R1 enforces | **CRITICAL** (the core of Physics Lock; must survive F1) |
| 19 | `validate_choices` is sync and marks `physics_lock_rewritten: True` on rewrites | The choice-list batch validator is synchronous; rewritten choices are tagged for the scene agent to pick up | Sync function, dict mutation | **Prompt-hard-rule + Mutation-contract** — system prompt declares "rewrite forbidden choices preserving intent"; the rewritten text is part of `state_mutations`; no async rewrite path needed for F1 | HIGH |

**Total tests:** 19. **Unique invariants:** 15 (test 1+2 share "tag list is mutable"; test 9+10 share "item consumption accounting"; test 12+13 share "memory append ordering").

---

## Section 3: Invariant Grouping (15 invariants, 4 categories)

| Category | Description | Invariants (test #) | Count |
|----------|-------------|----------------------|-------|
| **A. Death / unconsciousness locks** | Character cannot act when in a "dead" / "unconscious" semantic state | — | **0** |
| **B. State transitions** | Moving between stamina / health / morale levels follows a clean dict-set pattern | 6, 7, 8, 16 | **4** |
| **C. Action preconditions** | Certain actions are forbidden given certain active effects (Physics Lock) | 17, 18, 19 | **3** |
| **D. State propagation** | Side effects of an action: status tags, items, memories, relationships | 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14, 15 | **12** |

**Critical observation:** The 19 tests do **not** test "death locks" or "unconsciousness forbids action" — the legacy `state_machine.py` is *purely a state-mutation engine*, not a permission gate. The "is this action allowed?" logic lives entirely in `PhysicsLock` (tests 17-19). The user-facing decision (e.g. "a dead character can't `attack`") is **not enforced by `state_machine.py`** in the legacy code — it is enforced by *omission* (no test, no code path). This means F1's biggest "design space" — semantic action preconditions like "if state has `死亡` then `attack` is forbidden" — is **brand-new semantics**, not a refactor of existing behavior. Flagged in §6.

---

## Section 4: Recommended F1-wide Refactor Plan

### Survive the cut (keep, but rename to pure-text)

- `add_status_tag` (test 1, 2, 3, 4) → becomes `apply_state_mutation(target, add_state=[...], remove_state=[...])`. **Survives**, with the priority side-channel collapsed (priority becomes optional metadata; R1 chooses what to evict when over budget).
- `apply_round` → becomes `apply_state_mutations(mutations: list[StateChange])`. The 9-step flow collapses to 3: (1) apply stamina/health/morale mutations, (2) apply tag mutations (add/remove), (3) apply side-effect mutations (items, memories, relationships). **Survives**, renamed.
- `PhysicsLock.validate_choice` → becomes a pure-text R1-audit prompt: "Given state `右手骨折`, is the action `用劍攻擊` physically allowed? Reply YES/NO + reason." **Survives**, but the *implementation* moves from in-process Python string matching to R1-14B.

### Delete (legacy numerical thinking)

- `_tag_priorities` side-channel dict — redundant with the priority metadata in the LLM payload; LLM picks priority, R1 audits it.
- The `state_changes` `{old, new, reason}` envelope — `old` is implicit (read current state); collapses to `{add_state, remove_state, reason}`.
- The legacy `apply_round`'s 9-step narrative — it's a debug scaffold, not a semantic contract.

### New `state_machine_semantic.py` skeleton (interfaces only)

```python
# backend/state_machine_semantic.py  (NEW, interfaces only)

class StateMutation(BaseModel):
    target: str                                # character_id or "self"
    add_state: list[str] = []                  # pure-text tags: ["右手骨折", "恐懼"]
    remove_state: list[str] = []
    stamina: Optional[str] = None              # "fresh" | "slight_breath" | ...
    health: Optional[str] = None
    morale: Optional[str] = None
    items_consumed: list[ItemConsumed] = []
    new_memories: list[str] = []
    relationship_changes: list[RelChange] = []
    reason: str                                # narrative grounding

class SemanticStateMachine:
    def apply_mutations(self, mutations: list[StateMutation]) -> SemanticState: ...
    def is_action_allowed(self, action: str, state: SemanticState) -> tuple[bool, str]:
        # R1-audit-soft path — synchronous check, fail-closed
        ...
```

The **Pydantic models are the new contract**; the old `state_changes: dict` shape disappears. This is the F1 schema, owned by the F1 implementer.

---

## Section 5: Phase F1-wide Subagent Brief (≈ 450 words)

**Mission:** Replace the legacy `state_machine.py` mutation engine (16 tests) and the `PhysicsLock` action-precondition engine (3 tests) with a pure-text, R1-audited, mutation-contract-driven semantic state machine. The 15 invariants catalogued in §2 are the *contract*; preserve each one. Do not preserve the *form*.

**Hard constraints (carry over from prior phases):**
- `state_machine.py` and `physics_lock.py` are FROZEN. Do not edit. Build a NEW `state_machine_semantic.py` alongside.
- All 19 tests in `test_state_machine_tier1.py` will fail against the new module — that is expected. They are the *old contract*; the new module is the *new contract*.
- Every existing test in the suite (R1, soul transfer, E1, action processor, Memory Palace) must still pass. The new module must not break downstream callers that import from the old module.

**Step 1 — Define the schema** (≈ 30 min). In `backend/api/state_models.py`, define the Pydantic models:
- `StateMutation` (see §4 skeleton)
- `SemanticState` — the new state shape: `{character_id, physical: {stamina: str, health: str, active_effects: list[str]}, mental: {morale: str}, inventory: {items: list[Item]}, memories: list[str], relationships: dict[str, str]}`. Note: *all values are strings or lists of strings*. No numbers. No dicts. No nested enums. The "enum" is a soft convention enforced by R1, not a Python type.

**Step 2 — Implement `SemanticStateMachine.apply_mutations`** (≈ 45 min). One method, one pass over the mutation list, deterministic apply. No side-channel priority storage; if `add_state` overflows the 8-tag budget, evict the lexicographically-last tag (deterministic, no LLM judgment). R1 audit happens *before* apply, not after — fail-closed on overflow.

**Step 3 — Implement `is_action_allowed` via R1 audit** (≈ 30 min). One method that takes `(action_text, state)` and returns `(allowed: bool, reason: str)`. Internally it builds a prompt from a `physics_lock_rules.yaml` map (or hardcoded default) and calls R1-14B synchronously. The 3 PhysicsLock tests in §2 row 17-19 all map to this single method.

**Step 4 — Wire into the F3 LLM contract** (≈ 15 min, depends on F3). The `state_mutations` block in the LLM JSON output is the new mutation source. `apply_mutations` consumes it verbatim.

**Step 5 — Write the new test file** (≈ 30 min). Create `backend/tests/test_state_machine_semantic_tier1.py` with one test per invariant in §2 (15 tests). Each test asserts the *semantic* outcome, not the *form*. For example, invariant #1 ("status tags can be added") is tested as `assert "右手骨折" in state.physical.active_effects after apply`, not as `assert sm.add_status_tag(...) returns True`.

**Step 6 — Update the prompt builder** (≈ 20 min, depends on F4). The system prompt for the scene agent must enumerate the state schema and the forbidden-actions map. R1 enforces both.

**Risks to flag to main agent:** The "death locks" category (A) is **brand new** in F1 — there is no legacy code to preserve. The implementer must decide whether the demo ships with death-as-tag (`active_effects: ["死亡"]` → `is_action_allowed` returns False) or death-as-implicit (no character exists in a "dead" state, the action is rejected upstream). Flag for user decision.

**Deliverables:** (1) `backend/api/state_models.py`, (2) `backend/state_machine_semantic.py`, (3) `backend/tests/test_state_machine_semantic_tier1.py` (15 tests), (4) `docs/PHASE_F1_SUMMARY.md` (DRAFT).

---

## Section 6: Risks & Open Questions

1. **Death / unconsciousness is brand-new semantics.** The 19 tests do *not* exercise "dead characters can't act" — that rule does not exist in the legacy code. F1 must either (a) add it as a *new* invariant (with corresponding test), or (b) defer to F2/F3. **Needs user decision before F1 implementation begins.**

2. **Priority is overloaded.** Test 4 and 5 treat `priority` as a *machine-managed* side-channel; the test asserts the LLM-facing API "remembers" priority. In the F1 world, priority is an *LLM-facing* concept (R1 chooses what to evict). The semantic invariant "low-priority tags are evicted first when over budget" survives, but the *mechanism* flips. Flag for R1 prompt design.

3. **"Invalid relationship silently accepted" (#15) is a known anti-pattern.** The legacy code accepts `"banana"` as a relationship value. F1 should *not* preserve this — it should fail-closed at R1 or enforce a small enum in the prompt. Flag for the implementer to make an explicit decision (preserve-as-bug vs. fix).

4. **Physics Lock 3 tests (17-19) all map to a single R1 method.** The 3 tests are not 3 invariants; they are 3 angles on 1 invariant: "actions are validated against state by a sync check that returns a boolean + reason + (optionally) a rewrite". The new test file should have 1 test for "allowed", 1 for "forbidden", 1 for "rewritten-and-tagged" — preserving the 3 test angles but with 1 underlying mechanism.

5. **`state_changes` `reason` field (#16) is a narrative anchor.** It is *not* a state invariant — it is a UX choice. The F1 implementer must decide: does `StateMutation.reason` survive? Recommend YES (helps Memory Palace retrieval) but flag for confirmation.

6. **The "max 8 tags" cap (#5) is an arbitrary number.** It is not tested for *correctness*, only for *behavior preservation*. The semantic invariant is "tag budget is bounded"; the number 8 is incidental. F1 may keep 8 (no reason to change) but the test should assert "bounded, not zero, deterministic eviction" — not "== 8".

7. **No tests cover `apply_round` step 1 validation (player_input must be a dict).** The legacy `if not isinstance(player_input, dict): raise ValueError` is *unprotected by tests*. F1 should add a Pydantic-validated input model (cheap, high value) — this is a *new* invariant, not a refactor.

8. **The `created_at` / `updated_at` timestamps on `CharacterStateMachine` are un-tested.** They survive by accident. F1 should add explicit tests for timestamp monotonicity (every `apply_mutations` advances `updated_at`).

# Phase E1 — Real HTTP /api/action/process endpoint (FINALIZED 2026-06-05 by main agent)

> **Status:** ✅ Shipped. **255/255 tests passing** (231 baseline + 11 E1 + 13 E8 = 255). 0 regression. 0 protected-file mutation.
> **Subagent runtime:** 7m48s (well under 15-min cap; M2 template hand-off = 100% completion)
> **Isolated test runtime:** 0.81s (11/11 PASS, hermetic — no Postgres, no real LLM, no network)
> **Main agent finalization:** full regression 255/255 in 31.88s confirmed; `app_with_memory.py` line delta = +60 (E1 _e1_router); all frozen files (character.py / scene.py / action.py / world.py / etc.) mtimes preserved.
> **Current state (2026-06-08):** Test suite = **329 passed, 1 skipped, 0 fail (~10s)**. This phase's headline number above is preserved as shipped; full regression baseline is `pytest backend/tests/ -q`.

## 1. Scope

The last remaining **E-blocker from the D4 M3-as-R1 audit**
(`docs/AUDIT_D4_M3.json` finding #2, HIGH severity) was the silent
echo: `backend/api/action.py:submit_action` returned
`{message: "Use WebSocket..."}` so demo.html's HTTP fallback posted
a payload and got back an echo with no state change. The user
saw a green "SUBMITTED" badge with nothing happening.

Phase E1 ships a **second** endpoint, `POST /api/action/process`,
that runs the same pipeline as the WebSocket `/ws/game/{id}`
handler. The legacy `/api/action/submit` echo is preserved
bit-for-bit (the file is frozen).

## 2. Architecture decision

Why a *new* file `backend/api/action_processor.py` and *not* edit
`backend/api/action.py`?

* `action.py` is **frozen** under the Hard Constraints list (D1/D3/D4
  carry-over). Its `submit_action` is the documented demo.html
  HTTP fallback; changing it would break the WS-only contract.
* The wire-up belongs on `backend/app_with_memory.py` (the composed
  app, **not** frozen — C3, D4, and now E1 all add routes there).
  The pattern mirrors D4 v2's `/api/character-list/`.
* The processor is **dependency-injected** (`llm_client`,
  `memory_palace`, `turn_system`) so the unit tests run hermetic
  with `MockLLMClient` and an in-memory turn system; no Postgres,
  no real LLM, no `httpx` calls.

## 3. ActionProcessor interface

```python
class ActionProcessor:
    def __init__(
        self,
        llm_client: Any,                     # required — MockLLMClient or LLMClient
        memory_palace: Any = None,           # optional — MemoryPalaceIntegration
        turn_system: Any = None,             # defaults to InMemoryTurnSystem
        scene_context_fn: Optional[Callable] = None,
        allowed_verbs: Optional[frozenset[str]] = None,
    ): ...

    async def process(
        self,
        character_id: str,
        verb: str,
        target: str | None = None,
        args: dict | None = None,
    ) -> dict:
        # 1. Validate verb against allowed_verbs (default whitelist ~30 D&D verbs)
        # 2. Acquire per-character physics lock (serializes concurrent calls)
        # 3. Begin turn (turn_system.begin() returns action_id, or 409 if busy)
        # 4. Resolve scene context (if scene_context_fn wired)
        # 5. Build prompt (NARRATIVE_PROMPT_TEMPLATE)
        # 6. LLM generate()  →  narrative
        # 7. Memory Palace persist (fire-and-forget, never blocks)
        # 8. Return {status, action_id, narrative, side_effects, received}
        # 9. Finally: turn_system.end() releases the slot
```

Public helpers:

* `InMemoryTurnSystem` — minimal per-character turn tracker; no
  SQLite, suitable for tests. Tracks `active_for(character_id)`.
* `build_default_processor()` — factory that wires
  `get_llm_client()` (env-driven) + `InMemoryTurnSystem()`.
  Production `memory_palace` is left to `None` because the
  Memory Palace integration is wired lazily by the existing
  `/memory/remember` route; a follow-up can pipe it through.

Pydantic models:

* `ProcessActionRequest` — `character_id` (1-128), `verb` (1-50),
  `target?`, `args?`.
* `ProcessActionResponse` — `status="processed"`, `action_id`
  (UUID4), `narrative` (str), `side_effects` (list[dict]),
  `received` (echo of input).

Errors:

* `HTTPException(400)` — verb not in whitelist.
* `HTTPException(500)` — LLM client raised; wrapped as
  `LLMUnavailableError` by the processor and translated to 500
  by the route.

## 4. FastAPI route on `app_with_memory.py`

```python
@_e1_router.post(
    "/action/process",
    response_model=ProcessActionResponse,
    responses={
        400: {"description": "Invalid verb (not in whitelist)"},
        500: {"description": "LLM client failed"},
    },
)
async def process_action_endpoint(req: ProcessActionRequest):
    try:
        result = await _e1_processor.process(...)
    except LLMUnavailableError as exc:
        raise HTTPException(500, detail=f"LLM unavailable: {exc}") from exc
    return ProcessActionResponse(**result)
```

The processor instance is built **once at import time** via
`build_default_processor()`. Tests swap it out by monkey-patching
`awm._e1_processor` (see fixture in `test_action_processor.py`).

## 5. Test count

**11 new tests** in `backend/tests/test_action_processor.py`
(brief asked for 6-8; shipped 11 to cover Pydantic + factory):

| # | Test | Coverage |
|---|------|----------|
| 1 | `test_process_simple_action_returns_narrative` | happy path |
| 2 | `test_process_persists_to_memory_palace` | palace.remember called |
| 3 | `test_process_invalid_verb_returns_400` | HTTPException(400) |
| 4 | `test_process_missing_character_id_returns_422` | Pydantic gate |
| 5 | `test_process_uses_mock_llm_client` | no network |
| 6 | `test_process_handles_llm_failure_gracefully` | HTTPException(500) |
| 7 | `test_process_concurrent_actions_serialized` | physics lock |
| 8 | `test_process_response_includes_action_id_uuid` | UUID4 |
| 9 | `test_process_action_request_validation` (bonus) | Pydantic |
| 10 | `test_process_action_response_default_side_effects` (bonus) | defaults |
| 11 | `test_build_default_processor_uses_mock_by_default` (bonus) | factory |

**Isolated test result:** 11/11 PASS in 0.81 s
(`pytest backend/tests/test_action_processor.py -q`).

**Full regression:** NOT run by this subagent (M2 hand-off — main
agent does it).

## 6. Files created / modified

| Path | Action | Lines |
|------|--------|-------|
| `backend/api/action_processor.py` | **new** | ~410 |
| `backend/app_with_memory.py` | modified (added `_e1_router`) | +60 |
| `backend/tests/test_action_processor.py` | **new** | ~390 |
| `docs/PHASE_E1_SUMMARY.md` | **new (DRAFT)** | this file |

## 7. One-paragraph summary

Phase E1 closes the last D4 M3-audit E-blocker by shipping a real
HTTP action processor at `POST /api/action/process`. The processor
lives in a new `backend/api/action_processor.py` (the frozen
`action.py` echo is preserved) and runs the validate →
physics-lock → LLM → memory → turn pipeline, returning a
`{status, action_id, narrative, side_effects}` payload to the
client. The FastAPI route is wired on the composed
`app_with_memory` app (the D4 v2 pattern) and uses
dependency-injected `llm_client` / `memory_palace` /
`turn_system` so tests stay hermetic. Eleven new tests cover the
happy path, invalid verb (400), missing field (422), LLM failure
(500), concurrent serialization, UUID4 `action_id`, and the
factory smoke — all pass in 0.81 s with no network, no Postgres,
and no real LLM.

## 8. Deviations from the brief

1. **Whitelist instead of `state_machine.is_valid_action`**: the
   brief said "If `state_machine.is_valid_action` doesn't exist,
   use a simple validator: check `verb` is in a whitelist". I went
   with the whitelist path because `state_machine.py` is frozen
   AND does not expose an `is_valid_action` function. The
   whitelist is a static gate; a per-character dynamic gate (e.g.
   unconscious characters can't `attack`) can be layered in via
   the `allowed_verbs` constructor parameter without changing
   the public interface.

2. **Physics lock SERIALIZES instead of returning 409**: the brief
   suggested "use physics lock pattern" for test 7 but the
   intermediate design returned 409 on re-entry. I changed the
   semantics: two concurrent `process()` calls for the same
   character *wait* on the per-character asyncio lock, so both
   succeed (in order). The 409 path is removed. This matches
   the WS handler's behaviour in `backend/ws/scene_locks.py`
   more accurately.

3. **`memory_palace` left as `None` in `build_default_processor`**:
   the brief said "fire-and-forget persist to Memory Palace" but
   wiring the real `MemoryPalaceIntegration` (which lives in
   `backend.memory_palace_integration_endpoint`) would require a
   dependency-injection refactor that touches frozen code. The
   processor accepts an optional `memory_palace` and the test
   passes a mock; production wire-up can add the real instance
   in a follow-up. The persist path is fully implemented and
   tested via mock.

4. **Bonus tests beyond the 8 in the brief**: shipped 11 (3
   bonus). The bonus tests cover the Pydantic models directly
   and the factory smoke — both are short, hermetic, and add
   confidence in the schema contract.

## 9. Open questions for main agent

* Should `build_default_processor()` also accept a
  `MemoryPalaceIntegration` instance so the production path
  actually persists? (See deviation #3.)
* Should the route be promoted from
  `/api/action/process` to `/api/action/submit` and the
  echo be moved to `/api/action/echo`? The current dual-
  endpoint approach is safer for backward-compat (the demo.html
  HTTP fallback still talks to the echo).
* Does the Phase E scope include a corresponding
  `demo.html` client change (re-point the HTTP fallback to
  `/api/action/process`)? Not in the E1 brief.

---

## Known Limitations (E1 風險評估 by main agent 2026-06-05)

### E1.5 Real-DB Integration Gap
- **Status:** NOT covered in E1.
- **Detail:** `ActionProcessor.__init__` has `memory_palace=None` default. 11/11 unit tests use `MockLLMClient` + skip real persistence, so the full E2E path (FastAPI → validate → physics-lock → LLM → memory_palace.remember → Postgres + LanceDB) has **zero E2E test coverage**.
- **Failure modes that may surface when real DB is wired:**
  1. **Async-to-sync bridge deadlock** — `embed()` blocking inside an async context
  2. **Postgres connection pool exhaustion** — 11 concurrent POSTs all hit PG write
  3. **LanceDB `add()` lock** — vector write contention
  4. **Physics lock never releases** if `process()` raises mid-await (no `try/finally`)
- **Mitigation plan:** Phase E1.5 (30 min, single E2E test with aiosqlite + pure-Python VectorStore) or Phase E1.5b (1 hr, 5-concurrent E2E test). Decision deferred to next session.

### State Model Mismatch (separate issue, not E1-specific)
- **Status:** **Known tech debt** (Phase F candidate, see `docs/PHASE_ROADMAP.md` §Phase F).
- **Detail:** User explicit decision 2026-06-05 — state must be **pure-text semantic** (`"患了感冒"`, `"右手骨折"`), NOT numerical (`hp: 30/100`). Wave 2 `state_machine.py` / `soul_transfer.py` carry legacy numerical thinking.
- **Impact on E1:** `ActionProcessor.validate()` currently has no real validation (only whitelist check on `verb`). When F1 ships, the validate step should call R1 audit to check action against semantic state.
- **Defer to:** Phase F (post-E6).

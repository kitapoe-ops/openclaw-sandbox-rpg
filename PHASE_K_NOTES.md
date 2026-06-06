# Phase K Notes: Pushing Coverage from 89% to 90%

> **Status (as of 2026-06-06, Phase J):** Coverage 89.04%, 354/354 tests pass.
> **Target:** 90% (gap: 0.96 pp = ~80 lines)
> **Estimated effort:** 20-30 min dev work

## What's already covered (Phase J additions)

| File added | Tests | Lines covered | Impact |
|------------|-------|---------------|--------|
| `tests/test_config_settings.py` | 16 | 48 | 0% → 100% on `config.py` |
| `tests/test_llm_client_helpers.py` | 16 | ~40 | 61% → 73% on `llm_client.py` |

Net: 87.77% → 89.04% (+1.27 pp).

## The remaining 0.96 pp gap

Sorted by ease-of-writing (highest ROI first):

| File | Missing | Testability | Suggested approach |
|------|---------|-------------|---------------------|
| `api/action_processor.py` | 47 | Medium — needs mock LLM client + DB fixture | Test the `__init__` branches, the `elapsed_ms` calculation, the simple fallback paths (3-4 new tests) |
| `audit_queue.py` | 44 | High — pure-Python singleton + helper | Test `get_audit_queue()` singleton, `reset_audit_queue()`, and the "different r1_client" warning branch (3-4 new tests in `test_audit_queue_helpers.py`) |
| `state_machine.py` | 39 | High — pure function transitions | Test F1's semantic-state-machine `_apply_mutation` helper and the JSON-parse-fallback paths (4-5 new tests) |
| `soul_transfer.py` | 39 | Medium | Test the dataclass field defaults and the no-op transfer path |
| `ws/multiplayer_router.py` | 39 | Low — would need a real WS server | Skip for now; the file is already in .coveragerc's omit list is wrong (we want it in), but writing meaningful tests requires ASGI test client + WS handshake |

Estimated +50-80 lines covered by adding tests for the first 3 files. That gets us to 90-90.5%.

## Why we stopped at 89% in Phase J

- Each new test file is a 50-200 line PR with its own commit
- 30 min dev time, but coverage 0.96 pp isn't a big project-risk reduction
- Current 89% is **already 2 pp above the original Phase H3 gate** of 85%, which proves the gate has been effective
- Better to land a known-good PR (354/354 pass, 89% above gate) than to push for a round number

## Risk of raising the gate

If Phase K adds tests but the gate moves to 90%, future PRs have a tighter
ceiling. The remaining 9.04% uncovered is concentrated in:
- WebSocket handler code (hard to unit test)
- `main.py` lifespan / DB seeding (requires full app startup)
- `vector_store.py` LanceDB integration (requires external service)
- A few `def _helper` functions deep in narrative modules

So 90% → 95% would require 5-10x the effort that 89% → 90% did.
95% → 100% would be essentially impossible without significant refactoring
(di-based DI for `engine`, mocking LanceDB and the live WebSocket, etc.).

## What to do in Phase K (when the time comes)

1. Add `test_audit_queue_helpers.py` (easiest, 3-4 tests, +30 lines)
2. Add `test_state_machine_helpers.py` (4-5 tests, +25 lines)
3. Add 1-2 tests for `api/action_processor.py` retry/fallback paths
4. Re-run `pytest --cov` and verify 90%
5. Update `.coveragerc` `fail_under = 90`
6. Commit + push + watch CI #56

Estimated 4 commits, 20-30 min.

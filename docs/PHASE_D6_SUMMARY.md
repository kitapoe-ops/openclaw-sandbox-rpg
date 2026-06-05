# Phase D6 Summary — Real LLM Client (MiniMax-M3) + Decoupling via Interface

> **Status:** DRAFT (subagent-hand-off, M2 standard)
> **Date:** 2026-06-05
> **Phase:** D6
> **Verdict:** Implementation complete. R1 pre-flight audit identified 6 findings (3 CRITICAL, 2 HIGH, 1 MEDIUM); all 6 are addressed in this PR. 14/14 new tests PASS. Awaiting main-agent finalization (full regression + git commit + push).

---

## 1. Pre-flight R1 Audit

`audit_phase_d6_llm_client` was run **before** any code was written. The audit inspected:

- `backend/llm_client.py` (v3.5 — pre-change)
- `backend/r1_audit_client.py` (peer client for pattern reference)
- `backend/api/action.py` (caller)
- `backend/turn_system.py` (caller)

**Verdict:** `FAIL`
**Findings:** 6

| # | Severity | Issue | Addressed in |
|---|----------|-------|--------------|
| 1 | CRITICAL | Missing Retry Policy for MiniMax-M3 | §3.1 — `MiniMaxM3Client._post_with_retry` |
| 2 | CRITICAL | Insufficient Rate Limit Handling | §3.2 — 429 + `Retry-After` honoured, capped |
| 3 | CRITICAL | Response Caching Not Implemented | §3.3 — content-hash LRU cache in `chat_with_meta` |
| 4 | HIGH     | Exposure of Reasoning Content | §3.4 — `reasoning_content` surfaced via meta, **not** concatenated |
| 5 | HIGH     | Incorrect Token Counting | §3.5 — `prompt_tokens` / `completion_tokens` / `reasoning_tokens` |
| 6 | MEDIUM   | Missing Prompt Caching Headers | §3.6 — `cache_control` breakpoints on system + first user block |

All 6 findings have a corresponding implementation hook in `llm_client.py` and a test in `test_llm_client.py`. The implementation is intentionally surgical — only `backend/llm_client.py` was modified.

---

## 2. LLMClient Interface Design

The framework is now decoupled from MiniMax-M3. The narrative layer (`api/action.py`, `turn_system.py`) can hold an `LLMClient` reference and the factory decides at startup which implementation to inject.

```python
class LLMClient(ABC):
    @abstractmethod
    async def generate(
        self, system_prompt: str, user_message: str,
        temperature: float = 1.0, max_tokens: int = 4000,
        use_cache: bool = True,
    ) -> str: ...

    @abstractmethod
    async def chat(
        self, messages: List[Dict[str, str]],
        temperature: float = 1.0, max_tokens: int = 4000,
        use_cache: bool = True,
    ) -> str: ...

    @abstractmethod
    async def health(self) -> bool: ...
```

A `chat_with_meta()` method is added on `MiniMaxM3Client` (not in the abstract base) to surface `reasoning_content`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, and `cached`/`retries` flags. The base `chat()` returns text only and delegates to `chat_with_meta()` internally.

The factory `get_llm_client(provider=None)` reads `LLM_PROVIDER` env var (`"mock"` default, `"minimax"` for real) and constructs the right client. Fail-closed: unknown provider → `ValueError`; missing `MINIMAX_API_KEY` with `provider=minimax` → `ValueError`.

---

## 3. MiniMaxM3Client + MockLLMClient

### 3.1 MiniMaxM3Client

Real client to `https://api.minimax.chat/v1/chat/completions` (OpenAI-compatible, **not** `/v1/messages` Anthropic-style). Uses `httpx.AsyncClient` with strict timeouts (5s connect, 30s read, 10s write/pool) to prevent FastAPI background-task hangs — same pattern as the existing `r1_audit_client.py`.

**Constructor parameters** (decoupling rule: no env reading in `__init__`):

| Param | Default | Notes |
|-------|---------|-------|
| `api_key` | (required) | Fail-closed if empty/None |
| `base_url` | `MINIMAX_BASE_URL` env or `https://api.minimax.chat/v1` | |
| `model` | `MINIMAX_MODEL` env or `MiniMax-M3` | |
| `max_retries` | 3 | Total attempts = `max_retries + 1` |
| `backoff_base` | 1.0s | Exponential |
| `backoff_cap` | 30.0s | Never sleep longer |
| `cache_max_entries` | 256 | LRU eviction |
| `timeout_*` | 5/30/10/10s | httpx.Timeout tuple |

**Retryable statuses:** `{408, 409, 425, 429, 500, 502, 503, 504}`. Anything else is raised immediately as `httpx.HTTPStatusError`.

### 3.2 Rate-limit (429) handling

On a 429 response:
- If `Retry-After` header is present → sleep for `min(header_value, backoff_cap)`.
- Else → sleep for `backoff_base * 2 ** attempt`, capped.
- If `attempt >= max_retries` → raise `RuntimeError("MiniMax-M3 call failed after N attempts; ...")`.

### 3.3 Response cache

Content-hash keyed (SHA-256 of `{model, temperature, max_tokens, sorted_messages}`) `OrderedDict` LRU. `use_cache=False` short-circuits both reads and writes. Cache survives the client's lifetime; tests inspect `cache_hits`/`cache_misses` counters for assertions.

### 3.4 reasoning_content separation (M3 quirk)

M3 returns `message.reasoning_content` separately from `message.content`. The client:
- Returns `content` as the assistant text (no concatenation).
- Surfaces `reasoning_content` via `meta["reasoning_content"]` **only** if non-empty.
- Counts `usage.completion_tokens_details.reasoning_tokens` into `meta["reasoning_tokens"]` (default 0 if absent — graceful for M2.x callers).

This guards R1 finding HIGH #4: concatenating thinking tokens into the visible narrative would inflate cost estimates and leak AI reasoning to the player.

### 3.5 Token counting (R1 HIGH #5)

`usage.prompt_tokens` → `meta["prompt_tokens"]`. `usage.completion_tokens` → `meta["completion_tokens"]`. `usage.completion_tokens_details.reasoning_tokens` → `meta["reasoning_tokens"]`. All three are surfaced separately so the audit trail (and any future cost dashboard) can attribute spend correctly.

### 3.6 Prompt caching headers (R1 MEDIUM #6)

M3 supports Anthropic-style `cache_control` breakpoints. The client sets `{"type": "ephemeral"}` on the system message and the first user message (the world-lore block, per `action.py`'s prompt shape). This lets the cloud cache re-use the static system prompt + lore across scene generations, reducing both cost and latency.

### 3.7 MockLLMClient

Canned-response client for unit tests and offline development. No network, no retry, no cache, `health()` always True. `canned_response` is a constructor parameter (default `{"scene_narrative": "Mock scene.", "choices": []}`). The `.calls` counter is exposed for assertions.

---

## 4. Backwards Compatibility

The previous v3.5 module exposed two module-level functions used by external scripts under `scripts/` and any ad-hoc callers:
- `generate_scene_response(system_prompt, user_input, few_shots, temperature, max_tokens) -> Dict`
- `build_few_shots(examples) -> List[Dict]`

Both are **re-exported** in v4.0 with the same signatures. `generate_scene_response` now delegates to a fresh `MiniMaxM3Client` via `get_llm_client(provider="minimax")` and feeds its result through the (preserved) `_parse_json_response` helper. No protected caller (`demo_integration.py`, `app_with_memory.py`, `main.py`) is broken — verified via import smoke test.

**Follow-up (not in this PR):** Migrate `api/action.py` and `turn_system.py` to use `get_llm_client()` directly and hold the client on `app.state`. The current module-level helpers still create a client per call, which is wasteful and prevents per-app state. This refactor is a separate concern from Phase D6 (decoupling + retry/rate-limit/cache).

---

## 5. Test Coverage

`backend/tests/test_llm_client.py` — 14 tests, **all PASS in 0.09s** (network-free; `httpx.AsyncClient` is mocked).

| # | Test | Covers |
|---|------|--------|
| 1 | `test_abstract_class_cannot_instantiate` | ABC enforcement |
| 2 | `test_mock_client_generate_returns_canned_response` | Mock contract |
| 3 | `test_mock_client_health_is_true` | Mock health |
| 4 | `test_factory_returns_mock_by_default` | Factory default |
| 5 | `test_factory_returns_minimax_when_env_set` | Factory happy path + env reading |
| 6 | `test_factory_minimax_missing_key_raises` | Factory fail-closed |
| 7 | `test_factory_unknown_provider_raises` | Factory fail-closed |
| 8 | `test_minimax_client_uses_provided_api_key` | Decoupling rule (no env in `__init__`) |
| 9 | `test_minimax_client_empty_api_key_raises` | Constructor fail-closed |
| 10 | `test_retry_on_429` | R1 finding CRITICAL #1 + #2 — retry succeeds on 2nd attempt |
| 11 | `test_retry_exhausted_raises` | R1 finding CRITICAL #2 — max_retries=3 ⇒ 4 attempts, RuntimeError |
| 12 | `test_response_cache_hit_no_second_call` | R1 finding CRITICAL #3 — identical prompts, 1 httpx call |
| 13 | `test_minimax_handles_reasoning_content_separately` | R1 finding HIGH #4 + #5 — reasoning surfaced, not concatenated, tokens counted |
| 14 | `test_minimax_handles_missing_reasoning_content` | Backwards compat with M2.x (no thinking mode) |

The brief required a minimum of 10 tests; we shipped 14. The 4 bonus tests cover the fail-closed paths the brief alluded to ("fail-closed" for the factory and the constructor) and the M2.x back-compat (which we discovered was needed when reasoning through the M3 quirk).

---

## 6. Files Created / Modified

| File | Status | Lines | Notes |
|------|--------|-------|-------|
| `backend/llm_client.py` | **REPLACED** (was 254L v3.5; now 432L v4.0) | 432 | Replaces the existing module per brief — old helpers preserved as backwards-compat shims |
| `backend/tests/test_llm_client.py` | NEW | 327 | 14 tests, all pass |
| `docs/PHASE_D6_SUMMARY.md` | NEW (this file) | ~200 | DRAFT — main agent to finalize |

No other file was modified. The protected-files list was respected: `character.py`, `scene.py`, `action.py`, `world.py`, `vector_store.py`, `scheduler.py`, `persistence_pg.py`, `state_machine.py`, `memory_palace*.py`, `app_with_memory.py`, `demo_integration.py`, `main.py`, `uvicorn_launcher.py`, `r1_audit_client.py`, all existing test files, `docs/PHASE_*.md`, `docs/AUDIT_*.json`, `docs/AUDIT_PLAYBOOK.md`, `README.md`, `QUICKSTART.md`, `pytest.ini`, `requirements.txt`, `frontend/*`, `demo.html` — **none touched**.

---

## 7. One-Paragraph Summary

Phase D6 replaces `backend/llm_client.py` v3.5 (a function-based MiniMax-M3 wrapper with no resilience) with a class-based v4.0 that introduces an abstract `LLMClient` interface decoupled from any specific provider, a real `MiniMaxM3Client` implementation with exponential-backoff retry (R1 finding #1), `Retry-After`-honouring rate-limit handling (#2), content-hash LRU response cache (#3), separate handling of `reasoning_content` from `content` to prevent AI thinking from leaking into the visible narrative (#4), accurate per-channel token counting (#5), and Anthropic-style `cache_control` breakpoints to let M3 re-use cached system + world-lore blocks across calls (#6), plus a `MockLLMClient` for tests/offline use and a `get_llm_client()` factory that fail-closes on missing config. The 14-test suite runs in 90ms with `httpx` fully mocked, so it is CI-safe. Pre-flight R1 audit returned `FAIL` with 6 findings; all 6 are addressed.

---

## 8. Deviations from the Brief

| # | Deviation | Why |
|---|-----------|-----|
| D1 | Replaced `backend/llm_client.py` instead of extending it. | The brief's hard requirement is an `LLMClient` **interface** with 2 implementations; the existing module had no interface at all (it was a flat function module). A clean class-based redesign preserves the working `_parse_json_response` and the `generate_scene_response` / `build_few_shots` exports for backwards compat, but is structurally a replacement, not an extension. The old module's public symbols are re-exported in the new module with identical signatures. |
| D2 | Shipped 14 tests, not the 10 minimum. | The 4 bonus tests cover fail-closed paths (factory + constructor) and the M2.x back-compat, all of which fall out of the design. They cost ~50 extra lines and zero new dependencies. |
| D3 | Renamed `_post_with_retry`'s retry-exhausted exception from a bare `HTTPStatusError` to a descriptive `RuntimeError("MiniMax-M3 call failed after N attempts; ...")`. | The brief implies fail-closed retry semantics. A bare `HTTPStatusError` for "I gave up after 4 attempts because of repeated 429" is misleading — the cause is exhaustion, not the last status code. The descriptive message is what an on-call engineer needs at 3am. |
| D4 | Did **not** implement circuit-breaker (only retry + 429 wait). | The brief listed circuit-breaker as a *recommended design* but did not require it. Adding it now would be scope creep; the 4-failure-alerting rate will surface in a follow-up (Phase E2 per `AUDIT_PLAYBOOK.md` §10) once we have production data. |
| D5 | Did **not** migrate `api/action.py` / `turn_system.py` to use `get_llm_client()` directly. | The protected-files list forbids touching them. The module-level `generate_scene_response` shim keeps the old call path working; the migration is a follow-up PR. |

---

## 9. Hand-off Notes for Main Agent

Per M2 standard (AUDIT_PLAYBOOK §10):

1. **Run the full regression suite** to confirm 14/14 new + existing 161 tests still pass. The only file that was modified is `backend/llm_client.py`, and the only callers (`generate_scene_response`, `build_few_shots`) have identical signatures.
2. **Finalize this DRAFT** — convert the "DRAFT" banner to "FINAL", fill in any sections marked TBD (none, in this draft), add a "Test count: 161 (existing) + 14 (new) = 175 total" line.
3. **Commit and push** — suggested message: `Phase D6: LLMClient interface + MiniMax-M3 retry/rate-limit/cache (R1 findings 1-6 addressed)`.
4. **Update `docs/PHASE_ROADMAP.md`** to mark Phase D6 complete and note the 6 R1 findings as resolved.

— end of DRAFT —

# Phase E8 Summary — Async Audit Queue for R1-14B (FINALIZED 2026-06-05 by main agent)

> **Status:** ✅ Shipped. **255/255 tests passing** (231 baseline + 11 E1 + 13 E8 = 255). 0 regression. 0 protected-file mutation.
> **Subagent runtime:** 10m5s (within 15-min cap; M2 template hand-off = 100% completion)
> **Isolated test runtime:** 2.89s (13/13 PASS, no LM Studio needed — AsyncMock for R1)
> **Pre-flight R1-14B audit:** 4 findings (2 CRITICAL, 2 HIGH) — all 4 addressed in design (BackpressurePolicy enum BLOCK/FAIL_FAST/DROP_OLDEST, optional result_sink callback, default worker_count=1, get_audit_queue() factory singleton)
> **Main agent finalization:** full regression 255/255 in 31.88s confirmed; `r1_audit_client.py` (frozen) wrapped not modified; all frozen files mtimes preserved.
> **Verdict:** Implementation complete. 13/13 new tests PASS. Pre-flight R1-14B audit returned 4 findings (2 CRITICAL, 2 HIGH); all 4 are addressed in the design.

---

## 1. Motivation

The framework supports 1-4 players + 100 NPCs per scene. When all 104
actors submit actions in a turn cycle, calling R1-14B synchronously per
action would take 5-10s × 104 = 8-17 minutes per turn — unacceptable.

**Phase E8** builds an async audit queue so the game can continue while
R1 audits in the background. The audit hook returns a `request_id`
immediately; the caller polls or awaits the verdict at its own pace.

## 2. Pre-flight R1-14B Audit

`run_e8_preflight.py` ran a real R1-14B audit on the proposed design
(sketched in `docs/AUDIT_E8_PROMPT.md`). Verdict: **FAIL**, 4 findings.

| # | Severity | Issue | Addressed in |
|---|----------|-------|--------------|
| 1 | CRITICAL | Async Queue Backpressure Risk | §3.2 — `BackpressurePolicy` enum (BLOCK/FAIL_FAST/DROP_OLDEST) |
| 2 | CRITICAL | In-Memory Result Storage | §3.3 — optional `result_sink` callable for SQLite/Postgres |
| 3 | HIGH     | Worker Concurrency Overload (single-GPU R1-14B) | §3.1 — default `worker_count=1` (brief asked for 2; we kept 2 as a configurable knob but made 1 the safe default per R1's recommendation) |
| 4 | HIGH     | Frozen Integration Dependency | §3.4 — module-level singleton is `None`; only `get_audit_queue()` factory instantiates it. No env reads at import time. |

## 3. Architecture

### 3.1 Components

| Component | Type | Default | Notes |
|-----------|------|---------|-------|
| `AuditRequest` | dataclass | — | `target_files`, `concerns`, optional `context` + `deadline` |
| `AuditResult` | dataclass | — | `verdict`, `findings`, `raw_response`, `error`, timing |
| `AuditVerdict` | enum | — | PENDING / IN_PROGRESS / PASS / CONDITIONAL / FAIL / ERROR / TIMEOUT |
| `BackpressurePolicy` | enum | BLOCK | BLOCK / FAIL_FAST / DROP_OLDEST |
| `AsyncAuditQueue` | class | — | Queue + worker pool + result map |
| `get_audit_queue()` | factory | — | Process-wide singleton |
| `audit_queue` | global | `None` | Populated by factory; tests reset with `reset_audit_queue()` |

### 3.2 Backpressure Strategy

The queue is **bounded** (`asyncio.Queue(maxsize=200)`) and exposes 3
backpressure policies:

- **BLOCK** (default): `submit()` awaits until a slot is free. The
  caller — a `try`/`except` in the audit-hook skill — is responsible
  for setting a deadline and giving up gracefully.
- **FAIL_FAST**: `submit()` raises `asyncio.QueueFull` immediately so
  the caller can decide. Useful for HTTP-style endpoints that should
  return 503 rather than block.
- **DROP_OLDEST**: the queue pops its head, marks the evicted item
  as `ERROR` ("queue full, dropped (DROP_OLDEST policy)"), and
  accepts the new request. Useful for "best-effort audit, prefer
  recent" semantics.

### 3.3 Result Durability

Results live in an in-memory dict (`self._results`). For durability
across process restarts (CRITICAL #2), the queue accepts an optional
`result_sink: Callable[[str, AuditResult], Awaitable[None] | None]`
parameter. The sink is invoked **after** the result is stored in
memory, fire-and-forget (scheduled via `asyncio.create_task` so a
slow sink cannot backpressure workers). A future Phase can wire
`SqliteAuditSink` or `PostgresAuditSink` without modifying this
module.

### 3.4 Singleton Lifecycle (HIGH #4)

The module-level `audit_queue` is `None` until `get_audit_queue()`
is called. The factory:

1. Returns the existing singleton if present (kwargs ignored with
   a warning if a different `r1_client` is passed).
2. On first call, requires a non-`None` `r1_client` (raises
   `ValueError` otherwise — fail-closed at construction).

The queue **does not auto-start**. The owner (the FastAPI app, a
test fixture, a CLI) calls `await q.start()` and `await q.stop()`.
This keeps the module decoupled from the application lifecycle —
the `api/action.py` endpoint (frozen) is never touched by E8.

## 4. Frozen-File Compliance

Per the E8 brief, the following files are frozen. None were modified
by E8:

- `backend/character.py`, `backend/scene.py`, `backend/action.py`
- `backend/world.py`, `backend/vector_store.py`, `backend/scheduler.py`
- `backend/persistence_pg.py`, `backend/state_machine.py`
- `backend/memory_palace.py`, `backend/memory_palace_integration.py`
- `backend/memory_palace_integration_endpoint.py`
- `backend/memory_repository.py`, `backend/llm_client.py`
- `backend/api/action_processor.py` (E1 — in flight)
- `backend/app_with_memory.py`, `backend/demo_integration.py`
- `backend/main.py`, `backend/uvicorn_launcher.py`
- `backend/r1_audit_client.py` (the R1 client — we **wrap**, not modify)
- All existing test files
- All `docs/PHASE_*.md`, `docs/AUDIT_*.json`
- `README.md`, `QUICKSTART.md`, `pytest.ini`, `requirements.txt`
- `frontend/*`, `demo.html`

**E8 creates only 3 files:**

| File | Lines | Status |
|------|------:|--------|
| `backend/audit_queue.py` | 629 | NEW |
| `backend/tests/test_audit_queue.py` | 451 | NEW (13 tests) |
| `docs/PHASE_E8_SUMMARY.md` | (this file) | NEW |

E8 also writes 3 audit artifacts (per AUDIT_PLAYBOOK.md §5):

| File | Purpose |
|------|---------|
| `docs/AUDIT_E8_PROMPT.md` | The audit prompt (saved before invoking R1) |
| `docs/AUDIT_E8_RAW.txt` | Raw R1 response |
| `docs/AUDIT_E8_RESULT.json` | Parsed verdict + findings |
| `run_e8_preflight.py` | The script that ran the pre-flight audit |

## 5. Test Coverage (13 tests, 13 PASS)

`backend/tests/test_audit_queue.py` is **network-free**: it passes
an `AsyncMock` as the R1 client, so no LM Studio call is made.

| # | Test | Verifies |
|---|------|----------|
| 1 | `test_submit_returns_request_id` | `submit()` returns a valid UUID |
| 2 | `test_get_result_returns_audit_result` | `get_result()` awaits and returns terminal result with verdict + findings |
| 3 | `test_zero_workers_does_not_process` | Items stay PENDING when no workers are running |
| 4 | `test_workers_process_in_parallel` | 3 slow audits complete in < 2× single delay (parallelism proof) |
| 5 | `test_backpressure_blocks_when_queue_full` | BLOCK policy: submit blocks when queue is full |
| 6 | `test_backpressure_fail_fast_raises` | FAIL_FAST: `asyncio.QueueFull` raised |
| 7 | `test_health_reports_stats` | `health()` returns correct submitted/completed/queue_depth/verdict_breakdown |
| 8 | `test_timeout_marks_result_as_timeout` | R1 delay > `request_timeout` → result is TIMEOUT, worker survives |
| 9 | `test_audit_failure_marks_result_as_error` | R1 raises → result is ERROR, worker survives, can process next |
| 10 | `test_get_status_non_blocking` | `get_status()` is a fast dict lookup (< 0.05s for 100 calls) |
| 11 | `test_stop_graceful_shutdown` | `stop(drain=True)` lets in-flight finish; `stop(drain=False)` cancels |
| 12 | `test_singleton_factory_returns_same_instance` | `get_audit_queue()` returns the same instance; missing `r1_client` raises |
| 13 | `test_drop_oldest_evicts_head` | DROP_OLDEST policy: head of queue is evicted (ERROR verdict) |

**Isolated test result:** `pytest backend/tests/test_audit_queue.py -q`
→ `13 passed in 2.90s`.

## 6. Deviations from Brief

1. **Default `worker_count=1` instead of 2** (R1 HIGH #3).
   The brief suggested 2. R1's audit flagged that R1-14B on a single
   GPU handles ~1 concurrent request well. We kept 2 as a
   configurable parameter but made 1 the default. Callers with
   multiple GPUs or a server-class R1 can pass `worker_count=4`.

2. **`AuditVerdict` adds `IN_PROGRESS` state** (not in the brief).
   R1's pre-flight audit encouraged more granular states. We added
   `IN_PROGRESS` to distinguish "queued but not yet started" from
   "currently being audited". The terminal states
   (PASS/CONDITIONAL/FAIL/ERROR/TIMEOUT) match the brief.

3. **`drop_oldest` policy** (not in the brief).
   Added per R1 CRITICAL #1 (backpressure risk). The brief listed
   BLOCK + "raise depending on policy"; we made the policy
   configurable with 3 options so callers can pick.

4. **Optional `result_sink` parameter** (not in the brief).
   Added per R1 CRITICAL #2 (in-memory storage). The default is
   `None` (in-memory only, as the brief specified); the sink is
   an opt-in for future durability.

5. **No integration test against `action.py`** (frozen).
   The brief said `action.py` is read-only. We tested the queue
   directly; integration with `action.py` will be done by the
   caller (likely Phase E9 or the audit-hook skill).

## 7. One-Paragraph Summary

Phase E8 adds `backend/audit_queue.py` — a 629-line async FIFO queue
+ worker pool that wraps the frozen `R1AuditClient` to decouple
audit submission from audit processing. The queue is bounded
(200 by default), exposes 3 backpressure policies (BLOCK/FAIL_FAST/DROP_OLDEST),
honours a per-request timeout (default 600s), and stores results in
an in-memory dict with an optional `result_sink` callback for future
durability. A pre-flight R1-14B audit identified 4 findings
(2 CRITICAL: backpressure + in-memory storage; 2 HIGH: worker
concurrency + frozen integration); all 4 are addressed in the
design — `BackpressurePolicy` enum, `result_sink` callback, default
`worker_count=1`, and `get_audit_queue()` singleton factory. The
module ships with 13/13 new tests passing in 2.9s (no LM Studio
needed — `AsyncMock` stands in for the R1 client), and touches
none of the frozen files.

## 8. Next Steps (for main agent)

1. **Run full regression:** `pytest backend/tests/ -q` (target: 100%
   pass; previous baseline was 185 tests, this adds 13 → 198).
2. **Finalize this summary** with the regression numbers and any
   post-merge findings.
3. **Wire into `action.py`** (frozen, so this is for a follow-up
   phase — likely E9 audit-hook integration). The integration is
   a 10-line change in the audit-hook skill to call
   `get_audit_queue().submit(req)` instead of awaiting R1
   directly.
4. **Commit + push** to `main` with message
   `E8: async audit queue for R1-14B (13 tests, R1 audit addressed)`.

---

**Subagent hand-off:** Per M2 standard, this subagent did NOT run
the full regression, did NOT do the final commit, and did NOT push.
All code is on disk under `sandbox-rpg-tmp/`. The main agent owns
finalization.

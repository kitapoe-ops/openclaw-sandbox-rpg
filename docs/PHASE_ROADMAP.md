# Phase Roadmap

> Last updated: 2026-06-08
> Current state: **381/382 tests passing (1 skipped), Phase L2 shipped, Phase F1-F4 shipped**

---

## Shipped Phases

### Pre-Wave 1 — Core Engine Foundation
- **Status:** Shipped (commits before `5328c92`)
- **Scope:** Character / Scene / Action / World core modules, state machine, world lore YAML loader
- **Test count:** 36 (tier 1 logic baseline)
- **Description:** Synchronous in-memory RPG engine with rule-based state transitions and YAML-driven canon

### Wave 2 — Audit + Async Turn + World API
- **Status:** Shipped (commits `5328c92` → `53929bf`)
- **Scope:**
  - R1-14B audit client (LM Studio local, fail-closed)
  - Async Turn System with Soul Transfer
  - World API endpoints (lore query, world state)
  - 3D payload + anti-suicide degradation
  - Real R1 audit client (replacing earlier M3 mock)
- **Test count:** 36 → 117 (+81 tests)
- **Description:** Brought the framework from "in-memory toy" to "production-grade async engine with local LLM verification"

### Memory Palace Design Spec
- **Status:** Shipped (`docs/WAVE2_MEMORY_PALACE.md`, 728 lines)
- **Scope:** Full 3-phase rollout design for the AI's long-term memory subsystem
- **Description:** Schema, 5 backends, API surface, integration architecture, risks, 3-phase rollout. Source of truth for Phase B and C2 implementation.

### Phase B — Core Infrastructure
- **Status:** Shipped (commit `204749c`)
- **Scope:** Three independent modules, all with async APIs, all with aiosqlite / pure-Python fallback for tests
  - **B1** — `backend/vector_store.py` (471L) — LanceDB primary + pure-Python fallback
  - **B2** — `backend/scheduler.py` (281L) — APScheduler v3 AsyncIOScheduler with 3 cron jobs
  - **B3** — `backend/persistence_pg.py` (343L) — SQLAlchemy 2.0 async Postgres adapter
- **Test count:** 117 → 135 (+18 tests)
- **Description:** Built the three foundational modules that the Memory Palace integration depends on. Each one ships with a fallback path so the test environment needs no external services.

### Phase C1 — Polish Pass
- **Status:** Shipped (commit `204749c`)
- **Scope:**
  - Added `apscheduler>=3.10,<4.0` to `requirements.txt` (B2 subagent installed it manually, but it was missing from the file)
  - Replaced 5 callsites of `datetime.utcnow()` with `datetime.now(timezone.utc)` in `state_machine.py` (Python 3.12+ ready)
  - Added FK violation test + aiosqlite `PRAGMA foreign_keys=ON` fixture in `test_persistence_pg.py`
- **Test count:** 135 → 136 (+1 test)
- **Description:** Low-risk cleanup. Zero regression. Cleared all 16 `datetime.utcnow` deprecation warnings.

### Phase C2 — Memory Palace Phase A Integration
- **Status:** Shipped (commit `204749c`)
- **Scope:**
  - `backend/memory_palace_integration.py` (552L) — composes `PostgresPersistence` + `VectorStore` into unified per-character API
  - `backend/memory_palace_integration_endpoint.py` (284L) — FastAPI router (4 endpoints)
  - Class named `MemoryPalaceIntegration` (NOT `MemoryPalace`) to avoid clobbering the pre-existing 841L `memory_palace.py` and its 30 tests
- **Test count:** 136 → 154 (+18 tests: 12 unit + 6 endpoint)
- **Description:** The two memory_palace modules now coexist: the original SQLite-only Phase A and the new Postgres+Vector integration. Caller picks per use case.

### Phase C3 — Wire-up + Demo
- **Status:** Shipped (commit `204749c`)
- **Scope:**
  - `backend/app_with_memory.py` (115L) — `main.py` import + `include_router` (zero main.py modification)
  - `backend/demo_integration.py` (333L) — `memory_health_minute` cron + `GET /demo/info`
  - End-to-end chain verified: scheduler → ASGI → integration → Postgres + Vector
- **Test count:** 154 → 161 (+7 tests at time of ship; current suite: 381 passed)
- **Description:** 4 new routes wired into the live app. 23 total endpoints (18 gameplay + 4 `/memory/*` + 1 `/demo/info`). `main.py` mtime preserved across the entire Phase C work.

---

## Planned Phases

### Phase D1 — Merge two memory_palace modules
- **Effort:** ~45 min
- **Scope:** Decide between (a) keep both modules, caller picks per use case, or (b) consolidate into one module with two classes (requires migrating 30 existing tests)
- **Why now:** Technical debt cleanup. Currently both `memory_palace.py` (841L) and `memory_palace_integration.py` (552L) are maintained in parallel.
- **Risk:** Low. Both modules ship with their own test suites.

### Phase D2 — Clean 2 pre-existing warnings
- **Effort:** ~15 min
- **Scope:**
  - `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated` — wait for FastAPI upgrade
  - `RuntimeWarning: coroutine '_test_db_connection.<locals>.check' was never awaited` in `demo_mode.py:59` — fix by awaiting the coroutine
- **Why now:** Clean up the only 2 warnings remaining in the test output. Then the suite runs truly silent.
- **Risk:** Trivial.

### Phase D3 — Memory Palace Phase B + C
- **Effort:** ~2 hr
- **Scope:** Per the design doc's 3-phase rollout:
  - **Phase B:** Repository pattern (abstract `MemoryRepository` interface, so the caller can swap SQLite/Postgres without changing business logic)
  - **Phase C:** Real embedding model integration (replace the 384-dim stub with sentence-transformers loading + a small embedding cache layer)
- **Why now:** Phase A integration is shipped; the design doc was always 3 phases. The repository pattern is the natural prerequisite for the planned Redis cache.
- **Risk:** Medium. Real embedding model loading will need a model file (~90MB) and proper async handling.

### Phase D4 — Frontend demo.html full E2E
- **Effort:** ~1.5 hr
- **Scope:** Wire the static `demo.html` to the live backend (currently it loads scenes from a local file, not the API). Add WebSocket connection for real-time scene updates.
- **Why now:** The backend has 23 endpoints, the frontend doesn't use any of them. Close the loop.
- **Risk:** Low. Mostly frontend JS work.

### Phase D5 — ~~Docker deploy to Pi5~~ **REMOVED 2026-06-05**
- **Status:** ~~Planned~~ Cancelled by user decision. Do not revive.
- **Reason:** Pi5 (8GB RAM, no GPU) cannot host R1-14B (~9GB VRAM) + embedding model (~200MB) + FastAPI + Postgres + APScheduler. The framework is local-developer-only; production deploy is out of scope.
- **Action:** Never re-introduce this phase. Audit function `audit_phase_d5_pi5_deploy` is now deprecated — keep the code (not deleted, for historical reference) but do not invoke it.

### Phase D6 — Real LLM client to MiniMax-M3 cloud
- **Effort:** ~1 hr
- **Scope:** Replace the mock LLM client with a real call to the MiniMax-M3 cloud API (1M context). Add retry logic, rate limiting, response caching.
- **Why now:** Phase A through C all assumed a mock LLM. Real LLM integration will reveal prompt engineering requirements and latency budgets.
- **Risk:** Medium. MiniMax-M3 is the agent's own runtime — the framework shouldn't be tightly coupled to it. Use an LLM client interface (already exists in `backend/llm_client.py`).

---

## Long-Term Vision

The framework's north star is **persistent AI-driven narrative**. By Phase D6, a player should be able to:

1. Spin up the backend locally (venv)
2. Open `demo.html` in a browser
3. Spend 50 turns exploring a YAML-defined world
4. Close the laptop, return two weeks later
5. The blacksmith still remembers the iron sword conversation
6. The soul transfer system handles character death gracefully
7. R1-14B has caught every hallucination along the way

The Memory Palace is the keystone. Everything else (state machine, physics lock, audit hook) exists to make the Memory Palace trustworthy enough to persist across sessions.

**Deployment scope: LOCAL-ONLY.** The framework is designed for local development (single-machine venv + LM Studio for R1-14B). Production / Pi5 / cloud deploy is explicitly out of scope — see removed Phase D5.

**Game scope (1-4 players + 100 NPCs, set 2026-06-05):**

- **Players:** 1-4 concurrent human players per scene
- **NPCs:** Up to 100 per scene, all with full character parameters + Memory Palace support
- **Per-NPC overhead:** 384-dim embedding (~200KB) + state machine state (~5KB) + Memory Palace memories (variable, ~1MB/100 memories)
- **Total scene budget:** 100 NPCs × 1.2MB ≈ 120MB RAM, plus 4 players × ~50MB ≈ 200MB — well under 8GB local dev host
- **Turn system:** Per-character queue with DB row lock already designed for this scale (see `backend/turn_system.py` line 4: "multi-player RPG")
- **Audit scale:** R1-14B must audit 100 NPC + 4 player turns = ~104 actions/turn cycle. Target: 200-500ms R1 latency budget per action; total ~50s/turn cycle worst case. May need async audit queue (Phase D3+)

**Scope hard caps (do not exceed without explicit user approval):**
- Player count > 4: REJECT (UI/UX not designed for 5+; turn queue contention)
- NPC count > 100: REJECT (Memory Palace index size; R1 audit throughput)
- Local-only deploy: REJECT cloud/Pi5 (see removed Phase D5)

Beyond Phase D, the next major axis is **multiplayer polish** — the infrastructure supports it, but the UX (shared scenes, real-time WebSocket fan-out, NPC dialogue arbitration) is a Phase E+ scope.

---

## Phase F Candidates (State Model Refactor)

> **User explicit decision 2026-06-05:** State MUST be pure-text semantic (`"患了感冒"`, `"右手骨折"`), NOT numerical (`hp: 30/100`). Wave 2 implementations of `state_machine.py` / `soul_transfer.py` carry **legacy numerical thinking** that must be refactored.

### Phase F1 — Pure-text state contract
- **Scope:** Define `SemanticState` type (str or list[str] of tag-like strings), add validation, replace numerical fields
- **Files:** `backend/state_machine.py` (frozen, must reopen), `backend/api/state_models.py` (NEW)
- **Est:** ~2 hr
- **Risk:** 🔴 HIGH — reopens frozen file, may break 19+ existing tests

### Phase F2 — Semantic soul transfer
- **Scope:** Replace `random.uniform(0.6, 0.9)` numerical degradation with `TierListMapping` (e.g. "健康" → "虚弱" → "瀕死") OR LLM-driven semantic downgrade
- **Files:** `backend/soul_transfer.py` (frozen)
- **Est:** ~1.5 hr
- **Risk:** 🔴 HIGH — anti-exploit semantics change

### Phase F3 — LLM state_mutations contract
- **Scope:** Add `state_mutations: list[StateChange]` to LLM JSON schema; LLM must return `{target, add_state, remove_state}` for every action
- **Files:** `backend/llm_client.py` (frozen), `backend/api/action_processor.py` (frozen)
- **Est:** ~1.5 hr
- **Risk:** 🔴 HIGH — breaks MockLLMClient contract, ~14 tests need updating

### Phase F4 — Prompt builder with top-of-prompt current state
- **Scope:** New `backend/prompt_builder.py` that prepends current semantic state to system prompt, regardless of Memory Palace retrieval
- **Files:** `backend/prompt_builder.py` (NEW), `backend/api/action_processor.py` (frozen)
- **Est:** ~1 hr
- **Risk:** 🟡 MED — additive change, less likely to break existing tests

### Phase F ordering
1. F1 first (foundation — define the type)
2. F2 next (soul transfer needs F1's type)
3. F3 next (LLM contract change)
4. F4 last (uses everything)

**Total F estimate:** ~6 hr active coding + ~1 hr full regression + ~1 hr re-audit.

> **Status (2026-06-05):** Tech debt **documented** but **NOT** to be addressed before Phase E6 completes. The user explicitly chose to ship E6 (multiplayer connection layer) first; state model refactor is a Phase F+ scope.
> **Why this ordering:** E6a/b/c are decoupled from the state model — they ship the WebSocket fan-out, scene state, and frontend, none of which depend on how player/NPC state is represented. Refactoring state_model.py now would block multiplayer scope delivery without benefit.

---

## Phase G Candidates (Post-Phase-F Reality Check, 2026-06-05)

> **User explicit decision 2026-06-05:** After Phase F 100% completion, the user identified 3 architectural blind spots that contract-layer testing cannot catch. Two are **permanently SKIPPED** (per user); one is **documented for next session**.

### Phase G1 — Ghost State Retry (LLM self-correction on dropped mutations)
- **Scope:** When Pydantic validation drops a `StateMutation` (e.g. MiniMax-M3 produces a tag > 15 chars), the narrative still flows but state diverges from narrative ("ghost state"). Add a retry-with-feedback mechanism: if a mutation is dropped, the next LLM call receives a `previous_attempt_errors` field listing what went wrong, asking the LLM to re-emit a valid mutation.
- **Files:** `backend/llm_client.py` (just unfrozen by F3), `backend/api/action_processor.py` (just unfrozen by F3)
- **Est:** ~1.5 hr
- **Risk:** 🟡 MED — may cause latency regression (2x LLM calls per action), may confuse LLM with feedback
- **Status:** **Documented, NOT YET BUILT** (Phase F just shipped 2026-06-05 22:33)

### Phase G2 — Real Docker E2E (BAZOOKA + asyncpg + LanceDB) **PERMANENTLY SKIPPED 2026-06-05**
- **Why:** BAZOOKA is local-only dev host with no Docker. asyncpg / LanceDB are production-only. Framework scope is local venv + LM Studio.
- **Replacement:** Phase E1.5a (single-thread real-DB E2E with aiosqlite + pure-Python VectorStore fallback) is the strongest production-path validation we'll get in this scope.
- **Do not revive.**

### Phase G3 — Context Pruning (Selective memory recall + token budget) **PERMANENTLY SKIPPED 2026-06-05**
- **Why:** RX 6800 16GB VRAM + R1-14B Q4_K_M ~9GB. Real concurrent audit throughput unknown. User explicitly skipped this — framework is local-only, not production-scale.
- **Replacement:** Phase E8 async audit queue (backpressure policies BLOCK/FAIL_FAST/DROP_OLDEST) is the strongest concurrency-throttling we'll get.
- **Do not revive.**

### Phase F completion summary
- **F1-Audit** (15 semantic invariants) ✅
- **F1-wide** (pure-text state refactor) ✅
- **F2** (semantic soul transfer) ✅
- **F3** (LLM state_mutations contract + wiring) ✅
- **F4** (prompt builder with top-of-prompt current state) ✅
- **Net test delta:** 296 → 322 (+26 淨 at F-ship time; current suite: 381 passed)
- **M2 subagent cumulative:** 17/17 within 15-min cap, 0 disk work lost
- **Frozen files mutated beyond scope:** ZERO (only F1/F2/F3 unfroze their respective files)

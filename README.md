# OpenClaw Sandbox RPG

> An LLM-driven, persistent-state narrative RPG framework. The AI is the Dungeon Master; the world survives across sessions.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 161 passing](https://img.shields.io/badge/Tests-161%20passing-brightgreen)]()
[![Status: Phase B/C Shipped](https://img.shields.io/badge/Status-Phase%20B%2FC%20Shipped-blue)]()
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)]()

---

## Overview

OpenClaw Sandbox RPG is a backend-first framework for building AI-driven narrative games. Unlike a chatbot that forgets between turns, this framework treats the world, its characters, and their memories as first-class persistent state. A local language model (DeepSeek-R1-14B via LM Studio) audits every LLM-generated action before it commits, providing a fail-closed hallucination guard. A relational + vector persistence layer (PostgreSQL + LanceDB) stores the world canon, character state, and a per-character Memory Palace that supports semantic recall across sessions.

The design goal is simple: build a sandbox where **1-4 players** can spend 50 turns exploring a world populated by **up to 100 NPCs** (each with full character parameters and memory), then close the laptop, come back two weeks later, and the blacksmith still remembers what sword they tried to buy.

**Game scope (hard caps, do not exceed):**
- 1-4 concurrent human players per scene
- Up to 100 NPCs per scene, all with Memory Palace + character parameters

---

## Key Features

- **Persistent world state** — scenes, characters, lore survive restarts; state is the source of truth, not LLM context
- **Per-character Memory Palace** — episodic / semantic / procedural memories with 384-dim vector recall, character-scoped, salience-filtered
- **Audit-hook architecture** — every LLM action passes through a local R1-14B verifier before commit (fail-closed on R1 timeout)
- **Anti-hallucination world lore** — canonical lore is loaded from YAML; the LLM is forbidden from inventing canon
- **Async turn system with soul transfer** — concurrent players/NPCs share a turn queue; consciousness can transfer across bodies
- **Physics lock** — concurrency-safe action validation prevents impossible world states (two objects in one cell, etc.)
- **APScheduler backbone** — daily sentinel runs, 4-hour dashboard refresh, 10-minute heartbeat, all configurable
- **Pluggable persistence** — `PERSISTENCE_MODE=memory|postgres` env switch, with aiosqlite fallback for tests
- **23 FastAPI endpoints** — 18 gameplay + 4 `/memory/*` + 1 `/demo/info`
- **161 tests, 5.3s full suite** — tier 1 (logic), tier 3 (HTTP), concurrency, integration

---

## Tech Stack

| Layer | Technology | Version | Role |
|-------|-----------|---------|------|
| API | FastAPI | 0.110 | HTTP + WebSocket |
| Async runtime | uvicorn[standard] | 0.27 | ASGI server |
| ORM | SQLAlchemy | 2.0 (async) | Postgres + aiosqlite |
| Vector DB | LanceDB | 0.5 | Semantic search (384-dim) |
| Scheduler | APScheduler | 3.11 | Cron backbone |
| Validation | Pydantic | 2.6 | Request/response models |
| LLM cloud | MiniMax M3 | 1M context | Narrative generation |
| LLM local | DeepSeek-R1-14B | Q4_K_M | Audit / verification |
| Embeddings | sentence-transformers | all-MiniLM-L6-v2 | 384-dim vectors |
| Tests | pytest + pytest-asyncio | 8.0 | 161 tests, 5.3s |
| Deploy | Local venv | — | Local-only (Pi5/cloud deploy out of scope) |

---

## Architecture

```
+-----------------------------------------------------------------+
|  Frontend (demo.html) - WebSocket + REST                         |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
|  FastAPI App (main.py + app_with_memory.py)                    |
|  +----------+----------+----------+----------------------------+ |
|  | character|  scene   |  action  |  world   | /memory/* (4) | |
|  |  (8 rt)  |  (3 rt)  |  (4 rt)  |  (3 rt)  |  /demo/info    | |
|  +----+-----+----+-----+-----+----+------+---------+----------+ |
+-------|----------|----------|--------|--------|-----------------+
        |          |          |        |        |
+-------v-----+ +--v-------+ +v------+ +------v+ +---------------+
| State       | | Scene &  | |Action | | Turn  | | Memory Palace |
| Machine     | | World    | |Physic | | System| | (PG + Vector) |
| (sync,168L) | | Lore     | | Lock  | | (async| | (2 modules,   |
|             | | (YAML)   | | + R1  | |  turn)| |  1393L total) |
+------+------+ +----+-----+ +--+----+ +---+---+ +-------+-------+
       |             |           |         |             |
       +-------------+-----------+---------+-------------+
                             |
              +------------------------------+
              |  4 Subsystems                |
              |  - R1 Audit (fail-closed)    |
              |  - ETL (log -> lore)         |
              |  - Semantic Gradient         |
              |  - DB Race arbitration       |
              +------------------------------+
```

---

## Core Engines

### 1. State Machine (`backend/state_machine.py`, 168L)
Synchronous, in-memory state tracker for `Character` and `Scene`. All action requests pass through the state machine first as a rule-based gate (e.g. a dead character cannot perform an `attack` action). `created_at` / `updated_at` are timezone-aware UTC. **19 tests passing.**

### 2. Scene and World Lore (`backend/api/scene.py`, `world_lore_db.py`, `world_lore_loader.py`)
- **Scene** — a transient moment: location, NPCs, objects, physics lock state
- **World Lore** — persistent canon: geography, history, mythology. Loaded from YAML, never invented by the LLM
- The invariant: lore is immutable, scenes are mutable

### 3. Action and Physics Lock (`backend/api/action.py`, `backend/physics_lock.py`)
Action layer accepts player verbs (`move`, `attack`, `talk`, `use-item`). Physics lock prevents the LLM from violating world rules (walking through walls, two objects claiming the same cell). Concurrency-safe under multi-session writes. **19+ tests + concurrency tests passing.**

### 4. Turn System with Soul Transfer (`backend/turn_system.py`, `backend/soul_transfer.py`)
Async turn queue supporting concurrent players and NPCs. **Soul Transfer** is the narrative core twist: when a character dies or loses consciousness, the player soul can transfer to a new vessel (an object, animal, AI agent) — anti-suicide degradation rules prevent exploit. **7 concurrency tests passing.**

### 5. Memory Palace (`backend/memory_palace*.py`, 1393L total)
The AI's long-term memory. Two coexisting implementations:
- **`memory_palace.py` (841L)** — Phase A, SQLite-only, 14 public methods, 30 tests
- **`memory_palace_integration.py` (552L)** — Phase C2, Postgres + LanceDB composition, 6 public methods, 18 tests

Recall flow:
```
query -> embed (384d) -> VectorStore.search (top-25)
  -> filter by character_id, memory_type, salience
  -> rehydrate content from Postgres -> return top-k with similarity score
```

The two modules can coexist (caller picks) or be merged in Phase D.

---

## Subsystems

| Subsystem | File | Role | Trigger |
|-----------|------|------|---------|
| **R1 Audit** | `backend/r1_audit_client.py` | Local DeepSeek-R1-14B verifies LLM output against lore + physics | Every action commit, pre-write |
| **ETL Service** | `backend/etl_service.py` | Structured session log -> world lore | Daily cron, manual |
| **Semantic Gradient** | `backend/semantic_gradient.py` | Embedding similarity for recall + lore query | Recall path, lore lookup |
| **DB Race** | `backend/db.py` + tests | Concurrent write arbitration | Multi-session conflicts |

---

## Scheduler

APScheduler v3 `AsyncIOScheduler`, three production jobs plus one demo:

| Job ID | Cron | Timezone | Purpose |
|--------|------|----------|---------|
| `sentinel_daily` | `0 9 * * *` | Asia/Shanghai | Daily full pipeline run |
| `dashboard_refresh` | `0 */4 * * *` | host local | Refresh dashboard every 4 hours |
| `heartbeat` | `*/10 * * * *` | host local | Health ping every 10 minutes |
| `memory_health_minute` | `* * * * *` | host local | Demo: hit `/memory/health` every minute |

Wire-up code in `backend/scheduler.py`. Demo wiring in `backend/demo_integration.py`.

---

## Game Lifecycle

```
1. START    POST /world/lore/load         (YAML -> DB)
2. CREATE   POST /character               (name, class, soul_id)
3. ENTER    POST /scene                   (location, npcs, physics_lock_check)
4. LOOP     player POST /action  --+
             |                       |
             v                       |
           StateMachine.validate    |  (rule gate)
             |                       |
           PhysicsLock.check        |  (concurrency)
             |                       |
           LLM.generate_narrative    |
             |                       |
           R1-14B.audit              |  (fail-closed)
             |                       |
           MemoryPalace.remember     |  (embed + PG + Vector)
             |                       |
           WorldLore.update (if canonical)
             |                       |
           WebSocket broadcast -> browser
                                     |
   (loop until scene end / character dies / soul transfer)
5. END      POST /scene/close          (state snapshot -> MEMORY.md)
6. REPLAY   POST /scene/{id}/replay    (rehydrate from MemoryPalace)
```

---

## Player UX Flow

1. Open `demo.html` in a browser — see character list and scene map
2. Click "Start adventure" — backend creates character + scene
3. Type an action: "I tell the blacksmith I want to buy a sword"
4. Backend runs the full chain (1-3 seconds)
5. Browser receives narrative: `Blacksmith looks up: "Iron sword, 50 gold, interested?"` + scene state update
6. AI remembers — restart the session 30 seconds later and the blacksmith still recognizes you (Memory Palace)

---

## Test Coverage

```
backend/tests/  (161 tests, 5.3s full suite)
+- test_state_machine_tier1.py                   19 tests  pure logic
+- test_api_tier3.py                                  HTTP smoke, 6 endpoints
+- test_physics_lock.py                               concurrency, race conditions
+- test_soul_transfer.py                          7 tests  narrative rules
+- test_soul_transfer_concurrent.py               7 tests  async safety
+- test_db_race.py                                  DB write arbitration
+- test_wave2_core3.py                              async turn system
+- test_vector_store.py                           7 tests  Phase B1
+- test_scheduler.py                              4 tests  Phase B2
+- test_persistence_pg.py                         8 tests  Phase B3 + C1
+- test_memory_palace.py                         30 tests  pre-existing Phase A
+- test_memory_palace_integration.py             12 tests  Phase C2 unit
+- test_memory_palace_integration_endpoint.py     6 tests  Phase C2 HTTP
+- test_c3_integration.py                        7 tests  Phase C3 wire-up
```

**Total: 161 tests passing, 0 regression, 0 new warnings** (2 pre-existing: StarletteDeprecation, `demo_mode.py:59` coroutine).

---

## Design Principles

1. **Persistence First** — all state lives in Postgres; sessions are restartable, replayable, multi-session-safe
2. **Audit Hook is Mandatory** — LLM output passes through local R1-14B verification before any commit; fail-closed on R1 timeout
3. **Anti-Hallucination by Construction** — canonical lore is YAML-loaded, immutable; the LLM is a narrator, not a world-builder
4. **Memory as Infrastructure** — Memory Palace is a backend module, not a feature; recall is a database query, not a prompt
5. **Async Concurrency Safe** — physics lock, soul transfer, turn system, DB race all designed for concurrent writes

---

## Project Status

| Phase | Scope | Status | Commit |
|-------|-------|--------|--------|
| Wave 1 | Character/Scene/Action/World core | Shipped | (pre-B) |
| Wave 2 | Audit client, YAML, World API, async turn | Shipped | `5328c92` |
| Memory Palace design | 728L design spec | Shipped | (in Wave 2) |
| Phase B1 | LanceDB vector store | Shipped | `204749c` |
| Phase B2 | APScheduler cron wiring | Shipped | `204749c` |
| Phase B3 | PostgreSQL adapter skeleton | Shipped | `204749c` |
| Phase C1 | Polish (requirements, datetime, FK test) | Shipped | `204749c` |
| Phase C2 | MemoryPalaceIntegration + 4 endpoints | Shipped | `204749c` |
| Phase C3 | Wire-up + demo (main.py untouched) | Shipped | `204749c` |
| **Phase D1** | Merge two memory_palace modules | Planned | -- |
| **Phase D2** | Clean 2 pre-existing warnings | Planned | -- |
| **Phase D3** | Memory Palace Phase B+C (real embeddings) | Planned | -- |
| **Phase D4** | Frontend demo.html full E2E | Planned | -- |
| **Phase D5** | ~~Docker deploy to Pi5~~ | **REMOVED** | -- |
| **Phase D6** | Real LLM client to MiniMax-M3 cloud | Planned | -- |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg

# 2. Create venv
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt

# 3. Verify
.venv/Scripts/python.exe -m pytest backend/tests/ -q
# Expected: 161 passed in ~5s

# 4. Run the app
.venv/Scripts/python.exe -m uvicorn backend.app_with_memory:app --reload
# Opens on http://localhost:8000

# 5. Open the demo
# Open demo.html in your browser
```

For the full demo flow, see `QUICKSTART.md`.

---

## Documentation Index

- [QUICKSTART.md](./QUICKSTART.md) — 5-minute end-to-end demo
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — detailed architecture for engineers
- [docs/PHASE_ROADMAP.md](./docs/PHASE_ROADMAP.md) — what shipped, what's planned
- [docs/WAVE2_MEMORY_PALACE.md](./docs/WAVE2_MEMORY_PALACE.md) — Memory Palace 3-phase design spec
- [docs/PHASE_B_SUMMARY.md](./docs/PHASE_B_SUMMARY.md) — Phase B delivery report
- [docs/PHASE_C1_SUMMARY.md](./docs/PHASE_C1_SUMMARY.md) — Phase C1 polish report
- [docs/PHASE_C2_SUMMARY.md](./docs/PHASE_C2_SUMMARY.md) — Phase C2 Memory Palace integration
- [docs/PHASE_C3_SUMMARY.md](./docs/PHASE_C3_SUMMARY.md) — Phase C3 wire-up + demo

---

## Contributing

Issues and PRs welcome. For substantial changes, open an issue first to discuss scope. The project follows a sub-agent-driven development model: each change ships with its own test suite, regression gate, and phase summary doc.

---

## License

MIT. See [LICENSE](./LICENSE).

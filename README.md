# OpenClaw Sandbox RPG

> An LLM-driven, persistent-state narrative RPG framework. The AI is the Dungeon Master; the world survives across sessions.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: 313 passing](https://img.shields.io/badge/Tests-313%20passing-brightgreen)]()
[![Status: Phase L2 Shipped](https://img.shields.io/badge/Status-Phase%20L2%20Shipped-blue)]()
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)]()


---

## Overview

OpenClaw Sandbox RPG is a backend-first framework for building AI-driven narrative games. Unlike a chatbot that forgets between turns, this framework treats the world, its characters, and their memories as first-class persistent state. A local language model (DeepSeek-R1-14B via LM Studio) audits every LLM-generated action before it commits, providing a fail-closed hallucination guard. A relational + vector persistence layer (PostgreSQL + LanceDB) stores the world canon, character state, and a per-character Memory Palace that supports semantic recall across sessions.

The design goal is simple: build a sandbox where **1-4 players** can spend 50 turns exploring a world populated by **up to 100 NPCs** (each with full character parameters and memory), then close the laptop, come back two weeks later, and the blacksmith still remembers what sword they tried to buy.

**Game scope (hard caps, do not exceed):**
- 1-4 concurrent human players per scene
- Up to 100 NPCs per scene, all with Memory Palace + character parameters

---

## Narrative & Karma Loop (故事與業力閉環)

核心概念（網文套路、寫作鐵律、異步足跡、奪舍機制）全部串連起嚟，整個故事引擎嘅「閉環（Closed Loop）」其實係一個**「行為 → 改變 → 傳承 → 新行為」**嘅永動機。撇除所有技術細節，呢個閉環嘅完整運作畫面係咁樣嘅：

### 🔄 故事生成與奪舍閉環

**【起點】：帶着「業力」降生**
新玩家（或者剛剛死完重開嘅玩家）進入世界。佢嘅角色唔係一張白紙，系統會強行將**上一手玩家留低嘅「業力」或者「執念」**注入佢嘅背景設定。
*(例如：作為一個新兵，你無端端對酒館北面嗰口廢棄水井產生極度恐懼，因為上一手玩家啱啱死喺嗰度。)*

⬇️

**【推動】：導演佈局（套路與痕跡的碰撞）**
系統（導演）開始做嘢，佢會將兩樣材料放入榨汁機：
1. **網文套路庫：** 抽出一張劇本大綱（例如：【禍水東引】）。
2. **世界真實痕跡：** 撈取其他非同步玩家啱啱做過嘅「好事」（例如：玩家 A 殺咗個商人，留低把斷劍）。
系統將兩者結合，交低一個核心指令：**「今集劇本係『禍水東引』，道具係『斷劍』，即刻開拍！」**

⬇️

**【渲染】：極限施壓與抉擇（LLM 畫師發功）**
LLM 收到指令，並嚴格遵守「禁用情緒詞」、「倒數計時器」、「微觀視角」三大寫作鐵律，渲染出一個充滿張力嘅場景：
*(「門外傳來急促的鐵甲碰撞聲。你腳邊躺着商人尚有餘溫的屍體，旁邊是一把不屬於你的斷劍。火把的光芒正從門縫底下一寸寸逼近。」)*
緊接著，逼出 4 個帶有**代價與風險**的網文選項（隱忍、反殺、嫁禍、逃遁）。

⬇️

**【刻印】：無聲改寫世界**
玩家從 4 個選項中作出抉擇並採取行動。玩家睇唔到嘅背後，系統嘅「守門人」會將呢個行動翻譯成冷冰冰嘅「世界參數改變」。
*(例如：商人狀態 = 已死；房間 = 滿地鮮血；守衛狀態 = 敵對。)*

⬇️

**【分流】：生與死的終極判定**
呢度係閉環最關鍵嘅分水嶺：
- **👉 情況 A（玩家存活）：** 玩家嘅行動製造咗新嘅「痕跡」，角色帶住新嘅道具同狀態，重新跌入**【推動】**階段，繼續抽下一個套路，進入下一 Round。
- **👉 情況 B（玩家死亡，觸發奪舍）：** 玩家因為選錯被守衛斬死。Game Over？唔係。玩家角色嘅死亡，正式成為呢個世界嘅「歷史事件」。佢死前嘅恐懼、仇恨，會被系統提取成新嘅「業力」。系統隨即創造一個全新角色（例如一個路過嘅拾荒者），將呢股「業力」塞入佢腦海，然後將佢掉返去**【起點】**。

### 💡 點解呢個叫「真正嘅閉環」？

因為喺呢套系統入面，**沒有任何一次遊玩是孤立的，也沒有任何一次死亡是浪費的。**
1. **世界參數閉環：** 你今日劈爛嘅一張檯，會成為聽日另一個玩家（甚至係你自己新角色）用嚟做掩護嘅爛木板。
2. **敘事邏輯閉環：** M3 唔需要無中生有去「諗」故事，佢只係負責將「玩家 A 嘅破壞」+「網文套路」包裝成「玩家 B 嘅危機」。
3. **生死輪迴閉環（奪舍）：** 死亡不再是終點（Ending），而係產生下一個故事動機（Motivation）嘅原料。

這就是整個 OpenClaw Sandbox RPG 的靈魂：**一個由無數玩家的屍體、痕跡和執念所驅動的無限故事機器。**

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
- **313 tests, 8.1s full suite** — tier 1 (logic), tier 3 (HTTP), concurrency, integration, multiplayer, state machine


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
| Deploy | Cloudflared + PG | — | Hosted production stack (kitahim.uk) |


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

1. Open `http://localhost:8000` (or `localhost:5173` in dev) in a browser — see Vue 3 Premium UI
2. Click "開始冒險" — backend creates character + scene (or offline sandbox handles state)
3. Type an action: "I tell the blacksmith I want to buy a sword"
4. Backend runs the full chain (1-3 seconds)
5. Browser receives narrative: `Blacksmith looks up: "Iron sword, 50 gold, interested?"` + scene state update
6. AI remembers — restart the session 30 seconds later and the blacksmith still recognizes you (Memory Palace)

---

## Test Coverage

backend/tests/  (313 tests, 8.1s full suite)
+- test_state_machine_tier1.py                   19 tests  pure logic
+- test_state_machine_semantic.py                34 tests  semantic state machines
+- test_api_tier3.py                              14 tests  HTTP smoke, world registry
+- test_physics_lock.py                          5 tests   concurrency, race conditions
+- test_soul_transfer.py                          7 tests   narrative rules
+- test_soul_transfer_concurrent.py               7 tests   async safety
+- test_db_race.py                                5 tests   DB write arbitration
+- test_wave2_core3.py                            16 tests  async turn system
+- test_vector_store.py                           7 tests   Phase B1
+- test_scheduler.py                              4 tests   Phase B2
+- test_persistence_pg.py                         8 tests   Phase B3 + C1
+- test_memory_palace.py                         30 tests  pre-existing Phase A
+- test_memory_palace_integration.py             12 tests  Phase C2 unit
+- test_memory_palace_integration_endpoint.py     6 tests   Phase C2 HTTP
+- test_c3_integration.py                        7 tests   Phase C3 wire-up
+- test_multiplayer_router.py                     12 tests  Phase E6a multiplayer routing
+- test_scene_multiplayer.py                      21 tests  Phase E6b scene state
+- test_world_expansion.py                        2 tests   large-world verification
+- test_production_smoke.py                       8 tests   production sanity check
+```

**Total: 313 tests passing (excluding smoke tests when Postgres is off), 0 regression**


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
| Phase B/C/D | Memory Palace, Postgres, Permissive CORS | Shipped | `204749c` |
| Phase E/F | Multiplayer, WebSocket fan-out, F3 contract | Shipped | `9a91bee` |
| Phase L2 | Production stack, Cloudflare tunnel, Vue SPA | Shipped | `1b284f0` |
| UI Refactor | Premium UI, Glassmorphism, HSL theme, LED indicators | Shipped | `Current` |


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
# To run unit tests excluding Postgres smoke tests in development:
.venv/Scripts/python.exe -m pytest backend/tests/ -k "not test_production_smoke"
# Expected: 313 passed in ~8s

# 4. Run the backend (demo mode)
DEMO_MODE=true .venv/Scripts/python.exe -m uvicorn backend.main:app --reload
# Opens API docs on http://localhost:8000/docs

# 5. Run the frontend (development mode)
cd frontend
npm install
npm run dev
# Opens SPA interface on http://localhost:5173
```

For the production hosted deployment steps, see `deploy/` directory and `L2_E_deploy.ps1`.


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

# Architecture

> Version 0.1.0 | Last updated: 2026-06-05
> Audience: engineers contributing to the framework

---

## 1. System Overview

OpenClaw Sandbox RPG is a backend-first framework for AI-driven narrative games. It is organized around five independent core engines, four shared subsystems, and a single FastAPI app that exposes them all as REST + WebSocket endpoints. The design constraint throughout is: **persistent state is the source of truth, the LLM is a renderer of state, not the other way around**.

### 🔄 故事生成與奪舍閉環 (The Narrative & Karma Loop)

整個故事引擎的核心閉環（Closed Loop）其實是一個**「行為 → 改變 → 傳承 → 新行為」**的永動機。其完整運作畫面如下：

1. **【起點】：帶着「業力」降生**
   新玩家（或剛死亡重開的玩家）進入世界時，其角色並非白紙。系統會將**上一手玩家留下的「業力」或「執念」**注入新角色的背景設定。
   *(例如：作為一個新兵，你無端端對酒館北面的廢棄水井產生極度恐懼，因為上一手玩家剛在此處死亡。)*

2. **【推動】：導演佈局（套路與痕跡的碰撞）**
   系統（導演）會將兩樣材料結合：
   - **網文套路庫：** 抽取劇本大綱（例如：【禍水東引】）。
   - **世界真實痕跡：** 撈取其他非同步玩家做過的「好事」（例如：玩家 A 殺了商人並留下斷劍）。
   系統結合兩者發送指令：**「本集劇本為『禍水東引』，道具為『斷劍』，即刻開拍！」**

3. **【渲染】：極限施壓與抉擇（LLM 畫師發功）**
   LLM 嚴格遵守「禁用情緒詞」、「倒數計時器」、「微觀視角」三大寫作鐵律，渲染出張力場景，並提供 4 個帶有**代價與風險**的網文選項（隱忍、反殺、嫁禍、逃遁）。

4. **【刻印】：無聲改寫世界**
   玩家作出抉擇與行動。系統的「守門人」將此行動轉化為「世界參數改變」（例如：商人狀態 = 已死；房間 = 滿地鮮血；守衛狀態 = 敵對）。

5. **【分流】：生與死的終極判定**
   - **👉 情況 A（玩家存活）：** 玩家行動製造新「痕跡」，角色攜帶新道具與狀態，重回**【推動】**階段，抽取下一個套路，進入下一輪。
   - **👉 情況 B（玩家死亡，觸發奪舍）：** 玩家角色死亡成為世界的「歷史事件」。其死亡前的恐懼、仇恨被提取為新「業力」。系統創建全新角色（例如拾荒者），將業力注入其腦海並送回**【起點】**。

#### 💡 點解呢個叫「真正嘅閉環」？
- **世界參數閉環：** 你今日劈爛的桌子，會成為明日另一個玩家（甚至你自己的新角色）用來做掩護的爛木板。
- **敘事邏輯閉環：** 故事生成不需要無中生有，它只負責將「玩家 A 的破壞」+「網文套路」包裝成「玩家 B 的危機」。
- **生死輪迴閉環（奪舍）：** 死亡不再是終點，而是產生下一個故事動機的原料。

---

## 2. Three-Layer Architecture

```
+-----------------------------------------------------------------+
|  Layer 1: Frontend                                               |
|    demo.html (static SPA) -> WebSocket + REST to Layer 2         |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
|  Layer 2: FastAPI App                                           |
|    main.py  +  app_with_memory.py  (zero main.py modification)  |
|    Routes:                                                      |
|      character (8)  scene (3)  action (4)  world (3)           |
|      /memory/* (4)   /demo/info (1)                            |
+----------------------------+------------------------------------+
                             |
+----------------------------v------------------------------------+
|  Layer 3: Core Engines + Subsystems                            |
|                                                                  |
|    [Core Engines]                       [Subsystems]            |
|    1. State Machine                     - R1 Audit (fail-close) |
|    2. Scene + World Lore                - ETL (log -> lore)     |
|    3. Action + Physics Lock             - Semantic Gradient     |
|    4. Turn System (Async + Soul)        - DB Race arbitration   |
|    5. Memory Palace (PG + Vector)                                |
+-----------------------------------------------------------------+
```

---

## 3. Engine Deep-Dives

### 3.1 State Machine
- **File:** `backend/state_machine.py` (168L)
- **Mode:** Synchronous, in-memory
- **Key methods:** `transition(state, event)`, `add_status_tag`, `remove_status_tag`
- **Test count:** 19 (tier 1 logic)
- **Design rationale:** State transitions are the cheapest possible gate. By the time we call the LLM, we have already ruled out obviously-invalid actions. The state machine also owns the timestamp fields (`created_at`, `updated_at`) which are timezone-aware UTC since Phase C1.

### 3.2 Scene and World Lore
- **Files:** `backend/api/scene.py`, `backend/world_lore_db.py`, `backend/world_lore_loader.py`
- **Mode:** Mixed — scene is mutable runtime state, lore is immutable YAML-loaded
- **YAML source:** `worlds/dnd_5e_forgotten_realms.yaml` (D&D 5e SRD)
- **Test count:** Covered by tier 3 HTTP smoke + the world API tests
- **Design rationale:** The LLM must never invent canon. Anything the LLM says about a location, an NPC, or a historical event must come from the lore database. If the lore database doesn't have an answer, the LLM must say "I don't know" rather than confabulate. This is enforced by a two-layer check: the prompt is constrained, and R1-14B audits the output.

### 3.3 Action and Physics Lock
- **Files:** `backend/api/action.py`, `backend/physics_lock.py`
- **Mode:** Async, concurrency-safe
- **Key methods:** `ActionProcessor.process()`, `PhysicsLock.check(state_before, proposed_state)`
- **Test count:** 19+ (logic + concurrency)
- **Concurrency model:** `asyncio.Lock` per scene. Each scene has a single physics lock; multiple actions against the same scene are serialized. Actions against different scenes run in parallel.
- **Audit hook integration:** Every action that survives the physics lock is sent to R1-14B for verification before commit. R1-14B is queried with: (1) the action, (2) the world lore, (3) the scene state. R1 returns `pass` / `fail` with reasoning. Fail-closed: if R1 times out (10s), the action is rejected.

### 3.4 Turn System with Soul Transfer
- **Files:** `backend/turn_system.py`, `backend/soul_transfer.py`
- **Mode:** Async queue
- **Key methods:** `TurnQueue.enqueue()`, `SoulTransfer.transfer(soul_id, new_vessel)`
- **Test count:** 7 (concurrency) + 7 (soul transfer)
- **Soul transfer rules (anti-exploit):**
  - A soul can only transfer to a vessel in the same scene
  - A soul cannot transfer to a vessel that already has an active soul
  - Transfer takes one full turn (no instant transfer exploit)
  - If the new vessel dies within 3 turns, the soul is destroyed (no infinite suicide-and-revive loop)
- **Design rationale:** The soul is the player. The vessel is a body. This is the narrative twist that makes the framework more than a chat bot — the player has identity that persists across containers.

### 3.5 Memory Palace
- **Files:**
  - `backend/memory_palace.py` (841L, Phase A, SQLite-only)
  - `backend/memory_palace_integration.py` (552L, Phase C2, Postgres + Vector)
- **Mode:** Async, persistent
- **Embedding model:** sentence-transformers/all-MiniLM-L6-v2 (384-dim)
- **Storage:** LanceDB for vectors, Postgres (or SQLite) for structured payload
- **Test count:** 30 (Phase A) + 12 unit + 6 endpoint (Phase C2) = 48
- **Two-module coexistence:** The integration module was forced to use a different name (`MemoryPalaceIntegration`) to avoid clobbering the pre-existing 841L module. Phase D1 will decide whether to merge or keep both.

#### 3.5.1 Embedding Pipeline
```
content (str) -> sentence-transformers encode -> [384 floats]
                                              |
                                              v
                                   VectorStore.add(memory_id, embedding, metadata)
                                              |
                                              v
                                   Postgres.save(memory_id, content, metadata)
```

#### 3.5.2 Recall Pipeline
```
query (str) -> encode -> query_embedding
                          |
                          v
              VectorStore.search(query_embedding, k=25)  # over-fetch
                          |
                          v
              filter: metadata.character_id == target
              filter: memory_type in (episodic, semantic, procedural)
              filter: salience >= threshold
                          |
                          v
              truncate to top-k
                          |
                          v
              for each: Postgres.load(memory_id) -> rehydrate content
                          |
                          v
              return [{memory_id, content, similarity, memory_type, salience, metadata}]
```

The over-fetch (k=25 vs returned k=5) is deliberate. Vector similarity is cheap; rehydration is the bottleneck. We want to surface the best 5 from a wider pool, not be limited by the initial k.

---

## 4. Subsystem Integration

```
+------------+      +-----------------+      +----------------+
| Player     | ---> | FastAPI Action  | ---> | State Machine  |
| (action)   |      | Endpoint        |      | (rule gate)    |
+------------+      +--------+--------+      +----------------+
                              |
                              v
                     +----------------+
                     | Physics Lock   |
                     | (concurrency)  |
                     +--------+-------+
                              |
                              v
                     +----------------+      +----------------+
                     | LLM Narrator   | ---> | R1-14B Audit   |
                     | (mock / cloud) |      | (fail-closed)  |
                     +--------+-------+      +--------+-------+
                              |                        |
                              v                        v
                     +----------------+      +----------------+
                     | Memory Palace  | <--> | World Lore DB  |
                     | (PG + Vector)  |      | (YAML loaded)  |
                     +----------------+      +----------------+
```

R1-14B audit is a **sidecar**, not in the critical path of the loop diagram above, but it sits between the LLM output and any commit. Fail-closed semantics: if R1 returns `fail` or times out, the action is rejected, the scene state is not updated, the player is told "the action could not be resolved."

ETL Service is invoked by the daily cron (`sentinel_daily`, 09:00 SGT). It walks the session log, extracts structured events (NPC interactions, quest completions, scene transitions), and proposes lore updates. Lore updates go through the same R1 audit path before commit.

---

## 5. Scheduler Wiring

```python
# backend/scheduler.py (excerpt)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        job_sentinel_daily,
        CronTrigger(hour=9, minute=0, timezone="Asia/Shanghai"),
        id="sentinel_daily",
    )
    scheduler.add_job(
        job_dashboard_refresh,
        CronTrigger.from_crontab("0 */4 * * *"),
        id="dashboard_refresh",
    )
    scheduler.add_job(
        job_heartbeat,
        CronTrigger.from_crontab("*/10 * * * *"),
        id="heartbeat",
    )
    return scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = build_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()
```

`main.py` is the actual entry point for the production stack. It configures the main `FastAPI` instance, serves the Vue 3 SPA frontend, and handles the lifespan. `app_with_memory.py` acts as a compatibility testing shim, registering testing routers (`_e1_router`, `_d4_list_router`, `_e6a_router`, and `_e6b_router`) directly onto the `main.app` instance, and importing `app` at the end of the file to break circular imports.


---

## 6. Lifecycle Sequence

```
Player        Frontend      FastAPI       StateMach     PhysicsLk     LLM        R1-Audit    MemoryPalace
  |              |             |              |             |          |            |              |
  |--click------>|             |              |             |          |            |              |
  |              |--POST------>|             |             |          |            |              |
  |              |  /action    |              |             |          |            |              |
  |              |             |--validate--->|             |          |            |              |
  |              |             |  (rule gate) |             |          |            |              |
  |              |             |<-ok----------|             |          |            |              |
  |              |             |--check-------------------->|          |            |              |
  |              |             |  (concurrency)             |          |            |              |
  |              |             |<-ok------------------------|          |            |              |
  |              |             |--generate---------------------------->|            |              |
  |              |             |  (narrative)                         |            |              |
  |              |             |<-text--------------------------------|            |              |
  |              |             |--audit------------------------------------------->|              |
  |              |             |  (lore + physics check)                            |              |
  |              |             |<-pass----------------------------------------------|              |
  |              |             |--remember------------------------------------------------------->|
  |              |             |  (embed + PG + Vector)                                          |
  |              |             |<-ok----------------------------------------------------------------|
  |              |             |--WS broadcast--->|             |          |            |              |
  |              |<-scene_upd--|                 |             |          |            |              |
  |<render-------|             |                 |             |          |            |              |
```

The full round-trip is typically 1-3 seconds (dominated by the LLM call). R1 audit adds ~200-500ms when running on local GPU. The Memory Palace `remember` adds ~50ms (embed + 2 DB writes).

---

## 7. OpenClaw Workspace Context

This project lives at `~/.openclaw/workspace/sandbox-rpg-tmp/`. The parent OpenClaw workspace contains 12+ skills:

| Skill | Relevance |
|-------|-----------|
| `migm` (港股估值) | Anti-hallucination rules informed the audit client design |
| `mtool` (translation) | Phase 0-4 pipeline inspired ETL service structure |
| `autoresearch` | Multi-source search pattern applies to lore enrichment |
| `audit-hook` | DeepSeek-R1-14B local verifier — same model used by the audit client |
| `scanbot` | HK stock scanner — unrelated to RPG, but shares persistence patterns |
| `bear` | HSI bear CBBC — financial skills, not relevant to game |

The framework is **independent** of OpenClaw at the binary level (own git repo, own venv, own tests) but borrows design patterns from the parent workspace's skills.

---

## 8. Extension Points

A new contributor could add features at any of these seams:

1. **New memory type** — extend the `memory_type` enum in `memory_palace_integration.py` (currently `episodic | semantic | procedural`). Add a filter, add a rehydration strategy, ship a test. ~30 min.

2. **New cron job** — add a new function + `scheduler.add_job(...)` in `backend/scheduler.py`. The `build_scheduler()` factory is the only thing that needs to know. ~10 min.

3. **New world lore source** — implement a loader for a new YAML schema or a remote source (e.g. a wiki API). The interface is `WorldLoreLoader.load(source_path) -> dict`. ~1 hr.

4. **New LLM provider** — implement the `LLMClient` interface. The framework currently has a mock; swap in MiniMax-M3 cloud, GPT-4, or any local model. ~1 hr.

5. **New endpoint under `/memory/*`** — add a route in `memory_palace_integration_endpoint.py`. The router is already mounted; just add the function and a test. ~15 min.

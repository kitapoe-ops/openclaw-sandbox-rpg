# Phase B 完工報告

> **完成時間：** 2026-06-05
> **狀態：** ✅ All 3 sub-modules shipped, 135/135 tests pass, zero regression

---

## 📦 交付清單

| # | 模塊 | 主文件 (lines) | 測試文件 (lines) | 測試結果 |
|---|------|---------------|-----------------|---------|
| **B1** | LanceDB Vector Store | `backend/vector_store.py` (471) | `backend/tests/test_vector_store.py` (187) | **7/7 PASS** ✅ |
| **B2** | APScheduler Cron | `backend/scheduler.py` (281) | `backend/tests/test_scheduler.py` (130) | **4/4 PASS** ✅ |
| **B3** | PostgreSQL Adapter | `backend/persistence_pg.py` (343) | `backend/tests/test_persistence_pg.py` (153) | **7/7 PASS** ✅ |
| | **總計** | **3 個 module, 1095 lines** | **3 個 test file, 470 lines** | **18/18 新 PASS** |

**全套 regression：** `python -m pytest backend/tests/` → **135 passed in 4.92s** ✅

---

## 🧩 B1 — Vector Store (`backend/vector_store.py`)

**用途：** Memory Palace 嘅 vector search 後端（A/B/C migration seam）

**設計重點：**
- LanceDB primary path（lazy-init，upsert 用 delete+add，cosine 由 stored vectors 即時重計）
- Pure-Python fallback（in-memory dict，math module cosine，**zero dependency** — 唔靠 numpy/LanceDB）
- `EMBEDDING_DIM = 384` 常數 export
- 5 個 public methods 全部 `async def`，sync backend 用 `asyncio.to_thread` 包裹
- `_detect_lancedb` 同 `__init__` 解耦 — native build fail 唔會拖冇 Memory Palace

**Deviation Note：**
- 471 lines vs target 200-300（多咗完整 docstring + 兩條 path 完整實作）
- Fallback 唔用 numpy（test env 冇裝，math module 完全夠用）
- LanceDB code path 已實作但未用 test exercise（env 冇裝）— production `pip install lancedb` 即啟用

---

## ⏰ B2 — Scheduler (`backend/scheduler.py`)

**用途：** Cron backbone — dashboard refresh / sentinel / heartbeat

**3 個 jobs：**
- `sentinel_daily` — 09:00 Asia/Shanghai daily
- `dashboard_refresh` — 每 4 小時（cron `0 */4 * * *`）
- `heartbeat` — 每 10 分鐘（cron `*/10 * * * *`）

**設計重點：**
- `apscheduler==3.11.2` v3.x（**非 v4** — v4 API 唔穩定）
- `AsyncIOScheduler`（非 BackgroundScheduler）
- `build_scheduler()` + `create_app_with_scheduler()` factory — **唔改 `main.py`**
- 獨立 module-level `app` for `uvicorn backend.scheduler:app`
- 自動 import-or-skip guard — apscheduler 缺失時 test 唔會 fail

**Bug Caught（subagent 主動抓）：**
1. `Job.next_run_time` 在 scheduler 未 running 時會 raise — `/health` 已 guard
2. `AsyncIOScheduler.shutdown(wait=...)` defer via `call_soon_threadsafe` — lifespan 改用 `BaseScheduler.shutdown` 同步 shutdown，確保 `state` 即時 flip 到 `STATE_STOPPED`

**Missing Dependency：** `apscheduler` 唔喺 `backend/requirements.txt` — 後續 ship prod 之前要加 `apscheduler>=3.10,<4.0`

---

## 🗄️ B3 — PostgreSQL Adapter (`backend/persistence_pg.py`)

**用途：** 取代 in-memory state嘅 SQLAlchemy 2.0 async persistence layer

**Schema：**
- `characters` table：`id` (PK), `payload` (JSON), `created_at`, `updated_at`
- `scenes` table：`id` (PK), `character_id` (FK indexed), `payload` (JSON), `created_at`

**設計重點：**
- SQLAlchemy 2.0 async API（`AsyncSession` / `async_sessionmaker` / `create_async_engine`）
- **Test 用 aiosqlite** — 唔需要 live postgres / asyncpg
- Env switch `PERSISTENCE_MODE`：`"postgres"` / `"memory"`（default）
- 7 個 public methods 全部 `async def`
- `health()` + `close()` 完整 lifecycle
- FK violation 觸發 IntegrityError（被 test 7 捕獲）

**Key Methods：**
```python
class PostgresPersistence:
    async def save_character(character_id, payload)
    async def load_character(character_id) -> dict | None
    async def delete_character(character_id)
    async def save_scene(scene_id, character_id, payload)
    async def load_scene(scene_id) -> dict | None
    async def health() -> bool
    async def close()
```

---

## ✅ 已遵守嘅 Hard Constraints

| Constraint | 狀態 |
|-----------|------|
| ❌ 唔改 `main.py` / `uvicorn_launcher.py` | ✅ Verified by grep |
| ❌ 唔改 Wave 2 shipped files（character/scene/action/world.py） | ✅ 唔存在於本 repo |
| ❌ 唔改 `docs/WAVE2_MEMORY_PALACE.md` | ✅ mtime 確認 ~11h 無變 |
| ✅ Public methods 全部 `async def` | ✅ B1 5/5, B3 7/7 |
| ✅ 用 aiosqlite for tests（唔靠真 postgres / lancedb） | ✅ B1 fallback path, B3 全部 |

---

## 🐛 已知事項（下一輪處理）

| # | 事項 | 嚴重性 | 行動 |
|---|------|--------|------|
| 1 | `datetime.utcnow()` deprecation warning（state_machine.py） | 🟡 LOW | Python 3.12+ 強制改 timezone-aware；唔影響功能 |
| 2 | `test_persistence_pg.py::test_save_scene_fk_violation_raises` 之前 flaky | 🟢 OK | 子 agent 報告已 fixed（7/7 PASS） |
| 3 | `apscheduler` 唔喺 requirements.txt | 🟡 LOW | Ship prod 前要加 |
| 4 | `demo_mode.py:59` coroutine never awaited warning | 🟡 LOW | Pre-existing，非新 code 引入 |

---

## 🚀 Phase C 起步推薦（待你揀）

Phase C 可能嘅方向：

| Option | 範疇 | 估時 |
|--------|------|------|
| **C1** | 補 requirements.txt（加 apscheduler）+ datetime 現代化 + FK test 鞏固 | ~20 min |
| **C2** | Memory Palace Phase A 落地（用 VectorStore + PostgresPersistence 整 `memory_palace.py`） | ~2 hr |
| **C3** | FastAPI demo endpoint 連接 3 個新 module（`/memory/search`, `/scheduler/jobs`, `/persistence/characters`） | ~1 hr |
| **C4** | 收工（已 ship 大量嘢，夜深） | 0 min |

我哋已經完成：
- ✅ Phase 1: Character API (13 tests)
- ✅ Phase 2: HTTP smoke (6 endpoints)
- ✅ R1-14B re-audit pass
- ✅ Memory Palace design doc (728 lines)
- ✅ Phase B1: LanceDB
- ✅ Phase B2: APScheduler
- ✅ Phase B3: PostgreSQL

**總計：135/135 tests passing, zero regression。** 🎉

---

_本文件由 main agent (小B / MiniMax-M3) 於 2026-06-05 Phase B 收尾撰寫_

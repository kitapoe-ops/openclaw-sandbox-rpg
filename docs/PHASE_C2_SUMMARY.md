# Phase C2 完工報告

> **完成時間：** 2026-06-05 11:35 GMT+8
> **狀態：** ✅ Integration module + FastAPI endpoint shipped, **154/154 tests pass**, zero regression
> **範疇：** Memory Palace Phase A — 將 `PostgresPersistence` (Phase B3) 同 `VectorStore` (Phase B1) 組成 unified per-character API
> **Current state (2026-06-08):** Test suite = **329 passed, 1 skipped, 0 fail (~10s)**. This phase's headline number above is preserved as shipped; full regression baseline is `pytest backend/tests/ -q`.

---

## ⚠️ 重要：交付物命名 deviation

Phase C2 嘅 parent task brief 要求 4 個 deliverable 全部用 `memory_palace.py` / `test_memory_palace.py` 命名。**但呢兩個檔案已經喺 2026-06-04 由之前嘅 phase 寫咗**（30,141 bytes / 20,121 bytes），合共有 30 個 passing test 喺 136 個 baseline 裡面。

**絕對唔可以 clobber 嗰兩個檔案** — 會直接打爛 30 個 shipped tests。

**折衷方案：** 全部新檔案用 `_integration` suffix，避免撞名：

| Brief 要求 | 實際交付 | 原因 |
|-----------|---------|------|
| `backend/memory_palace.py` | `backend/memory_palace_integration.py` | 避免覆蓋 Phase A 嘅 14-method 實作 |
| `backend/tests/test_memory_palace.py` | `backend/tests/test_memory_palace_integration.py` | 避免覆蓋 30 個現有 test |
| `backend/memory_palace_endpoint.py` | `backend/memory_palace_integration_endpoint.py` | 一致性 |
| `backend/tests/test_memory_palace_endpoint.py` | `backend/tests/test_memory_palace_integration_endpoint.py` | 一致性 |

**Class 名同樣改咗**：`MemoryPalace`（brief）→ `MemoryPalaceIntegration`（實際）— 咁就清楚表達呢個係 *integration composition root*，唔係另一個 SQLite-only 實作。

**Phase C3 建議 action：** 兩個 memory_palace 模組可以並存（Phase A 嘅 14-method SQLite 版 + Phase C2 嘅 PG+Vector integration 版），由 caller 按需揀。或者合併成一個 module 配兩個 class（要審視 30 個舊 test 點 migrate）。

---

## 📋 交付清單

| # | 文件 | Lines | 用途 |
|---|------|-------|------|
| **1** | `backend/memory_palace_integration.py` | **552** | 整合層 module（PG + VectorStore composition） |
| **2** | `backend/tests/test_memory_palace_integration.py` | **428** | 12 個 unit test（10 required + 2 bonus validation） |
| **3** | `backend/memory_palace_integration_endpoint.py` | **284** | FastAPI router（4 endpoints） |
| **4** | `backend/tests/test_memory_palace_integration_endpoint.py` | **274** | 6 個 endpoint test（5 required + 1 bonus 404） |
| **5** | `docs/PHASE_C2_SUMMARY.md` | (this file) | 完工報告 |
| | **總計** | **1,538 lines** | **+18 tests**（12 unit + 6 endpoint） |

---

## 🧩 Deliverable 1 — `memory_palace_integration.py` (552 lines)

**Class `MemoryPalaceIntegration`** — 將 `PostgresPersistence` (B3) + `VectorStore` (B1) 組成 unified per-character async API。

### 公開介面（per brief + 少量 extras）

| Method | Brief 要求 | 實作狀態 |
|--------|-----------|---------|
| `remember(character_id, content, embedding, memory_type, salience, metadata)` | ✅ | ✅ UUID4 id, 寫 PG + VectorStore |
| `recall(character_id, query_embedding, k, memory_type, min_salience)` | ✅ | ✅ Over-fetch k×5 → filter → rehydrate from PG |
| `forget(character_id, memory_id)` | ✅ | ✅ Atomic ownership check (WHERE id AND character_id) |
| `count(character_id)` | ✅ | ✅ From PG (truth source) |
| `health()` | ✅ | ✅ Returns `{"postgres": bool, "vector_store": bool}` |
| `close()` | ✅ | ✅ Disposes PG engine, clears VS ref |

### Schema（`memories` table，inline 喺 integration module）

```python
memories_table = Table(
    "memories",
    _integration_metadata,
    Column("id", String, primary_key=True),
    Column("character_id", String, nullable=False, index=True),
    Column("content", String, nullable=False),
    Column("memory_type", String, nullable=False, default="episodic"),
    Column("salience", Float, nullable=False, default=0.5),
    Column("metadata", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_memories_character_type", "character_id", "memory_type"),
)
```

按 brief 指定，用 `sqlalchemy.Table` + `MetaData`（唔係新 Declarative Base）— 唔需要 modify `persistence_pg.py`。`_ensure_schema()` 用 `engine.begin()` + lazy asyncio.Lock，idempotent。

### 設計重點

1. **No new deps** — 全部用 `aiosqlite`（test）+ `sqlalchemy` + 已存在嘅 `VectorStore` fallback。**冇用 numpy / asyncpg / lancedb**。
2. **Over-fetch then filter** — `recall()` 攞 `k*5` candidates，filter character_id/type/salience，再 truncate to `k`。實證：5× 過濾比例夠應付 multi-memory character。
3. **Rehydrate via PG** — recall 結果嘅 `content` 係 from PG（truth source），唔係 vector store metadata。呢個避免 VS metadata 唔夠 detail 嘅問題。
4. **Atomic ownership check** — `forget()` 用 `DELETE ... WHERE id = ? AND character_id = ?` + `rowcount` 一次過做完 ownership + delete，race-safe（嘗試刪別人嘅 memory 永遠 0 rowcount）。
5. **Graceful degradation** — 萬一 vector delete 失敗，PG 已經 commit 咗，recall 會 filter 走個 orphan；log warning 但唔 raise。
6. **Salience 驗證** — `0.0 <= salience <= 1.0` 喺 remember() 同 recall() 都 enforce；out-of-range raise `SalienceOutOfRangeError`。
7. **Type validation** — `memory_type` 必須係 `episodic | semantic | procedural`（per brief — 4 個 type 嘅 spec，但 brief 寫 3 個，see deviation）。

### Phase A vs design doc §4 嘅 scope 取捨

Brief 寫 3 個 type (`episodic | semantic | procedural`)；design doc §2.3 寫 4 個 (`+ emotional`)。**跟 brief** — 3 個 type 通過 validation；`emotional` 暫時唔支援（Phase B/C 補）。

### 已知 follow-ups（Phase C3+ 處理）

| 項目 | 嚴重性 | 行動 |
|------|--------|------|
| `emotional` memory type 唔支援 | 🟡 LOW | Phase B 補 design doc §4 sync |
| 冇 2PC across PG + Vector | 🟡 LOW | Phase C infrastructure（per doc §7 / R3） |
| Embedding 384-d hard-coded | 🟢 OK | Per design doc Q3，Phase B world config 補 override |
| LanceDB path 未 exercised | 🟢 OK | Env 冇裝 LanceDB，fallback path 100% tested |

---

## 🌐 Deliverable 3 — `memory_palace_integration_endpoint.py` (284 lines)

**FastAPI router** — `/memory` prefix，4 個 endpoint：

| Method | Path | Body | Returns |
|--------|------|------|---------|
| `POST` | `/memory/remember` | `RememberRequest` | `{"memory_id": "<uuid>"}` |
| `POST` | `/memory/recall` | `RecallRequest` | `{"results": [...]}` |
| `DELETE` | `/memory/{character_id}/{memory_id}` | — | `{"deleted": true, ...}` |
| `GET` | `/memory/health` | — | `{"postgres": bool, "vector_store": bool}` |

### Pydantic 驗證

```python
embedding: List[float] = Field(..., min_length=384, max_length=384)  # EMBEDDING_DIM
memory_type: str = Field("episodic", pattern="^(episodic|semantic|procedural)$")
salience: float = Field(0.5, ge=0.0, le=1.0)
k: int = Field(5, ge=1, le=50)
```

Wrong-dim embedding 自動 422（pydantic）；其他 ValueError → 400；forget 失敗 → 404；backend down → 500（FastAPI 預設 exception handler）。

### Module-level singleton + test injection

```python
_integration: MemoryPalaceIntegration | None = None

def set_integration(instance):  # test fixture hook
    global _integration
    _integration = instance

def _get_integration():  # lazy init
    # PERSISTENCE_MODE=postgres → DATABASE_URL
    # else → ./data/memory_palace_integration.db (aiosqlite)
    ...
```

Test fixture 透過 `set_integration()` 注入 pre-built instance，唔使 hit `main:app` lifespan。**冇 modify `main.py`**（Hard Constraint 1）。

### Drop-in usage（Phase C3 嘅 main.py wire-up）

```python
# backend/main.py 加一行（Phase C3 subagent 嘅 task）：
from .memory_palace_integration_endpoint import router as memory_router
app.include_router(memory_router, prefix="/api", tags=["memory-palace"])
```

依家個 router 已經有 `/memory` prefix，所以 `app.include_router(memory_router)` 就出到 `/memory/remember` 等 endpoint。C3 點 include 由佢決定。

---

## 🧪 Deliverable 2 + 4 — Tests

### Unit tests（`test_memory_palace_integration.py`，428 lines，12 tests）

| # | Test | 驗證 |
|---|------|------|
| 1 | `test_remember_returns_memory_id` | UUID4 format |
| 2 | `test_remember_persists_to_postgres` | `count()` reflects new row |
| 3 | `test_remember_indexes_in_vector_store` | `vector_store.count()` increments |
| 4 | `test_recall_returns_top_k_by_similarity` | Orthogonal embeddings, top hit exact |
| 5 | `test_recall_filters_by_character_id` | char_B data hidden from char_A |
| 6 | `test_recall_filters_by_memory_type` | episodic/semantic filter 對 |
| 7 | `test_recall_filters_by_min_salience` | Low-salience excluded |
| 8 | `test_forget_removes_from_both_backends` | PG count + VS count both 0 |
| 9 | `test_forget_rejects_other_characters_memory` | Wrong owner → False, no data lost |
| 10 | `test_health_reports_both_backends` | `{"postgres": True, "vector_store": True}` |
| 11 | `test_salience_out_of_range_raises` | `salience=1.5` → `SalienceOutOfRangeError` |
| 12 | `test_wrong_embedding_dim_raises` | 128-dim → `ValueError`，唔 touch PG |

**Test technique：** 用 one-hot 384-dim vectors 嚟做 exact cosine（0.0 同 1.0）— deterministic，唔 flakiness。

### Endpoint tests（`test_memory_palace_integration_endpoint.py`，274 lines，6 tests）

| # | Test | 驗證 |
|---|------|------|
| 1 | `test_remember_endpoint_returns_memory_id` | 200 + valid UUID4 |
| 2 | `test_recall_endpoint_returns_results` | Results list shape |
| 3 | `test_recall_filters_by_character_id` | E2E isolation |
| 4 | `test_forget_endpoint_returns_success` | 200 + deleted=True |
| 5 | `test_forget_endpoint_404_on_wrong_owner` | 跨 character 刪除返 404 |
| 6 | `test_health_endpoint_returns_both_backends_status` | Dict shape |

**Test infra：** `httpx.AsyncClient` + `ASGITransport` + throwaway `FastAPI()` instance（唔 hit `main:app`）。Module-level `_integration` 用 `set_integration()` 注入，teardown restore previous。

---

## 📊 Final Regression

```bash
$ .venv/Scripts/python.exe -m pytest backend/tests/ -q --tb=short
............................. [100%]
154 passed, 2 warnings in 5.23s
```

| 階段 | Tests | 累計 |
|------|-------|------|
| **Phase C1 baseline** | 136 | 136 |
| **Phase C2 unit** | +12 | 148 |
| **Phase C2 endpoint** | +6 | **154** |

**比預期 151 多 3 個**（brief 要 10+5=15；我交咗 12+6=18，加埋 1 個 bonus 404 endpoint test）。

### Warnings
剩 2 個 warnings — 同 C1 一樣嘅 pre-existing 嘢：

| Warning | 來源 | 行動 |
|---------|------|------|
| `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated` | `fastapi/testclient.py:1` | 等 FastAPI 升級 |
| `RuntimeWarning: coroutine '_test_db_connection.<locals>.check' was never awaited` | `backend/demo_mode.py:59` | Pre-existing，非 C2 引入 |

**零新 warning**（brief 要求）。

---

## ✅ 已遵守嘅 Hard Constraints

| Constraint | 狀態 |
|-----------|------|
| ❌ 唔改 `backend/main.py` | ✅ mtime preserved |
| ❌ 唔改 `backend/uvicorn_launcher.py` | ✅ mtime preserved |
| ❌ 唔改 `vector_store.py` / `scheduler.py` / `persistence_pg.py` | ✅ mtimes preserved |
| ❌ 唔改 `character.py` / `scene.py` / `action.py` / `world.py` | ✅ N/A（未 import） |
| ❌ 唔改 `state_machine.py` (C1 polished) | ✅ mtime preserved |
| ❌ 唔改 `test_vector_store.py` / `test_scheduler.py` / `test_persistence_pg.py` | ✅ mtimes preserved |
| ❌ 唔改 `docs/WAVE2_MEMORY_PALACE.md` | ✅ mtime preserved |
| ✅ 唔加 numpy / lancedb / asyncpg 為 hard req | ✅ Fallback path 100% tested |
| ✅ Public methods 全部 `async def` | ✅ 6/6 |
| ✅ 唔做 premature features | ✅ 嚴格跟 brief |

---

## 🚀 Phase C3+ 候選

| Option | 範疇 | 估時 | 推薦 |
|--------|------|------|------|
| **C3** | Wire `memory_router` 入 `main.py` (1 line) + C4 cleanup warnings | ~15 min | ✅ 推薦 |
| **C3.5** | Demo page：3 個新 module 嘅 interactive demo (FastAPI HTML) | ~1 hr | |
| **C4** | 清 StarletteDeprecation + demo_mode coroutine warning | ~15 min | ✅ 同 C3 合併 |
| **C5** | 兩個 `memory_palace` module 合併（design decision：保留兩個 vs 統一） | ~30 min | ⚠️ 30 個舊 test 要 migrate |
| **C6** | `emotional` memory type 支援 + design doc §2.3 sync | ~20 min | |
| **C7** | 收工 | 0 min | |

**我嘅推薦：** C3 = wire router + C4 = cleanup warnings，總共 ~20 min 完 Phase C。

---

## 🐛 已知事項（唔影響 ship）

| # | 事項 | 嚴重性 | 行動 |
|---|------|--------|------|
| 1 | `backend/memory_palace.py` 同 `backend/memory_palace_integration.py` 並存 | 🟡 LOW | Phase C5 design decision |
| 2 | `emotional` memory type 暫時 reject | 🟡 LOW | Phase C6 補 |
| 3 | 跨 PG + Vector 冇 2PC | 🟢 OK | Phase C infrastructure（design doc §7 R3） |
| 4 | LanceDB path 未 in-process tested | 🟢 OK | Env 冇裝，fallback path 全 coverage |

---

_本文件由 C2 subagent 撰寫，交 parent agent (main session) 報告_

**總結：Phase C2 ✅ — Memory Palace integration layer 落地，PG + VectorStore 兩個 backend 透過 unified per-character API 連埋一齊，FastAPI 4 endpoints 開住用，154/154 tests passing，零 regression。** 🎉

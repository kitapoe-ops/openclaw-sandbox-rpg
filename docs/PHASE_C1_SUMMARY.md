# Phase C1 完工報告

> **完成時間：** 2026-06-05
> **狀態：** ✅ All 3 polish targets shipped, 136/136 tests pass, zero `datetime.utcnow` warnings
> **Current state (2026-06-08):** Test suite = **329 passed, 1 skipped, 0 fail (~10s)**. This phase's headline number above is preserved as shipped; full regression baseline is `pytest backend/tests/ -q`.

---

## 📋 交付清單

| # | 目標 | 文件 | Lines (before → after) | 狀態 |
|---|------|------|------------------------|------|
| **T1** | requirements.txt 補 apscheduler | `backend/requirements.txt` | 58 → 61 | ✅ |
| **T2** | datetime 現代化（Python 3.12+ ready） | `backend/state_machine.py` | 168 → 168 (5 swaps) | ✅ |
| **T3** | FK violation test 鞏固 | `backend/tests/test_persistence_pg.py` | 153 → 190 (+1 test + fixture fix) | ✅ |

**全套 regression：** `pytest backend/tests/` → **136 passed in 5.19s** ✅
- 比 Phase B 嘅 135 → **+1 test**（新增 FK violation test）
- 0 個 `datetime.utcnow` deprecation warning（之前有 ~16 個）
- 剩餘 2 個 warnings 係 pre-existing 嘅（StarletteDeprecation + `demo_mode.py:59` coroutine），唔關我哋事

---

## 🛠️ T1 — requirements.txt

新增 `# Scheduling` section：
```txt
# Scheduling
apscheduler>=3.10,<4.0
```

順手 sort 咗 `# Testing` section 字母序（httpx, pytest, pytest-asyncio, pytest-cov）。

**Why it matters：** Phase B2 subagent 手動裝咗 `apscheduler==3.11.2`，但 requirements.txt 漏咗。冇咗呢行，未來 deploy 環境會 break。

---

## ⏰ T2 — datetime 現代化

**問題：** Python 3.12+ 開始 deprecate `datetime.utcnow()`，會出 ~16 個 warning。

**5 個 callsites 已 swap**（`backend/state_machine.py` lines 40, 41, 117, 136, 156）：

```diff
- self.created_at = datetime.utcnow()
+ self.created_at = datetime.now(timezone.utc)
```

加 `timezone` 入 import：
```python
from datetime import datetime, timezone
```

**驗證：** `pytest backend/tests/test_state_machine_tier1.py` → **19/19 PASS**（用 `-W error::DeprecationWarning` 都唔爆 = 警告真係清咗，唔係只係當 info 顯示）

**好處：**
- Python 3.12+ compatible（UTC now 同 `datetime.UTC` aware object 一齊用）
- 全部 `created_at` / `updated_at` 變成 timezone-aware
- 零 warning 噪訊

---

## 🔒 T3 — FK Violation Test 鞏固

**問題：** Phase B3 subagent 提過 `test_save_scene_fk_violation_raises` 之前 flaky。Subagent 搵到 root cause：

> **aiosqlite 預設 `PRAGMA foreign_keys=OFF`**（SQLite 預設行為）— 所以 FK constraint 根本冇 enforce，test 行為不穩定。

**Fix（in test fixture，唔改 production adapter）：**
```python
from sqlalchemy import event

@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

**新增 8th test：**
```python
async def test_save_scene_fk_violation_raises(pg_adapter):
    """Saving a scene with non-existent character_id must raise IntegrityError."""
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await pg_adapter.save_scene("scene_99", "char_does_not_exist", {"foo": "bar"})
```

**結果：** `pytest backend/tests/test_persistence_pg.py` → **8/8 PASS**，PRAGMA 確認 return 1（FK 真係 enable 咗）。

---

## ✅ 已遵守嘅 Hard Constraints

| Constraint | 狀態 |
|-----------|------|
| ❌ 唔改 main.py / uvicorn_launcher.py | ✅ mtime preserved |
| ❌ 唔改 Phase B files（vector_store / scheduler / persistence_pg） | ✅ mtimes preserved |
| ❌ 唔改 Wave 2 shipped files | ✅ N/A — 唔存在於本 repo |
| ❌ 唔改 Memory Palace design doc | ✅ Untouched |
| ✅ 100% backward-compatible | ✅ 全部 135 個原有 test + 1 個新 test = 136 PASS |

---

## 🐛 剩餘警告（pre-existing, non-blocking）

| Warning | 來源 | 嚴重性 | 行動 |
|---------|------|--------|------|
| `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated` | `fastapi/testclient.py` | 🟡 LOW | 等 FastAPI 升級，唔關我哋事 |
| `RuntimeWarning: coroutine '_test_db_connection.<locals>.check' was never awaited` | `backend/demo_mode.py:59` | 🟡 LOW | Pre-existing，唔係今輪引入 |

呢兩個係 Phase A 已經存在嘅，唔影響 C1 嘅完成度。如果你想清，可以喺 Phase C 開多一個 C1.5 target。

---

## 🚀 仲可以做嘅嘢（Phase C 後續選項）

| Option | 範疇 | 估時 |
|--------|------|------|
| **C2** | Memory Palace Phase A 落地（用 VectorStore + PostgresPersistence 整 `memory_palace.py`） | ~2 hr |
| **C3** | FastAPI demo endpoint 連接 3 個新 module（`/memory/search`, `/scheduler/jobs`, `/persistence/characters`） | ~1 hr |
| **C4** | 清埋 StarletteDeprecation + demo_mode coroutine warning | ~15 min |
| **C5** | 收工休息 | 0 min |

---

## 📊 累計進度（Phase 1 → C1）

| 階段 | 模塊 | Tests |
|------|------|-------|
| Phase 1 | Character API | 13 |
| Phase 2 | HTTP smoke (6 endpoints) | — |
| Wave 2 | R1 re-audit, YAML, World API | 5 + 2 |
| Memory Palace | Design doc (728 lines) | — |
| Phase B1 | LanceDB | 7 |
| Phase B2 | APScheduler | 4 |
| Phase B3 | PostgreSQL | 7 → 8 (FK test) |
| **Phase C1** | **Polish pass** | **+1 (total 136)** |

**總計：136/136 tests passing, zero regression, 9 個 production files 落咗 / 1 個 design doc / 0 個 deprecation warning（剩 2 個 pre-existing）。** 🎉

---

_本文件由 main agent (小B / MiniMax-M3) 於 2026-06-05 Phase C1 收尾撰寫_

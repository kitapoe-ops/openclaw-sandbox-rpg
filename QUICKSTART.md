# 🚀 Quick Start — 1 分鐘跑 Demo

> 兩種模式：完整模式（PostgreSQL + Docker） 或 Demo 模式（零基礎設施）

---

## 模式 A：Demo 模式（最快，**30 秒啟動**）

**完全唔需要 Docker / Postgres / LLM API Key**。後端用 `scenes_demo.py` 嘅 hard-coded 數據。

```bash
# 1. Clone
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg

# 2. 裝依賴
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cd ..

# 3. 啟動（demo 模式）
cd backend
DEMO_MODE=true uvicorn main:app --reload --port 8000
```

預期 log：
```
[Mode] DEMO MODE — no DB required
[Demo] Character: char_demo_player
[Demo] Scene: loc_phandalin_town
[Startup] Ready
```

### 試 Demo API

```bash
# 健康檢查
curl http://localhost:8000/health
# { "status": "ok", "mode": "demo", ... }

# 取得 demo 角色狀態
curl http://localhost:8000/api/character/char_demo_player
# { "character_id": "char_demo_player", "name": "Rockseeker 家族嘅探子", ... }

# 取得當前場景 + 4 個 vignettes
curl http://localhost:8000/api/scene/char_demo_player
# { "round": 1, "narrative": "...", "choices": [4 個 vignettes] }

# 列出世界
curl http://localhost:8000/api/world/
# { "worlds": [{ "world_id": "dnd_5e_forgotten_realms_phandalin", ... }] }

# 連 WebSocket
wscat -c ws://localhost:8000/ws/game/char_demo_player
# 之後 send: {"type": "ping"}
# 收到: {"type": "pong", ...}
```

### 啟動前端

```bash
# 另一個 terminal
cd frontend
npm install
npm run dev
```

開 `http://localhost:8000` 或是 `http://localhost:5173`，預設顯示角色與場景。


---

## 模式 B：完整模式（PostgreSQL + Docker）

**真實 DB 持久化、LLM 整合**。

```bash
# 1. Clone
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg

# 2. 設定環境變數
cp .env.example .env
# 編輯 .env，填寫：
#   MINIMAX_API_KEY=your_key_here
#   POSTGRES_PASSWORD=strong_password

# 3. 一鍵啟動
docker-compose up -d
```

預期 log：
```
sandbox-rpg-postgres  | database system is ready to accept connections
sandbox-rpg-backend   | [Mode] FULL MODE — connecting to DB
sandbox-rpg-backend   | [Startup] DB schema initialized
sandbox-rpg-backend   | [Startup] Demo data seeded
sandbox-rpg-backend   | [Startup] Ready
sandbox-rpg-frontend  |   VITE v5.2.0  ready in 500 ms
sandbox-rpg-frontend  |   Local:   http://localhost:5173/
```

### 訪問

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/ws/game/char_demo_player

### 查看日誌

```bash
docker-compose logs -f backend
docker-compose logs -f postgres
docker-compose logs -f frontend
```

### 停止

```bash
docker-compose down           # 停止 + 保留 volumes
docker-compose down -v        # 停止 + 刪 volumes（包括 DB 數據）
```

---

## 🎮 Demo 玩法

### 1. 啟動後
- Backend 自動 seed：Phandalin 鎮 + Rockseeker 探子
- Demo character_id: `char_demo_player`
- Demo scene_id: `loc_phandalin_town`

### 2. 訪問
```bash
# 開瀏覽器：http://localhost:5173
# 角色：Rockseeker 家族嘅探子（Dwarf Shield）
# 場景：凡達林鎮 (Phandalin) — 戰後 30 年嘅偏遠小鎮
```

### 3. 試 WebSocket
```javascript
// 喺 browser console 或 Node.js
const ws = new WebSocket('ws://localhost:8000/ws/game/char_demo_player')
ws.onmessage = e => console.log(JSON.parse(e.data))

ws.onopen = () => {
  // Ping
  ws.send(JSON.stringify({type: 'ping'}))

  // 提交選擇
  setTimeout(() => {
    ws.send(JSON.stringify({
      type: 'action_submit',
      round: 1,
      character_id: 'char_demo_player',
      choice: {
        option_id: 'choice_1',  // 鐵匠 vignette
        attitude_selections: [
          { dimension: 'caution', level: 'careful' }
        ]
      }
    }))
  }, 1000)
}
```

預期：
1. 收到 `action_accepted` （task_id）
2. 收到 `scene_update` （新場景，由 LLM 或 demo 產生）

### 4. 切換 LLM
預設用 `scenes_demo.py` 嘅硬編碼場景。

**用真 LLM**（需要 MINIMAX_API_KEY）：
```bash
# .env
MINIMAX_API_KEY=sk-xxxx
```

後端會自動用 `llm_client.py` 呼叫 MiniMax M3，fallback 喺 LLM 失敗時用 demo。

---

## 🛠️ 常見問題

### Q: backend 啟動失敗？
**A:** 檢查 Python 版本（要 3.11+）同依賴：
```bash
python --version  # 要 3.11+
pip install -r backend/requirements.txt
```

### Q: docker-compose 啟動失敗？
**A:** 檢查 Docker / port：
```bash
docker --version
docker-compose --version
# 確認 5432, 8000, 5173 port 冇被佔用
```

### Q: 點解我嘅場景唔更新？
**A:** 檢查：
1. 連 WebSocket 成功？（`connection_ack` 收到？）
2. `action_accepted` 收到？（task_id 喺手？）
3. 等 5-15 秒（LLM call）or 立即（demo 模式）
4. 看 `docker-compose logs -f backend` 有冇 error

### Q: 點解 LLM 生成嘅 JSON 唔啱 schema？
**A:** 檢查：
1. `MINIMAX_API_KEY` 正確
2. 用嘅係 `MiniMax-M3`（非 `abab6.5-chat`）
3. 詳細睇 `docs/PROMPTS/scene_agent_prompt.md`

### Q: 我想加新 NPC / 場景？
**A:** 兩個方法：
1. 編輯 `worlds/dnd_5e_forgotten_realms.yaml`，跟 `docs/WORLD_FILLING_GUIDE.md` 標準填
2. 編輯 `backend/scenes_demo.py` 加 hard-coded 數據（即時生效）

---

## 📋 Checklist

✅ Backend 啟動（demo 或 full）
✅ 健康檢查通過
✅ 取得 demo character
✅ 取得 demo scene + 4 vignettes
✅ WebSocket 連線成功
✅ 提交選擇，收到 scene_update
✅ Frontend 顯示場景

如果以上全部 ✅，恭喜你可以開始填世界觀 / 整合 LLM / 部署上 Vercel + Cloudflare！

---

## 📚 進一步

- [架構文檔](docs/ARCHITECTURE.md) — 系統設計
- [50 萬 Token World 指南](docs/WORLD_FILLING_GUIDE.md) — 點樣填滿世界觀
- [RAG Chunking Strategy](docs/RAG_CHUNKING_STRATEGY.md) — LanceDB 設定
- [Cloudflare 部署](deploy/cloudflare/DEPLOY.md) — 上線
- [Scene Agent Prompt](docs/PROMPTS/scene_agent_prompt.md) — LLM prompt 設計

---

# 🌐 English Quick Start (5-minute end-to-end demo)

> For English-speaking contributors. The Chinese sections above cover the same flow in more detail.

## Prerequisites
- Python 3.11+
- 500 MB free disk
- No Docker, no Postgres, no LLM API key required (Phase B ships with aiosqlite + pure-Python vector fallback)

## Steps

### 1. Clone and set up the venv
```bash
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

### 2. Run the full test suite (expect 313 passed in ~8 seconds, excluding smoke tests)
```bash
.venv/Scripts/python.exe -m pytest backend/tests/ -k "not test_production_smoke"
```


### 3. Start the app (uses in-memory persistence + pure-Python vector store)
```bash
.venv/Scripts/python.exe -m uvicorn backend.app_with_memory:app --reload --port 8000
```

### 4. Verify health
```bash
curl http://localhost:8000/memory/health
# Expected: {"postgres": true, "vector_store": true}
```

### 5. Try a remember / recall round-trip
```bash
# Remember a memory (embedding is a 384-dim vector; use any 384 floats)
curl -X POST http://localhost:8000/memory/remember \
  -H "Content-Type: application/json" \
  -d '{
    "character_id": "char_demo",
    "content": "Met the blacksmith, asked about iron swords",
    "embedding": [0.0, 0.1, 0.2, ...]'"'"', /* 384 total */,
    "memory_type": "episodic",
    "salience": 0.7
  }'

# Recall similar memories
curl -X POST http://localhost:8000/memory/recall \
  -H "Content-Type: application/json" \
  -d '{
    "character_id": "char_demo",
    "query_embedding": [0.0, 0.1, 0.2, ...],
    "k": 5
  }'
```

### 6. Open the demo frontend
In your browser at `http://localhost:8000` (production) or `http://localhost:5173` (dev):

- The page loads the lobby screen


### 7. (Optional) Run the demo cron
The `memory_health_minute` job hits `/memory/health` every minute. Watch the backend logs to see the cron firing.

## What you should see
- **Step 2:** `313 passed in 8.14s` — no failures, 0 new warnings

- **Step 3:** Uvicorn banner on `http://0.0.0.0:8000`
- **Step 4:** JSON with both backends healthy
- **Step 5:** A memory_id (uuid4) on remember, an array of `{memory_id, content, similarity, ...}` on recall
- **Step 6:** Character list and scene map render in browser

## Troubleshooting
- **`pytest` complains about missing modules** — re-run `pip install -r backend/requirements.txt`; Phase B2 added `apscheduler>=3.10,<4.0`
- **Port 8000 in use** — change to `--port 8001` and update the `curl` URLs
- **Import errors on uvicorn** — make sure you activated the venv (`.venv/Scripts/Activate.ps1` on Windows)
- **Tests pass but `/memory/health` returns false** — check the backend log; aiosqlite should always report `postgres: true` since it uses the same SQLAlchemy engine

## Next steps
- Read [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for the full system design
- Check [docs/PHASE_ROADMAP.md](./docs/PHASE_ROADMAP.md) for what's shipped and what's planned
- Try Phase D1 (merge two memory_palace modules) or D4 (frontend full E2E) as a first contribution

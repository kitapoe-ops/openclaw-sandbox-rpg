# OpenClaw Sandbox RPG

> 異步多人純語意狀態機沙盒劇本世界 — 基於 D&D 5e SRD 預設世界

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status: Wave 1](https://img.shields.io/badge/Status-Wave%201-blue)]()

## 項目簡介

一個**完全放棄數字、純語意狀態**嘅異步多人沙盒 RPG。LLM 係上帝 + 沙盒，後端係物理引擎 + 邏輯鎖，玩家透過「事件選擇 + 態度組合 + 裝備配置」推動世界。

### 核心特色

- 🎭 **純語意狀態機** — 角色狀態用 `stamina: muscle_ache` 取代 `HP: 30/100`
- 🌍 **預載世界觀** — D&D 5e SRD（被遺忘嘅國度）作為預設
- ⚡ **15 分鐘異步回合** — 玩家每 15 分鐘揀 1 個選擇
- 🤖 **三層 Agent 矩陣** — 上帝 Agent（每日 ETL）+ 場景 Agent（即時）+ 副 Agent（細微）
- 🧠 **LLM 係上帝 + 沙盒** — 推動劇情 + 守世界規則
- 🔒 **物理邏輯鎖 v2.0** — 保留玩家意圖，演繹「想做但做唔到」
- 📚 **50 萬 token 世界觀** — 預載，永不改變嘅永恆層 + 動態調整嘅世界參數

## 技術棧

| 層 | 技術 |
|----|------|
| 後端 | Python 3.11+ / FastAPI / SQLAlchemy 2.0 async |
| 前端 | Vue 3 + Vite + TypeScript + Pinia |
| 資料庫 | PostgreSQL 15 + LanceDB |
| LLM 雲端 | MiniMax M3 (1M context) |
| 部署 | Vercel (前端) + 本地 Docker (後端) + Cloudflare Tunnels |

## 🚀 快速開始 (5 分鐘 Demo)

### 1. Clone + 設定

```bash
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg
cp .env.example .env
# 編輯 .env，至少填寫 MINIMAX_API_KEY
```

### 2. 啟動後端

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 啟動 PostgreSQL（Docker 方式）
docker run -d --name postgres-sandbox \
  -e POSTGRES_DB=sandbox_rpg \
  -e POSTGRES_USER=rpg_user \
  -e POSTGRES_PASSWORD=dev_password \
  -p 5432:5432 \
  postgres:15-alpine

# 啟動 FastAPI
uvicorn backend.main:app --reload --port 8000
```

預期輸出：
```
[Startup] DB schema initialized
[Startup] Demo data seeded
[Startup] Ready
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 3. 訪問 Demo API

```bash
# Health check
curl http://localhost:8000/health

# 取得 demo 角色
curl http://localhost:8000/api/character/char_demo_player

# 取得當前場景
curl http://localhost:8000/api/scene/char_demo_player

# 列出可用世界
curl http://localhost:8000/api/world/
```

### 4. 啟動前端

```bash
cd frontend
npm install
npm run dev
```

開啟 `http://localhost:5173` 即可。

### 5. 用 WebSocket 連線

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/game/char_demo_player')
ws.onopen = () => {
  console.log('Connected')
  ws.send(JSON.stringify({
    type: 'action_submit',
    round: 1,
    character_id: 'char_demo_player',
    choice: {
      option_id: 'choice_1',
      attitude_selections: [
        { dimension: 'caution', level: 'careful' }
      ]
    }
  }))
}
ws.onmessage = (e) => console.log('Scene update:', JSON.parse(e.data))
```

## 📚 文檔

- 📐 [架構文檔](docs/ARCHITECTURE.md) — 完整架構 + 設計決策
- 📋 [API 規格](docs/API.md) — REST + WebSocket
- 🛠️ [開發指南](docs/DEVELOPMENT.md) — 開發工作流
- 📜 [變更日誌](docs/CHANGELOG.md)
- 📑 [Schema 套件](docs/SCHEMAS/)
- 🤖 [Prompt 模板](docs/PROMPTS/)
- 🌍 [50 萬 Token World 填充指南](docs/WORLD_FILLING_GUIDE.md)
- 🔍 [RAG Chunking Strategy](docs/RAG_CHUNKING_STRATEGY.md)
- ☁️ [Cloudflare 部署指南](deploy/cloudflare/DEPLOY.md)

## 🎮 Demo 玩法

1. **開瀏覽器**：`http://localhost:5173`
2. **創建角色**：選擇「Rockseeker 家族嘅探子」（預設）
3. **閱讀場景**：凡達林鎮嘅描述 + 4 個 vignette
4. **揀選項**：每個 vignette 對應唔同故事方向
5. **選態度**：每個 vignette 內 1-2 個 attitude
6. **確認**：提交後 5-15 秒收到新場景（LLM 生成）or 立即（demo fallback）

## 🏗️ 開發進度

🚧 **Wave 1: 核心引擎** (Month 1-3 計劃)

- [x] 項目初始化
- [x] Schema 套件 (8 份)
- [x] LLM Prompt 模板 (Scene Agent v2.0)
- [x] Backend skeleton (FastAPI + WebSocket + DB)
- [x] Frontend skeleton (Vue 3 + Pinia + WebSocket)
- [x] 50 萬 Token World 範本 (25K 起步)
- [x] Q6/Q7 hardened (三步 DB TX + in-memory inflight)
- [x] Demo 數據 (Phandalin + Rockseeker starter)
- [ ] 實作 LLM 整合（用 scenes_demo fallback）
- [ ] 跑 RAG chunking + LanceDB index
- [ ] 測試完整 1 小時自由探索 (MVP-B)
- [ ] Vercel + Cloudflare 部署

## 🎯 下一步

1. **Clone 最新版**：`git pull`
2. **填世界觀到 100K token**（用 `docs/WORLD_FILLING_GUIDE.md` 標準）
3. **實作 RAG chunker**（按 `docs/RAG_CHUNKING_STRATEGY.md`）
4. **測試 Scene Agent pipeline**（完整 1 輪）
5. **Vercel + Cloudflare 部署**（按 `deploy/cloudflare/DEPLOY.md`）

## 授權

MIT License — 詳見 [LICENSE](LICENSE)
D&D 5e SRD 內容採用 OGL / CC 授權。

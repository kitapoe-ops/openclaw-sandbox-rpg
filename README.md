# OpenClaw Sandbox RPG

> 異步多人純語意狀態機沙盒劇本世界 — 基於 D&D 5e SRD 預設世界

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status: Wave 1](https://img.shields.io/badge/Status-Wave%201-blue)]()

## 項目簡介

一個**完全放棄數字、純語意狀態**嘅異步多人沙盒 RPG。LLM 係上帝 + 沙盒，後端係物理引擎 + 邏輯鎖，玩家透過「事件選擇 + 態度組合 + 裝備 + 道具」推動世界。

### 核心特色

- 🎭 **純語意狀態機** — 角色狀態用 `stamina: muscle_ache` 取代 `HP: 30/100`
- 🌍 **預載世界觀** — D&D 5e SRD（被遺忘嘅國度）作為預設
- ⚡ **15 分鐘異步回合** — 玩家每 15 分鐘揀 1 個選擇
- 🤖 **三層 Agent 矩陣** — 上帝 Agent（每日 ETL）+ 場景 Agent（即時）+ 副 Agent（細微）
- 🧠 **LLM 係上帝 + 沙盒** — 推動劇情 + 守世界規則
- 🔒 **物理邏輯鎖 v2.0** — 後端強制物理一致性，LLM 自由演繹殘疾文學
- 📚 **50 萬 token 世界觀** — 預載，永不改變嘅永恆層 + 動態調整嘅世界參數

## 技術棧

| 層 | 技術 |
|----|------|
| 後端 | Python 3.11+ / FastAPI |
| 前端 | Vue 3 + Vite + TypeScript |
| 資料庫 | PostgreSQL 15 + LanceDB |
| LLM 雲端 | MiniMax M3 (1M context) |
| LLM 本地 | Qwen2.5-14B-Instruct (LM Studio :1234) |
| 部署 | Docker Compose |

## 快速開始

```bash
# 1. Clone
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg

# 2. 複製環境變數範本
cp .env.example .env

# 3. 啟動 Docker
docker-compose up -d

# 4. 訪問
# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

## 文檔

- 📐 [架構文檔](docs/ARCHITECTURE.md)
- 📋 [API 規格](docs/API.md)
- 🛠️ [開發指南](docs/DEVELOPMENT.md)
- 📜 [變更日誌](docs/CHANGELOG.md)
- 📑 [Schema 套件](docs/SCHEMAS/)
- 🤖 [Prompt 模板](docs/PROMPTS/)

## 開發進度

🚧 **Wave 1: 核心引擎**（3 個月計劃）

- [x] 項目初始化
- [ ] Schema 套件（8 份）
- [ ] LLM Prompt 模板（3 份 + few-shots）
- [ ] 後端核心模組
- [ ] D&D 5e 預設世界包
- [ ] API 端點
- [ ] Vue 3 前端
- [ ] Docker 部署
- [ ] MVP-B 驗收：單玩家 1 小時自由探索

## 授權

MIT License — 詳見 [LICENSE](LICENSE)

## 致謝

- 預設世界觀基於 [D&D 5e SRD](https://dnd.wizards.com/resources/systems-reference-document)（OGL / CC）
- 靈感來自 MUD / 文字冒險遊戲 / 劇本殺
- 由 OpenClaw + MiniMax M3 + Qwen 2.5 共同驅動

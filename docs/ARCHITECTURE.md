# OpenClaw Sandbox RPG - Architecture

> Version 0.1.0 | Last updated: 2026-06-03

## 1. 系統定位

**異步多人純語意狀態機沙盒劇本世界** — 預設 D&D 5e 世界觀，玩家透過事件選擇 + 態度組合 + 裝備配置推動世界。

### 核心特色

- **純語意狀態**：無數字，全部用 semantic bucket labels
- **預載世界觀**：D&D 5e SRD（被遺忘嘅國度）
- **15 分鐘異步回合**：每 15 分鐘揀 1 個選擇
- **三層 Agent 矩陣**：上帝 Agent + 場景 Agent + 副 Agent
- **物理邏輯鎖 v2.0**：保留玩家意圖，演繹「想做但做唔到」

## 2. 技術棧

| 層 | 技術 |
|----|------|
| 後端 | Python 3.11+ / FastAPI |
| 前端 | Vue 3 + Vite + TypeScript |
| 資料庫 | PostgreSQL 15 + LanceDB |
| LLM 雲端 | MiniMax M3 (1M context) |
| LLM 本地 | Qwen2.5-14B-Instruct (LM Studio :1234) |
| 部署 | Docker Compose |

## 3. 整體架構

```
┌─────────────────────────────────────────────┐
│ Frontend (Vue 3 SPA)                         │
│  ├─ 場景面板 (ScenePanel)                   │
│  ├─ 選擇面板 (ChoicePanel + AttitudeSelector)│
│  ├─ 角色狀態 (CharacterStatus)              │
│  ├─ 背包 + 裝備 (Inventory + Equipment)     │
│  └─ 倒計時器 (CountdownTimer)              │
└────────────────┬────────────────────────────┘
                 │ HTTPS + WebSocket
┌────────────────▼────────────────────────────┐
│ Backend (FastAPI)                            │
│  ├─ REST API (/api/character, /api/action)  │
│  ├─ WebSocket (/ws/game/{id})               │
│  ├─ 語意狀態機 (semantic_gradient.py)       │
│  ├─ 物理邏輯鎖 (physics_lock.py)            │
│  └─ 選擇驗證 (choice_validator.py)          │
└────────────────┬────────────────────────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
┌────────┐  ┌─────────┐  ┌────────────────┐
│ Postgres│  │ LanceDB │  │ LLM Clients    │
│ (硬狀態)│  │ (向量)  │  │ ├─ MiniMax M3  │
│        │  │         │  │ └─ Qwen Local  │
└────────┘  └─────────┘  └────────────────┘
```

## 4. 三層世界觀模型

```
世界觀 = 永恆層 + 參數層 + 玩家影響層

永恆層（5 萬 token，預載，永不改）
├─ 物理規則
├─ 種族 / 文化
└─ 地圖 / 曆法

世界參數層（即時狀態，動態調整）
├─ 勇者之力（5 級 semantic gradient）
├─ 龍之威脅（5 級）
├─ 物價指數（5 級）
└─ ...（每個世界參數 5 級）

玩家影響層（累積效果，多輪後見效）
├─ 角色狀態
├─ NPC 好感度
└─ Quest 進度
```

## 5. Agent 矩陣

### 上帝 Agent (God Agent)
- **觸發**：每日 00:00 ETL
- **職責**：宏觀劇情、世界參數守門 (±15%)、Quest 管理、矛盾仲裁
- **LLM**：雲端 M3 或本地 Qwen
- **參考**：`docs/PROMPTS/god_agent_prompt.md`

### 場景 Agent (Scene Agent)
- **觸發**：每輪玩家提交後
- **職責**：即時敘事 + 4 選項生成 + 態度選項
- **LLM**：雲端 M3
- **參考**：`docs/PROMPTS/scene_agent_prompt.md`

### 副 Agent (Sub Agent)
- **觸發**：每輪 + 場景 Agent 並行
- **職責**：細微事件 + 狀態計算 + 物理邏輯執行
- **LLM**：本地 Qwen
- **參考**：`docs/PROMPTS/sub_agent_prompt.md`

### 死亡 Narrator
- **觸發**：玩家角色死亡時
- **職責**：死亡場景 + 奪舍流程 + 異常快照
- **參考**：`docs/PROMPTS/death_narrator_prompt.md`

## 6. 玩家互動流程

```
[T+0:00]  玩家收到場景 + 4 選項
   ↓
[T+0:00 ~ 15:00]  玩家自由配置（態度、裝備、道具）
   ↓
[T+15:00]  玩家提交選擇
   ↓
[後端]  驗證選擇 → 物理邏輯鎖
   ↓
[場景 Agent]  生成新敘事 + 4 新選項
   ↓
[副 Agent]  計算狀態變化 + 細微事件
   ↓
[前端]  顯示新場景 + 新 4 選項
   ↓
[T+15:01]  下一輪開始
```

## 7. 語意狀態系統

### 角色狀態（Semantic Buckets）

| 維度 | 5 個 Bucket |
|------|------------|
| 體力 (stamina) | fresh → slight_breath → muscle_ache → exhausted → collapse |
| 健康 (health) | healthy → wounded → severely_wounded → dying → dead |
| 情緒 (morale) | elated → calm → neutral → anxious → despair |

**升降級規則：**
- ✅ 允許：±1 級平移
- ❌ 禁止：跳級
- 🔒 鎖死：collapse 不可逆
- ✅ 例外：安全環境 + 完整休息 → -2 級

## 8. 物理邏輯鎖 v2.0

**核心原則：唔 disable 玩家，保留意圖，演繹殘疾。**

當玩家狀態 vs 動作衝突時：
- ❌ 唔好改寫玩家選擇
- ✅ 將「物理限制」傳畀 LLM
- ✅ LLM 自由演繹「想做但做唔到」

**範例：**
```
玩家：[雙臂骨折]
意圖：「溫柔擁抱對方」
LLM：「你舉起雙手，劇痛令你停喺半空。眼淚無聲咁流落嚟。」
```

## 9. 死亡 + 奪舍機制

```
玩家 HP → collapse
   ↓
[God Agent] 確認死亡
   ↓
[Death Narrator] 生成死亡場景（200-500 字）
   ↓
[玩家選擇] 放棄 / 奪舍
   ↓
[奪舍] 70% 記憶保留 + 異常快照生成
   ↓
[新角色] 寫入 Profile
   ↓
[World Lore DB] 更新
```

## 10. MVP 範圍

**MVP-B：單玩家 1 小時自由探索**

成功標準：
- 玩家可以喺 1 個場景自由探索 1 小時
- 每 15 分鐘有 1 個選擇
- 4 個中性選項（無明顯利益/風險詞彙）
- 1-2 個態度組合
- 語意狀態正確更新
- 物理邏輯鎖正確觸發

## 11. 開發 Waves

| Wave | 名稱 | 預計時間 |
|------|------|---------|
| 1 | 核心引擎 | Month 1-3 |
| 2 | 世界觀載入 | Month 4-5 |
| 3 | LLM 內容生成 | Month 6-7 |
| 4 | 多人 + 異步 | Month 8-9 |
| 5 | 死亡 + 奪舍 | Month 10-12 |

## 12. 參考文檔

- [Schema 套件](SCHEMAS/)
- [Prompt 模板](PROMPTS/)
- [API 規格](API.md)
- [開發指南](DEVELOPMENT.md)
- [變更日誌](CHANGELOG.md)

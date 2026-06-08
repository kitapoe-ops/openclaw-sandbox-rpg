# 🎮 How to Play — OpenClaw Sandbox RPG

> **Audience:** Anyone who successfully ran the 5-command deploy from `QUICKSTART_LOCAL_DEPLOY.md` and now wants to start a game session.
> **Scope:** 1-4 players + up to 100 NPCs per scene.

---

## 🔄 故事生成與奪舍閉環 (The Narrative & Karma Loop)

在 OpenClaw Sandbox RPG 中，核心概念（網文套路、寫作鐵律、異步足跡、奪舍機制）全部串連起嚟，整個故事引擎嘅「閉環（Closed Loop）」其實係一個**「行為 → 改變 → 傳承 → 新行為」**嘅永動機。撇除所有技術細節，呢個閉環嘅完整運作畫面係咁樣嘅：

### 1. 【起點】：帶着「業力」降生
新玩家（或者剛剛死完重開嘅玩家）進入世界。佢嘅角色唔係一張白紙，系統會強行將**上一手玩家留低嘅「業力」或者「執念」**注入佢嘅背景設定。
*(例如：作為一個新兵，你無端端對酒館北面嗰口廢棄水井產生極度恐懼，因為上一手玩家啱啱死喺嗰度。)*

### 2. 【推動】：導演佈局（套路與痕跡的碰撞）
系統（導演）會將兩樣材料放入榨汁機：
- **網文套路庫：** 抽出一張劇本大綱（例如：【禍水東引】）。
- **世界真實痕跡：** 撈取其他非同步玩家啱啱做過嘅「好事」（例如：玩家 A 殺咗個商人，留低把斷劍）。
系統將兩者結合，交低一個核心指令：**「今集劇本係『禍水東引』，道具係『斷劍』，即刻開拍！」**

### 3. 【渲染】：極限施壓與抉擇（LLM 畫師發功）
LLM 收到指令，並嚴格遵守「禁用情緒詞」、「倒數計時器」、「微觀視角」三大寫作鐵律，渲染出一個充滿張力嘅場景：
*(「門外傳來急促的鐵甲碰撞聲。你腳邊躺着商人尚有餘溫的屍體，旁邊是一把不屬於你的斷劍。火把的光芒正從門縫底下一寸寸逼近。」)*
緊接著，逼出 4 個帶有**代價與風險**的網文選項（隱忍、反殺、嫁禍、逃遁）。

### 4. 【刻印】：無聲改寫世界
玩家從 4 個選項中作出抉擇並採取行動。玩家睇唔到嘅背後，系統嘅「守門人」會將呢個行動翻譯成冷冰冰嘅「世界參數改變」。
*(例如：商人狀態 = 已死；房間 = 滿地鮮血；守衛狀態 = 敵對。)*

### 5. 【分流】：生與死的終極判定
- **👉 情況 A（玩家存活）：** 玩家嘅行動製造咗新嘅「痕跡」，角色帶住新嘅道具同狀態，重新跌入**【推動】**階段，繼續抽下一個套路，進入下一 Round。
- **👉 情況 B（玩家死亡，觸發奪舍）：** 玩家因為選錯被守衛斬死。Game Over？唔係。玩家角色嘅死亡，正式成為呢個世界嘅「歷史事件」。佢死前嘅恐懼、仇恨，會被系統提取成新嘅「業力」。系統隨即創造一個全新角色（例如一個路過嘅拾荒者），將呢股「業力」塞入佢腦海，然後將佢掉返去**【起點】**。

#### 💡 點解呢個叫「真正嘅閉環」？
因為喺呢套系統入面，**沒有任何一次遊玩是孤立的，也沒有任何一次死亡是浪費的。**
- **世界參數閉環：** 你今日劈爛嘅一張檯，會成為聽日另一個玩家（甚至係你自己新角色）用嚟做掩護嘅爛木板。
- **敘事邏輯閉環：** 故事生成不需要無中生有，它只負責將「玩家 A 嘅破壞」+「網文套路」包裝成「玩家 B 嘅危機」。
- **生死輪迴閉環（奪舍）：** 死亡不再是終點（Ending），而係產生下一個故事動機（Motivation）嘅原料。

這就是整個 OpenClaw Sandbox RPG 的靈魂：**一個由無數玩家的屍體、痕跡和執念所驅動的無限故事機器。**

---

## 🕹️ 3 Steps to In-Game

### Step 1 — Pick your character (single-player quick start)

In your browser at `http://localhost:8000` (production) or `http://localhost:5173` (dev):

- The page loads the lobby / starter screen

- Pick your starting character card or click "創建角色" (Create Character)
- Fill in:
  - **Name:** anything
  - **Starter Character selection:** choose from the magic parchment cards (e.g. Aelar, Elara, etc.)


### Step 2 — Enter a scene

- Click "Start Adventure" or "Enter Scene"
- You'll spawn into a default scene (currently: `phandalin_town`, a D&D 5e starter town)
- The right panel shows:
  - **Scene description** (narrative story first line indented, enhanced font)
  - **Interactive actions & choice cards** (click to choose / expand attitude adjustments)
  - **Action input** (text box + submit for manual commands)

### Step 3 — Take your first action

Type something in the action input, for example:

```
我向 blacksmith 查詢鐵劍價錢
```

Then press Enter. The framework will:

1. Validate your action (`is_action_allowed` — physics lock check)
2. Generate narrative via the LLM (default: MockLLMClient, returns canned response)
3. Update your semantic state if needed (e.g. "tired" → "exhausted")
4. Save to Memory Palace (so next time you ask, the blacksmith remembers)
5. Broadcast to other connected players (if any)

**Your action result will appear in the right panel within 1-3 seconds.**

---

## 👥 1-4 Player Multiplayer

### Add more players

Each player opens `http://localhost:8000` (or `http://localhost:5173`) in a **separate browser window / tab**.

- Player 1 enters the lobby and joins
- Player 2 enters the lobby and joins (in a new tab)
- ... up to 4 players
- A WebSocket connects each player to the scene
- Actions are broadcast to all 4 players in real time

### Hard cap: 4 players

The 5th join attempt returns a 409 "scene_full" error. The framework is locked to 1-4 player scope.

---

## 🤖 NPC Interaction (up to 100 per scene)

- Each NPC has its own character state and Memory Palace
- Click on an NPC name to view their profile
- Use action verb + NPC name: `向 [NPC name] [action]`
- Example: `向 blacksmith 講: 你有什麼武器?`
- The NPC "remembers" past interactions (via Memory Palace recall)

### NPC dialogue arbitration

If 2 players ask the same NPC at the same time, the system uses **first-come-first-served** ordering via the async turn queue. The 2nd player sees a "NPC is currently busy" notice.

---

## 🧠 What Makes This Different from a Chatbot

| Feature | What it does |
|---------|--------------|
| **Persistent state** | Close the browser, come back tomorrow — your state survives |
| **Memory Palace** | Every NPC remembers past conversations (semantic recall) |
| **Soul transfer** | If your character dies, your soul can move to another vessel |
| **Pure-text semantic state** | No hidden HP/mana — state is "right hand fractured" or "very healthy", human-readable |
| **Real LLM** | Set `LLM_PROVIDER=minimax` env var for real MiniMax-M3 instead of mock |
| **R1 audit** | LM Studio on :1234 = real DeepSeek-R1-14B verifies actions before commit |

---

## 🎯 Quick Action Examples

```
# Movement
move north
go to the tavern

# Combat
attack the goblin
defend with shield

# Dialogue
talk to the innkeeper
ask the blacksmith about iron swords

# Item use
drink healing potion
equip leather armor

# State interaction
check my injuries
rest for the night
```

---

## 🛠️ Troubleshooting

| Symptom | Fix |
|---------|-----|
| Page shows "WebSocket offline" | Check backend is running on :8000 (`curl /health`) |
| NPC responses are canned (mock) | Set `LLM_PROVIDER=minimax` env var + `MINIMAX_API_KEY=...` then restart backend |
| Action rejected ("not allowed") | Physics lock check failed — try a different verb |
| Memory recall returns nothing | Your embedding was too different from when the memory was stored |
| Multiplayer says "scene full" | Only 4 players allowed; the 5th is hard-rejected |
| Browser shows CORS error | Access the SPA via `http://localhost:8000` (production) or `http://localhost:5173` (Vite) |


---

## 🔌 Under the Hood (for the curious)

When you click "Submit Action":

```
Browser  →  POST /api/action/process  →  ActionProcessor.process()
   │                                              │
   │                                              ├─→ validate (whitelist + state machine)
   │                                              ├─→ physics lock (per-character)
   │                                              ├─→ prompt_builder.build() (state always on top)
   │                                              ├─→ llm_client.generate_with_state_contract() (with retry)
   │                                              ├─→ state_machine.apply_mutations() (strict Pydantic)
   │                                              └─→ memory_palace.remember() (state anchor)
   │
   ←  {"status":"processed","narrative":"...","mutation":{...},"action_id":"..."}
```

---

## 🎯 Recommended First Session (5 minutes)

1. **Open** `http://localhost:8000` (or `http://localhost:5173` in dev)
2. **Select/Create** a character
3. **Enter** the Phandalin Town scene
4. **Type:** `look around`
5. **See** the scene description populate the right panel
6. **Click** on "Blacksmith" NPC
7. **Type:** `向 blacksmith 講: 你好`
8. **See** the blacksmith "respond" (with mock LLM: canned text; with real LLM: generated)
9. **Close** the tab
10. **Reopen** it 5 minutes later
11. **Click** on "Blacksmith" again
12. **Notice:** the blacksmith still remembers you (Memory Palace persistence)

That last step is the magic. Most RPGs forget everything on browser close. This one doesn't.

---

_This file was added 2026-06-05 after deployment verification confirmed the framework is locally runnable. See `QUICKSTART_LOCAL_DEPLOY.md` for the 5-command deploy._

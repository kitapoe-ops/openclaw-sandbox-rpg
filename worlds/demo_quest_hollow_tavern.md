# Demo Mini-Quest: 「老酒館嘅迴響」(Hollow Tavern's Echo)

> **Demo 範圍：** 3 個 scene，1 個迷你 story arc
> **目的：** 展示 World Lore DB + Scene Agent v2.0 + 4-vignette 機制
> **世界：** D&D 5e Forgotten Realms（待用戶填 worlds/dnd_5e_forgotten_realms.yaml）

---

## 背景設定

**時間：** 遊戲開始時間 = 1492 DR（災難後之年），秋季
**地點：** 劍灣 (Sword Coast) 嘅一個偏遠小鎮 — **石影鎮 (Stonehollow)**
**氛圍：** 戰後 30 年，百廢待興，但有啲嘢**唔啱**

**核心 Mystery：**
石影鎮嘅居民**集體失蹤**。唔係死——係**消失**。
最後一個目擊者話：「佢哋聽到咗酒館嘅音樂，然後就行咗入去，再冇出嚟。」

---

## Scene 1：老酒館 (loc_old_tavern) — 開始

### 環境描述

昏暗嘅木屋，煙草味同低語聲交織。火爐照亮斑駁嘅牆壁，牆上掛住褪色嘅家族肖像。
吧台後面，**老鐵匠 Gideon** 用粗糙嘅手抹咗抹吧台，佢嘅視線喺你腰間嘅匕首停咗一下。
角落有個**戴老花眼鏡嘅學者 Elara**，攤開咗一本古舊嘅書。
門口附近有個**受傷嘅旅人**，佢嘅呼吸有啲急促，斗篷下露出一角閃光。

### World Lore DB 引用

- `npc:npc_blacksmith_gideon` — 老鐵匠，有戰後創傷
- `npc:npc_scholar_elara` — 神秘學者，研究失蹤事件
- `npc:npc_injured_traveler` — 唯一倖存目擊者
- `location:loc_old_tavern` — 案發現場
- `item:item_gideons_locket` — 鐵匠嘅遺物，可能藏住線索
- `item:item_elaras_journal` — 學者嘅研究筆記
- `item:item_mysterious_flute` — 旅人身上嘅閃光物品
- `world_parameter:war_aftermath` = 2（戰後復甦緩慢）
- `world_parameter:social_unrest` = 1（社會動盪）
- `world_parameter:arcane_disturbance` = 1（魔法異常）

### Vignettes (Scene Agent v2.0 會生成)

預期 4 個 vignettes 覆蓋：
- **character_growth** — 鐵匠 Gideon's 過去（戰時經歷）
- **world_exploration** — 牆上地圖嘅變化（失蹤者去咗邊）
- **relationship** — 學者 Elara 嘅信任建立
- **mystery_revelation** — 旅人嘅神秘物品

### Branching Point：act1_branch_A

玩家揀完後，**下一個 scene 嘅入口**取決於玩家嘅選擇 + 態度：

| Vignette 維度 + 態度 | 下一個 Scene |
|---------------------|------------|
| character_growth + caution=careful | Scene 2a：鐵匠嘅閣樓 |
| character_growth + caution=bold | Scene 2b：鐵匠嘅夢魘 |
| world_exploration | Scene 2c：地圖室 |
| relationship | Scene 2d：學者嘅書房 |
| mystery_revelation | Scene 2e：旅人嘅秘密 |

---

## Scene 2a：鐵匠嘅閣樓 (loc_blacksmith_loft)

### 環境

Gideon 帶你上咗閣樓，呢度擺滿戰時嘅遺物 — 殘破嘅旗幟、生鏽嘅劍、褪色嘅信件。
閣樓角落有一個上鎖嘅木箱。

### World Lore DB 引用

- `npc:npc_blacksmith_gideon` — 揭示佢嘅戰時創傷
- `item:item_gideons_locket` — 內藏亡妻嘅肖像
- `item:item_war_letters` — 未寄出嘅信件
- `event:event_battle_of_silvermarsh` — 30年前嘅戰役

### Vignettes

- character_growth：木箱上嘅刻字
- world_exploration：窗戶望出去嘅石影鎮
- relationship：Gideon 嘅眼淚
- mystery_revelation：信件中提到嘅「音樂」

### Branching Point：act2a_branch_X

每個選擇導向 Scene 3 嘅唔同切入點。

---

## Scene 3：揭示 (loc_cellar) — 收尾

### 環境

最終場景。玩家根據之前嘅選擇到達**酒館嘅地窖**。
呢度係**失蹤事件嘅核心**。

### World Lore DB 引用

- `location:loc_tavern_cellar` — 神秘空間
- `npc:npc_arcane_echo` — 「迴響」嘅本體
- `item:item_mysterious_flute` — 召喚「迴響」嘅關鍵
- `event:event_the_dissolution` — 失蹤嘅真相

### Ending Options

| 先前選擇 | Ending |
|---------|--------|
| 鐵匠線 + 信任 | `ending_rescue` — 部分失蹤者被救回 |
| 學者線 + 合作 | `ending_seal` — 封印「迴響」，阻止更多失蹤 |
| 旅人線 + 智慧 | `ending_truth` — 理解失蹤本質，作出犧牲 |
| 任一線 + 忽視 NPC | `ending_lost` — 更多失蹤，世界崩壞 |

---

## 給 Scene Agent 嘅 Prompt 指引

### 必須遵守嘅 Vignette Pattern

每個 vignette 要：
- 30-50 字
- 引用至少 1 個 World Lore DB 實體
- 暗示方向但唔劇透結局
- 反映玩家狀態（體力/情緒/態度）

### 範例 Vignettes（參考）

**character_growth 維度：**
> 「你將缺口嘅匕首放低喺吧台，老鐵匠嘅視線停喺上面，佢粗糙嘅手微微抖咗一下。」

**world_exploration 維度：**
> 「牆上嘅地圖被重新繪過，幾個城鎮符號消失咗，但有個你冇見過嘅新符號。」

**relationship 維度：**
> 「老學者 Elara 推推眼鏡，佢將地圖上嘅某個位置指畀你，嘴唇微微動但冇出聲。」

**mystery_revelation 維度：**
> 「門口嘅旅人斗篷下嘅閃光節奏變咗，似係回應你嘅呼吸，佢嘅眼睛喺暗處反光。」

---

## 開發 To-Do

### 內容填充（由你 - 用戶 - 負責）
- [ ] 填寫 `worlds/dnd_5e_forgotten_realms.yaml` 完整內容
  - [ ] world_meta (name, version, description)
  - [ ] eternal.physical_rules
  - [ ] world_parameters (5 個)
  - [ ] attitude_dimensions (4 個)
  - [ ] npcs（5 敘事 + 5 功能 = 10 個）
  - [ ] items (20 個)
  - [ ] locations (5 個)
  - [ ] quests（1 主線 + 2 支線）

### 內容填充（由我 - 小B - 負責）
- [x] Quest 模板設計 ✅（本文件）
- [ ] 完整 quest JSON（act1-3 嘅 branching points）
- [ ] 5 個 starter characters JSON
- [ ] Starter 角色嘅 semantic profile

### 技術實作（由用戶 - 你 - 負責）
- [ ] backend/db.py 真實 SQLAlchemy
- [ ] backend/llm_client.py 真實 MiniMax M3
- [ ] backend/world_lore_loader.py LanceDB 整合
- [ ] frontend GameView 整合 WebSocket + Pinia

# 50 萬 Token 世界觀填充指南

> 目標：將 1 個世界（單一設定）嘅 YAML / JSON 內容擴展到 **50 萬 token**，等 LanceDB 可以 RAG 提取。

---

## 📊 50 萬 Token 嘅分配

| 類別 | Token 預算 | 深度標準 |
|------|----------|---------|
| 永恆層 (Eternal) | 5 萬 | 物理 / 魔法 / 社會規則嘅完整描述 |
| 世界參數 | 5 萬 | 10-15 個參數，每個 5 級 × 完整 prompt |
| 態度維度 | 2 萬 | 5 個維度，每個 4-5 級 × prompt |
| 種族 × 文化 | 8 萬 | 8-10 種族，每個 2000-5000 token |
| NPC 庫 | 15 萬 | **100-200 個 NPC**，每個 800-2000 token |
| 場景庫 | 10 萬 | **50-80 個場景**，每個 1000-3000 token |
| 物品庫 | 8 萬 | **200-300 件物品**，每個 200-500 token |
| Quest 模板 | 5 萬 | 30-50 條 quest，每個 1000-2000 token |
| 歷史事件 | 5 萬 | 50-100 個事件，每個 500-1000 token |
| 地理百科 | 5 萬 | 城市 / 區域 / 地標 / 危險區 |
| 語言 / 宗教 | 3 萬 | 多語詞彙、神祇系統 |
| **總計** | **~50 萬** | |

---

## 🔍 點樣寫到深？每個 section 嘅深度標準

### NPC（每個 800-2000 token）

**❌ 淺寫法（~200 token）：**
```yaml
- id: "npc_gundren"
  name: "Gundren"
  description: "矮人探險家"
  location: "凡達林"
```

**✅ 深寫法（~1500 token）：**
```yaml
- id: "npc_gundren"
  name: "Gundren Rockseeker"
  race: "Dwarf (Shield)"
  role: "Quest Giver / Missing Person"
  location: "loc_coneyberry_start"
  appearance: |
    強壯嘅盾矮人，留住紅銅色嘅辮子，穿住探險服裝，
    腰間有個防水皮袋裝住重要文件。
  personality: ["固執", "粗獷", "藏有秘密地圖", "對朋友極度忠誠"]
  background: |
    Gundren 係 Rockseeker 三兄弟嘅老二。
    佢同大哥 Tharden、弟弟 Nundro 一齊發現咗「失落礦坑」嘅位置。
    [完整 200-500 字背景故事]
  hidden_lore: "佢身上嘅地圖標示失落礦坑嘅最後入口。"
  relationships: { [完整關係圖] }
  dialogue_hooks: [可開啟嘅對話主題]
  narrative_tags: [敘事標籤]
  typical_responses: [典型反應 + 例句]
  knowledge_areas: [佢知道嘅嘢]
  secrets: [佢隱瞞嘅嘢]
  inventory_at_start: [初始物品]
  daily_routine: [每日作息]
```

**深度標準：每個 NPC 要有 12 個維度嘅內容：**

1. **基本資料** (id, name, race, role, location)
2. **外貌** (appearance, 100-200 字具體描述)
3. **性格** (5-7 個關鍵詞 + 描述)
4. **背景** (300-500 字完整故事)
5. **隱藏 lore** (玩家發掘嘅秘密)
6. **關係網** (與其他 NPC 嘅關係)
7. **對話主題** (5-10 個可開啟嘅話題)
8. **敘事標籤** (用嚟觸發 LLM 嘅 hint)
9. **典型反應** (3-5 個常見反應 + 例句)
10. **知識領域** (佢知道咩)
11. **秘密** (佢隱瞞咩)
12. **物品 / 作息** (initial inventory, daily routine)

### 場景（每個 1000-3000 token）

**❌ 淺寫法（~150 token）：**
```yaml
- id: "loc_tavern"
  name: "酒館"
  description: "一個酒館"
```

**✅ 深寫法（~2500 token）：**
```yaml
- id: "loc_sleeping_giant_taphouse"
  name: "沉睡巨人酒館 (Sleeping Giant Taphouse)"
  type: "building"
  parent_location: "loc_phandalin_town"
  description: |
    [500-1000 字詳細描述：歷史、佈局、氣氛、危險點]
  safe_zone: false
  environment_tags: [6-10 個環境標籤]
  interactables:
    - [可互動物件，每個有 100-200 字描述]
  npcs_present: [NPC 列表]
  atmosphere: "ominous"
  ambient_sounds: [環境聲]
  first_visit_narrative: |
    [200-400 字首次拜訪敘事]
  history: [場景歷史]
  hidden_rooms: [秘密房間]
  traps: [陷阱]
  treasures: [寶藏]
  political_control: [政治控制]
  economic_activities: [經濟活動]
```

**深度標準：15 個維度**

### 物品（每個 200-500 token）

**❌ 淺寫法：**
```yaml
- id: "item_sword"
  name: "劍"
  description: "一把劍"
```

**✅ 深寫法：**
```yaml
- id: "item_glasstaff_spectacles"
  name: "Glasstaff 嘅魔法眼鏡"
  type: "magic"
  description: |
    [200-300 字：外觀、材質、來源、特殊效果]
  interaction_patterns: [5-8 種互動方式]
  rarity: "rare"
  narrative_tags: [3-5 個敘事標籤]
  attunement_requirements: [附魔條件]
  daily_uses: [每日可用次數]
  weight: [重量]
  value: [價值]
  history: [物品歷史]
  lore_connections: [與其他 lore 嘅關聯]
```

---

## 🧠 點樣用 AI 加速填充

呢個項目可以用 AI 幫手寫，但**要用人審查**。建議流程：

### 1. **種子清單**（手動，1-2 日）
列出每個 section 嘅核心實體 ID + 名字，例如：
```
NPC 種子 (200 個):
- npc_gundren
- npc_halia
- npc_redbrand_leader
- npc_tharden_rockseeker
...
```

### 2. **批次生成**（AI，3-5 日）
用 LLM 為每個種子生成完整 YAML 內容：
```
Prompt: 
"為以下 NPC 生成完整 YAML，每個 1500-2000 token。
 NPC ID: npc_xxx
 Name: xxx
 設定: [世界背景 500 字]
 請生成 appearance, personality, background (300-500 字),
 hidden_lore, relationships, dialogue_hooks 等 12 個維度。"
```

### 3. **一致性檢查**（手動 + AI，1-2 日）
- 所有 NPC 嘅 location ID 都要喺 locations 入面
- 所有物品嘅 lore_source ID 要互相對應
- 所有 quest 嘅 trigger 都要可達

### 4. **RAG chunking**（自動，1 日）
- 將 50 萬 token YAML 切成 ~500 token chunk
- 用 LanceDB 建立向量索引
- 測試 top-5 retrieval 質素

---

## 🎯 50 萬 Token ≠ 全部載入 Context

**LanceDB RAG 嘅運作：**
```
Player query: "凡達林嘅酒館有咩？"
   ↓
LanceDB 檢索：top-5 chunks (~2500 tokens)
   ↓
注入 Scene Agent prompt:
  - 永恆規則 (selected chunks, ~500 tokens)
  - 場景: loc_sleeping_giant_taphouse 完整 (~2000 tokens)
  - 附近 NPC: npc_redbrand_ringleader 簡卡 (~500 tokens)
  - 附近物品: item_redbrand_mask (~200 tokens)
   ↓
Total context: ~3200 tokens (per LLM call)
   ↓
Output: scene_narrative + 4 vignettes (~600 tokens)
```

**所以 50 萬 token 唔係「每次 call 都用晒」，而係「需要時精準提取」。**

---

## 📊 預估完成時間

假設每日寫 2-3 個完整 NPC（1500 token × 2 = 3000 token）：

| 任務 | 工作量 | 時間 |
|------|--------|------|
| 200 個 NPC | 400,000 token | 30-40 日（手動）/ 3-5 日（AI 加速）|
| 80 個場景 | 200,000 token | 15-20 日 / 2-3 日 |
| 300 件物品 | 120,000 token | 10-15 日 / 2 日 |
| 50 條 Quest | 100,000 token | 8-10 日 / 1-2 日 |
| 100 個事件 | 80,000 token | 5-8 日 / 1 日 |
| **總計** | **~900K token** | **~70-100 日 / ~10-12 日** |

**注意：** 唔需要 50 萬 token = 100% 滿。**MVP 階段可以 100K-200K token 就夠 demo**。

---

## 🎬 而家項目嘅狀態

✅ `worlds/dnd_5e_forgotten_realms.yaml` 已經擴展到 ~25K token（我嘅版本）
- 完整結構範本
- 10 個核心 NPC（每個 ~1500 token）
- 6 個核心場景（每個 ~2500 token）
- 5 個核心物品（每個 ~400 token）
- 完整 world_parameters / attitude_dimensions / semantic_states

🚧 **待你擴展：**
- 加多 100+ 個 NPC
- 加多 40+ 個場景
- 加多 250+ 件物品
- 加多 30+ 條 Quest
- 加多 50+ 個事件

---

## 💡 加速提示

### 用我嘅 `scenes_agent_prompt.md` v2.0 反向生成
- 用 Scene Agent 嘅 prompt 風格，批量生成 NPC 描述
- 保持 tone / structure 一致

### 建立 `NPC 模板` yaml snippet
```yaml
# Standard NPC template
- id: "npc_xxx"
  name: ""
  race: ""
  role: ""
  location: ""
  appearance: |
    [200 字]
  personality: []
  background: |
    [300-500 字]
  # ... 其他維度
```

然後複製 + 改 ID + 填內容。

### 從 D&D 5e 官方 SRD 提取
- D&D 5e SRD 5.1 公開版（OGL / CC）
- 大量預設 NPC、怪物、魔法物品
- 改寫成語意狀態機格式即可

---

## 🛠️ 我哋嘅 next step

1. **MVP 階段先填 100K token**（足夠 demo）：
   - 20 個核心 NPC
   - 15 個核心場景
   - 50 件核心物品
   - 5 條主線 Quest

2. **完整階段再填到 500K token**（完整世界觀）

3. **LanceDB chunking + RAG 自動完成**（backend 任務）

---

**記住：50 萬 token 係目標，唔係 deadline。** MVP 先做 20%，完整版做 100%。

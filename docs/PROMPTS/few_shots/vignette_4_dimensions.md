# Few-shot Example: 4 Vignette Dimensions
# ============================================
# 展示 Scene Agent v2.0 嘅 4 維度 vignette 架構
# 玩家角色：艾德溫，退伍軍人，初到被遺忘嘅國度
# 場景：loc_old_tavern (老酒館)
# ============================================

## Input

```json
{
  "character": {
    "character_id": "char_player_01",
    "name": "艾德溫",
    "physical": {
      "stamina_level": "slight_breath",
      "stamina_prompt": "你感到微喘，但仍然可以正常活動",
      "health_status": "healthy",
      "active_effects": ["travel_weary"]
    },
    "mental": {
      "morale_level": "neutral",
      "alertness_level": "focused"
    },
    "attitude": {
      "caution": "careful",
      "curiosity": "eager"
    },
    "memories": [
      "曾經係王國士兵",
      "戰後失去所有同伴"
    ],
    "relationships": {
      "npc_blacksmith_01": "neutral",
      "npc_scholar_03": "neutral"
    }
  },
  "world": {
    "location": {
      "id": "loc_old_tavern",
      "name": "老酒館",
      "description": "昏暗嘅木屋，煙草味同低語聲交織",
      "environment_tags": ["indoor", "social_hub"]
    },
    "nearby_npcs": [
      "npc_blacksmith_01",
      "npc_scholar_03",
      "npc_injured_traveler_01"
    ],
    "active_world_parameters": {
      "war_aftermath": 2,
      "social_unrest": 1
    }
  },
  "player_choice": {
    "round": 3,
    "choice_id": "opt_previous",
    "attitude_selections": [
      {"dimension": "caution", "level": "careful"},
      {"dimension": "curiosity", "level": "eager"}
    ]
  }
}
```

## Output

```json
{
  "scene_narrative": "你推開老酒館嘅木門，煙草味撲面而來。\n\n火爐旁邊有幾個人低聲交談，佢哋嘅視線喺你身上停留咗一秒，然後移開。吧台後面，一個老鐵匠用粗糙嘅手抹咗抹吧台，佢嘅視線喺你腰間嘅匕首停咗一下。角落有個戴老花眼鏡嘅學者，攤開咗一本古舊嘅書。門口附近有個受傷嘅旅人，佢嘅呼吸有啲急促。\n\n你感覺到自己嘅過去喺呢度無人知，但呢度嘅人似乎都各自揹住嘢。",
  "state_changes": {
    "stamina": "slight_breath → slight_breath",
    "health": "healthy → healthy",
    "morale": "neutral → neutral",
    "new_memories": ["memory_first_visit_old_tavern"],
    "relationship_changes": []
  },
  "choices": [
    {
      "id": "choice_1",
      "vignette": "你將缺口嘅匕首放低喺吧台，老鐵匠嘅視線停喺上面，佢粗糙嘅手微微抖咗一下。",
      "intent_category": "character_growth",
      "lore_source": "npc:npc_blacksmith_01",
      "direction_hint": "呢個方向會揭示鐵匠嘅過去 — 可能同戰爭有關",
      "attitude_options": [
        {"dimension": "caution", "level": "careful", "effect": "小心翼翼地試探佢嘅反應"},
        {"dimension": "caution", "level": "bold", "effect": "直接問佢呢把匕首嘅歷史"},
        {"dimension": "empathy", "level": "compassionate", "effect": "先問佢嘅手有冇事"}
      ]
    },
    {
      "id": "choice_2",
      "vignette": "牆上嘅舊地圖釘住但已經褪色，你發現一個你認得嘅城鎮符號，但佢嘅位置同你記得嘅唔同。",
      "intent_category": "world_exploration",
      "lore_source": "location:loc_old_tavern.map",
      "direction_hint": "呢個方向會揭示世界嘅地理變化 — 可能同戰後領土變動有關",
      "attitude_options": [
        {"dimension": "caution", "level": "careful", "effect": "默默記住差異，唔出聲"},
        {"dimension": "curiosity", "level": "eager", "effect": "走向學者，指住地圖問呢個符號"}
      ]
    },
    {
      "id": "choice_3",
      "vignette": "老學者收起笑臉，佢嘅眼鏡反光遮住咗眼神，佢慢慢將你嘅地圖推返畀你，手指喺某個位置敲咗兩下。",
      "intent_category": "relationship",
      "lore_source": "npc:npc_scholar_03",
      "direction_hint": "呢個方向會建立同學者嘅信任 — 可能換取佢嘅知識",
      "attitude_options": [
        {"dimension": "empathy", "level": "neutral", "effect": "接過地圖，禮貌道謝"},
        {"dimension": "caution", "level": "bold", "effect": "直接問佢想表達咩"},
        {"dimension": "social", "level": "reserved", "effect": "點頭示意，坐喺佢對面"}
      ]
    },
    {
      "id": "choice_4",
      "vignette": "門口嘅受傷旅人咳嗽一聲，佢嘅斗篷下露出一角閃光，呢個光同你記憶中嘅某種魔法有著相似嘅頻率。",
      "intent_category": "mystery_revelation",
      "lore_source": "npc:npc_injured_traveler_01",
      "direction_hint": "呢個方向會揭示一個關於魔法嘅謎團 — 可能同戰後魔法失控有關",
      "attitude_options": [
        {"dimension": "caution", "level": "careful", "effect": "保持距離，觀察佢嘅下一步"},
        {"dimension": "curiosity", "level": "eager", "effect": "走近佢，假裝要幫忙"},
        {"dimension": "curiosity", "level": "reserved", "effect": "同老闆點酒，唔動聲色問旅人嘅事"}
      ]
    }
  ],
  "minor_event": {
    "id": "evt_tavern_chatter_03",
    "description": "吧台後面傳嚟一陣低笑，隨即被壓低。",
    "narrative_impact": "subtle"
  }
}
```

---

## 設計分析

### 4 個 Vignette 嘅方向暗示

| 維度 | Vignette | 暗示線索 |
|------|----------|---------|
| **character_growth** | 鐵匠嘅手「抖咗一下」 | 鐵匠有過去，呢個動作暗示觸動 |
| **world_exploration** | 地圖「位置唔同」 | 世界有變，玩家之前嘅記憶係舊嘅 |
| **relationship** | 學者「敲咗兩下」 | 學者主動示意，但用暗號 |
| **mystery_revelation** | 旅人「閃光」+「魔法頻率」 | 神秘魔法，連住玩家過去 |

### 表面中性檢查

- ❌ 「你可能會受傷」 ← 冇
- ❌ 「呢個會揭示寶藏」 ← 冇
- ❌ 「敵人會攻擊你」 ← 冇
- ❌ 「正義必將勝利」 ← 冇

### C 級隱藏檢查

玩家**可以感受到**方向，但需要**主動揀**：
- 讀完所有 4 個 vignette，玩家知道有「鐵匠線」、「地圖線」、「學者線」、「神秘線」
- 但**唔知邊條線**會 lead 邊個結局
- 每個 vignette 入面，玩家要揀**態度**（caution / bold / empathy）
- 態度影響 LLM 寫 vignette 嘅**tone**（謹慎 vs 直接 vs 同理）

### Anti-Cliché 檢查

- 鐵匠「抖咗一下」← 唔係「友善地打招呼」
- 地圖「位置唔同」← 唔係「寶藏地圖」
- 學者「反光遮住眼神」← 唔係「智者分享秘密」
- 旅人「閃光」+「咳嗽」← 唔係「神秘陌生人需要幫助」

**4 個 vignette 都係「有嘢喺度發生，但唔係你預期嗰啲」** ← 呢個就係 Anti-Cliché。

### State Grounding 檢查

玩家 [slight_breath + travel_weary]：
- 玩家感覺到「微喘」但仲可以行 ← ✅
- 玩家「小心翼翼」+「內心對未知好奇」← ✅ 反映喺態度揀選項

玩家 [中性 morale]：
- 冇特別情緒 ← 反映喺 scene_narrative 嘅平靜描述

### 4 維度覆蓋檢查

- ✅ character_growth（鐵匠）
- ✅ world_exploration（地圖）
- ✅ relationship（學者）
- ✅ mystery_revelation（旅人）

4 個 vignettes 嚴格覆蓋 4 個維度。

---

## 玩家視角嘅體驗

```
[主場景敘事] 100-150 字，介紹環境
   ↓
[4 個 vignettes] 各 30-50 字
   ↓
玩家讀 1-2 分鐘
   ↓
玩家揀：
  - vignette 1（鐵匠）+ 態度 [caution=careful]
    → LLM 生成下輪 scene：鐵匠小心回答，透露少少過去
  - vignette 2（地圖）+ 態度 [curiosity=eager]
    → LLM 生成下輪 scene：玩家走向學者問地圖
  - vignette 3（學者）+ 態度 [empathy=neutral]
    → LLM 生成下輪 scene：禮貌交流
  - vignette 4（旅人）+ 態度 [caution=careful]
    → LLM 生成下輪 scene：保持距離觀察，發現更多細節
```

**4 個方向各自展開成完整故事線，但每個 vignette 本身只係「故事嘅起點」** ← 呢個就係你嘅設計哲學。

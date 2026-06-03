# Few-shot Example: Social Scene
# ============================================
# 範例：NPC 友善對話
# ============================================

## Input

```json
{
  "character": {
    "character_id": "char_player_01",
    "name": "艾德溫",
    "physical": {
      "stamina_level": "fresh",
      "health_status": "healthy",
      "active_effects": ["well_rested"]
    },
    "mental": {
      "morale_level": "neutral",
      "alertness_level": "focused"
    },
    "attitude": {
      "empathy": "compassionate",
      "caution": "neutral"
    },
    "inventory": {
      "items": [{"item_id": "item_healing_potion", "quantity": 2}],
      "equipment": {"weapon": "item_iron_dagger"}
    }
  },
  "world": {
    "location": {
      "id": "loc_old_tavern",
      "name": "老酒館",
      "atmosphere": "peaceful"
    },
    "nearby_npcs": ["npc_injured_traveler_01"],
    "time": "夜晚",
    "weather": "大雨"
  },
  "player_choice": {
    "option_id": "opt_02",
    "attitude_selections": [
      {"dimension": "empathy", "level": "compassionate"}
    ]
  }
}
```

## Output

```json
{
  "round": 12,
  "character_id": "char_player_01",
  "narrative": "你行到角落，喺受傷嘅旅人面前跪低。\n\n佢抬起頭望住你——雙眼充滿疲憊，但仲有一絲警覺。雨水從佢濕透嘅斗篷滴落，喺木地板上形成細小嘅水窪。\n\n「你⋯⋯你係邊個？」佢嘅聲音沙啞。\n\n你冇即刻回答。你留意到佢嘅左臂用布條紮住，但布條已經被血浸透。佢嘅嘴唇發白，身體微微發抖。\n\n「我冇惡意。」你輕聲講。\n\n你從背包攞出一瓶治療藥水，遞向佢。\n\n佢望住你嘅手，望住嗰瓶藥水。佢嘅警覺慢慢消退。\n\n「⋯⋯多謝。」佢伸出顫抖嘅手，接過藥水。\n\n酒館嘅其他人繼續飲緊酒，冇人注意到呢個角落發生嘅事。雨聲掩蓋住佢飲藥水時嘅咳嗽。\n\n你唔知道呢個人係邊個，從邊度嚟。但你知道，今晚佢至少安全。",
  "state_changes": {
    "stamina": {
      "old": "fresh",
      "new": "fresh",
      "reason": "僅係社交互動"
    },
    "health": {
      "old": "healthy",
      "new": "healthy"
    },
    "morale": {
      "old": "neutral",
      "new": "calm",
      "reason": "幫助他人，感受到平靜"
    },
    "items_consumed": [
      {"item_id": "item_healing_potion", "quantity": 1}
    ],
    "new_memories": [
      "memory_met_injured_traveler",
      "memory_traveler_left_arm_wounded"
    ],
    "relationship_changes": [
      {"npc_id": "npc_injured_traveler_01", "old": "wary", "new": "grateful"}
    ]
  },
  "choices": [
    {
      "id": "opt_01",
      "lore_source": "npc:npc_injured_traveler_01",
      "text": "【NPC】詢問佢點解會受傷",
      "intent_category": "npc_interaction",
      "attitude_options": [
        {"dimension": "empathy", "level": "compassionate", "effect": "先關心佢嘅傷勢，再問"},
        {"dimension": "caution", "level": "careful", "effect": "保持距離，直接問重點"}
      ]
    },
    {
      "id": "opt_02",
      "lore_source": "location:loc_old_tavern.fireplace",
      "text": "【環境】幫佢搵個近火爐嘅位置休息",
      "intent_category": "environment",
      "attitude_options": [
        {"dimension": "empathy", "level": "compassionate", "effect": "小心扶佢過去"},
        {"dimension": "caution", "level": "neutral", "effect": "指個方向俾佢自己去"}
      ]
    },
    {
      "id": "opt_03",
      "lore_source": "item:item_dry_rations",
      "text": "【物品】分享你嘅乾糧",
      "intent_category": "item_interaction",
      "attitude_options": [
        {"dimension": "empathy", "level": "compassionate", "effect": "默默遞上"},
        {"dimension": "social", "level": "talkative", "effect": "邊傾偈邊遞"}
      ]
    },
    {
      "id": "opt_04",
      "lore_source": "system:delay",
      "text": "【等待】留喺度陪伴佢，等佢恢復",
      "intent_category": "delay",
      "attitude_options": [
        {"dimension": "empathy", "level": "compassionate", "effect": "默默守護"},
        {"dimension": "caution", "level": "careful", "effect": "保持警覺，注意酒館其他人"}
      ]
    }
  ],
  "minor_event": {
    "id": "evt_fire_crackle_12",
    "description": "火爐中嘅木柴爆裂，迸出幾點火星。",
    "narrative_impact": "subtle"
  },
  "physics_lock_violations": []
}
```

## Notes

**重點：**

1. **NPC 對話風格：**
   - 旅人：警覺但脆弱（沙啞聲、顫抖手）
   - 玩家：溫柔但唔過度熱情
   - 對白簡短（唔係好萊塢式長對話）

2. **態度演繹（empathy: compassionate）：**
   - 「你冇即刻回答」
   - 「你輕聲講」
   - 「你從背包攞出」
   - 所有動作都係溫柔嘅

3. **感官細節：**
   - 視覺：濕透嘅斗篷、血浸透嘅布條、發白嘅嘴唇
   - 聽覺：雨聲、沙啞聲、咳嗽
   - 觸覺：水窪、顫抖

4. **物品使用：**
   - 玩家主動用 `item_healing_potion`（input 標明）
   - 寫入 `items_consumed`

5. **關係變化：**
   - `wary` → `grateful`
   - 寫入 `relationship_changes`

6. **記憶新增：**
   - 見過呢個 NPC
   - 記得佢嘅傷勢（為日後伏筆）

7. **情緒變化：**
   - `neutral` → `calm`（幫助他人嘅內心平靜）

8. **4 選項設計：**
   - 全部圍繞呢個 NPC
   - 全部唔會立即有「利益」
   - 全部可以延伸出唔同故事線

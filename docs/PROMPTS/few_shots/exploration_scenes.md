# Few-shot Example: Exploration Scene
# ============================================
# 範例：探索廢墟場景
# ============================================

## Input

```json
{
  "character": {
    "character_id": "char_player_01",
    "name": "艾德溫",
    "physical": {
      "stamina_level": "slight_breath",
      "stamina_prompt": "剛完成短途行軍，呼吸略為急促但仍可正常活動",
      "health_status": "healthy",
      "active_effects": ["well_fed", "cautious"]
    },
    "mental": {
      "morale_level": "calm",
      "alertness_level": "focused"
    },
    "attitude": {
      "caution": "careful",
      "empathy": "neutral"
    },
    "inventory": {
      "items": [{"item_id": "item_dry_rations", "quantity": 3}, {"item_id": "item_water_skin", "quantity": 1}],
      "equipment": {"weapon": "item_iron_dagger", "armor": "item_leather_vest"}
    }
  },
  "world": {
    "location": {
      "id": "loc_ruined_temple",
      "name": "古老神殿廢墟",
      "description": "一座被藤蔓吞噬嘅石造神殿，半塌嘅圓頂露出天空",
      "atmosphere": "mysterious"
    },
    "nearby_npcs": [],
    "time": "黃昏",
    "weather": "微風，烏雲密佈",
    "active_world_parameters": {
      "ancient_mystery": 3,
      "divine_blessing": 1
    }
  },
  "player_choice": {
    "option_id": "opt_01",
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
  "round": 5,
  "character_id": "char_player_01",
  "narrative": "你踏入神殿廢墟，腳下嘅石板發出清脆嘅回聲。\n\n黃昏嘅光線從半塌嘅圓頂灑落，照亮浮塵喺空氣中緩緩飄動。藤蔓從裂縫中伸入，像綠色嘅血管咁攀附住石柱。空氣中有一種古老嘅氣味——塵土、苔蘚，同埋某種你形容唔到嘅、甜膩嘅芳香。\n\n你嘅視線掃過四周。牆壁上殘留住褪色嘅壁畫，依稀可見某種儀式嘅場景——但細節已經被時間磨蝕。石製嘅祭壇仲喺度，上面放住一個倒落嘅銅碗，碗內積滿雨水。\n\n風從圓頂嘅缺口吹入，帶有遠方嘅雷聲。天色更暗咗。\n\n你感受到呢度曾經有過神聖嘅力量，但而家只剩下寂靜。\n\n[場景 Agent 觀察：玩家態度係 careful + eager，代表佢想探索但保持警覺。我用咗「視線掃過」、「感受到」等詞語反映 cautious 嘅態度，同時用「依稀可見」、「空氣中嘅芳香」等細節滿足 eager 嘅好奇心。]",
  "state_changes": {
    "stamina": {
      "old": "slight_breath",
      "new": "slight_breath",
      "reason": "僅係探索，無體力消耗"
    },
    "health": {
      "old": "healthy",
      "new": "healthy",
      "reason": "無受傷"
    },
    "morale": {
      "old": "calm",
      "new": "calm",
      "reason": "環境平靜"
    },
    "items_consumed": [],
    "new_memories": [
      "memory_ruined_temple_layout",
      "memory_ancient_fresco_ritual"
    ]
  },
  "choices": [
    {
      "id": "opt_01",
      "lore_source": "location:loc_ruined_temple.altar",
      "text": "【物品】翻查祭壇上嘅銅碗，檢查入面嘅水",
      "intent_category": "item_interaction",
      "attitude_options": [
        {"dimension": "caution", "level": "careful", "effect": "用樹枝撩動水面，唔直接接觸"},
        {"dimension": "caution", "level": "bold", "effect": "直接用手撈起水檢查"},
        {"dimension": "curiosity", "level": "eager", "effect": "先聞一聞，再嘗試飲"}
      ]
    },
    {
      "id": "opt_02",
      "lore_source": "location:loc_ruined_temple.fresco",
      "text": "【環境】靠近牆壁，仔細觀察褪色嘅壁畫",
      "intent_category": "environment",
      "attitude_options": [
        {"dimension": "caution", "level": "careful", "effect": "保持距離，僅用視覺觀察"},
        {"dimension": "curiosity", "level": "eager", "effect": "用手觸摸壁畫表面，嘗試感受質感"}
      ]
    },
    {
      "id": "opt_03",
      "lore_source": "npc:npc_scholar_03",
      "text": "【NPC】向遠方嘅老學者請教呢座神殿嘅歷史",
      "intent_category": "npc_interaction",
      "attitude_options": [
        {"dimension": "empathy", "level": "compassionate", "effect": "先問佢身體狀況，再問歷史"},
        {"dimension": "caution", "level": "bold", "effect": "直接問重點，唔囉嗦"}
      ]
    },
    {
      "id": "opt_04",
      "lore_source": "system:delay",
      "text": "【等待】喺神殿入面紮營，等待黎明再探索",
      "intent_category": "delay",
      "attitude_options": [
        {"dimension": "caution", "level": "timid", "effect": "選擇最安全嘅位置過夜"},
        {"dimension": "curiosity", "level": "eager", "effect": "選擇能觀察到壁畫嘅位置"}
      ]
    }
  ],
  "minor_event": {
    "id": "evt_wind_gust_05",
    "description": "一陣強風吹過，藤蔓沙沙作響，某處有石屑掉落。",
    "narrative_impact": "subtle"
  },
  "physics_lock_violations": []
}
```

## Notes

**點解咁樣生成：**

1. **敘事長度（~400 字）：** 達到最低要求 200 字，提供足夠感官細節但唔會悶親玩家

2. **感官細節覆蓋：**
   - 視覺：黃昏光線、浮塵、藤蔓、壁畫
   - 聽覺：腳步回聲、風聲、雷聲
   - 嗅覺：塵土、苔蘚、甜膩芳香
   - 觸覺：石板、風（隱含）

3. **態度演繹：**
   - `caution: careful` → 「視線掃過」、「感受到寂靜」
   - `curiosity: eager` → 細節豐富（壁畫、銅碗、雨水）

4. **狀態變化：**
   - 探索無體力消耗
   - 新增 2 條記憶（場景佈局、儀式壁畫）

5. **4 選項覆蓋：**
   - 物品互動（銅碗）— 3 個態度
   - 環境觀察（壁畫）— 2 個態度
   - NPC 互動（老學者）— 2 個態度
   - 等待延遲（紮營）— 2 個態度

6. **無明顯利益 / 風險詞彙：**
   - 冇「寶藏」、「獎勵」字眼
   - 冇「死亡」、「陷阱」字眼
   - 4 個選項表面價值相等

7. **世界參數反映：**
   - `ancient_mystery: 3` → 壁畫、祭壇、神秘芳香
   - `divine_blessing: 1` → 微弱嘅神聖感（「曾經有過神聖嘅力量」）

8. **細微事件：** 風聲 + 石屑掉落，營造黃昏 + 雷暴嘅氛圍

9. **Lore Source 標記：** 4 個選項全部有具體來源

10. **語言風格：** 繁體中文香港口語化，第二人稱「你」，留白適度

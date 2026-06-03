# Few-shot Example: Combat Scene
# ============================================
# 範例：戰鬥敘事（含物理邏輯鎖殘疾演繹）
# ============================================

## Input

```json
{
  "character": {
    "character_id": "char_player_01",
    "name": "艾德溫",
    "physical": {
      "stamina_level": "muscle_ache",
      "stamina_context": "post_long_march",
      "health_status": "broken_left_arm",
      "active_effects": ["exhausted", "broken_left_arm"]
    },
    "mental": {
      "morale_level": "anxious",
      "alertness_level": "sharp"
    },
    "attitude": {
      "aggression": "defensive",
      "conviction": "steady"
    },
    "inventory": {
      "items": [],
      "equipment": {
        "weapon": "item_iron_dagger",
        "armor": "item_leather_vest"
      }
    }
  },
  "world": {
    "location": {
      "id": "loc_ambush_path",
      "name": "山路小徑",
      "atmosphere": "tense"
    },
    "nearby_npcs": ["npc_bandit_01", "npc_bandit_02"],
    "time": "黃昏",
    "weather": "陰天，無風"
  },
  "player_choice": {
    "option_id": "opt_combat_01",
    "attitude_selections": [
      {"dimension": "aggression", "level": "defensive"},
      {"dimension": "conviction", "level": "steady"}
    ]
  }
}
```

## Output

```json
{
  "round": 8,
  "character_id": "char_player_01",
  "narrative": "兩個蒙面人影從樹叢後撲出。\n\n第一個揮刀斬向你嘅頭部。\n\n你本能地舉起右臂擋格——但你嘅左臂仲吊喺繃帶上，完全幫唔上。鐵刀砍中你嘅前臂，痛楚從手腕一路燒上膊頭。\n\n[物理邏輯鎖觸發：玩家揀「雙手擋格」但左臂骨折 → 自動演繹為單手擋格，並產生後果]\n\n你咬住牙，用僅有嘅右手抓實匕首。\n\n「退後！」你嗌。\n\n但你嘅聲音喺黃昏嘅山路上顯得單薄。\n\n第二個山賊從側面撲嚟。你轉身想避開——但你嘅左腳踩空，膝蓋撞上石頭。整個人失去平衡，半跪喺地。\n\n你嘅左臂傳嚟劇痛。\n\n你望住嗰兩個山賊慢慢迫近。\n\n你嘅肌肉在尖叫，你嘅骨頭在呻吟。但你嘅眼神仲係清醒。\n\n「我唔會就咁死。」你對自己講。\n\n[場景 Agent 觀察：玩家態度 defensive + steady，代表佢想防守但唔放棄。我用咗「本能地舉起」、「咬住牙」、「眼神仲係清醒」等詞語反映呢種態度。]\n\n山賊互相望咗一眼，笑咗起嚟。\n\n「又一個走投無路嘅。」第一個講。\n\n你慢慢企起身，雖然左臂劇痛，雖然膝蓋在流血。",
  "state_changes": {
    "stamina": {
      "old": "muscle_ache",
      "new": "exhausted",
      "reason": "戰鬥 + 受傷 -2 級"
    },
    "health": {
      "old": "broken_left_arm",
      "new": "broken_left_arm_and_wounded_knee",
      "reason": "戰鬥中受新傷 -1 級"
    },
    "morale": {
      "old": "anxious",
      "new": "anxious",
      "reason": "面對壓倒性敵人，無改善但亦未崩潰"
    },
    "items_consumed": [],
    "new_memories": [
      "memory_ambush_by_two_bandits",
      "memory_left_arm_blocks_failed"
    ]
  },
  "choices": [
    {
      "id": "opt_01",
      "lore_source": "npc:npc_bandit_01",
      "text": "【戰鬥】集中攻擊第一個山賊",
      "intent_category": "item_interaction",
      "attitude_options": [
        {"dimension": "aggression", "level": "aggressive", "effect": "全力一擊，唔理後果"},
        {"dimension": "aggression", "level": "defensive", "effect": "試圖找機會刺傷就跑"},
        {"dimension": "conviction", "level": "steady", "effect": "冷靜等待時機"}
      ]
    },
    {
      "id": "opt_02",
      "lore_source": "npc:npc_bandit_leader_05",
      "text": "【NPC】大聲呼叫附近嘅守衛",
      "intent_category": "npc_interaction",
      "attitude_options": [
        {"dimension": "conviction", "level": "steady", "effect": "冷靜呼救，描述位置"},
        {"dimension": "aggression", "level": "aggressive", "effect": "大聲威嚇山賊，話有埋伏"}
      ]
    },
    {
      "id": "opt_03",
      "lore_source": "location:loc_ambush_path.terrain",
      "text": "【環境】利用地形——滾落斜坡逃脫",
      "intent_category": "environment",
      "attitude_options": [
        {"dimension": "aggression", "level": "defensive", "effect": "趁佢哋未合圍，馬上行動"},
        {"dimension": "caution", "level": "timid", "effect": "先試探斜坡高度再行動"}
      ]
    },
    {
      "id": "opt_04",
      "lore_source": "system:surrender",
      "text": "【等待】放下武器，嘗試投降",
      "intent_category": "delay",
      "attitude_options": [
        {"dimension": "conviction", "level": "wavering", "effect": "徹底投降，希望留命"},
        {"dimension": "conviction", "level": "steady", "effect": "假裝投降，等待時機"}
      ]
    }
  ],
  "minor_event": {
    "id": "evt_distant_wolves_08",
    "description": "遠處傳嚟狼嚎，喺山谷中迴盪。",
    "narrative_impact": "subtle"
  },
  "physics_lock_violations": []
}
```

## Notes

**重點：**

1. **物理邏輯鎖殘疾演繹（核心展示）：**
   - 玩家狀態：`broken_left_arm`
   - 玩家意圖：舉臂擋格
   - LLM 演繹：「你本能地舉起右臂擋格——但你嘅左臂仲吊喺繃帶上，完全幫唔上」
   - 結果：擋格失敗，產生嚴重後果
   - 玩家**感受到**殘疾嘅真實影響，但**唔係**被 disable

2. **態度演繹（defensive + steady）：**
   - 「本能地舉起」（防禦本能）
   - 「咬住牙」（堅忍）
   - 「我唔會就咁死」（堅定）
   - 「慢慢企起身」（唔放棄）

3. **戰鬥狀態計算：**
   - stamina: muscle_ache → exhausted（-2 級，戰鬥加成）
   - health: broken_left_arm → broken_left_arm + 新傷（-1 級）
   - morale: anxious → anxious（無改善但亦未崩潰）

4. **感官細節：**
   - 視覺：蒙面人影、刀鋒
   - 聽覺：「退後！」、山賊笑聲
   - 觸覺：劇痛、血流
   - 嗅覺：（隱含血腥味）

5. **4 選項設計：**
   - 戰鬥（攻擊山賊）— 3 個態度
   - NPC 互動（呼救）— 2 個態度
   - 環境互動（利用地形）— 2 個態度
   - 等待（投降）— 2 個態度
   - 全部反映玩家嘅困境，但唔會立即死

6. **敘事張力：**
   - 玩家**唔係**超人
   - 玩家**唔係**無能
   - 玩家**面對**真實嘅威脅
   - 玩家**有**選擇

7. **細微事件：** 狼嚎增加環境張力

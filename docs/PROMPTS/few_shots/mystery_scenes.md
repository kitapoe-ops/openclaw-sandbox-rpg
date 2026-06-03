# Few-shot Example: Mystery Scene
# ============================================
# 範例：謎團揭示 + 線索佈局
# ============================================

## Scene 1: 線索埋設（早期）

### Input

```json
{
  "character": {...},
  "world": {
    "location": {
      "id": "loc_old_library",
      "name": "古老圖書館",
      "atmosphere": "mysterious"
    },
    "active_world_parameters": {
      "ancient_mystery": 2
    }
  },
  "player_choice": {
    "option_id": "opt_01",
    "attitude_selections": [
      {"dimension": "curiosity", "level": "eager"}
    ]
  }
}
```

### Output

```json
{
  "narrative": "你喺圖書館深處嘅書架前停下。\n\n呢度嘅書本大多已經殘破，但你注意到一本用深藍色皮革包裝嘅書，保存得異常完好。\n\n你將佢攞出。書脊上刻住一個符號——你從未見過，但感覺熟悉。\n\n你打開書。內頁係空白嘅。\n\n你再翻幾頁——全部都係空白。\n\n直到最後一頁。\n\n上面用褪色嘅墨水寫住一句話：\n\n「真相藏喺倒影之中。」\n\n你合上書。\n\n你唔知道呢句話係咩意思。但你記住咗。\n\n[場景 Agent 觀察：埋設伏筆，俾玩家一個謎團。佢哋會喺日後發現「倒影」可能指水池、鏡子、或某個 NPC。]",
  "state_changes": {
    "new_memories": [
      "memory_blue_book_phrase",
      "memory_unknown_symbol"
    ]
  }
}
```

---

## Scene 50: 謎團揭示（後期）

### Input

```json
{
  "character": {
    "memories": [
      "memory_blue_book_phrase",
      "memory_unknown_symbol"
    ]
  },
  "world": {
    "location": {
      "id": "loc_underground_cave",
      "name": "地下洞穴",
      "atmosphere": "mysterious"
    }
  },
  "player_choice": {
    "option_id": "opt_01",
    "attitude_selections": [
      {"dimension": "curiosity", "level": "eager"}
    ]
  }
}
```

### Output

```json
{
  "narrative": "你沿住狹窄嘅通道前進，直到進入一個寬闊嘅洞穴。\n\n洞穴中央有一池靜止嘅水。水面如鏡，完美咁反射住洞穴頂部嘅鐘乳石。\n\n你突然記起嗰句話：「真相藏喺倒影之中。」\n\n你跪喺水池邊，望入水中。\n\n你見到自己嘅倒影。\n\n但唔係你以為嘅倒影。\n\n水中嘅「你」望住你，嘴角露出微笑。\n\n「你終於嚟咗。」水中嘅「你」講。\n\n你後退一步。\n\n水中嘅「你」笑咗起嚟。\n\n「你以為你係邊個？」佢問。\n\n你望住佢——佢嘅樣貌同你一模一樣，但眼神唔同。更加老練，更加⋯⋯殘忍。\n\n「你只係我嘅一部分。」水中嘅「你」講，「我一直喺度等你。」\n\n[場景 Agent 觀察：揭示真相——玩家角色其實係某個存在嘅一部分。呢個係大 Quest 嘅轉折點。]",
  "state_changes": {
    "new_memories": [
      "memory_met_reflection",
      "memory_truth_about_identity"
    ],
    "world_state_changes": [
      "ancient_mystery: 2 → 3"
    ]
  }
}
```

---

## 謎團設計原則

**1. 早期埋設：**
- 線索要**唔起眼**
- 唔可以太明顯（否則玩家感覺「被擺佈」）
- 至少埋 3 條線索（保證至少有 1 條會被玩家發現）

**2. 中期呼應：**
- 當玩家收集到 2-3 條線索，LLM 開始**自然呼應**
- 唔好直接解釋（保持神秘感）

**3. 後期揭示：**
- 揭示要**戲劇性**
- 揭示要**呼應早期線索**（玩家有「啊原來係咁」嘅感覺）
- 揭示後要**開新支線**（唔好故事完結）

**4. 替代解釋：**
- 唔同玩家可能有**唔同解讀**
- LLM 唔可以「鎖死」單一真相
- 多個真相並存

**範例：**

```
線索 1：「真相藏喺倒影之中。」
線索 2：守衛經過水池時避開眼神。
線索 3：老學者講過「嗰個人有兩個靈魂」。

可能解釋 A：
玩家角色係雙重人格。

可能解釋 B：
玩家角色係某個神祇嘅一部分。

可能解釋 C：
玩家角色係複製人，原本有另一個版本。

LLM 唔需要選擇單一真相。佢可以俾線索，
讓玩家自己決定信邊個。
```

## 同其他 Agent 嘅協作

```
God Agent（埋線）：
- 喺 world_parameters 加 "ancient_mystery" 參數
- 喺 multiple locations 安排線索
- 喺 NPC 對話加入暗示

Scene Agent（即時演繹）：
- 收到埋設線索嘅指令
- 生成自然融入場景嘅敘事
- 唔可以太明顯

Player（探索）：
- 揀選項時可能發現線索
- 寫入 character.memories

Subsequent Rounds（呼應）：
- 當玩家探討相關地點，LLM 自然呼應
- 唔重複線索（已經發現過）
- 加入新線索
```

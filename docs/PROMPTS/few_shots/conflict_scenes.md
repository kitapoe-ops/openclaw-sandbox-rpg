# Few-shot Example: Player Conflict (Narrative Arbitration)
# ============================================
# 範例：兩個玩家做出矛盾行動 → God Agent 仲裁
# ============================================

## Scenario

**玩家 A** 寫：「我從 NPC 手中搶走咗聖劍，立刻逃走。」

**玩家 B** 寫：「我喺城外攔截從 NPC 手中搶走聖劍嘅賊人。」

**時序：** 玩家 A 提交時間 `T=12:34:56`，玩家 B 提交時間 `T=12:35:30`（相差 34 秒）

## God Agent Arbitration

### 仲裁過程

```
1. 偵測矛盾
   - 玩家 A：獲得聖劍（事件 evt_a_get_sword）
   - 玩家 B：攔截獲得聖劍嘅人（事件 evt_b_intercept）
   - 兩個事件邏輯互斥

2. 套用仲裁優先級
   - 時序優先：玩家 A 早 34 秒
   - 物理優先：N/A（兩者都係戰鬥）
   - 角色優先：兩者都係普通玩家
   - 故事優先：兩者都係支線 Quest
   - 玩家優先：兩者都係中立聲望

3. 決定
   - 時序優先生效
   - 玩家 A 獲得聖劍
   - 玩家 B 嘅攔截失敗，但觸發「謎團事件」

4. 生成 narrative_correction
   - 玩家 A：正常進行
   - 玩家 B：被告知「你到達時賊人已經走遠」+ 引入新線索
```

## God Agent Output (narrative_corrections 部分)

```json
{
  "narrative_corrections": [
    {
      "id": "corr_arb_001",
      "conflict_id": "conf_2024_001",
      "resolution": "時序優先 — 玩家 A 嘅行動生效",
      "explanation": "玩家 A (char_alice) 喺 12:34:56 提交，玩家 B (char_bob) 喺 12:35:30 提交。相差 34 秒，玩家 A 嘅行動先發生。",
      "affected_characters": ["char_alice", "char_bob"]
    }
  ]
}
```

## Scene Agent 對玩家 A 嘅回應

```json
{
  "character_id": "char_alice",
  "narrative": "你從守衛手中一把搶過聖劍。劍柄比你想像中更重，但握落去嘅一刻，你感覺到一股電流從掌心傳入。\n\n你冇回頭，直接衝出神殿大門。\n\n風從你耳邊呼嘯而過，腳下嘅石板被雨水打濕，你差啲滑倒，但依然保持住平衡。\n\n你轉入一條小巷，消失在夜色之中。\n\n你身後傳嚟守衛嘅叫喊聲，但已經越嚟越遠。",
  "state_changes": {
    "items_consumed": [],
    "new_memories": [
      "memory_acquired_holy_sword",
      "memory_fled_temple"
    ]
  }
}
```

## Scene Agent 對玩家 B 嘅回應

```json
{
  "character_id": "char_bob",
  "narrative": "你埋伏喺城外嘅樹叢中，等待獵物出現。\n\n時間一分一秒過去。\n\n你聽到遠處有腳步聲，仲有叫喊聲。但當你準備衝出去時，叫喊聲已經消失。\n\n你等咗一盞茶嘅時間。\n\n終於，一個守衛跌跌撞撞咁跑出嚟，身上有血跡。\n\n「佢⋯⋯佢搶走咗聖劍！」守衛喘息住講，「我追唔上！」\n\n你嘅心沉咗落去。\n\n你遲到咗。\n\n但你仲未放棄。你向守衛詢問更多細節——賊人嘅外貌、特徵、逃走嘅方向。\n\n守衛話：「佢好快。我只係見到一個身影，黑髮，著住⋯⋯」\n\n你記低咗所有細節。\n\n呢件事未完。",
  "state_changes": {
    "new_memories": [
      "memory_missed_intercept",
      "memory_sword_thief_description"
    ],
    "new_quests": [
      "quest_hunt_sword_thief"
    ]
  }
}
```

## 點解咁樣仲裁

**選擇時序優先嘅原因：**

1. **簡單透明：** 玩家容易理解點解
2. **避免 LLM 偏見：** 唔需要 LLM 判斷「邊個嘅故事比較好」
3. **保留玩家能動空間：** 兩個玩家都可以繼續行動
4. **產生新 Quest：** 玩家 B 獲得追擊 Quest，延長遊戲壽命

**避免嘅陷阱：**

- ❌ 唔可以 LLM 自由心證「邊個嘅故事比較合理」
- ❌ 唔可以因為玩家 A 較活躍就判佢贏
- ❌ 唔可以完全取消玩家 B 嘅選擇

**進階情況：**

如果玩家 A 同玩家 B 嘅時間差 < 5 秒：
- 觸發「同步事件」
- 兩個行動都「部分成功」
- 玩家 A 獲得聖劍但被目擊
- 玩家 B 攔截到但無取得聖劍
- 生成新衝突點俾雙方繼續互動

如果兩個玩家互相認識 + 同一陣營：
- 觸發「協作模式」
- LLM 將兩個行動融合為「聯合行動」
- 兩個玩家都獲得獎勵

如果兩個玩家敵對陣營：
- 觸發「PvP 模式」
- 雙方進入「對抗窗口」
- 結果由後端計算（速度、裝備、隨機數）
- LLM 根據結果生成敘事

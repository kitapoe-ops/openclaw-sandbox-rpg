# Few-shot Examples for Scene Agent
# ============================================
# 5-10 個精心設計嘅範例，展示預期輸出格式
# ============================================

呢個目錄包含 5-10 個 few-shot 範例，幫助場景 Agent 理解預期輸出。

## 範例類型

| 檔案 | 場景類型 | 重點展示 |
|------|---------|---------|
| `exploration_scenes.md` | 探索新地點 | 環境細節、感官描寫 |
| `social_scenes.md` | NPC 對話 | 對話風格、態度演繹 |
| `combat_scenes.md` | 戰鬥敘事 | 動作描述、狀態變化 |
| `conflict_scenes.md` | 玩家衝突 | 矛盾仲裁 |
| `mystery_scenes.md` | 謎團揭示 | 線索佈局、伏筆回收 |

## 範例格式

每個範例包括：
1. **Input** — 角色狀態 + 世界狀態 + 玩家選擇
2. **Output** — 完整 scene_output JSON
3. **Notes** — 解釋點解咁樣生成

## 使用方法

將呢啲範例作為 few-shot 注入到 LLM prompt 入面：

```python
# 偽代碼
prompt = base_prompt + "\n\n## Examples\n\n"
for example in few_shot_examples:
    prompt += format_example(example) + "\n\n"
prompt += "\n\n## Current Task\n\n" + current_input
```

## 維護

新增範例時：
- 必須符合 `scene_output.schema.json`
- 必須展示至少 1 個獨特嘅 LLM 演繹技巧
- 必須有清晰嘅 Notes 解釋

## 範例清單（待補）

- [ ] 探索新地點（廢墟）
- [ ] 探索新地點（繁華城鎮）
- [ ] NPC 友善對話
- [ ] NPC 敵對對話
- [ ] 戰鬥（單挑）
- [ ] 戰鬥（多人混戰）
- [ ] 玩家衝突（時序優先）
- [ ] 玩家衝突（謎團仲裁）
- [ ] 謎團揭示
- [ ] 物理邏輯鎖觸發（殘疾演繹）

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (2026-06-08)
- **User prompt restructured to 5 modules** (decision: 1B, 2A, 3A, 4A, 5A, 6A). New module: :mod:`backend.prompt_user` provides `build_user_prompt()` + section breakdown helper. Five modules: 1) Hard Facts (character + health + inventory placeholder + scene NPCs); 2) Karma & Traces (active threads + other-player footprints); 3) Trigger Action (verb + target + args); 4) Director's Constraints (trope directive + writing rules); 5) Output Requirements (JSON with narrative + state_mutations + 4 choices).
  - **Inventory:** placeholder text rendered; physical-constraint rule preserved; equipment section still hidden per 2026-06-08 commit 1727c30.
  - **F3 contract:** preserved — output JSON still requires `state_mutations` (Pydantic strict); `choices` array is additive (max 4 entries; each with `direction ∈ {combat, social, explore, creative}` + `vignette`).
  - **Footprints:** scene-level environmental metadata (blood, drag-marks, broken items). The memory_isolation audit invariant is **not broken** — footprints are public scene metadata, not cross-character private memory reads.
  - **Trope directive:** composed from `trope_router.get_trope_by_id(tid).narrative_directive` → `plot_beat + tonal_focus` narrative phrase.
  - **Health:** derived from `SemanticState.tags` (death-critical tags 死亡/瀕死 take priority); never returns numeric HP per F1 invariant.
  - `NARRATIVE_PROMPT_TEMPLATE` is preserved for backward compatibility; the active builder is `build_user_prompt_5module()` imported by :mod:`backend.api.action_processor`. The active user prompt is no longer constructed from `NARRATIVE_PROMPT_TEMPLATE.format(...)` in the F3 code path.
  - 25 new unit tests in `backend/tests/test_prompt_user.py` (all 5 modules, each section formatter, end-to-end `build_user_prompt`, `ALLOWED_CHOICE_DIRECTIONS` enum, section breakdown). All pass.
  - LLM output validator extended: `_validate_and_extract_choices()` enforces the 4-direction enum, non-empty vignette, soft numeric-content check (drops entries with >50% numeric tokens to enforce Module 5 "Risks ... 不可提供數字").
  - `action_processor._call_llm()` now returns a 5-tuple `(narrative, mutation, mutation_error, elapsed_ms, llm_meta)`; `llm_meta` holds `choices` + `ghost_state_warning` + `retries_used`. The handle() return value adds a top-level `choices` field.
  - Prompt Inspector `/preview` endpoint now also returns `user_prompt` (rendered + sections + template constants + allowed directions). Frontend panel not yet updated to display it; structural data is available for a future commit.

### Added (2026-06-08)
- **Prompt Inspector (dev-only, read-only).** New endpoint `GET /api/prompt-inspector/preview?character_id=X` returns the LLM system prompt that `PromptBuilder` would construct (placeholder state, no DB read, no LLM call, no audit bypass). New endpoint `GET /api/prompt-inspector/health` returns the flag state. New Vue component `frontend/src/components/PromptInspectorPanel.vue` is mounted in `GameView.vue` and auto-hides if the flag is off.
  - **Gating:** `ENABLE_PROMPT_INSPECTOR=true` env var (default false). The endpoint reads the env directly to avoid the pre-existing `backend/config.py` `.env` parse bug (CORS_ORIGINS JSON list). Production deploys must keep this disabled.
  - **Read-only by design:** there is no edit field, no submit button, no R1-14B bypass. The endpoint is purely a "what-would-the-LLM-see" preview.
  - 9 new unit tests in `backend/tests/test_prompt_inspector.py` (health flag, 404 gate, response shape, sections, hidden header, flags state, template constants, placeholder state). All pass; full suite 338 passed / 1 skipped / 0 fail.
  - The frontend panel offers three tabs: Full prompt (rendered template), Sections (per-section breakdown), Flags (hidden systems + R1 audit state).

### Hidden (2026-06-08)
- **Items / equipment system hidden.** `_format_equipment_section` in `backend/prompt_builder.py` now always returns `""`; the corresponding template header (`# 角色當前裝備與物理約束`) is stripped at format time. `<Equipment>` and `<Inventory>` mounts in `frontend/src/views/GameView.vue` are commented out. `TestEquipmentConstraints` (3 tests) updated to assert the section is empty. To re-enable: restore the disabled code blocks — original body preserved as comments.
- **Attitude / 態度選擇 system hidden.** Attitude section in `frontend/src/components/CharacterStatus.vue` (passive display) and the attitude accordion in `frontend/src/components/ChoiceCard.vue` (interactive selection) are commented out. Backend prompt never injected attitude state (verified — no `_format_attitude_section` exists), so no backend change needed. To re-enable: restore the disabled `<div v-if="state.attitude">` and `<details class="attitude-section">` blocks.

### Fixed
- `test_production_guard_rejects_demo_mode` was failing on Python 3.14 + Windows cp950 console due to `subprocess.run(..., text=True)` using locale encoding; added `encoding="utf-8"` + `errors="replace"`. Full suite now 329 passed, 1 skipped, 0 fail (~10s).

## [0.4.0] - 2026-06-08

### Added
- **前端 Premium 級 UI/UX 視覺重構**：
  - 導入 Google Fonts (`Cinzel` 與 `Outfit`)，建立極緻質感的暗紫金 HSL 視覺體系。
  - 全域使用 Glassmorphism 卡片特效 (`backdrop-filter: blur(12px)`) 與自定義滾動條。
  - 首頁極光漸層背景與金屬 Shimmer 按鈕特效。
  - 創角頁羊皮紙/魔法卡片排版、動態放大發光。
  - 體力、健康與情緒語意狀態**脈動 LED 發光燈**可視化。
  - 經典 RPG 裝備網格與特定裝備 silhouette 剪影。
  - 前端 LocalStorage 角色暫存與 WebSocket 斷線時的**「離線沙盒故事模擬器」**。
- **大世界配置重構與文學擴充**：
  - [dnd_5e_forgotten_realms.json](file:///c:/Users/kitap/.openclaw/workspace/sandbox-rpg-tmp/worlds/dnd_5e_forgotten_realms.json) 重構，支援 20+ 地點、75+ NPC、25+ 語意狀態物品及 5 個主線任務，完成 10 萬字大世界文學潤色。
- **後端架構相容性硬化與測試**：
  - 還原並解耦合 `app_with_memory.py` 以打破 Circular Import 循環依賴，使所有單元與整合測試全數 PASS（該 entry 寫 313，當前 suite 為 329 passed / 1 skipped）。**此 commit 重新引入 L2-B 喺 commit `dcafe4a` 刪除嘅 `app_with_memory.py`**（而家 568L，由 `main.py` line 203 import 5 個對外 endpoints）。
  - 修復前端性格 card 性格鍵 `v-for` 的 `TS2345` 類型錯誤，順利通過 Vite 編譯。
- **生產環境部署硬化 (Phase L2)**：
  - FastAPI 後端靜態資源一體化掛載、SPA 路由自動 fallback。
  - Cloudflared 隧道守護進程，ENV=production 資料庫安全 fail-loud 機制。

### Status
🚧 **Wave 1: Core Engine** (Month 1-3 plan)
- ✅ Project initialization
- ✅ Schema suite
- ✅ LLM prompt templates
- 🚧 Backend core modules (skeleton, TODO implementations)
- 🚧 D&D 5e world package (placeholder)
- ⏳ Frontend MVP
- ⏳ Docker deployment
- ⏳ MVP-B validation

## [0.1.0] - 2026-06-03

### Added
- Project bootstrap by OpenClaw
- Complete scaffolding for Wave 1 development

[Unreleased]: https://github.com/kitapoe-ops/openclaw-sandbox-rpg/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kitapoe-ops/openclaw-sandbox-rpg/releases/tag/v0.1.0

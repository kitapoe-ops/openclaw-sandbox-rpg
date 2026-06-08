# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

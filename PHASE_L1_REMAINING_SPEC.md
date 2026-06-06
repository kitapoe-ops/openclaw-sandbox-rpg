# Spec: Phase L1 Remaining — BAZOOKA Production Deployment (5 sub-tasks)

**Status:** Draft for user review (Phase 1 SPECIFY, project-agent skill)
**Date:** 2026-06-07 01:14 GMT+8
**Author:** Him / BAZOOKA deployment

---

## Objective

完成 Phase L1 剩餘嘅 5 個 deployment 步驟，將 `sandbox-rpg-tmp` 從「本地 developable」提升到「BAZOOKA 上 24/7 跑得」。前 2 步 (`.env.example` + NSSM scripts) 已喺 #61 / #62 commit 完成。

**Goal users:** Him 自己（BAZOOKA owner）+ 朋友（4 個 player 1 個月 demo）
**Success:** 撳 https://kitahim.ddns.net/openclaw/ → 入到 character selection → 玩到 game → 1 個月 stable

## Tech Stack

- **OS:** Windows 11 (BAZOOKA), PowerShell 5.1+ for scripts
- **Backend:** Python 3.11+, FastAPI + uvicorn + SQLAlchemy 2.x + aiosqlite
- **Database:** PostgreSQL 15+ (locally installed)
- **Vector store:** LanceDB (local dir, not cloud)
- **LLM:** Local R1-14B via LM Studio :1234 + cloud MiniMax-M3 (optional)
- **Tunnel:** Cloudflare named tunnel (requires stable domain, **NOT** quick tunnel)
- **Frontend:** Vue 3 + Vite, served as static files via `python -m http.server` (or nginx if operator installs)

## Commands (operator runbook)

```powershell
# One-time setup (Phase L1, 5 commits + this one):
scripts\setup_postgres.ps1              # idempotent db+user
scripts\run_migrations.ps1              # alembic upgrade head
scripts\install_service.ps1             # NSSM service (already shipped in #62)
scripts\setup_cloudflared.ps1           # register named tunnel
scripts\start_frontend.ps1              # launch static frontend serve
scripts\deploy_smoke_test.ps1           # 1-script validation of full chain

# Operational commands:
scripts\service_status.ps1              # is the backend up? (already shipped in #62)
scripts\restart_service.ps1             # nssm restart (or nssm start after stop)
Get-Service OpenClawSandboxRPG          # native Windows check
```

## Project Structure (new files)

```
scripts/
├── install_service.ps1          # DONE (#62)
├── uninstall_service.ps1        # DONE (#62)
├── service_status.ps1           # DONE (#62)
├── setup_postgres.ps1           # NEW
├── run_migrations.ps1           # NEW
├── setup_cloudflared.ps1        # NEW
├── start_frontend.ps1           # NEW
├── restart_service.ps1          # NEW
├── deploy_smoke_test.ps1        # NEW
└── .gitignore                   # (keep as-is; per-host paths already in root .gitignore)

docs/
└── DEPLOYMENT_BAZOOKA.md        # NEW (operator README, copy-paste commands)
```

## Code Style (per existing convention)

- **PowerShell:** Verb-Noun 命名, `param([type]$Name = default)` block, `[CmdletBinding()]` attribute, `$ErrorActionPreference = "Stop"`, `Write-Host -ForegroundColor` 顏色, `try/catch` for risky ops
- **PSScriptAnalyzer:** 不安裝，但所有 script 必須通過 `[System.Management.Automation.Language.Parser]::ParseFile` 0 syntax errors
- **Bash:** 不適用（本 deployment Windows-only）
- **Markdown:** 直接寫 `docs/DEPLOYMENT_BAZOOKA.md`，唔用 Mermaid（per MEMORY.md 顯示偏好）

## Testing Strategy

- **PowerShell:** 每個 script 內部做 self-test (e.g. `setup_postgres.ps1` 跑完立即 `psql -c "SELECT 1"` verify connection)
- **No pytest changes** — 純 deployment script，唔影響 backend code coverage
- **Verify CI 唔 fail:** 跑 `pytest tests/ -q --cov=. --cov-fail-under=85` 必須仍 329/330 PASS + 87.87% coverage
- **Smoke test (post-deploy):** 4 個 player 同時連入 → 揀 character → submit 1 個 action → 收到 LLM response within 30s → 全部 process 無 error in `logs/service-stderr.log`

## Boundaries

### Always (必須)
- **Each script:** idempotent (再 run OK 唔 crash)，用 `if (Test-Path ...)` 或 `IF NOT EXISTS` check
- **Pre-flight checks:** 確認 prerequisite 存在 (e.g. PostgreSQL 15+ binary, `cloudflared.exe`, `.env` filled)
- **Admin check:** 改 system 嘅 script (Postgres, NSSM install) 必須 check `WindowsBuiltInRole.Administrator`
- **No secrets in code:** 所有密碼/key 讀自 `.env`，script 唔 hardcode
- **No destructive ops without confirm:** `DROP DATABASE`, `nssm remove`, `cloudflared tunnel delete` 全部要 `ConfirmImpact = "High"` + 顯式 user prompt

### Ask First (先問)
- **Postgres password:** 唔自動 generate，要 user 提供 (或 prompt 一個 `secrets.token_urlsafe(32)` 然後 user 同意)
- **Cloudflare domain:** 要 user 提供 registered domain (e.g. `kitahim.ddns.net` 已被 DDNS 用, named tunnel 需要 stable)
- **Alembic destructive migrations:** downgrade 必須 confirm
- **Frontend serve port:** default 5173 (Vite dev) vs 8077 (nginx prod)，user preference

### Never (永不做)
- **Never** hardcode database password / JWT secret / API key
- **Never** `rm -rf` or `Remove-Item -Recurse -Force` on Postgres data dir or LanceDB dir
- **Never** auto-start `cloudflared quick tunnel` (deprecated, replaced by named tunnel)
- **Never** modify NSSM service that's not `OpenClawSandboxRPG` (avoid clobbering other services)
- **Never** `alembic downgrade` without explicit user instruction
- **Never** commit `.env`, `.service_wrapper.py`, or `logs/*` (already in .gitignore, must stay so)

## Success Criteria (specific + testable)

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | `scripts\setup_postgres.ps1` creates `sandbox_rpg` db + `rpg_user` user, idempotent (rerun OK) | Run twice; second run reports "already exists" not error |
| 2 | `scripts\run_migrations.ps1` runs `alembic upgrade head` successfully, reports "current revision: <hash>" | `psql -c "SELECT version_num FROM alembic_version"` returns hash |
| 3 | `scripts\setup_cloudflared.ps1` registers named tunnel + DNS route + runs `cloudflared service install` | `cloudflared tunnel list` shows `openclaw-rpg`; DNS resolves |
| 4 | `scripts\start_frontend.ps1` serves `frontend/dist/` on port 5173 (default) | `curl http://localhost:5173/` returns HTML with `<div id="app">` |
| 5 | `scripts\restart_service.ps1` is a thin wrapper (nssm stop + start) | After run, `Get-Service OpenClawSandboxRPG` returns `Running` within 5s |
| 6 | `scripts\deploy_smoke_test.ps1` does end-to-end check: DB connect, LM Studio :1234 reachable, frontend served, /health returns 200, all 4 expected vars in /health JSON | Script prints "ALL CHECKS PASSED" with green checkmarks |
| 7 | `docs/DEPLOYMENT_BAZOOKA.md` is < 200 lines, copy-paste runnable, ends with "VERIFICATION" section showing expected outputs | `wc -l docs/DEPLOYMENT_BAZOOKA.md` < 200 |
| 8 | All 6 commits: `ruff check .` 0 errors, `ruff format --check .` 0 errors, `mypy .` 0 errors, `pytest tests/` 329/330 PASS, coverage 87.87% | Local pre-push check, plus CI #63-#68 all green |
| 9 | **No new coverage-affecting files** (deployment scripts not in `omit` list, not in `source = .` of .coveragerc) | `git diff .coveragerc` returns empty |
| 10 | Each script's PowerShell parser returns 0 syntax errors | Run `[Parser]::ParseFile($f, [ref]$null, [ref]$err); $err.Count` |

## Open Questions (need user input before Phase 2)

1. **Domain for named tunnel:** Do you have a stable domain registered (e.g. `kitahim.com`)? `kitahim.ddns.net` is dynamic-DNS — does Cloudflare accept it for named tunnels, or do we need a static domain first?
   - **Option A:** Static domain ($10-15/year at Cloudflare Registrar)
   - **Option B:** Keep DDNS, use Cloudflare DNS-01 challenge for tunnel auth
   - **Option C:** Skip named tunnel, stick with quick tunnel (`*.trycloudflare.com`) for now

2. **Frontend serve port:** 5173 (Vite default) or 8077 (existing nginx on BAZOOKA per TOOLS.md)?
   - Option A: 5173 (simpler, no nginx needed, dedicated Python http.server)
   - Option B: 8077 (existing convention, requires nginx config)

3. **Postgres install method:** Docker, winget, or native Windows installer?
   - Option A: Docker Desktop (clean isolation, but requires Docker)
   - Option B: `winget install postgresql` (native, but adds Windows service)
   - Option C: Native `.exe` installer (traditional but heavyweight)

4. **Migration approach:** Auto-run on service start (cron-style) or manual one-shot?
   - Option A: Auto-run via pre-start hook in NSSM (but more complex; might break)
   - Option B: Manual `scripts\run_migrations.ps1` after `setup_postgres.ps1` (safer; documented)

5. **Backup strategy (per user cancellation of OneDrive/GoogleDrive):** User said NO backup offer. Does this mean:
   - Option A: Zero backups (data loss acceptable, Postgres + LanceDB on BAZOOKA only)
   - Option B: Manual `robocopy` script to external drive (operator-driven)
   - Option C: Built-in Postgres pg_dump to local dir (operator must copy out)

---

## ETA Estimate (per project-agent skill)

| Sub-task | Est time |
|----------|----------|
| H1: setup_postgres.ps1 + run_migrations.ps1 | ~30 min |
| H2: setup_cloudflared.ps1 | ~30 min (depends on user's domain answer) |
| H3: start_frontend.ps1 | ~20 min |
| H4: restart_service.ps1 (thin wrapper) | ~10 min |
| H5: deploy_smoke_test.ps1 | ~30 min |
| H6: docs/DEPLOYMENT_BAZOOKA.md | ~45 min |
| 6 commits × 5 min each (commit + push + wait CI) | ~30 min |
| **Total** | **~3.25 hr** |

**Note:** If user cannot answer Open Questions 1 (domain) and 3 (Postgres install) within first 30 min, the 3.25 hr estimate becomes 4-5 hr (with research time).

**Time check:** It's currently 01:15 GMT+8. A 3.25 hr session would end ~04:30 GMT+8, which is too late. **Recommendation:** Do H1 + H3 + H4 + H5 + H6 tonight (skip H2 cloudflared pending user domain answer) → 2 hr → end ~03:15 GMT+8. Defer H2 to next session.

---

## Spec Verification (per project-agent Phase 1)

1. ✅ Spec covers 6 core areas (Objective / Tech / Commands / Structure / Style / Testing) + Boundaries + Success Criteria
2. ✅ Success criteria are specific and testable (10 numbered criteria with verify methods)
3. ✅ Boundaries (Always / Ask First / Never) defined clearly
4. ⚠️ **5 open questions** need user input before Phase 2

**Spec awaits user approval before proceeding to PLAN + TASKS phase.**

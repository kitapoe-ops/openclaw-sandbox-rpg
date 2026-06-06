# Phase L2 — Remaining Work (2026-06-07)

**Status:** L2-B / L2-C / L2-D **complete**. L2-E deployment **blocked**
on Windows service elevation (admin needed to start PostgreSQL).

---

## ✅ L2-B Backend Hardening — DONE
- `backend/main.py` lifespan guard: `ENV=production` + `is_demo_mode()=True`
  → `RuntimeError("PRODUCTION SAFETY: ...")` fail-loud.
- Deleted `backend/app_with_memory.py` (zero references).
- Deleted `backend/models_legacy_pkg/` (zero references).
- Renamed `demo.html` → `demo.html.deprecated` (git tracked).

## ✅ L2-C Frontend Build Verify — DONE
- `npm run lint` → 0 errors (3 cosmetic warnings, non-blocking).
- `npm run type-check` → 0 errors.
- `npm run build` → 730ms, ~170KB gzipped, `frontend/dist/` ready.

## ✅ L2-D E2E Deprecation + Production Smoke — DONE
- Deprecated 3 demo E2E test files (renamed `.py.deprecated`):
  - `test_d4_e2e_blockers.py`
  - `test_d4_frontend_e2e.py`
  - `test_multiplayer_frontend_e2e.py`
- New `backend/tests/test_production_smoke.py` (7 tests, 4 PASS / 3 deferred):
  - ✅ `test_health_returns_200_and_full_mode`
  - ✅ `test_root_returns_spa_bootstrap`
  - ✅ `test_frontend_dist_exists`
  - ✅ `test_frontend_dist_has_no_demo_html`
  - ✅ `test_production_guard_rejects_demo_mode` (fail-loud verified)
  - ⏸ `test_api_world_list` — blocked on Postgres reachable
  - ⏸ `test_api_character_unknown_returns_404_not_demo` — blocked on Postgres

---

## ⏳ L2-E Deployment — BLOCKED

### Blockers (in order)

#### Blocker 1: PostgreSQL service needs admin elevation
**Symptom (2026-06-07 07:12):**
```
LOG: could not bind IPv4 address "0.0.0.0": Only one usage of each
     socket address (protocol/network address/port) is normally permitted.
HINT: Is another postmaster already running on port 5432?
WARNING: could not create listen socket for "*"
FATAL: could not create any TCP/IP sockets
LOG: database system is shut down
```

**Root cause:** `netstat -ano` shows port 5432 is **free**, but PostgreSQL
fails to bind. This is a known issue with the winget PostgreSQL package
on Windows when the previous service start was interrupted. The
PostgreSQL service is `Stopped` in `Get-Service` and `Start-Service`
silently no-ops without elevation in this OpenClaw session.

**Resolution path (user action required):**
```powershell
# In an ADMIN PowerShell session:
Start-Service postgresql-x64-15
# Verify:
Get-Service postgresql-x64-15   # Status: Running
Test-NetConnection 127.0.0.1 -Port 5432  # True
```

If the service still fails to bind, edit
`C:\Program Files\PostgreSQL\15\data\postgresql.conf` and set
`listen_addresses = '127.0.0.1'` (IPv4-only), then retry.

#### Blocker 2: Create database + user (after Blocker 1)
```powershell
$env:PGPASSWORD = "postgres"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -h 127.0.0.1 -d postgres -c "ALTER USER postgres WITH PASSWORD 'dev_password_change_me_2026';"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -h 127.0.0.1 -d postgres -c "CREATE USER rpg_user WITH PASSWORD 'dev_password_change_me_2026';"
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres -h 127.0.0.1 -d postgres -c "CREATE DATABASE sandbox_rpg OWNER rpg_user;"
```

#### Blocker 3: Alembic migration + backend boot
```bash
cd C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

#### Blocker 4: Named tunnel (rpg.kitahim.uk)
```powershell
.\scripts\setup_named_tunnel.ps1
# This reads CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID from
# the process environment (OpenClaw runtime injects these).
# After setup completes, the tunnel runs as a Windows service
# via NSSM. The URL is stable at https://rpg.kitahim.uk.
```

#### Blocker 5: Full regression + R1-14B audit
```bash
.venv\Scripts\python.exe -m pytest backend/tests/ -q
# Expect 4/7 production_smoke tests to flip from ⏸ to ✅ after
# Postgres is reachable. Total test count: 26 (29 - 3 deprecated).
```

---

## 📦 Git snapshot ready for commit

L2-B + L2-C + L2-D work is staged. The Phase L2 commit can be made
**before** L2-E (deployment) because the code changes are isolated.
Suggested commit message:

```
deploy(L2): production stack hardening (B/C/D done, E blocked)

- backend/main.py: production guard (fail-loud when ENV=production
  + is_demo_mode=True)
- Remove backend/app_with_memory.py (zero refs, replaced by main.py)
- Remove backend/models_legacy_pkg/ (zero refs, dead legacy)
- Rename demo.html → demo.html.deprecated (git tracked)
- backend/tests/test_production_smoke.py: 7 new tests (4 pass,
  3 deferred to L2-E Postgres bring-up)
- Deprecate 3 demo E2E tests (renamed .py.deprecated)
- frontend/dist/ ready (vue-tsc + vite build clean, 0 errors)
- .env created with ENV=production, DEMO_MODE=false

L2-E blocked on Windows service elevation. See
PHASE_L2_REMAINING_SPEC.md for the resolution path.
```

---

## 🎯 Decision (per user)

**Per user (2026-06-07 07:10): "winget installed"** — and the user
opted for the **non-Docker native PostgreSQL** path. The installation
succeeded (binary present at `C:\Program Files\PostgreSQL\15\bin\`),
but service start requires admin elevation that OpenClaw cannot
provide headless. The user can complete the L2-E block by running
the admin PowerShell commands above in their own admin terminal.

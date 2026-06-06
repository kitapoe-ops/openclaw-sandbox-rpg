# DEPLOYMENT_BAZOOKA.md

> Operator runbook for deploying `openclaw-sandbox-rpg` to BAZOOKA
> (Windows 11 PC, 16GB+ RAM, has GPU). Per MEMORY.md "Sandbox RPG
> 部署範圍 2026-06-07": BAZOOKA is the only deployment target.
> Pi5 and cloud (Hetzner/DO/Vercel) are permanently excluded.

## Pre-requisites

| Component | Required version | Verify command |
|-----------|------------------|----------------|
| Windows | 10+ with App Installer | `winget --version` |
| PowerShell | 5.1+ | `$PSVersionTable.PSVersion` |
| Git | 2.x+ | `git --version` |
| Python | 3.11+ | `py --version` (or `python --version`) |
| Node | 24+ | `node --version` |
| RAM | 16GB+ | (Task Manager → Performance) |

## One-time setup (per BAZOOKA)

Clone the repo:

```powershell
cd C:\Users\kitap\.openclaw\workspace
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git sandbox-rpg-tmp
cd sandbox-rpg-tmp
```

Create the venv and install Python deps:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Install frontend deps and build:

```powershell
cd frontend
npm install
npm run build
cd ..
```

(If you ever change frontend code, re-run `npm run build` to refresh
`frontend/dist/`.)

Copy `.env.example` to `.env` and fill in secrets:

```powershell
copy backend\.env.example backend\.env
notepad backend\.env
```

Replace these in `backend\.env`:

- `POSTGRES_PASSWORD` — generate one with:
  ```powershell
  .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `SECRET_KEY` — same method
- `LLM_CLOUD_API_KEY` — leave empty if you only use local R1

Save and close notepad.

## The 6 deployment scripts (in order)

```powershell
# All scripts must be run from an Administrator PowerShell
# (right-click PowerShell -> "Run as administrator")

# 1. Install PostgreSQL 15 + create sandbox_rpg DB + rpg_user
scripts\setup_postgres.ps1

# 2. Run Alembic migrations to create the schema
scripts\run_migrations.ps1

# 3. Install the OpenClawSandboxRPG Windows service (NSSM)
scripts\install_service.ps1

# 4. Sync the frontend build into backend/static/ and restart
scripts\start_frontend.ps1

# 5. Start the Cloudflare Quick Tunnel (URL appears in 5-10s)
scripts\setup_cloudflared.ps1
#    -> prints the public URL, e.g. https://random-words.trycloudflare.com
#    -> also writes to logs\cloudflared-url.txt

# 6. Run the end-to-end smoke test
scripts\deploy_smoke_test.ps1
#    -> Should print "ALL CRITICAL CHECKS PASSED"
```

## Day-to-day operations

### Check service status
```powershell
scripts\service_status.ps1
```

### Restart the backend
```powershell
scripts\restart_service.ps1
```

### Update the frontend (after changing code in frontend/src/)
```powershell
cd frontend
npm run build
cd ..
scripts\start_frontend.ps1
# (also copies dist/ to backend/static/ and restarts the service)
```

### Update the backend (after changing code in backend/)
```powershell
scripts\restart_service.ps1
# If the change requires a DB schema change, also run:
scripts\run_migrations.ps1
```

### Re-establish the public tunnel (after BAZOOKA reboot)
```powershell
scripts\setup_cloudflared.ps1
# (Note: the URL will change every time)
```

### View logs
```powershell
# Backend service stdout/stderr (rotating, 10MB each)
Get-Content logs\service-stdout.log -Tail 50 -Wait
Get-Content logs\service-stderr.log -Tail 50 -Wait

# Cloudflare tunnel URL + log
Get-Content logs\cloudflared-url.txt
Get-Content logs\cloudflared.log -Tail 50 -Wait
```

### Verify everything is healthy
```powershell
scripts\deploy_smoke_test.ps1
```

## Sharing the URL with players

After `scripts\setup_cloudflared.ps1` runs, copy the printed
`https://*.trycloudflare.com` URL and share it with the 4
players. They open it in a browser, the SPA loads, and the
backend API is at the same origin under `/api/*`.

The URL **changes every time** cloudflared restarts. If you
reboot BAZOOKA, re-run `setup_cloudflared.ps1` and tell your
players the new URL (Telegram bot, SMS, whatever).

## Upgrading to a stable URL (named tunnel)

The quick tunnel URL is fine for a 1-month demo but changes on
restart. If you want a stable URL like `https://rpg.yourdomain.com`:

1. Register a domain (any registrar; bring it to Cloudflare for free).
2. From BAZOOKA, run `cloudflared tunnel login` (browser-based auth).
3. `cloudflared tunnel create openclaw-rpg` (creates the tunnel).
4. Edit `C:\Users\kitap\.clouflared\config.yml` with the tunnel UUID + ingress rules.
5. In Cloudflare DNS, add a CNAME for your domain pointing to
   `<tunnel-uuid>.cfargotunnel.com`.
6. `cloudflared tunnel route dns openclaw-rpg rpg.yourdomain.com`.
7. `cloudflared service install` (run as Windows service).
8. Modify `scripts\setup_cloudflared.ps1` to use named-tunnel
   syntax instead of `--url`.

This is a separate Phase L2 task. Not needed for the demo.

## Uninstall

To remove the BAZOOKA deployment:

```powershell
# Stop + remove the Windows service
scripts\uninstall_service.ps1

# Stop + remove the Cloudflare tunnel
Get-Process cloudflared | Stop-Process -Force

# (Optional) Remove the Postgres database and role
psql -U postgres -c "DROP DATABASE sandbox_rpg"
psql -U postgres -c "DROP ROLE rpg_user"

# (Optional) Remove the NSSM service wrapper
# NSSM is installed at C:\Tools\nssm-2.24\ — delete if you want
# a fully clean machine.

# (Optional) Remove the venv and .env
rmdir /s /q .venv
del backend\.env
```

## VERIFICATION

After running all 6 scripts, you should see:

- `scripts\service_status.ps1` → Status: Running, Health check: HEALTHY
- `scripts\deploy_smoke_test.ps1` → ALL CRITICAL CHECKS PASSED
- `Get-Content logs\cloudflared-url.txt` → `https://something.trycloudflare.com`
- `curl <that URL>/health` → JSON with `status: "ok"`

Players can connect to that URL and play.

## Known limitations (Phase L1)

- **No backup.** If the Postgres data dir or LanceDB dir is lost,
  all game state is gone. Per user explicit decision (NO backup
  offer). For backup, add a manual `pg_dump` step later.
- **Quick tunnel URL changes on restart.** Use the named-tunnel
  upgrade path above for a stable URL.
- **No monitoring/alerting.** The `deploy_smoke_test.ps1` script
  is your manual health check. For 24/7 monitoring, add
  UptimeRobot or a simple cron via Task Scheduler that pings
  `/health` every 5 minutes.
- **No rate limiting on the LLM endpoint.** If 4 friends play
  24/7 and each submits 1 action per minute, that's
  ~5760 LLM calls/day. The MiniMax-M3 cloud rate limit is
  60 req/min by default; local R1 has no limit but is slow.
- **No structured logging / error tracking.** Stdout only.
  For production, add Sentry + Grafana.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|---------------|-----|
| `setup_postgres.ps1` fails with "Cannot connect as postgres" | pg_hba.conf requires password | Edit `C:\Program Files\PostgreSQL\15\data\pg_hba.conf` to allow local trust, restart `postgresql-x64-15` |
| `install_service.ps1` fails with "NSSM not found" | NSSM not installed | Download from https://nssm.cc/download, unpack to `C:\Tools\nssm-2.24\` |
| `service_status.ps1` shows service "Stopped" | Crash on startup | `Get-Content logs\service-stderr.log -Tail 50` to see why |
| `setup_cloudflared.ps1` doesn't print a URL within 60s | Firewall blocking outbound 7844 | Check Windows Defender outbound rules; add exception for `cloudflared.exe` |
| `/health` returns 503 | Backend started but DB unreachable | Check `POSTGRES_HOST=localhost` and that `psql` works as rpg_user |

## Related docs

- `PHASE_L1_REMAINING_SPEC.md` — the spec that drove this deployment.
- `MEMORY.md` (workspace root) — long-term rules, including the
  "Sandbox RPG 部署範圍 2026-06-07" entry that defines BAZOOKA
  as the only deployment target.
- `backend/.env.example` — the env var template.
- `scripts/setup_postgres.ps1` — the script you'll run first.

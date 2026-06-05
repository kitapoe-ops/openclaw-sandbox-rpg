# Hosted Deployment Quickstart — Cloudflare Quick Tunnel

**Status:** ✅ Verified 2026-06-06 on BAZOOKA (Windows 11).
**Deploy time:** ~5 minutes (after `cloudflared` is installed).
**Best for:** Solo dev or 1-4 friends testing multiplayer across networks.
**Not for:** Public launch — see [§ 8](#8-upgrade-path-named-tunnel).

---

## 1. Overview

**Cloudflare Quick Tunnel** is a one-line, no-account-required way to
expose your local backend (BAZOOKA) to the public internet with a real
HTTPS URL and **WebSocket support out of the box**.

| Constraint | Why Quick Tunnel works |
|---|---|
| `kitahim.ddns.net` is DDNS, not a registered domain | No DNS changes needed at all |
| Want 1-4 player multiplayer, not public launch | Zero account, zero config |
| Need WSS (WebSocket Secure) for multiplayer fan-out | Cloudflare issues real TLS certs |
| Test from phone, friend's house, café | Public URL works from any device |

**Trade-off:** the URL is **random and changes on every restart**
(e.g. `logs-perry-campaign-pleasant.trycloudflare.com`). For a stable
URL, upgrade to a **named tunnel** (§ 8).

**LOCAL-ONLY principle preserved:** BAZOOKA is still the source of
truth. Cloudflare's edge is just an HTTPS-terminating reverse proxy —
it does not store your data.

---

## 2. Prerequisites

| Requirement | Version | Check |
|---|---|---|
| `cloudflared` binary | 2026.5.2+ | `cloudflared --version` |
| Python venv | 3.12+ | `python --version` |
| Backend running | port 8000, demo mode | `curl http://localhost:8000/health` |
| Outbound HTTPS to Cloudflare edge | unrestricted | works on most home networks |

### Install `cloudflared` (Windows)

**Option A — winget (user-mode elevation):**
```powershell
winget install --id Cloudflare.cloudflared
```

**Option B — direct download (no admin):**
```powershell
Invoke-WebRequest `
  -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
  -OutFile "$env:USERPROFILE\cloudflared.exe" -UseBasicParsing
$env:PATH += ";$env:USERPROFILE"
& "$env:USERPROFILE\cloudflared.exe" --version
# Expected: cloudflared version 2026.5.2 (built 2026-05-27...)
```

---

## 3. 5-minute deploy

**Terminal 1 — Backend:**
```bash
cd C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp
.\.venv\Scripts\python.exe -m uvicorn backend.app_with_memory:app --host 0.0.0.0 --port 8000
```
Wait for: `INFO:     Uvicorn running on http://0.0.0.0:8000`.

**Terminal 2 — Quick Tunnel:**
```bash
& "$env:USERPROFILE\cloudflared.exe" tunnel --url http://localhost:8000 --no-autoupdate
```
Within ~5 seconds you get a box with a URL like:
```
|  https://logs-perry-campaign-pleasant.trycloudflare.com  |
```
**Copy that URL** — that's your public entry point.

> **Note:** `--no-autoupdate` is mandatory on Windows. Without it,
> `cloudflared` may hang trying to update a user-protected binary.

---

## 4. What you get

- **`https://*.trycloudflare.com` URL** valid for as long as `cloudflared` runs.
- **Real TLS certificate** issued by Cloudflare automatically.
- **HTTP/2 + QUIC** at the edge → low latency.
- **WebSocket support (WSS)** out of the box.
- **Free.** No account. No quota.

**Not included:** custom domain (URL changes on restart), uptime SLA,
CF Access / Auth, load balancing.

---

## 5. Verify the public URL

Replace `YOUR_URL` with your `*.trycloudflare.com`.

**HTTP:**
```bash
curl --ssl-no-revoke https://YOUR_URL/health
# {"status":"ok","version":"0.4.0","mode":"demo",...}
curl --ssl-no-revoke https://YOUR_URL/memory/health
# {"postgres":true,"vector_store":true}
```

> **Windows quirk:** PowerShell `curl` is `Invoke-WebRequest` and fails
> Cloudflare certs with `CRYPT_E_NO_REVOCATION_CHECK`. Use `curl.exe`
> or pass `--ssl-no-revoke`.

**WebSocket:**
```python
import asyncio, websockets

async def main():
    url = "wss://YOUR_URL/ws/multiplayer/test_scene/p1"
    async with websockets.connect(url, open_timeout=20) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        print(msg)  # {"event":"connected","scene_id":"test_scene",...}
        await ws.send('{"action": "ping"}')
        print(await asyncio.wait_for(ws.recv(), timeout=10))

asyncio.run(main())
```

**Verified on BAZOOKA 2026-06-06:** Handshake ~1s, server-push immediate,
echo round-trip <100ms.

**Cross-device smoke test:** From your phone (on cellular, NOT WiFi),
open `https://YOUR_URL/docs` — you should see FastAPI's Swagger UI. If
yes, the deployment is functional.

---

## 6. Vercel frontend configuration

The frontend is a Vite SPA. Two env vars control the public URL.

**Local dev** — `frontend/.env.local`:
```bash
VITE_API_BASE_URL=https://YOUR_URL
VITE_WS_BASE_URL=wss://YOUR_URL
```
Then `cd frontend && npm install && npm run dev`.

**Vercel production** — project → Environment Variables:
| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://YOUR_URL` |
| `VITE_WS_BASE_URL` | `wss://YOUR_URL` |

Then `vercel --prod`. `src/services/api.ts` and `src/services/websocket.ts`
already read from these env vars — **no code changes needed**.

> **Caveat:** When the tunnel restarts, the URL changes. Update both
> Vercel env vars and redeploy — or upgrade to a named tunnel (§ 8).

---

## 7. Limitations

1. **URL changes on every restart** — save it somewhere you'll remember.
2. **No uptime guarantee** — fine for game night, not production.
3. **No authentication** — anyone with the URL can hit your backend.
4. **Single machine** — all state on BAZOOKA; if BAZOOKA sleeps, tunnel dies.
5. **`cloudflared` does not auto-restart on reboot** (use Task Scheduler).
6. **Player IP is Cloudflare's edge IP**, not the player's real IP.

---

## 8. Upgrade path: Named Tunnel

For a stable URL (e.g. `sandbox.example.com`), 5 extra minutes plus a
Cloudflare account:
```bash
cloudflared tunnel login                              # opens browser
cloudflared tunnel create sandbox-rpg                 # creates tunnel
# Add %USERPROFILE%\.cloudflared\config.yml:
#   tunnel: sandbox-rpg
#   credentials-file: C:\Users\kitap\.cloudflared\<ID>.json
#   ingress:
#     - hostname: sandbox.example.com
#       service: http://localhost:8000
#     - service: http_status:404
cloudflared tunnel route dns sandbox-rpg sandbox.example.com
cloudflared tunnel run sandbox-rpg
```
Then Vercel env vars point to `https://sandbox.example.com` once.

---

## 9. Scope reminder: LOCAL-ONLY principle preserved

| Layer | Where it lives |
|---|---|
| **Game state** | BAZOOKA Postgres / Vector store |
| **AI narration** | BAZOOKA (LLM calls locally) |
| **WebSocket fan-out** | BAZOOKA's `MultiplayerConnectionManager` |
| **HTTPS termination** | Cloudflare edge (does not store payloads) |
| **Static frontend** | Vercel (read-only delivery) |

Cloudflare's edge does NOT cache or store your data — it only
terminates TLS and proxies HTTP/WS. BAZOOKA remains the source of truth.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `cloudflared: command not found` | Use full path `& "$env:USERPROFILE\cloudflared.exe"` or open new terminal |
| Port 8000 already in use | `netstat -ano \| findstr ":8000"` → `Stop-Process -Id <PID> -Force` |
| WSS returns HTTP 404 | Use `backend.app_with_memory:app` (not `backend.main:app`) |
| WSS works locally, fails through tunnel | Kill all uvicorn processes, restart from § 3 |
| `520` from Cloudflare | Backend crashed — check uvicorn logs |
| `525` from Cloudflare | `cloudflared` config broken — kill and restart |
| `CRYPT_E_NO_REVOCATION_CHECK` (Win curl) | Use `curl.exe` or `--ssl-no-revoke` |
| "Cannot determine default config path" | Harmless — Quick Tunnel doesn't use a config file |
| "Mixed Content: 'http://' is not allowed" (Vercel) | Use `https://` and `wss://` |

**WSS URL reminder:** correct path is
`/ws/multiplayer/{scene_id}/{player_id}` (note `multiplayer`, not `multi`).

---

## Appendix A — Verification log (2026-06-06)

| Step | Result | Notes |
|---|---|---|
| Install `cloudflared` | ✅ | v2026.5.2 to `$env:USERPROFILE\cloudflared.exe` |
| Start backend on :8000 | ✅ | `uvicorn backend.app_with_memory:app` (DEMO MODE) |
| Start Quick Tunnel | ✅ | URL: `https://logs-perry-campaign-pleasant.trycloudflare.com` |
| Verify `GET /health` | ✅ | `{"status":"ok","version":"0.4.0","mode":"demo",...}` |
| Verify `GET /memory/health` | ✅ | `{"postgres":true,"vector_store":true}` |
| Verify WSS `/ws/multiplayer/...` | ✅ | Handshake 1.02s; server-push + echo confirmed |
| Verify WSS `/ws/game/...` | ✅ | Handshake OK; `connection_ack` received |
| Kill background processes | ✅ | `cloudflared` and uvicorn terminated cleanly |

**URL was issued successfully** (invalidated when tunnel exits; new URL
on each restart).

**Re-launch log (2026-06-06 01:13 HKT, deployment-relaunch subagent):**
- New URL: `https://farmer-oecd-drilling-phil.trycloudflare.com`
- Cloudflare edge: `hkg12` (QUIC, conn `9aef875a-...`)
- `GET /memory/health` -> 200 `{"postgres":true,"vector_store":true}`
- `GET /health` -> 200 demo mode
- WSS `/ws/multiplayer/test/p1` -> 101 Switching Protocols, server-push
  `{"event":"connected","scene_id":"test","player_id":"p1",...}`

---

## Appendix B — Quick reference card

**Start:** T1 = `uvicorn backend.app_with_memory:app --host 0.0.0.0 --port 8000` · T2 = `cloudflared tunnel --url http://localhost:8000 --no-autoupdate`
**Verify:** `curl.exe --ssl-no-revoke https://YOUR_URL/health`
**Stop:** `Ctrl+C` in both, or `Get-Process -Name cloudflared,python | Stop-Process -Force`

---

## 11. Tunnel went down? Here's how to bring it back

If your public URL returns **Cloudflare error 1033**, the `cloudflared`
daemon has exited (most common: laptop sleep, terminal closed, host
rebooted). The previous URL is **dead** — Quick Tunnels cannot be
resumed. You must issue a new one.

**Re-launch in 60 seconds (Windows / PowerShell):**

```powershell
# Terminal 1 — backend (only if it's not already running)
cd C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp
.\.venv\Scripts\python.exe -m uvicorn backend.app_with_memory:app --host 0.0.0.0 --port 8000

# Terminal 2 — tunnel
& "$env:USERPROFILE\cloudflared.exe" tunnel --url http://localhost:8000 --no-autoupdate
```

Look for the box:
```
+--------------------------------------------------------------------------------------------+
|  https://<new-random-subdomain>.trycloudflare.com                                          |
+--------------------------------------------------------------------------------------------+
```

**Then update Vercel** (project → Settings → Environment Variables):
| Variable | New value |
|---|---|
| `VITE_API_BASE_URL` | `https://<new-url>` |
| `VITE_WS_BASE_URL` | `wss://<new-url>` |

Then `vercel --prod` (or `vercel deploy` for a preview).

> **Tip:** If you run the included `scripts\start_demo_public.bat`
> (see § 12, Option C), it parses the new URL from `cloudflared.log`
> and prints it for you.

---

## 12. Keep the tunnel alive (long-term options)

The Quick Tunnel is designed for **short-lived demos**, not always-on
service. Pick one of these three options based on your needs.

### Option A — Linux `systemd` user service (recommended for Linux hosts)

If you ever move the backend to a Linux box (VPS, Pi, etc.), run
`cloudflared` as a user-level systemd service so it auto-restarts on
failure and survives reboots.

**File:** `~/.config/systemd/user/cloudflared.service`
```ini
[Unit]
Description=Cloudflare Quick Tunnel -> sandbox-rpg backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel --url http://localhost:8000 --no-autoupdate
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/cloudflared.log
StandardError=append:/var/log/cloudflared.log

[Install]
WantedBy=default.target
```

```bash
# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now cloudflared.service

# Check status
systemctl --user status cloudflared.service

# Tail logs
journalctl --user -u cloudflared.service -f
```

> **Caveat:** Quick Tunnel URL still changes on every daemon restart.
> For a *truly* stable URL on Linux, also do the named-tunnel upgrade
> (§ 8). systemd only solves the "auto-restart" problem, not the
> "stable URL" problem.

### Option B — Windows NSSM (Non-Sucking Service Manager)

For Windows hosts that need to survive reboots/sleep and run the
tunnel unattended.

**Install NSSM** (no admin needed if you use a per-user copy):
```powershell
Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip"
Expand-Archive "$env:TEMP\nssm.zip" -DestinationPath "$env:USERPROFILE\nssm" -Force
```

**Register cloudflared as a service:**
```powershell
$nssm = "$env:USERPROFILE\nssm\nssm-2.24\win64\nssm.exe"
& $nssm install CloudflaredSandboxRPG "C:\Users\kitap\cloudflared.exe" "tunnel --url http://localhost:8000 --no-autoupdate"
& $nssm set CloudflaredSandboxRPG AppDirectory "C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp"
& $nssm set CloudflaredSandboxRPG AppStdout "C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\cloudflared.log"
& $nssm set CloudflaredSandboxRPG AppStderr "C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\cloudflared.log"
& $nssm set CloudflaredSandboxRPG AppRotateFiles 1
& $nssm set CloudflaredSandboxRPG AppRotateBytes 1048576
& $nssm set CloudflaredSandboxRPG Start SERVICE_AUTO_START
& $nssm set CloudflaredSandboxRPG AppExit Default Restart
& $nssm set CloudflaredSandboxRPG AppRestartDelay 5000
```

**Control the service:**
```powershell
nssm start CloudflaredSandboxRPG
nssm status CloudflaredSandboxRPG
nssm stop CloudflaredSandboxRPG
nssm restart CloudflaredSandboxRPG
nssm remove CloudflaredSandboxRPG confirm   # uninstall
```

**Caveat:** the Quick Tunnel URL still changes on every `nssm start`.
For a stable URL, the service needs to also call a small script that
parses the new URL out of `cloudflared.log` and updates Vercel via
the Vercel API. That's outside the scope of this doc — see § 8 for
the named-tunnel upgrade.

### Option C — Keep Quick Tunnel, accept the restart dance (1 script)

If you only need the tunnel for an evening of testing and don't want
to install NSSM or move to Linux, use the included one-shot script:

- **Windows:** `scripts\start_demo_public.bat`
- **Unix:**   `scripts/start_demo_public.sh`

Both scripts:
1. Kill any stale `uvicorn` / `cloudflared` processes from previous runs
2. Start the backend in a new window (`.bat`) or background (`.sh`)
3. Start `cloudflared` and tail its log until the URL appears
4. Print the new URL plus the Vercel env commands you need to run

**Usage (Windows):**
```powershell
cd C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp
.\scripts\start_demo_public.bat
```

**Usage (Unix / Git Bash):**
```bash
cd /c/Users/kitap/.openclaw/workspace/sandbox-rpg-tmp
./scripts/start_demo_public.sh
```

You still need to update the Vercel env vars after each run, but the
script collapses the manual "open 2 terminals + copy URL" sequence
into a single command. See `scripts/start_demo_public.{bat,sh}` for
the exact implementation.

---

*Last updated: 2026-06-06 (Sections 11+12 added by deployment-relaunch subagent)*

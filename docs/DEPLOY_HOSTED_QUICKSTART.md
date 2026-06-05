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

---

## Appendix B — Quick reference card

**Start:** T1 = `uvicorn backend.app_with_memory:app --host 0.0.0.0 --port 8000` · T2 = `cloudflared tunnel --url http://localhost:8000 --no-autoupdate`
**Verify:** `curl.exe --ssl-no-revoke https://YOUR_URL/health`
**Stop:** `Ctrl+C` in both, or `Get-Process -Name cloudflared,python | Stop-Process -Force`

---

*Last updated: 2026-06-06 (verified by deployment-verify subagent)*

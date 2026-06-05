# 🚀 Local Deploy Quickstart — Sandbox RPG on BAZOOKA

> **Verified:** 2026-06-05 — backend boot ✅, frontend static server ✅, E2E HTTP round-trip ✅.
> **Audience:** anyone (future you included) who wants to bring the framework up on their dev machine in < 5 minutes.

---

## 1. Overview

This guide covers the **local-only deployment** of OpenClaw Sandbox RPG on a single dev machine (Windows / macOS / Linux). Two processes, no containers, no cloud.

**What you get:**

| Component | Port | Process | Purpose |
|-----------|------|---------|---------|
| FastAPI backend | **8000** | `uvicorn backend.app_with_memory:app` | All 23 endpoints (18 gameplay + 4 memory + 1 demo) |
| Static demo server | **5173** | `python backend/scripts/serve_demo.py` | Serves `demo.html` (and the whole repo root) with CORS-friendly headers |

**Scope (hard caps — do not exceed):**

- **1–4 concurrent human players** per scene
- **Up to 100 NPCs** per scene, each with Memory Palace + character parameters
- **Single-machine only** — no cluster, no remote DB, no load balancer

**What's NOT in scope** (per `PHASE_G1_SUMMARY.md` and user scope-lock):

- ❌ Docker / docker-compose deploy
- ❌ Pi5 deploy (Phase D5 removed; G2 skipped)
- ❌ Cloud / Vercel / Cloudflare / production WSGI behind nginx
- ❌ Multi-tenant or public-internet exposure
- ❌ Real `MiniMax-M3` cloud LLM (optional via env var, see §7)

If you need any of the above, **stop and discuss scope first**. This guide assumes local-only.

---

## 2. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | **3.11+** | Tested on 3.14.3; 3.11 / 3.12 also work |
| Disk | ~500 MB | `.venv` + LanceDB + aiosqlite + demo.html ≈ 350 MB |
| LM Studio | **optional** | Only needed for the local **R1-14B audit** path; without it the system uses `MockLLMClient` (audit disabled, R1 fail-closed becomes "no R1") |
| Network | **none** | Backend + frontend are both localhost; no external calls unless MiniMax is wired (see §7) |

> **Already cloned?** If you have the repo + a working `.venv` from `README.md` §Quick Start, you can skip to §3.3.

---

## 3. 5-Command Quickstart

The 5 commands below are **copy-pasteable** on Windows PowerShell (the verified host). macOS / Linux equivalents are noted inline.

```powershell
# 1. Clone
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg           # or: cd sandbox-rpg-tmp if you already have it

# 2. Create venv + install deps (~ 60 s on a warm pip cache)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
# macOS / Linux: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt

# 3. (Optional but recommended) verify the install
.venv\Scripts\python.exe -m pytest backend/tests/ -q
# Expected: 322 passed in ~ 30 s
# If 0 tests run or modules missing, re-run step 2.

# 4. Start the backend (port 8000)
.venv\Scripts\python.exe -m uvicorn backend.app_with_memory:app --port 8000
# Leave this terminal open. Expected log:
#   [Mode] DEMO MODE — no DB required
#   [Startup] Ready. Try: curl http://localhost:8000/health
```

In a **second terminal**:

```powershell
# 5. Start the demo frontend (port 5173)
.venv\Scripts\python.exe backend/scripts/serve_demo.py
# Expected log:
#   [serve_demo] Serving demo.html from C:\...\sandbox-rpg-tmp
#   [serve_demo] Open http://localhost:5173/demo.html
```

Open **http://localhost:5173/demo.html** in your browser. You should see the character list and scene map render within ~ 1 s.

**Total wall-clock:** ~ 3 minutes from a clean clone to a working UI (most of it spent on `pip install`).

---

## 4. Verification (run after §3)

```powershell
# 4.1 Backend health
curl.exe http://localhost:8000/memory/health
# Expected: {"postgres":true,"vector_store":true}

# 4.2 Backend root
curl.exe http://localhost:8000/health
# Expected: {"status":"ok","version":"0.4.0","mode":"demo",...}

# 4.3 Frontend reachable
curl.exe -I http://localhost:5173/demo.html
# Expected: HTTP/1.0 200 OK, Content-Type: text/html, Access-Control-Allow-Origin: *

# 4.4 E2E: remember + recall round-trip
#   (requires Python to build a 384-dim embedding — see snippet below)
```

For 4.4, the cleanest path is a tiny helper:

```python
# e2e_check.py — run from repo root
import json, urllib.request

def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

emb = [round((i % 100) / 100.0, 4) for i in range(384)]
print("remember:", post("http://localhost:8000/memory/remember", {
    "character_id": "deploy_check",
    "content": "Local deploy verification",
    "embedding": emb,
    "memory_type": "episodic",
    "salience": 0.5,
}))
print("recall:  ", post("http://localhost:8000/memory/recall", {
    "character_id": "deploy_check",
    "query_embedding": emb,
    "k": 5,
}))
```

Run it: `.venv\Scripts\python.exe e2e_check.py`. Expected output:

```
remember: {'memory_id': '<uuid4>'}
recall:   {'results': [{'memory_id': '<same uuid>', 'content': 'Local deploy verification', 'similarity': 1.0, ...}]}
```

Similarity **1.0** confirms the same vector round-trips end-to-end (embed → PG → vector store → rehydrate).

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` on port 8000 | Another process owns the port | `netstat -ano \| findstr ":8000 "`, then `taskkill /PID <pid> /F`. Or restart uvicorn with `--port 8001` and update the URLs in `demo.html` (search for `localhost:8000`) |
| `Address already in use` on port 5173 | `serve_demo.py` already running, or another dev server (Vite, etc.) | `netstat -ano \| findstr ":5173 "` and kill. `serve_demo.py` sets `SO_REUSEADDR`, so a quick restart usually works |
| CORS error in browser console: "blocked by CORS policy" | Opened `demo.html` via `file://` or via a non-5173 port | **Always use `serve_demo.py`** — it serves on the same port that backend's CORS allowlist expects (5173) |
| `curl` is `Invoke-WebRequest` and complains about missing args | PowerShell aliases `curl` to `Invoke-WebRequest` | Use `curl.exe` (the real binary) or `Invoke-WebRequest -UseBasicParsing http://...` |
| `ModuleNotFoundError: No module named 'fastapi'` (or similar) on uvicorn start | venv not activated, or step 2 skipped | Re-run step 2: `.venv\Scripts\python.exe -m pip install -r backend/requirements.txt` |
| `/memory/health` returns `{"postgres": false, ...}` | `PERSISTENCE_MODE=postgres` set without a working `DATABASE_URL` | Unset both, or use the default (aiosqlite under `./data/memory_palace_integration.db`, created on first request). The default **always** reports `postgres: true` because it routes through the same SQLAlchemy engine |
| R1 audit times out / 429 from LM Studio | LM Studio server not on port 1234, or model still loading | The audit hook is **fail-closed** by design — if R1 is unavailable, action commits are blocked. Open LM Studio → Developer → Local Server → Enable, port 1234. Until then, the LLM path runs in mock mode (no audit, no fail-closed) |
| `demo.html` loads but every fetch returns ECONNREFUSED | Backend not started, or on a different port | Confirm `http://localhost:8000/health` returns JSON. If you started on `--port 8001`, edit the `API_BASE` constant at the top of `demo.html` |
| `aiosqlite` "database is locked" under heavy E2E | The demo data dir (`.//data/...`) collided with a previous run | Stop the backend, delete `data/memory_palace_integration.db`, restart |
| Test suite reports import errors for `apscheduler` or `lancedb` | Step 2 was skipped or interrupted | `pip install -r backend/requirements.txt` again — Phase B2 added `apscheduler>=3.10,<4.0` |

---

## 6. Scope Lock (re-stated)

> **This guide is local-only by design.** Do not attempt any of the following:
>
> 1. Running the backend on `0.0.0.0` exposed to a LAN
> 2. Putting it behind nginx / Caddy / a reverse proxy
> 3. Deploying to Pi5, a VPS, Vercel, Cloudflare, Fly.io, or any cloud
> 4. Running docker-compose in production mode
> 5. Exposing the WS endpoint to the public internet
>
> Per `PHASE_G1_SUMMARY.md`: **G2 (Real Docker E2E) and G3 (Context Pruning) are permanently skipped** — local-only scope. If a future requirement needs anything above, it is a scope change, not a deploy task.

---

## 7. Optional — Real MiniMax-M3 Wire-up

By default the backend uses a **mock narrative generator** (deterministic, fast, no network). To wire a real LLM:

```powershell
# 7.1 Set the env var (PowerShell — current process only)
$env:ANTHROPIC_API_KEY = "sk-...your-key..."
# (or MINIMAX_API_KEY, depending on backend/api/llm_client.py's expected name)

# 7.2 Start the backend in the same shell
.venv\Scripts\python.exe -m uvicorn backend.app_with_memory:app --port 8000
```

**What changes when the env var is set:**

- `MockLLMClient` is replaced by the real `llm_client` (`backend/llm_client.py`)
- Action commits go through G1's retry loop (`max_retries=2`)
- Audit hook tries to call LM Studio on `:1234`; if LM Studio is down, **the action is blocked** (fail-closed)

**What does NOT change:**

- The 5-command quickstart structure
- The static-server / CORS / port assumptions
- The data layer (still aiosqlite by default)

> **Cost / rate-limit note:** The real M3 path is rate-limited. If you see HTTP 429 from MiniMax, back off 30 s and retry; the G1 retry mechanism handles per-call 429s up to 2 retries, but sustained 429s require a wait.

---

## 8. What you should see end-to-end

| Step | Expected |
|------|----------|
| `pip install` finishes | `Successfully installed fastapi-0.110.0 ...` (no errors) |
| `pytest -q` | `322 passed in ~ 30 s` |
| Backend boot log | `[Mode] DEMO MODE — no DB required` → `[Startup] Ready` → `Uvicorn running on http://127.0.0.1:8000` |
| `serve_demo.py` log | `[serve_demo] Serving demo.html from ...` → `[serve_demo] Open http://localhost:5173/demo.html` |
| Browser at `/demo.html` | Character list + scene map render; clicking an action triggers a `POST /api/action/process` round-trip (visible in DevTools Network tab) |
| `curl /memory/health` | `{"postgres":true,"vector_store":true}` |

If all of the above match, **you are locally deployed**. 🎉

---

## 9. Where to go next

- **Read the architecture:** `docs/ARCHITECTURE.md`
- **Understand the Memory Palace:** `docs/WAVE2_MEMORY_PALACE.md`
- **See what shipped and what's next:** `docs/PHASE_ROADMAP.md`
- **Last delivery report:** `docs/PHASE_G1_SUMMARY.md` (current cap: 322/322 tests, G2 + G3 permanently skipped)

---

_Last verified 2026-06-05 on BAZOOKA (Windows 10.0.26200, Python 3.14.3, .venv from `backend/requirements.txt`). Three-step verification (backend boot / frontend static server / E2E HTTP round-trip) all green; no blockers found._

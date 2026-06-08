# 🚀 Local Deploy Quickstart — Sandbox RPG on BAZOOKA

> **Verified:** 2026-06-05 — backend boot ✅, frontend static server ✅, E2E HTTP round-trip ✅.
> **Audience:** anyone (future you included) who wants to bring the framework up on their dev machine in < 5 minutes.

---

## 1. Overview

This guide covers the **local-only deployment** of OpenClaw Sandbox RPG on a single dev machine (Windows / macOS / Linux). Two processes, no containers, no cloud.

**What you get:**

| Component | Port | Process | Purpose |
|-----------|------|---------|---------|
| FastAPI backend | **8000** | `uvicorn backend.main:app` | Backend API + Static Vue SPA fallback |
| Vue 3 SPA Dev Server | **5173** | `npm run dev` (in `frontend/`) | Premium UI Developer server (Vite) |


**Scope (hard caps — do not exceed):**

- **1–4 concurrent human players** per scene
- **Up to 100 NPCs** per scene, each with Memory Palace + character parameters
- **Single-machine only** — no cluster, no remote DB, no load balancer

**What is now IN SCOPE** (Phase L2 Shipped):

- ✅ Production Postgres 15 database integration
- ✅ Hosted deployment using Cloudflared Tunnel (rpg.kitahim.uk)
- ✅ Seamless Vue 3 SPA compilation and backend integration
- ✅ Fail-loud production safety checks (preventing fallback in production env)


---

## 2. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | **3.11+** | Tested on 3.14.3; 3.11 / 3.12 / 3.13 also work |
| Disk | ~500 MB | `.venv` + LanceDB + aiosqlite + frontend assets ≈ 350 MB |
| Node.js | **20+** | Required to build and run the Vue 3 Vite frontend |
| LM Studio | **optional** | Only needed for the local **R1-14B audit** path; without it the system uses `MockLLMClient` |
| Network | **none** | Backend + frontend are both localhost; no external calls unless MiniMax is wired |


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

# 3. (Optional but recommended) verify the install (exclude smoke test if Postgres is offline)
.venv\Scripts\python.exe -m pytest backend/tests/ -k "not test_production_smoke"
# Expected: 381 passed in ~10s
# If 0 tests run or modules missing, re-run step 2.

# 4. Start the backend (port 8000)
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
# Leave this terminal open. Expected log:
#   [Mode] DEMO MODE — no DB required
#   [Startup] Ready
```

In a **second terminal**:

```powershell
# 5. Start the frontend developer server (port 5173)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser. You should see the login/lobby screen render within ~ 1 s.


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

# 4.3 Frontend reachable via API fallback or Vite server
curl.exe -I http://localhost:5173/
# Expected: HTTP/1.1 200 OK


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

| `Address already in use` on port 8000 | Another process owns the port | Kill previous process or run backend on port 8001 |
| `Address already in use` on port 5173 | Vite dev server already running | Kill previous Vite process |
| CORS error in browser console | Incorrect origin configuration | Run frontend and backend on expected origins or set CORS_ORIGINS environment variable |
| `ModuleNotFoundError: No module named 'fastapi'` | venv not activated | Activate virtual environment: `.venv\Scripts\activate` |
| R1 audit times out | LM Studio server down or loading | Verify LM Studio server is running on port 1234 |


---

## 6. Scope Lock (re-stated)

> **This guide focuses on local development deployment.** For full-scale production deployment including Cloudflare Tunnel, database setup, and process daemonization, refer to `deploy/` scripts and `L2_E_deploy.ps1`.


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
| `pip install` finishes | Successfully installed deps |
| `pytest` | Unit tests pass |
| Backend boot log | `[Mode] DEMO MODE` → `[Startup] Ready` |
| Frontend Dev Server | `Local: http://localhost:5173/` |
| Browser at localhost | Login/lobby page renders |
| `curl /health` | `{"status":"ok", ...}` |


If all of the above match, **you are locally deployed**. 🎉

---

## 9. Where to go next

- **Read the architecture:** `docs/ARCHITECTURE.md`
- **Understand the Memory Palace:** `docs/WAVE2_MEMORY_PALACE.md`
- **See what shipped and what's next:** `docs/PHASE_ROADMAP.md`
- **Last delivery report:** `docs/PHASE_G1_SUMMARY.md` (current cap: 322/322 tests, G2 + G3 permanently skipped)

---

_Last verified 2026-06-05 on BAZOOKA (Windows 10.0.26200, Python 3.14.3, .venv from `backend/requirements.txt`). Three-step verification (backend boot / frontend static server / E2E HTTP round-trip) all green; no blockers found._

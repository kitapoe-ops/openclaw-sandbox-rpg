#!/usr/bin/env bash
# ============================================================================
# start_demo_public.sh
# ----------------------------------------------------------------------------
# One-shot bring-up for the Sandbox-RPG demo on Unix / Git Bash / WSL:
#   1. Kill any stale uvicorn / cloudflared processes from previous runs
#   2. Start backend (port 8000) in the background
#   3. Start cloudflared Quick Tunnel in the background
#   4. Tail the tunnel log until the new *.trycloudflare.com URL appears
#   5. Print the URL + Vercel env commands
#
# Usage (from repo root):
#   ./scripts/start_demo_public.sh
#
# Stop everything later with:
#   ./scripts/stop_demo_public.sh
# ============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# cloudflared binary - default user-mode install on Windows
CLOUDFLARED_EXE="${CLOUDFLARED_EXE:-$HOME/cloudflared.exe}"
TUNNEL_LOG="$ROOT/cloudflared.log"
BACKEND_LOG="$ROOT/uvicorn.out.log"
BACKEND_ERR="$ROOT/uvicorn.err.log"
BACKEND_PID_FILE="$ROOT/.uvicorn.pid"
TUNNEL_PID_FILE="$ROOT/.cloudflared.pid"

cleanup_on_exit() {
    # Don't kill the children on Ctrl+C - they should keep running.
    # This is just to reset the shell prompt cleanly.
    :
}

trap cleanup_on_exit EXIT INT TERM

echo "=== [1/5] Killing stale uvicorn / cloudflared (if any) ================="
# Anything listening on :8000
if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -ti :8000 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        echo "  killing $(echo "$PIDS" | wc -w | tr -d ' ') stale :8000 listener(s)"
        kill -9 $PIDS 2>/dev/null || true
    fi
fi
pkill -9 -f "uvicorn backend.app_with_memory" 2>/dev/null || true
pkill -9 -f "cloudflared tunnel"               2>/dev/null || true

echo
echo "=== [2/5] Starting backend (uvicorn) in background ===================="
# Pick the venv python. On Windows under Git Bash, .venv\Scripts\python.exe.
if [[ -x ".venv/Scripts/python.exe" ]]; then
    PY=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
    PY=".venv/bin/python"
else
    echo "  ERROR: .venv python not found (looked for .venv/Scripts/python.exe and .venv/bin/python)"
    exit 1
fi

nohup "$PY" -m uvicorn backend.app_with_memory:app --host 0.0.0.0 --port 8000 \
    >"$BACKEND_LOG" 2>"$BACKEND_ERR" </dev/null &
echo $! >"$BACKEND_PID_FILE"
echo "  backend pid: $(cat "$BACKEND_PID_FILE")"

# Wait for :8000 to start listening (max 30s)
echo "  waiting for backend to bind :8000 ..."
for _ in $(seq 1 30); do
    if (echo > /dev/tcp/127.0.0.1/8000) >/dev/null 2>&1; then
        echo "  backend is up. Logs: $BACKEND_LOG / $BACKEND_ERR"
        break
    fi
    sleep 1
done

if ! (echo > /dev/tcp/127.0.0.1/8000) >/dev/null 2>&1; then
    echo "  ERROR: backend failed to bind :8000 within 30s. Check $BACKEND_ERR."
    exit 1
fi

echo
echo "=== [3/5] Starting cloudflared Quick Tunnel in background ============="
if [[ ! -x "$CLOUDFLARED_EXE" && ! -f "$CLOUDFLARED_EXE" ]]; then
    echo "  ERROR: cloudflared not found at $CLOUDFLARED_EXE"
    echo "  Set CLOUDFLARED_EXE env var, or install per docs/DEPLOY_HOSTED_QUICKSTART.md §2"
    exit 1
fi

: >"$TUNNEL_LOG"
nohup "$CLOUDFLARED_EXE" tunnel --url http://localhost:8000 --no-autoupdate \
    >"$TUNNEL_LOG" 2>&1 </dev/null &
echo $! >"$TUNNEL_PID_FILE"
echo "  tunnel pid:  $(cat "$TUNNEL_PID_FILE")"

echo
echo "=== [4/5] Waiting for trycloudflare.com URL in tunnel log =============="
echo "  (this usually takes ~6-10 seconds)"
TUNNEL_URL=""
for _ in $(seq 1 30); do
    sleep 1
    # cloudflared prints the URL inside an ASCII-art box like:
    #   |  https://abc-def-ghi.trycloudflare.com  |
    TUNNEL_URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$TUNNEL_LOG" 2>/dev/null | head -1 || true)
    if [[ -n "$TUNNEL_URL" ]]; then
        break
    fi
done

if [[ -z "$TUNNEL_URL" ]]; then
    echo "  ERROR: never got a trycloudflare.com URL. Last 20 log lines:"
    tail -n 20 "$TUNNEL_LOG" || true
    exit 1
fi

echo
echo "=== [5/5] Tunnel is live ================================================"
echo
echo "  $TUNNEL_URL"
echo
echo "  --- Quick checks -----------------------------------------------------"
echo "  curl --ssl-no-revoke $TUNNEL_URL/health"
echo "  curl --ssl-no-revoke $TUNNEL_URL/memory/health"
echo
echo "  --- Update Vercel env vars (project -> Settings -> Env Vars) ----------"
echo "  VITE_API_BASE_URL = $TUNNEL_URL"
echo "  VITE_WS_BASE_URL  = ${TUNNEL_URL/https:/wss:}"
echo
echo "  Then run:  vercel --prod"
echo
echo "  --- When done --------------------------------------------------------"
echo "  kill \$(cat .uvicorn.pid) \$(cat .cloudflared.pid)"
echo "  # or just: pkill -f 'uvicorn backend.app_with_memory'; pkill -f 'cloudflared tunnel'"
echo

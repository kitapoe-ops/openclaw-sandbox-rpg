#!/usr/bin/env bash
# HTTP smoke test for the OpenClaw Sandbox RPG FastAPI backend.
#
# Starts uvicorn on port 8765 in the background, seeds demo data, hits
# /health, /api/character/<id>, /api/world/<id>/state,
# /api/action/submit (expected 400, no scene), /api/scene/<id>/seed,
# and /api/action/submit again (expected 200), then kills uvicorn.
#
# Prints PASS / FAIL for each of 6 steps and a final summary.
#
# The Traditional-Chinese JSON request bodies are loaded from
# scripts/action_body.json and scripts/seed_body.json. character_id in
# action_body.json is patched at runtime with the id from the seed script.
#
# Usage:   bash scripts/smoke_test.sh
# Exit:    0 if all 6 steps PASS, non-zero otherwise.

set -u
set -o pipefail

# ============================================================
# Config
# ============================================================
PORT="${PORT:-8765}"
HOST_ADDR="${HOST_ADDR:-127.0.0.1}"
WAIT_SECONDS="${WAIT_SECONDS:-3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Pick a python interpreter
if [ -x "$PROJECT_ROOT/.venv/Scripts/python.exe" ]; then
    PYTHON="$PROJECT_ROOT/.venv/Scripts/python.exe"
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

SEED_SCRIPT="$PROJECT_ROOT/backend/seed_demo.py"
ACTION_BODY_FILE="$SCRIPT_DIR/action_body.json"
SEED_BODY_FILE="$SCRIPT_DIR/seed_body.json"
BASE_URL="http://${HOST_ADDR}:${PORT}"
LOG_FILE="$PROJECT_ROOT/smoke_test.log"

# ============================================================
# State
# ============================================================
PASS_COUNT=0
FAIL_COUNT=0

log() {
    local msg="[$(date +%H:%M:%S)] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

step() {
    local num="$1"; local name="$2"; local ok="$3"; local detail="$4"
    if [ "$ok" = "true" ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
        log "  PASS step ${num}: ${name}  ${detail}"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        log "  FAIL step ${num}: ${name}  ${detail}"
    fi
}

# Returns "STATUS_CODE|BODY" or "000|err"
http_call() {
    local method="$1"; local url="$2"; local body_file="${3:-}"
    local code; local resp
    if [ -n "$body_file" ]; then
        code=$(curl -s -m 60 -o /dev/null -w "%{http_code}" \
            -X "$method" -H "Content-Type: application/json" \
            --data-binary "@${body_file}" "$url" 2>/dev/null || echo "000")
        resp=$(curl -s -m 60 -X "$method" -H "Content-Type: application/json" \
            --data-binary "@${body_file}" "$url" 2>/dev/null)
    else
        code=$(curl -s -m 60 -o /dev/null -w "%{http_code}" -X "$method" "$url" 2>/dev/null || echo "000")
        resp=$(curl -s -m 60 -X "$method" "$url" 2>/dev/null)
    fi
    echo "${code}|${resp}"
}

# Substitute the literal placeholder "char_starter_aria" in action_body.json
# with the actual id, write to a tmp file, return the path.
patch_action_body() {
    local character_id="$1"
    local out
    out=$(mktemp)
    # Use python for safe JSON editing (handles UTF-8 cleanly)
    "$PYTHON" - "$ACTION_BODY_FILE" "$character_id" "$out" <<'PY'
import json, sys
src, cid, dst = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, "r", encoding="utf-8") as f:
    data = json.load(f)
data["character_id"] = cid
with open(dst, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
PY
    echo "$out"
}

# ============================================================
# Start
# ============================================================
: > "$LOG_FILE"

log "============================================================"
log "OpenClaw Sandbox RPG - HTTP smoke test (bash)"
log "Project: $PROJECT_ROOT"
log "Port:    $PORT"
log "Python:  $PYTHON"
log "============================================================"

if [ ! -f "$SEED_SCRIPT" ]; then
    log "FATAL: seed script not found at $SEED_SCRIPT"
    exit 2
fi

# 1. Start uvicorn in background
UVICORN_STDOUT="$PROJECT_ROOT/uvicorn.out.log"
UVICORN_STDERR="$PROJECT_ROOT/uvicorn.err.log"
: > "$UVICORN_STDOUT"
: > "$UVICORN_STDERR"

log "Starting uvicorn (with in-process seed)..."

# Build a one-file Python launcher that calls seed_all() and then runs
# uvicorn.run() in the SAME process so the in-memory `store` is shared.
#
# The launcher script uses `os.path.dirname(__file__)` to locate the project
# root, so it works on Linux/macOS (POSIX paths) and Windows (Windows-style
# paths) without us having to embed a brittle path string.
UVICORN_LAUNCHER="$PROJECT_ROOT/uvicorn_launcher.py"
cat > "$UVICORN_LAUNCHER" <<'PYEOF'
import os
import sys
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
import backend.seed_demo as s
result = s.seed_all(verbose=False)
print('CHARACTER_ID=' + result['character_id'])
print('WORLD_ID=' + result['world_id'])
print('CHARACTER_NAME=' + result['character_name'])
sys.stdout.flush()
import uvicorn
from backend.main import app
PORT = int(os.environ.get('SMOKE_TEST_PORT', '8765'))
HOST = os.environ.get('SMOKE_TEST_HOST', '127.0.0.1')
uvicorn.run(app, host=HOST, port=PORT, log_level='info')
PYEOF

# Pass host/port via env vars so the launcher doesn't need them inlined.
export SMOKE_TEST_HOST="$HOST_ADDR"
export SMOKE_TEST_PORT="$PORT"

cd "$PROJECT_ROOT"

# When invoking a Windows .exe from WSL or Git-Bash, the shell's POSIX->Win
# path translation can mangle /mnt/c/... paths into C:\mnt\c\... (wrong),
# and POSIX shells cannot directly exec a Windows path. To avoid those
# issues, we detect the interop environment and fall back to the
# PowerShell version of the smoke test if it's available.
RUN_VIA_PWSH=""
if [ -n "${WSL_DISTRO_NAME:-}" ] || [ -n "${WSLENV:-}" ]; then
    RUN_VIA_PWSH="true"
fi
# On Git-Bash (MSYS), python.exe usually works directly with POSIX paths.
if [ -z "$RUN_VIA_PWSH" ] && command -v cmd.exe >/dev/null 2>&1 && uname -s | grep -qiE 'mingw|msys|cygwin'; then
    RUN_VIA_PWSH=""
fi

if [ -n "$RUN_VIA_PWSH" ] && command -v powershell.exe >/dev/null 2>&1; then
    log "Detected WSL — delegating to scripts/smoke_test.ps1 (PowerShell is more reliable on WSL)."
    WIN_PS1=$(wslpath -w "$SCRIPT_DIR/smoke_test.ps1" 2>/dev/null)
    if [ -n "$WIN_PS1" ]; then
        powershell.exe -ExecutionPolicy Bypass -File "$WIN_PS1"
        exit $?
    fi
fi

# Native Linux/macOS path: launch python directly.
"$PYTHON" "$UVICORN_LAUNCHER" \
    >"$UVICORN_STDOUT" 2>"$UVICORN_STDERR" &
UVICORN_PID=$!
log "Uvicorn PID = $UVICORN_PID, waiting ${WAIT_SECONDS}s for startup..."
sleep "$WAIT_SECONDS"

# Probe /health; if down, wait up to 6 more seconds
STARTED=false
for i in 1 2 3; do
    RES=$(http_call GET "$BASE_URL/health")
    CODE="${RES%%|*}"; BODY="${RES#*|}"
    if [ "$CODE" = "200" ] && echo "$BODY" | grep -q '"status":"ok"'; then
        STARTED=true; break
    fi
    sleep 2
done

if [ "$STARTED" != "true" ]; then
    log "FATAL: uvicorn failed to start within timeout."
    log "--- uvicorn stdout (last 50) ---"
    tail -n 50 "$UVICORN_STDOUT" | while read -r line; do log "  $line"; done
    log "--- uvicorn stderr (last 50) ---"
    tail -n 50 "$UVICORN_STDERR" | while read -r line; do log "  $line"; done
    kill -9 "$UVICORN_PID" 2>/dev/null || true
    rm -f "$UVICORN_LAUNCHER" 2>/dev/null || true
    exit 3
fi
log "Uvicorn up (PID $UVICORN_PID)."

# 2. Parse CHARACTER_ID / WORLD_ID from launcher stdout
# (the seed ran in the same process as uvicorn, so its output is in the
# uvicorn.out.log file we just captured).
log "Reading seed output from launcher..."
SEED_OUT=""
if [ -f "$UVICORN_STDOUT" ]; then
    SEED_OUT=$(head -n 20 "$UVICORN_STDOUT")
    echo "$SEED_OUT" | while read -r line; do
        [ -n "$line" ] && log "  seed: $line"
    done
fi

CHARACTER_ID=$(echo "$SEED_OUT" | sed -n 's/^CHARACTER_ID=\(.*\)$/\1/p' | head -1)
WORLD_ID=$(echo "$SEED_OUT"     | sed -n 's/^WORLD_ID=\(.*\)$/\1/p'     | head -1)
CHARACTER_ID=${CHARACTER_ID:-char_starter_aria}
WORLD_ID=${WORLD_ID:-dnd_5e_forgotten_realms}
log "Using character_id='$CHARACTER_ID', world_id='$WORLD_ID'"

# Build the patched action body file (UTF-8 with right character_id)
ACTION_BODY_PATCHED=$(patch_action_body "$CHARACTER_ID")
# Note: cleanup trap is set later so we don't accidentally clobber the
# patched file before HTTP calls happen.

# ============================================================
# Run all 6 steps (kill uvicorn in any exit path)
# ============================================================
cleanup() {
    log "Stopping uvicorn PID $UVICORN_PID..."
    if [ -n "${UVICORN_PID:-}" ]; then
        kill -TERM "$UVICORN_PID" 2>/dev/null || true
        sleep 0.5
        kill -KILL "$UVICORN_PID" 2>/dev/null || true
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti tcp:"$PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    fi
    rm -f "$UVICORN_LAUNCHER" 2>/dev/null || true
}
trap 'cleanup; rm -f "$ACTION_BODY_PATCHED" 2>/dev/null' EXIT

# ---- Step 1: GET /health
RES=$(http_call GET "$BASE_URL/health")
CODE="${RES%%|*}"; BODY="${RES#*|}"
OK=false
if [ "$CODE" = "200" ] && echo "$BODY" | grep -q '"status":"ok"'; then OK=true; fi
step 1 "/health" "$OK" "(status=$CODE)"

# ---- Step 2: GET /api/character/<id>
RES=$(http_call GET "$BASE_URL/api/character/$CHARACTER_ID")
CODE="${RES%%|*}"; BODY="${RES#*|}"
OK=false
if [ "$CODE" = "200" ] && echo "$BODY" | grep -q "$CHARACTER_ID"; then OK=true; fi
step 2 "GET /api/character/$CHARACTER_ID" "$OK" "(status=$CODE)"

# ---- Step 3: GET /api/world/<world>/state
RES=$(http_call GET "$BASE_URL/api/world/$WORLD_ID/state")
CODE="${RES%%|*}"; BODY="${RES#*|}"
OK=false
if [ "$CODE" = "200" ] && echo "$BODY" | grep -q "$WORLD_ID"; then OK=true; fi
step 3 "GET /api/world/$WORLD_ID/state" "$OK" "(status=$CODE)"

# ---- Step 4: POST /api/action/submit (expect 400)
RES=$(http_call POST "$BASE_URL/api/action/submit" "$ACTION_BODY_PATCHED")
CODE="${RES%%|*}"; BODY="${RES#*|}"
OK=false
if [ "$CODE" = "400" ] && (echo "$BODY" | grep -q "opt_01" || echo "$BODY" | grep -qi "scene"); then OK=true; fi
step 4 "POST /api/action/submit (no scene -> 400)" "$OK" "(status=$CODE)"

# ---- Step 5: POST /api/scene/<id>/seed
RES=$(http_call POST "$BASE_URL/api/scene/$CHARACTER_ID/seed" "$SEED_BODY_FILE")
CODE="${RES%%|*}"; BODY="${RES#*|}"
OK=false
if [ "$CODE" = "200" ] && echo "$BODY" | grep -q "opt_01"; then OK=true; fi
step 5 "POST /api/scene/$CHARACTER_ID/seed" "$OK" "(status=$CODE)"

# ---- Step 6: POST /api/action/submit (expect 200)
RES=$(http_call POST "$BASE_URL/api/action/submit" "$ACTION_BODY_PATCHED")
CODE="${RES%%|*}"; BODY="${RES#*|}"
OK=false
if [ "$CODE" = "200" ] && echo "$BODY" | grep -q '"scene"'; then OK=true; fi
HAS_SCENE=false
echo "$BODY" | grep -q '"scene"' && HAS_SCENE=true
step 6 "POST /api/action/submit (with scene -> 200)" "$OK" "(status=$CODE, has_scene=$HAS_SCENE)"

# ============================================================
# Final
# ============================================================
TOTAL=$((PASS_COUNT + FAIL_COUNT))
log "============================================================"
log "Smoke test summary: $PASS_COUNT / $TOTAL steps PASS"
if [ "$FAIL_COUNT" -gt 0 ]; then
    log "FAILED steps: $FAIL_COUNT"
    log "============================================================"
    exit 1
fi
log "ALL PASS"
log "============================================================"
exit 0

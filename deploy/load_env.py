"""Load .env into current process env, then exec uvicorn with that env.

This is needed because PowerShell's Start-Process doesn't easily inherit
the .env vars, and using a wrapper script is the cleanest way to start
the backend with the production .env loaded.
"""
import os
import subprocess
import sys
from pathlib import Path

ENV_FILE = Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\.env")

if not ENV_FILE.exists():
    print(f"ERROR: {ENV_FILE} not found", file=sys.stderr)
    sys.exit(1)

for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" in line:
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ[k] = v

# Phase L2-I/Phase C: in case LLM_CLOUD_API_KEY is missing or
# placeholder in .env, fall back to known system env names. This
# avoids Telegram / file-based secret leakage while still letting
# the operator inject the key via `setx MINIMAX_API_KEY=...` or
# the OpenClaw runtime's env-injection feature.
_PLACEHOLDER = "not_us…only"
if not os.environ.get("LLM_CLOUD_API_KEY") or os.environ.get("LLM_CLOUD_API_KEY", "").startswith("not_us"):
    for alt in ("MINIMAX_API_KEY", "MINIMAX_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        v = os.environ.get(alt)
        if v and not v.startswith("not_us"):
            os.environ["LLM_CLOUD_API_KEY"] = v
            print(f"  LLM_CLOUD_API_KEY ← {alt} (len={len(v)})")
            break

print(f"Loaded {len(os.environ)} env vars from {ENV_FILE}")
print(f"  ENV={os.environ.get('ENV')}")
print(f"  DEMO_MODE={os.environ.get('DEMO_MODE')}")
print(f"  POSTGRES_HOST={os.environ.get('POSTGRES_HOST')}")
print(f"  POSTGRES_PASSWORD starts: {os.environ.get('POSTGRES_PASSWORD', 'NOT SET')[:3]}")
print(f"  LLM_CLOUD_API_KEY length: {len(os.environ.get('LLM_CLOUD_API_KEY', ''))}")

# Start uvicorn with the loaded env (inherits via os.environ)
print("\nStarting uvicorn backend.main:app on 0.0.0.0:8000...")
sys.stdout.flush()
sys.stderr.flush()

# Replace current process with uvicorn (so it inherits env)
os.execvp(
    sys.executable,
    [sys.executable, "-m", "uvicorn", "backend.main:app",
     "--host", "0.0.0.0", "--port", "8000"],
)

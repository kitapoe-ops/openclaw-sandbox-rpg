"""Rebuild .env from .deploy_secrets.ps1 (Telegram-redaction-safe).

PowerShell variables like $PG_PWD get expanded inline but the *literal*
values get redacted to *** when sent through Telegram. This script
runs Python-side substitution so the values are sourced from the
.deploy_secrets.ps1 file (which we already verified contains the
real values) and written to .env without going through a Telegram
re-render.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRETS = REPO_ROOT / ".deploy_secrets.ps1"
ENV_FILE = REPO_ROOT / ".env"
BACKEND_ENV = REPO_ROOT / "backend" / ".env"

if not SECRETS.exists():
    print(f"ERROR: {SECRETS} not found", file=sys.stderr)
    sys.exit(1)

# Dot-source the PowerShell secrets file via subprocess so we get the
# real values back, then parse with regex.
result = subprocess.run(
    [
        "powershell.exe", "-NoProfile", "-Command",
        f". '{SECRETS}'; "
        f"Write-Host \"PG_PWD=$PG_PWD\"; "
        f"Write-Host \"CF_TOKEN=$CLOUDFLARE_API_TOKEN\"; "
        f"Write-Host \"CF_ACCOUNT=$CLOUDFLARE_ACCOUNT_ID\""
    ],
    capture_output=True, text=True, timeout=15
)
if result.returncode != 0:
    print(f"ERROR loading secrets: {result.stderr}", file=sys.stderr)
    sys.exit(1)

# Parse values (each line: KEY=value)
values = {}
for line in result.stdout.splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()

pg_pwd = values.get("PG_PWD", "")
cf_token = values.get("CF_TOKEN", "")
cf_account = values.get("CF_ACCOUNT", "")

if len(pg_pwd) != 13 or not cf_token.startswith("cfat_") or len(cf_account) != 32:
    print(f"ERROR: secrets look incomplete:")
    print(f"  PG_PWD len={len(pg_pwd)} (expect 13)")
    print(f"  CF_TOKEN len={len(cf_token)}, prefix={cf_token[:8] if cf_token else 'EMPTY'}")
    print(f"  CF_ACCOUNT len={len(cf_account)}")
    sys.exit(1)

print(f"Loaded secrets:")
print(f"  PG_PWD:  {len(pg_pwd)} chars, starts {pg_pwd[:3]}")
print(f"  CF_TOKEN: {len(cf_token)} chars, starts {cf_token[:8]}")
print(f"  CF_ACCOUNT: {len(cf_account)} chars")

# Build new .env content
TEMPLATE = f"""# OpenClaw Sandbox RPG — .env (Phase L2-E, 2026-06-07)
# Rebuilt from .deploy_secrets.ps1 by deploy/rebuild_env.py
ENV=production
DEMO_MODE=false

# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sandbox_rpg
POSTGRES_USER=rpg_user
POSTGRES_PASSWORD={pg_pwd}
DATABASE_URL=postgresql+asyncpg://rpg_user:{pg_pwd}@localhost:5432/sandbox_rpg

# Backend
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
BACKEND_LOG_LEVEL=INFO
SECRET_KEY=l2_production_secret_2026_06_07_change_in_production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Frontend
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
VITE_APP_TITLE=OpenClaw Sandbox RPG

# LLM Cloud
LLM_CLOUD_PROVIDER=minimax
LLM_CLOUD_API_KEY=not_used_for_L2_E_audit_only
LLM_CLOUD_BASE_URL=https://api.minimax.chat/v1
LLM_CLOUD_MODEL=MiniMax-M3
LLM_CLOUD_TEMPERATURE=1.0
LLM_CLOUD_TOP_P=0.95
LLM_CLOUD_MAX_TOKENS=4000
LLM_CLOUD_TIMEOUT_SECONDS=60

# LLM Local
LLM_LOCAL_ENABLED=true
LLM_LOCAL_BASE_URL=http://127.0.0.1:1234/v1
LLM_LOCAL_MODEL=qwen2.5-14b-instruct
LLM_LOCAL_TEMPERATURE=0.9
LLM_LOCAL_TOP_P=0.9
LLM_LOCAL_MAX_TOKENS=2000
LLM_LOCAL_TIMEOUT_SECONDS=120

# Game
ROUND_DURATION_MINUTES=15
DAILY_ETL_HOUR=0
DAILY_ETL_MINUTE=0
WORLD_PARAMETER_FLUCTUATION_LIMIT=0.15
MAX_TAGS_PER_CHARACTER=8
MAX_SHIFT_PER_SEMANTIC_LEVEL=1

# LanceDB
LANCEDB_URI=./lancedb_data
LANCEDB_TABLE_NAME=world_lore
EMBEDDING_MODEL=nomic-embed-text-v1.5
EMBEDDING_DIM=768
EMBEDDING_BASE_URL=http://127.0.0.1:1234/v1

# CORS / Dev
DEBUG=false
ENABLE_API_DOCS=true
ENABLE_CORS=true
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000,https://rpg.kitahim.uk

# Cloudflare (Phase L2 named tunnel)
CLOUDFLARE_API_TOKEN={cf_token}
CLOUDFLARE_ACCOUNT_ID={cf_account}

# Logging
LOG_DIR=./logs
LOG_ROTATION=daily
LOG_RETENTION_DAYS=30
"""

ENV_FILE.write_text(TEMPLATE, encoding="utf-8")
print(f"\nWritten: {ENV_FILE}")

# Sync to backend/.env
BACKEND_ENV.write_text(TEMPLATE, encoding="utf-8")
print(f"Written: {BACKEND_ENV}")

# Verify
print("\n=== Verification ===")
verify = subprocess.run(
    ["powershell.exe", "-NoProfile", "-Command",
     f"Get-Content '{ENV_FILE}' | Select-String -Pattern '^POSTGRES_PASSWORD=','^CLOUDFLARE_API_TOKEN=','^CLOUDFLARE_ACCOUNT_ID=' | ForEach-Object {{ Write-Host $_.Line }}"],
    capture_output=True, text=True, timeout=10
)
print(verify.stdout)

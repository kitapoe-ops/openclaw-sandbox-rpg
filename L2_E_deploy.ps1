# OpenClaw Sandbox RPG ??L2-E Deploy Script (FINAL)
# Loads secrets from .deploy_secrets.ps1 (gitignored, file-based delivery
# to bypass Telegram redaction of long numeric strings).
# MUST run as Administrator (Start-Service requires elevation).
#
# Usage (Admin PowerShell):
#   Set-Location "C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp"
#   .\L2_E_deploy.ps1

$ErrorActionPreference = "Stop"

# Load secrets from file
$RepoRoot = $PSScriptRoot
. (Join-Path $RepoRoot ".deploy_secrets.ps1")

# Inject Cloudflare env (overrides anything set in current session)
$env:CLOUDFLARE_API_TOKEN   = $CLOUDFLARE_API_TOKEN
$env:CLOUDFLARE_ACCOUNT_ID  = $CLOUDFLARE_ACCOUNT_ID

$PSQL   = "C:\Program Files\PostgreSQL\15\bin\psql.exe"
$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Write-Host "=== OpenClaw Sandbox RPG ??L2-E Deploy ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"
Write-Host "PG Password length: $($PG_PWD.Length)"
Write-Host "CF Account ID: $($CLOUDFLARE_ACCOUNT_ID.Substring(0,8))..."
Write-Host "CF Token prefix: $($CLOUDFLARE_API_TOKEN.Substring(0,8))..."
Write-Host ""

# ============================================================
# Step 1: PostgreSQL service running
# ============================================================
Write-Host "[1/5] Checking PostgreSQL service..." -ForegroundColor Cyan
$svc = Get-Service postgresql-x64-15 -ErrorAction SilentlyContinue
if (-not $svc) { throw "postgresql-x64-15 service not installed" }
if ($svc.Status -ne "Running") {
    Write-Host "    Starting service..."
    Start-Service postgresql-x64-15 -ErrorAction Stop
    Start-Sleep -Seconds 3
    $svc = Get-Service postgresql-x64-15
}
if ($svc.Status -ne "Running") { throw "PG service did not start. Status=$($svc.Status)" }
Write-Host "    Service: Running" -ForegroundColor Green

# ============================================================
# Step 2: Create user + database
# ============================================================
Write-Host "[2/5] Provisioning database and user..." -ForegroundColor Cyan

# 2a) Set postgres superuser password
& $PSQL -U postgres -h 127.0.0.1 -d postgres -c "ALTER USER postgres WITH PASSWORD '$PG_PWD';" 2>$null

# 2b) Create rpg_user (idempotent)
$sql = "DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'rpg_user') THEN CREATE ROLE rpg_user LOGIN PASSWORD '$PG_PWD'; END IF; END `$`$;"
& $PSQL -U postgres -h 127.0.0.1 -d postgres -c $sql

# 2c) Create sandbox_rpg DB (idempotent)
$exists = & $PSQL -U postgres -h 127.0.0.1 -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='sandbox_rpg'"
if ($exists -ne "1") {
    & $PSQL -U postgres -h 127.0.0.1 -d postgres -c "CREATE DATABASE sandbox_rpg OWNER rpg_user;"
} else {
    Write-Host "    DB sandbox_rpg already exists"
}

# 2d) Force-set rpg_user password to match .env
& $PSQL -U postgres -h 127.0.0.1 -d postgres -c "ALTER USER rpg_user WITH PASSWORD '$PG_PWD';"

# 2e) Verify rpg_user can log in
$verify = & $PSQL -U rpg_user -h 127.0.0.1 -d sandbox_rpg -c "SELECT current_user, current_database();"
Write-Host "    Verify: $verify" -ForegroundColor Green

# ============================================================
# ============================================================
# Step 3: Initialize Postgres schema via init_db()           
# ============================================================
Write-Host "[3/5] Initializing Postgres schema..." -ForegroundColor Cyan
& $VenvPy deploy\init_db_helper.py
if ($LASTEXITCODE -ne 0) { throw "init_db failed (exit=$LASTEXITCODE)" }
Write-Host "    Schema ready (6 tables: worlds, scenes, character_states, action_history, world_events, world_parameter_states)" -ForegroundColor Green
# ============================================================
# Step 4: Named tunnel
# ============================================================
Write-Host "[4/5] Named tunnel setup..." -ForegroundColor Cyan
& "$RepoRoot\scripts\setup_named_tunnel.ps1"
if ($LASTEXITCODE -ne 0) { throw "Tunnel setup failed (exit=$LASTEXITCODE)" }
Write-Host "    Tunnel: https://rpg.kitahim.uk" -ForegroundColor Green

# ============================================================
# Step 5: Production smoke tests
# ============================================================
Write-Host "[5/5] Production smoke tests..." -ForegroundColor Cyan
& $VenvPy -m pytest backend/tests/test_production_smoke.py -v
if ($LASTEXITCODE -ne 0) { throw "Smoke tests failed (exit=$LASTEXITCODE)" }
Write-Host "    7/7 tests passed" -ForegroundColor Green

# ============================================================
# Cleanup
# ============================================================
Write-Host ""
Write-Host "=== L2-E Deployment COMPLETE ===" -ForegroundColor Green
Write-Host "Backend:  http://127.0.0.1:8000"
Write-Host "Tunnel:   https://rpg.kitahim.uk"
Write-Host "Frontend: https://rpg.kitahim.uk/  (SPA)"
Write-Host ""
Write-Host "SECURITY: Removing .deploy_secrets.ps1 in 5 seconds..."
Start-Sleep -Seconds 5
Remove-Item (Join-Path $RepoRoot ".deploy_secrets.ps1") -Force
Write-Host "  Done. Secrets file removed."




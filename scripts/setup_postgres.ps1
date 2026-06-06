<#
.SYNOPSIS
    Install PostgreSQL 15+ on BAZOOKA and create the sandbox_rpg
    database + rpg_user role for the OpenClaw Sandbox RPG backend.

.DESCRIPTION
    Idempotent deployment step for Phase L1. Re-runnable: the
    second invocation reports "already exists" without error.

    What this script does:
      1. Detects winget and confirms it's available.
      2. Installs PostgreSQL 15.x via winget if not present.
         (winget id: PostgreSQL.PostgreSQL.15)
      3. Adds PostgreSQL's bin dir to the current PATH for this
         session so 'psql' works.
      4. Reads POSTGRES_PASSWORD from backend\.env (fails with a
         clear message if .env is missing or the var is empty).
      5. Creates the 'rpg_user' role with that password if it
         doesn't exist.
      6. Creates the 'sandbox_rpg' database owned by rpg_user
         if it doesn't exist.
      7. Verifies connectivity with a smoke test: psql -c
         "SELECT 1" as rpg_user.

    After this script:
      - psql is on PATH (within this session, and globally after
        you open a new terminal)
      - Connection string: postgresql+asyncpg://rpg_user:<pw>@
        localhost:5432/sandbox_rpg
      - Matches POSTGRES_PASSWORD in backend\.env

.PARAMETER EnvFile
    Path to .env file. Default: backend\.env (relative to project root)

.PARAMETER PostgresPort
    Default: 5432 (matches backend config.py)

.PARAMETER PostgresVersion
    winget package version filter. Default: 15

.EXAMPLE
    .\setup_postgres.ps1
    # Default: reads backend\.env for POSTGRES_PASSWORD, installs
    # PostgreSQL 15 if not present.

.NOTES
    Part of: Phase L1 deployment tooling (#63 onward)
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07

    KNOWN LIMITATIONS (per Phase L1 spec, Open Question 3 answer):
    - This script uses 'winget install' which requires BAZOOKA's
      winget (Win 10+ with App Installer). If you need to deploy
      to a server without winget, use Docker (Option 🅒1️⃣) or the
      native .exe installer (Option 🅒3️⃣) instead.
    - This script does NOT configure PostgreSQL for remote
      connections. The backend connects over localhost (default
      POSTGRES_HOST=localhost). If you ever deploy the backend
      on a different host, edit postgresql.conf + pg_hba.conf
      manually.
#>

[CmdletBinding()]
param(
    [string]$EnvFile = "$PSScriptRoot\..\backend\.env",
    [int]$PostgresPort = 5432,
    [string]$PostgresVersion = "15"
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — Postgres setup ===" -ForegroundColor Cyan
Write-Host ""

# ============================================
# Pre-flight
# ============================================

# 1. winget available?
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Write-Error @"
winget not found. This script requires App Installer (winget) to
install PostgreSQL 15+ on BAZOOKA.

Install winget from:
  https://aka.ms/getwinget

Or use Option 🅒1️⃣ (Docker) / 🅒3️⃣ (native installer) instead.
"@
    exit 1
}

# 2. .env exists?
if (-not (Test-Path $EnvFile)) {
    Write-Error @"
.env not found at: $EnvFile

Copy backend\.env.example to backend\.env first and fill in
POSTGRES_PASSWORD. Generate a strong one with:
  python -c "import secrets; print(secrets.token_urlsafe(32))"
"@
    exit 1
}

# 3. Read POSTGRES_PASSWORD
$envContent = Get-Content $EnvFile -Raw
$passwordMatch = [regex]::Match($envContent, '(?m)^POSTGRES_PASSWORD=(.+)$')
if (-not $passwordMatch.Success -or [string]::IsNullOrWhiteSpace($passwordMatch.Groups[1].Value)) {
    Write-Error @"
POSTGRES_PASSWORD not set or empty in $EnvFile.

Add a line like:
  POSTGRES_PASSWORD=<your-generated-strong-password>
"@
    exit 1
}
$postgresPassword = $passwordMatch.Groups[1].Value.Trim()
# Strip surrounding quotes if present
if (($postgresPassword.StartsWith('"') -and $postgresPassword.EndsWith('"')) -or
    ($postgresPassword.StartsWith("'") -and $postgresPassword.EndsWith("'"))) {
    $postgresPassword = $postgresPassword.Substring(1, $postgresPassword.Length - 2)
}
if ($postgresPassword -eq "change_me_in_production" -or $postgresPassword -eq "change…tion") {
    Write-Error @"
POSTGRES_PASSWORD is still the placeholder. Replace it with a
real strong password before running this script.
"@
    exit 1
}

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  .env file:        $EnvFile"
Write-Host "  Postgres port:    $PostgresPort"
Write-Host "  Postgres version: $PostgresVersion"
Write-Host ""

# ============================================
# Step 1: Install Postgres if not present
# ============================================

$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) {
    Write-Host "psql not found. Installing PostgreSQL $PostgresVersion via winget..." -ForegroundColor Yellow
    Write-Host "(This may take 2-5 minutes; PostgreSQL installer prompts for setup)" -ForegroundColor Yellow
    Write-Host ""
    $wingetInstallResult = & winget install --id "PostgreSQL.PostgreSQL.$PostgresVersion" `
        --silent --accept-package-agreements --accept-source-agreements 2>&1
    Write-Host $wingetInstallResult

    if ($LASTEXITCODE -ne 0) {
        Write-Error "winget install failed. Try running interactively: winget install --id PostgreSQL.PostgreSQL.$PostgresVersion"
        exit 1
    }

    # Re-check psql after install
    $psql = Get-Command psql -ErrorAction SilentlyContinue
    if (-not $psql) {
        Write-Warning @"
psql still not found after winget install. PostgreSQL installed but
not on PATH. Open a new terminal and re-run this script, or add
PostgreSQL's bin dir to your PATH manually:
  C:\Program Files\PostgreSQL\$PostgresVersion\bin\
"@
        exit 1
    }
}

# Make sure psql is on PATH for this session regardless
$psqlDir = Split-Path $psql.Source -Parent
if ($env:PATH -notlike "*$psqlDir*") {
    $env:PATH = "$psqlDir;$env:PATH"
}

# Use the version-specific bin path. winget usually installs to
# C:\Program Files\PostgreSQL\15\bin\
$expectedBinDir = "C:\Program Files\PostgreSQL\$PostgresVersion\bin"
if ((Test-Path $expectedBinDir) -and ($env:PATH -notlike "*$expectedBinDir*")) {
    $env:PATH = "$expectedBinDir;$env:PATH"
}

Write-Host "psql found at: $psql" -ForegroundColor Green

# ============================================
# Step 2: Verify can connect to Postgres as the default postgres superuser
# ============================================

# On Windows, PostgreSQL installs with a 'postgres' service account.
# Default 'postgres' role password is set during installation.
# We assume the operator has set the postgres user password to match
# (or trusts local trust auth). For BAZOOKA local-only deployment,
# this is the typical setup.

# Try to connect as postgres user (default superuser)
function Test-PostgresConnection {
    $result = & psql -h localhost -p $PostgresPort -U postgres -c "SELECT 1 AS test" 2>&1
    return ($LASTEXITCODE -eq 0)
}

$canConnectAsPostgres = Test-PostgresConnection
if (-not $canConnectAsPostgres) {
    Write-Warning @"
Cannot connect to Postgres as 'postgres' user via psql. This is
common on Windows when the postgres user requires a password.

To fix:
  1. Find the postgres data dir (usually C:\Program Files\PostgreSQL\$PostgresVersion\data\)
  2. Edit pg_hba.conf to allow local trust auth for the postgres user
     (replace 'scram-sha-256' with 'trust' on the 'host all postgres 127.0.0.1/32' line)
  3. Restart the postgres service: Restart-Service postgresql-x64-$PostgresVersion
  4. Re-run this script
"@
    exit 1
}
Write-Host "Postgres superuser connection OK" -ForegroundColor Green

# ============================================
# Step 3: Create rpg_user role
# ============================================

Write-Host ""
Write-Host "Creating role 'rpg_user'..." -ForegroundColor Yellow

# Escape single quotes in password for SQL literal
$escapedPassword = $postgresPassword -replace "'", "''"

$roleExists = & psql -h localhost -p $PostgresPort -U postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='rpg_user'" 2>&1
if ($roleExists -eq "1") {
    Write-Host "  Role 'rpg_user' already exists. Skipping CREATE ROLE." -ForegroundColor Yellow
} else {
    & psql -h localhost -p $PostgresPort -U postgres -c "CREATE ROLE rpg_user WITH LOGIN PASSWORD '$escapedPassword'" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "CREATE ROLE failed"
        exit 1
    }
    Write-Host "  Created role 'rpg_user'." -ForegroundColor Green
}

# ============================================
# Step 4: Create sandbox_rpg database
# ============================================

Write-Host ""
Write-Host "Creating database 'sandbox_rpg'..." -ForegroundColor Yellow

$dbExists = & psql -h localhost -p $PostgresPort -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='sandbox_rpg'" 2>&1
if ($dbExists -eq "1") {
    Write-Host "  Database 'sandbox_rpg' already exists. Skipping CREATE DATABASE." -ForegroundColor Yellow
} else {
    & psql -h localhost -p $PostgresPort -U postgres -c "CREATE DATABASE sandbox_rpg OWNER rpg_user" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "CREATE DATABASE failed"
        exit 1
    }
    Write-Host "  Created database 'sandbox_rpg' (owner: rpg_user)." -ForegroundColor Green
}

# ============================================
# Step 5: Smoke test as rpg_user
# ============================================

Write-Host ""
Write-Host "Verifying rpg_user can connect to sandbox_rpg..." -ForegroundColor Yellow

# Use PGPASSWORD env var to avoid psql password prompt
$env:PGPASSWORD = $postgresPassword
$smoke = & psql -h localhost -p $PostgresPort -U rpg_user -d sandbox_rpg -c "SELECT current_user, current_database()" 2>&1
Remove-Item Env:PGPASSWORD

if ($LASTEXITCODE -ne 0) {
    Write-Error @"
rpg_user cannot connect to sandbox_rpg. Check:
  - pg_hba.conf allows 'password' or 'md5' auth for rpg_user from 127.0.0.1
  - The password in backend\.env matches what was set here
"@
    exit 1
}

Write-Host $smoke
Write-Host ""
Write-Host "=== Postgres setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Connection string (for backend\.env POSTGRES_*):" -ForegroundColor Cyan
Write-Host "  POSTGRES_HOST=localhost"
Write-Host "  POSTGRES_PORT=$PostgresPort"
Write-Host "  POSTGRES_DB=sandbox_rpg"
Write-Host "  POSTGRES_USER=rpg_user"
Write-Host "  POSTGRES_PASSWORD=<as set in your .env>"
Write-Host ""
Write-Host "Next step: powershell -File scripts\run_migrations.ps1" -ForegroundColor Yellow

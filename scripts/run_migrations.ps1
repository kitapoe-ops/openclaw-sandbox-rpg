<#
.SYNOPSIS
    Run Alembic database migrations against the sandbox_rpg
    database on BAZOOKA.

.DESCRIPTION
    Idempotent deployment step for Phase L1. Calls
    'alembic upgrade head' from the backend/ directory. Safe
    to re-run: Alembic tracks the current revision and skips
    already-applied migrations.

    Pre-requisites:
      1. scripts\setup_postgres.ps1 has been run (creates the
         database and rpg_user role).
      2. backend\.env is filled in (POSTGRES_* vars).
      3. The .venv has been set up at
         C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\.venv
         (with alembic installed — it should be, via requirements.txt).

    What this script does:
      1. Validates that the venv and .env exist.
      2. Reads the POSTGRES_* values from .env.
      3. Injects them as env vars (so alembic.ini / env.py
         can pick them up — backend has a standard pattern
         where the .env values are read at module load time).
      4. Runs 'alembic upgrade head' from backend/.
      5. Verifies with 'alembic current' and reports the
         current revision.

.PARAMETER ProjectRoot
    Default: inferred from script location.

.EXAMPLE
    .\run_migrations.ps1
    # Default: alembic upgrade head against sandbox_rpg

.EXAMPLE
    .\run_migrations.ps1 -Verbose
    # Show full alembic output (default: only error output)

.NOTES
    Part of: Phase L1 deployment tooling (#63 onward)
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07

    If you ever need to DOWNGRADE (e.g. a bad migration shipped):
      .venv\Scripts\python.exe -m alembic downgrade -1
    But this script does NOT do downgrades automatically — that's
    a destructive op that requires explicit user approval.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — Alembic migrations ===" -ForegroundColor Cyan
Write-Host ""

# ============================================
# Pre-flight
# ============================================

$BackendDir = Join-Path $ProjectRoot "backend"
$EnvFile = Join-Path $BackendDir ".env"
$VenvDir = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python venv not found at: $PythonExe (create the venv first)"
    exit 1
}
if (-not (Test-Path $EnvFile)) {
    Write-Error ".env not found at: $EnvFile (run scripts\setup_postgres.ps1 first)"
    exit 1
}
if (-not (Test-Path (Join-Path $BackendDir "alembic.ini"))) {
    Write-Error "alembic.ini not found in $BackendDir (is the backend properly set up?)"
    exit 1
}
if (-not (Test-Path (Join-Path $BackendDir "alembic"))) {
    Write-Error "alembic directory not found in $BackendDir (no migration scripts to run)"
    exit 1
}

# ============================================
# Inject POSTGRES_* env vars from .env
# ============================================

$envContent = Get-Content $EnvFile -Raw
foreach ($var in @("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")) {
    $match = [regex]::Match($envContent, "(?m)^$var=(.+)$")
    if ($match.Success) {
        $value = $match.Groups[1].Value.Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path "Env:$var" -Value $value
        Write-Host "  Loaded $var from .env" -ForegroundColor Gray
    } else {
        Write-Warning "  $var not found in .env (Alembic may fail)"
    }
}

Write-Host ""

# ============================================
# Run alembic upgrade head
# ============================================

Write-Host "Running alembic upgrade head..." -ForegroundColor Yellow
Write-Host "  (cd $BackendDir)" -ForegroundColor Gray
Write-Host ""

Push-Location $BackendDir
try {
    & $PythonExe -m alembic upgrade head 2>&1 | ForEach-Object {
        Write-Host "  $_"
    }
} finally {
    Pop-Location
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "alembic upgrade head failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""

# ============================================
# Verify current revision
# ============================================

Write-Host "Current Alembic revision:" -ForegroundColor Yellow
Push-Location $BackendDir
try {
    & $PythonExe -m alembic current 2>&1 | ForEach-Object {
        Write-Host "  $_"
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "=== Migrations complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next step: powershell -File scripts\install_service.ps1 (if not done)" -ForegroundColor Yellow
Write-Host "             then start the service: Start-Service OpenClawSandboxRPG" -ForegroundColor Yellow

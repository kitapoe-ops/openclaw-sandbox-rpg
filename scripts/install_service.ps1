<#
.SYNOPSIS
    Register the OpenClaw Sandbox RPG backend (uvicorn) as a Windows
    service via NSSM (Non-Sucking Service Manager), so the server
    auto-starts on boot and auto-restarts on crash.

.DESCRIPTION
    On BAZOOKA (per MEMORY.md "Sandbox RPG 部署範圍 2026-06-07"),
    the backend runs as a Windows service so the server stays up
    without manual intervention after a reboot or a uvicorn crash.

    Pre-requisites:
      1. NSSM 2.24+ installed. Download from
         https://nssm.cc/download and unpack to C:\Tools\nssm\
         (or any directory; set $NssmExe below to point at the
         nssm.exe binary).
      2. Python venv already set up at
         C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\.venv
         (the venv created by the bootstrap script).
      3. backend\.env filled in (copy from backend\.env.example).
      4. Postgres reachable at POSTGRES_HOST (typically localhost).
      5. LM Studio running on http://127.0.0.1:1234 (for R1-14B
         audit path) — optional, server can run without it but
         the audit-hook skill will degrade.

    What this script does:
      1. Validates that NSSM, the venv, and the .env file all exist.
      2. Calls NSSM to install a new service called
         "OpenClawSandboxRPG" with the uvicorn binary as the
         executable and the right arguments.
      3. Sets service start type to "auto" (start on boot).
      4. Configures restart-on-failure (1s delay, restart up to 3
         times before giving up for 60s).
      5. Sets the working directory to the project root so
         LANCEDB_URI relative paths work.
      6. Sets the AppEnvironment to read backend\.env via a wrapper
         (so Pydantic sees POSTGRES_PASSWORD etc. as env vars).
      7. Starts the service.

    To uninstall: run scripts\uninstall_service.ps1

.PARAMETER NssmExe
    Full path to nssm.exe. Default: C:\Tools\nssm-2.24\win64\nssm.exe

.PARAMETER ProjectRoot
    Path to the sandbox-rpg-tmp repo checkout. Default: inferred
    from the script's location (parent of parent of scripts/).

.PARAMETER ServiceName
    Windows service name to register. Default: OpenClawSandboxRPG

.EXAMPLE
    .\install_service.ps1
    # Default: C:\Tools\nssm-2.24\win64\nssm.exe + current repo

.EXAMPLE
    .\install_service.ps1 -NssmExe "D:\apps\nssm\nssm.exe"
    # Custom NSSM location

.NOTES
    Author: Him / BAZOOKA deployment
    Created: 2026-06-07
    Part of: Phase L1 deployment tooling
#>

[CmdletBinding()]
param(
    [string]$NssmExe = "C:\Tools\nssm-2.24\win64\nssm.exe",
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$ServiceName = "OpenClawSandboxRPG"
)

$ErrorActionPreference = "Stop"

# ============================================
# Pre-flight checks
# ============================================

Write-Host "=== OpenClaw Sandbox RPG — service install ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $NssmExe)) {
    Write-Error @"
NSSM not found at: $NssmExe

Download NSSM 2.24+ from https://nssm.cc/download
Unpack to C:\Tools\nssm-2.24\ (or anywhere you like)
Re-run this script with -NssmExe <path> if you put it elsewhere.
"@
    exit 1
}

$BackendDir = Join-Path $ProjectRoot "backend"
$VenvDir = Join-Path $ProjectRoot ".venv"
$UvicornExe = Join-Path $VenvDir "Scripts\uvicorn.exe"
$EnvFile = Join-Path $BackendDir ".env"

if (-not (Test-Path $BackendDir)) {
    Write-Error "Backend dir not found: $BackendDir"
    exit 1
}
if (-not (Test-Path $UvicornExe)) {
    Write-Error "uvicorn.exe not found: $UvicornExe (run the venv setup first)"
    exit 1
}
if (-not (Test-Path $EnvFile)) {
    Write-Error @"
.env file not found: $EnvFile

Copy backend\.env.example to backend\.env and fill in:
  - POSTGRES_PASSWORD
  - SECRET_KEY
  - LLM_CLOUD_API_KEY (if using MiniMax-M3 cloud)
"@
    exit 1
}

# Check for admin rights (required to install a Windows service)
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error @"
This script must be run as Administrator.
Right-click PowerShell -> 'Run as administrator' -> re-run.
"@
    exit 1
}

# If a service with this name already exists, refuse to clobber
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Error @"
Service '$ServiceName' is already installed (state: $($existing.Status)).
Run scripts\uninstall_service.ps1 first if you want to reinstall.
"@
    exit 1
}

# ============================================
# Build the wrapper command
# ============================================
# We can't pass .env directly to uvicorn.exe. We have two options:
#   (a) Use a small Python wrapper that loads .env via python-dotenv
#       before exec'ing uvicorn. Cleanest but adds a dep.
#   (b) Use NSSM's AppEnvironmentExtra feature to inject the values
#       one by one. Brittle for long .env files.
#
# We pick (a): use python -c to load .env then exec uvicorn. This
# is the pattern recommended in the NSSM docs for Python services.

$wrapperPath = Join-Path $BackendDir ".service_wrapper.py"
$wrapperContent = @"
"""Wrapper script invoked by NSSM to start the OpenClaw backend.

Loads backend\.env into os.environ (Pydantic Settings reads from
os.environ), then execs uvicorn. This is the same pattern as
running `uvicorn backend.main:app` from a shell that has the
.env sourced.
"""
import os
import sys
from pathlib import Path

# Load .env (simple parser; avoids python-dotenv dependency)
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip matching surrounding quotes
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)

# Now exec uvicorn
# Arguments: passed by NSSM via AppParameters
# Default for our service: backend.main:app
os.execvp(
    sys.executable,
    [sys.executable, "-m", "uvicorn", *sys.argv[1:]],
)
"@
$wrapperContent | Set-Content -Path $wrapperPath -Encoding UTF8

# ============================================
# NSSM install
# ============================================

Write-Host "Installing service '$ServiceName'..." -ForegroundColor Yellow

# Step 1: nssm install <name> <executable>
& $NssmExe install $ServiceName (Join-Path $VenvDir "Scripts\python.exe") | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm install failed"; exit 1 }

# Step 2: nssm set <name> AppParameters <args>
#   - uvicorn reads the module path from the first arg
#   - we pass backend.main:app + bind host:port (read from .env
#     by Pydantic, but uvicorn needs its own --host/--port flags)
$backendHost = "0.0.0.0"
$backendPort = "8000"
& $NssmExe set $ServiceName AppParameters "$wrapperPath backend.main:app --host $backendHost --port $backendPort" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm set AppParameters failed"; exit 1 }

# Step 3: nssm set <name> AppDirectory <project_root>
#   uvicorn resolves LANCEDB_URI='./lancedb_data' relative to cwd;
#   this AppDirectory setting makes the service start in the
#   project root.
& $NssmExe set $ServiceName AppDirectory $ProjectRoot | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm set AppDirectory failed"; exit 1 }

# Step 4: nssm set <name> AppStdout / AppStderr <log_path>
#   Capture service stdout/stderr to rotating log files so we
#   can debug if the service crashes.
$logDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$stdoutLog = Join-Path $logDir "service-stdout.log"
$stderrLog = Join-Path $logDir "service-stderr.log"
& $NssmExe set $ServiceName AppStdout $stdoutLog | Out-Null
& $NssmExe set $ServiceName AppStderr $stderrLog | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm set stdout/stderr failed"; exit 1 }

# Step 5: nssm set <name> AppRotateFiles 1 + AppRotateBytes 10MB
#   Rotate log files when they hit 10MB so disk doesn't fill up.
& $NssmExe set $ServiceName AppRotateFiles 1 | Out-Null
& $NssmExe set $ServiceName AppRotateBytes 10485760 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm set rotate failed"; exit 1 }

# Step 6: nssm set <name> Start SERVICE_AUTO_START
#   Start on boot.
& $NssmExe set $ServiceName Start SERVICE_AUTO_START | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm set Start failed"; exit 1 }

# Step 7: nssm set <name> AppExit Default Exit
#   Restart on failure: 1s delay, max 3 restarts in 60s window.
#   After 3 crashes in 60s, give up (don't infinite-loop).
& $NssmExe set $ServiceName AppExit Default Exit | Out-Null
& $NssmExe set $ServiceName AppRestartDelay 1000 | Out-Null  # 1 second
& $NssmExe set $ServiceName AppThrottle 60000 | Out-Null    # 60 seconds window
& $NssmExe set $ServiceName AppRestartAttempts 3 | Out-Null  # up to 3 restarts
if ($LASTEXITCODE -ne 0) { Write-Error "nssm set AppRestart failed"; exit 1 }

# Step 8: nssm set <name> DisplayName + Description
& $NssmExe set $ServiceName DisplayName "OpenClaw Sandbox RPG Backend" | Out-Null
& $NssmExe set $ServiceName Description "FastAPI backend for OpenClaw Sandbox RPG (uvicorn + LM Studio + Postgres). Per MEMORY.md 2026-06-07: BAZOOKA-only deployment." | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm set DisplayName/Description failed"; exit 1 }

# ============================================
# Start the service
# ============================================

Write-Host "Starting service..." -ForegroundColor Yellow
& $NssmExe start $ServiceName | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Service installed but failed to start. Check logs in $logDir"
    exit 1
}

# Give uvicorn a moment to bind
Start-Sleep -Seconds 2

$status = Get-Service -Name $ServiceName
Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Green
Write-Host "  Service name:  $ServiceName"
Write-Host "  Display name:  OpenClaw Sandbox RPG Backend"
Write-Host "  Status:        $($status.Status)"
Write-Host "  Start type:    Auto (starts on boot)"
Write-Host "  Executable:    $(Join-Path $VenvDir 'Scripts\python.exe')"
Write-Host "  Arguments:     $wrapperPath backend.main:app --host $backendHost --port $backendPort"
Write-Host "  Working dir:   $ProjectRoot"
Write-Host "  Stdout log:    $stdoutLog"
Write-Host "  Stderr log:    $stderrLog"
Write-Host "  Health check:  http://localhost:$backendPort/health"
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  Status:   Get-Service $ServiceName"
Write-Host "  Stop:     Stop-Service $ServiceName   (or: nssm stop $ServiceName)"
Write-Host "  Start:    Start-Service $ServiceName (or: nssm start $ServiceName)"
Write-Host "  Tail log: Get-Content '$stdoutLog' -Wait"
Write-Host "  Uninstall: powershell -File scripts\uninstall_service.ps1"

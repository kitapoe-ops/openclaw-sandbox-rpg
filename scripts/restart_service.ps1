<#
.SYNOPSIS
    Restart the OpenClawSandboxRPG Windows service (NSSM-managed
    uvicorn backend) with a clean stop + start cycle.

.DESCRIPTION
    Phase L1 step H4 of 6. Thin wrapper around 'nssm stop' +
    'nssm start' with a wait for the service to actually come
    back to Running state. Useful after:
      - Deploying new code (restart to pick up changes)
      - Restarting after the cloudflared tunnel URL changes
      - Recovering from a hung service state

    Why a separate script (not just 'Restart-Service' built-in):
      - 'Restart-Service' waits for the service to fully stop
        BEFORE issuing the start command, which can be slow
        on Windows. The NSSM stop+start cycle is faster and
        gives us a reliable return-code-based wait.
      - This script also verifies the service is Running
        within 30s, rather than just assuming success.

.PARAMETER ServiceName
    Default: OpenClawSandboxRPG

.EXAMPLE
    .\restart_service.ps1
    # Standard stop + start cycle

.EXAMPLE
    .\restart_service.ps1 -ServiceName OpenClawSandboxRPG-Staging
    # Restart a different service (e.g. staging environment)

.NOTES
    Part of: Phase L1 deployment tooling (#66 onward)
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07
#>

[CmdletBinding()]
param(
    [string]$NssmExe = "C:\Tools\nssm-2.24\win64\nssm.exe",
    [string]$ServiceName = "OpenClawSandboxRPG"
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — service restart ===" -ForegroundColor Cyan
Write-Host ""

# Pre-flight
if (-not (Test-Path $NssmExe)) {
    Write-Error "NSSM not found at: $NssmExe (use -NssmExe to override)"
    exit 1
}
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Error "Service '$ServiceName' is not installed."
    exit 1
}
Write-Host "Service '$ServiceName' is currently: $($svc.Status)" -ForegroundColor Yellow
Write-Host ""

# Stop (idempotent: if already Stopped, nssm stop returns non-zero
# but that's OK — we just continue to the start step)
Write-Host "Stopping service..." -ForegroundColor Yellow
& $NssmExe stop $ServiceName 2>&1 | Out-Null
# Wait up to 15s for graceful stop
$deadline = (Get-Date).AddSeconds(15)
$svc.Refresh()
while ($svc.Status -ne "Stopped" -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    $svc.Refresh()
}
if ($svc.Status -ne "Stopped") {
    Write-Warning "Service did not stop within 15s (state: $($svc.Status))"
    Write-Warning "Proceeding to start anyway (NSSM will handle the transition)..."
}

# Start
Write-Host "Starting service..." -ForegroundColor Yellow
& $NssmExe start $ServiceName 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "nssm start failed"
    exit 1
}

# Wait up to 30s for Running state
$deadline = (Get-Date).AddSeconds(30)
$svc.Refresh()
while ($svc.Status -ne "Running" -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    $svc.Refresh()
}
if ($svc.Status -ne "Running") {
    Write-Error "Service did not reach Running state within 30s (state: $($svc.Status))"
    exit 1
}

# Health check
Write-Host ""
Write-Host "Health check (http://localhost:8000/health)..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        $body = $response.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        Write-Host "  Status: HEALTHY ($($response.StatusCode))" -ForegroundColor Green
        if ($body) {
            Write-Host "  Mode:    $($body.mode)"
            Write-Host "  Version: $($body.version)"
        }
    } else {
        Write-Host "  Status: DEGRADED (HTTP $($response.StatusCode))" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Status: UNREACHABLE ($($_.Exception.Message))" -ForegroundColor Red
    Write-Host "  (The service is Running but the health endpoint didn't respond.)" -ForegroundColor Yellow
    Write-Host "  Check logs\service-stdout.log and logs\service-stderr.log." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Service restart complete ===" -ForegroundColor Green

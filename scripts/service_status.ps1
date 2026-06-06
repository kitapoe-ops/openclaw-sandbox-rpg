<#
.SYNOPSIS
    Show the current state of the OpenClaw Sandbox RPG Windows
    service: status, last-start time, exit code, recent log lines.

.DESCRIPTION
    Read-only helper to check whether the service is up without
    needing to log in to the server. Designed to be safe to run
    as a non-admin user (it does not modify the service, just
    queries Service Control Manager + reads log files).

.PARAMETER ServiceName
    Default: OpenClawSandboxRPG

.PARAMETER LogLines
    How many recent lines to show from logs\service-stdout.log.
    Default: 30

.EXAMPLE
    .\service_status.ps1
    # Standard "is it up?" check

.EXAMPLE
    .\service_status.ps1 -LogLines 100
    # Tail more lines for debugging

.NOTES
    Author: Him / BAZOOKA deployment
    Created: 2026-06-07
#>

[CmdletBinding()]
param(
    [string]$ServiceName = "OpenClawSandboxRPG",
    [int]$LogLines = 30
)

$ErrorActionPreference = "Continue"

Write-Host "=== OpenClaw Sandbox RPG — service status ===" -ForegroundColor Cyan
Write-Host ""

# Get-Service works for non-admin users in most cases (read access)
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "Service '$ServiceName' is NOT installed." -ForegroundColor Red
    Write-Host "To install: powershell -File scripts\install_service.ps1" -ForegroundColor Yellow
    exit 0
}

# Status + start type
Write-Host "Service name:    $ServiceName"
Write-Host "Display name:    $($svc.DisplayName)"
Write-Host "Status:          $($svc.Status)"
Write-Host "Start type:      $($svc.StartType)"
Write-Host "Can stop:        $($svc.CanStop)"
Write-Host "Can pause:       $($svc.CanPauseAndContinue)"

# Get-WmiObject is the safe way to get the exit code + start time
# for non-admin callers. (Get-Service doesn't expose these.)
try {
    $wmi = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'" -ErrorAction Stop
    Write-Host "Process ID:      $($wmi.ProcessId)"
    Write-Host "Exit code:       $($wmi.ExitCode)"
    Write-Host "Started:         $($wmi.State) since $($wmi.Started)"
} catch {
    Write-Host "(CIM query failed: $($_.Exception.Message))" -ForegroundColor Yellow
}

# Health check (HTTP)
$port = 8000
$healthUrl = "http://localhost:$port/health"
Write-Host ""
Write-Host "Health check:    $healthUrl"
try {
    $response = Invoke-WebRequest -Uri $healthUrl -Method GET -UseBasicParsing -TimeoutSec 5
    $body = $response.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
    if ($response.StatusCode -eq 200) {
        Write-Host "  Status:        HEALTHY ($($response.StatusCode))" -ForegroundColor Green
        if ($body) {
            Write-Host "  Mode:          $($body.mode)"
            Write-Host "  Version:       $($body.version)"
            if ($body.registry) {
                Write-Host "  Registry:      $($body.registry | ConvertTo-Json -Compress)"
            }
            if ($body.scene_locks) {
                Write-Host "  Scene locks:   $($body.scene_locks | ConvertTo-Json -Compress)"
            }
        }
    } else {
        Write-Host "  Status:        DEGRADED (HTTP $($response.StatusCode))" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Status:        UNREACHABLE ($($_.Exception.Message))" -ForegroundColor Red
}

# Recent stdout
$projectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$stdoutLog = Join-Path $projectRoot "logs\service-stdout.log"
if (Test-Path $stdoutLog) {
    Write-Host ""
    Write-Host "--- Last $LogLines lines of $stdoutLog ---" -ForegroundColor Cyan
    Get-Content $stdoutLog -Tail $LogLines
}

# Recent stderr
$stderrLog = Join-Path $projectRoot "logs\service-stderr.log"
if (Test-Path $stderrLog) {
    $errCount = (Get-Content $stderrLog | Measure-Object -Line).Lines
    if ($errCount -gt 0) {
        Write-Host ""
        Write-Host "--- Last $LogLines lines of $stderrLog ---" -ForegroundColor Yellow
        Get-Content $stderrLog -Tail $LogLines
    }
}

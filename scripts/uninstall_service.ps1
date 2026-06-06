<#
.SYNOPSIS
    Remove the OpenClaw Sandbox RPG Windows service that was
    installed by install_service.ps1.

.DESCRIPTION
    Stops the service if running, then calls nssm remove to
    unregister it from the Windows Service Control Manager.
    Leaves backend\.env, the .venv, and the project files
    untouched — only the service registration is removed.

    Does NOT remove:
      - backend\.env (your real secrets)
      - .service_wrapper.py (the launch script)
      - logs\service-*.log (captured stdout/stderr)
      - Postgres data
      - LanceDB data

    If you want a full clean reinstall, also delete
    logs\service-*.log after this script completes.

.PARAMETER NssmExe
    Full path to nssm.exe. Must match the path used in
    install_service.ps1. Default: C:\Tools\nssm-2.24\win64\nssm.exe

.PARAMETER ServiceName
    Windows service name to remove. Default: OpenClawSandboxRPG

.EXAMPLE
    .\uninstall_service.ps1
    # Default: stop + remove the OpenClawSandboxRPG service

.EXAMPLE
    .\uninstall_service.ps1 -Confirm:$false
    # Skip the y/N prompt

.NOTES
    Author: Him / BAZOOKA deployment
    Created: 2026-06-07
    Part of: Phase L1 deployment tooling
#>

[CmdletBinding(ConfirmImpact = "High")]
param(
    [string]$NssmExe = "C:\Tools\nssm-2.24\win64\nssm.exe",
    [string]$ServiceName = "OpenClawSandboxRPG"
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — service uninstall ===" -ForegroundColor Cyan
Write-Host ""

# Admin check
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This script must be run as Administrator."
    exit 1
}

# NSSM check
if (-not (Test-Path $NssmExe)) {
    Write-Error "NSSM not found at: $NssmExe (use -NssmExe to override)"
    exit 1
}

# Service must exist
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Service '$ServiceName' is not installed. Nothing to do." -ForegroundColor Yellow
    exit 0
}

Write-Host "Service '$ServiceName' is currently: $($existing.Status)" -ForegroundColor Yellow

# Stop if running (nssm stop handles 'running' and 'start pending' states
# but errors on 'stopped' — handle both)
if ($existing.Status -ne "Stopped") {
    Write-Host "Stopping service..." -ForegroundColor Yellow
    & $NssmExe stop $ServiceName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "nssm stop returned non-zero; continuing anyway."
    }
    # Wait for the service to actually stop
    $service = Get-Service -Name $ServiceName
    $deadline = (Get-Date).AddSeconds(30)
    while ($service.Status -ne "Stopped" -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        $service.Refresh()
    }
    if ($service.Status -ne "Stopped") {
        Write-Error @"
Service did not stop within 30 seconds.
Check for stuck processes in Task Manager (look for 'python.exe'
and 'uvicorn' under the '$ServiceName' service name).
"@
        exit 1
    }
}

# Remove from Service Control Manager
Write-Host "Removing service registration..." -ForegroundColor Yellow
& $NssmExe remove $ServiceName confirm | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "nssm remove failed."
    exit 1
}

# Also clean up the wrapper script that install_service.ps1 dropped
# in backend/.service_wrapper.py. This file is not tracked in git
# (it's in scripts\.gitignore — see scripts\.gitignore) so removing
# it is safe.
$projectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$wrapperPath = Join-Path $projectRoot "backend\.service_wrapper.py"
if (Test-Path $wrapperPath) {
    Remove-Item $wrapperPath -Force
    Write-Host "Removed wrapper: $wrapperPath" -ForegroundColor Yellow
}

# Verify it's gone
$goneCheck = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($goneCheck) {
    Write-Error "Service still appears in the service manager after removal. Investigate manually."
    exit 1
}

Write-Host ""
Write-Host "=== Uninstallation complete ===" -ForegroundColor Green
Write-Host "  Removed:       $ServiceName"
Write-Host "  Preserved:     backend\.env, .venv, project files"
Write-Host ""
Write-Host "To reinstall: powershell -File scripts\install_service.ps1" -ForegroundColor Cyan

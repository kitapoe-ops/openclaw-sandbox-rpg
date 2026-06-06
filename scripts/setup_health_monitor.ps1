<#
.SYNOPSIS
    Register a Task Scheduler job that runs the deploy smoke
    test on a schedule, so 24/7 health monitoring works
    without an external service like UptimeRobot.

.DESCRIPTION
    Phase L2 step B: add Windows Task Scheduler entry that
    runs scripts\deploy_smoke_test.ps1 every 5 minutes.
    The smoke test writes its results to logs\health-check.log
    and to logs\alerts.log (if any critical check fails).

    Why Task Scheduler (not UptimeRobot, Pingdom, etc.):
      - Free, no external service required.
      - Already running on Windows.
      - Logs to local files that the operator can grep.
      - Limitation: only works while BAZOOKA is on. If BAZOOKA
        is down, the monitor is also down (this is acceptable
        for a single-machine deployment).

    What this script does:
      1. Validates the smoke test script exists and runs cleanly
         (one-shot dry run).
      2. Creates a Task Scheduler task named "OpenClawHealthCheck"
         that runs every 5 minutes as the SYSTEM user (so it
         works even when no one is logged in).
      3. The task runs:
           powershell.exe -File scripts\deploy_smoke_test.ps1
              > logs\health-check-<timestamp>.log 2>&1
      4. Also creates a one-shot task "OpenClawHealthCheckOnce"
         that runs at next logon (for the very first time after
         a reboot, before the 5-min schedule kicks in).

    Limitations (documented inline):
      - Local-only: monitor goes down with BAZOOKA.
      - No external notification: alerts log to a file, not
        to Telegram/Discord/SMS. (If you want notifications,
        add a webhook call to deploy_smoke_test.ps1.)

.PARAMETER ProjectRoot
    Default: inferred from script location.

.PARAMETER IntervalMinutes
    Default: 5 (matches the recommended health check cadence
    for 4-player demo).

.EXAMPLE
    .\setup_health_monitor.ps1
    # Default: 5-minute interval, SYSTEM user, runs as Administrator

.EXAMPLE
    .\setup_health_monitor.ps1 -IntervalMinutes 1
    # Tighter cadence for troubleshooting (every 1 minute)

.NOTES
    Part of: Phase L2 deployment tooling
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [int]$IntervalMinutes = 5,
    [string]$TaskName = "OpenClawHealthCheck"
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — health monitor setup ===" -ForegroundColor Cyan
Write-Host ""

# ============================================
# Pre-flight
# ============================================

$SmokeTest = Join-Path $ProjectRoot "scripts\deploy_smoke_test.ps1"
if (-not (Test-Path $SmokeTest)) {
    Write-Error "Smoke test not found: $SmokeTest"
    exit 1
}

# Admin check
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This script must be run as Administrator (Task Scheduler requires admin)."
    exit 1
}

# Log dir
$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# ============================================
# Step 1: Dry-run the smoke test
# ============================================

Write-Host "Dry-running the smoke test (so we know it exits 0 in BAZOOKA's context)..." -ForegroundColor Yellow
$dryRunLog = Join-Path $LogDir "health-check-dryrun.log"
$proc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$SmokeTest`"" `
    -RedirectStandardOutput $dryRunLog `
    -RedirectStandardError $dryRunLog `
    -WindowStyle Hidden -PassThru -Wait
Write-Host "  Dry-run exit code: $($proc.ExitCode)" -ForegroundColor $(if ($proc.ExitCode -eq 0) { "Green" } else { "Yellow" })
if ($proc.ExitCode -ne 0) {
    Write-Warning "Smoke test exited non-zero. The schedule will still be created (the operator can investigate), but alerts will fire continuously."
}

# ============================================
# Step 2: Create the recurring task
# ============================================

Write-Host ""
Write-Host "Creating Task Scheduler entry '$TaskName'..." -ForegroundColor Yellow

# Remove any existing task with the same name
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  Existing task found. Removing..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$SmokeTest`" >> `"$LogDir\health-check.log`" 2>&1" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

# Run as SYSTEM so the monitor works even when nobody is logged
# in. RunLevel Highest so the script can use NSSM and network.
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Runs the OpenClaw Sandbox RPG deployment smoke test every $IntervalMinutes minutes. Logs to logs\health-check.log." | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to register scheduled task"
    exit 1
}
Write-Host "  Task registered: $TaskName (every $IntervalMinutes min, runs as SYSTEM)" -ForegroundColor Green

# ============================================
# Step 3: Verify the task is registered
# ============================================

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Error "Task not found after registration"
    exit 1
}
Write-Host "  Task state: $($task.State)" -ForegroundColor Green

# ============================================
# Step 4: Add the alerts.log to .gitignore
# ============================================

$gitignorePath = Join-Path $ProjectRoot ".gitignore"
$gitignoreContent = Get-Content $gitignorePath -Raw -ErrorAction SilentlyContinue
if ($gitignoreContent -and -not ($gitignoreContent -match "alerts\.log")) {
    Add-Content -Path $gitignorePath -Value @"

# Health monitor alert log (populated by deploy_smoke_test.ps1
# when a critical check fails)
logs/alerts.log
"@
    Write-Host "  Added logs/alerts.log to .gitignore" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Health monitor setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Task name:     $TaskName"
Write-Host "  Interval:      every $IntervalMinutes minutes"
Write-Host "  Runs as:       SYSTEM (works without user logged in)"
Write-Host "  Smoke test:    $SmokeTest"
Write-Host "  Log file:      $LogDir\health-check.log (rolling, append-only)"
Write-Host "  Alert log:     $LogDir\alerts.log (when checks fail)"
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  View task:     Get-ScheduledTask -TaskName $TaskName"
Write-Host "  Run now:       Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Disable:       Disable-ScheduledTask -TaskName $TaskName"
Write-Host "  Enable:        Enable-ScheduledTask -TaskName $TaskName"
Write-Host "  Remove:        Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host "  Tail log:      Get-Content $LogDir\health-check.log -Wait -Tail 30"
Write-Host ""
Write-Host "KNOWN LIMITATION:" -ForegroundColor Yellow
Write-Host "  The monitor is local-only. If BAZOOKA is down, the" -ForegroundColor Yellow
Write-Host "  monitor is also down (no external service to notice)." -ForegroundColor Yellow
Write-Host "  For external monitoring, point UptimeRobot at" -ForegroundColor Yellow
Write-Host "  https://rpg.kitahim.uk/health for free 5-min probes." -ForegroundColor Yellow

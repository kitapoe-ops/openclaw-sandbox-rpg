# OpenClaw Sandbox RPG — Cloudflared Task Scheduler registration
# Replaces the broken Windows service (which stops 0.3s after start)
# with a Task Scheduler job that auto-restarts on failure.

# Must run as Administrator.

$TaskName = "CloudflaredTunnel"
$TaskDescription = "OpenClaw Sandbox RPG - Cloudflare named tunnel (auto-restart on failure)"
$CloudflaredExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$TunnelId = "7570db25-3848-49bb-b1d4-c9653c1c74c0"
$TaskRun = '"' + $CloudflaredExe + '" tunnel run ' + $TunnelId

Write-Host "=== OpenClaw Sandbox RPG — Task Scheduler Setup ===" -ForegroundColor Cyan
Write-Host "Task name:    $TaskName"
Write-Host "Task action:  $TaskRun"
Write-Host ""

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the task
Write-Host "Creating task..." -ForegroundColor Yellow
$action = New-ScheduledTaskAction -Execute $CloudflaredExe -Argument "tunnel run $TunnelId"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $TaskDescription -Force | Out-Null

Write-Host "  Task registered" -ForegroundColor Green

# Start the task now
Write-Host ""
Write-Host "Starting task..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5

# Verify
$status = Get-ScheduledTask -TaskName $TaskName
Write-Host ""
Write-Host "Task state: $($status.State)" -ForegroundColor $(if ($status.State -eq "Running") { "Green" } else { "Yellow" })

# Verify via tunnel
Write-Host ""
Write-Host "=== Verifying via https://rpg.kitahim.uk/health ===" -ForegroundColor Cyan
Start-Sleep -Seconds 3
try {
    $resp = Invoke-WebRequest -Uri "https://rpg.kitahim.uk/health" -Method GET -UseBasicParsing -TimeoutSec 20
    Write-Host "  HTTP $($resp.StatusCode): $($resp.Content)" -ForegroundColor Green
} catch {
    Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Red
}

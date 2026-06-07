# OpenClaw Sandbox RPG — Cloudflared named tunnel service wrapper
# This PowerShell script runs the cloudflared tunnel command in the
# foreground so the NSSM/service host sees the process as the "service
# process" and doesn't kill it after the wrapper exits.
# Used as the binaryPath in the Windows service.

# Important: this script does NOT exit. It blocks on cloudflared
# until the tunnel is terminated (service stop, machine reboot, etc).

$ErrorActionPreference = "Continue"
$CloudflaredExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$TunnelId = "7570db25-3848-49bb-b1d4-c9653c1c74c0"
$LogFile = "C:\Program Files (x86)\cloudflared\cloudflared-wrapper.log"

# Tee stdout/stderr to a log file so we can debug later
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Starting cloudflared tunnel run $TunnelId" | Add-Content $LogFile

# Run cloudflared with arguments, redirecting both streams to log
# Use Start-Process with -Wait to block until cloudflared exits
try {
    $process = Start-Process -FilePath $CloudflaredExe `
        -ArgumentList "tunnel", "run", $TunnelId `
        -NoNewWindow `
        -RedirectStandardOutput "$LogFile.stdout" `
        -RedirectStandardError "$LogFile.stderr" `
        -PassThru

    "  PID: $($process.Id)" | Add-Content $LogFile
    $process.WaitForExit()

    "  Exit code: $($process.ExitCode)" | Add-Content $LogFile
} catch {
    "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] ERROR: $_" | Add-Content $LogFile
    exit 1
}

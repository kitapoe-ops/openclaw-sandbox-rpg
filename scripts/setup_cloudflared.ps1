<#
.SYNOPSIS
    Install cloudflared on BAZOOKA and start a Cloudflare Quick
    Tunnel that exposes the local backend (port 8000) to the
    public internet via a free *.trycloudflare.com URL.

.DESCRIPTION
    Phase L1 step H2 of 6 (per spec Open Question 1 answer:
    option 3 = quick tunnel). This is a one-time setup:
    cloudflared is installed, then run as a background tunnel.

    Why quick tunnel (not named tunnel) for Phase L1:
      - Free, no domain registration required.
      - Zero cert/DNS configuration.
      - The tunnel URL changes every time cloudflared restarts
        unless you also install cloudflared as a Windows
        service that re-establishes the same tunnel. For Phase
        L1 (a 1-month demo with 4 friends) this is acceptable.
      - If you later want a stable URL, see the
        "UPGRADING TO NAMED TUNNEL" section below.

    What this script does:
      1. Validates cloudflared is on PATH (or installs it via
         winget).
      2. Starts a quick tunnel pointing at http://localhost:8000
         (the backend) in a new window.
      3. Tails the cloudflared log until the trycloudflare.com
         URL appears, then prints the URL.
      4. Writes the URL to logs\cloudflared-url.txt so other
         scripts (deploy_smoke_test.ps1, start_frontend.ps1)
         can pick it up.

    SECURITY NOTE: Quick tunnels give anyone on the internet
    access to your localhost:8000. The BAZOOKA backend has
    no authentication on most endpoints (it's a demo). DO
    NOT use this for anything beyond a closed-group demo with
    trusted players.

.PARAMETER ProjectRoot
    Default: inferred from script location.

.PARAMETER BackendPort
    Default: 8000 (matches backend config.py)

.EXAMPLE
    .\setup_cloudflared.ps1
    # Default: install cloudflared, start quick tunnel to :8000

.EXAMPLE
    .\setup_cloudflared.ps1 -BackendPort 8077
    # Tunnel to a different port (e.g. nginx on 8077)

.NOTES
    Part of: Phase L1 deployment tooling (#64 onward)
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07

    UPGRADING TO NAMED TUNNEL (for future, not Phase L1):
      1. Register a domain at Cloudflare (free if you bring
         your own, $10-15/year otherwise).
      2. cloudflared tunnel login  (browser-based auth)
      3. cloudflared tunnel create openclaw-rpg
      4. Edit ~/.cloudflared/config.yml to add the tunnel UUID
         and ingress rules.
      5. Add a CNAME record in Cloudflare DNS pointing your
         domain at <tunnel-uuid>.cfargotunnel.com
      6. cloudflared tunnel route dns openclaw-rpg <your-domain>
      7. cloudflared service install  (run as Windows service)
    This script is hardcoded to quick tunnel only; named tunnel
    is a separate setup (and a separate decision).
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — Cloudflare Quick Tunnel ===" -ForegroundColor Cyan
Write-Host ""

# ============================================
# Pre-flight
# ============================================

$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$UrlFile = Join-Path $LogDir "cloudflared-url.txt"
$LogFile = Join-Path $LogDir "cloudflared.log"

# Check if a previous URL is still fresh
if (Test-Path $UrlFile) {
    $existing = Get-Content $UrlFile -ErrorAction SilentlyContinue
    if ($existing -and $existing -like "https://*.trycloudflare.com") {
        Write-Host "Existing tunnel URL found: $existing" -ForegroundColor Yellow
        Write-Host "(To force a fresh tunnel, delete $UrlFile and re-run)" -ForegroundColor Yellow
    }
}

# ============================================
# Step 1: Install cloudflared if needed
# ============================================

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Host "cloudflared not found. Installing via winget..." -ForegroundColor Yellow
    & winget install --id Cloudflare.cloudflared --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error @"
winget install cloudflared failed. Try:
  winget install --id Cloudflare.cloudflared
manually and re-run this script.
"@
        exit 1
    }
    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $cf = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cf) {
        Write-Error "cloudflared installed but not on PATH. Open a new terminal and re-run."
        exit 1
    }
}

Write-Host "cloudflared: $($cf.Source)" -ForegroundColor Green

# ============================================
# Step 2: Kill any existing cloudflared process
# ============================================

$existingCf = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
if ($existingCf) {
    Write-Host "Killing $($existingCf.Count) existing cloudflared process(es)..." -ForegroundColor Yellow
    $existingCf | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# ============================================
# Step 3: Start cloudflared in a new window
# ============================================

Write-Host ""
Write-Host "Starting Cloudflare Quick Tunnel to http://localhost:$BackendPort ..." -ForegroundColor Yellow
Write-Host "(A new window will pop up with cloudflared's live log)" -ForegroundColor Yellow
Write-Host ""

# Use Start-Process so cloudflared keeps running after this script exits.
# The tunnel URL is captured by tailing the log file.
"-" * 60 | Out-File -FilePath $LogFile -Encoding UTF8
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Starting cloudflared tunnel to http://localhost:$BackendPort" | Out-File -FilePath $LogFile -Append -Encoding UTF8
"-" * 60 | Out-File -FilePath $LogFile -Append -Encoding UTF8

$proc = Start-Process -FilePath $cf.Source `
    -ArgumentList "tunnel", "--url", "http://localhost:$BackendPort", "--no-autoupdate" `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError $LogFile `
    -WindowStyle Normal `
    -PassThru
Write-Host "  cloudflared started (PID $($proc.Id))" -ForegroundColor Green

# ============================================
# Step 4: Wait for the URL to appear in the log
# ============================================

Write-Host ""
Write-Host "Waiting for trycloudflare.com URL (timeout: 60s)..." -ForegroundColor Yellow
$deadline = (Get-Date).AddSeconds(60)
$tunnelUrl = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (Test-Path $LogFile) {
        $content = Get-Content $LogFile -Raw -ErrorAction SilentlyContinue
        if ($content -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $tunnelUrl = $matches[0]
            break
        }
    }
}

if (-not $tunnelUrl) {
    Write-Error @"
Cloudflared did not print a trycloudflare.com URL within 60s.
Check the log at: $LogFile
Or run cloudflared manually to see the error:
  cloudflared tunnel --url http://localhost:$BackendPort
"@
    exit 1
}

# Persist the URL for other scripts to pick up
$tunnelUrl | Out-File -FilePath $UrlFile -Encoding UTF8 -NoNewline

Write-Host ""
Write-Host "=== Cloudflare Quick Tunnel is up ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Public URL:  $tunnelUrl" -ForegroundColor Cyan
Write-Host "  Target:      http://localhost:$BackendPort  (the BAZOOKA backend)"
Write-Host "  Log file:    $LogFile"
Write-Host "  URL file:    $UrlFile"
Write-Host ""
Write-Host "Test it:" -ForegroundColor Yellow
Write-Host "  curl $tunnelUrl/health"
Write-Host ""
Write-Host "Other BAZOOKA-side commands:" -ForegroundColor Yellow
Write-Host "  Status:   Get-Content $UrlFile"
Write-Host "  Stop:     Get-Process cloudflared | Stop-Process -Force"
Write-Host "  Restart:  & $PSCommandPath (this script)"
Write-Host ""
Write-Host "Note: This URL changes every time cloudflared restarts." -ForegroundColor Gray
Write-Host "      If you need a stable URL, see the NAMED TUNNEL note in the script." -ForegroundColor Gray

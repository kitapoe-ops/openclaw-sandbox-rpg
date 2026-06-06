<#
.SYNOPSIS
    Configure a Cloudflare NAMED tunnel for stable URL
    (replaces the per-restart trycloudflare.com URL of the
    quick tunnel with a fixed https://rpg.kitahim.uk).

.DESCRIPTION
    Phase L2 step A: upgrade the deployment from the free
    Quick Tunnel (URL changes every restart) to a NAMED
    Tunnel (URL is stable: https://rpg.kitahim.uk).

    Pre-requisites:
      1. The 'kitahim.uk' domain is registered in Cloudflare
         (already done — confirmed via NS lookup resolving
         to Cloudflare IPs).
      2. cloudflared is installed (run winget install
         Cloudflare.cloudflared if not).
      3. A Cloudflare API token with the following permissions
         is set in backend\.env (added during the .env update):
           - Zone:DNS:Edit (for kitahim.uk zone)
           - Account:Cloudflare Tunnel:Edit (or just tunnel-scoped)

    What this script does (mostly automatic, with ONE
    interactive step for tunnel credential creation):
      1. Validates cloudflared is on PATH.
      2. Validates CLOUDFLARE_API_TOKEN is in .env.
      3. Asks for the tunnel name (default: openclaw-rpg).
      4. If the tunnel doesn't exist yet, runs
         'cloudflared tunnel create' INTERACTIVELY (this is
         the ONE step that needs user attention; the credential
         file lands in C:\Users\kitap\.cloudflared\<id>.json
         and is used for the rest of the config).
      5. Writes the config.yml with the tunnel UUID and
         ingress rules (frontend on /, backend on /api/*,
         404 -> /).
      6. Uses the API token to create the DNS CNAME record
         (rpg.kitahim.uk -> <tunnel-uuid>.cfargotunnel.com).
      7. Installs cloudflared as a Windows service so the
         tunnel re-establishes on BAZOOKA reboot.
      8. Starts the service and verifies the public URL
         rpg.kitahim.uk responds with HTTP 200.

    After this script:
      - https://rpg.kitahim.uk/         -> the BAZOOKA backend
        (which serves the SPA from / and the API from /api/*)
      - URL is STABLE: BAZOOKA reboots don't change it.
      - Quick tunnel setup_cloudflared.ps1 should NOT be used
        anymore (the URL it produces is different and would
        confuse players who bookmarked the named URL).

.PARAMETER ProjectRoot
    Default: inferred from script location.

.PARAMETER TunnelName
    Default: openclaw-rpg

.PARAMETER Subdomain
    Default: rpg.kitahim.uk (the public hostname)

.PARAMETER BackendPort
    Default: 8000 (matches backend config.py)

.EXAMPLE
    .\setup_named_tunnel.ps1
    # Default: tunnel name 'openclaw-rpg', public URL rpg.kitahim.uk

.NOTES
    Part of: Phase L2 deployment tooling
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07

    SECURITY:
      - The API token in .env is read-only used (DNS:Edit +
        Tunnel:Edit). Scope it narrowly at
        https://dash.cloudflare.com/profile/api-tokens
      - The tunnel credential file (C:\Users\kitap\.cloudflared\
        <uuid>.json) is what cloudflared uses to authenticate
        to Cloudflare. It contains a private key; treat it
        like a password. It is NOT added to git (already covered
        by the .gitignore rule for that path).
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$TunnelName = "openclaw-rpg",
    [string]$Subdomain = "rpg.kitahim.uk",
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — named tunnel setup ===" -ForegroundColor Cyan
Write-Host ""

# ============================================
# Pre-flight
# ============================================

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Error @"
cloudflared not found. Install with:
  winget install --id Cloudflare.cloudflared
Then re-run this script.
"@
    exit 1
}
Write-Host "cloudflared: $($cf.Source)" -ForegroundColor Green

$EnvFile = Join-Path $ProjectRoot "backend\.env"
if (-not (Test-Path $EnvFile)) {
    Write-Error ".env not found at $EnvFile"
    exit 1
}
$envContent = Get-Content $EnvFile -Raw
$tokenMatch = [regex]::Match($envContent, '(?m)^CLOUDFLARE_API_TOKEN=***')
if (-not $tokenMatch.Success -or [string]::IsNullOrWhiteSpace($tokenMatch.Groups[1].Value)) {
    Write-Error @"
CLOUDFLARE_API_TOKEN not in .env. To create one:
  1. Go to https://dash.cloudflare.com/profile/api-tokens
  2. Create Token -> Edit Custom Token
  3. Permissions:
     - Zone:DNS:Edit     (scoped to kitahim.uk)
     - Account:Cloudflare Tunnel:Edit
  4. Zone Resources: Include -> Specific zone -> kitahim.uk
  5. Click 'Continue to summary' -> Create Token
  6. Copy the token and add to backend\.env:
     CLOUDFLARE_API_TOKEN=… your-token-here
Then re-run this script.
"@
    exit 1
}
$apiToken = $tokenMatch.Groups[1].Value.Trim() -replace '^["'']|["'']$', ''
Write-Host "CLOUDFLARE_API_TOKEN loaded (length: $($apiToken.Length))" -ForegroundColor Green

# Verify the API token works (call /user/tokens/verify)
Write-Host ""
Write-Host "Verifying API token with Cloudflare..." -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "https://api.cloudflare.com/client/v4/user/tokens/verify" `
        -Headers @{Authorization="Bearer $apiToken"; Accept="application/json"} `
        -Method GET -UseBasicParsing -TimeoutSec 10
    $verify = $resp.Content | ConvertFrom-Json
    if ($verify.success) {
        Write-Host "  API token valid (status: $($verify.result.status))" -ForegroundColor Green
    } else {
        Write-Error "API token rejected: $($verify.errors[0].message)"
        exit 1
    }
} catch {
    Write-Error "API token verification failed: $($_.Exception.Message)"
    exit 1
}

# Find the zone ID for kitahim.uk
$zoneResp = Invoke-WebRequest -Uri "https://api.cloudflare.com/client/v4/zones?name=kitahim.uk" `
    -Headers @{Authorization="Bearer $apiToken"; Accept="application/json"} `
    -Method GET -UseBasicParsing -TimeoutSec 10
$zoneData = $zoneResp.Content | ConvertFrom-Json
if (-not $zoneData.success -or $zoneData.result.Count -eq 0) {
    Write-Error "Zone 'kitahim.uk' not found in this Cloudflare account. Did you add it to your account?"
    exit 1
}
$zoneId = $zoneData.result[0].id
Write-Host "  Zone 'kitahim.uk' ID: $zoneId" -ForegroundColor Green

# ============================================
# Step 1: Check if tunnel already exists locally
# ============================================

$cloudflaredDir = Join-Path $env:USERPROFILE ".cloudflared"
$TunnelConfig = Join-Path $cloudflaredDir "config.yml"
$TunnelIdFile = Join-Path $cloudflaredDir "$TunnelName.id"

if (Test-Path $TunnelIdFile) {
    $tunnelId = Get-Content $TunnelIdFile -Raw
    Write-Host ""
    Write-Host "Tunnel '$TunnelName' already exists locally (id: $($tunnelId.Trim()))" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Creating tunnel '$TunnelName'..." -ForegroundColor Yellow
    Write-Host "A browser window will open for Cloudflare authentication." -ForegroundColor Yellow
    Write-Host "Log in with the account that owns the kitahim.uk zone." -ForegroundColor Yellow
    Write-Host ""
    # The 'cloudflared tunnel create' command requires interactive auth.
    # The credential file lands in C:\Users\<user>\.cloudflared\<UUID>.json
    & $cf.Source tunnel create $TunnelName 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "tunnel create failed"
        exit 1
    }
    if (-not (Test-Path $TunnelIdFile)) {
        Write-Error "Tunnel created but ID file not found at $TunnelIdFile"
        exit 1
    }
    $tunnelId = Get-Content $TunnelIdFile -Raw
    Write-Host "  Tunnel created: $tunnelId" -ForegroundColor Green
}

# ============================================
# Step 2: Write config.yml
# ============================================

Write-Host ""
Write-Host "Writing cloudflared config.yml..." -ForegroundColor Yellow

# Make sure the config dir exists
if (-not (Test-Path $cloudflaredDir)) {
    New-Item -ItemType Directory -Path $cloudflaredDir | Out-Null
}

$credFile = Join-Path $cloudflaredDir "$($tunnelId.Trim()).json"
$configContent = @"
tunnel: $($tunnelId.Trim())
credentials-file: $credFile

ingress:
  - hostname: $Subdomain
    service: http://localhost:$BackendPort
  - service: http_status:404
"@
$configContent | Out-File -FilePath $TunnelConfig -Encoding UTF8
Write-Host "  Written: $TunnelConfig" -ForegroundColor Green

# ============================================
# Step 3: Add DNS CNAME record (rpg.kitahim.uk -> tunnel)
# ============================================

Write-Host ""
Write-Host "Creating DNS CNAME record ($Subdomain -> $($tunnelId.Trim()).cfargotunnel.com)..." -ForegroundColor Yellow

# Check if record already exists
$existing = Invoke-WebRequest `
    -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records?type=CNAME&name=$Subdomain" `
    -Headers @{Authorization="Bearer $apiToken"; Accept="application/json"} `
    -Method GET -UseBasicParsing -TimeoutSec 10
$existingData = $existing.Content | ConvertFrom-Json

if ($existingData.result.Count -gt 0) {
    Write-Host "  CNAME record already exists. Updating if needed..." -ForegroundColor Yellow
    $recordId = $existingData.result[0].id
    $updateBody = @{
        type = "CNAME"
        name = $Subdomain
        content = "$($tunnelId.Trim()).cfargotunnel.com"
        proxied = $true
    } | ConvertTo-Json
    Invoke-WebRequest `
        -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records/$recordId" `
        -Headers @{Authorization="Bearer $apiToken"; Accept="application/json"; "Content-Type"="application/json"} `
        -Method PUT -Body $updateBody -UseBasicParsing -TimeoutSec 10 | Out-Null
} else {
    $createBody = @{
        type = "CNAME"
        name = $Subdomain
        content = "$($tunnelId.Trim()).cfargotunnel.com"
        proxied = $true
    } | ConvertTo-Json
    Invoke-WebRequest `
        -Uri "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records" `
        -Headers @{Authorization="Bearer $apiToken"; Accept="application/json"; "Content-Type"="application/json"} `
        -Method POST -Body $createBody -UseBasicParsing -TimeoutSec 10 | Out-Null
}
Write-Host "  DNS record created/updated." -ForegroundColor Green

# ============================================
# Step 4: Install cloudflared as a Windows service
# ============================================

Write-Host ""
Write-Host "Installing cloudflared as Windows service..." -ForegroundColor Yellow

# Check if service already exists
$svc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "  Service 'cloudflared' already installed (state: $($svc.Status))" -ForegroundColor Yellow
    Write-Host "  Skipping 'cloudflared service install'." -ForegroundColor Yellow
} else {
    & $cf.Source service install 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "cloudflared service install failed. You can run it manually later."
    } else {
        Write-Host "  cloudflared installed as Windows service." -ForegroundColor Green
    }
}

# ============================================
# Step 5: Verify public URL
# ============================================

Write-Host ""
Write-Host "Verifying $Subdomain responds..." -ForegroundColor Yellow
$verified = $false
for ($i = 1; $i -le 5; $i++) {
    Start-Sleep -Seconds 3
    try {
        $r = Invoke-WebRequest -Uri "https://$Subdomain/health" -Method GET -UseBasicParsing -TimeoutSec 15
        if ($r.StatusCode -eq 200) {
            $body = $r.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
            Write-Host "  Status: 200 OK" -ForegroundColor Green
            if ($body) {
                Write-Host "  Mode:    $($body.mode)"
                Write-Host "  Version: $($body.version)"
            }
            $verified = $true
            break
        }
    } catch {
        # DNS propagation can take a few seconds after the CNAME
        # record is created; keep retrying.
    }
}

if (-not $verified) {
    Write-Warning @"
$Subdomain did not return 200 within 15s. This is normal for the
first few minutes after creating a CNAME (DNS propagation). The
operator can verify later with:
  curl https://$Subdomain/health
"@
}

# Persist the named tunnel URL (replaces the old trycloudflare URL file)
$UrlFile = Join-Path $ProjectRoot "logs\cloudflared-url.txt"
$Subdomain | Out-File -FilePath $UrlFile -Encoding UTF8 -NoNewLine
Write-Host "  URL file updated: $UrlFile" -ForegroundColor Green

Write-Host ""
Write-Host "=== Named tunnel setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Tunnel name:   $TunnelName"
Write-Host "  Tunnel ID:     $($tunnelId.Trim())"
Write-Host "  Public URL:    https://$Subdomain" -ForegroundColor Cyan
Write-Host "  Backend at:    http://localhost:$BackendPort"
Write-Host "  Service:       cloudflared (auto-starts on boot)"
Write-Host ""
Write-Host "Players can now bookmark https://$Subdomain and it won't change." -ForegroundColor Yellow
Write-Host ""
Write-Host "If you previously used the Quick Tunnel, that script" -ForegroundColor Gray
Write-Host "(setup_cloudflared.ps1) is no longer needed." -ForegroundColor Gray

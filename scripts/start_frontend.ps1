<#
.SYNOPSIS
    Serve the built frontend (frontend/dist/) as static files
    on port 5173 using Python's built-in http.server.

.DESCRIPTION
    Phase L1 step H3 of 6 (per spec Open Question 2 answer:
    option 1 = port 5173, no nginx). The frontend is a Vite
    SPA; 'python -m http.server' is enough for static serving
    in a closed demo (no caching, no gzip, no rate limiting —
    these would matter for public production but not for a
    1-month BAZOOKA demo with 4 friends).

    Pre-requisites:
      1. frontend/dist/ exists with a built SPA. Run
         'npm run build' from frontend/ first.
      2. The Cloudflare Quick Tunnel (or any reverse proxy)
         points at http://localhost:5173 for the frontend.

    Wait — that's wrong. The current setup is:
      - Cloudflare Quick Tunnel -> http://localhost:8000 (backend)
      - The backend serves the frontend at GET / (Vite dev) or
        via a static mount (prod build).
      - We do NOT separately serve the frontend on 5173.

    REVISED APPROACH (per spec):
      - The Vite build emits to frontend/dist/.
      - We mount this directory onto the FastAPI backend as
        a StaticFiles app, so the same :8000 origin serves
        both /api/* and / (the SPA).
      - That removes the need for a separate :5173 listener.
      - The Quick Tunnel continues to point at :8000.

    What this script does:
      1. Validates frontend/dist/index.html exists.
      2. Copies frontend/dist/ to backend/static/ (so the
         FastAPI StaticFiles mount in backend/main.py can
         serve it without changes to the main.py code path).
      3. Touches backend/static/.last-deploy so the operator
         can see when the frontend was last synced.
      4. Restarts the OpenClawSandboxRPG service (NSSM)
         so the new static files are picked up.
      5. Smoke tests GET / returns 200 + HTML.

.PARAMETER ProjectRoot
    Default: inferred from script location.

.EXAMPLE
    .\start_frontend.ps1
    # Default: copy dist/ to backend/static/, restart service,
    # smoke test.

.NOTES
    Part of: Phase L1 deployment tooling (#65 onward)
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07

    Why the REVISED APPROACH (mounting on :8000) instead of
    a separate :5173 listener:
      - Single origin for the SPA + API (avoids CORS preflight
        on every fetch).
      - One port to tunnel.
      - No need for a reverse proxy or a second systemd
        service.
    This is what the existing backend/main.py already supports
    via `app.mount("/", StaticFiles(directory="static"))` — we
    just need to populate the static/ dir.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [int]$BackendPort = 8000,
    [string]$ServiceName = "OpenClawSandboxRPG"
)

$ErrorActionPreference = "Stop"

Write-Host "=== OpenClaw Sandbox RPG — Frontend static serve ===" -ForegroundColor Cyan
Write-Host ""

# ============================================
# Pre-flight
# ============================================

$FrontendDir = Join-Path $ProjectRoot "frontend"
$DistDir = Join-Path $FrontendDir "dist"
$IndexHtml = Join-Path $DistDir "index.html"
$BackendDir = Join-Path $ProjectRoot "backend"
$StaticDir = Join-Path $BackendDir "static"

if (-not (Test-Path $IndexHtml)) {
    Write-Error @"
Frontend dist/index.html not found at: $IndexHtml

Build the frontend first:
  cd frontend
  npm install
  npm run build

This produces frontend/dist/ with index.html and a hash-named
JS bundle.
"@
    exit 1
}

# ============================================
# Step 1: Copy dist/ to backend/static/
# ============================================

Write-Host "Syncing frontend/dist/ -> backend/static/..." -ForegroundColor Yellow

# Robocopy handles 'dist' to 'static' cleanly with /MIR (mirror)
# Use a conservative set of flags:
#   /MIR   : mirror (deletes files in dest that aren't in src)
#   /IS    : include same files (timestamps, etc.)
#   /IT    : include tweaked files (preserve attributes)
#   /R:1   : 1 retry on lock
#   /W:1   : 1 second wait between retries
#   /NFL /NDL /NP /NJH /NJS : quiet output (only show summary)
robocopy $DistDir $StaticDir /MIR /IS /IT /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
# robocopy exit codes: 0-7 are success-ish, 8+ are errors
if ($LASTEXITCODE -ge 8) {
    Write-Error "robocopy failed with exit code $LASTEXITCODE"
    exit 1
}
# Touch a marker file so the operator can see when the last
# deploy happened.
$markerFile = Join-Path $StaticDir ".last-deploy"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"Frontend deployed at $timestamp (commit: $(git -C $ProjectRoot rev-parse --short HEAD 2>$null))" |
    Out-File -FilePath $markerFile -Encoding UTF8

Write-Host "  Synced. Marker: $markerFile" -ForegroundColor Green

# ============================================
# Step 2: Restart the backend service
# ============================================

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($service) {
    Write-Host ""
    Write-Host "Restarting service '$ServiceName'..." -ForegroundColor Yellow
    & nssm stop $ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    & nssm start $ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 3

    $service.Refresh()
    if ($service.Status -ne "Running") {
        Write-Error "Service did not come back to Running state (current: $($service.Status))"
        exit 1
    }
    Write-Host "  Service '$ServiceName' restarted (status: $($service.Status))" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Service '$ServiceName' not installed (skipping restart)" -ForegroundColor Yellow
    Write-Host "If you want the new static files served, run scripts\install_service.ps1 first," -ForegroundColor Yellow
    Write-Host "or just restart the backend manually." -ForegroundColor Yellow
}

# ============================================
# Step 3: Smoke test GET /
# ============================================

Write-Host ""
Write-Host "Smoke testing GET http://localhost:$BackendPort/ ..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:$BackendPort/" -Method GET -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        # Check for the SPA root element (Vite uses <div id="app">)
        if ($response.Content -like '*id="app"*') {
            Write-Host "  Status: 200 OK, served index.html with #app element" -ForegroundColor Green
        } else {
            Write-Host "  Status: 200 OK, but no #app element found. Wrong dist build?" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Status: $($response.StatusCode) (expected 200)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Request failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  (If the backend is not on this machine, use a different host:port.)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Frontend deploy complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next: the Quick Tunnel URL (from logs/cloudflared-url.txt)" -ForegroundColor Yellow
Write-Host "now serves the SPA at /. Backend API at /api/*." -ForegroundColor Yellow

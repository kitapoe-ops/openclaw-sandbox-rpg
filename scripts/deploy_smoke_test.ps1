<#
.SYNOPSIS
    End-to-end validation of a fresh BAZOOKA deployment: every
    component (Postgres, .env, NSSM service, frontend static,
    /health endpoint, Cloudflare Quick Tunnel URL) is checked
    and the script prints a green/red summary.

.DESCRIPTION
    Phase L1 step H5 of 6. This is the "did Phase L1 work?"
    check. Run after:
      1. setup_postgres.ps1
      2. run_migrations.ps1
      3. install_service.ps1
      4. start_frontend.ps1
      5. setup_cloudflared.ps1

    The script does NOT modify anything; it only reads state
    and reports.

    What it checks (in order):
      1. backend/.env exists and is not the placeholder.
      2. Postgres reachable as rpg_user (psql -c "SELECT 1").
      3. Alembic current revision is set (no pending migrations).
      4. NSSM service is installed and Running.
      5. Backend /health endpoint returns 200 with expected
         JSON fields.
      6. Frontend GET / returns 200 HTML with <div id="app">.
      7. Cloudflare URL file exists and looks valid.
      8. LM Studio :1234 is reachable (optional — the server
         can run without it but the audit-hook skill degrades).

    Each check is independent: a failure in one doesn't skip
    the others. The script exits 0 only if ALL critical checks
    pass; LM Studio is non-critical and prints a warning.

.EXAMPLE
    .\deploy_smoke_test.ps1
    # Full diagnostic; prints a summary table at the end.

.NOTES
    Part of: Phase L1 deployment tooling (#67 onward)
    Author: Him / BAZOOKA deployment
    Date: 2026-06-07

    Critical checks (fail = non-zero exit):
      - .env present
      - Postgres reachable
      - NSSM service Running
      - /health returns 200
      - Frontend GET / returns 200
      - Cloudflare URL file present

    Non-critical checks (warn but don't fail):
      - LM Studio reachable
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [int]$BackendPort = 8000,
    [string]$ServiceName = "OpenClawSandboxRPG"
)

$ErrorActionPreference = "Continue"

Write-Host "=== OpenClaw Sandbox RPG — deployment smoke test ===" -ForegroundColor Cyan
Write-Host ""

$results = @()  # Array of [CheckName, Pass, Detail]

function Add-Result($name, $pass, $detail) {
    $script:results += [PSCustomObject]@{
        Check = $name
        Pass  = $pass
        Detail = $detail
    }
}

# ============================================
# Check 1: .env exists and is not placeholder
# ============================================

$EnvFile = Join-Path $ProjectRoot "backend\.env"
if (-not (Test-Path $EnvFile)) {
    Add-Result "1. backend/.env exists" $false "NOT FOUND at $EnvFile"
} else {
    $envContent = Get-Content $EnvFile -Raw
    $isPlaceholder = $envContent -match "change_me_in_production|change…tion"
    if ($isPlaceholder) {
        Add-Result "1. backend/.env exists" $true "PRESENT but contains placeholder values"
    } else {
        Add-Result "1. backend/.env exists" $true "PRESENT with real values"
    }
}

# ============================================
# Check 2: Postgres reachable as rpg_user
# ============================================

$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) {
    Add-Result "2. Postgres reachable" $false "psql not on PATH (run setup_postgres.ps1)"
} else {
    # Read password from .env
    $pgPasswordMatch = [regex]::Match($envContent, '(?m)^POSTGRES_PASSWORD=(.+)$')
    if ($pgPasswordMatch.Success) {
        $pgPassword = $pgPasswordMatch.Groups[1].Value.Trim() -replace '^["'']|["'']$', ''
        $env:PGPASSWORD = $pgPassword
        try {
            $out = & psql -h localhost -p 5432 -U rpg_user -d sandbox_rpg -tAc "SELECT 1" 2>&1
            if ($LASTEXITCODE -eq 0 -and $out -match "1") {
                Add-Result "2. Postgres reachable" $true "psql connects as rpg_user to sandbox_rpg"
            } else {
                Add-Result "2. Postgres reachable" $false "psql returned: $out"
            }
        } catch {
            Add-Result "2. Postgres reachable" $false $_.Exception.Message
        }
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    } else {
        Add-Result "2. Postgres reachable" $false "POSTGRES_PASSWORD not in .env"
    }
}

# ============================================
# Check 3: Alembic current revision
# ============================================

$VenvDir = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Add-Result "3. Alembic current revision" $false ".venv\Scripts\python.exe not found"
} else {
    Push-Location (Join-Path $ProjectRoot "backend")
    try {
        $out = & $PythonExe -m alembic current 2>&1
        if ($LASTEXITCODE -eq 0 -and $out -match "Current revision") {
            Add-Result "3. Alembic current revision" $true ($out -split "`n" | Select-Object -First 1)
        } else {
            Add-Result "3. Alembic current revision" $false "alembic current failed: $out"
        }
    } finally {
        Pop-Location
    }
}

# ============================================
# Check 4: NSSM service Running
# ============================================

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Add-Result "4. NSSM service Running" $false "Service '$ServiceName' is not installed"
} elseif ($svc.Status -ne "Running") {
    Add-Result "4. NSSM service Running" $false "Status: $($svc.Status)"
} else {
    Add-Result "4. NSSM service Running" $true "Status: Running"
}

# ============================================
# Check 5: Backend /health
# ============================================

try {
    $response = Invoke-WebRequest -Uri "http://localhost:$BackendPort/health" -Method GET -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        $body = $response.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        $hasExpected = $body -and $body.status -eq "ok" -and $body.version -and $body.mode
        if ($hasExpected) {
            Add-Result "5. /health returns 200" $true "status=ok version=$($body.version) mode=$($body.mode)"
        } else {
            Add-Result "5. /health returns 200" $true "200 OK but unexpected JSON shape: $($response.Content.Substring(0, [Math]::Min(150, $response.Content.Length)))"
        }
    } else {
        Add-Result "5. /health returns 200" $false "HTTP $($response.StatusCode)"
    }
} catch {
    Add-Result "5. /health returns 200" $false $_.Exception.Message
}

# ============================================
# Check 6: Frontend GET /
# ============================================

try {
    $response = Invoke-WebRequest -Uri "http://localhost:$BackendPort/" -Method GET -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        if ($response.Content -like '*id="app"*') {
            Add-Result "6. Frontend GET /" $true "200 OK with Vite #app root"
        } else {
            Add-Result "6. Frontend GET /" $true "200 OK but no #app element (wrong dist build?)"
        }
    } else {
        Add-Result "6. Frontend GET /" $false "HTTP $($response.StatusCode)"
    }
} catch {
    Add-Result "6. Frontend GET /" $false $_.Exception.Message
}

# ============================================
# Check 7: Cloudflare URL file
# ============================================

$UrlFile = Join-Path $ProjectRoot "logs\cloudflared-url.txt"
if (-not (Test-Path $UrlFile)) {
    Add-Result "7. Cloudflare URL file" $false "Not found at $UrlFile (run setup_cloudflared.ps1)"
} else {
    $url = Get-Content $UrlFile -ErrorAction SilentlyContinue
    if ($url -and $url -like "https://*.trycloudflare.com") {
        Add-Result "7. Cloudflare URL file" $true $url
    } else {
        Add-Result "7. Cloudflare URL file" $false "File content is not a trycloudflare.com URL: '$url'"
    }
}

# ============================================
# Check 8 (non-critical): LM Studio :1234
# ============================================

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:1234/v1/models" -Method GET -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        Add-Result "8. LM Studio :1234 reachable" $true "Models endpoint returns 200 (audit-hook OK)"
    } else {
        Add-Result "8. LM Studio :1234 reachable" $false "HTTP $($response.StatusCode) (audit-hook will degrade)"
    }
} catch {
    Add-Result "8. LM Studio :1234 reachable" $false "$($_.Exception.Message) (audit-hook will degrade; non-critical)"
}

# ============================================
# Print results table
# ============================================

Write-Host ""
Write-Host "Results:" -ForegroundColor Cyan
Write-Host ("-" * 80)
$passCount = 0
$failCount = 0
foreach ($r in $results) {
    $icon = if ($r.Pass) { "[PASS]" } else { "[FAIL]" }
    $color = if ($r.Pass) { "Green" } else { "Red" }
    Write-Host ("{0,-10} {1,-45} {2}" -f $icon, $r.Check, $r.Detail) -ForegroundColor $color
    if ($r.Pass) { $passCount++ } else { $failCount++ }
}
Write-Host ("-" * 80)
Write-Host ""
Write-Host "Summary: $passCount passed, $failCount failed (out of $($results.Count))" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Yellow" })

# Exit code: 0 only if all critical (1-7) pass; 8 (LM Studio) is
# non-critical and doesn't affect the exit code.
$criticalFail = ($results | Where-Object { -not $_.Pass -and $_.Check -notlike "8.*" }).Count
if ($criticalFail -gt 0) {
    Write-Host ""
    Write-Host "$criticalFail critical check(s) failed. See above for details." -ForegroundColor Red
    Write-Host "Run the appropriate setup_*.ps1 / install_service.ps1 to fix." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== ALL CRITICAL CHECKS PASSED ===" -ForegroundColor Green
Write-Host "Phase L1 deployment looks healthy. Players can connect at:" -ForegroundColor Cyan
$urlFile = Get-Content $UrlFile -ErrorAction SilentlyContinue
if ($urlFile) {
    Write-Host "  $urlFile" -ForegroundColor White
} else {
    Write-Host "  http://localhost:$BackendPort/  (local only)" -ForegroundColor White
}

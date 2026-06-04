<#
.SYNOPSIS
    HTTP smoke test for the OpenClaw Sandbox RPG FastAPI backend.

.DESCRIPTION
    Starts uvicorn on port 8765 in the background, seeds demo data, hits
    /health, /api/character/<id>, /api/world/<id>/state,
    /api/action/submit (expected 400, no scene), /api/scene/<id>/seed,
    and /api/action/submit again (expected 200), then kills uvicorn.

    Prints PASS / FAIL for each of 6 steps and a final summary.

    Exit code 0 if all 6 steps PASS, non-zero otherwise.

    The Traditional-Chinese JSON request bodies are loaded from
    scripts/action_body.json and scripts/seed_body.json to keep this
    script 100% ASCII (PowerShell 5.1 cannot parse non-ASCII string
    literals embedded inline in .ps1 source files reliably).

.PARAMETER Port
    Port for uvicorn (default 8765). Avoid 8000/8080/5173 (commonly in use).
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$HostAddr = "127.0.0.1",
    [int]$WaitSeconds = 3
)

# ============================================================
# Paths
# ============================================================
$ScriptDir      = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot    = Resolve-Path (Join-Path $ScriptDir "..")
$Python         = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SeedScript     = Join-Path $ProjectRoot "backend\seed_demo.py"
$ActionBodyFile = Join-Path $ScriptDir "action_body.json"
$SeedBodyFile   = Join-Path $ScriptDir "seed_body.json"

# ============================================================
# Helpers
# ============================================================
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$script:PassCount = 0
$script:FailCount = 0
$script:LogFile   = Join-Path $ProjectRoot "smoke_test.log"

function Write-Log {
    param([string]$Message)
    $ts = (Get-Date).ToString("HH:mm:ss")
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $script:LogFile -Value $line -Encoding UTF8
}

function Report-Step {
    param(
        [int]$StepNum,
        [string]$Name,
        [bool]$Passed,
        [string]$Detail = ""
    )
    if ($Passed) {
        $script:PassCount += 1
        Write-Log "  PASS step ${StepNum}: ${Name}  ${Detail}"
    } else {
        $script:FailCount += 1
        Write-Log "  FAIL step ${StepNum}: ${Name}  ${Detail}"
    }
}

# Read a JSON file as UTF-8 bytes (for request bodies that contain CJK chars).
function Read-JsonBodyBytes {
    param([string]$Path)
    return [System.IO.File]::ReadAllBytes($Path)
}

# Patch a JSON body's "character_id" field with the actual id we got from seed.
# We do this by parsing -> mutating -> reserialising in PowerShell.
function Set-CharacterIdInJson {
    param([string]$Path, [string]$CharacterId)
    $obj = Get-Content -Raw -Path $Path -Encoding UTF8 | ConvertFrom-Json
    $obj.character_id = $CharacterId
    $json = $obj | ConvertTo-Json -Depth 20 -Compress
    return [System.Text.Encoding]::UTF8.GetBytes($json)
}

function Test-HealthEndpoint {
    param([string]$BaseUrl)
    try {
        $resp = Invoke-WebRequest -Uri "$BaseUrl/health" -Method GET -TimeoutSec 5 -UseBasicParsing
        $ok = ($resp.StatusCode -eq 200) -and ($resp.Content -match '"status"\s*:\s*"ok"')
        return @{ Passed = $ok; StatusCode = $resp.StatusCode; Body = $resp.Content }
    } catch {
        return @{ Passed = $false; StatusCode = $null; Body = $_.Exception.Message }
    }
}

function Test-JsonEndpoint {
    param(
        [string]$Url,
        [string]$Method = "GET",
        [byte[]]$BodyBytes = $null,
        [int[]]$ExpectedStatus = @(200),
        [string]$ExpectedContains = ""
    )

    # Use HttpClient directly — PowerShell 5.1's Invoke-WebRequest
    # disposes the error response stream before the catch block can
    # read it, leaving us with an empty body. System.Net.Http.HttpClient
    # is reliable.
    if (-not ('System.Net.Http.HttpClient' -as [type])) {
        try { Add-Type -AssemblyName System.Net.Http } catch {}
    }
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client  = [System.Net.Http.HttpClient]::new($handler)
    try {
        $httpMethod = switch ($Method.ToUpper()) {
            "GET"    { [System.Net.Http.HttpMethod]::Get }
            "POST"   { [System.Net.Http.HttpMethod]::Post }
            "PUT"    { [System.Net.Http.HttpMethod]::Put }
            "DELETE" { [System.Net.Http.HttpMethod]::Delete }
            "PATCH"  { [System.Net.Http.HttpMethod]::Patch }
            "HEAD"   { [System.Net.Http.HttpMethod]::Head }
            "OPTIONS" { [System.Net.Http.HttpMethod]::Options }
            default  { [System.Net.Http.HttpMethod]::Get }
        }
        $req = [System.Net.Http.HttpRequestMessage]::new($httpMethod, $Url)
        if ($null -ne $BodyBytes) {
            $content = [System.Net.Http.ByteArrayContent]::new($BodyBytes)
            $content.Headers.ContentType =
                [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/json")
            $req.Content = $content
        }
        $task = $client.SendAsync($req)
        $resp = $task.GetAwaiter().GetResult()
        $code = [int]$resp.StatusCode
        $bodyStr = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $resp.Dispose()
        $statusOk = $ExpectedStatus -contains $code
        $containsOk = ($ExpectedContains -eq "") -or ($bodyStr -match [regex]::Escape($ExpectedContains))
        return @{
            Passed        = $statusOk -and $containsOk
            StatusCode    = $code
            Body          = $bodyStr
            StatusMatched = $statusOk
            ContainsMatch = $containsOk
        }
    } catch {
        $code = $null
        $body = $null
        # Try to extract code + body from HttpRequestException
        $ex = $_.Exception
        while ($ex -and -not $ex.GetType().Name -eq "HttpRequestException") { $ex = $ex.InnerException }
        if ($ex) {
            $prop = $ex.PSObject.Properties['StatusCode']
            if ($prop) { $code = [int]$prop.Value }
        }
        if ($code -and $ex.Response) {
            try {
                $body = $ex.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            } catch {}
        }
        if ($null -eq $body) {
            $body = $_.Exception.ToString()
        }
        $statusOk = $ExpectedStatus -contains $code
        $containsOk = ($ExpectedContains -eq "") -or ($body -match [regex]::Escape($ExpectedContains))
        return @{
            Passed        = $statusOk -and $containsOk
            StatusCode    = $code
            Body          = $body
            StatusMatched = $statusOk
            ContainsMatch = $containsOk
        }
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

# ============================================================
# Start
# ============================================================
"" | Set-Content -Path $script:LogFile -Encoding UTF8

Write-Log "============================================================"
Write-Log "OpenClaw Sandbox RPG - HTTP smoke test"
Write-Log "Project: $ProjectRoot"
Write-Log "Port:    $Port"
Write-Log "============================================================"

# 0. Sanity
if (-not (Test-Path $Python)) {
    Write-Log "FATAL: python not found at $Python"
    exit 2
}
if (-not (Test-Path $SeedScript)) {
    Write-Log "FATAL: seed script not found at $SeedScript"
    exit 2
}

# 1. Start uvicorn in background.
#
# Important: the in-memory `store` singleton lives in the Python process.
# Running `python backend/seed_demo.py` as a separate process and then
# `python -m uvicorn` as another process does NOT share state — the seed
# populates one process's store and uvicorn has an empty one. So we launch
# uvicorn via a one-liner that imports `seed_demo.seed_all()` and then
# runs uvicorn.run(app, ...) IN THE SAME PROCESS, guaranteeing the store
# is shared.
#
# The launcher uses os.path.dirname(__file__) to find the project root, so
# we don't need to embed a brittle absolute path string. Host/port come
# from environment variables set below.
$uvicornLauncherCode = @'
import os
import sys
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
import backend.seed_demo as s
result = s.seed_all(verbose=False)
# Emit parseable summary on stdout for the smoke test to pick up
print('CHARACTER_ID=' + result['character_id'])
print('WORLD_ID=' + result['world_id'])
print('CHARACTER_NAME=' + result['character_name'])
sys.stdout.flush()
import uvicorn
from backend.main import app
PORT = int(os.environ.get('SMOKE_TEST_PORT', '8765'))
HOST = os.environ.get('SMOKE_TEST_HOST', '127.0.0.1')
uvicorn.run(app, host=HOST, port=PORT, log_level='info')
'@
$uvicornLauncherFile = Join-Path $ProjectRoot "uvicorn_launcher.py"
Set-Content -Path $uvicornLauncherFile -Value $uvicornLauncherCode -Encoding UTF8

# Pass host/port via env vars (avoids embedding them in the launcher file).
$env:SMOKE_TEST_HOST = $HostAddr
$env:SMOKE_TEST_PORT = "$Port"

$uvicornArgs = @(
    $uvicornLauncherFile
)
Write-Log "Starting uvicorn (with in-process seed): $Python $($uvicornArgs -join ' ')"

$uvicornStdout = Join-Path $ProjectRoot "uvicorn.out.log"
$uvicornStderr = Join-Path $ProjectRoot "uvicorn.err.log"
"" | Set-Content -Path $uvicornStdout -Encoding UTF8
"" | Set-Content -Path $uvicornStderr -Encoding UTF8

$uvicornProc = Start-Process `
    -FilePath $Python `
    -ArgumentList $uvicornArgs `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $uvicornStdout `
    -RedirectStandardError $uvicornStderr `
    -WindowStyle Hidden `
    -PassThru

Write-Log "Uvicorn PID = $($uvicornProc.Id), waiting $WaitSeconds s for startup..."
Start-Sleep -Seconds $WaitSeconds

# 2. Probe /health; if down, wait a few more times
$baseUrl = "http://${HostAddr}:${Port}"
$health = Test-HealthEndpoint -BaseUrl $baseUrl
$started = $health.Passed
if (-not $started) {
    Write-Log "Server not up yet, retrying 2x..."
    for ($i = 1; $i -le 2; $i++) {
        Start-Sleep -Seconds 2
        $health = Test-HealthEndpoint -BaseUrl $baseUrl
        if ($health.Passed) { $started = $true; break }
    }
}

if (-not $started) {
    Write-Log "FATAL: uvicorn failed to start within timeout."
    Write-Log "--- uvicorn stdout ---"
    Get-Content $uvicornStdout -Tail 50 | ForEach-Object { Write-Log $_ }
    Write-Log "--- uvicorn stderr ---"
    Get-Content $uvicornStderr -Tail 50 | ForEach-Object { Write-Log $_ }
    try { Stop-Process -Id $uvicornProc.Id -Force -ErrorAction SilentlyContinue } catch {}
    exit 3
}
Write-Log "Uvicorn up (PID $($uvicornProc.Id))."

# Clean up the launcher file now that the process is running
try {
    if (Test-Path $uvicornLauncherFile) {
        # The python process may still have the file open; safe to remove anyway on Windows
        Remove-Item -Path $uvicornLauncherFile -Force -ErrorAction SilentlyContinue
    }
} catch {}

# 3. Parse CHARACTER_ID / WORLD_ID from the launcher stdout
# (the seed ran in the same process as uvicorn, before uvicorn began
# listening; stdout is captured in $uvicornStdout).
Write-Log "Reading seed output from launcher..."
if (Test-Path $uvicornStdout) {
    $seedOutput = Get-Content $uvicornStdout -Raw -Encoding UTF8
    $seedOutput.Split("`n") | ForEach-Object { if ($_.Trim()) { Write-Log "  seed: $_" } }
} else {
    $seedOutput = ""
}

# Parse CHARACTER_ID and WORLD_ID from output
$characterId = "char_starter_aria"
$worldId     = "dnd_5e_forgotten_realms"
$charMatch = $seedOutput | Select-String -Pattern "^CHARACTER_ID=(.+)$"
if ($charMatch) { $characterId = $charMatch.Matches[0].Groups[1].Value }
$worldMatch = $seedOutput | Select-String -Pattern "^WORLD_ID=(.+)$"
if ($worldMatch) { $worldId = $worldMatch.Matches[0].Groups[1].Value }
Write-Log "Using character_id='$characterId', world_id='$worldId'"

try {
    # ============================================================
    # Step 1: GET /health
    # ============================================================
    $r = Test-HealthEndpoint -BaseUrl $baseUrl
    Report-Step 1 "/health" $r.Passed "(status=$($r.StatusCode))"

    # ============================================================
    # Step 2: GET /api/character/<id>
    # ============================================================
    $r = Test-JsonEndpoint `
        -Url "$baseUrl/api/character/$characterId" `
        -Method GET `
        -ExpectedStatus 200 `
        -ExpectedContains $characterId
    Report-Step 2 "GET /api/character/$characterId" $r.Passed "(status=$($r.StatusCode))"

    # ============================================================
    # Step 3: GET /api/world/<world_id>/state
    # ============================================================
    $r = Test-JsonEndpoint `
        -Url "$baseUrl/api/world/$worldId/state" `
        -Method GET `
        -ExpectedStatus 200 `
        -ExpectedContains $worldId
    Report-Step 3 "GET /api/world/$worldId/state" $r.Passed "(status=$($r.StatusCode))"

    # ============================================================
    # Step 4: POST /api/action/submit (expect 400 - no scene yet)
    # ============================================================
    $actionBytes = Set-CharacterIdInJson -Path $ActionBodyFile -CharacterId $characterId
    $r = Test-JsonEndpoint `
        -Url "$baseUrl/api/action/submit" `
        -Method POST `
        -BodyBytes $actionBytes `
        -ExpectedStatus 400
    # The validation should mention opt_01 (since no scene has opt_01 in choices)
    $containsOk = ($r.Body -match "opt_01") -or ($r.Body -match "scene")
    $passed = $r.Passed -and $containsOk
    Report-Step 4 "POST /api/action/submit (no scene -> 400)" $passed "(status=$($r.StatusCode))"

    # ============================================================
    # Step 5: POST /api/scene/<id>/seed
    # ============================================================
    $seedBytes = [System.IO.File]::ReadAllBytes($SeedBodyFile)
    $r = Test-JsonEndpoint `
        -Url "$baseUrl/api/scene/$characterId/seed" `
        -Method POST `
        -BodyBytes $seedBytes `
        -ExpectedStatus 200 `
        -ExpectedContains "opt_01"
    Report-Step 5 "POST /api/scene/$characterId/seed" $r.Passed "(status=$($r.StatusCode))"

    # ============================================================
    # Step 6: POST /api/action/submit again (expect 200 with new scene)
    # ============================================================
    $r = Test-JsonEndpoint `
        -Url "$baseUrl/api/action/submit" `
        -Method POST `
        -BodyBytes $actionBytes `
        -ExpectedStatus 200
    $hasScene = $r.Body -match '"scene"'
    $passed6 = $r.Passed -and $hasScene
    Report-Step 6 "POST /api/action/submit (with scene -> 200)" $passed6 "(status=$($r.StatusCode), has_scene=$hasScene)"
}
finally {
    # ============================================================
    # Kill uvicorn
    # ============================================================
    Write-Log "Stopping uvicorn PID $($uvicornProc.Id)..."
    try {
        $proc = Get-Process -Id $uvicornProc.Id -ErrorAction SilentlyContinue
        if ($proc) {
            Get-CimInstance Win32_Process -Filter "ParentProcessId=$($uvicornProc.Id)" |
                ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
            Stop-Process -Id $uvicornProc.Id -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Log "  (could not stop uvicorn: $_)"
    }
    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object {
                try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
            }
    } catch {}
}

# ============================================================
# Final
# ============================================================
$total = $script:PassCount + $script:FailCount
Write-Log "============================================================"
Write-Log "Smoke test summary: $script:PassCount / $total steps PASS"
if ($script:FailCount -gt 0) {
    Write-Log "FAILED steps: $script:FailCount"
    Write-Log "============================================================"
    exit 1
}
Write-Log "ALL PASS"
Write-Log "============================================================"
exit 0

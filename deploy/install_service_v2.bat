@echo off
REM OpenClaw Sandbox RPG - Install Cloudflared named tunnel as Windows service
REM MUST run as Administrator
REM v2: Use cloudflared.exe directly as the service binary (proven to work
REM in our manual test). Add auto-restart on failure via sc failure.

echo === OpenClaw Sandbox RPG - Cloudflared Service Install v2 ===

REM 1. Stop and delete any existing service
echo [1/5] Removing old service (if any)...
sc stop Cloudflared 2>nul
sc delete Cloudflared 2>nul
timeout /t 2 /nobreak > nul

REM 2. Create service with cloudflared.exe as the binary directly
echo [2/5] Creating service (cloudflared.exe as binary)...
set "CF_EXE=C:\Program Files (x86)\cloudflared\cloudflared.exe"
set "TUNNEL_ID=7570db25-3848-49bb-b1d4-c9653c1c74c0"
REM sc.exe needs the full command line including arguments
set "FULL_BIN=""%CF_EXE%" tunnel run %TUNNEL_ID%"
sc create Cloudflared binPath= "%FULL_BIN%" start= auto DisplayName= "Cloudflare Tunnel" depend= ""
if errorlevel 1 (
    echo ERROR: sc create failed
    exit /b 1
)

REM 3. Configure auto-restart on failure
echo [3/5] Configuring auto-restart on failure (every 30s)...
sc failure Cloudflared reset= 30 actions= restart/5000/restart/10000/restart/30000
if errorlevel 1 (
    echo WARN: sc failure config failed
)

REM 4. Start the service
echo [4/5] Starting service...
sc start Cloudflared
if errorlevel 1 (
    echo ERROR: sc start failed
    exit /b 1
)

REM 5. Verify
echo [5/5] Verifying...
timeout /t 8 /nobreak > nul
sc query Cloudflared
echo.
echo === Service status ===
powershell -Command "Get-Service Cloudflared | Format-List"
echo === cloudflared process ===
powershell -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime | Format-Table -AutoSize"
echo === public URL test ===
curl -s -o nul -w "HTTP %%{http_code}\n" https://rpg.kitahim.uk/health 2>nul
curl -s https://rpg.kitahim.uk/health
echo.
echo === DONE ===

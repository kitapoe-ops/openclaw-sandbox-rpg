@echo off
REM OpenClaw Sandbox RPG - Install Cloudflared named tunnel as Windows service
REM MUST run as Administrator

echo === OpenClaw Sandbox RPG - Cloudflared Service Install ===

REM 1. Stop and delete any existing Cloudflared service
echo [1/4] Removing old service (if any)...
sc stop Cloudflared 2>nul
sc delete Cloudflared 2>nul
timeout /t 2 /nobreak > nul

REM 2. Create the new service
echo [2/4] Creating service with PowerShell wrapper...
set "SCRIPT_PATH=C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\deploy\start_named_tunnel_service.ps1"
set "BIN_PATH=powershell.exe -ExecutionPolicy Bypass -File ""%SCRIPT_PATH%"""
sc create Cloudflared binPath= "%BIN_PATH%" start= auto DisplayName= "Cloudflare Tunnel"
if errorlevel 1 (
    echo ERROR: sc create failed
    exit /b 1
)

REM 3. Start the service
echo [3/4] Starting service...
sc start Cloudflared
if errorlevel 1 (
    echo ERROR: sc start failed
    exit /b 1
)

REM 4. Verify
echo [4/4] Verifying...
timeout /t 5 /nobreak > nul
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

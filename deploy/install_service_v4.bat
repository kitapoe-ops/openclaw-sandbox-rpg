@echo off
REM OpenClaw Sandbox RPG - Cloudflared Service Install v4
REM v4: Run as the current user (kitap) so cloudflared can read
REM C:\Users\kitap\.cloudflared\7570db25-...json credentials.

echo === OpenClaw Sandbox RPG - Cloudflared Service Install v4 ===

echo [1/5] Removing old service...
sc stop Cloudflared 2>nul
sc delete Cloudflared 2>nul
timeout /t 2 /nobreak > nul

echo [2/5] Creating service (as current user)...
sc create Cloudflared binPath= "C:\Program Files (x86)\cloudflared\cloudflared.exe tunnel run 7570db25-3848-49bb-b1d4-c9653c1c74c0" start= auto DisplayName= "Cloudflare Tunnel" obj= ".\kitap" password= ""
if errorlevel 1 (
    echo ERROR: sc create failed
    exit /b 1
)

echo [3/5] Configuring auto-restart...
sc failure Cloudflared reset= 30 actions= restart/5000/restart/10000/restart/30000

echo [4/5] Starting service...
sc start Cloudflared
if errorlevel 1 (
    echo ERROR: sc start failed
    exit /b 1
)

echo [5/5] Verifying...
timeout /t 8 /nobreak > nul
sc query Cloudflared
echo.
powershell -Command "Get-Service Cloudflared | Format-List"
powershell -Command "Get-Process cloudflared -ErrorAction SilentlyContinue | Format-Table Id,ProcessName,StartTime -AutoSize"
echo === public URL test ===
curl -s -o nul -w "HTTP %%{http_code}\n" https://rpg.kitahim.uk/health 2>nul
curl -s https://rpg.kitahim.uk/health
echo.
echo === DONE ===

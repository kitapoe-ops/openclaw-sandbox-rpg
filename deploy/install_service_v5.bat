@echo off
REM OpenClaw Sandbox RPG - Cloudflared Service Install v5
REM v5: Keep LocalSystem (no logon issues) BUT grant LocalSystem
REM read access to C:\Users\kitap\.cloudflared\, and copy the
REM credentials file to a system-accessible location so the
REM service binary can find it regardless of USERPROFILE.

echo === OpenClaw Sandbox RPG - Cloudflared Service Install v5 ===

echo [1/6] Removing old service...
sc stop Cloudflared 2>nul
sc delete Cloudflared 2>nul
timeout /t 2 /nobreak > nul

echo [2/6] Copying credentials + cert to system-readable location...
set "SYSDIR=C:\ProgramData\cloudflared"
if not exist "%SYSDIR%" mkdir "%SYSDIR%"
copy /Y "C:\Users\kitap\.cloudflared\cert.pem" "%SYSDIR%\cert.pem" > nul
copy /Y "C:\Users\kitap\.cloudflared\7570db25-3848-49bb-b1d4-c9653c1c74c0.json" "%SYSDIR%\7570db25-3848-49bb-b1d4-c9653c1c74c0.json" > nul
copy /Y "C:\Users\kitap\.cloudflared\config.yml" "%SYSDIR%\config.yml" > nul
echo   Files copied to %SYSDIR%

echo [3/6] Creating service...
sc create Cloudflared binPath= "C:\Program Files (x86)\cloudflared\cloudflared.exe --config %SYSDIR%\config.yml tunnel run" start= auto DisplayName= "Cloudflare Tunnel"
if errorlevel 1 (
    echo ERROR: sc create failed
    exit /b 1
)

echo [4/6] Configuring auto-restart...
sc failure Cloudflared reset= 30 actions= restart/5000/restart/10000/restart/30000

echo [5/6] Starting service...
sc start Cloudflared
if errorlevel 1 (
    echo ERROR: sc start failed
    exit /b 1
)

echo [6/6] Verifying...
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

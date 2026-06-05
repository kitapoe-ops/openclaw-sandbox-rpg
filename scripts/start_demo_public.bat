@echo off
REM ============================================================================
REM start_demo_public.bat
REM ----------------------------------------------------------------------------
REM One-shot bring-up for the Sandbox-RPG demo on BAZOOKA:
REM   1. Kill any stale uvicorn / cloudflared processes from previous runs
REM   2. Start backend (port 8000) in a new window
REM   3. Start cloudflared Quick Tunnel in a new window
REM   4. Tail the tunnel log until the new *.trycloudflare.com URL appears
REM   5. Print the URL + Vercel env commands
REM
REM Usage (from repo root):
REM   scripts\start_demo_public.bat
REM
REM Stop everything later with:
REM   scripts\stop_demo_public.bat   (or just close the two new windows)
REM ============================================================================

setlocal

set "ROOT=%~dp0.."
pushd "%ROOT%"

set "CLOUDFLARED_EXE=%USERPROFILE%\cloudflared.exe"
set "TUNNEL_LOG=%ROOT%\cloudflared.log"
set "BACKEND_LOG=%ROOT%\uvicorn.out.log"
set "BACKEND_ERR=%ROOT%\uvicorn.err.log"

echo === [1/5] Killing stale uvicorn / cloudflared (if any) =================
for /f "tokens=2" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   killing PID %%P (was holding :8000)
    taskkill /F /PID %%P >nul 2>&1
)
taskkill /F /IM cloudflared.exe >nul 2>&1

echo.
echo === [2/5] Starting backend (uvicorn) in a new window ====================
start "sandbox-rpg-backend" cmd /k ^
    ".\.venv\Scripts\python.exe -m uvicorn backend.app_with_memory:app --host 0.0.0.0 --port 8000"

echo   waiting for backend to bind :8000 ...
:wait_backend
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if errorlevel 1 goto :wait_backend

echo   backend is up. Logs: %BACKEND_LOG% / %BACKEND_ERR%
echo.

echo === [3/5] Starting cloudflared Quick Tunnel in a new window ============
if not exist "%CLOUDFLARED_EXE%" (
    echo   ERROR: cloudflared not found at %CLOUDFLARED_EXE%
    echo   Install it first - see docs\DEPLOY_HOSTED_QUICKSTART.md ^§2
    popd
    endlocal
    exit /b 1
)

del /Q "%TUNNEL_LOG%" 2>nul
start "sandbox-rpg-tunnel" cmd /k ^
    ""%CLOUDFLARED_EXE%" tunnel --url http://localhost:8000 --no-autoupdate > "%TUNNEL_LOG%" 2>&1"

echo.
echo === [4/5] Waiting for trycloudflare.com URL in tunnel log ==============
echo   (this usually takes ~6-10 seconds)
:wait_url
timeout /t 2 /nobreak >nul
if not exist "%TUNNEL_LOG%" goto :wait_url
findstr /R "https://.*trycloudflare.com" "%TUNNEL_LOG%" >nul 2>&1
if errorlevel 1 goto :wait_url

for /f "tokens=*" %%U in ('findstr /R "https://.*trycloudflare.com" "%TUNNEL_LOG%"') do (
    set "TUNNEL_LINE=%%U"
    goto :got_url
)
:got_url

echo.
echo === [5/5] Tunnel is live ================================================
echo.
echo   %TUNNEL_LINE%
echo.
echo   --- Quick checks -----------------------------------------------------
echo   curl --ssl-no-revoke https://%TUNNEL_LINE:~10%/health
echo   curl --ssl-no-revoke https://%TUNNEL_LINE:~10%/memory/health
echo.
echo   --- Update Vercel env vars (project -^> Settings -^> Env Vars) --------
echo   VITE_API_BASE_URL = https://%TUNNEL_LINE:~10%
echo   VITE_WS_BASE_URL  = wss://%TUNNEL_LINE:~10%
echo.
echo   Then run:  vercel --prod
echo.
echo   --- When done --------------------------------------------------------
echo   Close the two new windows (sandbox-rpg-backend, sandbox-rpg-tunnel)
echo.

popd
endlocal

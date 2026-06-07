@echo off
REM OpenClaw Sandbox RPG ? Named tunnel Windows service wrapper
REM Run as Administrator:
REM   sc.exe create Cloudflared binPath= "%~f0 tunnel run 7570db25-3848-49bb-b1d4-c9653c1c74c0" start= auto
REM   sc.exe start Cloudflared
"C:\Program Files (x86)\cloudflared\cloudflared.exe" %*

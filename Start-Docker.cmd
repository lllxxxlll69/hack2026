@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy-docker.ps1"
set "DEPLOY_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %DEPLOY_EXIT%

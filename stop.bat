@echo off
setlocal
cd /d "%~dp0"
title AzerothPanel - stop
if not exist ".venv\Scripts\python.exe" (echo Nothing to stop - the panel was never built. & pause & exit /b 0)

rem Safely stops every server the panel started (worldserver saves players, then authserver,
rem then MySQL), then the panel itself. This can take a while if players are online.
".venv\Scripts\python.exe" -m backend stop
if errorlevel 1 (
    echo.
    echo [FAILED] See data\panel.log
    pause
    exit /b 1
)
echo.
pause
exit /b 0

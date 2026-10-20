@echo off
setlocal
cd /d "%~dp0"
title AzerothPanel - start
if not exist ".venv\Scripts\python.exe" (echo Run install.bat first. & pause & exit /b 1)
if not exist "frontend\dist\index.html" (echo Run install.bat first. & pause & exit /b 1)

rem Starts the panel in the background (no console window) and opens it in your browser.
rem The panel keeps running after this window closes; use stop.bat or "Shut down panel" in the sidebar.
".venv\Scripts\python.exe" -m backend start
if errorlevel 1 (
    echo.
    echo [FAILED] See data\panel.log
    pause
    exit /b 1
)
timeout /t 3 >nul
exit /b 0

@echo off
setlocal
cd /d "%~dp0"
title AzerothPanel - clean
echo === AzerothPanel clean ===
echo Removes build output only. Your panel settings (data) and backups (backups) are kept.
echo.

if exist "data\panel.pid" (
    for /f %%p in (data\panel.pid) do tasklist /FI "PID eq %%p" 2>nul | find "%%p" >nul && (
        echo [ERROR] The panel is running. Run stop.bat first.
        goto :fail
    )
)

call :remove ".venv" || goto :fail
call :remove "frontend\node_modules" || goto :fail
call :remove "frontend\dist" || goto :fail
for /d /r "backend" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"

echo.
echo [OK] Clean finished. Run install.bat to install again.
pause
exit /b 0

:remove
if exist "%~1" (
    echo Removing %~1
    rmdir /s /q "%~1"
    if exist "%~1" (
        echo [ERROR] Could not remove %~1 - is something still using it?
        exit /b 1
    )
)
exit /b 0

:fail
echo.
echo [FAILED] Clean did not complete.
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
title AzerothPanel - install
echo === AzerothPanel install ===
echo.

where python >nul 2>nul || (echo [ERROR] Python was not found in PATH. Install Python 3.11 or newer. & goto :fail)
python -c "import sys; sys.exit(sys.version_info < (3, 11))" || (echo [ERROR] Python 3.11 or newer is required. & goto :fail)
where npm >nul 2>nul || (echo [ERROR] npm was not found in PATH. Install Node.js 20 or newer. & goto :fail)

if exist "data\panel.pid" (
    for /f %%p in (data\panel.pid) do tasklist /FI "PID eq %%p" 2>nul | find "%%p" >nul && (
        echo [ERROR] The panel is running. Run stop.bat first.
        goto :fail
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    python -m venv .venv || goto :fail
)
echo Installing backend packages...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

echo Installing frontend packages...
pushd frontend
call npm ci --no-fund --no-audit || (popd & goto :fail)
echo Building frontend...
call npm run build || (popd & goto :fail)
popd

echo.
echo [OK] Install finished. Run start.bat to open the panel.
pause
exit /b 0

:fail
echo.
echo [FAILED] Install did not complete. See the messages above.
pause
exit /b 1

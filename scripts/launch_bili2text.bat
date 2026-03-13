@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"

pushd "%PROJECT_ROOT%" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Failed to switch to project root:
  echo         "%PROJECT_ROOT%"
  pause
  exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher "py" was not found in PATH.
  echo Install Python 3.12 and ensure the py launcher is available.
  echo Download: https://www.python.org/downloads/windows/
  pause
  popd >nul
  exit /b 1
)

py -3.12 scripts\launcher.py %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] BilibiliHarvest failed to start. Exit code: %EXIT_CODE%
  echo Try: py -3.12 scripts\launcher.py --doctor
  pause
)

popd >nul
exit /b %EXIT_CODE%

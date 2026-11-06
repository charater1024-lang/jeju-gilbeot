@echo off
setlocal
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set "CENTER_PYTHON=%~dp0runtime\python.exe"
if not exist "%CENTER_PYTHON%" (
  where python.exe >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10 or later is required. See GITHUB_RESTORE.md.
    pause
    exit /b 1
  )
  set "CENTER_PYTHON=python.exe"
)
"%CENTER_PYTHON%" "%~dp0center_app.py" %*
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%

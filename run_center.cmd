@echo off
setlocal
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
if not exist "%~dp0runtime\python.exe" (
  echo Missing runtime. Extract the complete Jeju Gilbeot package first.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" "%~dp0center_app.py" %*
if errorlevel 1 pause
endlocal

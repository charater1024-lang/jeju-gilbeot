@echo off
setlocal
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
"%~dp0runtime\python.exe" "%~dp0dev.py" test %*
if errorlevel 1 (
  echo A test failed or Node UI checks could not run. Read the report above.
  pause
  exit /b 1
)
echo Python and UI checks passed.
pause
endlocal

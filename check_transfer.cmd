@echo off
setlocal
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set PYTHONIOENCODING=utf-8
"%~dp0runtime\python.exe" "%~dp0dev.py" check
if errorlevel 1 (
  echo Verification failed or files have been edited. Read the report above.
  pause
  exit /b 1
)
echo Transfer verification passed.
pause
endlocal

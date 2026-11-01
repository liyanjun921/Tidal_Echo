@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=observer\.venv\Scripts\python.exe"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer and run this file again.
  pause
  exit /b 1
)

if not exist "%VENV_PY%" (
  echo Creating the private observer environment...
  python -m venv observer\.venv
  if errorlevel 1 goto :failed
)

echo Installing the optional OpenCV observer...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%VENV_PY%" -m pip install -r observer\requirements.txt
if errorlevel 1 goto :failed

echo.
echo Verifying the observer...
"%VENV_PY%" observer\worker.py health
if errorlevel 1 goto :failed

echo.
echo Observer installation completed.
pause
exit /b 0

:failed
echo.
echo Observer installation failed. Copy this window when asking for help.
pause
exit /b 1

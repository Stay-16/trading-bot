@echo off
setlocal
cd /d "F:\Action!\Trade\op\New folder"

echo ==========================================
echo Quotex AI Desk - WebApp / Backend
echo ==========================================
echo.

if not exist ".env" (
  echo [ERROR] Missing .env file in project root.
  echo Create it first, or copy values from .env.example
  echo.
  pause
  exit /b 1
)

set "PYTHON_EXE=C:\Users\Abde\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%PYTHON_EXE%" goto run_backend

where py >nul 2>nul
if %errorlevel%==0 (
  echo Starting backend using py...
  py run_webapp.py
  goto end
)

where python >nul 2>nul
if %errorlevel%==0 (
  echo Starting backend using python...
  python run_webapp.py
  goto end
)

echo [ERROR] Python was not found.
echo Install Python, then run:
echo pip install -r requirements.txt
echo.
pause
exit /b 1

:run_backend
echo Starting backend using:
echo %PYTHON_EXE%
"%PYTHON_EXE%" run_webapp.py

:end
echo.
echo Backend stopped.
pause
endlocal

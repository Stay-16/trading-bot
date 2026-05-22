@echo off
title Bot1 — التداول الذكي v3
cd /d "%~dp0"

set "PYTHON=C:\Users\Abde\AppData\Local\Programs\Python\Python312\python.exe"
set "WEBAPP=1"

if /i "%1"=="--no-webapp" set "WEBAPP=0"
if /i "%1"=="--silent" goto :silent

echo ==========================================
echo   بوت التداول الذكي v3 — Bot1
echo   Fusion: Confluence + AI + TV + WebApp
echo ==========================================
echo.

if not exist ".env" (
  echo [خطأ] ملف .env غير موجود!
  pause
  exit /b 1
)

:: 1. تشغيل البوت (Telegram)
echo [1/2] تشغيل البوت الرئيسي...
start "Bot-Telegram" "%PYTHON%" main.py

if "%WEBAPP%"=="1" (
  timeout /t 3 /nobreak >nul
  echo [2/2] تشغيل WebApp (http://127.0.0.1:8081)...
  start "Bot-WebApp" "%PYTHON%" run_webapp.py
)

echo.
echo ✅ البوت شغال!
echo    Telegram: افتح البوت وأرسل /start
echo    WebApp:   http://127.0.0.1:8081
echo.
echo    إيقاف: أغلق النوافذ أو استخدم Ctrl+C
echo ==========================================
pause
exit /b 0

:: ──────────────────────────────────────────────
:: Silent mode (no pause, minimized windows)
:: ──────────────────────────────────────────────
:silent
if not exist ".env" exit /b 1
start /min "Bot-Telegram" "%PYTHON%" main.py
if "%WEBAPP%"=="1" (
  timeout /t 3 /nobreak >nul
  start /min "Bot-WebApp" "%PYTHON%" run_webapp.py
)
exit /b 0

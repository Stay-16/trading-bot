# 24/7 Operation Guide

## Goal

Keep the backend running continuously so these clients can connect at any time:

- Telegram bot
- Web dashboard
- Telegram Mini App

## Recommended architecture

Run the backend on one machine that stays online all the time:

- Windows VPS or dedicated Windows PC
- Stable internet connection
- Fixed local IP or public server IP

The backend process is:

- `run_webapp.py`

## Local always-on Windows setup

1. Use a machine that remains powered on.
2. Start the backend with:
   - `C:/Users/Abde/AppData/Local/Programs/Python/Python312/python.exe run_webapp.py`
3. Keep the app reachable on port `8000`.
4. Point the browser or Telegram Mini App to that machine:
   - `http://SERVER-IP:8000`

## Run backend automatically on startup

### Option A: Task Scheduler

Create a scheduled task:

- Trigger: `At startup`
- Action: start program
- Program:
  - `C:\Users\Abde\AppData\Local\Programs\Python\Python312\python.exe`
- Arguments:
  - `F:\Action!\Trade\op\New folder\run_webapp.py`
- Start in:
  - `F:\Action!\Trade\op\New folder`

Enable:

- `Run whether user is logged on or not`
- `Restart on failure`

### Option B: NSSM service

Install NSSM and create a Windows service for the same command above.

## Important note about phone access

`http://127.0.0.1:8000` works only on the same machine.

For phones on the same network, use:

- local network IP like `http://192.168.1.50:8000`

For remote access outside your local network, use:

- VPS/public IP/domain
- or a tunnel/reverse proxy

## Best practice

For real 24/7 usage, the best path is:

1. Run the backend on VPS
2. Keep Telegram bot and Web dashboard connected to the same backend
3. Use the Web dashboard as the main visual control panel
4. Use Telegram bot and Mini App for quick access and remote control

## Health checklist

Before you rely on the system:

- backend responds on `/api/health`
- web dashboard loads market board
- Telegram bot opens and responds
- Telegram Mini App opens correctly
- Quotex connection is stable
- Task Scheduler or service restarts the backend automatically

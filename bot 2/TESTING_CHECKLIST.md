# Project Testing Checklist

## Current scope

- Telegram bot
- Web dashboard
- Telegram Mini App

## Current environment status

- Python runtime is required to run `trading_bot.py` and `run_webapp.py`.
- Node, Flutter, Tauri, desktop, and mobile checks are no longer relevant to the project scope.

## Backend and bot

1. Install Python 3.12 or the version expected by the deployment docs.
2. Create and activate a virtual environment.
3. Install project dependencies:
   - `pip install -r requirements.txt`
4. Run:
   - `py run_webapp.py`
5. Confirm:
   - `GET /` returns the web app.
   - `GET /api/health` returns success.
   - Protected endpoints reject missing or invalid `X-API-Key`.
   - Protected endpoints accept a valid `X-API-Key`.
6. Run:
   - `py trading_bot.py`
7. Confirm:
   - Telegram bot starts without import errors.
   - `/start`, `/stats`, and `/performance` respond.
   - button callbacks work.
   - trade execution respects risk rules.

## Web dashboard

1. Start the backend.
2. Open:
   - `http://HOST:8000/`
3. Confirm:
   - CSS loads.
   - JavaScript loads.
   - market board renders.
   - scanner works.
   - journal loads with a valid API token.
   - trade execution requires a valid API token and user id.
4. Open:
   - `http://HOST:8000/webapp`
5. Confirm:
   - the legacy path redirects to `/`.

## Telegram Mini App

1. Set `WEBAPP_URL` in [\.env](F:\Action!\Trade\op\New%20folder\.env) to the public URL or local URL you want Telegram to open.
2. Start the bot.
3. Open Telegram and send `/start`.
4. Confirm:
   - the WebApp button appears.
   - it opens the same web dashboard.
   - analysis and execution work with the configured API token.

## Recommended follow-up

- Add automated tests for backend risk and execution flows.
- Add a small health endpoint if one does not already exist.
- Keep the UI thin and reuse the same backend logic for Web and Telegram Mini App.

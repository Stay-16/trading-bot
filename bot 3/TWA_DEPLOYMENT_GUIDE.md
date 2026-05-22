# Telegram Web App Deployment Guide

## Goal

Run the WebApp on a public HTTPS URL and open it directly inside your Telegram bot as a Telegram Web App.

## 1. Run Locally First

Start the bot:

```powershell
& 'C:/Users/Abde/AppData/Local/Programs/Python/Python312/python.exe' 'F:/Action!/Trade/New folder/trading_bot.py'
```

Start the WebApp server:

```powershell
& 'C:/Users/Abde/AppData/Local/Programs/Python/Python312/python.exe' 'F:/Action!/Trade/New folder/run_webapp.py'
```

Local test URL:

```text
http://127.0.0.1:8000
```

## 2. Expose the WebApp Over HTTPS

Telegram Web Apps require a public HTTPS URL.

Two simple options:

### Option A: Cloudflared Tunnel

Install Cloudflared, then run:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

It will give you a public HTTPS URL like:

```text
https://something.trycloudflare.com
```

Use that HTTPS URL as your `WEBAPP_URL`.

### Option B: VPS + Domain

- Deploy the project to a VPS
- Run `run_webapp.py`
- Put Nginx in front of it
- Enable HTTPS with Let's Encrypt

## 3. Configure the Bot

Set these values in `.env`:

```env
WEBAPP_URL=https://your-public-https-url
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8000
WEBAPP_TITLE=Quotex AI Desk
```

Restart the bot after changing `.env`.

## 4. Open Inside Telegram

When `WEBAPP_URL` is set, the bot home screen shows:

```text
Open Web Dashboard
```

That button opens the WebApp inside Telegram using `WebAppInfo`, which makes it a Telegram Web App.

## 5. Optional: Set the Menu Button in BotFather

If you want the WebApp to open from the permanent bot menu:

1. Open `@BotFather`
2. Choose your bot
3. Open `Bot Settings`
4. Open `Menu Button`
5. Set the button type to `Web App`
6. Paste the same public HTTPS URL from `WEBAPP_URL`

That makes the dashboard open directly from the bot menu as a Telegram Web App.

## 6. Recommended Production Setup

- Keep the bot and WebApp on the same VPS
- Use PM2, NSSM, or Task Scheduler to keep both running
- Put the WebApp behind Nginx
- Use HTTPS only
- Keep `WEBAPP_URL` pointing to the public HTTPS domain

## 7. Notes

- `localhost` is not enough for Telegram mobile clients
- The WebApp is already wired for direct opening inside the bot
- Live candles, payout, and sentiment now come from Quotex live streams
- Higher-level analysis still uses TradingView when available, with cache and degraded fallback when rate-limited

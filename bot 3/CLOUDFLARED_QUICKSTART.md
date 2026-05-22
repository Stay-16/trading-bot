# Cloudflared Quickstart For Telegram Web App

## 1. Start the WebApp locally

```powershell
& 'C:/Users/Abde/AppData/Local/Programs/Python/Python312/python.exe' 'F:/Action!/Trade/New folder/run_webapp.py'
```

Local address:

```text
http://127.0.0.1:8000
```

## 2. Download Cloudflared

Download it from Cloudflare and place `cloudflared.exe` somewhere on your machine.

Example:

```text
C:\Tools\cloudflared\cloudflared.exe
```

## 3. Open a public HTTPS tunnel

Run:

```powershell
& 'C:\Tools\cloudflared\cloudflared.exe' tunnel --url http://127.0.0.1:8000
```

Cloudflared will print a public URL like:

```text
https://random-name.trycloudflare.com
```

## 4. Put the public URL into `.env`

Example:

```env
WEBAPP_URL=https://random-name.trycloudflare.com
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8000
WEBAPP_TITLE=Quotex AI Desk
```

Restart `trading_bot.py` after changing `.env`.

## 5. Open it inside Telegram

When `WEBAPP_URL` is present, the bot shows:

```text
Open Web Dashboard
```

That button opens the WebApp directly inside Telegram.

## 6. Set it in BotFather menu button too

In `@BotFather`:

1. Select your bot
2. Open `Bot Settings`
3. Open `Menu Button`
4. Choose `Configure menu button`
5. Set type to `Web App`
6. Paste the same `WEBAPP_URL`

Now the WebApp can open from the permanent bot menu on your phone.

## 7. Important note

The free `trycloudflare.com` URL changes every time you restart the tunnel.

So if you restart the tunnel:

1. copy the new HTTPS URL
2. update `WEBAPP_URL` in `.env`
3. restart the Telegram bot
4. update the menu button in BotFather if needed

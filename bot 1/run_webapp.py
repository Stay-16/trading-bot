"""
Launcher for the bot1 FastAPI WebApp server (port 8081).

Usage:
    python run_webapp.py

Requires bot1 dependencies (fastapi, uvicorn).
The bot (main.py) must be running separately or started via Telegram.
"""

import os
import uvicorn

if __name__ == "__main__":
    host = os.getenv("WEBAPP_HOST", "127.0.0.1")
    port = int(os.getenv("WEBAPP_PORT", "8081"))
    print(f"Bot1 WebApp: http://{host}:{port}")
    uvicorn.run("webapp_server:app", host=host, port=port, reload=False)

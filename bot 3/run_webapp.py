import os
import logging

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

import uvicorn

from bot_config import load_settings


def main() -> None:
    settings = load_settings()
    logging.getLogger("websocket").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    uvicorn.run(
        "webapp_server:app",
        host=settings.webapp.host,
        port=settings.webapp.port,
        reload=False,
    )


if __name__ == "__main__":
    main()

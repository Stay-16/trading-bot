import os
from dataclasses import dataclass


def _load_dotenv_file() -> None:
    dotenv_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(dotenv_path):
        return

    try:
        with open(dotenv_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        return


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get_env(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RiskSettings:
    risk_per_trade_pct: float = 0.02
    daily_loss_limit_pct: float = 0.10
    max_consecutive_losses: int = 3
    min_confidence_score: int = 75
    min_trade_amount: float = 1.0
    max_trade_amount: float = 25.0
    expected_payout: float = 0.82
    kelly_fraction_cap: float = 0.25


@dataclass(frozen=True)
class WebAppSettings:
    public_url: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    title: str = "Quotex AI Desk"


@dataclass(frozen=True)
class BotSettings:
    telegram_token: str
    quotex_email: str
    quotex_password: str
    cache_ttl_seconds: int = 60
    min_signals_required: int = 8
    risk: RiskSettings = RiskSettings()
    webapp: WebAppSettings = WebAppSettings()


def load_settings() -> BotSettings:
    _load_dotenv_file()
    return BotSettings(
        telegram_token=_get_env("TELEGRAM_TOKEN"),
        quotex_email=_get_env("QUOTEX_EMAIL"),
        quotex_password=_get_env("QUOTEX_PASSWORD"),
        cache_ttl_seconds=_get_int("CACHE_TTL_SECONDS", 60),
        min_signals_required=_get_int("MIN_SIGNALS_REQUIRED", 8),
        risk=RiskSettings(
            risk_per_trade_pct=_get_float("RISK_PER_TRADE_PCT", 0.02),
            daily_loss_limit_pct=_get_float("DAILY_LOSS_LIMIT_PCT", 0.10),
            max_consecutive_losses=_get_int("MAX_CONSECUTIVE_LOSSES", 3),
            min_confidence_score=_get_int("MIN_CONFIDENCE_SCORE", 75),
            min_trade_amount=_get_float("MIN_TRADE_AMOUNT", 1.0),
            max_trade_amount=_get_float("MAX_TRADE_AMOUNT", 25.0),
            expected_payout=_get_float("EXPECTED_PAYOUT", 0.82),
            kelly_fraction_cap=_get_float("KELLY_FRACTION_CAP", 0.25),
        ),
        webapp=WebAppSettings(
            public_url=_get_env("WEBAPP_URL"),
            host=_get_env("WEBAPP_HOST", "127.0.0.1"),
            port=_get_int("WEBAPP_PORT", 8000),
            title=_get_env("WEBAPP_TITLE", "Quotex AI Desk"),
        ),
    )

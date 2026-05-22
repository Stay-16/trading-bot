import asyncio
import logging
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

from tradingview_ta import TA_Handler, Interval

log = logging.getLogger("TVProvider")

TIMEFRAMES = {
    "1m":  {"tv": Interval.INTERVAL_1_MINUTE,  "quotex": 60},
    "5m":  {"tv": Interval.INTERVAL_5_MINUTES, "quotex": 300},
    "15m": {"tv": Interval.INTERVAL_15_MINUTES,"quotex": 900},
    "1h":  {"tv": Interval.INTERVAL_1_HOUR,    "quotex": 3600},
    "4h":  {"tv": Interval.INTERVAL_4_HOURS,   "quotex": 14400},
}


@dataclass
class MarketContext:
    volatility: float = 0.0
    trend_strength: float = 0.0
    market_condition: str = "normal"
    trend_condition: str = "moderate"

    @classmethod
    def from_indicators(cls, indicators: dict) -> "MarketContext":
        close = indicators.get("close", 0) or 0
        high = indicators.get("high", close) or close
        low = indicators.get("low", close) or close
        volatility = ((high - low) / close) if close else 0.0
        trend_strength = indicators.get("ADX", 0) or 0
        return cls(
            volatility=volatility,
            trend_strength=trend_strength,
            market_condition="high_vol" if volatility > 0.03 else "low_vol" if volatility < 0.01 else "normal",
            trend_condition="strong" if trend_strength > 25 else "weak" if trend_strength < 20 else "moderate",
        )


class TradingViewProvider:
    def __init__(self, cache_ttl: int = 60):
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = cache_ttl
        self._rate_limited_until: float = 0.0

    def _cache_key(self, symbol: str, screener: str, exchange: str, interval_key: str) -> str:
        return f"{symbol}|{screener}|{exchange}|{interval_key}"

    async def get_analysis(self, symbol: str, screener: str = "forex",
                           exchange: str = "FX_IDC",
                           interval_key: str = "1m") -> Optional[Any]:
        key = self._cache_key(symbol, screener, exchange, interval_key)
        now = time.time()

        cached = self._cache.get(key)
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1]

        if self._rate_limited_until and now < self._rate_limited_until:
            log.debug("TV cooldown %.0fs", self._rate_limited_until - now)
            return None

        exchange_candidates = [exchange]
        if screener == "forex":
            for fb in ("FX_IDC", "OANDA"):
                if fb not in exchange_candidates:
                    exchange_candidates.append(fb)

        interval = TIMEFRAMES.get(interval_key, {}).get("tv", Interval.INTERVAL_1_MINUTE)
        last_error = None

        for exch in exchange_candidates:
            try:
                handler = TA_Handler(symbol=symbol, exchange=exch, screener=screener, interval=interval)
                analysis = await asyncio.to_thread(handler.get_analysis)
                self._cache[key] = (now, analysis)
                return analysis
            except Exception as e:
                last_error = e
                if "429" in str(e):
                    raise

        if last_error:
            err = str(last_error)
            if "429" in err:
                self._rate_limited_until = now + 90
                log.warning("TradingView rate-limited. Cooldown 90s.")
            elif "not found" in err:
                log.info("TV mapping unavailable for %s", symbol)
            else:
                log.debug("TV fetch failed: %s", err)
        return None

    def get_summary(self, analysis) -> Dict[str, Any]:
        if not analysis:
            return {"recommendation": "NEUTRAL", "buy": 0, "sell": 0, "neutral": 0}
        s = analysis.summary
        return {
            "recommendation": s.get("RECOMMENDATION", "NEUTRAL"),
            "buy": s.get("BUY", 0),
            "sell": s.get("SELL", 0),
            "neutral": s.get("NEUTRAL", 0),
        }

    def get_indicators(self, analysis) -> dict:
        return getattr(analysis, "indicators", {}) if analysis else {}

    def build_market_context(self, analysis) -> MarketContext:
        return MarketContext.from_indicators(self.get_indicators(analysis))

    def get_tradingview_signal(self, analysis) -> dict:
        summary = self.get_summary(analysis)
        rec = summary.get("recommendation", "NEUTRAL")
        if rec in ("STRONG_BUY", "BUY"):
            return {"direction": "UP", "confidence": summary.get("buy", 0) * 10, "source": "tv"}
        if rec in ("STRONG_SELL", "SELL"):
            return {"direction": "DOWN", "confidence": summary.get("sell", 0) * 10, "source": "tv"}
        return {"direction": "WAIT", "confidence": 50, "source": "tv"}

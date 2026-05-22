import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Tuple


@dataclass(frozen=True)
class MarketContext:
    volatility: float
    trend_strength: float
    market_condition: str
    trend_condition: str


@dataclass(frozen=True)
class MarketSnapshot:
    pairdict: dict
    timeframe: str
    analysis: Any
    indicators: dict
    context: MarketContext


class MarketDataLayer:
    """Layer 1: market access, caching, and market context extraction."""

    def __init__(
        self,
        get_analysis_callable: Callable[[dict, str, Any], Any],
        timeframe_map: Dict[str, dict],
        cache_ttl_seconds: int = 60,
    ) -> None:
        self._get_analysis_callable = get_analysis_callable
        self._timeframe_map = timeframe_map
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def _cache_key(self, pairdict: dict, timeframe: str) -> str:
        return (
            f"{pairdict['symbol']}|{pairdict['exchange']}|"
            f"{pairdict['screener']}|{timeframe}"
        )

    async def fetch_snapshot(self, pairdict: dict, timeframe: str) -> MarketSnapshot:
        analysis = await self._get_or_fetch_analysis(pairdict, timeframe)
        indicators = getattr(analysis, "indicators", {}) if analysis else {}
        context = self._build_market_context(indicators)
        return MarketSnapshot(
            pairdict=pairdict,
            timeframe=timeframe,
            analysis=analysis,
            indicators=indicators,
            context=context,
        )

    async def _get_or_fetch_analysis(self, pairdict: dict, timeframe: str) -> Any:
        key = self._cache_key(pairdict, timeframe)
        cached = self._cache.get(key)
        if cached and (time.time() - cached[0] < self._cache_ttl_seconds):
            return cached[1]

        interval = self._timeframe_map[timeframe]["tv"]
        analysis = await self._get_analysis_callable(pairdict, timeframe, interval)
        self._cache[key] = (time.time(), analysis)
        return analysis

    def _build_market_context(self, indicators: dict) -> MarketContext:
        close = indicators.get("close", 0) or 0
        high = indicators.get("high", close)
        low = indicators.get("low", close)
        volatility = ((high - low) / close) if close else 0.0
        trend_strength = indicators.get("ADX", 0) or 0

        return MarketContext(
            volatility=volatility,
            trend_strength=trend_strength,
            market_condition=(
                "high_vol" if volatility > 0.03 else "low_vol" if volatility < 0.01 else "normal"
            ),
            trend_condition=(
                "strong" if trend_strength > 25 else "weak" if trend_strength < 20 else "moderate"
            ),
        )

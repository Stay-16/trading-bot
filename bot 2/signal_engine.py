from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import numpy as np

from data_layer import MarketSnapshot


@dataclass(frozen=True)
class SignalPackage:
    snapshot: MarketSnapshot
    traditional_signal: dict
    ai_prediction: dict
    lstm_signal: dict
    features: np.ndarray
    price_sequence: list
    candle_pattern: str


class SignalEngine:
    """Layer 2: traditional + AI signal generation."""

    def __init__(
        self,
        traditional_signal_fn: Callable[[Any], Awaitable[dict]],
        feature_extractor_fn: Callable[[dict, str, str], Awaitable[np.ndarray]],
        ai_prediction_fn: Callable[[np.ndarray, dict, dict, str, str, dict], Awaitable[dict]],
        lstm_signal_fn: Callable[[str, str, dict, dict], Awaitable[dict]],
        candle_pattern_fn: Callable[[dict], str],
    ) -> None:
        self._traditional_signal_fn = traditional_signal_fn
        self._feature_extractor_fn = feature_extractor_fn
        self._ai_prediction_fn = ai_prediction_fn
        self._lstm_signal_fn = lstm_signal_fn
        self._candle_pattern_fn = candle_pattern_fn

    async def analyze(self, snapshot: MarketSnapshot) -> SignalPackage:
        if snapshot.analysis is None:
            traditional_signal = {
                "direction": "neutral",
                "confidence": 50,
                "recommendation": "UNAVAILABLE",
            }
        else:
            traditional_signal = await self._traditional_signal_fn(snapshot.analysis)
        features = await self._feature_extractor_fn(
            snapshot.indicators,
            snapshot.pairdict["symbol"],
            snapshot.timeframe,
        )
        ai_prediction = await self._ai_prediction_fn(
            features,
            traditional_signal,
            {
                "volatility": snapshot.context.volatility,
                "trend_strength": snapshot.context.trend_strength,
                "market_condition": snapshot.context.market_condition,
                "trend_condition": snapshot.context.trend_condition,
            },
            snapshot.pairdict["symbol"],
            snapshot.timeframe,
            snapshot.indicators,
        )
        lstm_signal = await self._lstm_signal_fn(
            snapshot.pairdict["symbol"],
            snapshot.timeframe,
            snapshot.indicators,
            traditional_signal,
        )
        candle_pattern = self._candle_pattern_fn(snapshot.indicators)

        return SignalPackage(
            snapshot=snapshot,
            traditional_signal=traditional_signal,
            ai_prediction=ai_prediction,
            lstm_signal=lstm_signal,
            features=features,
            price_sequence=lstm_signal.get("price_sequence", []),
            candle_pattern=candle_pattern,
        )

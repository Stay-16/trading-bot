from dataclasses import dataclass
from typing import List

from decision_engine import DecisionResult, SignalVote, WeightedDecisionEngine
from signal_engine import SignalPackage


@dataclass(frozen=True)
class DecisionPayload:
    package: SignalPackage
    result: DecisionResult
    risk_level: str


class BinaryOptionsDecisionCore:
    """Layer 3: weighted voting, filtering, and confidence thresholding."""

    def __init__(self, engine: WeightedDecisionEngine) -> None:
        self._engine = engine

    def decide(self, package: SignalPackage) -> DecisionPayload:
        indicators = package.snapshot.indicators
        close = indicators.get("close", 0)
        ema20 = indicators.get("EMA20", close)
        ema50 = indicators.get("EMA50", close)

        trend_direction = "neutral"
        trend_confidence = 45
        trend_reason = "Trend is mixed"
        if close > ema20 > ema50:
            trend_direction = "call"
            trend_confidence = 72
            trend_reason = "Price is above EMA20 and EMA50"
        elif close < ema20 < ema50:
            trend_direction = "put"
            trend_confidence = 72
            trend_reason = "Price is below EMA20 and EMA50"

        volatility = package.snapshot.context.volatility
        volatility_direction = package.ai_prediction.get("direction", "neutral")
        volatility_confidence = 65
        volatility_reason = "Volatility is normal"
        if volatility > 0.03:
            volatility_direction = "neutral"
            volatility_confidence = 35
            volatility_reason = "High volatility reduces execution confidence"
        elif volatility < 0.01:
            volatility_reason = "Low volatility supports conservative entries"

        candle_direction = "neutral"
        candle_confidence = 45
        candle_reason = package.candle_pattern
        pattern_text = package.candle_pattern.lower()
        if "bullish" in pattern_text or "hammer" in pattern_text or "green" in pattern_text:
            candle_direction = "call"
            candle_confidence = 60
        elif "bearish" in pattern_text or "shooting star" in pattern_text or "red" in pattern_text:
            candle_direction = "put"
            candle_confidence = 60

        votes: List[SignalVote] = [
            SignalVote(
                name="traditional",
                direction=package.traditional_signal.get("direction", "neutral"),
                confidence=package.traditional_signal.get("confidence", 50),
                weight=0.22,
                reason=f"TradingView={package.traditional_signal.get('recommendation', 'N/A')}",
            ),
            SignalVote(
                name="ai_model",
                direction=package.ai_prediction.get("direction", "neutral"),
                confidence=package.ai_prediction.get(
                    "ai_confidence", package.ai_prediction.get("confidence", 50)
                ),
                weight=0.23,
                reason=f"Method={package.ai_prediction.get('method', 'unknown')}",
            ),
            SignalVote(
                name="lstm_base_model",
                direction=package.lstm_signal.get("direction", "neutral"),
                confidence=package.lstm_signal.get("confidence", 50),
                weight=0.20,
                reason=f"Method={package.lstm_signal.get('method', 'lstm_unavailable')}",
            ),
            SignalVote(
                name="trend_filter",
                direction=trend_direction,
                confidence=trend_confidence,
                weight=0.15,
                reason=trend_reason,
            ),
            SignalVote(
                name="volatility_filter",
                direction=volatility_direction,
                confidence=volatility_confidence,
                weight=0.10,
                reason=volatility_reason,
            ),
            SignalVote(
                name="candle_pattern",
                direction=candle_direction,
                confidence=candle_confidence,
                weight=0.10,
                reason=candle_reason,
            ),
        ]

        result = self._engine.decide(votes)
        if result.confidence >= 85:
            risk_level = "low"
        elif result.confidence >= 70:
            risk_level = "medium"
        else:
            risk_level = "high"

        return DecisionPayload(package=package, result=result, risk_level=risk_level)

from typing import Optional


def detect_candlestick_patterns(candles: list, direction_hint: str = "") -> dict:
    """
    Detect 8 candlestick patterns from a list of candles.
    Each candle must have .open, .close, .high, .low attributes.

    Returns dict with:
      - patterns: list of detected pattern names
      - bullish_count / bearish_count
      - dominant: "bullish" | "bearish" | "neutral"
    """
    if not candles or len(candles) < 3:
        return {"patterns": [], "bullish_count": 0, "bearish_count": 0, "dominant": "neutral"}

    patterns = []
    bullish = bearish = 0
    last = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else None
    prev2 = candles[-3] if len(candles) >= 3 else None

    body = abs(last.close - last.open)
    upper_wick = last.high - max(last.open, last.close)
    lower_wick = min(last.open, last.close) - last.low
    total_range = last.high - last.low
    avg_body = sum(abs(c.close - c.open) for c in candles[-5:]) / min(5, len(candles))
    avg_range = sum(c.high - c.low for c in candles[-5:]) / min(5, len(candles))

    # Doji: very small body relative to range
    if total_range > 0 and body / total_range < 0.1:
        patterns.append("doji")
        # Neutral — no direction
        return {"patterns": ["doji"], "bullish_count": 0, "bearish_count": 0, "dominant": "neutral"}

    # Hammer: small body at top, long lower wick (2x body), little/no upper wick
    if body > 0 and lower_wick >= 2 * body and upper_wick <= 0.3 * body:
        patterns.append("hammer")
        bullish += 1

    # Shooting Star: small body at bottom, long upper wick (2x body)
    if body > 0 and upper_wick >= 2 * body and lower_wick <= 0.3 * body:
        patterns.append("shooting_star")
        bearish += 1

    if prev and prev2:
        prev_body = abs(prev.close - prev.open)
        prev2_body = abs(prev2.close - prev2.open)

        # Bullish Engulfing: prev bearish candle, current fully engulfs it
        if prev.close < prev.open and last.close > last.open:
            if last.open < prev.close and last.close > prev.open:
                patterns.append("bullish_engulfing")
                bullish += 1

        # Bearish Engulfing: prev bullish candle, current fully engulfs it
        if prev.close > prev.open and last.close < last.open:
            if last.open > prev.close and last.close < prev.open:
                patterns.append("bearish_engulfing")
                bearish += 1

        # Morning Star: long bearish, small body (gap down), long bullish (gap up)
        if prev2.close < prev2.open and abs(prev2.close - prev2.open) > avg_body * 1.5:
            if body < avg_body * 0.6 and last.close > last.open and last.close > prev.high:
                patterns.append("morning_star_style")
                bullish += 2

        # Evening Star: long bullish, small body (gap up), long bearish (gap down)
        if prev2.close > prev2.open and abs(prev2.close - prev2.open) > avg_body * 1.5:
            if body < avg_body * 0.6 and last.close < last.open and last.close < prev.low:
                patterns.append("evening_star_style")
                bearish += 2

    # Momentum Expansion: current candle body > 1.5x average, in direction of hint
    if body > avg_body * 1.5 and avg_body > 0:
        if last.close > last.open:
            patterns.append("momentum_expansion")
            bullish += 1
        else:
            patterns.append("momentum_expansion")
            bearish += 1

    dominant = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    return {
        "patterns": patterns,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "dominant": dominant,
        "details": {
            "last_body": round(body, 6),
            "last_range": round(total_range, 6),
            "avg_body": round(avg_body, 6),
            "upper_wick": round(upper_wick, 6),
            "lower_wick": round(lower_wick, 6),
        },
    }

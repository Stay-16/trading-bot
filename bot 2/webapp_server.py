from __future__ import annotations

import logging
import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api_schemas import (
    AnalyzeResponse,
    ExecuteTradeResponse,
    HealthResponse,
    LiveSnapshotResponse,
    MarketsResponse,
    TopSetupsResponse,
)
import trading_bot as bot


BASE_DIR = Path(__file__).parent
WEBAPP_INDEX = BASE_DIR / "webapp_index.html"
WEBAPP_JS = BASE_DIR / "webapp_app.js"
WEBAPP_CSS = BASE_DIR / "webapp_styles.css"
connection_lock = asyncio.Lock()
entry_watchers: dict[str, dict[str, Any]] = {}
ENTRY_AUTO_PAIR_LOCK_SECONDS = 90
MIN_EXECUTION_PAYOUT = 76.0
response_cache: dict[str, tuple[float, Any]] = {}
ANALYSIS_CACHE_SECONDS = 4
MARKETS_CACHE_SECONDS = 8
HEALTH_CACHE_SECONDS = 12
TOP_SETUPS_CACHE_SECONDS = 10
JOURNAL_CACHE_SECONDS = 6
CURRENCY_STRENGTH_CACHE_SECONDS = 15
MTF_CACHE_SECONDS = 20
CONNECTION_CHECK_CACHE_SECONDS = 12
BROKER_PRESSURE_COOLDOWN_SECONDS = 18
WEBAPP_HIGHER_TF = {
    "1m": "5m",
    "5m": "15m",
    "15m": "1h",
    "1h": "4h",
    "4h": "4h",
}
MAJOR_FX_CURRENCIES = ("USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD")
connection_state_cache: dict[str, tuple[float, Any]] = {}
broker_pressure_until = 0.0
QUAD_ANALYSIS_WEIGHTS = {
    "trend": 30,
    "support_resistance": 25,
    "price_action": 25,
    "momentum_volatility": 20,
}


def mark_broker_pressure(seconds: int | float = BROKER_PRESSURE_COOLDOWN_SECONDS) -> None:
    global broker_pressure_until
    broker_pressure_until = max(broker_pressure_until, time.time() + float(seconds))


def broker_is_under_pressure() -> bool:
    return time.time() < broker_pressure_until


def get_cached_response(cache_key: str, max_age_seconds: int | float) -> Any | None:
    cached = response_cache.get(cache_key)
    if not cached:
        return None
    cached_at, payload = cached
    if time.time() - cached_at <= float(max_age_seconds):
        return payload
    return None


def get_stale_cached_response(cache_key: str) -> Any | None:
    cached = response_cache.get(cache_key)
    if not cached:
        return None
    return cached[1]


def store_cached_response(cache_key: str, payload: Any) -> Any:
    response_cache[cache_key] = (time.time(), payload)
    return payload


def invalidate_cached_responses(*prefixes: str) -> None:
    if not prefixes:
        return
    for cache_key in list(response_cache.keys()):
        if any(cache_key.startswith(prefix) for prefix in prefixes):
            response_cache.pop(cache_key, None)


def describe_exception(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def serialize_live_entry(entry: dict[str, Any]) -> dict[str, Any]:
    health = get_symbol_health(entry)
    return {
        "id": entry["callback_id"],
        "pair_key": entry["pair_key"],
        "display_name": entry["display_name"],
        "market_type": entry["market_type"],
        "payout": entry.get("payout"),
        "quotex_symbol": entry["quotex_symbol"],
        "symbol": entry["pairdict"]["symbol"],
        "health": health,
    }


class ExecuteTradeRequest(BaseModel):
    asset_id: str
    timeframe: str
    direction: str
    user_id: int = 0
    confidence: int | None = None


class EntryWatchRequest(BaseModel):
    asset_id: str
    timeframe: str
    direction: str | None = None
    user_id: int = 0
    mode: str = "alert"


def _extract_api_token(request: Request) -> str:
    bearer = request.headers.get("Authorization", "").strip()
    if bearer.lower().startswith("bearer "):
        return bearer[7:].strip()
    return request.headers.get("X-API-Key", "").strip()


def require_webapp_api_token(request: Request) -> None:
    return


def get_symbol_health(entry: dict[str, Any], timeframe: str = "1m") -> dict[str, Any]:
    timeframe_seconds = bot.TIMEFRAMES.get(timeframe, bot.TIMEFRAMES["1m"])["quotex"]
    cache_key = f"{entry['pairdict']['quotex_symbol']}|{timeframe_seconds}"
    cached_snapshot = bot.live_snapshot_cache.get(cache_key)
    snapshot = cached_snapshot[1] if cached_snapshot else {}

    price = snapshot.get("price")
    payout = snapshot.get("payout", entry.get("payout"))
    sentiment = snapshot.get("sentiment")
    candles = snapshot.get("candles", [])
    snapshot_ts = snapshot.get("timestamp") or (cached_snapshot[0] if cached_snapshot else None)

    if snapshot_ts:
        age = max(0.0, bot.now_ts() - float(snapshot_ts))
        speed_score = max(0, min(100, round(100 - age * 18)))
    else:
        speed_score = 22 if entry.get("market_type") == "otc" else 35

    completeness = sum(
        1 for value in (price, payout, sentiment) if value not in (None, {}, [])
    ) + (1 if candles else 0)
    stability_score = min(100, completeness * 25)
    if entry.get("market_type") == "otc":
        stability_score = min(100, stability_score + 10)

    score = round(speed_score * 0.45 + stability_score * 0.55)
    if score >= 75:
        grade = "strong"
    elif score >= 50:
        grade = "watch"
    else:
        grade = "weak"

    return {
        "score": score,
        "update_speed": speed_score,
        "data_stability": stability_score,
        "grade": grade,
    }


def build_entry_plan(
    entry: dict[str, Any],
    timeframe: str,
    direction: str,
    confidence: int,
    live_snapshot: dict[str, Any],
) -> dict[str, Any]:
    candles = live_snapshot.get("candles", []) or []
    live_price = live_snapshot.get("price")
    if live_price is None and candles:
        live_price = candles[-1].get("close")

    if live_price is None:
        return {
            "mode": "wait",
            "label": "No entry zone yet",
            "summary": "Waiting for enough live price data to build an entry zone.",
            "entry_min": None,
            "entry_max": None,
            "stop_chasing_above": None,
            "stop_chasing_below": None,
        }

    if candles:
        recent = candles[-5:]
        avg_range = sum(abs(c["high"] - c["low"]) for c in recent) / max(1, len(recent))
    else:
        avg_range = abs(live_price) * 0.0008

    avg_range = max(avg_range, abs(live_price) * 0.0002)
    pullback = avg_range * 0.45
    trigger = avg_range * 0.15
    direction = direction or "neutral"

    if direction == "call":
        entry_min = live_price - pullback
        entry_max = live_price - trigger
        summary = "Prefer buying a dip into the zone instead of chasing the candle top."
        label = "CALL pullback zone"
        stop_above = live_price + trigger
        stop_below = None
    elif direction == "put":
        entry_min = live_price + trigger
        entry_max = live_price + pullback
        summary = "Prefer selling a bounce into the zone instead of entering after a deep drop."
        label = "PUT rebound zone"
        stop_above = None
        stop_below = live_price - trigger
    else:
        return {
            "mode": "wait",
            "label": "Wait for direction",
            "summary": "The engine does not have a clear CALL or PUT edge yet.",
            "entry_min": None,
            "entry_max": None,
            "stop_chasing_above": None,
            "stop_chasing_below": None,
        }

    return {
        "mode": "zone",
        "label": label,
        "summary": summary,
        "entry_min": round(entry_min, 5),
        "entry_max": round(entry_max, 5),
        "stop_chasing_above": round(stop_above, 5) if stop_above is not None else None,
        "stop_chasing_below": round(stop_below, 5) if stop_below is not None else None,
        "confidence": confidence,
        "timeframe": timeframe,
    }


def serialize_journal_trade(trade: dict[str, Any]) -> dict[str, Any]:
    reasons = trade.get("market_context", {}).get("decision_reasons", [])
    return {
        "trade_id": trade.get("trade_id"),
        "pair": trade.get("pair_name") or trade.get("pair") or trade.get("asset"),
        "direction": trade.get("direction"),
        "amount": trade.get("amount"),
        "profit": trade.get("profit"),
        "result": trade.get("result"),
        "confidence": trade.get("confidence"),
        "timeframe": trade.get("analysis_timeframe") or trade.get("timeframe"),
        "status": trade.get("status"),
        "opened_at": trade.get("open_time"),
        "closed_at": trade.get("close_time"),
        "result_source": trade.get("result_source"),
        "reason": reasons[0] if reasons else "",
    }


def serialize_entry_watcher(watcher: dict[str, Any] | None) -> dict[str, Any] | None:
    if not watcher:
        return None
    payload = dict(watcher)
    payload.pop("task", None)
    return payload


def price_in_entry_zone(price: float | None, best_entry: dict[str, Any]) -> bool:
    if price is None:
        return False
    entry_min = best_entry.get("entry_min")
    entry_max = best_entry.get("entry_max")
    if entry_min is None or entry_max is None:
        return False
    low, high = sorted([float(entry_min), float(entry_max)])
    return low <= float(price) <= high


def build_entry_watch_message(watcher: dict[str, Any]) -> str:
    status = watcher.get("status", "idle").replace("_", " ")
    pair = watcher.get("pair", "Unknown pair")
    mode = watcher.get("mode", "alert").upper()
    direction = watcher.get("direction", "neutral").upper()
    best_entry = watcher.get("best_entry", {})
    zone = "WAIT"
    if best_entry.get("entry_min") is not None and best_entry.get("entry_max") is not None:
        zone = f"{best_entry['entry_min']:.5f} - {best_entry['entry_max']:.5f}"
    price = watcher.get("last_price")
    price_text = f"{price:.5f}" if isinstance(price, (int, float)) else "--"
    return f"{pair} | {mode} | {direction} | Zone {zone} | Last {price_text} | {status}"


def detect_market_regime(market_context: dict[str, Any], live_snapshot: dict[str, Any], direction: str) -> dict[str, Any]:
    volatility = float(market_context.get("volatility", 0) or 0)
    trend_condition = market_context.get("trend_condition", "unknown")
    sentiment = live_snapshot.get("sentiment")
    candles = live_snapshot.get("candles", []) or []

    efficiency = 0.0
    if len(candles) >= 5:
        closes = [float(c.get("close", 0) or 0) for c in candles[-6:]]
        total_path = sum(abs(closes[idx] - closes[idx - 1]) for idx in range(1, len(closes)))
        direct_path = abs(closes[-1] - closes[0])
        efficiency = bot.safe_div(direct_path, total_path)

    if market_context.get("market_condition") == "unavailable":
        regime = "unavailable"
        score = 25
        summary = "The market regime could not be classified from live data."
    elif volatility > 0.03 or efficiency < 0.25:
        regime = "noisy"
        score = 32
        summary = "Price is moving with unstable structure, so entries should stay defensive."
    elif trend_condition == "strong" or efficiency >= 0.62 or (sentiment is not None and (sentiment >= 64 or sentiment <= 36)):
        regime = "trending"
        score = 82
        summary = f"The market is showing directional structure that supports {direction.upper()} continuation trades."
    else:
        regime = "ranging"
        score = 58
        summary = "The market is rotating in a range, so only clean pullback entries should be considered."

    return {
        "regime": regime,
        "score": score,
        "efficiency": round(efficiency, 3),
        "volatility": round(volatility, 4),
        "summary": summary,
    }


def clamp_score(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, int(round(value))))


def manual_ema(values: list[float], length: int) -> float | None:
    if not values:
        return None
    sample = values[-max(2, length * 3):]
    alpha = 2 / (max(1, length) + 1)
    ema_value = float(sample[0])
    for value in sample[1:]:
        ema_value = alpha * float(value) + (1 - alpha) * ema_value
    return ema_value


def manual_rsi(values: list[float], length: int = 14) -> float | None:
    if len(values) <= length:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-(length + 1):-1], values[-length:]):
        delta = float(current) - float(previous)
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    average_gain = sum(gains) / max(1, len(gains))
    average_loss = sum(losses) / max(1, len(losses))
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return 100 - (100 / (1 + rs))


def manual_atr(highs: list[float], lows: list[float], closes: list[float], length: int = 14) -> float | None:
    if len(closes) < 2 or len(highs) != len(lows) or len(highs) != len(closes):
        return None
    true_ranges: list[float] = []
    for index in range(1, len(closes)):
        high = float(highs[index])
        low = float(lows[index])
        previous_close = float(closes[index - 1])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if not true_ranges:
        return None
    sample = true_ranges[-length:]
    return sum(sample) / max(1, len(sample))


def manual_stochastic(highs: list[float], lows: list[float], closes: list[float], length: int = 14) -> float | None:
    if len(closes) < length or len(highs) < length or len(lows) < length:
        return None
    period_high = max(float(value) for value in highs[-length:])
    period_low = min(float(value) for value in lows[-length:])
    if period_high == period_low:
        return 50.0
    return ((float(closes[-1]) - period_low) / (period_high - period_low)) * 100


def manual_stddev(values: list[float], length: int = 14) -> float | None:
    if len(values) < 2:
        return None
    sample = [float(value) for value in values[-length:]]
    mean = sum(sample) / len(sample)
    variance = sum((value - mean) ** 2 for value in sample) / len(sample)
    return variance ** 0.5


def build_indicator_snapshot(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [float(candle.get("close", 0) or 0) for candle in candles if candle.get("close") is not None]
    highs = [float(candle.get("high", 0) or 0) for candle in candles if candle.get("high") is not None]
    lows = [float(candle.get("low", 0) or 0) for candle in candles if candle.get("low") is not None]
    if not closes:
        return {
            "source": "unavailable",
            "ema_50": None,
            "ema_200": None,
            "rsi": None,
            "atr": None,
            "stochastic_k": None,
            "stddev": None,
        }

    indicator_payload = {
        "source": "manual",
        "ema_50": manual_ema(closes, 50),
        "ema_200": manual_ema(closes, 200),
        "rsi": manual_rsi(closes, 14),
        "atr": manual_atr(highs, lows, closes, 14),
        "stochastic_k": manual_stochastic(highs, lows, closes, 14),
        "stddev": manual_stddev(closes, 14),
    }

    pandas_ta = getattr(bot, "pandas_ta", None)
    pd = getattr(bot, "pd", None)
    if pandas_ta is None or pd is None or len(closes) < 5:
        return indicator_payload

    try:
        frame = pd.DataFrame({
            "high": highs,
            "low": lows,
            "close": closes,
        })
        ema_50 = pandas_ta.ema(frame["close"], length=min(50, len(frame))).iloc[-1]
        ema_200 = pandas_ta.ema(frame["close"], length=min(200, len(frame))).iloc[-1]
        rsi = pandas_ta.rsi(frame["close"], length=min(14, max(2, len(frame) - 1))).iloc[-1]
        atr = pandas_ta.atr(frame["high"], frame["low"], frame["close"], length=min(14, max(2, len(frame) - 1))).iloc[-1]
        stoch = pandas_ta.stoch(frame["high"], frame["low"], frame["close"], k=min(14, max(3, len(frame) - 1)))
        stdev = pandas_ta.stdev(frame["close"], length=min(14, max(2, len(frame) - 1))).iloc[-1]
        indicator_payload.update({
            "source": "pandas_ta",
            "ema_50": float(ema_50) if ema_50 == ema_50 else indicator_payload["ema_50"],
            "ema_200": float(ema_200) if ema_200 == ema_200 else indicator_payload["ema_200"],
            "rsi": float(rsi) if rsi == rsi else indicator_payload["rsi"],
            "atr": float(atr) if atr == atr else indicator_payload["atr"],
            "stochastic_k": (
                float(stoch.iloc[-1, 0])
                if getattr(stoch, "empty", True) is False and stoch.iloc[-1, 0] == stoch.iloc[-1, 0]
                else indicator_payload["stochastic_k"]
            ),
            "stddev": float(stdev) if stdev == stdev else indicator_payload["stddev"],
        })
    except Exception as exc:
        logging.debug("pandas_ta indicator snapshot failed: %s", exc)

    return indicator_payload


def build_scoring_label(total_score: int) -> dict[str, Any]:
    if total_score >= 75:
        return {
            "label": "Strong Execution",
            "grade": "gold",
            "trade_ready": True,
            "summary": "The quad-analysis engine sees a high-quality setup with strong agreement across the stack.",
        }
    if total_score >= 50:
        return {
            "label": "Watchlist",
            "grade": "watch",
            "trade_ready": False,
            "summary": "The setup has some structure, but it still needs cleaner alignment before execution.",
        }
    return {
        "label": "Wait",
        "grade": "wait",
        "trade_ready": False,
        "summary": "The engine sees too little agreement right now, so this pair should stay in waiting mode.",
    }


def derive_quad_confidence_adjustment(total_score: int) -> int:
    if total_score >= 85:
        return 8
    if total_score >= 75:
        return 6
    if total_score >= 65:
        return 3
    if total_score >= 50:
        return 0
    if total_score >= 40:
        return -4
    return -8


def build_quad_analysis(
    *,
    direction: str,
    timeframe: str,
    live_price: float | None,
    market_context: dict[str, Any],
    live_snapshot: dict[str, Any],
    support_resistance: dict[str, Any],
    candlestick_pattern: dict[str, Any],
    breakout_structure: dict[str, Any],
    market_regime: dict[str, Any],
    mtf_confirmation: dict[str, Any],
    payout_filter: dict[str, Any],
    symbol_health: dict[str, Any],
) -> dict[str, Any]:
    candles = live_snapshot.get("candles", []) or []
    indicators = build_indicator_snapshot(candles)
    atr = indicators.get("atr") or (abs(float(live_price or 0)) * 0.0008 if live_price else 0.0)

    trend_score = 0
    trend_reasons: list[str] = []
    ema_200 = indicators.get("ema_200")
    ema_50 = indicators.get("ema_50")
    trend_condition = str(market_context.get("trend_condition", "unknown"))
    if direction in {"call", "put"}:
        trend_score += 8
        trend_reasons.append(f"Directional bias is {direction.upper()}.")
    else:
        trend_reasons.append("No directional bias is available yet.")

    if live_price is not None and ema_200 is not None:
        aligned_with_ema200 = (direction == "call" and live_price >= ema_200) or (direction == "put" and live_price <= ema_200)
        if aligned_with_ema200:
            trend_score += 12
            trend_reasons.append("Price is aligned with EMA 200.")
        else:
            trend_reasons.append("Price is not aligned with EMA 200.")
    elif trend_condition in {"strong", "bullish", "bearish"}:
        trend_score += 8
        trend_reasons.append(f"Trend condition reports {trend_condition}.")
    else:
        trend_reasons.append("EMA 200 alignment is unavailable, so trend confirmation stays lighter.")

    if live_price is not None and ema_50 is not None and ema_200 is not None:
        structure_ok = (direction == "call" and ema_50 >= ema_200) or (direction == "put" and ema_50 <= ema_200)
        if structure_ok:
            trend_score += 4
            trend_reasons.append("EMA 50 supports the broader trend structure.")

    mtf_status = mtf_confirmation.get("status")
    if mtf_status == "aligned":
        trend_score += 6
        trend_reasons.append("Higher timeframe confirms the current direction.")
    elif mtf_status == "misaligned":
        trend_reasons.append("Higher timeframe conflicts with the current direction.")
    else:
        trend_score += 2
        trend_reasons.append("Higher timeframe confirmation is neutral or skipped.")

    if market_regime.get("regime") == "trending":
        trend_score += 4
        trend_reasons.append("Market regime is trending.")

    trend_score = clamp_score(trend_score, 0, QUAD_ANALYSIS_WEIGHTS["trend"])
    trend_status = "passed" if trend_score >= 22 else "warning" if trend_score >= 12 else "blocked"

    sr_score = 0
    sr_reasons: list[str] = []
    nearest_support = support_resistance.get("nearest_support")
    nearest_resistance = support_resistance.get("nearest_resistance")
    relevant_zone = nearest_support if direction == "call" else nearest_resistance if direction == "put" else None
    zone_name = "support" if direction == "call" else "resistance" if direction == "put" else "zone"
    if relevant_zone and live_price is not None:
        distance = abs(float(live_price) - float(relevant_zone.get("level", live_price)))
        touches = int(relevant_zone.get("touches", 0) or 0)
        if distance <= atr * 1.2:
            sr_score += 14
            sr_reasons.append(f"Price is trading near the nearest {zone_name} zone.")
        elif distance <= atr * 2.5:
            sr_score += 8
            sr_reasons.append(f"Price is reasonably close to the nearest {zone_name} zone.")
        else:
            sr_reasons.append(f"Price is far from the nearest {zone_name} zone.")
        if touches >= 3:
            sr_score += 11
            sr_reasons.append(f"The nearest {zone_name} has {touches} historical touches.")
        elif touches >= 2:
            sr_score += 6
            sr_reasons.append(f"The nearest {zone_name} has repeated interaction history.")
    else:
        sr_reasons.append("No relevant support/resistance zone was available for this direction.")
    sr_score = clamp_score(sr_score, 0, QUAD_ANALYSIS_WEIGHTS["support_resistance"])
    sr_status = "passed" if sr_score >= 18 else "warning" if sr_score >= 10 else "blocked"

    price_action_score = 0
    pa_reasons: list[str] = []
    pattern_bias = candlestick_pattern.get("bias", "neutral")
    pattern_strength = int(candlestick_pattern.get("strength", 0) or 0)
    if candlestick_pattern.get("name") and candlestick_pattern.get("name") not in {"none", "unavailable"}:
        if pattern_bias == direction:
            price_action_score += 15
            pa_reasons.append(f"{candlestick_pattern.get('name')} supports the current direction.")
        elif pattern_bias == "neutral":
            price_action_score += 5
            pa_reasons.append("Candle pattern is neutral and needs more context.")
        else:
            pa_reasons.append(f"{candlestick_pattern.get('name')} conflicts with the current direction.")
        if pattern_strength >= 75:
            price_action_score += 5
            pa_reasons.append("The candle pattern is strong.")
    else:
        pa_reasons.append("No strong candle pattern confirmation is active.")

    breakout_state = str(breakout_structure.get("state", "none"))
    if direction == "call" and breakout_state in {"confirmed_breakout", "retest"}:
        price_action_score += 5
        pa_reasons.append(f"Breakout structure is supportive: {breakout_state}.")
    elif direction == "put" and breakout_state in {"confirmed_breakdown", "retest"}:
        price_action_score += 5
        pa_reasons.append(f"Breakdown structure is supportive: {breakout_state}.")
    elif breakout_state in {"false_breakout", "false_breakdown"}:
        pa_reasons.append(f"Breakout structure is risky: {breakout_state}.")

    raw_pa_score = int(market_context.get("price_action_score", 0) or 0)
    if raw_pa_score > 0:
        price_action_score += min(5, raw_pa_score)
        pa_reasons.append(f"Internal price-action engine added {min(5, raw_pa_score)} points.")

    price_action_score = clamp_score(price_action_score, 0, QUAD_ANALYSIS_WEIGHTS["price_action"])
    pa_status = "passed" if price_action_score >= 18 else "warning" if price_action_score >= 10 else "blocked"

    momentum_score = 0
    momentum_reasons: list[str] = []
    rsi = indicators.get("rsi")
    stochastic_k = indicators.get("stochastic_k")
    stddev = indicators.get("stddev")
    regime_name = market_regime.get("regime", "unknown")
    if rsi is not None:
        if direction == "call" and 40 <= rsi <= 68:
            momentum_score += 7
            momentum_reasons.append(f"RSI {rsi:.1f} leaves room for bullish continuation.")
        elif direction == "put" and 32 <= rsi <= 60:
            momentum_score += 7
            momentum_reasons.append(f"RSI {rsi:.1f} leaves room for bearish continuation.")
        elif 45 <= rsi <= 55:
            momentum_score += 4
            momentum_reasons.append(f"RSI {rsi:.1f} is neutral and not stretched.")
        else:
            momentum_reasons.append(f"RSI {rsi:.1f} is stretched for this direction.")
    else:
        momentum_reasons.append("RSI is unavailable.")

    if stochastic_k is not None:
        if direction == "call" and stochastic_k <= 78:
            momentum_score += 5
            momentum_reasons.append(f"Stochastic {stochastic_k:.1f} is not overbought.")
        elif direction == "put" and stochastic_k >= 22:
            momentum_score += 5
            momentum_reasons.append(f"Stochastic {stochastic_k:.1f} still allows downside rotation.")
        else:
            momentum_reasons.append(f"Stochastic {stochastic_k:.1f} is stretched.")

    if regime_name == "trending":
        momentum_score += 4
        momentum_reasons.append("Trending regime supports continuation momentum.")
    elif regime_name == "noisy":
        momentum_reasons.append("Noisy regime weakens momentum quality.")
    else:
        momentum_score += 2
        momentum_reasons.append("Range regime keeps momentum expectations moderate.")

    if stddev is not None and live_price:
        normalized_stddev = bot.safe_div(stddev, abs(float(live_price)))
        if 0.0004 <= normalized_stddev <= 0.006:
            momentum_score += 4
            momentum_reasons.append("Volatility is active without being overly chaotic.")
        else:
            momentum_reasons.append("Volatility is either too compressed or too unstable.")
    else:
        momentum_reasons.append("Volatility normalization is unavailable.")

    momentum_score = clamp_score(momentum_score, 0, QUAD_ANALYSIS_WEIGHTS["momentum_volatility"])
    momentum_status = "passed" if momentum_score >= 14 else "warning" if momentum_score >= 8 else "blocked"

    total_score = clamp_score(
        trend_score + sr_score + price_action_score + momentum_score,
        0,
        sum(QUAD_ANALYSIS_WEIGHTS.values()),
    )
    scoring_state = build_scoring_label(total_score)

    summary_bits = []
    if trend_status == "passed":
        summary_bits.append("Trend aligned")
    elif trend_status == "warning":
        summary_bits.append("Trend mixed")
    else:
        summary_bits.append("Trend weak")

    if sr_status == "passed":
        summary_bits.append("S/R supportive")
    elif sr_status == "warning":
        summary_bits.append("S/R moderate")
    else:
        summary_bits.append("S/R weak")

    if pa_status == "passed":
        summary_bits.append("Price action confirmed")
    elif pa_status == "warning":
        summary_bits.append("Price action partial")
    else:
        summary_bits.append("Price action weak")

    if momentum_status == "passed":
        summary_bits.append("Momentum supportive")
    elif momentum_status == "warning":
        summary_bits.append("Momentum mixed")
    else:
        summary_bits.append("Momentum weak")
    if payout_filter.get("passed"):
        summary_bits.append("Payout passed")
    else:
        summary_bits.append("Payout below filter")
    if (symbol_health.get("score") or 0) < 45:
        summary_bits.append("Health weak")

    return {
        "weights": dict(QUAD_ANALYSIS_WEIGHTS),
        "indicator_snapshot": indicators,
        "sections": {
            "trend": {
                "score": trend_score,
                "weight": QUAD_ANALYSIS_WEIGHTS["trend"],
                "status": trend_status,
                "summary": " | ".join(trend_reasons),
            },
            "support_resistance": {
                "score": sr_score,
                "weight": QUAD_ANALYSIS_WEIGHTS["support_resistance"],
                "status": sr_status,
                "summary": " | ".join(sr_reasons),
            },
            "price_action": {
                "score": price_action_score,
                "weight": QUAD_ANALYSIS_WEIGHTS["price_action"],
                "status": pa_status,
                "summary": " | ".join(pa_reasons),
            },
            "momentum_volatility": {
                "score": momentum_score,
                "weight": QUAD_ANALYSIS_WEIGHTS["momentum_volatility"],
                "status": momentum_status,
                "summary": " | ".join(momentum_reasons),
            },
        },
        "total_score": total_score,
        "label": scoring_state["label"],
        "grade": scoring_state["grade"],
        "trade_ready": scoring_state["trade_ready"] and payout_filter.get("passed", False) and direction in {"call", "put"},
        "summary": f"{scoring_state['summary']} {' | '.join(summary_bits)}.",
    }


def build_live_analysis_steps(
    asset_name: str,
    direction: str,
    quad_analysis: dict[str, Any],
    support_resistance: dict[str, Any],
    candlestick_pattern: dict[str, Any],
    payout_filter: dict[str, Any],
    market_regime: dict[str, Any],
    live_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    nearest_support = support_resistance.get("nearest_support")
    nearest_resistance = support_resistance.get("nearest_resistance")
    sections = quad_analysis.get("sections", {})
    live_sentiment = live_snapshot.get("sentiment")
    if isinstance(live_sentiment, (int, float)):
        if live_sentiment >= 60:
            sentiment_headline = f"Sentiment is bullish at {round(live_sentiment)}%"
            sentiment_status = "passed" if direction == "call" else "warning"
            sentiment_detail = "Live market sentiment is supporting upside pressure right now."
        elif live_sentiment <= 40:
            sentiment_headline = f"Sentiment is bearish at {round(live_sentiment)}%"
            sentiment_status = "passed" if direction == "put" else "warning"
            sentiment_detail = "Live market sentiment is supporting downside pressure right now."
        else:
            sentiment_headline = f"Sentiment is mixed at {round(live_sentiment)}%"
            sentiment_status = "warning"
            sentiment_detail = "Live market sentiment is balanced, so the setup needs stronger confirmation from the rest of the stack."
    else:
        sentiment_headline = "Live sentiment is unavailable"
        sentiment_status = "blocked"
        sentiment_detail = "The live sentiment feed did not return a usable value for this pair yet."
    if direction == "call" and nearest_support and nearest_support.get("level") is not None:
        sr_headline = f"Nearest support {nearest_support['level']:.5f}"
    elif direction == "put" and nearest_resistance and nearest_resistance.get("level") is not None:
        sr_headline = f"Nearest resistance {nearest_resistance['level']:.5f}"
    else:
        sr_headline = "No strong S/R zone nearby"
    steps = [
        {
            "id": "trend",
            "label": "Checking Market Trend",
            "status": sections.get("trend", {}).get("status", "blocked"),
            "headline": (
                f"Trend is {direction.upper()}"
                if direction in {"call", "put"}
                else "Trend is neutral"
            ),
            "detail": sections.get("trend", {}).get("summary", "Trend confirmation is unavailable."),
        },
        {
            "id": "sentiment",
            "label": "Reading Live Market Sentiment",
            "status": sentiment_status,
            "headline": sentiment_headline,
            "detail": sentiment_detail,
        },
        {
            "id": "support_resistance",
            "label": "Scanning Support Levels",
            "status": sections.get("support_resistance", {}).get("status", "blocked"),
            "headline": sr_headline,
            "detail": sections.get("support_resistance", {}).get("summary", "Support/resistance scan is unavailable."),
        },
        {
            "id": "momentum",
            "label": "Analyzing Momentum",
            "status": sections.get("momentum_volatility", {}).get("status", "blocked"),
            "headline": f"Regime: {market_regime.get('regime', 'unknown')}",
            "detail": sections.get("momentum_volatility", {}).get("summary", "Momentum analysis is unavailable."),
        },
        {
            "id": "price_action",
            "label": "Confirming Candle Pattern",
            "status": sections.get("price_action", {}).get("status", "blocked"),
            "headline": f"Pattern: {candlestick_pattern.get('name', 'none')}",
            "detail": sections.get("price_action", {}).get("summary", "Candle confirmation is unavailable."),
        },
        {
            "id": "result",
            "label": "AI Voting Result",
            "status": "passed" if quad_analysis.get("trade_ready") else "warning" if quad_analysis.get("total_score", 0) >= 50 else "blocked",
            "headline": f"{asset_name}: {quad_analysis.get('label', 'Wait')}",
            "detail": f"{quad_analysis.get('summary', 'No voting summary available.')} {payout_filter.get('summary', '')}".strip(),
        },
    ]
    return steps


def analyze_candlestick_patterns(candles: list[dict[str, Any]], direction: str) -> dict[str, Any]:
    if len(candles) < 3:
        return {
            "name": "unavailable",
            "bias": "neutral",
            "strength": 0,
            "summary": "Not enough candle history to detect price action patterns.",
            "confidence_adjustment": 0,
        }

    latest = candles[-1]
    previous = candles[-2]
    third = candles[-3]

    def body(candle):
        return abs(float(candle["close"]) - float(candle["open"]))

    def candle_range(candle):
        return max(1e-9, float(candle["high"]) - float(candle["low"]))

    def upper_wick(candle):
        return float(candle["high"]) - max(float(candle["open"]), float(candle["close"]))

    def lower_wick(candle):
        return min(float(candle["open"]), float(candle["close"])) - float(candle["low"])

    latest_body = body(latest)
    latest_range = candle_range(latest)
    previous_body = body(previous)
    bullish_latest = float(latest["close"]) > float(latest["open"])
    bearish_latest = float(latest["close"]) < float(latest["open"])
    bullish_previous = float(previous["close"]) > float(previous["open"])
    bearish_previous = float(previous["close"]) < float(previous["open"])

    pattern = {
        "name": "none",
        "bias": "neutral",
        "strength": 0,
        "summary": "No strong candlestick confirmation was detected.",
        "confidence_adjustment": 0,
    }

    if bullish_latest and bearish_previous and float(latest["open"]) <= float(previous["close"]) and float(latest["close"]) >= float(previous["open"]):
        pattern = {
            "name": "bullish_engulfing",
            "bias": "call",
            "strength": 82,
            "summary": "Bullish engulfing detected. Buyers absorbed the prior bearish candle.",
            "confidence_adjustment": 8 if direction == "call" else -8,
        }
    elif bearish_latest and bullish_previous and float(latest["open"]) >= float(previous["close"]) and float(latest["close"]) <= float(previous["open"]):
        pattern = {
            "name": "bearish_engulfing",
            "bias": "put",
            "strength": 82,
            "summary": "Bearish engulfing detected. Sellers absorbed the prior bullish candle.",
            "confidence_adjustment": 8 if direction == "put" else -8,
        }
    elif lower_wick(latest) > latest_body * 2.2 and upper_wick(latest) < latest_body * 0.8 and latest_body / latest_range < 0.42:
        pattern = {
            "name": "hammer",
            "bias": "call",
            "strength": 72,
            "summary": "Hammer-style rejection detected, often supporting bullish reversal entries.",
            "confidence_adjustment": 6 if direction == "call" else -6,
        }
    elif upper_wick(latest) > latest_body * 2.2 and lower_wick(latest) < latest_body * 0.8 and latest_body / latest_range < 0.42:
        pattern = {
            "name": "shooting_star",
            "bias": "put",
            "strength": 72,
            "summary": "Shooting star rejection detected, often supporting bearish reversal entries.",
            "confidence_adjustment": 6 if direction == "put" else -6,
        }
    elif latest_body / latest_range < 0.12:
        pattern = {
            "name": "doji",
            "bias": "neutral",
            "strength": 38,
            "summary": "Doji-style indecision detected. The market may need more confirmation before entry.",
            "confidence_adjustment": -6,
        }
    elif bullish_latest and float(third["close"]) < float(third["open"]) and float(previous["close"]) < float(previous["open"]) and float(latest["close"]) > float(previous["high"]):
        pattern = {
            "name": "morning_star_style",
            "bias": "call",
            "strength": 76,
            "summary": "A three-candle bullish reversal structure appeared, similar to a morning-star continuation.",
            "confidence_adjustment": 7 if direction == "call" else -7,
        }
    elif bearish_latest and float(third["close"]) > float(third["open"]) and float(previous["close"]) > float(previous["open"]) and float(latest["close"]) < float(previous["low"]):
        pattern = {
            "name": "evening_star_style",
            "bias": "put",
            "strength": 76,
            "summary": "A three-candle bearish reversal structure appeared, similar to an evening-star continuation.",
            "confidence_adjustment": 7 if direction == "put" else -7,
        }

    if pattern["name"] == "none" and latest_body > previous_body * 1.4:
        directional_bias = "call" if bullish_latest else "put" if bearish_latest else "neutral"
        pattern = {
            "name": "momentum_expansion",
            "bias": directional_bias,
            "strength": 58,
            "summary": "Momentum expansion candle detected, suggesting aggressive short-term participation.",
            "confidence_adjustment": 4 if directional_bias == direction else -4 if directional_bias != "neutral" else 0,
        }

    return pattern


def extract_symbol_currencies(pair_symbol: str) -> tuple[str | None, str | None]:
    token = str(pair_symbol or "").replace("/", "").replace("-", "").replace("_OTC", "").replace("OTC", "")
    if len(token) < 6:
        return None, None
    base = token[:3].upper()
    quote = token[3:6].upper()
    if base in MAJOR_FX_CURRENCIES and quote in MAJOR_FX_CURRENCIES:
        return base, quote
    return None, None


def check_payout_filter(payout: float | None, minimum: float = MIN_EXECUTION_PAYOUT) -> dict[str, Any]:
    if payout is None:
        return {
            "enabled": True,
            "minimum": minimum,
            "current": None,
            "passed": False,
            "summary": "Live payout is unavailable, so execution remains blocked by the payout filter.",
        }

    passed = float(payout) >= float(minimum)
    return {
        "enabled": True,
        "minimum": minimum,
        "current": round(float(payout), 2),
        "passed": passed,
        "summary": (
            f"Payout {float(payout):.0f}% passed the minimum payout filter."
            if passed
            else f"Payout {float(payout):.0f}% is below the minimum {float(minimum):.0f}% filter."
        ),
    }


def serialize_support_resistance(market_context: dict[str, Any]) -> dict[str, Any]:
    sr_info = dict(market_context.get("support_resistance", {}) or {})
    sr_info.setdefault("supports", [])
    sr_info.setdefault("resistances", [])
    return sr_info


def is_pair_locked_for_auto_entry(entry: dict[str, Any], user_id: int, cooldown_seconds: int = ENTRY_AUTO_PAIR_LOCK_SECONDS) -> tuple[bool, str]:
    pair_name = entry.get("display_name")
    api_symbol = entry.get("quotex_api_symbol") or bot.quotex_symbol_to_api_symbol(entry["pairdict"]["quotex_symbol"])
    now = bot.now_ts()

    for trade in bot.active_trades.values():
        if trade.get("status") != "pending":
            continue
        if user_id and trade.get("user_id") not in {0, user_id}:
            continue
        same_pair = trade.get("pair_name") == pair_name or trade.get("asset") == api_symbol
        if same_pair:
            return True, "Auto entry is locked because this pair already has an open trade."

    for trade in reversed(bot.trade_history):
        if user_id and trade.get("user_id") not in {0, user_id}:
            continue
        same_pair = trade.get("pair_name") == pair_name or trade.get("asset") == api_symbol
        if not same_pair:
            continue
        closed_at = trade.get("close_time") or trade.get("open_time") or 0
        if now - float(closed_at) <= cooldown_seconds:
            remaining = max(1, int(cooldown_seconds - (now - float(closed_at))))
            return True, f"Auto entry is locked for this pair for {remaining}s to avoid duplicate rapid entries."
        break

    return False, ""


def compute_journal_analytics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("status") == "closed"]
    if not closed:
        return {
            "summary": {
                "total_trades": 0,
                "win_rate": 0,
                "net_profit": 0,
                "expectancy": 0,
                "avg_confidence": 0,
            },
            "best_pair": None,
            "worst_pair": None,
            "best_timeframe": None,
            "market_split": [],
            "recent_streak": {"type": "flat", "count": 0},
        }

    total = len(closed)
    wins = [trade for trade in closed if trade.get("result") == "win"]
    net_profit = round(sum(float(trade.get("profit", 0) or 0) for trade in closed), 2)
    avg_confidence = round(sum(float(trade.get("confidence", 0) or 0) for trade in closed) / total, 2)
    expectancy = round(net_profit / total, 2)

    def aggregate_by(key_fn):
        stats = {}
        for trade in closed:
            key = key_fn(trade)
            if not key:
                continue
            bucket = stats.setdefault(key, {"trades": 0, "wins": 0, "profit": 0.0})
            bucket["trades"] += 1
            if trade.get("result") == "win":
                bucket["wins"] += 1
            bucket["profit"] += float(trade.get("profit", 0) or 0)
        rows = []
        for key, bucket in stats.items():
            trades_count = bucket["trades"]
            rows.append({
                "key": key,
                "trades": trades_count,
                "win_rate": round(bot.safe_div(bucket["wins"] * 100, trades_count), 2),
                "profit": round(bucket["profit"], 2),
            })
        rows.sort(key=lambda item: (item["profit"], item["win_rate"], item["trades"]), reverse=True)
        return rows

    pair_rows = aggregate_by(lambda trade: trade.get("pair_name") or trade.get("pair"))
    timeframe_rows = aggregate_by(lambda trade: trade.get("analysis_timeframe") or trade.get("timeframe"))
    market_rows = aggregate_by(
        lambda trade: "otc" if "otc" in str((trade.get("pair_name") or trade.get("pair") or "")).lower() else "regular"
    )

    streak_type = "flat"
    streak_count = 0
    for trade in reversed(closed):
        result = trade.get("result")
        if result not in {"win", "loss"}:
            break
        if streak_type == "flat":
            streak_type = result
            streak_count = 1
            continue
        if result == streak_type:
            streak_count += 1
        else:
            break

    return {
        "summary": {
            "total_trades": total,
            "win_rate": round(bot.safe_div(len(wins) * 100, total), 2),
            "net_profit": net_profit,
            "expectancy": expectancy,
            "avg_confidence": avg_confidence,
        },
        "best_pair": pair_rows[0] if pair_rows else None,
        "worst_pair": pair_rows[-1] if pair_rows else None,
        "best_timeframe": timeframe_rows[0] if timeframe_rows else None,
        "market_split": market_rows,
        "recent_streak": {"type": streak_type, "count": streak_count},
    }


async def get_multi_timeframe_confirmation(
    entry: dict[str, Any],
    timeframe: str,
    base_direction: str,
    base_confidence: int,
) -> dict[str, Any]:
    if (
        entry.get("market_type") == "otc"
        or entry["pairdict"].get("tv_supported") is False
        or bot.should_prefer_live_quotex_analysis(entry["pairdict"])
    ):
        return {
            "enabled": False,
            "current_timeframe": timeframe,
            "higher_timeframe": WEBAPP_HIGHER_TF.get(timeframe, timeframe),
            "status": "skipped_live_only",
            "direction": base_direction,
            "confidence": int(base_confidence or 0),
            "adjustment": 0,
            "label": "Skipped in live-only mode",
            "summary": "Higher timeframe confirmation is skipped for OTC/live-only assets to keep analysis fast and stable.",
        }

    cache_key = (
        f"mtf:{entry.get('callback_id') or entry['pairdict'].get('quotex_symbol')}:{timeframe}:"
        f"{base_direction}:{int(base_confidence or 0)}"
    )
    cached_payload = get_cached_response(cache_key, MTF_CACHE_SECONDS)
    if cached_payload is not None:
        return cached_payload

    higher_tf = WEBAPP_HIGHER_TF.get(timeframe, timeframe)
    if higher_tf == timeframe:
        return store_cached_response(cache_key, {
            "enabled": False,
            "current_timeframe": timeframe,
            "higher_timeframe": higher_tf,
            "status": "same_timeframe",
            "direction": base_direction,
            "confidence": base_confidence,
            "adjustment": 0,
            "label": "No higher timeframe available",
            "summary": "This timeframe already sits at the highest supported confirmation level.",
        })

    try:
        _, higher_direction, higher_confidence, _, higher_context = await asyncio.wait_for(
            bot.advanced_ai_analysis_layered(entry["pairdict"], higher_tf),
            timeout=8,
        )
        if higher_direction not in {"call", "put"} or base_direction not in {"call", "put"}:
            return store_cached_response(cache_key, {
                "enabled": True,
                "current_timeframe": timeframe,
                "higher_timeframe": higher_tf,
                "status": "neutral",
                "direction": higher_direction,
                "confidence": int(higher_confidence or 0),
                "adjustment": 0,
                "label": "Higher timeframe is neutral",
                "summary": "The higher timeframe did not produce a clear CALL or PUT bias.",
                "reasons": higher_context.get("decision_reasons", []),
            })

        aligned = higher_direction == base_direction
        adjustment = 8 if aligned else -12
        status = "aligned" if aligned else "misaligned"
        label = "Trend confirmed" if aligned else "Trend conflict"
        summary = (
            f"The {higher_tf} timeframe confirms the {base_direction.upper()} bias."
            if aligned
            else f"The {higher_tf} timeframe is pointing {higher_direction.upper()}, which conflicts with the current setup."
        )
        return store_cached_response(cache_key, {
            "enabled": True,
            "current_timeframe": timeframe,
            "higher_timeframe": higher_tf,
            "status": status,
            "direction": higher_direction,
            "confidence": int(higher_confidence or 0),
            "adjustment": adjustment,
            "label": label,
            "summary": summary,
            "reasons": higher_context.get("decision_reasons", []),
        })
    except Exception as exc:
        return store_cached_response(cache_key, {
            "enabled": True,
            "current_timeframe": timeframe,
            "higher_timeframe": higher_tf,
            "status": "unavailable",
            "direction": "neutral",
            "confidence": 0,
            "adjustment": 0,
            "label": "Confirmation unavailable",
            "summary": f"Higher timeframe confirmation could not be loaded: {exc}",
        })


async def ensure_quotex_connection() -> None:
    async with connection_lock:
        if broker_is_under_pressure() and bot.quotex_client:
            return
        cached_state = connection_state_cache.get("quotex")
        if cached_state and time.time() - cached_state[0] < CONNECTION_CHECK_CACHE_SECONDS:
            return

        client = bot.quotex_client
        if client:
            try:
                await client.get_balance()
                connection_state_cache["quotex"] = (time.time(), True)
                return
            except Exception as exc:
                logging.warning("Detected stale Quotex session. Reconnecting: %s", exc)
                bot.quotex_client = None

        try:
            await bot.connect_to_quotex_with_retry(max_retries=5)
            connection_state_cache["quotex"] = (time.time(), bool(bot.quotex_client))
        except Exception as exc:
            logging.warning("WebApp could not initialize Quotex connection: %s", exc)


async def resolve_entry(asset_id: str | None = None, symbol: str | None = None) -> dict[str, Any]:
    if asset_id:
        entry = bot.live_pair_registry.get(asset_id)
        if entry:
            return entry

    entries = await bot.get_live_quotex_assets("all")
    if asset_id:
        entry = bot.live_pair_registry.get(asset_id)
        if entry:
            return entry

    if symbol:
        normalized = bot.normalize_quotex_symbol(symbol)
        for entry in entries:
            if bot.normalize_quotex_symbol(entry["quotex_symbol"]) == normalized:
                return entry

    raise HTTPException(status_code=404, detail="Asset not found in live registry.")


async def build_analysis_payload(entry: dict[str, Any], timeframe: str) -> dict[str, Any]:
    if timeframe not in bot.TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Unsupported timeframe.")

    analysis_cache_key = f"analysis:{entry.get('callback_id') or entry['pairdict'].get('quotex_symbol')}:{timeframe}"
    cached_payload = get_cached_response(analysis_cache_key, ANALYSIS_CACHE_SECONDS)
    if cached_payload is not None:
        return cached_payload

    enriched_entry = await bot.enrich_live_entry_with_payout(dict(entry))
    cached_result = bot.get_cached_analysis_result(entry["pairdict"], timeframe)
    use_live_only = (
        bot.should_prefer_live_quotex_analysis(entry["pairdict"])
        or entry.get("market_type") == "otc"
        or (bot.tradingview_rate_limited_until and bot.now_ts() < bot.tradingview_rate_limited_until)
    )

    if use_live_only:
        try:
            _, direction, confidence, _, market_context = await asyncio.wait_for(
                bot.live_stream_analysis(entry["pairdict"], timeframe),
                timeout=6,
            )
            analysis = None
            traditional = {
                "direction": direction,
                "confidence": confidence,
                "recommendation": direction.upper() if direction in {"call", "put"} else "WAIT",
            }
            ai_prediction = {
                "direction": direction,
                "confidence": confidence,
                "method": "live_stream_fallback",
                "risk_level": "medium",
                "decision_score": confidence,
                "models_used": ["live_stream"],
            }
            market_context = dict(market_context or {})
            if isinstance(market_context.get("decision_reasons"), list):
                market_context["decision_reasons"] = list(market_context["decision_reasons"])
            market_context.setdefault("lstm_signal", {"direction": direction, "confidence": confidence, "method": "live_stream"})
            degraded = True
            degraded_reason = "Using live stream fallback because OTC/rate-limited assets cannot rely on TradingView."
        except Exception as exc:
            logging.warning("WebApp live-stream fallback failed for %s: %s", entry["display_name"], describe_exception(exc))
            traditional = {"direction": "neutral", "confidence": 0, "recommendation": "UNAVAILABLE"}
            ai_prediction = {"direction": "neutral", "confidence": 0, "method": "live_unavailable", "risk_level": "high", "decision_score": 0}
            market_context = {
                "degraded": True,
                "degraded_reason": f"Live stream analysis is currently unavailable: {describe_exception(exc)}",
                "trend_condition": "unknown",
                "market_condition": "unavailable",
                "decision_reasons": ["The live market feed could not be analyzed right now."],
                "candle_pattern": "N/A",
                "lstm_signal": {"direction": "neutral", "confidence": 0, "method": "unavailable"},
            }
            analysis = None
            degraded = True
            degraded_reason = market_context["degraded_reason"]
    else:
        try:
            orchestrator = bot.get_trading_orchestrator()
            outcome = await asyncio.wait_for(
                orchestrator.analyze_market(entry["pairdict"], timeframe),
                timeout=12,
            )
            snapshot = outcome.decision.package.snapshot
            analysis = snapshot.analysis
            traditional = outcome.decision.package.traditional_signal
            ai_prediction = outcome.decision.package.ai_prediction
            market_context = dict(outcome.market_context or {})
            if isinstance(market_context.get("decision_reasons"), list):
                market_context["decision_reasons"] = list(market_context["decision_reasons"])
            degraded = False
            degraded_reason = ""
        except Exception as exc:
            logging.warning("WebApp analysis fell back for %s: %s", entry["display_name"], exc)
            if cached_result:
                traditional = cached_result.get("traditional_signal", {"direction": "neutral", "confidence": 50, "recommendation": "NEUTRAL"})
                ai_prediction = cached_result.get("ai_prediction", {"direction": cached_result.get("direction", "neutral"), "confidence": cached_result.get("confidence", 50), "method": "cached_analysis"})
                market_context = dict(cached_result.get("market_context", {}))
                if isinstance(market_context.get("decision_reasons"), list):
                    market_context["decision_reasons"] = list(market_context["decision_reasons"])
                analysis = cached_result.get("analysis")
                degraded = True
                degraded_reason = f"Showing cached analysis because live data is unavailable: {exc}"
            else:
                traditional = {"direction": "neutral", "confidence": 0, "recommendation": "UNAVAILABLE"}
                ai_prediction = {"direction": "neutral", "confidence": 0, "method": "live_unavailable", "risk_level": "high", "decision_score": 0}
                market_context = {
                    "degraded": True,
                    "degraded_reason": f"Live analysis is currently unavailable: {exc}",
                    "trend_condition": "unknown",
                    "market_condition": "unavailable",
                    "decision_reasons": ["The live market feed could not be analyzed right now."],
                    "candle_pattern": "N/A",
                    "lstm_signal": {"direction": "neutral", "confidence": 0, "method": "unavailable"},
                }
                analysis = None
                degraded = True
                degraded_reason = market_context["degraded_reason"]

    indicators = getattr(analysis, "indicators", {}) if analysis is not None else {}
    cached_live_snapshot = market_context.get("live_snapshot") if isinstance(market_context, dict) else None
    if isinstance(cached_live_snapshot, dict):
        live_snapshot = cached_live_snapshot
    else:
        try:
            live_snapshot = await asyncio.wait_for(
                bot.get_live_market_snapshot(
                    entry["pairdict"]["quotex_symbol"],
                    bot.TIMEFRAMES[timeframe]["quotex"],
                ),
                timeout=6,
            )
        except Exception as exc:
            logging.warning("Live snapshot failed for %s: %s", entry["display_name"], describe_exception(exc))
            cached_snapshot = bot.live_snapshot_cache.get(
                f"{entry['pairdict']['quotex_symbol']}|{bot.TIMEFRAMES[timeframe]['quotex']}"
            )
            if cached_snapshot:
                live_snapshot = dict(cached_snapshot[1])
            else:
                live_snapshot = {
                    "candles": [],
                    "price": None,
                    "sentiment": None,
                    "payout": enriched_entry.get("payout"),
                }

    price_series = live_snapshot.get("candles", [])
    if not price_series:
        sequence_key = bot.advanced_ai_system._sequence_key(entry["pairdict"]["symbol"], timeframe)
        sequence_buffer = list(bot.advanced_ai_system.sequence_buffers.get(sequence_key, []))
        price_series = [
            {"time": idx + 1, "open": row[0], "high": row[1], "low": row[2], "close": row[3], "volume": row[4]}
            for idx, row in enumerate(sequence_buffer[-20:])
        ]

    live_sentiment = live_snapshot.get("sentiment")
    live_payout = live_snapshot.get("payout")
    if live_payout is None:
        live_payout = enriched_entry.get("payout") or bot.settings.risk.expected_payout * 100
    if live_sentiment is None:
        if ai_prediction.get("direction") == "call":
            live_sentiment = max(50, ai_prediction.get("confidence", 50))
        elif ai_prediction.get("direction") == "put":
            live_sentiment = min(50, 100 - ai_prediction.get("confidence", 50))

    symbol_health = get_symbol_health(enriched_entry, timeframe)
    market_insights_raw = bot.advanced_ai_system.get_market_insights(entry["pairdict"]["symbol"], timeframe)
    market_insights = {
        **market_insights_raw,
        "historical_win_rate": round(float(market_insights_raw.get("win_rate", 0)) * 100, 2),
        "pattern_confidence": market_insights_raw.get("confidence", "low"),
    }
    mtf_confirmation = await get_multi_timeframe_confirmation(
        enriched_entry,
        timeframe,
        ai_prediction.get("direction", "neutral"),
        int(ai_prediction.get("confidence", 0) or 0),
    )
    market_regime = detect_market_regime(market_context, live_snapshot, ai_prediction.get("direction", "neutral"))
    payout_filter = check_payout_filter(live_payout)
    candlestick_pattern = analyze_candlestick_patterns(price_series or live_snapshot.get("candles", []), ai_prediction.get("direction", "neutral"))
    support_resistance = serialize_support_resistance(market_context)
    breakout_structure = market_context.get("breakout_structure", {}) or {}
    price_action_score = int(market_context.get("price_action_score", 0) or 0)
    raw_confidence = int(ai_prediction.get("confidence", 0) or 0)
    regime_adjustment = 6 if market_regime["regime"] == "trending" else -10 if market_regime["regime"] == "noisy" else 0
    payout_adjustment = 4 if payout_filter["passed"] else -15
    pattern_adjustment = int(candlestick_pattern.get("confidence_adjustment", 0) or 0)
    adjusted_confidence = max(
        0,
        min(
            99,
            raw_confidence
            + int(mtf_confirmation.get("adjustment", 0) or 0)
            + regime_adjustment
            + payout_adjustment
            + pattern_adjustment
            + price_action_score,
        ),
    )
    ai_prediction["confidence"] = adjusted_confidence
    ai_prediction["decision_score"] = max(
        0,
        min(
            99,
            int(ai_prediction.get("decision_score", raw_confidence) or 0)
            + int(mtf_confirmation.get("adjustment", 0) or 0)
            + regime_adjustment
            + payout_adjustment
            + pattern_adjustment
            + price_action_score,
        ),
    )
    if adjusted_confidence <= 0:
        ai_prediction["direction"] = "neutral"
        ai_prediction["risk_level"] = "high"
        traditional["direction"] = "neutral"
        market_context.setdefault("lstm_signal", {})
        if isinstance(market_context["lstm_signal"], dict):
            market_context["lstm_signal"]["direction"] = "neutral"
            market_context["lstm_signal"]["confidence"] = 0
    market_context.setdefault("decision_reasons", [])
    market_context["decision_reasons"].append(
        f"Multi-timeframe confirmation ({mtf_confirmation.get('higher_timeframe')}): {mtf_confirmation.get('label')}"
    )
    market_context["decision_reasons"].append(f"Market regime: {market_regime['regime']}")
    market_context["decision_reasons"].append(payout_filter["summary"])
    market_context["decision_reasons"].append(f"Candlestick pattern: {candlestick_pattern['name']}")
    if breakout_structure.get("summary"):
        market_context["decision_reasons"].append(f"Breakout state: {breakout_structure['summary']}")
    quad_analysis = build_quad_analysis(
        direction=ai_prediction.get("direction", "neutral"),
        timeframe=timeframe,
        live_price=live_snapshot.get("price"),
        market_context=market_context,
        live_snapshot=live_snapshot,
        support_resistance=support_resistance,
        candlestick_pattern=candlestick_pattern,
        breakout_structure=breakout_structure,
        market_regime=market_regime,
        mtf_confirmation=mtf_confirmation,
        payout_filter=payout_filter,
        symbol_health=symbol_health,
    )
    live_analysis_steps = build_live_analysis_steps(
        enriched_entry.get("display_name", "Selected pair"),
        ai_prediction.get("direction", "neutral"),
        quad_analysis,
        support_resistance,
        candlestick_pattern,
        payout_filter,
        market_regime,
        live_snapshot,
    )
    quad_confidence_adjustment = derive_quad_confidence_adjustment(int(quad_analysis.get("total_score", 0) or 0))
    final_confidence = max(0, min(99, adjusted_confidence + quad_confidence_adjustment))
    ai_prediction["confidence"] = final_confidence
    ai_prediction["decision_score"] = final_confidence
    if traditional.get("direction") in {"call", "put"}:
        traditional["confidence"] = final_confidence
        traditional["recommendation"] = traditional.get("recommendation") or traditional["direction"].upper()
    if final_confidence < 50 and ai_prediction.get("direction") in {"call", "put"}:
        market_context["decision_reasons"].append("Confidence dropped below the execution-quality threshold, so the setup is now in watch mode.")
    market_context["decision_reasons"].append(
        f"Quad-analysis alignment: {quad_analysis['label']}"
    )
    market_context["decision_reasons"] = list(dict.fromkeys(market_context["decision_reasons"]))
    best_entry = build_entry_plan(
        enriched_entry,
        timeframe,
        ai_prediction.get("direction", "neutral"),
        int(ai_prediction.get("confidence", 0) or 0),
        live_snapshot,
    )

    return store_cached_response(analysis_cache_key, {
        "asset": serialize_live_entry(enriched_entry),
        "timeframe": timeframe,
        "direction": ai_prediction.get("direction", "neutral"),
        "confidence": final_confidence,
        "raw_confidence": raw_confidence,
        "risk_level": ai_prediction.get("risk_level", "medium"),
        "decision_score": final_confidence,
        "analysis_method": ai_prediction.get("method", "unknown"),
        "models_used": ai_prediction.get("models_used", []),
        "model_weights": bot.advanced_ai_system.model_weights,
        "traditional": traditional,
        "lstm_signal": market_context.get("lstm_signal", {}),
        "market_context": market_context,
        "technical_summary": bot.get_advanced_technical_details(indicators) if indicators else "No live technical snapshot available.",
        "market_insights": market_insights,
        "performance": bot.advanced_ai_system.get_performance_stats(),
        "decision_reasons": market_context.get("decision_reasons", []),
        "candle_pattern": market_context.get("candle_pattern", "N/A"),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "price_series": price_series,
        "live_price": live_snapshot.get("price"),
        "live_sentiment": live_sentiment,
        "live_payout": live_payout,
        "symbol_health": symbol_health,
        "multi_timeframe": mtf_confirmation,
        "market_regime": market_regime,
        "payout_filter": payout_filter,
        "candlestick_pattern_detail": candlestick_pattern,
        "support_resistance": support_resistance,
        "breakout_structure": breakout_structure,
        "price_action_score": price_action_score,
        "quad_analysis": quad_analysis,
        "ai_voting": {
            "score": quad_analysis["total_score"],
            "label": quad_analysis["label"],
            "grade": quad_analysis["grade"],
            "trade_ready": quad_analysis["trade_ready"],
            "summary": quad_analysis["summary"],
        },
        "live_analysis_steps": live_analysis_steps,
        "best_entry": best_entry,
    })


async def execute_trade_from_webapp(
    entry: dict[str, Any],
    timeframe: str,
    direction: str,
    user_id: int,
    confidence: int | None = None,
    market_context: dict[str, Any] | None = None,
    analysis_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mark_broker_pressure()
    if timeframe not in bot.TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Unsupported timeframe.")
    if direction not in {"call", "put"}:
        raise HTTPException(status_code=400, detail="Direction must be call or put.")
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="A valid authenticated user_id is required for execution.")
    bot.cleanup_stale_active_trades(
        user_id=user_id,
        pair_label=entry["display_name"],
        asset=entry.get("quotex_api_symbol") or bot.quotex_symbol_to_api_symbol(entry["pairdict"]["quotex_symbol"]),
    )

    effective_confidence = confidence
    if effective_confidence is None:
        cached_result = bot.get_cached_analysis_result(entry["pairdict"], timeframe)
        effective_confidence = cached_result.get("confidence", bot.settings.risk.min_confidence_score) if cached_result else bot.settings.risk.min_confidence_score

    cached_result = bot.get_cached_analysis_result(entry["pairdict"], timeframe) or {}
    orchestrator = bot.get_trading_orchestrator()
    try:
        execution_plan = await asyncio.wait_for(
            orchestrator.prepare_execution(
                user_id,
                entry["pairdict"],
                timeframe,
                int(effective_confidence),
            ),
            timeout=6,
        )
    except asyncio.TimeoutError:
        logging.warning("Manual web execution plan timed out for %s. Falling back to direct amount sizing.", entry["display_name"])
        execution_plan = None
    except Exception as exc:
        logging.warning("Manual web execution plan failed for %s: %s", entry["display_name"], exc)
        execution_plan = None

    if execution_plan is None:
        raise HTTPException(
            status_code=503,
            detail="Execution planning is temporarily unavailable. Please retry after the backend reconnects.",
        )
    if not execution_plan.allowed:
        raise HTTPException(status_code=403, detail=execution_plan.reason)

    execution_amount = execution_plan.amount

    try:
        payout = await asyncio.wait_for(
            bot.fetch_live_payout(entry["pairdict"]["quotex_symbol"], bot.TIMEFRAMES[timeframe]["quotex"]),
            timeout=6,
        )
    except asyncio.TimeoutError:
        payout = None
        logging.warning("Manual web payout lookup timed out for %s. Continuing with cached payout.", entry["display_name"])
    except Exception as exc:
        payout = None
        logging.warning("Manual web payout lookup failed for %s: %s", entry["display_name"], exc)
    if payout is None:
        payout = (
            cached_result.get("live_payout")
            or cached_result.get("asset", {}).get("payout")
            or entry.get("payout")
        )
    payout_filter = check_payout_filter(payout)
    if not payout_filter["passed"]:
        raise HTTPException(status_code=409, detail=payout_filter["summary"])

    try:
        execution_result = await asyncio.wait_for(
            orchestrator.execute_trade(
                direction,
                entry.get("quotex_api_symbol") or bot.quotex_symbol_to_api_symbol(entry["pairdict"]["quotex_symbol"]),
                execution_amount,
                bot.TIMEFRAMES[timeframe]["quotex"],
            ),
            timeout=70,
        )
    except asyncio.TimeoutError:
        mark_broker_pressure(25)
        raise HTTPException(status_code=504, detail="Trade execution timed out. Please try again.")
    if not execution_result.success:
        if "timed out" in str(execution_result.reason).lower():
            mark_broker_pressure(25)
            logging.warning(
                "Manual web execution timed out for %s. Refreshing connection without retrying the stale order.",
                entry["display_name"],
            )
            bot.quotex_client = None
            connection_state_cache.pop("quotex", None)
            await bot.refresh_quotex_connection_if_needed()
        if not execution_result.success:
            status_code = 504 if "timed out" in str(execution_result.reason).lower() else 400
            raise HTTPException(status_code=status_code, detail=execution_result.reason)

    mark_broker_pressure(10)

    trade_id = execution_result.trade_id
    if trade_id in bot.active_trades:
        bot.get_trade_state_service().attach_trade_context(
            trade_id,
            user_id=user_id,
            analysis_timeframe=timeframe,
            pair_name=entry["display_name"],
        )
        cached_result = bot.get_cached_analysis_result(entry["pairdict"], timeframe) or {}
        merged_market_context = dict(cached_result.get("market_context", {}))
        if market_context:
            merged_market_context.update(market_context)
        trade_data = {
            "direction": direction,
            "confidence": int(effective_confidence),
            "pair": entry["display_name"],
            "timeframe": timeframe,
            "amount": execution_amount,
            "features": cached_result.get("features", []),
            "price_sequence": merged_market_context.get("price_sequence", []),
        }
        asyncio.create_task(
            bot.monitor_trade_with_advanced_ai(
                trade_id,
                user_id,
                None,
                trade_data,
                cached_result.get("features", []),
                merged_market_context,
            )
        )

    invalidate_cached_responses(
        "health",
        "trade-journal",
        "journal-analytics",
        "analysis:",
        "top-setups:",
    )

    return {
        "success": True,
        "trade_id": trade_id,
        "pair": entry["display_name"],
        "amount": execution_amount,
        "direction": direction,
        "duration": bot.TIMEFRAMES[timeframe]["quotex"],
    }


async def run_entry_watch(watcher_id: str) -> None:
    watcher = entry_watchers.get(watcher_id)
    if not watcher:
        return

    try:
        timeframe_seconds = bot.TIMEFRAMES[watcher["timeframe"]]["quotex"]
        max_wait_seconds = max(90, min(900, timeframe_seconds * 6))
        deadline = bot.now_ts() + max_wait_seconds
        watcher["status"] = "watching"

        while bot.now_ts() < deadline:
            current = entry_watchers.get(watcher_id)
            if not current or current.get("status") == "cancelled":
                return

            entry = await resolve_entry(asset_id=current["asset_id"])
            analysis = await build_analysis_payload(entry, current["timeframe"])
            current["updated_at"] = bot.now_ts()
            current["symbol_health"] = analysis.get("symbol_health", {})
            current["best_entry"] = analysis.get("best_entry", {})
            current["confidence"] = analysis.get("confidence", 0)
            current["analysis_method"] = analysis.get("analysis_method", "unknown")
            current["multi_timeframe"] = analysis.get("multi_timeframe", {})

            live_price = analysis.get("live_price")
            current["last_price"] = live_price
            if analysis.get("direction") != current["direction"]:
                current["status"] = "cancelled"
                current["reason"] = f"Signal flipped to {analysis.get('direction', 'neutral').upper()}."
                return

            if current.get("multi_timeframe", {}).get("status") == "misaligned":
                current["status"] = "cancelled"
                current["reason"] = "Auto entry stopped because the higher timeframe moved against this setup."
                return

            if int(current["confidence"] or 0) < bot.settings.risk.min_confidence_score:
                current["status"] = "cancelled"
                current["reason"] = "Confidence dropped below the minimum execution threshold."
                return

            if (current.get("symbol_health", {}).get("score") or 0) < 35:
                current["status"] = "cancelled"
                current["reason"] = "Symbol health became too weak for a safe entry."
                return

            if price_in_entry_zone(live_price, current["best_entry"]):
                current["triggered_at"] = bot.now_ts()
                if current["mode"] == "alert":
                    current["status"] = "ready"
                    current["reason"] = "Price reached the best entry zone. You can open the trade now."
                    return

                locked, lock_reason = is_pair_locked_for_auto_entry(entry, int(current.get("user_id", 0) or 0))
                if locked:
                    current["status"] = "locked"
                    current["reason"] = lock_reason
                    return

                current["status"] = "executing"
                execution = await execute_trade_from_webapp(
                    entry,
                    current["timeframe"],
                    current["direction"],
                    current["user_id"],
                    int(current["confidence"] or 0),
                    analysis.get("market_context", {}),
                    analysis,
                )
                current["status"] = "executed"
                current["reason"] = "Auto entry opened the trade inside the planned zone."
                current["trade"] = execution
                return

            current["reason"] = build_entry_watch_message(current)
            await asyncio.sleep(2.5)

        watcher = entry_watchers.get(watcher_id)
        if watcher and watcher.get("status") not in {"executed", "ready", "cancelled"}:
            watcher["status"] = "expired"
            watcher["reason"] = "The watch window expired before price entered the best entry zone."
    except Exception as exc:
        watcher = entry_watchers.get(watcher_id)
        if watcher:
            watcher["status"] = "failed"
            watcher["reason"] = f"Entry watch failed: {exc}"


def create_app() -> FastAPI:
    app = FastAPI(title=bot.settings.webapp.title)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/assets", StaticFiles(directory=BASE_DIR), name="assets")

    @app.middleware("http")
    async def disable_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.on_event("startup")
    async def startup_event() -> None:
        await ensure_quotex_connection()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(
            WEBAPP_INDEX,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/webapp_bundle_20260329e.js")
    async def webapp_bundle_js() -> FileResponse:
        return FileResponse(
            WEBAPP_JS,
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/webapp_bundle_20260329e.css")
    async def webapp_bundle_css() -> FileResponse:
        return FileResponse(
            WEBAPP_CSS,
            media_type="text/css",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> dict[str, Any]:
        cached_payload = get_cached_response("health", HEALTH_CACHE_SECONDS)
        if cached_payload is not None:
            return cached_payload
        if broker_is_under_pressure():
            cached_balance = bot.balance_cache.get("main")
            return store_cached_response("health", {
                "title": bot.settings.webapp.title,
                "connection": "🟡 Broker busy with execution",
                "balance": cached_balance[1] if cached_balance else None,
                "open_trades": len([trade for trade in bot.active_trades.values() if trade.get("status") == "pending"]),
                "history_size": len(bot.trade_history),
                "performance": bot.advanced_ai_system.get_performance_stats(),
                "webapp_url": bot.settings.webapp.public_url,
            })
        connection = await bot.check_quotex_connection()
        try:
            balance = await bot.get_current_balance()
        except Exception as exc:
            logging.warning("Health balance fallback used: %s", exc)
            cached_balance = bot.balance_cache.get("main")
            balance = cached_balance[1] if cached_balance else None
        performance = bot.advanced_ai_system.get_performance_stats()
        open_trades = len([trade for trade in bot.active_trades.values() if trade.get("status") == "pending"])
        return store_cached_response("health", {
            "title": bot.settings.webapp.title,
            "connection": connection,
            "balance": balance,
            "open_trades": open_trades,
            "history_size": len(bot.trade_history),
            "performance": performance,
            "webapp_url": bot.settings.webapp.public_url,
        })

    @app.get("/api/markets", response_model=MarketsResponse)
    async def markets(category: str = Query("all")) -> dict[str, Any]:
        cache_key = f"markets:{category}"
        cached_payload = get_cached_response(cache_key, MARKETS_CACHE_SECONDS)
        if cached_payload is not None:
            return cached_payload
        await ensure_quotex_connection()
        entries = await bot.get_live_quotex_assets(category)
        if entries:
            semaphore = asyncio.Semaphore(6)

            async def enrich_entry(entry: dict[str, Any]) -> None:
                async with semaphore:
                    await bot.enrich_live_entry_with_payout(entry)

            await asyncio.gather(*(enrich_entry(entry) for entry in entries))
        counts = {
            "all": len(entries),
            "regular": len([entry for entry in entries if entry["market_type"] == "regular"]),
            "otc": len([entry for entry in entries if entry["market_type"] == "otc"]),
            "crypto": len([entry for entry in entries if entry["market_type"] == "crypto"]),
        }
        return store_cached_response(cache_key, {
            "category": category,
            "counts": counts,
            "items": [serialize_live_entry(entry) for entry in entries],
        })

    @app.get("/api/top-setups", response_model=TopSetupsResponse)
    async def top_setups(
        timeframe: str = Query("1m"),
        category: str = Query("all"),
        limit: int = Query(3, ge=1, le=6),
    ) -> dict[str, Any]:
        cache_key = f"top-setups:{timeframe}:{category}:{limit}"
        cached_payload = get_cached_response(cache_key, TOP_SETUPS_CACHE_SECONDS)
        if cached_payload is not None:
            return cached_payload
        if broker_is_under_pressure():
            stale_cached = response_cache.get(cache_key)
            if stale_cached and isinstance(stale_cached[1], dict):
                return stale_cached[1]
            return {
                "timeframe": timeframe,
                "category": category,
                "items": [],
            }
        await ensure_quotex_connection()
        try:
            results = await asyncio.wait_for(
                bot.scan_top_trade_setups(timeframe=timeframe, category=category, top_n=limit),
                timeout=16 if category == "otc" else 18,
            )
        except Exception as exc:
            logging.warning("Top setups timed out or failed for %s/%s: %s", category, timeframe, exc)
            stale_cached = response_cache.get(cache_key)
            results = stale_cached[1]["items"] if stale_cached and isinstance(stale_cached[1], dict) and stale_cached[1].get("items") else []
        filtered_results = []
        for result in results:
            if result.get("direction") not in {"call", "put"}:
                continue
            if "asset" in result and "entry" not in result:
                continue
            payout_gate = check_payout_filter(result["entry"].get("payout"))
            if payout_gate["passed"]:
                filtered_results.append((result, payout_gate))
        confirmations = await asyncio.gather(*[
            get_multi_timeframe_confirmation(result["entry"], timeframe, result["direction"], int(result["confidence"] or 0))
            for result, _ in filtered_results
        ]) if filtered_results else []
        return store_cached_response(cache_key, {
            "timeframe": timeframe,
            "category": category,
            "items": [
                {
                    "asset": serialize_live_entry(result["entry"]),
                    "direction": result["direction"],
                    "confidence": max(0, min(99, int(result["confidence"]) + int(confirmation.get("adjustment", 0) or 0))),
                    "score": round(
                        result["score"]
                        + get_symbol_health(result["entry"], timeframe)["score"] * 0.2
                        + (confirmation.get("adjustment", 0) or 0),
                        2,
                    ),
                    "trend_condition": result["market_context"].get("trend_condition", "normal"),
                    "market_condition": result["market_context"].get("market_condition", "normal"),
                    "health": get_symbol_health(result["entry"], timeframe),
                    "multi_timeframe": confirmation,
                    "payout_filter": payout_gate,
                    "price_action_score": int(result["market_context"].get("price_action_score", 0) or 0),
                    "breakout_structure": result["market_context"].get("breakout_structure", {}),
                }
                for (result, payout_gate), confirmation in zip(filtered_results, confirmations)
            ],
        })

    @app.get("/api/best-entry")
    async def best_entry(
        asset_id: str = Query(...),
        timeframe: str = Query("1m"),
        direction: str | None = Query(None),
    ) -> dict[str, Any]:
        await ensure_quotex_connection()
        entry = await resolve_entry(asset_id=asset_id)
        analysis = await build_analysis_payload(entry, timeframe)
        effective_direction = direction or analysis.get("direction", "neutral")
        return {
            "asset_id": asset_id,
            "pair": analysis["asset"]["display_name"],
            "direction": effective_direction,
            "best_entry": build_entry_plan(entry, timeframe, effective_direction, int(analysis.get("confidence", 0) or 0), {
                "price": analysis.get("live_price"),
                "payout": analysis.get("live_payout"),
                "sentiment": analysis.get("live_sentiment"),
                "candles": analysis.get("price_series", []),
            }),
        }

    @app.get("/api/trade-journal")
    async def trade_journal(request: Request, limit: int = Query(25, ge=1, le=100)) -> dict[str, Any]:
        require_webapp_api_token(request)
        cache_key = f"trade-journal:{limit}"
        cached_payload = get_cached_response(cache_key, JOURNAL_CACHE_SECONDS)
        if cached_payload is not None:
            return cached_payload
        closed_trades = [trade for trade in bot.trade_history if trade.get("status") == "closed"]
        closed_trades.sort(key=lambda item: item.get("close_time", 0), reverse=True)
        items = [serialize_journal_trade(trade) for trade in closed_trades[:limit]]
        return store_cached_response(cache_key, {
            "count": len(items),
            "items": items,
        })

    @app.get("/api/journal-analytics")
    async def journal_analytics(request: Request) -> dict[str, Any]:
        require_webapp_api_token(request)
        cached_payload = get_cached_response("journal-analytics", JOURNAL_CACHE_SECONDS)
        if cached_payload is not None:
            return cached_payload
        return store_cached_response("journal-analytics", compute_journal_analytics(list(bot.trade_history)))

    @app.get("/api/currency-strength")
    async def currency_strength(
        timeframe: str = Query("1m"),
        category: str = Query("regular"),
    ) -> dict[str, Any]:
        effective_category = category if category in {"regular", "otc"} else "regular"
        cache_key = f"currency-strength:{timeframe}:{effective_category}"
        cached_payload = get_cached_response(cache_key, CURRENCY_STRENGTH_CACHE_SECONDS)
        if cached_payload is not None:
            return cached_payload
        await ensure_quotex_connection()
        entries = await bot.get_live_quotex_assets(effective_category)
        scores = {
            currency: {"currency": currency, "score": 0.0, "pairs": 0, "bullish_votes": 0, "bearish_votes": 0}
            for currency in MAJOR_FX_CURRENCIES
        }

        semaphore = asyncio.Semaphore(4)

        async def analyze_strength_entry(entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
            async with semaphore:
                try:
                    analysis = await build_analysis_payload(entry, timeframe)
                    return entry, analysis
                except Exception as exc:
                    logging.warning("Currency strength skipped %s: %s", entry.get("display_name"), exc)
                    return entry, None

        analyzed_entries = await asyncio.gather(*(analyze_strength_entry(entry) for entry in entries[:18]))
        for entry, analysis in analyzed_entries:
            base, quote = extract_symbol_currencies(entry["pairdict"].get("symbol") or entry.get("quotex_symbol"))
            if not base or not quote:
                continue
            if not analysis:
                continue
            direction = analysis.get("direction", "neutral")
            confidence = float(analysis.get("confidence", 0) or 0)
            if direction not in {"call", "put"} or confidence <= 0:
                continue

            base_delta = confidence if direction == "call" else -confidence
            quote_delta = -base_delta

            scores[base]["score"] += base_delta
            scores[quote]["score"] += quote_delta
            scores[base]["pairs"] += 1
            scores[quote]["pairs"] += 1
            if base_delta > 0:
                scores[base]["bullish_votes"] += 1
            else:
                scores[base]["bearish_votes"] += 1
            if quote_delta > 0:
                scores[quote]["bullish_votes"] += 1
            else:
                scores[quote]["bearish_votes"] += 1

        rows = []
        for currency, payload in scores.items():
            pairs = max(1, payload["pairs"])
            normalized = max(-100, min(100, payload["score"] / pairs))
            rows.append({
                **payload,
                "normalized_score": round(normalized, 2),
                "bias": "strong" if normalized >= 35 else "weak" if normalized <= -35 else "mixed",
            })
        rows.sort(key=lambda item: item["normalized_score"], reverse=True)
        return store_cached_response(cache_key, {
            "timeframe": timeframe,
            "category": category,
            "items": rows,
            "strongest": rows[0] if rows else None,
            "weakest": rows[-1] if rows else None,
        })

    @app.get("/api/entry-watch")
    async def entry_watch_status(
        user_id: int = Query(0),
        asset_id: str | None = Query(None),
    ) -> dict[str, Any]:
        items = [
            serialize_entry_watcher(watcher)
            for watcher in entry_watchers.values()
            if watcher.get("user_id", 0) == user_id
        ]
        if asset_id:
            items = [item for item in items if item and item.get("asset_id") == asset_id]
        items = [item for item in items if item]
        items.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
        return {
            "count": len(items),
            "active": items[0] if items else None,
            "items": items[:10],
        }

    @app.post("/api/entry-watch")
    async def start_entry_watch(http_request: Request, request: EntryWatchRequest) -> dict[str, Any]:
        require_webapp_api_token(http_request)
        await ensure_quotex_connection()
        entry = await resolve_entry(asset_id=request.asset_id)
        analysis = await build_analysis_payload(entry, request.timeframe)
        direction = (request.direction or analysis.get("direction") or "neutral").lower()
        if direction not in {"call", "put"}:
            raise HTTPException(status_code=400, detail="Best entry needs a live CALL or PUT direction first.")
        if request.user_id <= 0:
            raise HTTPException(status_code=400, detail="A valid authenticated user_id is required for entry watch.")
        mode = request.mode.lower()
        if mode not in {"alert", "auto"}:
            raise HTTPException(status_code=400, detail="Entry watch mode must be alert or auto.")
        if mode == "auto":
            locked, lock_reason = is_pair_locked_for_auto_entry(entry, request.user_id)
            if locked:
                raise HTTPException(status_code=400, detail=lock_reason)

        for watcher in entry_watchers.values():
            if watcher.get("user_id") == request.user_id and watcher.get("status") in {"pending", "watching", "executing", "ready"}:
                watcher["status"] = "cancelled"
                watcher["reason"] = "Replaced by a newer entry watch."

        watcher_id = f"{request.user_id}:{request.asset_id}:{int(bot.now_ts())}"
        watcher = {
            "id": watcher_id,
            "asset_id": request.asset_id,
            "user_id": request.user_id,
            "pair": entry["display_name"],
            "timeframe": request.timeframe,
            "direction": direction,
            "mode": mode,
            "status": "pending",
            "created_at": bot.now_ts(),
            "updated_at": bot.now_ts(),
            "confidence": int(analysis.get("confidence", 0) or 0),
            "analysis_method": analysis.get("analysis_method", "unknown"),
            "symbol_health": analysis.get("symbol_health", {}),
            "best_entry": analysis.get("best_entry", {}),
            "last_price": analysis.get("live_price"),
            "reason": "Entry watch created and waiting for the first live recheck.",
        }
        watcher["task"] = asyncio.create_task(run_entry_watch(watcher_id))
        entry_watchers[watcher_id] = watcher
        return {
            "success": True,
            "watcher": serialize_entry_watcher(watcher),
        }

    @app.post("/api/entry-watch/cancel")
    async def cancel_entry_watch(
        request: Request,
        user_id: int = Query(0),
        watcher_id: str | None = Query(None),
    ) -> dict[str, Any]:
        require_webapp_api_token(request)
        target = None
        if watcher_id:
            target = entry_watchers.get(watcher_id)
        else:
            user_watchers = [
                watcher for watcher in entry_watchers.values()
                if watcher.get("user_id") == user_id and watcher.get("status") in {"pending", "watching", "executing", "ready"}
            ]
            user_watchers.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
            target = user_watchers[0] if user_watchers else None
        if not target:
            return {"success": True, "watcher": None}

        target["status"] = "cancelled"
        target["updated_at"] = bot.now_ts()
        target["reason"] = "Entry watch cancelled by the user."
        task = target.get("task")
        if task and not task.done():
            task.cancel()
        return {
            "success": True,
            "watcher": serialize_entry_watcher(target),
        }

    @app.get("/api/analyze", response_model=AnalyzeResponse)
    async def analyze(
        asset_id: str | None = Query(None),
        symbol: str | None = Query(None),
        timeframe: str = Query("1m"),
    ) -> dict[str, Any]:
        cache_asset_key = asset_id or symbol or "unknown"
        cache_key = f"analysis:{cache_asset_key}:{timeframe}"
        if broker_is_under_pressure():
            stale_cached = get_stale_cached_response(cache_key)
            if stale_cached is not None:
                return stale_cached
        await ensure_quotex_connection()
        entry = await resolve_entry(asset_id=asset_id, symbol=symbol)
        return await build_analysis_payload(entry, timeframe)

    @app.get("/api/live-snapshot", response_model=LiveSnapshotResponse)
    async def live_snapshot(
        asset_id: str = Query(...),
        timeframe: str = Query("1m"),
    ) -> dict[str, Any]:
        entry = await resolve_entry(asset_id=asset_id)
        if timeframe not in bot.TIMEFRAMES:
            raise HTTPException(status_code=400, detail="Unsupported timeframe.")
        cache_key = f"live-snapshot:{asset_id}:{timeframe}"

        if broker_is_under_pressure():
            stale_cached = get_stale_cached_response(cache_key)
            if stale_cached is not None:
                return stale_cached
            snapshot_cache_key = f"{entry['pairdict']['quotex_symbol']}|{bot.TIMEFRAMES[timeframe]['quotex']}"
            stale_snapshot = bot.live_snapshot_cache.get(snapshot_cache_key)
            if stale_snapshot and isinstance(stale_snapshot[1], dict):
                payload = {
                    "asset_id": asset_id,
                    "timeframe": timeframe,
                    "price": stale_snapshot[1].get("price"),
                    "sentiment": stale_snapshot[1].get("sentiment"),
                    "payout": stale_snapshot[1].get("payout"),
                    "candles": stale_snapshot[1].get("candles", [])[-120:],
                    "timestamp": stale_snapshot[1].get("timestamp"),
                }
                return store_cached_response(cache_key, payload)

        await ensure_quotex_connection()

        try:
            snapshot = await asyncio.wait_for(
                bot.get_live_market_snapshot(
                    entry["pairdict"]["quotex_symbol"],
                    bot.TIMEFRAMES[timeframe]["quotex"],
                ),
                timeout=5,
            )
        except Exception as exc:
            logging.warning("HTTP live snapshot failed for %s: %s", entry["display_name"], exc)
            snapshot = {
                "price": None,
                "sentiment": None,
                "payout": entry.get("payout"),
                "candles": [],
                "timestamp": None,
            }

        return store_cached_response(cache_key, {
            "asset_id": asset_id,
            "timeframe": timeframe,
            "price": snapshot.get("price"),
            "sentiment": snapshot.get("sentiment"),
            "payout": snapshot.get("payout"),
            "candles": snapshot.get("candles", [])[-120:],
            "timestamp": snapshot.get("timestamp"),
        })

    @app.post("/api/execute", response_model=ExecuteTradeResponse)
    async def execute_trade(http_request: Request, request: ExecuteTradeRequest) -> dict[str, Any]:
        require_webapp_api_token(http_request)
        await ensure_quotex_connection()
        entry = await resolve_entry(asset_id=request.asset_id)
        return await execute_trade_from_webapp(
            entry,
            request.timeframe,
            request.direction,
            request.user_id,
            request.confidence,
        )

    @app.websocket("/ws/live-feed")
    async def live_feed(
        websocket: WebSocket,
        asset_id: str,
        timeframe: str = "1m",
    ) -> None:
        await websocket.accept()
        try:
            entry = await resolve_entry(asset_id=asset_id)
            timeframe_seconds = bot.TIMEFRAMES.get(timeframe, bot.TIMEFRAMES["1m"])["quotex"]
            while True:
                if broker_is_under_pressure():
                    stale_snapshot = bot.live_snapshot_cache.get(f"{entry['pairdict']['quotex_symbol']}|{timeframe_seconds}")
                    snapshot = stale_snapshot[1] if stale_snapshot and isinstance(stale_snapshot[1], dict) else {
                        "price": None,
                        "sentiment": None,
                        "payout": entry.get("payout"),
                        "candles": [],
                        "timestamp": time.time(),
                    }
                else:
                    await ensure_quotex_connection()
                    try:
                        snapshot = await bot.get_live_market_snapshot(entry["pairdict"]["quotex_symbol"], timeframe_seconds)
                    except Exception as exc:
                        logging.warning("Live feed snapshot failed for %s: %s", entry["display_name"], exc)
                        bot.live_snapshot_cache.pop(f"{entry['pairdict']['quotex_symbol']}|{timeframe_seconds}", None)
                        bot.quotex_client = None
                        await ensure_quotex_connection()
                        snapshot = await bot.get_live_market_snapshot(entry["pairdict"]["quotex_symbol"], timeframe_seconds)
                await websocket.send_json(
                    {
                        "asset_id": asset_id,
                        "timeframe": timeframe,
                        "price": snapshot.get("price"),
                        "sentiment": snapshot.get("sentiment"),
                        "payout": snapshot.get("payout"),
                        "candles": snapshot.get("candles", [])[-120:],
                        "timestamp": snapshot.get("timestamp"),
                    }
                )
                await asyncio.sleep(2.5 if broker_is_under_pressure() else 1.25)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json({"error": str(exc)})
            await websocket.close()

    return app


app = create_app()

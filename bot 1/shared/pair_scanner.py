import asyncio
import logging
from typing import Any, Callable, Optional

from bot_algorithms import Candle, ConfluenceEngine

log = logging.getLogger("Scanner")


def _raw_to_candle(raw) -> Optional[Candle]:
    try:
        if isinstance(raw, dict):
            return Candle(
                open=float(raw.get("open", raw.get("o", 0))),
                close=float(raw.get("close", raw.get("c", 0))),
                high=float(raw.get("high", raw.get("h", 0))),
                low=float(raw.get("low", raw.get("l", 0))),
                volume=float(raw.get("volume", raw.get("v", 0))),
            )
        if isinstance(raw, (list, tuple)) and len(raw) >= 5:
            idx = 1 if len(raw) >= 6 else 0
            return Candle(
                open=float(raw[idx]),
                close=float(raw[idx + 1]),
                high=float(raw[idx + 2]),
                low=float(raw[idx + 3]),
                volume=float(raw[idx + 4]) if len(raw) > idx + 4 else 0.0,
            )
    except Exception:
        pass
    return None


async def fetch_candles_for_pair(client, symbol: str, count: int = 60) -> list[Candle]:
    period = 60
    fetch_methods = [
        ("get_candles", lambda: client.get_candles(symbol, period, count)),
        ("get_candle_v2", lambda: client.get_candle_v2(symbol, period)),
        ("get_history", lambda: client.get_history(symbol, period, count)),
    ]
    for method_name, method_call in fetch_methods:
        if not hasattr(client, method_name):
            continue
        try:
            raw_data = await method_call()
            if not raw_data:
                continue
            candles = []
            for raw in (raw_data if isinstance(raw_data, list) else [raw_data]):
                c = _raw_to_candle(raw)
                if c and c.high >= c.low and c.high > 0:
                    candles.append(c)
            if candles:
                return candles[-count:]
        except Exception:
            pass
    return []


async def scan_top_trade_setups(
    get_payout_fn: Callable[[str], float],
    pipeline=None,
    market: str = "otc",
    top_n: int = 5,
    min_payout: float = 76.0,
    balance: float = 1000.0,
) -> list[dict[str, Any]]:
    from pairs_registry import list_pairs, get_pair

    pairs = list_pairs(pair_type=market) if market != "all" else list_pairs()[:15]
    if not pairs:
        pairs = list_pairs(pair_type="otc")[:10]

    client = None
    current_symbol = None
    if pipeline:
        current_symbol = pipeline.data_settings.symbol if hasattr(pipeline, 'data_settings') else None
        if hasattr(pipeline, 'connection') and pipeline.connection:
            client = pipeline.connection.client

    semaphore = asyncio.Semaphore(3)
    results = []

    async def analyze_one(key: str, info) -> Optional[dict]:
        async with semaphore:
            payout = get_payout_fn(key)
            if payout < min_payout:
                return None
            if payout <= 0:
                payout = getattr(info, 'min_payout', 76.0)

            candles = []
            price = 0.0
            quotex_sym = getattr(info, 'quotex_symbol', None) or key
            raw_symbol = quotex_sym.split("-")[0] if "-" in quotex_sym else quotex_sym

            if pipeline and current_symbol and current_symbol == quotex_sym:
                if hasattr(pipeline, 'buffer') and pipeline.buffer:
                    candles = pipeline.buffer.candles
                    price = pipeline.buffer.current_price or (candles[-1].close if candles else 0)
            elif client:
                try:
                    candles = await fetch_candles_for_pair(client, raw_symbol, 60)
                    if candles:
                        price = candles[-1].close
                except Exception:
                    pass

            if len(candles) < 10:
                return {
                    "key": key, "pair": key,
                    "display_name": getattr(info, 'display_name', key) if info else key,
                    "direction": "neutral", "confidence": 50, "score": 0,
                    "payout": payout,
                    "market_type": market,
                    "reasons": ["Insufficient candles"],
                }

            sig = ConfluenceEngine(candles, price, payout, balance).run()
            score = sig.score + min(10, payout / 10)
            return {
                "key": key, "pair": key,
                "display_name": getattr(info, 'display_name', key) if info else key,
                "direction": "call" if sig.direction == "UP" else "put" if sig.direction == "DOWN" else "neutral",
                "confidence": sig.confidence,
                "score": round(score, 1),
                "payout": payout,
                "market_type": market,
                "reasons": list(sig.reasons)[:3],
            }

    tasks = [analyze_one(key, info) for key, info in pairs[:15]]
    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            if result:
                results.append(result)
        except Exception as e:
            log.debug("Scanner error: %s", e)

    results.sort(key=lambda x: (x["score"], x["confidence"]), reverse=True)
    return results[:top_n]

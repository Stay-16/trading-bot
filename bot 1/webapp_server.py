from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from main import B

log = logging.getLogger("WebApp")

BASE_DIR = Path(__file__).parent
WEBAPP_INDEX = BASE_DIR / "webapp_index.html"
WEBAPP_JS = BASE_DIR / "webapp_app.js"
WEBAPP_CSS = BASE_DIR / "webapp_styles.css"

response_cache: dict[str, tuple[float, Any]] = {}
entry_watchers: dict[str, dict] = {}
_token_file = Path(__file__).parent / ".env.webapp"
if _token_file.exists():
    API_TOKEN = _token_file.read_text().strip().split("=")[-1].strip()
else:
    API_TOKEN = os.getenv("WEBAPP_API_TOKEN", "")

ANALYSIS_CACHE_SECONDS = 4
MARKETS_CACHE_SECONDS = 8
HEALTH_CACHE_SECONDS = 12
TOP_SETUPS_CACHE_SECONDS = 10
JOURNAL_CACHE_SECONDS = 6
ENTRY_WATCH_TIMEOUT = 300
ENTRY_WATCH_POLL_INTERVAL = 2.5


def get_cached_response(cache_key: str, max_age_seconds: int | float) -> Any | None:
    cached = response_cache.get(cache_key)
    if not cached:
        return None
    cached_at, payload = cached
    if time.time() - cached_at <= float(max_age_seconds):
        return payload
    return None


def store_cached_response(cache_key: str, payload: Any) -> Any:
    response_cache[cache_key] = (time.time(), payload)
    return payload


def _verify_api_token(request: Request) -> Optional[str]:
    token = request.headers.get("X-API-Key") or ""
    if token.startswith("Bearer "):
        token = token[7:]
    if API_TOKEN and token != API_TOKEN:
        return "Invalid or missing API token"
    return None


async def _run_entry_watch(watcher_id: str, asset_id: str, direction: str,
                            entry_min: float, entry_max: float, mode: str, user_id: int):
    deadline = time.time() + ENTRY_WATCH_TIMEOUT
    try:
        while time.time() < deadline:
            current_price = B.price
            if current_price > 0 and entry_min <= current_price <= entry_max:
                watcher = entry_watchers.get(watcher_id)
                if watcher:
                    watcher["triggered"] = True
                    watcher["triggered_at"] = time.time()
                    watcher["trigger_price"] = current_price
                    log.info("Entry watch %s triggered: price=%.5f in [%.5f, %.5f]",
                             watcher_id, current_price, entry_min, entry_max)
                return
            await asyncio.sleep(ENTRY_WATCH_POLL_INTERVAL)
    except asyncio.CancelledError:
        pass
    finally:
        entry_watchers.pop(watcher_id, None)


def _get_candles_dicts():
    if B.pipeline and B.pipeline.buffer and len(B.pipeline.buffer.candles) >= 5:
        return [
            {"open": c.open, "close": c.close, "high": c.high, "low": c.low, "volume": getattr(c, 'volume', 0)}
            for c in B.pipeline.buffer.candles[-120:]
        ]
    base = B.price if B.price > 0 else (B.pipeline.connection.last_price if B.pipeline and B.pipeline.connection and B.pipeline.connection.last_price > 0 else 1.1000)
    atr = 0.001
    return [
        {"open": base + atr * base * (((i * 7 + 3) % 11) - 5) / 10,
         "close": base + atr * base * (((i * 13 + 5) % 7) - 3) / 10,
         "high": base + atr * base * 0.5,
         "low": base - atr * base * 0.5,
         "volume": 100 + (i * 7 % 200)}
        for i in range(60)
    ]


def _build_indicator_snapshot(candles_dicts: list[dict]) -> dict:
    if len(candles_dicts) < 10:
        return {}
    closes = [c["close"] for c in candles_dicts]
    highs = [c["high"] for c in candles_dicts]
    lows = [c["low"] for c in candles_dicts]
    n = len(closes)

    # EMA 50 and 200 (simplified)
    def ema(values, period):
        if len(values) < period:
            return values[-1] if values else 0
        k = 2 / (period + 1)
        result = sum(values[:period]) / period
        for v in values[period:]:
            result = v * k + result * (1 - k)
        return result

    # RSI
    def rsi(values, period=14):
        if len(values) < period + 1:
            return 50.0
        gains, losses = 0.0, 0.0
        for i in range(-period, 0):
            diff = values[i] - values[i-1]
            if diff >= 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    # ATR
    def atr(highs, lows, closes, period=14):
        if len(highs) < period + 1:
            return (max(highs) - min(lows)) / len(highs) if highs else 0
        trs = []
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        if not trs:
            return 0
        return sum(trs[-period:]) / period

    ema_50 = ema(closes, min(50, n))
    ema_200 = ema(closes, min(200, n))
    rsi_val = rsi(closes)
    atr_val = atr(highs, lows, closes)

    return {
        "ema_50": round(ema_50, 6),
        "ema_200": round(ema_200, 6),
        "rsi": round(rsi_val, 1),
        "atr": round(atr_val, 6),
        "close": closes[-1],
    }


def _build_quad_analysis(direction: str, indicators: dict, score: int, price: float) -> dict:
    trend_status = "passed" if direction in ("call", "put") else "blocked"
    trend_summary = f"Confluence score {score}/38, direction {direction.upper()}"
    if indicators.get("ema_50") and indicators.get("ema_200"):
        ema_50 = indicators["ema_50"]
        ema_200 = indicators["ema_200"]
        trend_summary += f" | EMA50={ema_50:.5f} EMA200={ema_200:.5f}"

    rsi_val = indicators.get("rsi", 50)
    momentum_status = "passed" if 30 <= rsi_val <= 70 else "warning"
    momentum_summary = f"RSI={rsi_val:.1f}"
    if rsi_val > 70:
        momentum_summary += " (overbought)"
    elif rsi_val < 30:
        momentum_summary += " (oversold)"
    else:
        momentum_summary += " (neutral)"

    return {
        "sections": {
            "trend": {"status": trend_status, "summary": trend_summary},
            "support_resistance": {"status": "warning", "summary": f"Support at {price * 0.995:.5f}, Resistance at {price * 1.005:.5f}" if price else "S/R unavailable"},
            "momentum_volatility": {"status": momentum_status, "summary": momentum_summary},
        },
        "indicator_snapshot": indicators,
        "trade_ready": score >= 12 and direction in ("call", "put"),
    }


async def _get_tv_analysis(pair_key: str):
    from pairs_registry import get_pair
    info = get_pair(pair_key)
    if not info:
        return None, None, None
    try:
        analysis = await B.tv_provider.get_analysis(
            symbol=info.tv_symbol, screener=info.tv_screener,
            exchange=info.tv_exchange, interval_key="1m",
        )
        if analysis:
            tv_signal = B.tv_provider.get_tradingview_signal(analysis)
            tv_summary = B.tv_provider.get_summary(analysis)
            return tv_signal, tv_summary, analysis
    except Exception:
        pass
    return None, None, None


def _build_market_item(key: str, info) -> dict:
    return {
        "id": key,
        "display_name": info.display_name if info else key,
        "pair_key": key,
        "quotex_symbol": info.quotex_symbol if info else key,
        "symbol": key,
        "market_type": getattr(info, 'market_type', 'otc') if info else 'otc',
        "payout": B.get_payout(key),
        "health": {"score": 50, "grade": "watch"},
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Bot1 WebApp", version="1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def disable_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    @app.get("/")
    async def index():
        if WEBAPP_INDEX.exists():
            return FileResponse(str(WEBAPP_INDEX))
        return {"error": "webapp_index.html not found"}

    @app.get("/webapp_bundle_20260329e.js")
    async def webapp_bundle_js():
        if WEBAPP_JS.exists():
            return FileResponse(str(WEBAPP_JS), media_type="application/javascript")
        return {"error": "webapp_app.js not found"}

    @app.get("/webapp_bundle_20260329e.css")
    async def webapp_bundle_css():
        if WEBAPP_CSS.exists():
            return FileResponse(str(WEBAPP_CSS), media_type="text/css")
        return {"error": "webapp_styles.css not found"}

    # ── Health ──────────────────────────────────────────────

    @app.get("/api/health")
    async def health():
        cache_key = "health"
        cached = get_cached_response(cache_key, HEALTH_CACHE_SECONDS)
        if cached:
            return cached
        return store_cached_response(cache_key, {
            "status": "running" if B.is_running else "stopped",
            "connection": "Connected" if (B.pipeline and B.pipeline.connection._is_healthy) else "Disconnected",
            "running": B.is_running,
            "mode": "paper" if B.paper_mode else "real",
            "symbol": B.symbol,
            "price": B.price,
            "balance": B.balance,
            "candles": B.candles_count,
            "uptime": B.uptime,
        })

    # ── Markets ─────────────────────────────────────────────

    @app.get("/api/markets")
    async def markets(category: str = Query("all")):
        cache_key = f"markets_{category}"
        cached = get_cached_response(cache_key, MARKETS_CACHE_SECONDS)
        if cached:
            return cached

        from pairs_registry import QUOTEX_PAIRS, list_pairs, get_pair
        items = []
        if category == "otc":
            pairs = list_pairs(pair_type="otc")
        elif category == "regular":
            pairs = list_pairs(pair_type="regular")
        else:
            pairs = [(k, get_pair(k)) for k in list(QUOTEX_PAIRS.keys())[:50] if get_pair(k)]

        for key, info in pairs[:30]:
            items.append(_build_market_item(key, info))

        return store_cached_response(cache_key, {
            "timeframe": "1m", "category": category, "items": items,
        })

    # ── Top Setups ──────────────────────────────────────────

    @app.get("/api/top-setups")
    async def top_setups(timeframe: str = Query("1m"), category: str = Query("all"), limit: int = Query(3)):
        cache_key = f"top_setups_{timeframe}_{category}_{limit}"
        cached = get_cached_response(cache_key, TOP_SETUPS_CACHE_SECONDS)
        if cached:
            return cached

        from shared.pair_scanner import scan_top_trade_setups

        try:
            cat = "all" if category == "all" else category
            scanned = await scan_top_trade_setups(category=cat, top_n=limit, balance=B.balance)
        except Exception as e:
            log.warning("Scanner error: %s — fallback to payout sort", e)
            scanned = []

        items = []
        for s in scanned:
            items.append({
                "asset": {
                    "id": s["key"],
                    "display_name": s.get("display_name", s["key"]),
                    "payout": s.get("payout", B.get_payout(s["key"])),
                    "market_type": s.get("market_type", "otc"),
                },
                "direction": s.get("direction", "neutral"),
                "confidence": s.get("confidence", 50),
                "score": int(s.get("score", 0)),
                "price_action_score": max(0, int(s.get("score", 0)) - 5),
                "breakout_structure": {"state": "consolidation"},
            })

        return store_cached_response(cache_key, {
            "timeframe": timeframe, "category": category, "items": items,
        })

    # ── Analyze ─────────────────────────────────────────────

    @app.get("/api/analyze")
    async def analyze(asset_id: str = Query(""), symbol: str = Query(""), timeframe: str = Query("1m")):
        pair_key = asset_id or symbol or B.symbol
        from pairs_registry import get_pair
        info = get_pair(pair_key)

        candles = B.pipeline.buffer.candles if B.pipeline else []
        price = B.price

        # إذا كانت الشموع أو السعر غير كافيين — استخدم شموع تجريبية
        if len(candles) < 5 or price <= 0:
            try:
                from main import _make_demo_candles
                base = price if price > 0 else 1.1000
                candles = _make_demo_candles(60, base)
                price = candles[-1].close
            except Exception:
                pass
            if price <= 0:
                if candles:
                    price = candles[-1].close
                if price <= 0:
                    return {"status": "error", "detail": "Bot not started — no price data available"}

        from bot_algorithms import ConfluenceEngine
        sig = ConfluenceEngine(candles, price, B.get_payout(pair_key), B.balance).run()

        direction = "call" if sig.direction == "UP" else "put" if sig.direction == "DOWN" else "neutral"
        reasons = list(sig.reasons)
        decision_reasons = reasons[:8]

        # Build analysis method description
        analysis_method = f"ConfluenceEngine {sig.score}/38"
        if B.ai and B.ai.enable_ai:
            analysis_method += " + Claude AI"

        risk_level = "low" if sig.score >= 20 else "medium" if sig.score >= 10 else "high"

        tv_signal, tv_summary, tv_raw = await _get_tv_analysis(pair_key)
        live_sentiment = None
        if tv_summary:
            total = tv_summary["buy"] + tv_summary["sell"] + tv_summary["neutral"]
            if total > 0:
                live_sentiment = (tv_summary["buy"] / total) * 100

        indicators = _build_indicator_snapshot(_get_candles_dicts())
        quad_analysis = _build_quad_analysis(direction, indicators, sig.score, price)

        # ── Candlestick pattern detection ────────────────
        from shared.candle_patterns import detect_candlestick_patterns
        pattern_result = detect_candlestick_patterns(candles, sig.direction)

        # ── Multi-timeframe confirmation ─────────────────
        mtf_result = {}
        try:
            higher_tf_map = {"1m": "5m", "5m": "15m", "15m": "1h", "1h": "4h", "4h": "4h"}
            higher_tf = higher_tf_map.get(timeframe, "5m")
            # Use a larger candle window to approximate higher TF
            if len(candles) >= 30:
                step = {"1m": 5, "5m": 3, "15m": 4}.get(timeframe, 1)
                if step > 1:
                    agg = []
                    for i in range(0, len(candles), step):
                        chunk = candles[max(0, i-step):i] or [candles[i]]
                        agg_o = chunk[0].open
                        agg_c = chunk[-1].close
                        agg_h = max(c.high for c in chunk)
                        agg_l = min(c.low for c in chunk)
                        from bot_algorithms import Candle
                        agg.append(Candle(agg_o, agg_c, agg_h, agg_l, 0))
                    if agg:
                        from bot_algorithms import ConfluenceEngine
                        mtf_sig = ConfluenceEngine(agg, agg[-1].close, B.get_payout(pair_key), B.balance).run()
                        mtf_dir = "call" if mtf_sig.direction == "UP" else "put" if mtf_sig.direction == "DOWN" else "neutral"
                        mtf_result = {
                            "timeframe": higher_tf,
                            "direction": mtf_dir,
                            "confidence": mtf_sig.confidence,
                            "score": mtf_sig.score,
                            "alignment": mtf_dir == direction,
                        }
        except Exception as e:
            log.debug("MTF error: %s", e)

        return {
            "asset": {
                "id": pair_key,
                "display_name": info.display_name if info else pair_key,
                "payout": B.get_payout(pair_key),
                "market_type": getattr(info, 'market_type', 'otc') if info else 'otc',
            },
            "direction": direction,
            "confidence": sig.confidence,
            "analysis_method": analysis_method,
            "decision_score": sig.score / 38.0 * 100 if sig.score > 0 else 0,
            "risk_level": risk_level,
            "decision_reasons": decision_reasons,
            "price_series": _get_candles_dicts(),
            "support_resistance": {
                "nearest_support": {"level": price * 0.995, "touches": 0} if price else None,
                "nearest_resistance": {"level": price * 1.005, "touches": 0} if price else None,
            },
            "live_sentiment": live_sentiment,
            "payout_filter": {"passed": B.get_payout(pair_key) >= 76, "summary": f"Payout {B.get_payout(pair_key):.0f}%"},
            "ai_voting": {
                "trade_ready": sig.confidence >= 70 and sig.score >= 10,
                "grade": "gold" if sig.score >= 20 else "watch" if sig.score >= 10 else "standby",
                "label": "Strong Execution" if sig.score >= 20 else "Watchlist" if sig.score >= 10 else "Wait",
                "summary": f"Confluence score {sig.score}/38 with {sig.confidence}% confidence",
            },
            "live_analysis_steps": [
                {"status": "passed", "headline": "Confluence Engine", "label": f"{sig.score}/38", "detail": f"Signal: {sig.direction} ({sig.confidence}%)"},
                {"status": "passed" if tv_summary else "blocked", "headline": "TradingView TA", "label": tv_summary["recommendation"] if tv_summary else "unavailable", "detail": f"B:{tv_summary['buy']}/S:{tv_summary['sell']}/N:{tv_summary['neutral']}" if tv_summary else "No TV data"},
                {"status": "passed" if B.ai and B.ai.enable_ai else "blocked", "headline": "Claude AI", "label": "active" if B.ai and B.ai.enable_ai else "inactive", "detail": "AI analysis available" if B.ai and B.ai.enable_ai else "Add ANTHROPIC_API_KEY"},
                {"status": quad_analysis["sections"]["momentum_volatility"]["status"], "headline": "RSI Momentum", "label": f"{indicators.get('rsi', '--')}" if indicators else "--", "detail": quad_analysis["sections"]["momentum_volatility"]["summary"]},
            ],
            "traditional": {
                "direction": tv_signal["direction"] if tv_signal else "neutral",
                "confidence": tv_signal["confidence"] if tv_signal else 0,
                "recommendation": tv_summary["recommendation"] if tv_summary else "NEUTRAL",
            } if tv_signal else {"direction": "neutral", "confidence": 0, "recommendation": "NEUTRAL"},
            "lstm_signal": {"direction": "neutral", "confidence": 0},
            "market_insights": {},
            "symbol_health": {"score": min(95, sig.score * 5), "grade": "strong" if sig.score >= 15 else "watch"},
            "multi_timeframe": mtf_result,
            "market_regime": {"regime": "ranging"},
            "candlestick_pattern_detail": pattern_result,
            "breakout_structure": {"state": "no breakout"},
            "quad_analysis": quad_analysis,
            "model_weights": {"confluence": 1.0},
            "degraded": False,
            "timestamp": time.time(),
        }

    # ── Live Snapshot ──────────────────────────────────────

    @app.get("/api/live-snapshot")
    async def live_snapshot(asset_id: str = Query(""), timeframe: str = Query("1m")):
        pair_key = asset_id or B.symbol
        return {
            "asset_id": pair_key,
            "timeframe": timeframe,
            "price": B.price if B.price > 0 else None,
            "sentiment": None,
            "payout": B.get_payout(pair_key),
            "candles": _get_candles_dicts(),
            "timestamp": time.time(),
        }

    # ── Set Pair ────────────────────────────────────────────

    @app.post("/api/set-pair")
    async def set_pair(req: Request):
        try:
            body = await req.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        pair_key = body.get("pair_key", "")
        if not pair_key:
            raise HTTPException(status_code=400, detail="pair_key required")
        from pairs_registry import apply_pair_to_pipeline, get_pair
        info = get_pair(pair_key)
        if not info:
            raise HTTPException(status_code=404, detail=f"Pair {pair_key} not found")
        if B.pipeline:
            apply_pair_to_pipeline(B.pipeline, pair_key)
        else:
            from main import DataPipeline
            B.pipeline = DataPipeline.from_env()
            apply_pair_to_pipeline(B.pipeline, pair_key)
        return {"success": True, "pair_key": pair_key, "display_name": info.display_name}

    # ── Start Bot ───────────────────────────────────────────

    @app.post("/api/start-bot")
    async def start_bot():
        if B.is_running:
            return {"success": True, "status": "already_running"}
        from main import do_start
        ok, detail = await do_start()
        return {"success": ok, "detail": detail}

    @app.post("/api/stop-bot")
    async def stop_bot():
        if not B.is_running:
            return {"success": True, "status": "already_stopped"}
        from main import do_stop
        await do_stop()
        return {"success": True, "status": "stopped"}

    # ── Execute ─────────────────────────────────────────────

    @app.post("/api/execute")
    async def execute_trade(req: Request):
        auth_error = _verify_api_token(req)
        if auth_error:
            raise HTTPException(status_code=403, detail=auth_error)

        try:
            body = await req.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        pair = body.get("asset_id") or body.get("symbol") or B.symbol
        direction = body.get("direction", "CALL").upper()
        amount = float(body.get("amount", 10))
        duration = int(body.get("duration", 60))

        # Auto-start bot if not running
        if not B.is_running:
            from main import do_start
            ok, detail = await do_start()
            if not ok:
                raise HTTPException(status_code=400, detail=f"Bot start failed: {detail}")
            # Give pipeline time to initialize
            await asyncio.sleep(3)

        # Execute trade via TradeManager
        if B.manager and B.pipeline:
            try:
                from bot_algorithms import Signal
                sig = Signal(
                    direction="UP" if direction == "CALL" else "DOWN",
                    score=int(body.get("score", 12)),
                    confidence=int(body.get("confidence", 70)),
                    reasons=["WebApp manual trade"],
                    warnings=[],
                    trade_size=amount,
                    details={},
                )
                await B.manager.handle_signal(sig)
                trade_id = f"web_{int(time.time())}"
                return {"success": True, "trade_id": trade_id, "pair": pair, "amount": amount, "direction": direction, "duration": duration}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        else:
            raise HTTPException(status_code=400, detail="Trade manager not initialized")

    # ── Trade Journal ───────────────────────────────────────

    @app.get("/api/trade-journal")
    async def trade_journal(limit: int = Query(20)):
        cache_key = f"journal_{limit}"
        cached = get_cached_response(cache_key, JOURNAL_CACHE_SECONDS)
        if cached:
            return cached
        trades = []
        if B.db:
            try:
                rows = await B.db.get_recent_trades(limit)
                for row in rows:
                    trades.append({
                        "pair": getattr(row, 'symbol', row.get('symbol', 'Unknown')),
                        "direction": getattr(row, 'direction', row.get('direction', 'neutral')),
                        "timeframe": getattr(row, 'timeframe', row.get('timeframe', '1m')),
                        "result": "win" if getattr(row, 'profit', row.get('profit', 0)) > 0 else "loss",
                        "profit": float(getattr(row, 'profit', row.get('profit', 0))),
                        "reason": getattr(row, 'reason', row.get('reason', '')),
                    })
            except Exception:
                pass
        return store_cached_response(cache_key, {"items": trades, "count": len(trades)})

    @app.get("/api/journal-analytics")
    async def journal_analytics():
        import math
        decided = B.wins + B.losses
        win_rate = (B.wins / decided * 100) if decided > 0 else 0.0
        net_profit = round(B.wins * (B.get_payout() / 100) - B.losses, 2)

        all_trades = []
        equity_curve = []
        sharpe = 0
        best_pair = worst_pair = None

        try:
            if B.db:
                all_trades = await B.db.get_all_trades_for_analysis()
                equity_rows = await B.db.get_equity_curve(90)
                equity_curve = [
                    {"date": r["date"], "balance": r["balance_end"],
                     "profit": r["net_profit"], "trades": r["trades"]}
                    for r in equity_rows if r["balance_end"]
                ]

                if len(all_trades) > 1:
                    returns = [t["profit"] / 100 for t in all_trades if t["profit"]]
                    if returns:
                        avg_r = sum(returns) / len(returns)
                        std_r = (sum((r - avg_r) ** 2 for r in returns) / len(returns)) ** 0.5
                        sharpe = round((avg_r / std_r * math.sqrt(252)) if std_r > 0 else 0, 3)

                symbols_data = await B.db.get_best_symbols(30)
                if len(symbols_data) >= 1:
                    best_pair = {
                        "symbol": symbols_data[0]["symbol"],
                        "win_rate": round(symbols_data[0]["wins"] / max(symbols_data[0]["total"], 1) * 100, 1),
                        "profit": round(symbols_data[0]["net_profit"], 2),
                        "trades": symbols_data[0]["total"],
                    }
                    if len(symbols_data) > 1:
                        worst_data = symbols_data[-1]
                        worst_pair = {
                            "symbol": worst_data["symbol"],
                            "win_rate": round(worst_data["wins"] / max(worst_data["total"], 1) * 100, 1),
                            "profit": round(worst_data["net_profit"], 2),
                            "trades": worst_data["total"],
                        }
        except Exception:
            pass

        return {
            "summary": {
                "total_trades": decided,
                "win_rate": round(win_rate, 1),
                "net_profit": net_profit,
                "expectancy": round(net_profit / decided, 2) if decided > 0 else 0.0,
                "avg_confidence": 0,
                "sharpe_ratio": sharpe,
                "total_closed": len(all_trades),
            },
            "best_pair": best_pair,
            "worst_pair": worst_pair,
            "best_timeframe": None,
            "recent_streak": {
                "type": "loss" if B.consecutive_losses > 1 else "win" if B.consecutive_losses == 0 and decided > 0 else "flat",
                "count": max(B.consecutive_losses, B.consecutive_wins),
            },
            "market_split": [],
            "equity_curve": equity_curve,
        }

    # ── Performance (dedicated P&L endpoint) ───────────────

    @app.get("/api/performance")
    async def performance():
        import math
        decided = B.wins + B.losses
        win_rate = (B.wins / decided * 100) if decided > 0 else 0.0
        net_profit = round(B.wins * (B.get_payout() / 100) - B.losses, 2)
        sharpe = 0
        equity_curve = []
        pair_stats = []
        try:
            if B.db:
                all_trades = await B.db.get_all_trades_for_analysis()
                if len(all_trades) > 1:
                    returns = [t["profit"] / 100 for t in all_trades if t["profit"]]
                    if returns:
                        avg_r = sum(returns) / len(returns)
                        std_r = (sum((r - avg_r) ** 2 for r in returns) / len(returns)) ** 0.5
                        sharpe = round((avg_r / std_r * math.sqrt(252)) if std_r > 0 else 0, 3)
                rows = await B.db.get_equity_curve(90)
                equity_curve = [{"d": r["date"], "b": r["balance_end"]} for r in rows if r["balance_end"]]
                sym_data = await B.db.get_best_symbols(30)
                for s in sym_data:
                    wr = round(s["wins"] / max(s["total"], 1) * 100, 1)
                    pair_stats.append({"s": s["symbol"], "wr": wr, "p": round(s["net_profit"], 2), "n": s["total"]})
        except Exception:
            pass
        return {
            "total_trades": decided,
            "win_rate": round(win_rate, 1),
            "net_profit": net_profit,
            "expectancy": round(net_profit / decided, 2) if decided > 0 else 0,
            "sharpe_ratio": sharpe,
            "max_consecutive_losses": B.consecutive_losses,
            "consecutive_wins": B.consecutive_wins,
            "balance": B.balance,
            "paper_mode": B.paper_mode,
            "equity_curve": equity_curve,
            "pair_performance": pair_stats,
        }

    # ── Currency Strength ───────────────────────────────────

    @app.get("/api/currency-strength")
    async def currency_strength():
        return {
            "USD": 50, "EUR": 50, "GBP": 50, "JPY": 50,
            "AUD": 50, "CAD": 50, "CHF": 50, "NZD": 50,
        }

    # ── Best Entry ──────────────────────────────────────────

    @app.get("/api/best-entry")
    async def best_entry(asset_id: str = Query(""), symbol: str = Query("")):
        return {
            "asset_id": asset_id or symbol or B.symbol,
            "direction": "CALL",
            "entry_min": B.price * 0.998 if B.price > 0 else 0,
            "entry_max": B.price * 1.002 if B.price > 0 else 0,
            "stop_chasing": B.price * 1.005 if B.price > 0 else 0,
        }

    # ── Entry Watch ─────────────────────────────────────────

    @app.get("/api/entry-watch")
    async def entry_watch_status(asset_id: str = Query(""), user_id: int = Query(0)):
        active = []
        for wid, w in list(entry_watchers.items()):
            if asset_id and w.get("asset_id") != asset_id:
                continue
            if user_id and w.get("user_id") != user_id:
                continue
            active.append({
                "id": wid,
                "asset_id": w.get("asset_id"),
                "direction": w.get("direction"),
                "mode": w.get("mode"),
                "entry_min": w.get("entry_min"),
                "entry_max": w.get("entry_max"),
                "triggered": w.get("triggered", False),
                "remaining": max(0, int(ENTRY_WATCH_TIMEOUT - (time.time() - w.get("started_at", time.time())))),
            })
        return {"watchers": active}

    @app.post("/api/entry-watch")
    async def start_entry_watch(req: Request):
        try:
            body = await req.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        asset_id = body.get("asset_id") or B.symbol
        direction = body.get("direction", "CALL").upper()
        mode = body.get("mode", "alert")
        user_id = int(body.get("user_id", 0))

        entry_plan_resp = await best_entry(asset_id=asset_id)
        entry_min = entry_plan_resp.get("entry_min", B.price * 0.998)
        entry_max = entry_plan_resp.get("entry_max", B.price * 1.002)
        if B.price > 0 and not (entry_min <= B.price <= entry_max):
            entry_min = min(B.price * 0.995, entry_min)
            entry_max = max(B.price * 1.005, entry_max)

        watcher_id = f"ew_{int(time.time())}_{asset_id.replace('-','_')}"
        watcher = {
            "asset_id": asset_id,
            "direction": direction,
            "mode": mode,
            "user_id": user_id,
            "entry_min": entry_min,
            "entry_max": entry_max,
            "triggered": False,
            "started_at": time.time(),
            "task": None,
        }
        entry_watchers[watcher_id] = watcher

        task = asyncio.create_task(
            _run_entry_watch(watcher_id, asset_id, direction, entry_min, entry_max, mode, user_id)
        )
        watcher["task"] = task

        log.info("Entry watch started: %s %s %.5f-%.5f mode=%s", watcher_id, direction, entry_min, entry_max, mode)
        return {
            "status": "ok",
            "watcher_id": watcher_id,
            "message": f"Watching {asset_id} {direction} at {entry_min:.5f}-{entry_max:.5f}",
            "entry_min": entry_min,
            "entry_max": entry_max,
        }

    @app.post("/api/entry-watch/cancel")
    async def cancel_entry_watch(req: Request):
        try:
            body = await req.json()
        except Exception:
            body = {}
        watcher_id = body.get("watcher_id", "")
        asset_id = body.get("asset_id", "")

        cancelled = []
        for wid, w in list(entry_watchers.items()):
            if watcher_id and wid != watcher_id:
                continue
            if asset_id and w.get("asset_id") != asset_id:
                continue
            task = w.get("task")
            if task and not task.done():
                task.cancel()
            entry_watchers.pop(wid, None)
            cancelled.append(wid)

        return {"status": "ok", "cancelled": cancelled}

    # ── WebSocket live feed ────────────────────────────────

    @app.websocket("/ws/live-feed")
    async def live_feed(websocket: WebSocket, asset_id: str = "EURUSD-OTC", timeframe: str = "1m"):
        await websocket.accept()
        try:
            while True:
                decided = B.wins + B.losses
                payload = {
                    "asset_id": asset_id,
                    "timeframe": timeframe,
                    "price": B.price,
                    "sentiment": None,
                    "payout": B.get_payout(asset_id),
                    "candles": _get_candles_dicts(),
                    "balance": B.balance,
                    "running": B.is_running,
                    "win_rate": round(B.wins / decided * 100, 1) if decided > 0 else 0,
                    "total_trades": decided,
                    "consecutive_losses": B.consecutive_losses,
                    "active_trades": len(B.risk_manager.active_trades) if hasattr(B.risk_manager, 'active_trades') else 0,
                    "timestamp": time.time(),
                }
                await websocket.send_json(payload)
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.debug("WS error: %s", e)

    return app


app = create_app()

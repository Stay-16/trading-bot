from __future__ import annotations

import logging
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import trading_bot as bot


BASE_DIR = Path(__file__).parent
WEBAPP_INDEX = BASE_DIR / "webapp_index.html"
WEBAPP_JS = BASE_DIR / "webapp_app.js"
WEBAPP_CSS = BASE_DIR / "webapp_styles.css"
connection_lock = asyncio.Lock()


def serialize_live_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["callback_id"],
        "pair_key": entry["pair_key"],
        "display_name": entry["display_name"],
        "market_type": entry["market_type"],
        "payout": entry.get("payout"),
        "quotex_symbol": entry["quotex_symbol"],
        "symbol": entry["pairdict"]["symbol"],
    }


class ExecuteTradeRequest(BaseModel):
    asset_id: str
    timeframe: str
    direction: str
    user_id: int = 0
    confidence: int | None = None


async def ensure_quotex_connection() -> None:
    async with connection_lock:
        client = bot.quotex_client
        if client:
            try:
                await client.get_balance()
                return
            except Exception as exc:
                logging.warning("Detected stale Quotex session. Reconnecting: %s", exc)
                bot.quotex_client = None

        try:
            await bot.connect_to_quotex_with_retry(max_retries=5)
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

    enriched_entry = await bot.enrich_live_entry_with_payout(dict(entry))
    cached_result = bot.get_cached_analysis_result(entry["pairdict"], timeframe)
    use_live_only = (
        entry.get("market_type") == "otc"
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
            market_context.setdefault("lstm_signal", {"direction": direction, "confidence": confidence, "method": "live_stream"})
            degraded = True
            degraded_reason = "Using live stream fallback because OTC/rate-limited assets cannot rely on TradingView."
        except Exception as exc:
            logging.warning("WebApp live-stream fallback failed for %s: %s", entry["display_name"], exc)
            traditional = {"direction": "neutral", "confidence": 0, "recommendation": "UNAVAILABLE"}
            ai_prediction = {"direction": "neutral", "confidence": 0, "method": "live_unavailable", "risk_level": "high", "decision_score": 0}
            market_context = {
                "degraded": True,
                "degraded_reason": f"Live stream analysis is currently unavailable: {exc}",
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
            market_context = outcome.market_context
            degraded = False
            degraded_reason = ""
        except Exception as exc:
            logging.warning("WebApp analysis fell back for %s: %s", entry["display_name"], exc)
            if cached_result:
                traditional = cached_result.get("traditional_signal", {"direction": "neutral", "confidence": 50, "recommendation": "NEUTRAL"})
                ai_prediction = cached_result.get("ai_prediction", {"direction": cached_result.get("direction", "neutral"), "confidence": cached_result.get("confidence", 50), "method": "cached_analysis"})
                market_context = dict(cached_result.get("market_context", {}))
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
    try:
        live_snapshot = await asyncio.wait_for(
            bot.get_live_market_snapshot(
                entry["pairdict"]["quotex_symbol"],
                bot.TIMEFRAMES[timeframe]["quotex"],
            ),
            timeout=6,
        )
    except Exception as exc:
        logging.warning("Live snapshot failed for %s: %s", entry["display_name"], exc)
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

    return {
        "asset": serialize_live_entry(enriched_entry),
        "timeframe": timeframe,
        "direction": ai_prediction.get("direction", "neutral"),
        "confidence": ai_prediction.get("confidence", 0),
        "risk_level": ai_prediction.get("risk_level", "medium"),
        "decision_score": ai_prediction.get("decision_score", 0),
        "analysis_method": ai_prediction.get("method", "unknown"),
        "models_used": ai_prediction.get("models_used", []),
        "model_weights": bot.advanced_ai_system.model_weights,
        "traditional": traditional,
        "lstm_signal": market_context.get("lstm_signal", {}),
        "market_context": market_context,
        "technical_summary": bot.get_advanced_technical_details(indicators) if indicators else "No live technical snapshot available.",
        "market_insights": bot.advanced_ai_system.get_market_insights(entry["pairdict"]["symbol"], timeframe),
        "performance": bot.advanced_ai_system.get_performance_stats(),
        "decision_reasons": market_context.get("decision_reasons", []),
        "candle_pattern": market_context.get("candle_pattern", "N/A"),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "price_series": price_series,
        "live_price": live_snapshot.get("price"),
        "live_sentiment": live_sentiment,
        "live_payout": live_payout,
    }


def create_app() -> FastAPI:
    app = FastAPI(title=bot.settings.webapp.title)
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

    @app.get("/webapp_bundle_20260327f.js")
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

    @app.get("/webapp_bundle_20260327f.css")
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

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        connection = await bot.check_quotex_connection()
        balance = await bot.get_current_balance()
        performance = bot.advanced_ai_system.get_performance_stats()
        open_trades = len([trade for trade in bot.active_trades.values() if trade.get("status") == "pending"])
        return {
            "title": bot.settings.webapp.title,
            "connection": connection,
            "balance": balance,
            "open_trades": open_trades,
            "history_size": len(bot.trade_history),
            "performance": performance,
            "webapp_url": bot.settings.webapp.public_url,
        }

    @app.get("/api/markets")
    async def markets(category: str = Query("all")) -> dict[str, Any]:
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
        return {
            "category": category,
            "counts": counts,
            "items": [serialize_live_entry(entry) for entry in entries],
        }

    @app.get("/api/top-setups")
    async def top_setups(
        timeframe: str = Query("1m"),
        category: str = Query("all"),
        limit: int = Query(3, ge=1, le=6),
    ) -> dict[str, Any]:
        await ensure_quotex_connection()
        try:
            results = await asyncio.wait_for(
                bot.scan_top_trade_setups(timeframe=timeframe, category=category, top_n=limit),
                timeout=15,
            )
        except Exception as exc:
            logging.warning("Top setups timed out or failed for %s/%s: %s", category, timeframe, exc)
            results = []
        return {
            "timeframe": timeframe,
            "category": category,
            "items": [
                {
                    "asset": serialize_live_entry(result["entry"]),
                    "direction": result["direction"],
                    "confidence": result["confidence"],
                    "score": result["score"],
                    "trend_condition": result["market_context"].get("trend_condition", "normal"),
                    "market_condition": result["market_context"].get("market_condition", "normal"),
                }
                for result in results
            ],
        }

    @app.get("/api/analyze")
    async def analyze(
        asset_id: str | None = Query(None),
        symbol: str | None = Query(None),
        timeframe: str = Query("1m"),
    ) -> dict[str, Any]:
        await ensure_quotex_connection()
        entry = await resolve_entry(asset_id=asset_id, symbol=symbol)
        return await build_analysis_payload(entry, timeframe)

    @app.get("/api/live-snapshot")
    async def live_snapshot(
        asset_id: str = Query(...),
        timeframe: str = Query("1m"),
    ) -> dict[str, Any]:
        await ensure_quotex_connection()
        entry = await resolve_entry(asset_id=asset_id)
        if timeframe not in bot.TIMEFRAMES:
            raise HTTPException(status_code=400, detail="Unsupported timeframe.")

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

        return {
            "asset_id": asset_id,
            "timeframe": timeframe,
            "price": snapshot.get("price"),
            "sentiment": snapshot.get("sentiment"),
            "payout": snapshot.get("payout"),
            "candles": snapshot.get("candles", [])[-120:],
            "timestamp": snapshot.get("timestamp"),
        }

    @app.post("/api/execute")
    async def execute_trade(request: ExecuteTradeRequest) -> dict[str, Any]:
        await ensure_quotex_connection()
        entry = await resolve_entry(asset_id=request.asset_id)
        if request.timeframe not in bot.TIMEFRAMES:
            raise HTTPException(status_code=400, detail="Unsupported timeframe.")
        if request.direction not in {"call", "put"}:
            raise HTTPException(status_code=400, detail="Direction must be call or put.")

        confidence = request.confidence
        if confidence is None:
            cached_result = bot.get_cached_analysis_result(entry["pairdict"], request.timeframe)
            confidence = cached_result.get("confidence", bot.settings.risk.min_confidence_score) if cached_result else bot.settings.risk.min_confidence_score

        orchestrator = bot.get_trading_orchestrator()
        execution_plan = await orchestrator.prepare_execution(
            request.user_id,
            entry["pairdict"],
            request.timeframe,
            int(confidence),
        )
        if not execution_plan.allowed:
            raise HTTPException(status_code=400, detail=execution_plan.reason)

        execution_result = await orchestrator.execute_trade(
            request.direction,
            entry.get("quotex_api_symbol") or bot.quotex_symbol_to_api_symbol(entry["pairdict"]["quotex_symbol"]),
            execution_plan.amount,
            bot.TIMEFRAMES[request.timeframe]["quotex"],
        )
        if not execution_result.success:
            raise HTTPException(status_code=400, detail=execution_result.reason)

        trade_id = execution_result.trade_id
        if trade_id in bot.active_trades:
            bot.active_trades[trade_id]["user_id"] = request.user_id
            bot.active_trades[trade_id]["analysis_timeframe"] = request.timeframe
            bot.active_trades[trade_id]["pair_name"] = entry["display_name"]

        return {
            "success": True,
            "trade_id": trade_id,
            "pair": entry["display_name"],
            "amount": execution_plan.amount,
            "direction": request.direction,
            "duration": bot.TIMEFRAMES[request.timeframe]["quotex"],
        }

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
                await asyncio.sleep(1.25)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json({"error": str(exc)})
            await websocket.close()

    return app


app = create_app()

import asyncio
from typing import Any, Callable

import numpy as np


def _find_last_analysis(history: list[dict[str, Any]], pair: str, timeframe: str) -> dict[str, Any] | None:
    for hist_item in history:
        if hist_item.get("pair") == pair and hist_item.get("tf") == timeframe:
            return hist_item
    return None


async def handle_execution_callbacks(
    *,
    data: str,
    context: Any,
    user_id: int,
    user_data: dict[int, dict[str, Any]],
    pairs: dict[str, Any],
    live_pair_registry: dict[str, Any],
    live_update_tasks: dict[int, Any],
    higher_tf: dict[str, str],
    timeframes: dict[str, Any],
    settings: Any,
    cleanup_stale_active_trades: Callable[..., Any],
    get_trading_orchestrator: Callable[[], Any],
    get_market_context_from_cache: Callable[..., Any],
    monitor_trade_with_advanced_ai: Callable[..., Any],
    advanced_ai_analysis_layered: Callable[..., Any],
    stream_live_signal_updates: Callable[..., Any],
    trade_state_service_getter: Callable[[], Any],
) -> bool:
    if data.startswith("liveid_"):
        _, pair_id, timeframe = data.split("_", 2)
        entry = live_pair_registry.get(pair_id)
        if not entry:
            await context.bot.send_message(chat_id=user_id, text="⚠️ The live asset cache expired. Please select the asset again.")
            return True
        existing_task = live_update_tasks.get(user_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()
        live_update_tasks[user_id] = asyncio.create_task(
            stream_live_signal_updates(context, user_id, entry["display_name"], entry["pairdict"], timeframe)
        )
        return True

    if data.startswith("live_"):
        _, pair, timeframe = data.split("_", 2)
        pairdict = pairs[pair]
        pair_label = pair.replace("_otc", " OTC")
        existing_task = live_update_tasks.get(user_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()
        live_update_tasks[user_id] = asyncio.create_task(
            stream_live_signal_updates(context, user_id, pair_label, pairdict, timeframe)
        )
        return True

    if data == "stop_live_stream":
        existing_task = live_update_tasks.get(user_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()
            await context.bot.send_message(chat_id=user_id, text="⏹️ <b>Live signal stream stopped manually.</b>", parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=user_id, text="📭 No live stream is running right now.", parse_mode="HTML")
        return True

    if data.startswith("deepid_"):
        _, pair_id, timeframe = data.split("_", 2)
        entry = live_pair_registry.get(pair_id)
        if not entry:
            await context.bot.send_message(chat_id=user_id, text="⚠️ The live asset cache expired. Please reopen the market board.")
            return True
        await context.bot.send_message(chat_id=user_id, text="🔍 Running higher-timeframe confirmation...")
        resolved_higher_tf = higher_tf.get(timeframe, timeframe)
        higher_message, _, _, _, _ = await advanced_ai_analysis_layered(entry["pairdict"], resolved_higher_tf)
        analysis_msg = (
            f"📊 <b>Deep Analysis</b>\n"
            f"💰 <b>{entry['display_name']} - Higher timeframe ({resolved_higher_tf})</b>\n\n"
            f"{higher_message}\n\n"
            f"💡 <b>Summary:</b>\n"
            f"• Current timeframe: {timeframe}\n"
            f"• Higher timeframe: {resolved_higher_tf}\n"
            f"• Combined view: short-term setup with broader trend confirmation"
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=analysis_msg,
            parse_mode="HTML",
        )
        return True

    if data.startswith("deep_analysis_"):
        _, pair, timeframe = data.split("_", 2)
        pairdict = pairs[pair]
        await context.bot.send_message(chat_id=user_id, text="🔍 Running higher-timeframe confirmation...")
        resolved_higher_tf = higher_tf.get(timeframe, timeframe)
        higher_message, _, _, _, _ = await advanced_ai_analysis_layered(pairdict, resolved_higher_tf)
        analysis_msg = (
            f"📊 <b>Deep Analysis</b>\n"
            f"💰 <b>{pair} - Higher timeframe ({resolved_higher_tf})</b>\n\n"
            f"{higher_message}\n\n"
            f"💡 <b>Summary:</b>\n"
            f"• Current timeframe: {timeframe}\n"
            f"• Higher timeframe: {resolved_higher_tf}\n"
            f"• Combined view: short-term setup with broader trend confirmation"
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=analysis_msg,
            parse_mode="HTML",
        )
        return True

    if data.startswith("executeid_"):
        _, pair_id, timeframe, direction = data.split("_", 3)
        entry = live_pair_registry.get(pair_id)
        if not entry:
            await context.bot.send_message(chat_id=user_id, text="⚠️ The live asset cache expired. Please select the asset again.")
            return True
        pair = entry["display_name"]
        pairdict = entry["pairdict"]
        await _execute_trade_flow(
            context=context,
            user_id=user_id,
            user_data=user_data,
            pair=pair,
            pairdict=pairdict,
            timeframe=timeframe,
            direction=direction,
            timeframes=timeframes,
            settings=settings,
            cleanup_stale_active_trades=cleanup_stale_active_trades,
            get_trading_orchestrator=get_trading_orchestrator,
            get_market_context_from_cache=get_market_context_from_cache,
            monitor_trade_with_advanced_ai=monitor_trade_with_advanced_ai,
            trade_state_service_getter=trade_state_service_getter,
        )
        return True

    if data.startswith("execute_"):
        _, pair, timeframe, direction = data.split("_")
        pairdict = pairs[pair]
        await _execute_trade_flow(
            context=context,
            user_id=user_id,
            user_data=user_data,
            pair=pair,
            pairdict=pairdict,
            timeframe=timeframe,
            direction=direction,
            timeframes=timeframes,
            settings=settings,
            cleanup_stale_active_trades=cleanup_stale_active_trades,
            get_trading_orchestrator=get_trading_orchestrator,
            get_market_context_from_cache=get_market_context_from_cache,
            monitor_trade_with_advanced_ai=monitor_trade_with_advanced_ai,
            trade_state_service_getter=trade_state_service_getter,
        )
        return True

    return False


async def _execute_trade_flow(
    *,
    context: Any,
    user_id: int,
    user_data: dict[int, dict[str, Any]],
    pair: str,
    pairdict: dict[str, Any],
    timeframe: str,
    direction: str,
    timeframes: dict[str, Any],
    settings: Any,
    cleanup_stale_active_trades: Callable[..., Any],
    get_trading_orchestrator: Callable[[], Any],
    get_market_context_from_cache: Callable[..., Any],
    monitor_trade_with_advanced_ai: Callable[..., Any],
    trade_state_service_getter: Callable[[], Any],
) -> None:
    cleanup_stale_active_trades(user_id=user_id, pair_label=pair, asset=pairdict["quotex_symbol"])
    await context.bot.send_message(chat_id=user_id, text="🔄 Preparing trade execution...")

    last_analysis = _find_last_analysis(user_data[user_id].get("history", []), pair, timeframe)
    confidence_value = last_analysis.get("confidence", settings.risk.min_confidence_score) if last_analysis else settings.risk.min_confidence_score

    orchestrator = get_trading_orchestrator()
    execution_plan = await orchestrator.prepare_execution(user_id, pairdict, timeframe, confidence_value)
    if not execution_plan.allowed:
        await context.bot.send_message(chat_id=user_id, text=f"⛔ {execution_plan.reason}")
        return

    amount = execution_plan.amount
    execution_result = await orchestrator.execute_trade(direction, pairdict["quotex_symbol"], amount, timeframes[timeframe]["quotex"])
    success = execution_result.success
    result = execution_result.trade_id if execution_result.success else execution_result.reason
    if not success:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Trade execution failed: {result}")
        return

    trade_state_service = trade_state_service_getter()
    trade_state_service.attach_trade_context(
        result,
        user_id=user_id,
        analysis_timeframe=timeframe,
        pair_name=pair,
    )

    trade_data = {
        "direction": direction,
        "confidence": last_analysis.get("confidence", 75) if last_analysis else 75,
        "pair": pair,
        "timeframe": timeframe,
        "amount": amount,
        "features": last_analysis.get("features", np.array([])) if last_analysis else np.array([]),
        "price_sequence": last_analysis.get("price_sequence", []) if last_analysis else [],
    }
    market_context = await get_market_context_from_cache(pairdict, timeframe)
    asyncio.create_task(
        monitor_trade_with_advanced_ai(
            result,
            user_id,
            context,
            trade_data,
            last_analysis.get("features", np.array([])) if last_analysis else np.array([]),
            market_context,
        )
    )
    trade_msg = (
        f"✅ <b>Trade Opened Successfully</b>\n\n"
        f"• Pair: {pair}\n"
        f"• Direction: {direction.upper()}\n"
        f"• Amount: ${amount}\n"
        f"• Duration: {timeframes[timeframe]['quotex']} seconds\n"
        f"• Trade ID: <code>{result}</code>\n"
        f"• Confidence: {trade_data['confidence']}%\n"
    )
    await context.bot.send_message(chat_id=user_id, text=trade_msg, parse_mode="HTML")

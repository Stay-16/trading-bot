import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


async def handle_analysis_callbacks(
    *,
    data: str,
    query: Any,
    context: Any,
    user_id: int,
    user_data: dict[int, dict[str, Any]],
    timeframes: dict[str, Any],
    pairs: dict[str, Any],
    live_pair_registry: dict[str, Any],
    calculate_seconds_to_new_candle: Callable[[int], int],
    scan_top_trade_setups: Callable[..., Any],
    smart_trading_execution: Callable[..., Any],
) -> bool:
    if data.startswith("scanbest_"):
        timeframe = data.split("_", 1)[1]
        user_data[user_id]["preferred_timeframe"] = timeframe
        timeframe_minutes = 1 if timeframe == "1m" else 5 if timeframe == "5m" else 15 if timeframe == "15m" else 60 if timeframe == "1h" else 240
        seconds_to_fresh_candle = calculate_seconds_to_new_candle(timeframe_minutes)
        scan_started_at = datetime.now()
        signal_basis = "current candle"
        target_candle_time = scan_started_at
        await query.edit_message_text(
            (
                f"🔍 <b>Scanning Live Markets</b>\n\n"
                f"• Timeframe: <b>{timeframe}</b>\n"
                f"• Scope: <b>all currently open Quotex assets</b>\n"
                f"• Target: <b>fresh / next candle setups</b>\n"
                f"• Ranking: confidence + payout + trend freshness\n"
                f"• Next candle in: <b>{seconds_to_fresh_candle}s</b>\n\n"
                f"<i>Please wait while the scanner reviews the market...</i>"
            ),
            parse_mode="HTML",
        )
        if 3 < seconds_to_fresh_candle <= 18:
            signal_basis = "next candle"
            target_candle_time = scan_started_at + timedelta(seconds=seconds_to_fresh_candle)
            await asyncio.sleep(seconds_to_fresh_candle)
        else:
            signal_basis = "current candle"
            target_candle_time = datetime.now()
        results = await scan_top_trade_setups(timeframe=timeframe, category="all", top_n=3)
        if not results:
            empty_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Retry Scan", callback_data=f"scanbest_{timeframe}")],
                [InlineKeyboardButton("🟢 Markets", callback_data="market_live")],
                [InlineKeyboardButton("🔙 Main Desk", callback_data="back_to_main")],
            ])
            await query.edit_message_text(
                "⚠️ <b>No tradeable high-conviction setups were found right now.</b>\n\nTry another timeframe or rescan in a moment.",
                parse_mode="HTML",
                reply_markup=empty_keyboard,
            )
            return True

        lines = [
            "🏆 <b>Top 3 Live Setups</b>",
            "",
            f"• Timeframe: <b>{timeframe}</b>",
            "• Ranked from the currently open Quotex board",
            "• Focus: <b>fresh candle timing</b>",
            f"• Signal basis: <b>{signal_basis}</b>",
            f"• Target candle time: <b>{target_candle_time.strftime('%H:%M:%S')}</b>",
            "",
        ]
        for index, result in enumerate(results, start=1):
            entry = result["entry"]
            direction = "CALL" if result["direction"] == "call" else "PUT"
            payout_text = f"{entry['payout']:.0f}%" if entry.get("payout") else "n/a"
            trend_hint = result["market_context"].get("trend_condition", "normal")
            lines.extend([
                f"{index}. <b>{entry['display_name']}</b>",
                f"   • Direction: {direction}",
                f"   • Confidence: {result['confidence']}%",
                f"   • Payout: {payout_text}",
                f"   • Trend context: {trend_hint}",
                "",
            ])
        keyboard = []
        for index, result in enumerate(results, start=1):
            entry = result["entry"]
            keyboard.append([
                InlineKeyboardButton(
                    f"Open #{index}: {entry['display_name']}",
                    callback_data=f"setpairid_{entry['callback_id']}",
                )
            ])
        keyboard.append([
            InlineKeyboardButton("🔄 Rescan", callback_data=f"scanbest_{timeframe}"),
            InlineKeyboardButton("🟢 Markets", callback_data="market_live"),
        ])
        keyboard.append([InlineKeyboardButton("🔙 Main Desk", callback_data="back_to_main")])
        await query.edit_message_text(
            "\n".join(lines).strip(),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return True

    if data.startswith("setpairid_"):
        pair_id = data.split("_", 1)[1]
        entry = live_pair_registry.get(pair_id)
        if not entry:
            await context.bot.send_message(chat_id=user_id, text="⚠️ This live asset is no longer in cache. Please refresh the market board.")
            return True
        user_data[user_id]["pair"] = entry["pair_key"]
        user_data[user_id]["pairdict"] = entry["pairdict"]
        user_data[user_id]["pair_label"] = entry["display_name"]
        user_data[user_id]["pair_registry_id"] = pair_id
        user_data[user_id]["pair_market_type"] = entry["market_type"]
        tf_list = list(timeframes.keys())
        keyboard = []
        for i in range(0, len(tf_list), 2):
            keyboard.append([InlineKeyboardButton(tf, callback_data=f"settf_{tf}") for tf in tf_list[i:i + 2]])
        keyboard.append([InlineKeyboardButton("🔙 Back to Markets", callback_data=f"livepairs_{entry['market_type']}_0")])
        payout_line = f"\n• Current payout: {entry['payout']:.0f}%" if entry.get("payout") else ""
        await query.edit_message_text(
            f"💹 <b>{entry['display_name']}</b>\n\nChoose a timeframe for layered analysis.{payout_line}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return True

    if data.startswith("setpair_"):
        selected_pair = data.split("_", 1)[1]
        user_data[user_id]["pair"] = selected_pair
        user_data[user_id]["pairdict"] = pairs[selected_pair]
        user_data[user_id]["pair_label"] = selected_pair.replace("_otc", " OTC")
        user_data[user_id]["pair_registry_id"] = None
        tf_list = list(timeframes.keys())
        keyboard = []
        for i in range(0, len(tf_list), 2):
            keyboard.append([InlineKeyboardButton(tf, callback_data=f"settf_{tf}") for tf in tf_list[i:i + 2]])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
        await query.edit_message_text(
            f"⏱️ <b>Select timeframe for {user_data[user_id]['pair_label']}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return True

    if data.startswith("settf_"):
        selected_timeframe = data.split("_", 1)[1]
        selected_pair = user_data[user_id].get("pair")
        if not selected_pair:
            await context.bot.send_message(chat_id=user_id, text="⚠️ No pair selected.")
            return True
        user_data[user_id]["preferred_timeframe"] = selected_timeframe
        pairdict = user_data[user_id].get("pairdict") or pairs[selected_pair]
        pair_label = user_data[user_id].get("pair_label", selected_pair)
        pair_registry_id = user_data[user_id].get("pair_registry_id")
        timeframe_minutes = int(selected_timeframe.replace("m", ""))
        message, trade_direction, confidence, features, market_context = await smart_trading_execution(
            context, user_id, pairdict, selected_timeframe, timeframe_minutes
        )
        hist = user_data[user_id].setdefault("history", [])
        hist.insert(0, {
            "pair": pair_label,
            "pair_key": selected_pair,
            "tf": selected_timeframe,
            "time": time.ctime(),
            "result": message,
            "direction": trade_direction,
            "confidence": confidence,
            "features": features.tolist() if hasattr(features, "tolist") else features,
            "price_sequence": market_context.get("price_sequence", []),
        })
        user_data[user_id]["history"] = hist[:10]
        if pair_registry_id:
            execute_callback = f"executeid_{pair_registry_id}_{selected_timeframe}_{trade_direction}"
            analysis_callback = f"deepid_{pair_registry_id}_{selected_timeframe}"
            live_callback = f"liveid_{pair_registry_id}_{selected_timeframe}"
            back_callback = f"livepairs_{user_data[user_id].get('pair_market_type', 'all')}_0"
        else:
            execute_callback = f"execute_{selected_pair}_{selected_timeframe}_{trade_direction}"
            analysis_callback = f"deep_analysis_{selected_pair}_{selected_timeframe}"
            live_callback = f"live_{selected_pair}_{selected_timeframe}"
            back_callback = f"setpair_{selected_pair}"
        if trade_direction in ["call", "put"] and confidence > 65:
            direction_text = "Buy CALL 📈" if trade_direction == "call" else "Buy PUT 📉"
            risk_color = "🟢" if confidence > 80 else "🟡" if confidence > 65 else "🔴"
            keyboard = [
                [InlineKeyboardButton(f"{risk_color} {direction_text}", callback_data=execute_callback)],
                [InlineKeyboardButton("📊 Deep Analysis", callback_data=analysis_callback), InlineKeyboardButton("📡 Live Tape", callback_data=live_callback)],
                [InlineKeyboardButton("🔄 Reanalyze", callback_data=f"settf_{selected_timeframe}"), InlineKeyboardButton("🔙 Back", callback_data=back_callback)],
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("📡 Live Tape", callback_data=live_callback)],
                [InlineKeyboardButton("🔄 Reanalyze", callback_data=f"settf_{selected_timeframe}"), InlineKeyboardButton("🔙 Back", callback_data=back_callback)],
            ]
        await context.bot.send_message(chat_id=user_id, text=message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    return False

from typing import Any, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


async def handle_static_button_menu(
    *,
    update: Any,
    context: Any,
    user_id: int,
    data: str,
    query: Any,
    user_data: dict[int, dict[str, Any]],
    start_handler: Callable[[Any, Any], Any],
    active_trades_handler: Callable[[Any, Any], Any],
    trade_history_handler: Callable[[Any, Any], Any],
    check_connection_status: Callable[[], Any],
    reconnect_broker: Callable[[], Any],
    advanced_ai_system: Any,
) -> bool:
    if data == "back_to_main":
        await start_handler(update, context)
        return True

    if data == "active_trades_list":
        await active_trades_handler(update, context)
        return True

    if data == "trade_history":
        await trade_history_handler(update, context)
        return True

    if data == "ai_stats":
        stats_msg = (
            "<b>AI Engine Stats</b>\n\n"
            f"• Training samples: {len(advanced_ai_system.training_data)}\n"
            f"• Available models: {', '.join(advanced_ai_system._available_models().keys())}\n"
            f"• Dynamic weights: {', '.join(f'{k}={v:.2f}' for k, v in advanced_ai_system.model_weights.items()) if advanced_ai_system.model_weights else 'uniform'}\n"
            f"• LSTM available: {'yes' if advanced_ai_system.lstm_model is not None else 'no'}\n"
        )
        keyboard = [[InlineKeyboardButton("Back", callback_data="back_to_main")]]
        await query.edit_message_text(stats_msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data == "debug_connection":
        connection_status = await check_connection_status()
        keyboard = [
            [InlineKeyboardButton("Reconnect", callback_data="reconnect_quotex")],
            [InlineKeyboardButton("Back", callback_data="back_to_main")],
        ]
        await query.edit_message_text(connection_status, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data == "reconnect_quotex":
        await context.bot.send_message(chat_id=user_id, text="Reconnecting to Quotex...")
        client = await reconnect_broker()
        await context.bot.send_message(
            chat_id=user_id,
            text="Reconnected successfully." if client else "Reconnect failed.",
        )
        return True

    if data == "scanner_menu":
        preferred_timeframe = user_data[user_id].get("preferred_timeframe", "1m")
        scanner_text = (
            "<b>Market Scanner</b>\n\n"
            "Run a full scan across the currently open Quotex assets.\n"
            "The bot will rank the best 3 setups using the layered engine.\n\n"
            f"Current default timeframe: <b>{preferred_timeframe}</b>"
        )
        keyboard = []
        for tf_row in (("1m", "5m"), ("15m", "1h"), ("4h",)):
            row = [InlineKeyboardButton(f"Scan {tf}", callback_data=f"scanbest_{tf}") for tf in tf_row]
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("Main Desk", callback_data="back_to_main")])
        await query.edit_message_text(scanner_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    return False

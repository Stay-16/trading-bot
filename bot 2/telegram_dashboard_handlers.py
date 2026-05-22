from typing import Any, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


async def start_handler(
    update: Any,
    *,
    user_data: dict[int, dict[str, Any]],
    settings: Any,
    quotex_connected: bool,
    get_connection_status: Callable[[], Any],
    advanced_ai_system: Any,
) -> None:
    user_id = update.effective_user.id
    if user_id not in user_data:
        user_data[user_id] = {"preferred_timeframe": "15m", "history": []}

    connection_status = await get_connection_status()
    performance_stats = advanced_ai_system.get_performance_stats()
    stats_text = (
        f"• Total trades: {performance_stats['total_trades']}\n"
        f"• Win rate: {performance_stats['win_rate']}%\n"
        f"• Profit factor: {performance_stats['profit_factor']}"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    if settings.webapp.public_url:
        keyboard.append([
            InlineKeyboardButton(
                "Open Mini App",
                web_app=WebAppInfo(url=settings.webapp.public_url),
            )
        ])
    keyboard.extend([
        [InlineKeyboardButton("Live Forex Markets", callback_data="market_live")],
        [InlineKeyboardButton("Best 3 Setups", callback_data="scanner_menu")],
        [InlineKeyboardButton("Active Trades", callback_data="active_trades_list")],
        [InlineKeyboardButton("Trade History", callback_data="trade_history")],
        [InlineKeyboardButton("AI Stats", callback_data="ai_stats")],
        [InlineKeyboardButton(f"{'Connected' if quotex_connected else 'Disconnected'}", callback_data="debug_connection")],
    ])

    mini_app_line = (
        f"Mini App: connected to {settings.webapp.public_url}\n"
        "Open it directly inside Telegram from the button below.\n\n"
        if settings.webapp.public_url
        else "Mini App: set WEBAPP_URL to open the dashboard from Telegram.\n\n"
    )

    welcome_msg = (
        "<b>Quotex AI Desk</b>\n\n"
        f"{connection_status}\n\n"
        "<b>Desk Stats:</b>\n"
        f"{stats_text}\n\n"
        "<b>Main Surfaces:</b>\n"
        "• Telegram bot for commands and quick actions\n"
        "• Telegram Mini App for the visual dashboard\n"
        "• Browser dashboard for larger-screen access\n\n"
        "<b>Workflow:</b>\n"
        "• Open the live market board from Quotex\n"
        "• Pick any currently available asset\n"
        "• Run a full layered analysis\n"
        "• Or scan the market and get the best 3 setups\n\n"
        "<b>Engine Stack:</b>\n"
        "• Ensemble AI with dynamic model weights\n"
        "• LSTM base model for price action\n"
        "• Technical analysis, trend, volatility, and candle voting\n"
        "• Dynamic risk management and continuous learning\n\n"
        f"{mini_app_line}"
        "Choose your next action:"
    )

    target = update.message if update.message else update.callback_query.message
    await target.reply_text(
        welcome_msg,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def stats_handler(
    update: Any,
    *,
    get_connection_status: Callable[[], Any],
    advanced_ai_system: Any,
    active_trades: dict[str, dict[str, Any]],
    trade_history: list[dict[str, Any]],
) -> None:
    performance_stats = advanced_ai_system.get_performance_stats()
    connection_status = await get_connection_status()
    stats_message = (
        "📊 <b>System Report</b>\n\n"
        f"{connection_status}\n\n"
        "🤖 <b>AI Performance:</b>\n"
        f"• Total trades: {performance_stats['total_trades']}\n"
        f"• Win rate: {performance_stats['win_rate']}%\n"
        f"• Profit factor: {performance_stats['profit_factor']}\n"
        f"• Expectancy: ${performance_stats['expectancy']}\n\n"
        "💹 <b>Trading State:</b>\n"
        f"• Active trades: {len([t for t in active_trades.values() if t.get('status') == 'pending'])}\n"
        f"• History size: {len(trade_history)}\n"
        f"• Training samples: {len(advanced_ai_system.training_data)}\n\n"
        "🧠 <b>Models:</b>\n"
        f"• Ensemble members: {', '.join(advanced_ai_system._available_models().keys())}\n"
        f"• Dynamic weights: {', '.join(f'{k}={v:.2f}' for k, v in advanced_ai_system.model_weights.items()) if advanced_ai_system.model_weights else 'uniform'}\n"
        f"• LSTM available: {'yes' if advanced_ai_system.lstm_model is not None else 'no'}"
    )
    await update.message.reply_text(stats_message, parse_mode="HTML")


async def performance_handler(
    update: Any,
    *,
    get_trade_state_service: Callable[[], Any],
) -> None:
    user_id = update.effective_user.id
    user_trades = get_trade_state_service().get_user_trade_history(user_id)
    if not user_trades:
        await update.message.reply_text("📭 No completed trades available yet.")
        return

    wins = len([t for t in user_trades if t.get("result") == "win"])
    total = len(user_trades)
    win_rate = (wins / total * 100) if total > 0 else 0
    total_profit = sum(t.get("profit", 0) for t in user_trades)
    avg_profit = total_profit / total if total > 0 else 0
    best_trades = sorted(user_trades, key=lambda x: x.get("profit", 0), reverse=True)[:3]

    performance_msg = (
        "🎯 <b>Your Performance Report</b>\n\n"
        "📈 <b>Core Stats:</b>\n"
        f"• Total trades: {total}\n"
        f"• Winning trades: {wins}\n"
        f"• Win rate: {win_rate:.1f}%\n"
        f"• Total PnL: ${total_profit:.2f}\n"
        f"• Average PnL: ${avg_profit:.2f}\n\n"
        "🏆 <b>Best Trades:</b>\n"
    )
    for i, trade in enumerate(best_trades, 1):
        profit = trade.get("profit", 0)
        pair = trade.get("pair_name", trade["asset"])
        direction = trade.get("direction", "").upper()
        performance_msg += f"{i}. {pair} {direction} - ${profit:.2f}\n"

    performance_msg += (
        "\n💡 <b>Suggestions:</b>\n"
        "• Focus on pairs with your strongest results\n"
        "• Prefer multi-timeframe confirmation\n"
        "• Keep position sizing disciplined\n"
    )
    await update.message.reply_text(performance_msg, parse_mode="HTML")

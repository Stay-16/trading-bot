import time
from typing import Any, Callable


def _reply_target(update: Any):
    return update.callback_query.message if update.callback_query else update.message


async def active_trades_handler(update: Any, get_trade_state_service: Callable[[], Any]) -> None:
    user_id = update.effective_user.id
    user_active_trades = get_trade_state_service().get_user_active_trades(user_id)
    target = _reply_target(update)

    if not user_active_trades:
        await target.reply_text("📭 No active trades right now.")
        return

    trades_text = "📊 <b>Your Active Trades</b>\n\n"
    for i, trade in enumerate(user_active_trades, 1):
        elapsed = time.time() - trade["open_time"]
        remaining = max(0, trade["duration"] - elapsed)
        trades_text += (
            f"{i}. {trade['asset']} - {trade['direction'].upper()}\n"
            f"   💰 ${trade['amount']} | ⏳ {int(remaining)}s remaining\n"
            f"   🆔 {trade['trade_id'][:8]}...\n"
            f"────────────────────\n"
        )

    await target.reply_text(trades_text, parse_mode="HTML")


async def trade_history_handler(update: Any, get_trade_state_service: Callable[[], Any]) -> None:
    user_id = update.effective_user.id
    user_trades = get_trade_state_service().get_user_trade_history(user_id)
    target = _reply_target(update)

    if not user_trades:
        await target.reply_text("📋 No trade history found.")
        return

    recent_trades = user_trades[-5:] if len(user_trades) > 5 else user_trades
    history_text = "📋 <b>Recent Trades</b>\n\n"
    for i, trade in enumerate(recent_trades, 1):
        result_emoji = "🎉" if trade.get("result") == "win" else "💸" if trade.get("result") == "loss" else "⚠️"
        result_text = "Win" if trade.get("result") == "win" else "Loss" if trade.get("result") == "loss" else "Pending"
        profit = trade.get("profit", 0)
        history_text += (
            f"{i}. {trade['asset']} - {trade['direction'].upper()}\n"
            f"   💰 ${trade['amount']} | {result_emoji} {result_text} (${profit})\n"
            f"   🆔 {trade['trade_id'][:8]}...\n"
            f"────────────────────\n"
        )

    await target.reply_text(history_text, parse_mode="HTML")

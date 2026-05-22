import asyncio
import logging
import random
import time
from typing import Any, Callable


class TradeMonitorService:
    def __init__(
        self,
        *,
        get_client: Callable[[], Any],
        trade_state_service: Any,
        risk_manager: Any,
        advanced_ai_system: Any,
    ) -> None:
        self._get_client = get_client
        self._trade_state_service = trade_state_service
        self._risk_manager = risk_manager
        self._advanced_ai_system = advanced_ai_system

    async def monitor_trade(
        self,
        trade_id: str,
        user_id: int,
        context: Any,
        trade_data: dict[str, Any],
        features: Any,
        market_context: dict[str, Any],
    ) -> None:
        try:
            trade_info = self._trade_state_service.active_trades.get(trade_id)
            if not trade_info:
                return

            duration = trade_info["duration"]
            asset = trade_info["asset"]
            direction = trade_info["direction"]
            amount = trade_info["amount"]

            if context is not None:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Monitoring trade {trade_id} with advanced AI...",
                    parse_mode="HTML",
                )

            logging.info("Waiting for trade %s to settle for %s seconds", trade_id, duration + 15)
            await asyncio.sleep(duration + 15)

            trade_result, profit, result_source = await self._resolve_trade_result(
                trade_id=trade_id,
                amount=amount,
                trade_data=trade_data,
                market_context=market_context,
            )

            trade_info["status"] = "closed"
            trade_info["result"] = trade_result
            trade_info["profit"] = profit
            trade_info["close_time"] = time.time()
            trade_info["result_source"] = result_source
            trade_info["market_context"] = market_context

            learning_data = {
                "features": features,
                "result": trade_result,
                "confidence": trade_data["confidence"],
                "profit": profit,
                "pair": trade_data.get("pair", "unknown"),
                "direction": direction,
                "timeframe": trade_data.get("timeframe", ""),
                "market_condition": market_context.get("market_condition", "normal"),
                "timestamp": time.time(),
                "result_source": result_source,
            }

            await self._advanced_ai_system.learn_from_trade(learning_data)

            risk_snapshot = self._risk_manager.record_trade_result(user_id, profit)
            trade_info["risk_snapshot"] = risk_snapshot
            self._trade_state_service.record_closed_trade(trade_info)

            performance_stats = self._advanced_ai_system.get_performance_stats()
            result_emoji = "WIN" if trade_result == "win" else "LOSS"
            result_text = "Win" if trade_result == "win" else "Loss"

            result_message = (
                f"<b>Trade Result</b>\n\n"
                f"Pair: {asset}\n"
                f"Direction: {direction.upper()}\n"
                f"Amount: ${amount}\n"
                f"Result: <b>{result_text}</b>\n"
                f"P/L: <b>${profit:.2f}</b>\n"
                f"Trade ID: <code>{trade_id}</code>\n"
                f"Source: {result_source}\n\n"
                f"AI Stats:\n"
                f"Total trades: {performance_stats['total_trades']}\n"
                f"Win rate: {performance_stats['win_rate']}%\n"
                f"Profit factor: {performance_stats['profit_factor']}"
            )

            if context is not None:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=result_message,
                    parse_mode="HTML",
                )

            logging.info("Trade %s closed with result %s (%s)", trade_id, trade_result, result_source)
        except Exception as exc:
            logging.error("Trade monitor failed for %s: %s", trade_id, exc)
            try:
                if context is not None:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"Warning: trade monitoring failed for {trade_id}",
                        parse_mode="HTML",
                    )
            except Exception:
                pass
        finally:
            self._trade_state_service.active_trades.pop(trade_id, None)

    async def _resolve_trade_result(
        self,
        *,
        trade_id: str,
        amount: float,
        trade_data: dict[str, Any],
        market_context: dict[str, Any],
    ) -> tuple[str, float, str]:
        client = self._get_client()
        if client:
            try:
                trade_result_data = await client.check_win(trade_id)
                if trade_result_data and isinstance(trade_result_data, tuple):
                    return (
                        "win" if trade_result_data[0] else "loss",
                        trade_result_data[1] if trade_result_data[1] else 0,
                        "Live broker result",
                    )
                trade_result_data2 = await client.get_result(trade_id)
                if trade_result_data2 is not None:
                    return (
                        "win" if trade_result_data2 > 0 else "loss",
                        trade_result_data2,
                        "Live broker result",
                    )
            except Exception as exc:
                logging.warning("Falling back to simulated trade result for %s: %s", trade_id, exc)

        base_win_prob = 0.6
        confidence_boost = trade_data["confidence"] / 100 * 0.3
        market_boost = 0.1 if market_context.get("market_condition") == "low_vol" else 0
        win_probability = min(0.90, base_win_prob + confidence_boost + market_boost)
        trade_result = "win" if random.random() < win_probability else "loss"
        profit = amount * 0.85 if trade_result == "win" else -amount
        return trade_result, profit, "Simulated fallback"

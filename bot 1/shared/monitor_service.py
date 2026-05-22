import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("MonitorSvc")


class TradeMonitorService:
    def __init__(
        self,
        *,
        get_client: Callable[[], Any],
        ensure_connection: Callable[[int], Awaitable[Any]],
        learn_from_trade_fn: Optional[Callable] = None,
        record_risk_result_fn: Optional[Callable] = None,
        active_trades: dict,
        trade_history: list,
        now_ts: Callable[[], float],
    ) -> None:
        self._get_client = get_client
        self._ensure_connection = ensure_connection
        self._learn_from_trade_fn = learn_from_trade_fn
        self._record_risk_result_fn = record_risk_result_fn
        self._active_trades = active_trades
        self._trade_history = trade_history
        self._now_ts = now_ts

    async def monitor_trade(self, trade_key: str, duration: int, direction: str, payout: float, metadata: Optional[dict] = None):
        await asyncio.sleep(duration + 15)
        trade_entry = self._active_trades.get(trade_key, {})
        asset = trade_entry.get("asset", "unknown")
        amount = trade_entry.get("amount", 0)

        client = self._get_client()
        result_data = {"direction": direction, "payout": payout, "amount": amount}

        if client:
            try:
                win_result = await asyncio.wait_for(client.check_win(trade_key), timeout=5)
                if self._is_win(win_result):
                    profit = amount * payout
                    result_data["outcome"] = "win"
                    result_data["profit"] = profit
                else:
                    profit = -amount
                    result_data["outcome"] = "loss"
                    result_data["profit"] = profit
            except Exception:
                try:
                    get_result = await asyncio.wait_for(client.get_result(trade_key), timeout=5)
                    if self._is_win(get_result):
                        profit = amount * payout
                        result_data["outcome"] = "win"
                        result_data["profit"] = profit
                    else:
                        profit = -amount
                        result_data["outcome"] = "loss"
                        result_data["profit"] = profit
                except Exception:
                    result_data["outcome"] = "unknown"
                    result_data["profit"] = 0
        else:
            result_data["outcome"] = "unknown"
            result_data["profit"] = 0

        if trade_key in self._active_trades:
            self._active_trades[trade_key].update({
                "status": result_data["outcome"],
                "profit": result_data["profit"],
                "close_time": self._now_ts(),
            })
            closed = dict(self._active_trades.pop(trade_key))
            closed["closed_at"] = self._now_ts()
            self._trade_history.append(closed)

        if self._learn_from_trade_fn:
            try:
                self._learn_from_trade_fn(result_data)
            except Exception as e:
                log.debug("learn_from_trade error: %s", e)

        if self._record_risk_result_fn:
            try:
                self._record_risk_result_fn(result_data)
            except Exception as e:
                log.debug("record_risk_result error: %s", e)

        return result_data

    @staticmethod
    def _is_win(result: Any) -> bool:
        if isinstance(result, bool):
            return result
        if isinstance(result, (int, float)):
            return result > 0
        if isinstance(result, dict):
            status = str(result.get("result", result.get("status", ""))).lower()
            amount = float(result.get("profit", result.get("amount", 0)))
            return "win" in status or amount > 0
        if isinstance(result, (tuple, list)):
            return bool(result[0]) if len(result) >= 1 else False
        return False

from typing import Any, Callable


class TradeStateService:
    def __init__(
        self,
        *,
        active_trades: dict[str, dict[str, Any]],
        trade_history: list[dict[str, Any]],
        now_ts: Callable[[], float],
    ) -> None:
        self._active_trades = active_trades
        self._trade_history = trade_history
        self._now_ts = now_ts

    @property
    def active_trades(self) -> dict[str, dict[str, Any]]:
        return self._active_trades

    @property
    def trade_history(self) -> list[dict[str, Any]]:
        return self._trade_history

    def cleanup_stale_active_trades(
        self,
        *,
        user_id: int | None = None,
        pair_label: str | None = None,
        asset: str | None = None,
        grace_seconds: int = 45,
    ) -> int:
        normalized_pair = str(pair_label or "").lower()
        normalized_asset = str(asset or "").lower()
        now = self._now_ts()
        removed = 0

        for trade_id, trade in list(self._active_trades.items()):
            if not isinstance(trade, dict):
                self._active_trades.pop(trade_id, None)
                removed += 1
                continue

            status = str(trade.get("status", "")).lower()
            trade_user_id = trade.get("user_id", 0)
            if user_id and trade_user_id not in {0, user_id}:
                continue

            trade_pair = str(trade.get("pair_name") or trade.get("pair") or "").lower()
            trade_asset = str(trade.get("asset") or "").lower()
            if normalized_pair or normalized_asset:
                same_pair = normalized_pair and trade_pair == normalized_pair
                same_asset = normalized_asset and trade_asset == normalized_asset
                if not (same_pair or same_asset):
                    continue

            if status and status != "pending":
                self._active_trades.pop(trade_id, None)
                removed += 1
                continue

            open_time = trade.get("open_time")
            duration = trade.get("duration")
            if open_time is None or duration is None:
                continue

            try:
                expires_at = float(open_time) + float(duration) + float(grace_seconds)
            except Exception:
                continue

            if now >= expires_at:
                trade["status"] = "stale"
                trade["close_time"] = now
                self._active_trades.pop(trade_id, None)
                removed += 1

        return removed

    def get_user_active_trades(self, user_id: int) -> list[dict[str, Any]]:
        return [
            trade
            for trade in self._active_trades.values()
            if trade.get("user_id") == user_id and trade.get("status") == "pending"
        ]

    def get_user_trade_history(self, user_id: int) -> list[dict[str, Any]]:
        return [trade for trade in self._trade_history if trade.get("user_id") == user_id]

    def attach_trade_context(self, trade_id: str, **updates: Any) -> dict[str, Any] | None:
        trade = self._active_trades.get(trade_id)
        if not trade:
            return None
        trade.update(updates)
        return trade

    def record_closed_trade(self, trade: dict[str, Any]) -> None:
        self._trade_history.append(trade.copy())

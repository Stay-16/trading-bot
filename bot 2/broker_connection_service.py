import asyncio
from typing import Any, Awaitable, Callable


class BrokerConnectionService:
    def __init__(
        self,
        *,
        get_client: Callable[[], Any],
        connect_with_retry: Callable[[int], Awaitable[Any]],
        balance_cache: dict[str, tuple[float, float]],
        now_ts: Callable[[], float],
        reconnect_lock: asyncio.Lock,
        get_last_reconnect_at: Callable[[], float],
        set_last_reconnect_at: Callable[[float], None],
    ) -> None:
        self._get_client = get_client
        self._connect_with_retry = connect_with_retry
        self._balance_cache = balance_cache
        self._now_ts = now_ts
        self._reconnect_lock = reconnect_lock
        self._get_last_reconnect_at = get_last_reconnect_at
        self._set_last_reconnect_at = set_last_reconnect_at

    async def get_current_balance(self) -> float:
        cached_balance = self._balance_cache.get("main")
        if cached_balance and self._now_ts() - cached_balance[0] < 15:
            return cached_balance[1]

        client = self._get_client()
        if not client:
            if cached_balance:
                return cached_balance[1]
            raise RuntimeError("Quotex client is not connected")

        try:
            balance = await asyncio.wait_for(client.get_balance(), timeout=8)
            self._balance_cache["main"] = (self._now_ts(), balance)
            return balance
        except Exception:
            if cached_balance:
                return cached_balance[1]
            raise

    async def refresh_connection_if_needed(self, min_interval_seconds: int = 8) -> bool:
        if self._now_ts() - self._get_last_reconnect_at() < float(min_interval_seconds):
            return bool(self._get_client())

        async with self._reconnect_lock:
            if self._now_ts() - self._get_last_reconnect_at() < float(min_interval_seconds):
                return bool(self._get_client())
            self._set_last_reconnect_at(self._now_ts())
            client = await self._connect_with_retry(max_retries=1)
            return bool(client)

    async def check_connection_status(self, connected_label: str, disconnected_label: str) -> str:
        client = self._get_client()
        if not client:
            return disconnected_label

        try:
            balance = await self.get_current_balance()
            return connected_label.format(balance=balance)
        except Exception:
            return disconnected_label

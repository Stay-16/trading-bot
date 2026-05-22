from dataclasses import dataclass
import asyncio
from typing import Awaitable, Callable, Optional, Tuple


@dataclass(frozen=True)
class ExecutionRequest:
    direction: str
    asset: str
    amount: float
    duration: int


class ExecutionLayer:
    """Layer 5: broker execution and connectivity."""

    def __init__(
        self,
        execute_trade_fn: Callable[[str, str, float, int], Awaitable[Tuple[bool, str]]],
        connection_check_fn: Callable[[], Awaitable[str]],
        balance_fn: Callable[[], Awaitable[float]],
    ) -> None:
        self._execute_trade_fn = execute_trade_fn
        self._connection_check_fn = connection_check_fn
        self._balance_fn = balance_fn

    async def get_balance(self) -> Optional[float]:
        try:
            return await self._balance_fn()
        except Exception:
            return None

    async def check_connection(self) -> str:
        return await self._connection_check_fn()

    async def execute(self, request: ExecutionRequest) -> Tuple[bool, str]:
        try:
            return await asyncio.wait_for(
                self._execute_trade_fn(
                    request.direction,
                    request.asset,
                    request.amount,
                    request.duration,
                ),
                timeout=65,
            )
        except asyncio.TimeoutError:
            return False, "Broker execution timed out"

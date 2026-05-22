import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Tuple

log = logging.getLogger("ExecService")


@dataclass(frozen=True)
class ExecutionRequest:
    direction: str
    asset: str
    amount: float
    duration: int


class ExecutionLayer:
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
                self._execute_trade_fn(request.direction, request.asset, request.amount, request.duration),
                timeout=65,
            )
        except asyncio.TimeoutError:
            return False, "Broker execution timed out"


class TradeExecutionService:
    def __init__(
        self,
        *,
        get_client: Callable[[], Any],
        ensure_connection: Callable[[int], Awaitable[Any]],
        refresh_connection: Callable[[int], Awaitable[bool]],
        symbol_to_api_symbol: Callable[[str], str],
        active_trades: dict,
        balance_cache: dict,
        execution_lock: asyncio.Lock,
    ) -> None:
        self._get_client = get_client
        self._ensure_connection = ensure_connection
        self._refresh_connection = refresh_connection
        self._symbol_to_api_symbol = symbol_to_api_symbol
        self._active_trades = active_trades
        self._balance_cache = balance_cache
        self._execution_lock = execution_lock

    async def execute_trade(self, direction: str, asset: str, amount: float, duration: int = 60):
        try:
            async with self._execution_lock:
                client = self._get_client()
                if not client:
                    await self._ensure_connection(2)
                    client = self._get_client()
                if not client:
                    return False, "Broker is not connected to Quotex right now"

                api_asset = self._symbol_to_api_symbol(asset)
                log.info("Attempting trade: %s on %s (api: %s) for $%s", direction, asset, api_asset, amount)

                direct_buy = getattr(client, "buy", None)
                if not direct_buy:
                    return False, "Direct buy method is unavailable on the Quotex client"

                execution_errors: list[str] = []
                candidate_assets = build_candidate_assets(asset, api_asset)

                async def attempt_direct_buy(candidate_asset: str, timeout_seconds: int = 14):
                    current_client = self._get_client()
                    current_buy = getattr(current_client, "buy", None)
                    if not current_buy:
                        raise RuntimeError("Direct buy method is unavailable on the Quotex client")
                    if inspect.iscoroutinefunction(current_buy):
                        return await asyncio.wait_for(
                            current_buy(float(amount), candidate_asset, direction, int(duration)),
                            timeout=timeout_seconds,
                        )
                    return await asyncio.wait_for(
                        asyncio.to_thread(current_buy, float(amount), candidate_asset, direction, int(duration)),
                        timeout=timeout_seconds,
                    )

                def normalize_execution_result(result: Any, candidate_asset: str, method_used: str):
                    success = False
                    trade_id = None
                    if isinstance(result, tuple):
                        success = bool(result[0])
                        if len(result) > 1 and result[1]:
                            trade_id = str(result[1])
                    else:
                        success = bool(result)
                        if result not in {True, False, None}:
                            trade_id = str(result)
                    if not success:
                        return None
                    trade_key = trade_id or f"{candidate_asset}_{int(time.time())}"
                    self._active_trades[trade_key] = {
                        "trade_id": trade_key, "direction": direction,
                        "asset": candidate_asset, "amount": amount,
                        "duration": duration, "open_time": time.time(),
                        "status": "pending", "method_used": method_used,
                    }
                    self._balance_cache.pop("main", None)
                    return trade_key

                for candidate_asset in candidate_assets:
                    try:
                        normalized_candidate = str(candidate_asset).lower()
                        buy_timeout = 36 if "otc" in normalized_candidate else 28
                        log.info("Trying broker buy for %s using asset candidate %s", asset, candidate_asset)
                        direct_result = await attempt_direct_buy(candidate_asset, timeout_seconds=buy_timeout)
                        trade_key = normalize_execution_result(direct_result, candidate_asset, "buy")
                        if trade_key:
                            return True, trade_key
                        execution_errors.append(f"{candidate_asset}: broker returned no success confirmation")
                    except asyncio.TimeoutError:
                        execution_errors.append(f"{candidate_asset}: broker timeout")
                        log.warning("Broker buy timed out for %s with asset candidate %s", asset, candidate_asset)
                        try:
                            await self._refresh_connection(8)
                            await asyncio.sleep(2.0)
                        except Exception as refresh_error:
                            execution_errors.append(f"{candidate_asset}: refresh failed ({refresh_error})")
                        continue
                    except Exception as direct_error:
                        execution_errors.append(f"{candidate_asset}: {direct_error}")

                timeout_errors = [e for e in execution_errors if "broker timeout" in e]
                if timeout_errors:
                    return False, "Execution timed out on all broker symbol attempts. Connection refreshed; try again."
                return False, " | ".join(execution_errors) if execution_errors else "Trade execution failed"
        except Exception as exc:
            log.error("Trade execution service failed: %s", exc)
            return False, f"Technical execution error: {exc}"


def build_candidate_assets(asset: str, api_asset: str) -> list[str]:
    candidates: list[str] = []
    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)
    primary = str(api_asset or asset or "").strip()
    original = str(asset or "").strip()
    upper_primary = primary.upper()
    upper_original = original.upper()
    add(primary)
    add(original)
    add(upper_primary)
    add(upper_original)
    for seed in (upper_primary, upper_original):
        if not seed:
            continue
        collapsed = seed.replace("/", "").replace(" ", "")
        hyphenated = collapsed.replace("_", "-")
        underscored = collapsed.replace("-", "_")
        add(collapsed)
        add(hyphenated)
        add(underscored)
        if collapsed.endswith("OTC"):
            base = collapsed[:-3]
            add(f"{base}-OTC")
            add(f"{base}_otc")
            add(f"{base}_OTC")
            add(f"{base}OTC")
        if underscored.lower().endswith("_otc"):
            base = underscored[:-4]
            add(f"{base}-OTC")
            add(f"{base}OTC")
        if hyphenated.endswith("-OTC"):
            base = hyphenated[:-4]
            add(f"{base}_otc")
            add(f"{base}OTC")
    return candidates

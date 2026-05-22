import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable


class TradeExecutionService:
    def __init__(
        self,
        *,
        get_client: Callable[[], Any],
        ensure_connection: Callable[[int], Awaitable[Any]],
        refresh_connection: Callable[[int], Awaitable[bool]],
        symbol_to_api_symbol: Callable[[str], str],
        active_trades: dict[str, dict[str, Any]],
        balance_cache: dict[str, tuple[float, float]],
        execution_lock: asyncio.Lock,
    ) -> None:
        self._get_client = get_client
        self._ensure_connection = ensure_connection
        self._refresh_connection = refresh_connection
        self._symbol_to_api_symbol = symbol_to_api_symbol
        self._active_trades = active_trades
        self._balance_cache = balance_cache
        self._execution_lock = execution_lock

    @staticmethod
    def _build_candidate_assets(asset: str, api_asset: str) -> list[str]:
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
                logging.info(
                    "Attempting trade execution: %s on %s (api: %s) for $%s",
                    direction,
                    asset,
                    api_asset,
                    amount,
                )

                direct_buy = getattr(client, "buy", None)
                if not direct_buy:
                    return False, "Direct buy method is unavailable on the Quotex client"

                execution_errors: list[str] = []
                candidate_assets = self._build_candidate_assets(asset, api_asset)

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
                        asyncio.to_thread(
                            current_buy,
                            float(amount),
                            candidate_asset,
                            direction,
                            int(duration),
                        ),
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
                        "trade_id": trade_key,
                        "direction": direction,
                        "asset": candidate_asset,
                        "amount": amount,
                        "duration": duration,
                        "open_time": time.time(),
                        "status": "pending",
                        "method_used": method_used,
                    }
                    self._balance_cache.pop("main", None)
                    return trade_key

                for candidate_asset in candidate_assets:
                    try:
                        normalized_candidate = str(candidate_asset).lower()
                        buy_timeout = 36 if "otc" in normalized_candidate else 28
                        logging.info(
                            "Trying broker buy for %s using asset candidate %s with %ss timeout",
                            asset,
                            candidate_asset,
                            buy_timeout,
                        )
                        direct_result = await attempt_direct_buy(
                            candidate_asset,
                            timeout_seconds=buy_timeout,
                        )
                        logging.info(
                            "Broker buy returned for %s with candidate %s: %r",
                            asset,
                            candidate_asset,
                            direct_result,
                        )
                        trade_key = normalize_execution_result(direct_result, candidate_asset, "buy")
                        if trade_key:
                            return True, trade_key
                        execution_errors.append(f"{candidate_asset}: broker returned no success confirmation")
                    except asyncio.TimeoutError:
                        execution_errors.append(f"{candidate_asset}: broker timeout")
                        logging.warning(
                            "Broker buy timed out for %s with asset candidate %s. Refreshing Quotex connection before trying any remaining candidate.",
                            asset,
                            candidate_asset,
                        )
                        try:
                            await self._refresh_connection(8)
                            await asyncio.sleep(2.0)
                        except Exception as refresh_error:
                            execution_errors.append(f"{candidate_asset}: refresh failed ({refresh_error})")
                        continue
                    except Exception as direct_error:
                        execution_errors.append(f"{candidate_asset}: {direct_error}")

                timeout_errors = [error for error in execution_errors if "broker timeout" in error]
                if timeout_errors:
                    return False, "Execution timed out before broker confirmation on all broker symbol attempts. Connection was refreshed; please try again."
                return False, " | ".join(execution_errors) if execution_errors else "Trade execution failed"
        except Exception as exc:
            logging.error("Trade execution service failed: %s", exc)
            return False, f"Technical execution error: {exc}"

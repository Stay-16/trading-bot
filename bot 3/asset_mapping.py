import hashlib
import re
from typing import Any, Dict, List, Tuple


def normalize_quotex_symbol(asset_name: str) -> str:
    symbol = str(asset_name or "").strip().upper()
    symbol = symbol.replace(" ", "").replace("/", "").replace("_", "-")
    if symbol.endswith("OTC") and not symbol.endswith("-OTC"):
        symbol = f"{symbol[:-3]}-OTC"
    return symbol


def quotex_symbol_to_api_symbol(asset_name: str) -> str:
    normalized = normalize_quotex_symbol(asset_name)
    if normalized.endswith("-OTC"):
        return f"{normalized[:-4]}_otc"
    return normalized


def infer_market_type_from_symbol(asset_name: str) -> str:
    symbol = normalize_quotex_symbol(asset_name)
    base_symbol = symbol[:-4] if symbol.endswith("-OTC") else symbol
    if symbol.endswith("-OTC") and len(base_symbol) == 6 and base_symbol.isalpha():
        return "otc"
    if len(base_symbol) == 6 and base_symbol.isalpha():
        return "regular"
    if symbol.startswith(("BTC", "ETH", "ADA", "SOL", "XRP", "LTC", "DOGE", "BNB")):
        return "crypto"
    return "other"


def is_tradingview_supported(asset_name: str, market_type: str) -> bool:
    normalized = normalize_quotex_symbol(asset_name)
    base_symbol = normalized[:-4] if normalized.endswith("-OTC") else normalized
    if market_type in {"regular", "otc"}:
        return len(base_symbol) == 6 and base_symbol.isalpha()
    if market_type == "crypto":
        return base_symbol.endswith("USD") or base_symbol.endswith("USDT")
    return False


def quotex_symbol_to_display_name(asset_name: str) -> str:
    symbol = normalize_quotex_symbol(asset_name)
    is_otc = symbol.endswith("-OTC")
    base_symbol = symbol[:-4] if is_otc else symbol

    if len(base_symbol) == 6 and base_symbol.isalpha():
        display = f"{base_symbol[:3]}/{base_symbol[3:]}"
    elif base_symbol.endswith("USD") and len(base_symbol) > 3:
        display = f"{base_symbol[:-3]}/USD"
    else:
        display = base_symbol

    return f"{display} OTC" if is_otc else display


def quotex_symbol_to_pair_key(asset_name: str) -> str:
    symbol = normalize_quotex_symbol(asset_name)
    is_otc = symbol.endswith("-OTC")
    base_symbol = symbol[:-4] if is_otc else symbol
    if len(base_symbol) == 6 and base_symbol.isalpha():
        key = f"{base_symbol[:3]}/{base_symbol[3:]}"
    elif base_symbol.endswith("USD") and len(base_symbol) > 3:
        key = f"{base_symbol[:-3]}/USD"
    else:
        key = base_symbol
    return f"{key}_otc" if is_otc else key


def infer_tradingview_symbol(asset_name: str, market_type: str) -> Tuple[str, str, str]:
    normalized = normalize_quotex_symbol(asset_name)
    base_symbol = normalized[:-4] if normalized.endswith("-OTC") else normalized

    if market_type == "crypto":
        tv_symbol = base_symbol if base_symbol.endswith("USDT") else f"{base_symbol[:-3]}USDT" if base_symbol.endswith("USD") else base_symbol
        return tv_symbol, "crypto", "BINANCE"

    exchange = "FX_IDC" if market_type in {"regular", "otc"} else "OANDA"
    return re.sub(r"[^A-Z]", "", base_symbol), "forex", exchange


def parse_possible_payout(raw_value: Any):
    try:
        if raw_value is None:
            return None
        if isinstance(raw_value, str):
            raw_value = raw_value.replace("%", "").strip()
        payout = float(raw_value)
        if payout <= 0:
            return None
        return payout * 100 if payout <= 1 else payout
    except Exception:
        return None


def payload_flag_is_open(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return True
    for key in ("open", "is_open", "enabled", "active", "available", "tradable"):
        if key in payload:
            return bool(payload.get(key))
    return True


def looks_like_asset_symbol(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = normalize_quotex_symbol(value)
    if len(normalized) < 6 or len(normalized) > 20:
        return False
    return bool(re.fullmatch(r"[A-Z0-9-]+", normalized)) and any(ch.isalpha() for ch in normalized)


def collect_live_assets_from_payload(payload: Any, bucket: Dict[str, Dict[str, Any]]) -> None:
    if payload is None:
        return

    if isinstance(payload, str):
        if looks_like_asset_symbol(payload):
            normalized = normalize_quotex_symbol(payload)
            bucket.setdefault(normalized, {"symbol": normalized, "is_open": True, "payout": None})
        return

    if isinstance(payload, (list, tuple, set)):
        for item in payload:
            collect_live_assets_from_payload(item, bucket)
        return

    if not isinstance(payload, dict):
        return

    named_symbol = payload.get("asset") or payload.get("name") or payload.get("symbol") or payload.get("pair")
    named_payout = payload.get("payout") or payload.get("profit") or payload.get("return") or payload.get("payment")
    if named_symbol and looks_like_asset_symbol(named_symbol) and payload_flag_is_open(payload):
        normalized = normalize_quotex_symbol(named_symbol)
        bucket[normalized] = {
            "symbol": normalized,
            "is_open": True,
            "payout": parse_possible_payout(named_payout),
        }

    for key, value in payload.items():
        if looks_like_asset_symbol(key) and payload_flag_is_open(value):
            normalized = normalize_quotex_symbol(key)
            payout = value.get("payout") if isinstance(value, dict) else None
            bucket[normalized] = {
                "symbol": normalized,
                "is_open": True,
                "payout": parse_possible_payout(payout),
            }
        collect_live_assets_from_payload(value, bucket)


def register_live_pair(
    asset_symbol: str,
    pairs: Dict[str, Dict[str, Any]],
    live_pair_registry: Dict[str, Dict[str, Any]],
    payout=None,
) -> Dict[str, Any]:
    normalized = normalize_quotex_symbol(asset_symbol)
    callback_id = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:10]

    for pair_key, pair_info in pairs.items():
        if normalize_quotex_symbol(pair_info["quotex_symbol"]) == normalized:
            pairdict = dict(pair_info)
            pairdict.setdefault("tv_supported", True)
            live_pair_registry[callback_id] = {
                "callback_id": callback_id,
                "pair_key": pair_key,
                "display_name": quotex_symbol_to_display_name(normalized),
                "market_type": pairdict["type"],
                "pairdict": pairdict,
                "payout": payout,
                "quotex_symbol": normalized,
                "quotex_api_symbol": quotex_symbol_to_api_symbol(normalized),
            }
            return live_pair_registry[callback_id]

    market_type = infer_market_type_from_symbol(normalized)
    tv_symbol, screener, exchange = infer_tradingview_symbol(normalized, market_type)
    pairdict = {
        "symbol": tv_symbol,
        "screener": screener,
        "exchange": exchange,
        "quotex_symbol": normalized,
        "type": market_type,
        "tv_supported": is_tradingview_supported(normalized, market_type),
    }
    live_pair_registry[callback_id] = {
        "callback_id": callback_id,
        "pair_key": quotex_symbol_to_pair_key(normalized),
        "display_name": quotex_symbol_to_display_name(normalized),
        "market_type": market_type,
        "pairdict": pairdict,
        "payout": payout,
        "quotex_symbol": normalized,
        "quotex_api_symbol": quotex_symbol_to_api_symbol(normalized),
    }
    return live_pair_registry[callback_id]


def fallback_live_assets(
    category: str,
    pairs: Dict[str, Dict[str, Any]],
    live_pair_registry: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    entries = []
    for pair_key, pair_info in pairs.items():
        if pair_info["type"] not in {"regular", "otc"}:
            continue
        if category != "all" and pair_info["type"] != category:
            continue
        entry = register_live_pair(pair_info["quotex_symbol"], pairs, live_pair_registry)
        entry["pair_key"] = pair_key
        entries.append(entry)
    return sorted(entries, key=lambda item: item["display_name"])

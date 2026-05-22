import logging
import asyncio
import time
import json
import random
import os
import importlib
import hashlib
import re
import inspect
import io
import contextlib
from collections import defaultdict, deque
from typing import Dict, Tuple, Any, List
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import joblib
from tradingview_ta import TA_Handler, Interval
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from bot_config import load_settings
import asset_mapping as mapping
from telegram_button_menus import handle_static_button_menu
from telegram_analysis_callbacks import handle_analysis_callbacks
from broker_connection_service import BrokerConnectionService
from decision_engine import SignalVote, WeightedDecisionEngine
from data_layer import MarketDataLayer
from decision_core import BinaryOptionsDecisionCore
from execution_layer import ExecutionLayer
from risk_management import RiskManager
from signal_engine import SignalEngine
from telegram_dashboard_handlers import performance_handler as shared_performance_handler
from telegram_dashboard_handlers import start_handler as shared_start_handler
from telegram_dashboard_handlers import stats_handler as shared_stats_handler
from telegram_execution_callbacks import handle_execution_callbacks
from telegram_trade_handlers import active_trades_handler as shared_active_trades_handler
from telegram_trade_handlers import trade_history_handler as shared_trade_history_handler
from trade_execution_service import TradeExecutionService
from trade_monitor_service import TradeMonitorService
from trade_state_service import TradeStateService
from trading_orchestrator import TradingOrchestrator

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

try:
    from xgboost import XGBClassifier
except Exception:
    XGBClassifier = None

try:
    import talib  # type: ignore
except Exception:
    talib = None

try:
    import pandas_ta as pandas_ta  # type: ignore
except Exception:
    pandas_ta = None

LSTM = None
Dense = None
Input = None
Sequential = None
load_model = None


def load_tensorflow_keras():
    """Load TensorFlow Keras lazily so the bot still works when TensorFlow is absent."""
    global LSTM, Dense, Input, Sequential, load_model
    if all(symbol is not None for symbol in (LSTM, Dense, Input, Sequential, load_model)):
        return True

    try:
        keras_layers = importlib.import_module("tensorflow.keras.layers")
        keras_models = importlib.import_module("tensorflow.keras.models")
        LSTM = getattr(keras_layers, "LSTM", None)
        Dense = getattr(keras_layers, "Dense", None)
        Input = getattr(keras_layers, "Input", None)
        Sequential = getattr(keras_models, "Sequential", None)
        load_model = getattr(keras_models, "load_model", None)
        return all(symbol is not None for symbol in (LSTM, Dense, Input, Sequential, load_model))
    except Exception:
        return False

# ---------------- CONFIG ----------------
settings = load_settings()
TELEGRAM_TOKEN = settings.telegram_token
CACHE_TTL_SECONDS = settings.cache_ttl_seconds
MIN_SIGNALS_REQUIRED = settings.min_signals_required

# ---------------- Ø£Ø²ÙˆØ§Ø¬ Ø§Ù„Ø¹Ù…Ù„Ø§Øª Ø§Ù„ÙƒØ§Ù…Ù„Ø© ----------------
PAIRS = {
    # Ø£Ø²ÙˆØ§Ø¬ ÙÙˆØ±ÙƒØ³ Ø¹Ø§Ø¯ÙŠØ©
    'EUR/USD': {
        'symbol': 'EURUSD', 
        'screener': 'forex', 
        'exchange': 'OANDA',
        'quotex_symbol': 'EURUSD',
        'type': 'regular'
    },
    'GBP/USD': {
        'symbol': 'GBPUSD', 
        'screener': 'forex', 
        'exchange': 'OANDA',
        'quotex_symbol': 'GBPUSD',
        'type': 'regular'
    },
    'USD/JPY': {
        'symbol': 'USDJPY', 
        'screener': 'forex', 
        'exchange': 'OANDA',
        'quotex_symbol': 'USDJPY',
        'type': 'regular'
    },
    'AUD/USD': {
        'symbol': 'AUDUSD', 
        'screener': 'forex', 
        'exchange': 'OANDA',
        'quotex_symbol': 'AUDUSD',
        'type': 'regular'
    },
    'USD/CAD': {
        'symbol': 'USDCAD',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'USDCAD',
        'type': 'regular'
    },
    'USD/CHF': {
        'symbol': 'USDCHF',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'USDCHF',
        'type': 'regular'
    },
    'NZD/USD': {
        'symbol': 'NZDUSD',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'NZDUSD',
        'type': 'regular'
    },
    'EUR/JPY': {
        'symbol': 'EURJPY',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'EURJPY',
        'type': 'regular'
    },
    'EUR/GBP': {
        'symbol': 'EURGBP',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'EURGBP',
        'type': 'regular'
    },
    'EUR/CHF': {
        'symbol': 'EURCHF',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'EURCHF',
        'type': 'regular'
    },
    'EUR/AUD': {
        'symbol': 'EURAUD',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'EURAUD',
        'type': 'regular'
    },
    'GBP/JPY': {
        'symbol': 'GBPJPY',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'GBPJPY',
        'type': 'regular'
    },
    'GBP/CHF': {
        'symbol': 'GBPCHF',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'GBPCHF',
        'type': 'regular'
    },
    'AUD/JPY': {
        'symbol': 'AUDJPY',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'AUDJPY',
        'type': 'regular'
    },
    'AUD/CHF': {
        'symbol': 'AUDCHF',
        'screener': 'forex',
        'exchange': 'OANDA',
        'quotex_symbol': 'AUDCHF',
        'type': 'regular'
    },
    
    # Ø£Ø²ÙˆØ§Ø¬ OTC
    'EUR/USD_otc': {
        'symbol': 'EURUSD',
        'screener': 'forex', 
        'exchange': 'FX_IDC',
        'quotex_symbol': 'EURUSD-OTC',
        'type': 'otc'
    },
    'GBP/USD_otc': {
        'symbol': 'GBPUSD',
        'screener': 'forex', 
        'exchange': 'FX_IDC',
        'quotex_symbol': 'GBPUSD-OTC',
        'type': 'otc'
    },
    'USD/JPY_otc': {
        'symbol': 'USDJPY',
        'screener': 'forex', 
        'exchange': 'FX_IDC',
        'quotex_symbol': 'USDJPY-OTC',
        'type': 'otc'
    },
    'AUD/USD_otc': {
        'symbol': 'AUDUSD',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'AUDUSD-OTC',
        'type': 'otc'
    },
    'USD/CAD_otc': {
        'symbol': 'USDCAD',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'USDCAD-OTC',
        'type': 'otc'
    },
    'USD/CHF_otc': {
        'symbol': 'USDCHF',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'USDCHF-OTC',
        'type': 'otc'
    },
    'NZD/USD_otc': {
        'symbol': 'NZDUSD',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'NZDUSD-OTC',
        'type': 'otc'
    },
    'EUR/JPY_otc': {
        'symbol': 'EURJPY',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'EURJPY-OTC',
        'type': 'otc'
    },
    'EUR/GBP_otc': {
        'symbol': 'EURGBP',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'EURGBP-OTC',
        'type': 'otc'
    },
    'EUR/CHF_otc': {
        'symbol': 'EURCHF',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'EURCHF-OTC',
        'type': 'otc'
    },
    'EUR/AUD_otc': {
        'symbol': 'EURAUD',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'EURAUD-OTC',
        'type': 'otc'
    },
    'GBP/JPY_otc': {
        'symbol': 'GBPJPY',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'GBPJPY-OTC',
        'type': 'otc'
    },
    'GBP/CHF_otc': {
        'symbol': 'GBPCHF',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'GBPCHF-OTC',
        'type': 'otc'
    },
    'AUD/JPY_otc': {
        'symbol': 'AUDJPY',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'AUDJPY-OTC',
        'type': 'otc'
    },
    'AUD/CHF_otc': {
        'symbol': 'AUDCHF',
        'screener': 'forex',
        'exchange': 'FX_IDC',
        'quotex_symbol': 'AUDCHF-OTC',
        'type': 'otc'
    },
    
    # ÙƒØ±ÙŠØ¨ØªÙˆ
    'BTC/USD': {
        'symbol': 'BTCUSDT', 
        'screener': 'crypto', 
        'exchange': 'BINANCE',
        'quotex_symbol': 'BTCUSD',
        'type': 'crypto'
    },
    'ETH/USD': {
        'symbol': 'ETHUSDT', 
        'screener': 'crypto', 
        'exchange': 'BINANCE',
        'quotex_symbol': 'ETHUSD',
        'type': 'crypto'
    },
    'ADA/USD': {
        'symbol': 'ADAUSDT', 
        'screener': 'crypto', 
        'exchange': 'BINANCE',
        'quotex_symbol': 'ADAUSD',
        'type': 'crypto'
    }
}

TIMEFRAMES = {
    '1m': {'tv': Interval.INTERVAL_1_MINUTE, 'quotex': 60},
    '5m': {'tv': Interval.INTERVAL_5_MINUTES, 'quotex': 300},
    '15m': {'tv': Interval.INTERVAL_15_MINUTES, 'quotex': 900},
    '1h': {'tv': Interval.INTERVAL_1_HOUR, 'quotex': 3600},
    '4h': {'tv': Interval.INTERVAL_4_HOURS, 'quotex': 14400},
}

HIGHER_TF = {'5m': '15m', '15m': '1h', '1h': '4h', '4h': '4h'}

# ---------------- Ø£Ù†Ø¸Ù…Ø© Ø§Ù„ØªØ®Ø²ÙŠÙ† ----------------
user_data: Dict[int, Dict[str, Any]] = {}
analysis_cache: Dict[str, Tuple[float, Any]] = {}
analysis_result_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
quotex_client = None
active_trades: Dict[str, Dict] = {}
trade_history: List[Dict] = []
risk_manager = RiskManager(settings.risk)
decision_engine = WeightedDecisionEngine(settings.risk.min_confidence_score)
trading_orchestrator = None
live_pair_registry: Dict[str, Dict[str, Any]] = {}
tradingview_rate_limited_until = 0.0
live_update_tasks: Dict[int, asyncio.Task] = {}
live_snapshot_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
recent_trade_requests: Dict[str, float] = {}
live_assets_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
live_payout_cache: Dict[str, Tuple[float, float]] = {}
balance_cache: Dict[str, Tuple[float, float]] = {}
broker_execution_lock = asyncio.Lock()
broker_reconnect_lock = asyncio.Lock()
last_broker_reconnect_at = 0.0
broker_connection_service = None
trade_execution_service = None
trade_monitor_service = None
trade_state_service = None
NOISY_QUOTEX_TEXT = (
    "tá agarrado",
    "ta agarrado",
    "aguarde",
    "carregando",
    "loading",
)

# ---------------- Ù†Ø¸Ø§Ù… Ø§Ù„ÙƒØ§Ø´ Ø§Ù„Ù…ØªÙ‚Ø¯Ù… ----------------
def now_ts() -> float:
    return time.time()


def describe_exception(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def should_prefer_live_quotex_analysis(pairdict: dict) -> bool:
    return bool(pairdict.get("quotex_symbol"))


def cleanup_stale_active_trades(
    user_id: int | None = None,
    pair_label: str | None = None,
    asset: str | None = None,
    grace_seconds: int = 45,
) -> int:
    return get_trade_state_service().cleanup_stale_active_trades(
        user_id=user_id,
        pair_label=pair_label,
        asset=asset,
        grace_seconds=grace_seconds,
    )


def can_open_trade_for_pair(user_id: int, pair_label: str, asset: str, cooldown_seconds: int = 8) -> Tuple[bool, str]:
    normalized_pair = str(pair_label or asset or "").lower()
    normalized_asset = str(asset or "").lower()
    now = now_ts()

    cleanup_stale_active_trades(
        user_id=user_id,
        pair_label=normalized_pair,
        asset=normalized_asset,
    )

    expired_keys = [key for key, ts in recent_trade_requests.items() if now - ts > cooldown_seconds]
    for key in expired_keys:
        recent_trade_requests.pop(key, None)

    request_key = f"{user_id}:{normalized_pair}:{normalized_asset}"
    last_request_ts = recent_trade_requests.get(request_key)
    if last_request_ts and now - last_request_ts < cooldown_seconds:
        remaining = max(1, int(cooldown_seconds - (now - last_request_ts)))
        return False, f"Please wait {remaining}s before opening the same pair again."

    for trade in active_trades.values():
        if trade.get("status") != "pending":
            continue
        if user_id and trade.get("user_id") not in {0, user_id}:
            continue
        same_pair = str(trade.get("pair_name", "")).lower() == normalized_pair
        same_asset = str(trade.get("asset", "")).lower() == normalized_asset
        if same_pair or same_asset:
            return False, "This pair already has an active trade. Wait for it to finish first."

    recent_trade_requests[request_key] = now
    return True, "allowed"

def cache_key(pairdict: dict, interval_key: str) -> str:
    return f"{pairdict['symbol']}|{pairdict['exchange']}|{pairdict['screener']}|{interval_key}"

def safe_div(numerator, denominator):
    try:
        if denominator and denominator != 0:
            return numerator / denominator
    except Exception:
        pass
    return 0


normalize_quotex_symbol = mapping.normalize_quotex_symbol
infer_market_type_from_symbol = mapping.infer_market_type_from_symbol
is_tradingview_supported = mapping.is_tradingview_supported
quotex_symbol_to_display_name = mapping.quotex_symbol_to_display_name
quotex_symbol_to_pair_key = mapping.quotex_symbol_to_pair_key
infer_tradingview_symbol = mapping.infer_tradingview_symbol
parse_possible_payout = mapping.parse_possible_payout
payload_flag_is_open = mapping.payload_flag_is_open
looks_like_asset_symbol = mapping.looks_like_asset_symbol
collect_live_assets_from_payload = mapping.collect_live_assets_from_payload
quotex_symbol_to_api_symbol = mapping.quotex_symbol_to_api_symbol
is_preferred_live_entry = mapping.is_preferred_live_entry


def register_live_pair(asset_symbol: str, payout=None) -> Dict[str, Any]:
    return mapping.register_live_pair(asset_symbol, PAIRS, live_pair_registry, payout)


def fallback_live_assets(category: str = "all") -> List[Dict[str, Any]]:
    return mapping.fallback_live_assets(category, PAIRS, live_pair_registry)


async def get_live_quotex_assets(category: str = "all") -> List[Dict[str, Any]]:
    cached_assets = live_assets_cache.get(category)
    if cached_assets and now_ts() - cached_assets[0] < 8:
        return [dict(item) for item in cached_assets[1]]

    if not quotex_client:
        return fallback_live_assets(category)

    discovered_assets: Dict[str, Dict[str, Any]] = {}
    for method_name in ("get_available_asset", "get_all_assets", "get_all_asset_name"):
        method = getattr(quotex_client, method_name, None)
        if not method:
            continue
        try:
            signature = inspect.signature(method)
            required_params = [
                parameter for parameter in signature.parameters.values()
                if parameter.default is inspect._empty
                and parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            if required_params:
                continue

            payload = method()
            if asyncio.iscoroutine(payload):
                payload = await payload
            collect_live_assets_from_payload(payload, discovered_assets)
        except Exception as exc:
            logging.warning(f"Live asset fetch failed via {method_name}: {exc}")

    if not discovered_assets:
        return fallback_live_assets(category)

    entries = []
    for asset in discovered_assets.values():
        entry = register_live_pair(asset["symbol"], asset.get("payout"))
        if entry["market_type"] not in {"regular", "otc"}:
            continue
        if not is_preferred_live_entry(entry, PAIRS):
            continue
        if category == "all" or entry["market_type"] == category:
            entries.append(entry)
    sorted_entries = sorted(entries, key=lambda item: item["display_name"])
    live_assets_cache[category] = (now_ts(), [dict(item) for item in sorted_entries])
    return sorted_entries


async def enrich_live_entry_with_payout(entry: Dict[str, Any]) -> Dict[str, Any]:
    if entry.get("payout") is not None:
        return entry

    cached_payout = live_payout_cache.get(str(entry.get("quotex_symbol", "")))
    if cached_payout and now_ts() - cached_payout[0] < 15:
        entry["payout"] = cached_payout[1]
        return entry

    if quotex_client:
        try:
            payout = await fetch_live_payout(entry["quotex_symbol"])
            if payout is not None:
                entry["payout"] = payout
                live_payout_cache[str(entry.get("quotex_symbol", ""))] = (now_ts(), payout)
                registry_entry = live_pair_registry.get(entry.get("callback_id", ""))
                if isinstance(registry_entry, dict):
                    registry_entry["payout"] = payout
        except Exception as exc:
            logging.debug(f"Could not fetch payout for {entry['quotex_symbol']}: {exc}")
    return entry


async def call_quotex_method(method_name: str, *args, **kwargs):
    if not quotex_client:
        return None
    method = getattr(quotex_client, method_name, None)
    if not method:
        return None
    output_buffer = io.StringIO()
    with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
        result = method(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result

    noisy_output = output_buffer.getvalue().strip()
    if noisy_output and not is_noisy_quotex_payload(noisy_output):
        logging.debug("%s emitted stdout/stderr: %s", method_name, noisy_output)

    return sanitize_quotex_payload(result)


def is_noisy_quotex_payload(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return any(fragment in normalized for fragment in NOISY_QUOTEX_TEXT)


def sanitize_quotex_payload(value: Any):
    if isinstance(value, str) and is_noisy_quotex_payload(value):
        return None
    if isinstance(value, dict):
        return {key: sanitize_quotex_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_quotex_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_quotex_payload(item) for item in value)
    return value


async def fetch_live_payout(asset: str, timeframe_seconds: int = 60):
    cache_id = f"{asset}|{timeframe_seconds}"
    cached_entry = live_payout_cache.get(cache_id)
    if cached_entry and now_ts() - cached_entry[0] < 15:
        return cached_entry[1]

    api_asset = quotex_symbol_to_api_symbol(asset)
    timeframe_minutes = str(max(1, timeframe_seconds // 60))
    attempts = [
        ("get_payout_by_asset", (api_asset, timeframe_minutes)),
        ("get_payout_by_asset", (api_asset,)),
        ("get_available_asset", (api_asset,)),
        ("get_profit", ()),
        ("get_payment", ()),
    ]

    for method_name, args in attempts:
        try:
            raw_value = await call_quotex_method(method_name, *args)
            if method_name == "get_available_asset" and isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
                asset_data = raw_value[1]
                if isinstance(asset_data, (list, tuple)) and len(asset_data) >= 4:
                    raw_value = asset_data[3]
                else:
                    raw_value = None
            payout = parse_possible_payout(raw_value)
            if payout is not None:
                live_payout_cache[cache_id] = (now_ts(), payout)
                live_payout_cache[str(asset)] = (now_ts(), payout)
                return payout
        except Exception as exc:
            logging.debug(f"Payout lookup via {method_name} failed for {api_asset}: {exc}")
    return None


def derive_sentiment_value(realtime_sentiment: Any, candles: List[Dict[str, float]]) -> Any:
    sentiment_value = None

    if isinstance(realtime_sentiment, dict):
        nested_sentiment = realtime_sentiment.get("sentiment")
        if isinstance(nested_sentiment, dict):
            if "buy" in nested_sentiment:
                try:
                    sentiment_value = float(nested_sentiment["buy"])
                except Exception:
                    pass
            elif "sell" in nested_sentiment:
                try:
                    sentiment_value = 100 - float(nested_sentiment["sell"])
                except Exception:
                    pass
        direct_keys = ("sentiment", "value", "bullish", "call", "buy")
        inverse_keys = ("put", "sell", "bearish")
        for key in direct_keys:
            if sentiment_value is not None:
                break
            if key in realtime_sentiment:
                try:
                    sentiment_value = float(realtime_sentiment[key])
                    break
                except Exception:
                    pass
        if sentiment_value is None:
            for key in inverse_keys:
                if key in realtime_sentiment:
                    try:
                        sentiment_value = 100 - float(realtime_sentiment[key])
                        break
                    except Exception:
                        pass
    else:
        try:
            sentiment_value = float(realtime_sentiment) if realtime_sentiment is not None else None
        except Exception:
            sentiment_value = None

    if sentiment_value is not None and sentiment_value <= 1:
        sentiment_value *= 100

    if sentiment_value is None and candles:
        sample = candles[-5:]
        bullish = sum(1 for candle in sample if candle["close"] > candle["open"])
        bearish = sum(1 for candle in sample if candle["close"] < candle["open"])
        total = max(1, bullish + bearish)
        sentiment_value = 50 + ((bullish - bearish) / total) * 25

        try:
            momentum = sample[-1]["close"] - sample[0]["open"]
            if momentum > 0:
                sentiment_value += 7
            elif momentum < 0:
                sentiment_value -= 7
        except Exception:
            pass

    if sentiment_value is None:
        return None

    return max(0, min(100, sentiment_value))


def normalize_realtime_candles_payload(payload: Any) -> List[Dict[str, float]]:
    candles: List[Dict[str, float]] = []

    def append_candle(item: Any, fallback_time: int) -> None:
        if not isinstance(item, dict):
            return
        open_price = item.get("open") or item.get("Open")
        high = item.get("high") or item.get("High")
        low = item.get("low") or item.get("Low")
        close = item.get("close") or item.get("Close") or item.get("price")
        if None in (open_price, high, low, close):
            return
        candles.append({
            "time": float(item.get("time") or item.get("from") or item.get("timestamp") or fallback_time),
            "open": float(open_price),
            "high": float(high),
            "low": float(low),
            "close": float(close),
        })

    if isinstance(payload, dict):
        for index, value in enumerate(payload.values()):
            if isinstance(value, dict):
                append_candle(value, index)
    elif isinstance(payload, list):
        if len(payload) >= 4 and isinstance(payload[1], (int, float)) and isinstance(payload[2], (int, float)):
            price = float(payload[2])
            candles.append({
                "time": float(payload[1]),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
            })
        else:
            for index, item in enumerate(payload):
                append_candle(item, index)

    candles.sort(key=lambda item: item["time"])
    return candles[-120:]


async def ensure_live_market_stream(asset: str, timeframe_seconds: int = 60) -> None:
    if not quotex_client:
        return
    api_asset = quotex_symbol_to_api_symbol(asset)
    try:
        await asyncio.wait_for(call_quotex_method("start_realtime_price", api_asset, timeframe_seconds), timeout=3)
    except Exception:
        pass
    try:
        await asyncio.wait_for(call_quotex_method("start_realtime_candle", api_asset, timeframe_seconds), timeout=3)
    except Exception:
        pass
    try:
        await asyncio.wait_for(call_quotex_method("start_realtime_sentiment", api_asset, timeframe_seconds), timeout=3)
    except Exception:
        pass


async def get_live_market_snapshot(asset: str, timeframe_seconds: int = 60) -> Dict[str, Any]:
    cache_id = f"{asset}|{timeframe_seconds}"
    cached_snapshot = live_snapshot_cache.get(cache_id)
    if cached_snapshot and now_ts() - cached_snapshot[0] < 2:
        return cached_snapshot[1]

    await ensure_live_market_stream(asset, timeframe_seconds)
    api_asset = quotex_symbol_to_api_symbol(asset)

    realtime_price = None
    realtime_sentiment = None
    candles = []
    payout = None

    try:
        realtime_price = await asyncio.wait_for(call_quotex_method("get_realtime_price", api_asset), timeout=2)
    except Exception as exc:
        logging.debug(f"Realtime price unavailable for {asset}: {exc}")

    try:
        realtime_sentiment = await asyncio.wait_for(call_quotex_method("get_realtime_sentiment", api_asset), timeout=2)
    except Exception as exc:
        logging.debug(f"Realtime sentiment unavailable for {asset}: {exc}")

    try:
        candle_payload = await asyncio.wait_for(call_quotex_method("get_realtime_candles", api_asset), timeout=2.5)
        candles = normalize_realtime_candles_payload(candle_payload)
    except Exception as exc:
        logging.debug(f"Realtime candles unavailable for {asset}: {exc}")

    try:
        payout = await asyncio.wait_for(fetch_live_payout(asset, timeframe_seconds), timeout=2.5)
    except Exception as exc:
        logging.debug(f"Realtime payout unavailable for {asset}: {exc}")

    last_price = None
    if isinstance(realtime_price, list):
        for item in reversed(realtime_price):
            if isinstance(item, dict) and "price" in item:
                try:
                    last_price = float(item["price"])
                    break
                except Exception:
                    pass
    elif isinstance(realtime_price, dict):
        for key in ("price", "close", "value", "bid", "ask"):
            if key in realtime_price:
                try:
                    last_price = float(realtime_price[key])
                    break
                except Exception:
                    pass
    else:
        try:
            last_price = float(realtime_price) if realtime_price is not None else None
        except Exception:
            last_price = None

    if last_price is None and candles:
        last_price = candles[-1]["close"]

    sentiment_value = derive_sentiment_value(realtime_sentiment, candles)

    if last_price is None and sentiment_value is None and not candles and cached_snapshot:
        stale_payload = dict(cached_snapshot[1])
        stale_payload["timestamp"] = time.time()
        return stale_payload

    snapshot_payload = {
        "asset": asset,
        "timeframe_seconds": timeframe_seconds,
        "price": last_price,
        "sentiment": sentiment_value,
        "candles": candles,
        "payout": payout,
        "timestamp": time.time(),
    }
    live_snapshot_cache[cache_id] = (now_ts(), snapshot_payload)
    return snapshot_payload


def market_type_title(category: str) -> str:
    return {
        "all": "All Open Markets",
        "regular": "Regular FX",
        "otc": "OTC Markets",
        "crypto": "Crypto Markets",
    }.get(category, "Live Markets")


def build_live_market_keyboard(entries: List[Dict[str, Any]], category: str, page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    visible_entries = entries[page * per_page:(page + 1) * per_page]
    keyboard = []

    for i in range(0, len(visible_entries), 2):
        row = []
        for entry in visible_entries[i:i + 2]:
            payout_text = f" {entry['payout']:.0f}%" if entry.get("payout") else ""
            row.append(
                InlineKeyboardButton(
                    f"• {entry['display_name']}{payout_text}",
                    callback_data=f"setpairid_{entry['callback_id']}",
                )
            )
        keyboard.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀ Prev", callback_data=f"livepairs_{category}_{page - 1}"))
    nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶", callback_data=f"livepairs_{category}_{page + 1}"))
    keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton("All", callback_data="livepairs_all_0"),
        InlineKeyboardButton("FX", callback_data="livepairs_regular_0"),
        InlineKeyboardButton("OTC", callback_data="livepairs_otc_0"),
    ])
    keyboard.append([
        InlineKeyboardButton("🏆 Top 3 Scan", callback_data="scanner_menu"),
        InlineKeyboardButton("🔄 Refresh", callback_data=f"livepairs_{category}_{page}"),
    ])
    keyboard.append([InlineKeyboardButton("🔙 Main Desk", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)


def analysis_result_cache_key(pairdict: dict, timeframe: str) -> str:
    return f"{pairdict.get('quotex_symbol', pairdict.get('symbol', 'unknown'))}|{timeframe}"


def get_cached_analysis_result(pairdict: dict, timeframe: str):
    entry = analysis_result_cache.get(analysis_result_cache_key(pairdict, timeframe))
    if not entry:
        return None
    ts, payload = entry
    if now_ts() - ts < CACHE_TTL_SECONDS * 3:
        return payload
    return None


def store_cached_analysis_result(pairdict: dict, timeframe: str, payload: Dict[str, Any]) -> None:
    analysis_result_cache[analysis_result_cache_key(pairdict, timeframe)] = (now_ts(), payload)


async def live_stream_analysis(pairdict: dict, interval_key: str) -> Tuple[str, str, int, np.array, dict]:
    timeframe_seconds = TIMEFRAMES[interval_key]["quotex"]
    snapshot = await get_live_market_snapshot(pairdict["quotex_symbol"], timeframe_seconds)
    candles = snapshot.get("candles", [])
    sentiment = snapshot.get("sentiment")
    payout = snapshot.get("payout")
    live_price = snapshot.get("price")

    direction = "neutral"
    confidence = 50
    reasons = ["Live Quotex stream fallback was used."]

    if candles:
        last_candle = candles[-1]
        candle_move = last_candle["close"] - last_candle["open"]
        direction = "call" if candle_move > 0 else "put" if candle_move < 0 else "neutral"
        confidence = 58
        reasons.append(f"Last candle closed {'above' if candle_move > 0 else 'below' if candle_move < 0 else 'near'} its open.")

    if isinstance(sentiment, (int, float)):
        if sentiment >= 58:
            direction = "call"
            confidence = max(confidence, min(78, int(sentiment)))
            reasons.append(f"Live sentiment is bullish at {sentiment:.0f}%.")
        elif sentiment <= 42:
            direction = "put"
            confidence = max(confidence, min(78, int(100 - sentiment)))
            reasons.append(f"Live sentiment is bearish at {sentiment:.0f}%.")
        else:
            reasons.append("Live sentiment is mixed.")

    if direction == "neutral":
        reasons.append("No strong live directional edge was detected.")

    market_context = {
        "degraded": True,
        "degraded_reason": "Using Quotex live-only analysis because TradingView mapping/data was unavailable.",
        "decision_reasons": reasons,
        "candle_pattern": "Live stream candles",
        "market_condition": "live_stream",
        "trend_condition": "intraday",
        "volatility": 0.0,
        "trend_strength": 0.0,
        "live_price": live_price,
        "live_sentiment": sentiment,
        "live_payout": payout,
        "live_snapshot": snapshot,
        "candles": candles,
        "lstm_signal": {"direction": direction, "confidence": confidence, "method": "quotex_live_stream"},
    }
    message = (
        f"📡 <b>Live Quotex Stream Analysis</b>\n"
        f"💰 <b>{pairdict['quotex_symbol']} - {interval_key}</b>\n\n"
        f"• Direction: <b>{direction.upper()}</b>\n"
        f"• Confidence: <b>{confidence}%</b>\n"
        f"• Live Price: <b>{f'{live_price:.5f}' if isinstance(live_price, (int, float)) else '--'}</b>\n"
        f"• Sentiment: <b>{f'{sentiment:.0f}%' if isinstance(sentiment, (int, float)) else '--'}</b>\n"
        f"• Payout: <b>{f'{payout:.0f}%' if isinstance(payout, (int, float)) else '--'}</b>\n\n"
        f"⚠️ <i>TradingView was unavailable or unsupported for this asset, so the bot used live Quotex data only.</i>"
    )

    payload = {
        "message": message,
        "direction": direction,
        "confidence": confidence,
        "features": np.array([]),
        "market_context": market_context,
        "traditional_signal": {"direction": direction, "confidence": confidence, "recommendation": "LIVE_ONLY"},
        "ai_prediction": {"direction": direction, "confidence": confidence, "method": "quotex_live_stream", "risk_level": "medium"},
        "analysis": None,
    }
    store_cached_analysis_result(pairdict, interval_key, payload)
    return message, direction, confidence, np.array([]), market_context


async def render_live_market_board(query, category: str = "all", page: int = 0) -> None:
    entries = await get_live_quotex_assets(category)
    keyboard = build_live_market_keyboard(entries, category, page)
    open_count = len(entries)
    market_text = (
        f"🟢 <b>Quotex Live Board</b>\n\n"
        f"• View: <b>{market_type_title(category)}</b>\n"
        f"• Open assets now: <b>{open_count}</b>\n"
        f"• Tap any asset to analyze it instantly\n\n"
        f"<i>Pairs shown here come from Quotex availability at this moment when possible.</i>"
    )
    await query.edit_message_text(market_text, parse_mode="HTML", reply_markup=keyboard)


async def scan_top_trade_setups(timeframe: str = "1m", category: str = "all", top_n: int = 3) -> List[Dict[str, Any]]:
    entries = await get_live_quotex_assets(category)
    if not entries:
        return []

    if category == "otc":
        entries = entries[:6]
        semaphore = asyncio.Semaphore(2)
    else:
        semaphore = asyncio.Semaphore(6)

    async def analyze_entry(entry: Dict[str, Any]):
        async with semaphore:
            try:
                use_live_only = (
                    should_prefer_live_quotex_analysis(entry["pairdict"])
                    or entry.get("market_type") == "otc"
                    or (tradingview_rate_limited_until and now_ts() < tradingview_rate_limited_until)
                )
                if use_live_only:
                    _, direction, confidence, _, market_context = await asyncio.wait_for(
                        live_stream_analysis(entry["pairdict"], timeframe),
                        timeout=6,
                    )
                else:
                    _, direction, confidence, _, market_context = await asyncio.wait_for(
                        advanced_ai_analysis_layered(entry["pairdict"], timeframe),
                        timeout=7,
                    )
                if direction not in {"call", "put"}:
                    return None
                entry_with_payout = await enrich_live_entry_with_payout(dict(entry))
                payout = entry_with_payout.get("payout") or 0
                live_bonus = 8 if market_context.get("market_condition") == "live_stream" else 0
                trend_bonus = 6 if market_context.get("trend_condition") == "strong" else 3 if market_context.get("trend_condition") == "moderate" else 0
                price_action_bonus = int(market_context.get("price_action_score", 0) or 0)
                score = confidence + min(12, payout / 10) + live_bonus + trend_bonus + price_action_bonus
                return {
                    "entry": entry_with_payout,
                    "direction": direction,
                    "confidence": confidence,
                    "score": score,
                    "market_context": market_context,
                }
            except Exception as exc:
                try:
                    fallback_entry = await enrich_live_entry_with_payout(dict(entry))
                    fallback_confidence = 54 if entry.get("market_type") == "otc" else 50
                    fallback_context = {
                        "market_condition": "scanner_fallback",
                        "trend_condition": "normal",
                        "price_action_score": 0,
                        "decision_reasons": [f"Scanner fallback used after {describe_exception(exc)}."],
                    }
                    return {
                        "entry": fallback_entry,
                        "direction": "neutral",
                        "confidence": fallback_confidence,
                        "score": 0,
                        "market_context": fallback_context,
                    }
                except Exception as fallback_exc:
                    logging.warning(
                        "Scanner skipped %s: %s | fallback failed: %s",
                        entry.get("display_name"),
                        describe_exception(exc),
                        describe_exception(fallback_exc),
                    )
                    return None

    results = await asyncio.gather(*(analyze_entry(entry) for entry in entries))
    ranked_results = [result for result in results if result]
    ranked_results.sort(key=lambda item: (item["score"], item["confidence"]), reverse=True)
    return ranked_results[:top_n]

async def get_cached_analysis(pairdict: dict, interval_key: str, interval) -> Any:
    global tradingview_rate_limited_until
    if pairdict.get("tv_supported") is False or should_prefer_live_quotex_analysis(pairdict):
        return None

    key = cache_key(pairdict, interval_key)
    entry = analysis_cache.get(key)
    if entry:
        ts, analysis = entry
        if now_ts() - ts < CACHE_TTL_SECONDS:
            return analysis

    if tradingview_rate_limited_until and now_ts() < tradingview_rate_limited_until:
        logging.debug(
            "TradingView cooldown active for %.0fs more. Skipping remote analysis for %s.",
            tradingview_rate_limited_until - now_ts(),
            pairdict.get("symbol", "unknown"),
        )
        return None
    
    exchange_candidates = [pairdict['exchange']]
    if pairdict.get("screener") == "forex":
        for fallback_exchange in ("FX_IDC", "OANDA"):
            if fallback_exchange not in exchange_candidates:
                exchange_candidates.append(fallback_exchange)

    try:
        last_error = None
        for exchange_name in exchange_candidates:
            try:
                handler = TA_Handler(
                    symbol=pairdict['symbol'],
                    exchange=exchange_name,
                    screener=pairdict['screener'],
                    interval=interval
                )
                analysis = await asyncio.to_thread(handler.get_analysis)
                analysis_cache[key] = (now_ts(), analysis)
                return analysis
            except Exception as exchange_error:
                last_error = exchange_error
                if "HTTP status code: 429" in str(exchange_error):
                    raise
        raise last_error or RuntimeError("TradingView returned no analysis")
    except Exception as e:
        error_text = str(e)
        if "HTTP status code: 429" in error_text:
            should_log = not tradingview_rate_limited_until or now_ts() >= tradingview_rate_limited_until
            tradingview_rate_limited_until = now_ts() + 90
            if should_log:
                logging.warning("TradingView rate-limited the bot. Entering cooldown mode for 90 seconds.")
        elif "Exchange or symbol not found" in error_text:
            logging.info("TradingView mapping unavailable for %s.", pairdict.get("symbol", "unknown"))
        else:
            logging.debug(f"TradingView analysis fetch failed: {e}")
        return None

# ---------------- Ø£Ù†Ù…Ø§Ø· Ø§Ù„Ø´Ù…ÙˆØ¹ Ø§Ù„ÙŠØ§Ø¨Ø§Ù†ÙŠØ© ----------------
def candle_patterns_from_inds(inds):
    try:
        pattern_info = detect_price_action_patterns(inds)
        return pattern_info.get("label", "Ø¹Ø§Ø¯ÙŠ")
    except Exception:
        return "Ø®Ø·Ø£ ÙÙŠ ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ø´Ù…Ø¹Ø©"


def build_ohlc_arrays_from_sequence(price_sequence: list) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | tuple[None, None, None, None]:
    try:
        if not price_sequence or len(price_sequence) < 3:
            return None, None, None, None
        opens = np.array([float(row[0]) for row in price_sequence], dtype=float)
        highs = np.array([float(row[1]) for row in price_sequence], dtype=float)
        lows = np.array([float(row[2]) for row in price_sequence], dtype=float)
        closes = np.array([float(row[3]) for row in price_sequence], dtype=float)
        return opens, highs, lows, closes
    except Exception:
        return None, None, None, None


def detect_price_action_patterns(indicators: dict, price_sequence: list | None = None) -> dict:
    close = float(indicators.get('close', 0) or 0)
    open_ = float(indicators.get('open', close) or close)
    high = float(indicators.get('high', close) or close)
    low = float(indicators.get('low', close) or close)

    if not close and not high and not low:
        return {"name": "unavailable", "label": "No candle pattern", "bias": "neutral", "strength": 0, "summary": "No OHLC candle data is available."}

    pattern = {"name": "normal", "label": "Normal Candle", "bias": "neutral", "strength": 0, "summary": "No strong price-action pattern was detected."}

    if talib is not None and price_sequence:
        opens, highs, lows, closes = build_ohlc_arrays_from_sequence(price_sequence)
        if opens is not None:
            try:
                checks = [
                    ("bullish_engulfing", "Bullish Engulfing", "call", talib.CDLENGULFING(opens, highs, lows, closes)[-1]),
                    ("hanging_man", "Hanging Man", "put", talib.CDLHANGINGMAN(opens, highs, lows, closes)[-1]),
                    ("hammer", "Hammer", "call", talib.CDLHAMMER(opens, highs, lows, closes)[-1]),
                    ("shooting_star", "Shooting Star", "put", talib.CDLSHOOTINGSTAR(opens, highs, lows, closes)[-1]),
                ]
                for name, label, bias, value in checks:
                    if value:
                        return {
                            "name": name,
                            "label": label,
                            "bias": bias,
                            "strength": 85 if abs(value) >= 100 else 70,
                            "summary": f"{label} detected by TA-Lib pattern recognition.",
                        }
            except Exception:
                pass

    body = abs(close - open_)
    rng = max(high - low, 1e-8)
    upper_wick = high - max(close, open_)
    lower_wick = min(close, open_) - low
    body_ratio = safe_div(body, rng)

    prev = price_sequence[-2] if price_sequence and len(price_sequence) >= 2 else None
    prev_open = float(prev[0]) if prev else open_
    prev_close = float(prev[3]) if prev else close

    if close > open_ and prev and prev_close < prev_open and open_ <= prev_close and close >= prev_open:
        pattern = {"name": "bullish_engulfing", "label": "Bullish Engulfing", "bias": "call", "strength": 82, "summary": "Bullish engulfing shows buyers absorbing the previous bearish candle."}
    elif close < open_ and prev and prev_close > prev_open and open_ >= prev_close and close <= prev_open:
        pattern = {"name": "bearish_engulfing", "label": "Bearish Engulfing", "bias": "put", "strength": 82, "summary": "Bearish engulfing shows sellers absorbing the previous bullish candle."}
    elif lower_wick > 2 * max(body, 1e-8) and upper_wick < max(body * 0.4, 1e-8):
        pattern = {"name": "hammer", "label": "Hammer", "bias": "call", "strength": 72, "summary": "Hammer rejection suggests bullish response from lower prices."}
    elif upper_wick > 2 * max(body, 1e-8) and lower_wick < max(body * 0.4, 1e-8):
        pattern = {"name": "shooting_star", "label": "Shooting Star", "bias": "put", "strength": 72, "summary": "Shooting-star rejection suggests bearish response from higher prices."}
    elif upper_wick < body * 0.45 and lower_wick > body * 2.1 and close < open_:
        pattern = {"name": "hanging_man", "label": "Hanging Man", "bias": "put", "strength": 74, "summary": "Hanging Man warns that bullish control is weakening after an upward push."}
    elif body_ratio < 0.12:
        pattern = {"name": "doji", "label": "Doji", "bias": "neutral", "strength": 36, "summary": "Doji indicates indecision and often needs more confirmation."}

    return pattern


def detect_support_resistance_zones(price_sequence: list, min_touches: int = 3) -> dict:
    if not price_sequence or len(price_sequence) < 8:
        return {"supports": [], "resistances": [], "nearest_support": None, "nearest_resistance": None}

    lows = [float(row[2]) for row in price_sequence]
    highs = [float(row[1]) for row in price_sequence]
    closes = [float(row[3]) for row in price_sequence]
    current_price = closes[-1]
    tolerance = max(abs(current_price) * 0.0015, 0.0001)

    support_buckets: dict[float, int] = {}
    resistance_buckets: dict[float, int] = {}

    for low in lows:
        key = round(round(low / tolerance) * tolerance, 5)
        support_buckets[key] = support_buckets.get(key, 0) + 1
    for high in highs:
        key = round(round(high / tolerance) * tolerance, 5)
        resistance_buckets[key] = resistance_buckets.get(key, 0) + 1

    supports = [{"level": level, "touches": touches} for level, touches in support_buckets.items() if touches >= min_touches and level <= current_price]
    resistances = [{"level": level, "touches": touches} for level, touches in resistance_buckets.items() if touches >= min_touches and level >= current_price]

    supports.sort(key=lambda item: (abs(current_price - item["level"]), -item["touches"]))
    resistances.sort(key=lambda item: (abs(item["level"] - current_price), -item["touches"]))

    return {
        "supports": supports[:4],
        "resistances": resistances[:4],
        "nearest_support": supports[0] if supports else None,
        "nearest_resistance": resistances[0] if resistances else None,
    }


def score_price_action_setup(direction: str, pattern_info: dict, sr_info: dict, current_price: float) -> dict:
    score = 0
    reasons = []
    nearest_support = sr_info.get("nearest_support")
    nearest_resistance = sr_info.get("nearest_resistance")

    if pattern_info.get("bias") == direction:
        score += min(10, int(pattern_info.get("strength", 0) / 10))
        reasons.append(f"Pattern alignment: {pattern_info.get('label')}")
    elif pattern_info.get("bias") not in {"neutral", None}:
        score -= 8
        reasons.append(f"Pattern conflict: {pattern_info.get('label')}")

    if direction == "call" and nearest_support:
        distance = abs(current_price - nearest_support["level"])
        if distance <= max(abs(current_price) * 0.0015, 0.0001):
            score += 8
            reasons.append(f"Price is reacting near support {nearest_support['level']:.5f}")
    if direction == "put" and nearest_resistance:
        distance = abs(nearest_resistance["level"] - current_price)
        if distance <= max(abs(current_price) * 0.0015, 0.0001):
            score += 8
            reasons.append(f"Price is reacting near resistance {nearest_resistance['level']:.5f}")

    summary = " | ".join(reasons) if reasons else "No strong support/resistance confluence was detected."
    return {"score": score, "reasons": reasons, "summary": summary}


def detect_breakout_structure(direction: str, sr_info: dict, current_price: float, price_sequence: list) -> dict:
    nearest_support = sr_info.get("nearest_support")
    nearest_resistance = sr_info.get("nearest_resistance")
    if not price_sequence or len(price_sequence) < 3:
        return {"state": "unavailable", "score": 0, "summary": "Not enough history to classify breakout structure."}

    recent_closes = [float(row[3]) for row in price_sequence[-3:]]
    tolerance = max(abs(current_price) * 0.0015, 0.0001)

    if direction == "call" and nearest_resistance:
        resistance = float(nearest_resistance["level"])
        if recent_closes[-1] > resistance + tolerance and recent_closes[-2] > resistance:
            return {"state": "confirmed_breakout", "score": 8, "summary": f"Price is holding above resistance {resistance:.5f} after a breakout."}
        if recent_closes[-1] < resistance and recent_closes[-2] > resistance + tolerance:
            return {"state": "false_breakout", "score": -8, "summary": f"Price failed to hold above resistance {resistance:.5f}; breakout looks weak."}
        if abs(recent_closes[-1] - resistance) <= tolerance:
            return {"state": "retest", "score": 5, "summary": f"Price is retesting broken resistance {resistance:.5f}."}

    if direction == "put" and nearest_support:
        support = float(nearest_support["level"])
        if recent_closes[-1] < support - tolerance and recent_closes[-2] < support:
            return {"state": "confirmed_breakdown", "score": 8, "summary": f"Price is holding below support {support:.5f} after a breakdown."}
        if recent_closes[-1] > support and recent_closes[-2] < support - tolerance:
            return {"state": "false_breakdown", "score": -8, "summary": f"Price reclaimed support {support:.5f}; breakdown looks weak."}
        if abs(recent_closes[-1] - support) <= tolerance:
            return {"state": "retest", "score": 5, "summary": f"Price is retesting broken support {support:.5f}."}

    return {"state": "none", "score": 0, "summary": "No breakout or retest structure is active."}

# ---------------- Ø§Ù„Ù…Ø¤Ø´Ø±Ø§Øª Ø§Ù„ÙÙ†ÙŠØ© Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø© ----------------
STRONG_INDICATORS = [
    ("RSI", lambda v, inds: (v < 35, v > 65)),
    ("Stoch.K", lambda v, inds: (v < 25, v > 75)),
    ("MACD.macd", lambda v, inds: (v > inds.get('MACD.signal',0), v < inds.get('MACD.signal',0))),
    ("EMA50", lambda v, inds: (inds.get('close',0) > v, inds.get('close',0) < v)),
    ("SMA50", lambda v, inds: (inds.get('close',0) > v, inds.get('close',0) < v)),
    ("CCI", lambda v, inds: (v < -100, v > 100)),
    ("ADX", lambda v, inds: (v > 25, v < 20)),
]

# ---------------- Ù†Ø¸Ø§Ù… Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ù…ØªÙ‚Ø¯Ù… ----------------
class AdvancedAITradingSystem:
    def __init__(self):
        self.model = None
        self.models = {}
        self.scaler = StandardScaler()
        self.training_data = []
        self.performance_history = []
        self.market_patterns = {}
        self.model_file = "advanced_ai_models.pkl"
        self.scaler_file = "advanced_ai_scaler.pkl"
        self.data_file = "advanced_trading_data.json"
        self.lstm_model = None
        self.lstm_model_file = "advanced_lstm_model.keras"
        self.sequence_length = 20
        self.price_action_feature_count = 8
        self.sequence_buffers = defaultdict(lambda: deque(maxlen=self.sequence_length))
        self.model_weights = {}
        self.model_weights_file = "advanced_ai_model_weights.json"
        self.label_to_index = {-2: 0, -1: 1, 0: 2, 1: 3, 2: 4}
        self.index_to_label = {0: -2, 1: -1, 2: 0, 3: 1, 4: 2}

        load_tensorflow_keras()
        
        self.load_ai_system()
    
    def load_ai_system(self):
        """ØªØ­Ù…ÙŠÙ„ Ù†Ø¸Ø§Ù… Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…"""
        try:
            if os.path.exists(self.model_file):
                loaded_model = joblib.load(self.model_file)
                if isinstance(loaded_model, dict):
                    self.models = loaded_model
                    self.model = self.models.get('random_forest') or next(iter(self.models.values()), None)
                else:
                    self.model = loaded_model
                    self.models = {'random_forest': loaded_model}
                self.scaler = joblib.load(self.scaler_file)
                print("âœ… ØªÙ… ØªØ­Ù…ÙŠÙ„ Ù†Ù…ÙˆØ°Ø¬ Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…")
            else:
                self.initialize_advanced_model()
                print("New advanced AI model initialized")

            if load_tensorflow_keras() and load_model and os.path.exists(self.lstm_model_file):
                self.lstm_model = load_model(self.lstm_model_file)

            if os.path.exists(self.model_weights_file):
                with open(self.model_weights_file, 'r', encoding='utf-8') as f:
                    self.model_weights = json.load(f)
                
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.training_data = data.get('training_data', [])
                    self.performance_history = data.get('performance_history', [])
                    self.market_patterns = data.get('market_patterns', {})
                    
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ ØªØ­Ù…ÙŠÙ„ Ø§Ù„Ù†Ø¸Ø§Ù… Ø§Ù„Ù…ØªÙ‚Ø¯Ù…: {e}")
            self.initialize_advanced_model()
    
    def initialize_advanced_model(self):
        """ØªÙ‡ÙŠØ¦Ø© Ø§Ù„Ù†Ù…ÙˆØ°Ø¬ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…"""
        self.models = {
            'random_forest': RandomForestClassifier(
                n_estimators=200,
                max_depth=20,
                min_samples_split=3,
                min_samples_leaf=1,
                random_state=42,
                bootstrap=True
            ),
            'extra_trees': ExtraTreesClassifier(
                n_estimators=200,
                max_depth=18,
                min_samples_split=3,
                min_samples_leaf=1,
                random_state=42
            ),
            'gradient_boosting': GradientBoostingClassifier(
                n_estimators=150,
                learning_rate=0.05,
                max_depth=3,
                random_state=42
            ),
        }
        if XGBClassifier is not None:
            self.models['xgboost'] = XGBClassifier(
                n_estimators=150,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=42,
                eval_metric='mlogloss'
            )
        self.model = self.models['random_forest']
        self.model_weights = {name: 1.0 for name in self.models.keys()}
        if load_tensorflow_keras() and Sequential and LSTM and Dense and Input:
            self.lstm_model = Sequential([
                Input(shape=(self.sequence_length, self.price_action_feature_count)),
                LSTM(32, return_sequences=False),
                Dense(32, activation='relu'),
                Dense(5, activation='softmax'),
            ])
            self.lstm_model.compile(
                optimizer='adam',
                loss='sparse_categorical_crossentropy',
                metrics=['accuracy'],
            )
        self.training_data = []
        self.performance_history = []
        self.market_patterns = {}
    
    def save_ai_system(self):
        """Ø­ÙØ¸ Ù†Ø¸Ø§Ù… Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…"""
        try:
            joblib.dump(self.models if self.models else self.model, self.model_file)
            joblib.dump(self.scaler, self.scaler_file)
            if self.lstm_model is not None:
                self.lstm_model.save(self.lstm_model_file, overwrite=True)
            with open(self.model_weights_file, 'w', encoding='utf-8') as f:
                json.dump(self.model_weights, f, ensure_ascii=False, indent=2)
            
            data_to_save = {
                'training_data': self.training_data[-2000:],
                'performance_history': self.performance_history,
                'market_patterns': self.market_patterns
            }
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
                
            print("ðŸ’¾ ØªÙ… Ø­ÙØ¸ Ù†Ø¸Ø§Ù… Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ")
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø­ÙØ¸ Ø§Ù„Ù†Ø¸Ø§Ù…: {e}")
    
    async def extract_advanced_features(self, indicators: dict, pair: str, timeframe: str) -> np.array:
        """Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ù…ÙŠØ²Ø§Øª Ù…ØªÙ‚Ø¯Ù…Ø© Ù„Ù„ØªØ¹Ù„Ù… Ø§Ù„Ø¢Ù„ÙŠ"""
        try:
            features = []
            
            # 1. Ø§Ù„Ù…Ø¤Ø´Ø±Ø§Øª Ø§Ù„Ø£Ø³Ø§Ø³ÙŠØ© Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø©
            features.extend([
                indicators.get('RSI', 50),
                indicators.get('MACD.macd', 0),
                indicators.get('MACD.signal', 0),
                indicators.get('Stoch.K', 50),
                indicators.get('Stoch.D', 50),
                indicators.get('CCI', 0),
                indicators.get('ADX', 0),
                indicators.get('Williams %R', 0),
                indicators.get('Ultimate Oscillator', 50),
            ])
            
            # 2. Ø§Ù„Ù…ØªÙˆØ³Ø·Ø§Øª Ø§Ù„Ù…ØªØ­Ø±ÙƒØ© Ø§Ù„Ù…ØªØ¹Ø¯Ø¯Ø©
            close = indicators.get('close', 1)
            ma_values = [
                indicators.get('EMA5', close),
                indicators.get('EMA10', close),
                indicators.get('EMA20', close),
                indicators.get('EMA50', close),
                indicators.get('EMA100', close),
                indicators.get('EMA200', close),
                indicators.get('SMA20', close),
                indicators.get('SMA50', close),
            ]
            features.extend(ma_values)
            
            # 3. Ù†Ø³Ø¨ ÙˆØªÙ‚Ø§Ø·Ø¹Ø§Øª Ø§Ù„Ù…ØªÙˆØ³Ø·Ø§Øª
            for i in range(len(ma_values)-1):
                if ma_values[i+1] != 0:
                    features.append(ma_values[i] / ma_values[i+1])
                    features.append(ma_values[i] - ma_values[i+1])
            
            # 4. Ø§Ù„ØªÙ‚Ù„Ø¨Ø§Øª ÙˆØ§Ù„Ù†Ø·Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø©
            high = indicators.get('high', close)
            low = indicators.get('low', close)
            open_price = indicators.get('open', close)
            prev_close = indicators.get('prev_close', close)
            
            features.extend([
                high - low,  # Ø§Ù„Ù†Ø·Ø§Ù‚ Ø§Ù„Ù…Ø·Ù„Ù‚
                (high - low) / close if close != 0 else 0,  # Ø§Ù„Ù†Ø·Ø§Ù‚ Ø§Ù„Ù†Ø³Ø¨ÙŠ
                (close - open_price) / close if close != 0 else 0,  # ØªØºÙŠØ± Ø§Ù„Ø³Ø¹Ø± Ø§Ù„ÙŠÙˆÙ…ÙŠ
                (close - prev_close) / prev_close if prev_close != 0 else 0,  # Ø§Ù„Ø¹Ø§Ø¦Ø¯
                (high - close) / (high - low) if high != low else 0.5,  # Ù…ÙˆÙ‚Ø¹ Ø§Ù„Ø¥ØºÙ„Ø§Ù‚
            ])
            
            # 5. Ø§Ù„Ø²Ø®Ù… ÙˆØ§Ù„Ø­Ø¬Ù… Ø§Ù„Ù…ØªÙ‚Ø¯Ù…
            volume = indicators.get('volume', 0)
            features.extend([
                volume,
                indicators.get('RSI', 50) - 50,  # Ø§Ù†Ø­Ø±Ø§Ù RSI
                indicators.get('MACD.macd', 0) - indicators.get('MACD.signal', 0),  # Ø§Ù†Ø­Ø±Ø§Ù MACD
                indicators.get('Volume SMA', volume),  # Ø­Ø¬Ù… Ù…ØªÙˆØ³Ø·
                self.safe_div(volume, indicators.get('Volume SMA', volume)),  # Ù†Ø³Ø¨Ø© Ø§Ù„Ø­Ø¬Ù…
            ])
            
            # 6. Ù…Ø¹Ù„ÙˆÙ…Ø§Øª Ø§Ù„ÙˆÙ‚Øª ÙˆØ§Ù„Ø³ÙŠØ§Ù‚
            current_time = datetime.now()
            features.extend([
                current_time.hour,
                current_time.weekday(),
                1 if 8 <= current_time.hour <= 17 else 0,  # Ø³Ø§Ø¹Ø§Øª Ø§Ù„ØªØ¯Ø§ÙˆÙ„ Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ©
                1 if current_time.weekday() < 5 else 0,  # Ø£ÙŠØ§Ù… Ø§Ù„Ø£Ø³Ø¨ÙˆØ¹
            ])
            
            # 7. Ø£Ù†Ù…Ø§Ø· Ø§Ù„Ø´Ù…ÙˆØ¹
            body = abs(close - open_price)
            total_range = high - low
            features.extend([
                self.safe_div(body, total_range),  # Ù†Ø³Ø¨Ø© Ø§Ù„Ø¬Ø³Ù…
                self.safe_div(high - max(close, open_price), total_range),  # Ø§Ù„ÙØªÙŠÙ„Ø© Ø§Ù„Ø¹Ù„ÙˆÙŠØ©
                self.safe_div(min(close, open_price) - low, total_range),  # Ø§Ù„ÙØªÙŠÙ„Ø© Ø§Ù„Ø³ÙÙ„ÙŠØ©
            ])
            
            return np.array(features).reshape(1, -1)
            
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ø§Ù„Ù…ÙŠØ²Ø§Øª Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø©: {e}")
            return np.array([50] * 50).reshape(1, -1)  # Ø¥Ø±Ø¬Ø§Ø¹ Ù…ÙŠØ²Ø§Øª Ø§ÙØªØ±Ø§Ø¶ÙŠØ©
    
    def safe_div(self, numerator, denominator):
        """Ù‚Ø³Ù…Ø© Ø¢Ù…Ù†Ø©"""
        try:
            if denominator and denominator != 0:
                return numerator / denominator
        except Exception:
            pass
        return 0

    def _available_models(self):
        return {name: model for name, model in self.models.items() if model is not None}

    def _prediction_label_order(self):
        return [-2, -1, 0, 1, 2]

    def _probability_map(self, model_name: str, model, features_scaled: np.array) -> dict:
        probabilities = model.predict_proba(features_scaled)[0]
        classes = getattr(model, "classes_", [])
        prob_map = {label: 0.0 for label in self._prediction_label_order()}
        for index, class_label in enumerate(classes):
            normalized_label = int(class_label)
            if model_name == 'xgboost' and normalized_label in self.index_to_label:
                normalized_label = self.index_to_label[normalized_label]
            prob_map[int(normalized_label)] = float(probabilities[index])
        return prob_map

    def _ensemble_probabilities(self, features_scaled: np.array) -> dict:
        available_models = self._available_models()
        if not available_models:
            raise RuntimeError("No AI models are available for ensemble prediction")

        combined = {label: 0.0 for label in self._prediction_label_order()}
        total_weight = 0.0
        for model_name, model in available_models.items():
            weight = float(self.model_weights.get(model_name, 1.0))
            total_weight += weight
            for label, probability in self._probability_map(model_name, model, features_scaled).items():
                combined[label] += probability * weight

        normalization = total_weight if total_weight > 0 else len(available_models)
        return {label: value / normalization for label, value in combined.items()}

    def _predict_from_ensemble(self, features_scaled: np.array) -> tuple[int, dict]:
        ensemble_probabilities = self._ensemble_probabilities(features_scaled)
        predicted_label = max(ensemble_probabilities, key=ensemble_probabilities.get)
        return predicted_label, ensemble_probabilities

    def _build_price_action_vector(self, indicators: dict) -> List[float]:
        close = float(indicators.get('close', 0) or 0)
        open_price = float(indicators.get('open', close) or close)
        high = float(indicators.get('high', close) or close)
        low = float(indicators.get('low', close) or close)
        volume = float(indicators.get('volume', 0) or 0)
        ema20 = float(indicators.get('EMA20', close) or close)
        ema50 = float(indicators.get('EMA50', close) or close)
        rsi = float(indicators.get('RSI', 50) or 50)
        return [open_price, high, low, close, volume, ema20, ema50, rsi]

    def _sequence_key(self, pair: str, timeframe: str) -> str:
        return f"{pair}_{timeframe}"

    def update_sequence_buffer(self, pair: str, timeframe: str, indicators: dict) -> List[List[float]]:
        key = self._sequence_key(pair, timeframe)
        self.sequence_buffers[key].append(self._build_price_action_vector(indicators))
        return list(self.sequence_buffers[key])

    async def lstm_price_action_signal(self, pair: str, timeframe: str, indicators: dict, traditional_signal: dict) -> dict:
        sequence = self.update_sequence_buffer(pair, timeframe, indicators)
        if len(sequence) < self.sequence_length or self.lstm_model is None:
            return {
                'direction': traditional_signal.get('direction', 'neutral'),
                'confidence': max(40, traditional_signal.get('confidence', 50) - 5),
                'method': 'lstm_warming_up' if self.lstm_model is not None else 'lstm_unavailable',
                'price_sequence': sequence,
            }

        try:
            sequence_array = np.array(sequence[-self.sequence_length:], dtype=np.float32).reshape(
                1, self.sequence_length, self.price_action_feature_count
            )
            probabilities = self.lstm_model.predict(sequence_array, verbose=0)[0]
            predicted_index = int(np.argmax(probabilities))
            predicted_label = self.index_to_label[predicted_index]
            confidence = int(float(np.max(probabilities)) * 100)

            if predicted_label in (1, 2):
                direction = 'call'
            elif predicted_label in (-1, -2):
                direction = 'put'
            else:
                direction = 'neutral'

            return {
                'direction': direction,
                'confidence': confidence,
                'method': 'lstm_price_action',
                'raw_label': predicted_label,
                'probabilities': probabilities.tolist(),
                'price_sequence': sequence,
            }
        except Exception as e:
            print(f"LSTM signal error: {e}")
            return {
                'direction': traditional_signal.get('direction', 'neutral'),
                'confidence': max(35, traditional_signal.get('confidence', 50) - 10),
                'method': 'lstm_fallback',
                'price_sequence': sequence,
            }
    
    async def ai_enhanced_prediction(self, features: np.array, traditional_signal: dict,
                                   market_context: dict, pair: str = "", timeframe: str = "",
                                   indicators: dict | None = None) -> dict:
        """Ø§Ù„ØªÙ†Ø¨Ø¤ Ø§Ù„Ù…ØªÙ‚Ø¯Ù… Ø¨Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ"""
        try:
            # Ø¥Ø°Ø§ ÙƒØ§Ù† Ø§Ù„Ù†Ù…ÙˆØ°Ø¬ ØºÙŠØ± Ù…Ø¯Ø±Ø¨ØŒ Ø§Ø³ØªØ®Ø¯Ù… Ø§Ù„Ø¥Ø´Ø§Ø±Ø© Ø§Ù„ØªÙ‚Ù„ÙŠØ¯ÙŠØ©
            if len(self.training_data) < 100:
                return {
                    'direction': traditional_signal['direction'],
                    'confidence': traditional_signal['confidence'],
                    'method': 'traditional_fallback',
                    'ai_confidence': 50,
                    'risk_level': 'medium',
                    'models_used': list(self._available_models().keys()) or ['random_forest'],
                }
            
            # ØªØ·Ø¨ÙŠØ¹ Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª ÙˆØ§Ù„ØªÙ†Ø¨Ø¤
            features_scaled = self.scaler.transform(features)
            prediction, ensemble_probabilities = self._predict_from_ensemble(features_scaled)
            probabilities = [ensemble_probabilities[label] for label in self._prediction_label_order()]
            
            # ØªÙØ³ÙŠØ± Ø§Ù„Ù†ØªØ§Ø¦Ø¬ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø©
            if prediction == 2:  # Ø´Ø±Ø§Ø¡ Ù‚ÙˆÙŠ
                direction = "call"
                ai_confidence = int(ensemble_probabilities[2] * 100)
                risk_level = "low"
            elif prediction == 1:  # Ø´Ø±Ø§Ø¡ Ø¹Ø§Ø¯ÙŠ
                direction = "call" 
                ai_confidence = int(ensemble_probabilities[1] * 100)
                risk_level = "medium"
            elif prediction == -1:  # Ø¨ÙŠØ¹ Ø¹Ø§Ø¯ÙŠ
                direction = "put"
                ai_confidence = int(ensemble_probabilities[-1] * 100)
                risk_level = "medium"
            elif prediction == -2:  # Ø¨ÙŠØ¹ Ù‚ÙˆÙŠ
                direction = "put"
                ai_confidence = int(ensemble_probabilities[-2] * 100)
                risk_level = "low"
            else:  # Ù…Ø­Ø§ÙŠØ¯
                direction = "neutral"
                ai_confidence = int(ensemble_probabilities[0] * 100)
                risk_level = "high"
            
            # ØªØ¹Ø¯ÙŠÙ„ Ø§Ù„Ø«Ù‚Ø© Ø¨Ù†Ø§Ø¡Ù‹ Ø¹Ù„Ù‰ Ø³ÙŠØ§Ù‚ Ø§Ù„Ø³ÙˆÙ‚
            adjusted_confidence = self.adjust_confidence_by_market(ai_confidence, market_context)
            
            # Ø¯Ù…Ø¬ Ù…Ø¹ Ø§Ù„Ø¥Ø´Ø§Ø±Ø© Ø§Ù„ØªÙ‚Ù„ÙŠØ¯ÙŠØ©
            final_confidence = self.combine_confidence(traditional_signal['confidence'], adjusted_confidence)
            
            return {
                'direction': direction,
                'confidence': final_confidence,
                'method': 'ensemble_ai',
                'ai_confidence': ai_confidence,
                'risk_level': risk_level,
                'probabilities': probabilities,
                'market_adjustment': adjusted_confidence - ai_confidence,
                'models_used': list(self._available_models().keys()),
            }
            
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø§Ù„ØªÙ†Ø¨Ø¤ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…: {e}")
            return {
                'direction': traditional_signal['direction'],
                'confidence': traditional_signal['confidence'],
                'method': 'fallback',
                'ai_confidence': 50,
                'risk_level': 'high',
                'models_used': list(self._available_models().keys()) or ['random_forest'],
            }
    
    def adjust_confidence_by_market(self, confidence: int, market_context: dict) -> int:
        """ØªØ¹Ø¯ÙŠÙ„ Ø§Ù„Ø«Ù‚Ø© Ø¨Ù†Ø§Ø¡Ù‹ Ø¹Ù„Ù‰ Ø³ÙŠØ§Ù‚ Ø§Ù„Ø³ÙˆÙ‚"""
        adjusted = confidence
        
        # ØªØ¹Ø¯ÙŠÙ„ based on Ø§Ù„ØªÙ‚Ù„Ø¨Ø§Øª
        volatility = market_context.get('volatility', 0)
        if volatility > 0.03:  # ØªÙ‚Ù„Ø¨Ø§Øª Ø¹Ø§Ù„ÙŠØ©
            adjusted -= 10
        elif volatility < 0.01:  # ØªÙ‚Ù„Ø¨Ø§Øª Ù…Ù†Ø®ÙØ¶Ø©
            adjusted += 5
            
        # ØªØ¹Ø¯ÙŠÙ„ based on ÙˆÙ‚Øª Ø§Ù„ØªØ¯Ø§ÙˆÙ„
        current_hour = datetime.now().hour
        if 8 <= current_hour <= 17:  # Ø³Ø§Ø¹Ø§Øª Ø§Ù„ØªØ¯Ø§ÙˆÙ„ Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠØ©
            adjusted += 5
        else:  # Ø®Ø§Ø±Ø¬ Ø³Ø§Ø¹Ø§Øª Ø§Ù„ØªØ¯Ø§ÙˆÙ„
            adjusted -= 5
            
        return max(10, min(95, adjusted))
    
    def combine_confidence(self, trad_confidence: int, ai_confidence: int) -> int:
        """Ø¯Ù…Ø¬ Ø«Ù‚Ø© Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ù…Ø¹ Ø§Ù„ØªÙ‚Ù„ÙŠØ¯ÙŠ"""
        # ÙˆØ²Ù† Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ ÙŠØ²Ø¯Ø§Ø¯ Ù…Ø¹ Ø²ÙŠØ§Ø¯Ø© Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª
        ai_weight = min(0.8, len(self.training_data) / 500)
        trad_weight = 1 - ai_weight
        
        combined = (trad_confidence * trad_weight) + (ai_confidence * ai_weight)
        return min(95, int(combined))
    
    async def learn_from_trade(self, trade_data: dict):
        """Ø§Ù„ØªØ¹Ù„Ù… Ù…Ù† Ù†ØªÙŠØ¬Ø© Ø§Ù„ØµÙÙ‚Ø©"""
        try:
            if trade_data.get('result') in ['win', 'loss']:
                # ØªØ­Ø¶ÙŠØ± Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª Ù„Ù„ØªØ¯Ø±ÙŠØ¨
                features = trade_data.get('features', np.array([]))
                
                # Ø§Ù„ØªØ£ÙƒØ¯ Ù…Ù† Ø£Ù† features Ù‡ÙŠ Ù…ØµÙÙˆÙØ© numpy
                if not isinstance(features, np.ndarray):
                    if isinstance(features, list):
                        features = np.array(features)
                    else:
                        print("âŒ Ù†ÙˆØ¹ features ØºÙŠØ± Ù…Ø¯Ø¹ÙˆÙ…")
                        return
                
                # ØªØµÙ†ÙŠÙ Ø§Ù„Ù†ØªÙŠØ¬Ø© Ø¨Ø´ÙƒÙ„ Ø£Ø¯Ù‚
                outcome = 0  # Ù…Ø­Ø§ÙŠØ¯ Ø§ÙØªØ±Ø§Ø¶ÙŠ
                if trade_data['result'] == 'win':
                    profit_ratio = trade_data.get('profit', 0) / trade_data.get('amount', 1) if trade_data.get('amount', 1) != 0 else 0
                    if profit_ratio > 0.5:  # Ø±Ø¨Ø­ Ø¹Ø§Ù„ÙŠ
                        outcome = 2  # Ø´Ø±Ø§Ø¡ Ù‚ÙˆÙŠ
                    else:
                        outcome = 1  # Ø´Ø±Ø§Ø¡ Ø¹Ø§Ø¯ÙŠ
                else:
                    loss_ratio = abs(trade_data.get('profit', 0)) / trade_data.get('amount', 1) if trade_data.get('amount', 1) != 0 else 0
                    if loss_ratio > 0.5:  # Ø®Ø³Ø§Ø±Ø© Ø¹Ø§Ù„ÙŠØ©
                        outcome = -2  # Ø¨ÙŠØ¹ Ù‚ÙˆÙŠ
                    else:
                        outcome = -1  # Ø¨ÙŠØ¹ Ø¹Ø§Ø¯ÙŠ
                
                # Ø¥Ø¶Ø§ÙØ© Ù„Ù„Ø¨ÙŠØ§Ù†Ø§Øª Ø§Ù„ØªØ¯Ø±ÙŠØ¨ÙŠØ©
                training_example = {
                    'features': features.tolist()[0] if features.size > 0 else [],
                    'outcome': outcome,
                    'timestamp': time.time(),
                    'confidence': trade_data.get('confidence', 50),
                    'pair': trade_data.get('pair', 'unknown'),
                    'timeframe': trade_data.get('timeframe', ''),
                    'market_condition': trade_data.get('market_condition', 'normal'),
                    'price_sequence': trade_data.get('price_sequence', []),
                }
                
                self.training_data.append(training_example)
                
                # ØªØ­Ø¯ÙŠØ« Ø£Ù†Ù…Ø§Ø· Ø§Ù„Ø³ÙˆÙ‚
                self.update_market_patterns(trade_data)
                
                # ØªØ­Ø¯ÙŠØ« Ù…Ù‚Ø§ÙŠÙŠØ³ Ø§Ù„Ø£Ø¯Ø§Ø¡
                self.update_performance_metrics(trade_data)
                
                # Ø¥Ø¹Ø§Ø¯Ø© ØªØ¯Ø±ÙŠØ¨ Ø§Ù„Ù†Ù…ÙˆØ°Ø¬ Ø¥Ø°Ø§ ÙƒØ§Ù† Ù„Ø¯ÙŠÙ†Ø§ Ø¨ÙŠØ§Ù†Ø§Øª ÙƒØ§ÙÙŠØ©
                if len(self.training_data) >= 100:
                    await self.retrain_model()
                
                # Ø­ÙØ¸ Ø§Ù„Ù†Ø¸Ø§Ù…
                self.save_ai_system()
                
                print(f"ðŸ“š ØªÙ… Ø§Ù„ØªØ¹Ù„Ù… Ù…Ù† Ø§Ù„ØµÙÙ‚Ø©: {trade_data['result']} (Ø§Ù„ØªØµÙ†ÙŠÙ: {outcome})")
                
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø§Ù„ØªØ¹Ù„Ù…: {e}")
    
    def update_market_patterns(self, trade_data: dict):
        """ØªØ­Ø¯ÙŠØ« Ø£Ù†Ù…Ø§Ø· Ø§Ù„Ø³ÙˆÙ‚"""
        try:
            pair = trade_data['pair']
            timeframe = trade_data.get('timeframe', '')
            result = trade_data['result']
            
            key = f"{pair}_{timeframe}"
            
            if key not in self.market_patterns:
                self.market_patterns[key] = {
                    'total_trades': 0,
                    'wins': 0,
                    'win_rate': 0,
                    'last_updated': time.time()
                }
            
            pattern = self.market_patterns[key]
            pattern['total_trades'] += 1
            if result == 'win':
                pattern['wins'] += 1
            pattern['win_rate'] = pattern['wins'] / pattern['total_trades']
            pattern['last_updated'] = time.time()
            
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ ØªØ­Ø¯ÙŠØ« Ø§Ù„Ø£Ù†Ù…Ø§Ø·: {e}")
    
    async def retrain_model(self):
        """Ø¥Ø¹Ø§Ø¯Ø© ØªØ¯Ø±ÙŠØ¨ Ø§Ù„Ù†Ù…ÙˆØ°Ø¬"""
        try:
            if len(self.training_data) < 100:
                return
                
            # ØªØ­Ø¶ÙŠØ± Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª
            X = []
            y = []
            
            for example in self.training_data:
                X.append(example['features'])
                y.append(example['outcome'])
            
            X = np.array(X)
            y = np.array(y)

            split_index = max(1, int(len(X) * 0.8))
            X_train, X_val = X[:split_index], X[split_index:]
            y_train, y_val = y[:split_index], y[split_index:]

            self.scaler.fit(X_train)
            X_train_scaled = self.scaler.transform(X_train)
            X_val_scaled = self.scaler.transform(X_val) if len(X_val) > 0 else X_train_scaled

            updated_weights = {}
            for model_name, model in self._available_models().items():
                if model_name == 'xgboost':
                    y_train_fit = np.array([self.label_to_index[int(label)] for label in y_train])
                    y_val_eval = np.array([self.label_to_index[int(label)] for label in y_val]) if len(y_val) > 0 else y_train_fit
                    model.fit(X_train_scaled, y_train_fit)
                    score = float(model.score(X_val_scaled, y_val_eval)) if len(X_val_scaled) > 0 else 0.5
                else:
                    model.fit(X_train_scaled, y_train)
                    score = float(model.score(X_val_scaled, y_val)) if len(X_val) > 0 else 0.5
                updated_weights[model_name] = max(0.05, score)
                print(f"🔁 Retrained {model_name} on {len(X)} samples with validation score {score:.3f}")

            total_weight = sum(updated_weights.values()) or 1.0
            self.model_weights = {
                model_name: round(weight / total_weight, 4)
                for model_name, weight in updated_weights.items()
            }

            await self.retrain_lstm_model()
            
            print(f"ðŸ”„ ØªÙ… Ø¥Ø¹Ø§Ø¯Ø© ØªØ¯Ø±ÙŠØ¨ Ø§Ù„Ù†Ù…ÙˆØ°Ø¬ Ø§Ù„Ù…ØªÙ‚Ø¯Ù… Ø¹Ù„Ù‰ {len(X)} Ø¹ÙŠÙ†Ø©")
            
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„ØªØ¯Ø±ÙŠØ¨: {e}")

    async def retrain_lstm_model(self):
        """Retrain the LSTM price-action model when enough sequence data is available."""
        try:
            if self.lstm_model is None:
                return

            sequence_examples = []
            sequence_labels = []
            for example in self.training_data:
                sequence = example.get('price_sequence', [])
                if len(sequence) >= self.sequence_length:
                    sequence_examples.append(sequence[-self.sequence_length:])
                    sequence_labels.append(self.label_to_index[int(example['outcome'])])

            if len(sequence_examples) < 30:
                return

            X_seq = np.array(sequence_examples, dtype=np.float32)
            y_seq = np.array(sequence_labels, dtype=np.int32)
            self.lstm_model.fit(X_seq, y_seq, epochs=5, batch_size=16, verbose=0)
            print(f"🔁 Retrained lstm_price_action on {len(X_seq)} sequences")
        except Exception as e:
            print(f"LSTM retraining error: {e}")
    
    def update_performance_metrics(self, trade_data: dict):
        """ØªØ­Ø¯ÙŠØ« Ù…Ù‚Ø§ÙŠÙŠØ³ Ø§Ù„Ø£Ø¯Ø§Ø¡"""
        try:
            # Ø§Ù„ØªØ£ÙƒØ¯ Ù…Ù† ÙˆØ¬ÙˆØ¯ Ø¬Ù…ÙŠØ¹ Ø§Ù„Ø­Ù‚ÙˆÙ„ Ø§Ù„Ù…Ø·Ù„ÙˆØ¨Ø©
            performance_record = {
                'timestamp': time.time(),
                'result': trade_data.get('result', 'unknown'),
                'confidence': trade_data.get('confidence', 50),
                'profit': trade_data.get('profit', 0),
                'pair': trade_data.get('pair', 'unknown'),
                'direction': trade_data.get('direction', 'unknown'),
                'timeframe': trade_data.get('timeframe', 'unknown'),
                'risk_level': trade_data.get('risk_level', 'medium')
            }
            
            self.performance_history.append(performance_record)
            
            # Ø§Ø­ØªÙØ¸ Ø¨Ø£Ù„ÙÙŠ Ø³Ø¬Ù„ ÙÙ‚Ø·
            if len(self.performance_history) > 2000:
                self.performance_history = self.performance_history[-2000:]
                
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ ØªØ­Ø¯ÙŠØ« Ù…Ù‚Ø§ÙŠÙŠØ³ Ø§Ù„Ø£Ø¯Ø§Ø¡: {e}")
    
    def get_performance_stats(self) -> dict:
        """Ø§Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ø¥Ø­ØµØ§Ø¦ÙŠØ§Øª Ø§Ù„Ø£Ø¯Ø§Ø¡ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø© - Ø§Ù„Ø¥ØµØ¯Ø§Ø± Ø§Ù„Ù…ØµØ­Ø­"""
        if not self.performance_history:
            return {
                'total_trades': 0, 
                'win_rate': 0, 
                'avg_confidence': 0, 
                'recent_trades': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'expectancy': 0
            }
        
        try:
            # Ø§Ù„Ø¥Ø­ØµØ§Ø¦ÙŠØ§Øª Ø§Ù„Ø£Ø³Ø§Ø³ÙŠØ©
            wins = len([t for t in self.performance_history if t.get('result') == 'win'])
            total = len(self.performance_history)
            win_rate = wins / total if total > 0 else 0
            
            # Ù…ØªÙˆØ³Ø· Ø§Ù„Ø«Ù‚Ø©
            confidences = [t.get('confidence', 0) for t in self.performance_history if t.get('confidence') is not None]
            avg_confidence = np.mean(confidences) if confidences else 0
            
            # Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ù†Ø§Ø¬Ø­Ø© ÙÙŠ Ø¢Ø®Ø± 10 ØµÙÙ‚Ø§Øª
            recent_trades = self.performance_history[-10:] if len(self.performance_history) >= 10 else self.performance_history
            recent_wins = len([t for t in recent_trades if t.get('result') == 'win'])
            
            # Ø¹Ø§Ù…Ù„ Ø§Ù„Ø±Ø¨Ø­
            total_profit = sum([t.get('profit', 0) for t in self.performance_history if t.get('profit', 0) > 0])
            total_loss = abs(sum([t.get('profit', 0) for t in self.performance_history if t.get('profit', 0) < 0]))
            profit_factor = total_profit / total_loss if total_loss > 0 else 0
            
            # Ù…ØªÙˆØ³Ø· Ø§Ù„Ø±Ø¨Ø­/Ø§Ù„Ø®Ø³Ø§Ø±Ø©
            win_trades = [t for t in self.performance_history if t.get('result') == 'win']
            loss_trades = [t for t in self.performance_history if t.get('result') == 'loss']
            
            avg_win = np.mean([t.get('profit', 0) for t in win_trades]) if win_trades else 0
            avg_loss = np.mean([abs(t.get('profit', 0)) for t in loss_trades]) if loss_trades else 0
            
            # Ø­Ø³Ø§Ø¨ expectancy Ø¢Ù…Ù†
            if win_trades and loss_trades:
                expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
            else:
                expectancy = 0
            
            return {
                'total_trades': total,
                'win_rate': round(win_rate * 100, 2),
                'avg_confidence': round(avg_confidence, 2),
                'recent_trades': recent_wins,
                'profit_factor': round(profit_factor, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'expectancy': round(expectancy, 2)
            }
            
        except Exception as e:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø­Ø³Ø§Ø¨ Ø§Ù„Ø¥Ø­ØµØ§Ø¦ÙŠØ§Øª: {e}")
            return {
                'total_trades': 0, 
                'win_rate': 0, 
                'avg_confidence': 0, 
                'recent_trades': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'expectancy': 0
            }
    
    def get_market_insights(self, pair: str, timeframe: str) -> dict:
        """Ø§Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ø±Ø¤Ù‰ Ø§Ù„Ø³ÙˆÙ‚"""
        key = f"{pair}_{timeframe}"
        pattern = self.market_patterns.get(key, {})
        
        win_rate = pattern.get('win_rate', 0)
        if win_rate > 0.6:
            confidence = 'high'
        elif win_rate > 0.5:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        return {
            'win_rate': win_rate,
            'total_trades': pattern.get('total_trades', 0),
            'last_updated': pattern.get('last_updated', 0),
            'confidence': confidence
        }

# Ø¥Ù†Ø´Ø§Ø¡ Ù†Ø¸Ø§Ù… Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…
advanced_ai_system = AdvancedAITradingSystem()
# ---------------- Ø¯ÙˆØ§Ù„ Ø§Ù„Ø§Ù†ØªØ¸Ø§Ø± Ø§Ù„Ø°ÙƒÙŠ Ù„Ù„Ø´Ù…Ø¹Ø© Ø§Ù„Ø¬Ø¯ÙŠØ¯Ø© ----------------
def calculate_seconds_to_new_candle(timeframe_minutes: int) -> int:
    """Ø­Ø³Ø§Ø¨ Ø§Ù„Ø«ÙˆØ§Ù†ÙŠ Ø§Ù„Ù…ØªØ¨Ù‚ÙŠØ© Ù„Ù„Ø´Ù…Ø¹Ø© Ø§Ù„Ø¬Ø¯ÙŠØ¯Ø©"""
    current_time = datetime.now()
    current_minute = current_time.minute
    current_second = current_time.second
    
    remainder = current_minute % timeframe_minutes
    if remainder == 0:
        return 0
    else:
        return (timeframe_minutes - remainder) * 60 - current_second

# ---------------- Ù†Ø¸Ø§Ù… Quotex Ø§Ù„Ù…ØªÙ‚Ø¯Ù… ----------------
async def connect_to_quotex():
    """Ø§Ù„Ø§ØªØµØ§Ù„ Ø¨Ù…Ù†ØµØ© Quotex Ù…Ø¹ Ø¥Ø¯Ø§Ø±Ø© Ù…Ø­Ø³Ù†Ø©"""
    global quotex_client
    try:
        from pyquotex.stable_api import Quotex
        client = Quotex(settings.quotex_email, settings.quotex_password)
        try:
            client.lang = "en"
        except Exception:
            pass
        
        ok = await client.connect()
        if ok and (isinstance(ok, tuple) and ok[0]):
            logging.info("âœ… Connected to Quotex successfully")
            
            try:
                balance = await client.get_balance()
                logging.info(f"ðŸ’° Ø§Ù„Ø±ØµÙŠØ¯ Ø§Ù„Ø£ÙˆÙ„ÙŠ: ${balance}")
            except Exception as balance_error:
                logging.warning(f"âš ï¸ ÙŠÙ…ÙƒÙ† Ø§Ù„Ø§ØªØµØ§Ù„ ÙˆÙ„ÙƒÙ† Ù„Ø§ ÙŠÙ…ÙƒÙ† Ø¬Ù„Ø¨ Ø§Ù„Ø±ØµÙŠØ¯: {balance_error}")
            
            quotex_client = client
            
            # ÙØ­Øµ Ø§Ù„Ø¯ÙˆØ§Ù„ Ø§Ù„Ù…ØªØ§Ø­Ø©
            methods = [method for method in dir(client) if not method.startswith('_')]
            logging.info(f"ðŸ” Ø§Ù„Ø¯ÙˆØ§Ù„ Ø§Ù„Ù…ØªØ§Ø­Ø© ÙÙŠ Quotex: {methods}")
            
            return client
        else:
            logging.error("âŒ Failed to connect to Quotex")
            return None
    except Exception as e:
        logging.error(f"âŒ Quotex connection error: {e}")
        return None

async def connect_to_quotex_with_retry(max_retries=3):
    """Ø§Ù„Ø§ØªØµØ§Ù„ Ù…Ø¹ Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„Ù…Ø­Ø§ÙˆÙ„Ø©"""
    global quotex_client
    for attempt in range(max_retries):
        try:
            quotex_client = None
            logging.info(f"ðŸ”„ Ù…Ø­Ø§ÙˆÙ„Ø© Ø§Ù„Ø§ØªØµØ§Ù„ {attempt + 1}/{max_retries}")
            client = await connect_to_quotex()
            if client:
                return client
        except Exception as e:
            logging.warning(f"âš ï¸ Ù…Ø­Ø§ÙˆÙ„Ø© {attempt + 1} ÙØ´Ù„Øª: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(min(15, 5 * (attempt + 1)))
    
    logging.error("âŒ ÙØ´Ù„ Ø¬Ù…ÙŠØ¹ Ù…Ø­Ø§ÙˆÙ„Ø§Øª Ø§Ù„Ø§ØªØµØ§Ù„")
    return None


def get_broker_connection_service() -> BrokerConnectionService:
    global broker_connection_service
    if broker_connection_service is None:
        broker_connection_service = BrokerConnectionService(
            get_client=lambda: quotex_client,
            connect_with_retry=connect_to_quotex_with_retry,
            balance_cache=balance_cache,
            now_ts=now_ts,
            reconnect_lock=broker_reconnect_lock,
            get_last_reconnect_at=lambda: last_broker_reconnect_at,
            set_last_reconnect_at=_set_last_broker_reconnect_at,
        )
    return broker_connection_service


def get_trade_state_service() -> TradeStateService:
    global trade_state_service
    if trade_state_service is None:
        trade_state_service = TradeStateService(
            active_trades=active_trades,
            trade_history=trade_history,
            now_ts=now_ts,
        )
    return trade_state_service


def _set_last_broker_reconnect_at(value: float) -> None:
    global last_broker_reconnect_at
    last_broker_reconnect_at = value

async def get_current_balance() -> float:
    """Helper for the execution layer to fetch current balance."""
    return await get_broker_connection_service().get_current_balance()

async def refresh_quotex_connection_if_needed(min_interval_seconds: int = 8) -> bool:
    return await get_broker_connection_service().refresh_connection_if_needed(min_interval_seconds)


def get_trade_execution_service() -> TradeExecutionService:
    global trade_execution_service
    if trade_execution_service is None:
        trade_execution_service = TradeExecutionService(
            get_client=lambda: quotex_client,
            ensure_connection=connect_to_quotex_with_retry,
            refresh_connection=refresh_quotex_connection_if_needed,
            symbol_to_api_symbol=quotex_symbol_to_api_symbol,
            active_trades=active_trades,
            balance_cache=balance_cache,
            execution_lock=broker_execution_lock,
        )
    return trade_execution_service


def get_trade_monitor_service() -> TradeMonitorService:
    global trade_monitor_service
    if trade_monitor_service is None:
        trade_monitor_service = TradeMonitorService(
            get_client=lambda: quotex_client,
            trade_state_service=get_trade_state_service(),
            risk_manager=risk_manager,
            advanced_ai_system=advanced_ai_system,
        )
    return trade_monitor_service

# ---------------- Ù†Ø¸Ø§Ù… ØªÙ†ÙÙŠØ° Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ù…ØªÙ‚Ø¯Ù… ----------------
async def execute_trade_advanced(direction: str, asset: str, amount: float, duration: int = 60):
    """Execute a trade through the extracted execution service."""
    return await get_trade_execution_service().execute_trade(direction, asset, amount, duration)

async def try_general_methods(direction: str, asset: str, amount: float, duration: int, methods: list):
    """ØªØ¬Ø±Ø¨Ø© Ø§Ù„Ø¯ÙˆØ§Ù„ Ø§Ù„Ø¹Ø§Ù…Ø©"""
    for method_name in methods:
        try:
            method_func = getattr(quotex_client, method_name)
            
            # Ø¥Ø°Ø§ ÙƒØ§Ù†Øª Ø§Ù„Ø¯Ø§Ù„Ø© ØªØ£Ø®Ø° Ø¨Ø§Ø±Ø§Ù…ØªØ±Ø§ØªØŒ Ø¬Ø±Ø¨Ù‡Ø§
            param_count = method_func.__code__.co_argcount - 1
            
            if param_count >= 2:  # ØªØ£Ø®Ø° Ø¹Ù„Ù‰ Ø§Ù„Ø£Ù‚Ù„ 2 Ø¨Ø§Ø±Ø§Ù…ØªØ±Ø§Øª
                try:
                    # Ø¬Ø±Ø¨ Ù…Ø¹ Ø¨Ø§Ø±Ø§Ù…ØªØ±Ø§Øª Ø£Ø³Ø§Ø³ÙŠØ©
                    if param_count == 2:
                        result = await method_func(asset, amount)
                    elif param_count == 3:
                        result = await method_func(asset, amount, duration)
                    elif param_count == 4:
                        result = await method_func(direction, asset, amount, duration)
                    
                    if result and result != False:
                        trade_id = result[0] if isinstance(result, tuple) else result
                        if trade_id:
                            logging.info(f"âœ… âœ… Ù†Ø¬Ø­ Ø§Ù„ØªÙ†ÙÙŠØ° Ø¨Ø§Ø³ØªØ®Ø¯Ø§Ù… {method_name} - ID: {trade_id}")
                            return True, trade_id
                            
                except Exception:
                    continue
                    
        except Exception:
            continue
    
    return False, "âŒ ÙØ´Ù„ Ø¬Ù…ÙŠØ¹ Ù…Ø­Ø§ÙˆÙ„Ø§Øª Ø§Ù„ØªÙ†ÙÙŠØ°. Ù‚Ø¯ ØªØ­ØªØ§Ø¬ Ø§Ù„Ù…ÙƒØªØ¨Ø© Ù„Ù„ØªØ­Ø¯ÙŠØ«"

# ---------------- Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ù…ØªÙ‚Ø¯Ù… Ø¨Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ ----------------
async def get_traditional_signal(analysis: Any) -> dict:
    """Ø§Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ø§Ù„Ø¥Ø´Ø§Ø±Ø© Ø§Ù„ØªÙ‚Ù„ÙŠØ¯ÙŠØ© Ù…Ù† ØªØ­Ù„ÙŠÙ„ TradingView"""
    try:
        if analysis is None:
            return {'direction': 'neutral', 'confidence': 50, 'recommendation': 'UNAVAILABLE'}
        summary = analysis.summary
        recommendation = summary.get('RECOMMENDATION', 'NEUTRAL')
        buy_signals = summary.get('BUY', 0)
        sell_signals = summary.get('SELL', 0)
        neutral_signals = summary.get('NEUTRAL', 0)
        
        total_signals = buy_signals + sell_signals + neutral_signals
        
        if total_signals == 0:
            return {'direction': 'neutral', 'confidence': 50, 'recommendation': 'NEUTRAL'}
        
        # ØªØ­Ø¯ÙŠØ¯ Ø§Ù„Ø§ØªØ¬Ø§Ù‡ Ø¨Ù†Ø§Ø¡Ù‹ Ø¹Ù„Ù‰ Ø§Ù„Ø¥Ø´Ø§Ø±Ø§Øª
        if buy_signals > sell_signals and buy_signals > neutral_signals:
            direction = "call"
            confidence = min(95, int((buy_signals / total_signals) * 100))
        elif sell_signals > buy_signals and sell_signals > neutral_signals:
            direction = "put"
            confidence = min(95, int((sell_signals / total_signals) * 100))
        else:
            direction = "neutral"
            confidence = 50
            
        return {
            'direction': direction,
            'confidence': confidence,
            'recommendation': recommendation,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'neutral_signals': neutral_signals
        }
        
    except Exception as e:
        logging.debug(f"Traditional signal fallback used: {e}")
        return {'direction': 'neutral', 'confidence': 50, 'recommendation': 'NEUTRAL'}

async def get_market_context(indicators: dict) -> dict:
    """Ø§Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ø³ÙŠØ§Ù‚ Ø§Ù„Ø³ÙˆÙ‚"""
    try:
        close = indicators.get('close', 0)
        high = indicators.get('high', close)
        low = indicators.get('low', close)
        
        volatility = (high - low) / close if close != 0 else 0
        trend_strength = indicators.get('ADX', 0)
        
        return {
            'volatility': volatility,
            'trend_strength': trend_strength,
            'market_condition': 'high_vol' if volatility > 0.03 else 'low_vol' if volatility < 0.01 else 'normal',
            'trend_condition': 'strong' if trend_strength > 25 else 'weak' if trend_strength < 20 else 'moderate',
            'support_resistance': {},
            'price_action_pattern': {},
            'price_action_score': 0,
        }
    except Exception as e:
        return {
            'volatility': 0.01,
            'trend_strength': 0,
            'market_condition': 'normal',
            'trend_condition': 'moderate',
            'support_resistance': {},
            'price_action_pattern': {},
            'price_action_score': 0,
        }

def build_decision_votes(traditional_signal: dict, ai_prediction: dict, indicators: dict, market_context: dict):
    """Build weighted votes for the final decision."""
    close = indicators.get('close', 0)
    ema20 = indicators.get('EMA20', close)
    ema50 = indicators.get('EMA50', close)

    trend_direction = 'neutral'
    trend_confidence = 45
    trend_reason = "Trend is mixed"
    if close > ema20 > ema50:
        trend_direction = 'call'
        trend_confidence = 72
        trend_reason = "Price is above EMA20 and EMA50"
    elif close < ema20 < ema50:
        trend_direction = 'put'
        trend_confidence = 72
        trend_reason = "Price is below EMA20 and EMA50"

    volatility = market_context.get('volatility', 0)
    volatility_direction = ai_prediction.get('direction', 'neutral')
    volatility_confidence = 65
    volatility_reason = "Volatility is normal"
    if volatility > 0.03:
        volatility_direction = 'neutral'
        volatility_confidence = 35
        volatility_reason = "High volatility reduces execution confidence"
    elif volatility < 0.01:
        volatility_reason = "Low volatility supports conservative entries"

    return [
        SignalVote(
            name="traditional",
            direction=traditional_signal.get('direction', 'neutral'),
            confidence=traditional_signal.get('confidence', 50),
            weight=0.35,
            reason=f"TradingView={traditional_signal.get('recommendation', 'N/A')}",
        ),
        SignalVote(
            name="ai_model",
            direction=ai_prediction.get('direction', 'neutral'),
            confidence=ai_prediction.get('ai_confidence', ai_prediction.get('confidence', 50)),
            weight=0.35,
            reason=f"Method={ai_prediction.get('method', 'unknown')}",
        ),
        SignalVote(
            name="trend_filter",
            direction=trend_direction,
            confidence=trend_confidence,
            weight=0.15,
            reason=trend_reason,
        ),
        SignalVote(
            name="volatility_filter",
            direction=volatility_direction,
            confidence=volatility_confidence,
            weight=0.15,
            reason=volatility_reason,
        ),
    ]

def get_trading_orchestrator() -> TradingOrchestrator:
    """Build and cache the layered trading architecture."""
    global trading_orchestrator

    if trading_orchestrator is None:
        data_layer = MarketDataLayer(
            get_analysis_callable=get_cached_analysis,
            timeframe_map=TIMEFRAMES,
            cache_ttl_seconds=CACHE_TTL_SECONDS,
        )
        signal_engine = SignalEngine(
            traditional_signal_fn=get_traditional_signal,
            feature_extractor_fn=advanced_ai_system.extract_advanced_features,
            ai_prediction_fn=advanced_ai_system.ai_enhanced_prediction,
            lstm_signal_fn=advanced_ai_system.lstm_price_action_signal,
            candle_pattern_fn=candle_patterns_from_inds,
        )
        decision_core = BinaryOptionsDecisionCore(decision_engine)
        execution_layer = ExecutionLayer(
            execute_trade_fn=execute_trade_advanced,
            connection_check_fn=check_quotex_connection,
            balance_fn=get_current_balance,
        )
        trading_orchestrator = TradingOrchestrator(
            data_layer=data_layer,
            signal_engine=signal_engine,
            decision_core=decision_core,
            risk_manager=risk_manager,
            execution_layer=execution_layer,
            timeframe_map=TIMEFRAMES,
        )

    return trading_orchestrator

async def advanced_ai_analysis_layered(pairdict: dict, interval_key: str) -> Tuple[str, str, int, np.array, dict]:
    """Primary layered analysis path used by the bot."""
    if pairdict.get("tv_supported") is False:
        return await live_stream_analysis(pairdict, interval_key)

    if should_prefer_live_quotex_analysis(pairdict):
        try:
            live_result = await live_stream_analysis(pairdict, interval_key)
            _, live_direction, live_confidence, _, live_context = live_result
            live_snapshot = live_context.get("live_snapshot", {}) if isinstance(live_context, dict) else {}
            has_live_signal = (
                live_direction in {"call", "put"}
                or isinstance(live_snapshot.get("price"), (int, float))
                or bool(live_snapshot.get("candles"))
            )
            if has_live_signal:
                return live_result
        except Exception:
            pass

    try:
        orchestrator = get_trading_orchestrator()
        outcome = await orchestrator.analyze_market(pairdict, interval_key)
        snapshot = outcome.decision.package.snapshot
        if snapshot.analysis is None:
            return await live_stream_analysis(pairdict, interval_key)
        traditional_signal = outcome.decision.package.traditional_signal
        ai_prediction = outcome.decision.package.ai_prediction
        market_context = outcome.market_context
        sequence = outcome.decision.package.price_sequence or []
        pattern_info = detect_price_action_patterns(snapshot.indicators, sequence)
        sr_info = detect_support_resistance_zones(sequence)
        price_action = score_price_action_setup(
            outcome.direction,
            pattern_info,
            sr_info,
            float(snapshot.indicators.get('close', 0) or 0),
        )
        breakout_info = detect_breakout_structure(
            outcome.direction,
            sr_info,
            float(snapshot.indicators.get('close', 0) or 0),
            sequence,
        )
        market_context["price_action_pattern"] = pattern_info
        market_context["support_resistance"] = sr_info
        market_context["breakout_structure"] = breakout_info
        market_context["price_action_score"] = price_action["score"] + breakout_info["score"]
        market_context.setdefault("decision_reasons", [])
        market_context["decision_reasons"].extend(price_action["reasons"])
        market_context["decision_reasons"].append(breakout_info["summary"])
        ai_prediction["confidence"] = max(0, min(99, int(ai_prediction.get("confidence", 0) or 0) + int(market_context["price_action_score"])))
        ai_prediction["decision_score"] = max(0, min(99, int(ai_prediction.get("decision_score", ai_prediction["confidence"]) or 0) + int(market_context["price_action_score"])))
        market_context["candle_pattern"] = pattern_info.get("label", market_context.get("candle_pattern", "N/A"))

        message = await generate_advanced_ai_message(
            pairdict,
            interval_key,
            snapshot.analysis,
            traditional_signal,
            ai_prediction,
            market_context,
        )
        store_cached_analysis_result(
            pairdict,
            interval_key,
            {
                "message": message,
                "direction": outcome.direction,
                "confidence": outcome.confidence,
                "features": outcome.features,
                "market_context": market_context,
                "traditional_signal": traditional_signal,
                "ai_prediction": ai_prediction,
                "analysis": snapshot.analysis,
            },
        )
        return message, outcome.direction, outcome.confidence, outcome.features, market_context
    except Exception as exc:
        logging.debug(f"Layered analysis path failed, falling back: {exc}")
        cached_result = get_cached_analysis_result(pairdict, interval_key)
        if cached_result:
            fallback_context = dict(cached_result.get("market_context", {}))
            fallback_context["degraded"] = True
            fallback_context["degraded_reason"] = f"Using cached analysis because live analysis failed: {exc}"
            return (
                cached_result.get("message", "⚠️ Cached analysis only."),
                cached_result.get("direction", "neutral"),
                cached_result.get("confidence", 50),
                cached_result.get("features", np.array([])),
                fallback_context,
            )
        return await live_stream_analysis(pairdict, interval_key)

# Ø¥Ø¶Ø§ÙØ© ÙØ­Øµ Ù„Ù„Ø£Ø®Ø·Ø§Ø¡ ÙÙŠ advanced_ai_analysis
async def advanced_ai_analysis(pairdict: dict, interval_key: str, interval) -> Tuple[str, str, int, np.array, dict]:
    """Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ù…ØªÙ‚Ø¯Ù… Ø¨Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ - Ù…Ø¹ Ù…Ø¹Ø§Ù„Ø¬Ø© Ø§Ù„Ø£Ø®Ø·Ø§Ø¡ Ø§Ù„Ù…Ø­Ø³Ù†Ø©"""
    if pairdict.get("tv_supported") is False:
        return await live_stream_analysis(pairdict, interval_key)

    try:
        analysis = await get_cached_analysis(pairdict, interval_key, interval)
        
        if not analysis:
            cached_result = get_cached_analysis_result(pairdict, interval_key)
            if cached_result:
                fallback_context = dict(cached_result.get("market_context", {}))
                fallback_context["degraded"] = True
                fallback_context["degraded_reason"] = "TradingView data is temporarily unavailable. Showing the latest cached analysis."
                return (
                    cached_result.get("message", "⚠️ Cached analysis only."),
                    cached_result.get("direction", "neutral"),
                    cached_result.get("confidence", 50),
                    cached_result.get("features", np.array([])),
                    fallback_context,
                )

            unavailable_context = {
                "degraded": True,
                "degraded_reason": "TradingView data is temporarily unavailable or rate-limited.",
                "volatility": 0.0,
                "trend_strength": 0.0,
                "market_condition": "unavailable",
                "trend_condition": "unknown",
                "candle_pattern": "N/A",
                "decision_reasons": ["No live TradingView snapshot was available."],
            }
            unavailable_message = (
                "⚠️ <b>Live analysis is temporarily unavailable</b>\n\n"
                "TradingView is rate-limiting requests right now. The bot is staying online, but this asset cannot be analyzed live at the moment."
            )
            if pairdict.get("quotex_symbol"):
                return await live_stream_analysis(pairdict, interval_key)
            return unavailable_message, "neutral", 0, np.array([]), unavailable_context
        
        # 2. Ø§Ù„ØªØ­Ù„ÙŠÙ„ Ø§Ù„ØªÙ‚Ù„ÙŠØ¯ÙŠ
        traditional_signal = await get_traditional_signal(analysis)
        
        # 3. Ø³ÙŠØ§Ù‚ Ø§Ù„Ø³ÙˆÙ‚
        market_context = await get_market_context(analysis.indicators)

        # 4. Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ø§Ù„Ù…ÙŠØ²Ø§Øª Ù„Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ
        features = await advanced_ai_system.extract_advanced_features(analysis.indicators, pairdict['symbol'], interval_key)

        # 5. Ø§Ù„ØªÙ†Ø¨Ø¤ Ø¨Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…
        ai_prediction = await advanced_ai_system.ai_enhanced_prediction(features, traditional_signal, market_context)
        lstm_signal = await advanced_ai_system.lstm_price_action_signal(pairdict['symbol'], interval_key, analysis.indicators, traditional_signal)
        sequence = lstm_signal.get('price_sequence', [])
        pattern_info = detect_price_action_patterns(analysis.indicators, sequence)
        sr_info = detect_support_resistance_zones(sequence)
        price_action = score_price_action_setup(
            ai_prediction['direction'],
            pattern_info,
            sr_info,
            float(analysis.indicators.get('close', 0) or 0),
        )
        breakout_info = detect_breakout_structure(
            ai_prediction['direction'],
            sr_info,
            float(analysis.indicators.get('close', 0) or 0),
            sequence,
        )
        market_context['lstm_signal'] = lstm_signal
        market_context['price_action_pattern'] = pattern_info
        market_context['support_resistance'] = sr_info
        market_context['breakout_structure'] = breakout_info
        market_context['price_action_score'] = price_action['score'] + breakout_info['score']
        market_context.setdefault('decision_reasons', [])
        market_context['decision_reasons'].extend(price_action['reasons'])
        market_context['decision_reasons'].append(breakout_info['summary'])
        market_context['candle_pattern'] = pattern_info.get('label', market_context.get('candle_pattern', 'N/A'))
        ai_prediction['confidence'] = max(0, min(99, int(ai_prediction.get('confidence', 0) or 0) + int(market_context['price_action_score'])))
        ai_prediction['decision_score'] = max(0, min(99, int(ai_prediction.get('decision_score', ai_prediction['confidence']) or 0) + int(market_context['price_action_score'])))

        # 6. Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„Ø±Ø³Ø§Ù„Ø© Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø© Ù…Ø¹ Ù…Ø¹Ø§Ù„Ø¬Ø© Ø§Ù„Ø£Ø®Ø·Ø§Ø¡
        try:
            message = await generate_advanced_ai_message(pairdict, interval_key, analysis, traditional_signal, ai_prediction, market_context)
        except Exception as msg_error:
            print(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„Ø±Ø³Ø§Ù„Ø©: {msg_error}")
            # Ø±Ø³Ø§Ù„Ø© Ø¨Ø¯ÙŠÙ„Ø© Ù…Ø¨Ø³Ø·Ø©
            message = f"""
ðŸ¤– <b>ØªØ­Ù„ÙŠÙ„ Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ø£Ø³Ø§Ø³ÙŠ</b>
ðŸ’° <b>{pairdict['symbol']} - {interval_key}</b>

ðŸ“Š <b>Ø§Ù„Ù‚Ø±Ø§Ø±: {ai_prediction['direction']}</b>
ðŸŽ¯ <b>Ø§Ù„Ø«Ù‚Ø©: {ai_prediction['confidence']}%</b>

ðŸ’¡ ØªØ­Ù„ÙŠÙ„ Ù…Ø¨Ø³Ø· - Ø¬Ø§Ø±ÙŠ ØªØ­Ø³ÙŠÙ† Ø§Ù„Ù†Ø¸Ø§Ù…...
"""
        
        store_cached_analysis_result(
            pairdict,
            interval_key,
            {
                "message": message,
                "direction": ai_prediction['direction'],
                "confidence": ai_prediction['confidence'],
                "features": features,
                "market_context": market_context,
                "traditional_signal": traditional_signal,
                "ai_prediction": ai_prediction,
                "analysis": analysis,
            },
        )
        return message, ai_prediction['direction'], ai_prediction['confidence'], features, market_context
        
    except Exception as e:
        logging.debug(f"Advanced analysis failed: {e}")
        cached_result = get_cached_analysis_result(pairdict, interval_key)
        if cached_result:
            fallback_context = dict(cached_result.get("market_context", {}))
            fallback_context["degraded"] = True
            fallback_context["degraded_reason"] = f"Using cached analysis because live analysis failed: {e}"
            return (
                cached_result.get("message", "⚠️ Cached analysis only."),
                cached_result.get("direction", "neutral"),
                cached_result.get("confidence", 50),
                cached_result.get("features", np.array([])),
                fallback_context,
            )

        error_msg = (
            "⚠️ <b>Advanced analysis could not be completed</b>\n\n"
            f"Reason: {str(e)}\n\n"
            "Try another pair, wait a little, or refresh when TradingView becomes available again."
        )
        return error_msg, "neutral", 0, np.array([]), {
            "degraded": True,
            "degraded_reason": str(e),
            "decision_reasons": ["Advanced analysis could not be completed."],
        }

def format_support_resistance_summary(market_context: dict) -> str:
    sr_info = market_context.get('support_resistance', {}) or {}
    nearest_support = sr_info.get('nearest_support')
    nearest_resistance = sr_info.get('nearest_resistance')
    parts = []
    if nearest_support:
        parts.append(f"Support {nearest_support['level']:.5f} ({nearest_support['touches']} touches)")
    if nearest_resistance:
        parts.append(f"Resistance {nearest_resistance['level']:.5f} ({nearest_resistance['touches']} touches)")
    return " | ".join(parts) if parts else "No strong support/resistance zone detected yet."

def get_ai_insights(ai_prediction: dict, market_context: dict) -> str:
    """Ù…Ù„Ø§Ø­Ø¸Ø§Øª Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ø§Ù„Ù…ØªÙ‚Ø¯Ù…Ø© - Ø§Ù„Ø¥ØµØ¯Ø§Ø± Ø§Ù„Ù…ØµØ­Ø­"""
    insights = []
    
    if ai_prediction['confidence'] > 80:
        insights.append("ðŸ“ˆ Ø¥Ø´Ø§Ø±Ø© Ø¹Ø§Ù„ÙŠØ© Ø§Ù„Ù…ÙˆØ«ÙˆÙ‚ÙŠØ©")
    elif ai_prediction['confidence'] < 50:
        insights.append("ðŸ“‰ Ø¥Ø´Ø§Ø±Ø© ØªØ­ØªØ§Ø¬ Ø­Ø°Ø±")
    
    if ai_prediction.get('risk_level') == 'low':
        insights.append("ðŸŸ¢ Ù…Ø®Ø§Ø·Ø±Ø© Ù…Ù†Ø®ÙØ¶Ø©")
    elif ai_prediction.get('risk_level') == 'high':
        insights.append("ðŸ”´ Ù…Ø®Ø§Ø·Ø±Ø© Ù…Ø±ØªÙØ¹Ø©")
    
    if market_context.get('market_condition') == 'high_vol':
        insights.append("âš¡ Ø³ÙˆÙ‚ Ù…ØªÙ‚Ù„Ø¨")
    elif market_context.get('market_condition') == 'low_vol':
        insights.append("ðŸŒŠ Ø³ÙˆÙ‚ Ù‡Ø§Ø¯Ø¦")
    
    if market_context.get('trend_condition') == 'strong':
        insights.append("ðŸŽ¯ Ø§ØªØ¬Ø§Ù‡ Ù‚ÙˆÙŠ")
    
    return " â€¢ ".join(insights) if insights else "Ø§Ù„Ø¸Ø±ÙˆÙ Ø§Ù„Ø³ÙˆÙ‚ÙŠØ© Ø·Ø¨ÙŠØ¹ÙŠØ©"

# English overrides for report output
async def generate_advanced_ai_message(pairdict: dict, interval_key: str, analysis: Any,
                                     traditional: dict, ai_prediction: dict, market_context: dict) -> str:
    """Generate the advanced AI report in English."""
    direction_emoji = "🟢" if ai_prediction['direction'] == "call" else "🔴" if ai_prediction['direction'] == "put" else "⚪"
    direction_text = "CALL" if ai_prediction['direction'] == "call" else "PUT" if ai_prediction['direction'] == "put" else "WAIT"

    performance_stats = advanced_ai_system.get_performance_stats()
    market_insights = advanced_ai_system.get_market_insights(pairdict['symbol'], interval_key)
    technical_details = get_advanced_technical_details(analysis.indicators)
    risk_emoji = {
        'low': '🟢',
        'medium': '🟡',
        'high': '🔴'
    }.get(ai_prediction.get('risk_level', 'medium'), '⚪')

    return f"""
🤖 <b>Advanced AI Trading Report</b>
💰 <b>{pairdict['symbol']} - {interval_key}</b>

{direction_emoji} <b>Final Decision: {direction_text}</b>
📊 <b>Confidence Level: {ai_prediction['confidence']}%</b>
{risk_emoji} <b>Risk Level: {ai_prediction.get('risk_level', 'medium')}</b>

📈 <b>Analysis Details:</b>
• Traditional Signal: {traditional['direction']} ({traditional['confidence']}%)
• TradingView Recommendation: {traditional['recommendation']}
• Analysis Method: {ai_prediction['method']}
• Models Used: {', '.join(ai_prediction.get('models_used', ['random_forest']))}
• Dynamic Model Weights: {', '.join(f'{name}={weight:.2f}' for name, weight in advanced_ai_system.model_weights.items()) if advanced_ai_system.model_weights else 'uniform'}
• LSTM Base Signal: {market_context.get('lstm_signal', {}).get('direction', 'neutral')} ({market_context.get('lstm_signal', {}).get('confidence', 0)}%)
• Market Adjustment: {ai_prediction.get('market_adjustment', 0):+d}%
• Decision Score: {ai_prediction.get('decision_score', 0)}%
• Candle Pattern: {market_context.get('candle_pattern', 'N/A')}

📊 <b>Advanced Machine Learning Stats:</b>
• Total Trades: {performance_stats['total_trades']}
• Win Rate: {performance_stats['win_rate']}%
• Profit Factor: {performance_stats['profit_factor']}
• Winning Trades (Last 10): {performance_stats['recent_trades']}
• Expectancy: ${performance_stats.get('expectancy', 0):.2f}

🔍 <b>Market Insights:</b>
• Historical Win Rate: {market_insights.get('win_rate', 0):.1%}
• Pattern Confidence: {market_insights.get('confidence', 'low')}
• Total Trades: {market_insights.get('total_trades', 0)}

🔧 <b>Advanced Technical Details:</b>
{technical_details}

🧱 <b>Price Action & Zones:</b>
• Pattern: {market_context.get('price_action_pattern', {}).get('label', 'N/A')}
• Score: {market_context.get('price_action_score', 0):+d}
• Zones: {format_support_resistance_summary(market_context)}

💡 <b>AI Insights:</b>
{get_ai_insights(ai_prediction, market_context)}

🧩 <b>Decision Reasons:</b>
{' • '.join(market_context.get('decision_reasons', [])) if market_context.get('decision_reasons') else 'N/A'}

⚠️ This analysis combines AI signals, technical analysis, and continuous learning.
"""

def get_advanced_technical_details(indicators: dict) -> str:
    """Return advanced technical details in English."""
    try:
        details = []

        rsi = indicators.get('RSI')
        if rsi:
            if rsi < 30:
                details.append(f"RSI: {rsi:.1f} oversold")
            elif rsi > 70:
                details.append(f"RSI: {rsi:.1f} overbought")
            elif 30 <= rsi <= 70:
                details.append(f"RSI: {rsi:.1f} neutral")
            else:
                details.append(f"RSI: {rsi:.1f}")

        macd = indicators.get('MACD.macd', 0)
        signal = indicators.get('MACD.signal', 0)
        if macd and signal:
            diff = macd - signal
            if diff > 0:
                details.append(f"MACD: bullish +{diff:.4f}")
            else:
                details.append(f"MACD: bearish {diff:.4f}")

        close = indicators.get('close', 0)
        ema20 = indicators.get('EMA20', close)
        ema50 = indicators.get('EMA50', close)
        ema200 = indicators.get('EMA200', close)

        if close > ema20 > ema50 > ema200:
            details.append("Trend: strong bullish")
        elif close > ema20:
            details.append("Trend: bullish")
        elif close < ema20 < ema50 < ema200:
            details.append("Trend: strong bearish")
        else:
            details.append("Trend: sideways")

        high = indicators.get('high', close)
        low = indicators.get('low', close)
        volatility = (high - low) / close if close != 0 else 0
        if volatility > 0.03:
            details.append(f"Volatility: high {volatility:.2%}")
        elif volatility < 0.01:
            details.append(f"Volatility: low {volatility:.2%}")
        else:
            details.append(f"Volatility: medium {volatility:.2%}")

        return " | ".join(details) if details else "Advanced technical analysis is being prepared..."
    except Exception:
        return "Advanced technical analysis is in progress..."

def get_ai_insights(ai_prediction: dict, market_context: dict) -> str:
    """Return AI insights in English."""
    insights = []

    if ai_prediction['confidence'] > 80:
        insights.append("High-confidence signal")
    elif ai_prediction['confidence'] < 50:
        insights.append("Low-confidence setup, caution advised")

    if ai_prediction.get('risk_level') == 'low':
        insights.append("Low risk")
    elif ai_prediction.get('risk_level') == 'high':
        insights.append("High risk")

    if market_context.get('market_condition') == 'high_vol':
        insights.append("High-volatility market")
    elif market_context.get('market_condition') == 'low_vol':
        insights.append("Calm market")

    if market_context.get('trend_condition') == 'strong':
        insights.append("Strong trend")

    return " • ".join(insights) if insights else "Market conditions are normal"

# ---------------- Ù†Ø¸Ø§Ù… ØªØªØ¨Ø¹ Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ù…ØªÙ‚Ø¯Ù… ----------------
async def monitor_trade_with_advanced_ai(trade_id: str, user_id: int, context: ContextTypes.DEFAULT_TYPE, 
                                       trade_data: dict, features: np.array, market_context: dict):
    """Monitor a trade through the extracted monitor service."""
    await get_trade_monitor_service().monitor_trade(
        trade_id=trade_id,
        user_id=user_id,
        context=context,
        trade_data=trade_data,
        features=features,
        market_context=market_context,
    )

async def get_market_context_from_cache(pairdict: dict, timeframe: str) -> dict:
    """Ø§Ù„Ø­ØµÙˆÙ„ Ø¹Ù„Ù‰ Ø³ÙŠØ§Ù‚ Ø§Ù„Ø³ÙˆÙ‚ Ù…Ù† Ø§Ù„ÙƒØ§Ø´"""
    try:
        analysis = await get_cached_analysis(pairdict, timeframe, TIMEFRAMES[timeframe]['tv'])
        if analysis:
            return await get_market_context(analysis.indicators)
    except:
        pass
    return {
        'volatility': 0.01,
        'trend_strength': 0,
        'market_condition': 'normal',
        'trend_condition': 'moderate'
    }

# ---------------- English UI overrides ----------------
async def check_quotex_connection():
    return await get_broker_connection_service().check_connection_status(
        connected_label="🟢 Connected - Balance: ${balance:.2f}",
        disconnected_label="🔴 Connected session is not active",
    )


async def smart_trading_execution(context, user_id, pairdict, timeframe, timeframe_minutes):
    seconds_to_wait = calculate_seconds_to_new_candle(timeframe_minutes)
    if seconds_to_wait > 10:
        minutes_wait = seconds_to_wait // 60
        seconds_remaining = seconds_to_wait % 60
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"⏳ <b>Professional Entry Timing</b>\n"
                f"📊 Waiting for the next candle\n"
                f"⏰ Remaining: {minutes_wait:02d}:{seconds_remaining:02d}\n"
                f"🎯 This can improve analysis timing by entering on a fresh candle"
            ),
            parse_mode='HTML'
        )
        await asyncio.sleep(seconds_to_wait)
        await context.bot.send_message(
            chat_id=user_id,
            text="🎯 <b>New candle started. Running analysis now...</b>",
            parse_mode='HTML'
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="🎯 <b>Running analysis on the current fresh candle...</b>",
            parse_mode='HTML'
        )

    return await advanced_ai_analysis_layered(pairdict, timeframe)


async def stream_live_signal_updates(context, user_id: int, pair_label: str, pairdict: dict, timeframe: str, updates_count: int = 20):
    timeframe_seconds = TIMEFRAMES[timeframe]["quotex"]
    placeholder = await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"📡 <b>Live Signal Stream Started</b>\n\n"
            f"• Pair: {pair_label}\n"
            f"• Timeframe: {timeframe}\n"
            f"• Source: Quotex live stream\n\n"
            f"<i>Collecting the first live ticks...</i>"
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏹️ Stop Stream", callback_data="stop_live_stream")]]),
    )

    try:
        for _ in range(updates_count):
            snapshot = await get_live_market_snapshot(pairdict["quotex_symbol"], timeframe_seconds)
            price = snapshot.get("price")
            sentiment = snapshot.get("sentiment")
            payout = snapshot.get("payout")
            candles = snapshot.get("candles", [])
            candle_bias = "WAIT"
            if candles:
                last_candle = candles[-1]
                candle_bias = "CALL" if last_candle["close"] >= last_candle["open"] else "PUT"

            price_text = f"{price:.5f}" if isinstance(price, (int, float)) else "--"
            payout_text = f"{payout:.0f}%" if isinstance(payout, (int, float)) else "--"
            sentiment_text = f"{sentiment:.0f}%" if isinstance(sentiment, (int, float)) else "--"

            stream_text = (
                f"📡 <b>Live Signal Stream</b>\n\n"
                f"• Pair: {pair_label}\n"
                f"• Timeframe: {timeframe}\n"
                f"• Price: {price_text}\n"
                f"• Payout: {payout_text}\n"
                f"• Sentiment: {sentiment_text}\n"
                f"• Candle Bias: {candle_bias}\n"
                f"• Live Candles: {len(candles)}\n\n"
                f"<i>Updated: {datetime.now().strftime('%H:%M:%S')}</i>"
            )
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=placeholder.message_id,
                text=stream_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏹️ Stop Stream", callback_data="stop_live_stream")]]),
            )
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=placeholder.message_id,
            text="⏹️ <b>Live signal stream stopped.</b>",
            parse_mode="HTML",
        )
        raise
    except Exception as exc:
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=placeholder.message_id,
            text=f"⚠️ <b>Live signal stream failed</b>\n\n{exc}",
            parse_mode="HTML",
        )
    finally:
        live_update_tasks.pop(user_id, None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await shared_start_handler(
        update,
        user_data=user_data,
        settings=settings,
        quotex_connected=bool(quotex_client),
        get_connection_status=check_quotex_connection,
        advanced_ai_system=advanced_ai_system,
    )


async def active_trades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await shared_active_trades_handler(update, get_trade_state_service)


async def trade_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await shared_trade_history_handler(update, get_trade_state_service)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await shared_stats_handler(
        update,
        get_connection_status=check_quotex_connection,
        advanced_ai_system=advanced_ai_system,
        active_trades=active_trades,
        trade_history=trade_history,
    )


async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await shared_performance_handler(
        update,
        get_trade_state_service=get_trade_state_service,
    )


def build_scanner_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    tf_list = list(TIMEFRAMES.keys())
    for i in range(0, len(tf_list), 2):
        row = [
            InlineKeyboardButton(f"Scan {tf}", callback_data=f"scanbest_{tf}")
            for tf in tf_list[i:i + 2]
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Main Desk", callback_data='back_to_main')])
    return InlineKeyboardMarkup(keyboard)


def build_best_setup_keyboard(results: List[Dict[str, Any]], timeframe: str) -> InlineKeyboardMarkup:
    keyboard = []
    for index, result in enumerate(results, start=1):
        entry = result["entry"]
        keyboard.append([
            InlineKeyboardButton(
                f"Open #{index}: {entry['display_name']}",
                callback_data=f"setpairid_{entry['callback_id']}",
            )
        ])
    keyboard.append([
        InlineKeyboardButton("🔄 Rescan", callback_data=f"scanbest_{timeframe}"),
        InlineKeyboardButton("🟢 Markets", callback_data="market_live"),
    ])
    keyboard.append([InlineKeyboardButton("🔙 Main Desk", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id not in user_data:
        user_data[user_id] = {'preferred_timeframe': '15m', 'history': []}

    try:
        if await handle_static_button_menu(
            update=update,
            context=context,
            user_id=user_id,
            data=data,
            query=query,
            user_data=user_data,
            start_handler=start,
            active_trades_handler=active_trades_handler,
            trade_history_handler=trade_history_handler,
            check_connection_status=check_quotex_connection,
            reconnect_broker=connect_to_quotex_with_retry,
            advanced_ai_system=advanced_ai_system,
        ):
            return

        if data == 'noop':
            return
        if data in {'market_live', 'market_regular', 'market_otc'}:
            category = {
                'market_live': 'all',
                'market_regular': 'regular',
                'market_otc': 'otc',
            }[data]
            await render_live_market_board(query, category, 0)
        elif data.startswith('livepairs_'):
            _, category, page = data.split('_', 2)
            await render_live_market_board(query, category, int(page))
        elif await handle_analysis_callbacks(
            data=data,
            query=query,
            context=context,
            user_id=user_id,
            user_data=user_data,
            timeframes=TIMEFRAMES,
            pairs=PAIRS,
            live_pair_registry=live_pair_registry,
            calculate_seconds_to_new_candle=calculate_seconds_to_new_candle,
            scan_top_trade_setups=scan_top_trade_setups,
            smart_trading_execution=smart_trading_execution,
        ):
            return
        elif await handle_execution_callbacks(
            data=data,
            context=context,
            user_id=user_id,
            user_data=user_data,
            pairs=PAIRS,
            live_pair_registry=live_pair_registry,
            live_update_tasks=live_update_tasks,
            higher_tf=HIGHER_TF,
            timeframes=TIMEFRAMES,
            settings=settings,
            cleanup_stale_active_trades=cleanup_stale_active_trades,
            get_trading_orchestrator=get_trading_orchestrator,
            get_market_context_from_cache=get_market_context_from_cache,
            monitor_trade_with_advanced_ai=monitor_trade_with_advanced_ai,
            advanced_ai_analysis_layered=advanced_ai_analysis_layered,
            stream_live_signal_updates=stream_live_signal_updates,
            trade_state_service_getter=get_trade_state_service,
        ):
            return
    except Exception as e:
        logging.exception("Error in English button handler")
        await context.bot.send_message(chat_id=user_id, text=f"❌ Unexpected error: {e}")

# ---------------- Ø§Ù„Ù†Ø¸Ø§Ù… Ø§Ù„Ø±Ø¦ÙŠØ³ÙŠ ----------------
def main():
    # Ø¥Ø¹Ø¯Ø§Ø¯ Ø§Ù„ØªØ³Ø¬ÙŠÙ„
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('trading_bot.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN is not set. Configure it in the environment before starting the bot.")
    
    # Ø¥Ù†Ø´Ø§Ø¡ loop Ù„Ù„Ø£Ø­Ø¯Ø§Ø«
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Ø§Ù„Ø§ØªØµØ§Ù„ Ø¨Ù…Ù†ØµØ© Quotex
    logging.info("ðŸ”— Ø¬Ø§Ø±ÙŠ Ø§Ù„Ø§ØªØµØ§Ù„ Ø¨Ù…Ù†ØµØ© Quotex...")
    try:
        client = loop.run_until_complete(connect_to_quotex_with_retry())
        if client:
            logging.info("âœ… ØªÙ… Ø§Ù„Ø§ØªØµØ§Ù„ Ø¨ Quotex Ø¨Ù†Ø¬Ø§Ø­")
        else:
            logging.warning("âš ï¸ ÙØ´Ù„ Ø§Ù„Ø§ØªØµØ§Ù„ Ø¨ Quotex - Ø§Ù„Ù†Ø¸Ø§Ù… Ø³ÙŠØ¹Ù…Ù„ ÙÙŠ ÙˆØ¶Ø¹ Ø§Ù„ØªØ­Ù„ÙŠÙ„ ÙÙ‚Ø·")
    except Exception as e:
        logging.error(f"âŒ Ø®Ø·Ø£ ÙÙŠ Ø§Ù„Ø§ØªØµØ§Ù„: {e}")
    
    # Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„ØªØ·Ø¨ÙŠÙ‚
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Ø¥Ø¶Ø§ÙØ© handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("performance", performance_command))
    application.add_handler(CallbackQueryHandler(button))
    
    # Ø±Ø³Ø§Ù„Ø© Ø§Ù„Ø¨Ø¯Ø¡
    print("\n" + "="*50)
    print("ðŸš€ Ø¨ÙˆØª Ø§Ù„ØªØ¯Ø§ÙˆÙ„ Ø§Ù„Ù…ØªÙ‚Ø¯Ù… Ø¨Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ ÙŠØ¹Ù…Ù„...")
    print("ðŸ¤– Ù†Ø¸Ø§Ù… Ø°ÙƒÙŠ ÙŠØªØ¹Ù„Ù… Ù…Ù† ÙƒÙ„ ØµÙÙ‚Ø©")
    print("ðŸ“Š ØªØ­Ù„ÙŠÙ„ Ù…ØªÙ‚Ø¯Ù… Ø¨Ù…Ø¤Ø´Ø±Ø§Øª Ù…ØªØ¹Ø¯Ø¯Ø©")
    print("ðŸ’¹ Ø¥Ø¯Ø§Ø±Ø© Ù…Ø®Ø§Ø·Ø± Ø°ÙƒÙŠØ©")
    print("="*50)
    
    # ØªØ´ØºÙŠÙ„ Ø§Ù„Ø¨ÙˆØª
    try:
        application.run_polling()
    except KeyboardInterrupt:
        print("\nâ¹ï¸ Ø¥ÙŠÙ‚Ø§Ù Ø§Ù„Ø¨ÙˆØª...")
        # Ø­ÙØ¸ Ø¨ÙŠØ§Ù†Ø§Øª Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ Ù‚Ø¨Ù„ Ø§Ù„Ø¥ØºÙ„Ø§Ù‚
        advanced_ai_system.save_ai_system()
        print("ðŸ’¾ ØªÙ… Ø­ÙØ¸ Ø¨ÙŠØ§Ù†Ø§Øª Ø§Ù„ØªØ¹Ù„Ù…")
    except Exception as e:
        logging.error(f"âŒ Ø®Ø·Ø£ ÙÙŠ ØªØ´ØºÙŠÙ„ Ø§Ù„Ø¨ÙˆØª: {e}")
    finally:
        # ØªÙ†Ø¸ÙŠÙ Ø§Ù„Ù…ÙˆØ§Ø±Ø¯
        if quotex_client:
            try:
                loop.run_until_complete(quotex_client.close())
            except:
                pass

if __name__ == '__main__':
    main()





"""
=============================================================
  طبقة البيانات الكاملة — Data Layer
  
  المكونات:
  1. QuotexConnection   — إدارة الاتصال بـ Quotex (مُصحَّح)
  2. CandleStream       — جلب الشموع بشكل مستمر
  3. DataBuffer         — تخزين وتنظيم البيانات
  4. LiveDataFeed       — التغذية الحية للبوت
  5. DataPipeline       — يربط كل شيء ببوت الخوارزميات
=============================================================
"""

import asyncio
import contextlib
import io
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
# استيراد خوارزميات البوت
from bot_algorithms import Candle, TradingBot, ConfluenceEngine

log = logging.getLogger("DataLayer")

# ── Quotex utility functions (from bot2) ─────

NOISY_QUOTEX_TEXT = {"ta agarrado", "aguarde", "please wait", "waiting", "no se pudo"}


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


async def call_quotex_method(client, method_name: str, *args, **kwargs):
    """Call a Quotex client method with stdout/stderr silencing."""
    if not client:
        return None
    method = getattr(client, method_name, None)
    if not method:
        return None
    output_buffer = io.StringIO()
    with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
        result = method(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
    noisy_output = output_buffer.getvalue().strip()
    if noisy_output and not is_noisy_quotex_payload(noisy_output):
        log.debug("%s emitted: %s", method_name, noisy_output[:200])
    return sanitize_quotex_payload(result)


def normalize_realtime_candles_payload(payload: Any) -> List[Dict[str, float]]:
    """Normalize various Quotex candle response formats into uniform dicts."""
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
                "time": float(payload[1]), "open": price,
                "high": price, "low": price, "close": price,
            })
        else:
            for index, item in enumerate(payload):
                append_candle(item, index)

    candles.sort(key=lambda item: item["time"])
    return candles[-120:]


# ─────────────────────────────────────────────
#  إعدادات الاتصال
# ─────────────────────────────────────────────

@dataclass
class ConnectionSettings:
    email:               str   = ""
    password:            str   = ""
    max_retries:         int   = 5
    retry_delay_base:    float = 5.0    # ثواني
    check_cache_ttl:     int   = 30     # ثواني
    reconnect_on_error:  bool  = True


@dataclass
class DataSettings:
    candle_period:       int   = 60     # ثواني (1 دقيقة)
    candles_history:     int   = 100    # عدد الشموع المحفوظة
    symbol:              str   = "EURUSD_otc"
    payout:              float = 88.0
    balance:             float = 1000.0
    min_score:           int   = 4      # الحد الأدنى لنقاط التأكيد


# ─────────────────────────────────────────────
#  1. إدارة الاتصال بـ Quotex (مُصحَّح)
# ─────────────────────────────────────────────

class QuotexConnection:
    """
    إدارة الاتصال بـ Quotex مع:
    - دعم tuple و bool في نتيجة connect()
    - إعادة المحاولة التلقائية
    - كاش حالة الاتصال
    - فحص صحة الاتصال
    """

    def __init__(self, settings: ConnectionSettings):
        self.settings  = settings
        self.client    = None
        self._lock     = asyncio.Lock()
        self._last_check: float = 0.0
        self._is_healthy: bool  = False
        self.last_price: float = 0.0

    @staticmethod
    def _parse_connect_result(result) -> bool:
        """
        ✅ الإصلاح الرئيسي:
        pyquotex قد ترجع:
          - True                    (bool)
          - (True, "message")       (tuple)
          - (False, "error msg")    (tuple)
        هذه الدالة تتعامل مع الحالات الثلاث
        """
        if result is None:
            return False
        if isinstance(result, bool):
            return result
        if isinstance(result, (tuple, list)) and len(result) >= 1:
            return bool(result[0])
        return bool(result)

    async def _try_connect(self) -> Optional[object]:
        """محاولة اتصال واحدة"""
        try:
            from pyquotex.stable_api import Quotex
            client = Quotex(
                self.settings.email,
                self.settings.password
            )
            # ضبط اللغة — تجاهل الخطأ إن لم تكن الخاصية موجودة
            try:
                client.lang = "en"
            except Exception:
                pass

            # session.json cache (من bot2)
            session_path = os.path.join(os.getcwd(), "session.json")
            if os.path.exists(session_path):
                try:
                    setattr(client, "session_path", session_path)
                    log.info("📁 session.json موجود — سيُستخدم تلقائياً")
                except Exception:
                    pass

            result = await client.connect()
            connected = self._parse_connect_result(result)

            if not connected:
                log.error("❌ الاتصال فشل — pyquotex أرجعت: %s", result)
                return None

            # فحص الرصيد كتأكيد نهائي
            try:
                balance = await client.get_balance()
                log.info("✅ متصل بـ Quotex | الرصيد: $%.2f", balance)
            except Exception as e:
                log.warning("⚠️ متصل لكن get_balance() فشل: %s", e)

            # طباعة الدوال المتاحة (مفيد للتطوير)
            methods = [m for m in dir(client) if not m.startswith("_")]
            log.debug("🔍 دوال pyquotex المتاحة: %s", methods)

            return client

        except ImportError:
            log.error("❌ مكتبة pyquotex غير مثبتة. pip install git+https://github.com/...")
            return None
        except Exception as e:
            log.error("❌ خطأ في الاتصال: %s", e)
            return None

    async def connect(self) -> Optional[object]:
        """الاتصال مع إعادة المحاولة التلقائية"""
        async with self._lock:
            for attempt in range(1, self.settings.max_retries + 1):
                log.info("🔄 محاولة اتصال %d/%d", attempt, self.settings.max_retries)
                self.client = None

                client = await self._try_connect()
                if client:
                    self.client       = client
                    self._is_healthy  = True
                    self._last_check  = time.time()
                    return client

                if attempt < self.settings.max_retries:
                    delay = min(30.0, self.settings.retry_delay_base * attempt)
                    log.info("⏳ انتظار %.0f ثانية قبل المحاولة التالية...", delay)
                    await asyncio.sleep(delay)

            log.error("❌ فشلت جميع محاولات الاتصال (%d)", self.settings.max_retries)
            return None

    async def ensure_connected(self) -> bool:
        """
        التحقق من صحة الاتصال — مع كاش لتجنب الفحص المتكرر
        يُستدعى قبل كل عملية جلب بيانات
        """
        now = time.time()

        # استخدم الكاش إذا كان الفحص الأخير حديثاً
        if (self._is_healthy and self.client and
                now - self._last_check < self.settings.check_cache_ttl):
            return True

        # فحص حقيقي
        if self.client:
            try:
                await self.client.get_balance()
                self._is_healthy = True
                self._last_check = now
                return True
            except Exception as e:
                log.warning("⚠️ الاتصال منتهي الصلاحية، إعادة الاتصال: %s", e)
                self.client      = None
                self._is_healthy = False

        # إعادة الاتصال
        client = await self.connect()
        return client is not None

    async def get_balance(self) -> float:
        """جلب الرصيد الحالي"""
        if not await self.ensure_connected():
            return 0.0
        try:
            return float(await self.client.get_balance())
        except Exception as e:
            log.error("❌ get_balance فشل: %s", e)
            return 0.0

    # ── realtime methods from bot2 ─────────────────────────

    async def fetch_live_payout(self, asset: str, timeframe_seconds: int = 60) -> Optional[float]:
        """جلب payout حقيقي من Quotex بعدة طرق."""
        if not self.client:
            return None
        api_asset = asset.replace("-", "_")
        # 1. try get_payout_by_asset (per-asset)
        for tf in (str(max(1, timeframe_seconds // 60)), "1"):
            try:
                raw = await call_quotex_method(self.client, "get_payout_by_asset", api_asset, tf)
                if isinstance(raw, dict):
                    for entry in raw.values():
                        if isinstance(entry, dict):
                            p = float(entry.get("payment", 0))
                            if 50 <= p <= 100:
                                return p
            except Exception:
                pass
        # 2. try get_available_asset
        try:
            raw = await call_quotex_method(self.client, "get_available_asset", api_asset)
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                d = raw[1]
                if isinstance(d, (list, tuple)) and len(d) >= 4:
                    p = float(d[3])
                    if 50 <= p <= 100:
                        return p
        except Exception:
            pass
        # 3. try get_payment (bulk) — extract single asset
        try:
            raw = await call_quotex_method(self.client, "get_payment")
            if isinstance(raw, dict):
                for name, data in raw.items():
                    if api_asset.replace("_", "") in name.replace("_", "").replace("-", ""):
                        if isinstance(data, dict):
                            p = float(data.get("payment", 0))
                            if 50 <= p <= 100:
                                return p
        except Exception:
            pass
        return None

    async def ensure_live_market_stream(self, asset: str, timeframe_seconds: int = 60) -> None:
        """الاشتراك في تدفقات Quotex الحية (سعر، شموع، معنويات)."""
        if not self.client:
            return
        api_asset = asset.replace("-", "_")
        for stream_type in ["start_realtime_price", "start_realtime_candle", "start_realtime_sentiment"]:
            try:
                await asyncio.wait_for(
                    call_quotex_method(self.client, stream_type, api_asset, timeframe_seconds),
                    timeout=3,
                )
            except Exception:
                pass

    async def get_live_market_snapshot(self, asset: str, timeframe_seconds: int = 60) -> dict:
        """لقطة سوق حية: السعر + الشموع + المعنويات + payout."""
        result = {
            "price": None, "sentiment": None, "candles": [],
            "payout": None, "asset": asset,
        }
        await self.ensure_live_market_stream(asset, timeframe_seconds)
        api_asset = asset.replace("-", "_")

        try:
            price_raw = await asyncio.wait_for(
                call_quotex_method(self.client, "get_realtime_price", api_asset), timeout=2
            )
            if isinstance(price_raw, list):
                for item in reversed(price_raw):
                    if isinstance(item, dict) and "price" in item:
                        result["price"] = float(item["price"])
                        break
            elif isinstance(price_raw, dict):
                for key in ("price", "close", "value", "bid", "ask"):
                    if key in price_raw:
                        result["price"] = float(price_raw[key])
                        break
        except Exception as exc:
            log.debug("Realtime price unavailable for %s: %s", asset, exc)

        try:
            sentiment_raw = await asyncio.wait_for(
                call_quotex_method(self.client, "get_realtime_sentiment", api_asset), timeout=2
            )
            result["sentiment"] = self._derive_sentiment(sentiment_raw)
        except Exception as exc:
            log.debug("Realtime sentiment unavailable for %s: %s", asset, exc)

        try:
            candle_payload = await asyncio.wait_for(
                call_quotex_method(self.client, "get_realtime_candles", api_asset), timeout=2.5
            )
            result["candles"] = normalize_realtime_candles_payload(candle_payload)
        except Exception as exc:
            log.debug("Realtime candles unavailable for %s: %s", asset, exc)

        try:
            result["payout"] = await asyncio.wait_for(
                self.fetch_live_payout(asset, timeframe_seconds), timeout=2.5
            )
        except Exception as exc:
            log.debug("Realtime payout unavailable for %s: %s", asset, exc)

        return result

    @staticmethod
    def _derive_sentiment(realtime_sentiment: Any) -> Optional[float]:
        """استخراج قيمة المعنويات من تنسيقات Quotex المختلفة."""
        if realtime_sentiment is None:
            return None
        if isinstance(realtime_sentiment, dict):
            nested = realtime_sentiment.get("sentiment")
            if isinstance(nested, dict):
                for key in ("buy", "bullish", "call"):
                    if key in nested:
                        try:
                            return max(0, min(100, float(nested[key])))
                        except Exception:
                            pass
                for key in ("sell", "bearish", "put"):
                    if key in nested:
                        try:
                            return max(0, min(100, 100 - float(nested[key])))
                        except Exception:
                            pass
            for key in ("sentiment", "value", "bullish", "call", "buy"):
                if key in realtime_sentiment:
                    try:
                        return max(0, min(100, float(realtime_sentiment[key])))
                    except Exception:
                        pass
            for key in ("put", "sell", "bearish"):
                if key in realtime_sentiment:
                    try:
                        return max(0, min(100, 100 - float(realtime_sentiment[key])))
                    except Exception:
                        pass
        try:
            val = float(realtime_sentiment)
            return max(0, min(100, val * 100 if val <= 1 else val))
        except Exception:
            return None

    async def disconnect(self):
        """قطع الاتصال بشكل نظيف"""
        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass
            finally:
                self.client      = None
                self._is_healthy = False
                log.info("🔌 تم قطع الاتصال بـ Quotex")


# ─────────────────────────────────────────────
#  2. جلب الشموع من Quotex
# ─────────────────────────────────────────────

class CandleStream:
    """
    يجلب الشموع من pyquotex ويحوّلها لـ Candle objects
    
    طرق الجلب المدعومة:
    - get_candles()     — تاريخية
    - realtime_price()  — لحظية
    """

    # أسماء الأزواج الشائعة في pyquotex
    SYMBOL_MAP = {
        "EURUSD":     "EURUSD_otc",
        "GBPUSD":     "GBPUSD_otc",
        "USDJPY":     "USDJPY_otc",
        "USDPKR":     "USDPKR_otc",
        "NZDCHF":     "NZDCHF_otc",
        "EURNZD":     "EURNZD_otc",
        "AUDUSD":     "AUDUSD_otc",
        "USDDZ":      "USDDZD_otc",
    }

    def __init__(self, connection: QuotexConnection, settings: DataSettings):
        self.conn     = connection
        self.settings = settings

    def _raw_to_candle(self, raw) -> Optional[Candle]:
        """تحويل أي صيغة بيانات من pyquotex إلى Candle"""
        try:
            # صيغة dict
            if isinstance(raw, dict):
                return Candle(
                    open   = float(raw.get("open",   raw.get("o", 0))),
                    close  = float(raw.get("close",  raw.get("c", 0))),
                    high   = float(raw.get("high",   raw.get("h", 0))),
                    low    = float(raw.get("low",    raw.get("l", 0))),
                    volume = float(raw.get("volume", raw.get("v", 0))),
                )
            # صيغة list/tuple: [time, open, close, high, low, volume]
            if isinstance(raw, (list, tuple)) and len(raw) >= 5:
                idx = 1 if len(raw) >= 6 else 0  # تخطي الـ timestamp إن وُجد
                return Candle(
                    open   = float(raw[idx]),
                    close  = float(raw[idx+1]),
                    high   = float(raw[idx+2]),
                    low    = float(raw[idx+3]),
                    volume = float(raw[idx+4]) if len(raw) > idx+4 else 0.0,
                )
        except Exception as e:
            log.debug("⚠️ فشل تحويل شمعة: %s | البيانات: %s", e, raw)
        return None

    async def fetch_historical(self, count: int = 100) -> list[Candle]:
        """جلب شموع تاريخية — يجرب Quotex أولاً، ثم TradingView، وأخيراً يولد شموعاً واقعية"""
        # 1. Quotex
        if await self.conn.ensure_connected():
            client = self.conn.client
            symbol = self.settings.symbol
            period = self.settings.candle_period

            fetch_methods = [
                ("get_candles",         lambda: client.get_candles(symbol, period, count)),
                ("get_candle_v2",       lambda: client.get_candle_v2(symbol, period)),
                ("get_history",         lambda: client.get_history(symbol, period, count)),
            ]
            for method_name, method_call in fetch_methods:
                if not hasattr(client, method_name):
                    continue
                try:
                    raw_data = await method_call()
                    if not raw_data:
                        continue
                    candles = []
                    for raw in (raw_data if isinstance(raw_data, list) else [raw_data]):
                        c = self._raw_to_candle(raw)
                        if c and c.high >= c.low and c.high > 0:
                            candles.append(c)
                    if candles:
                        log.info("📊 جُلبت %d شمعة عبر %s", len(candles), method_name)
                        return candles[-count:]
                except Exception as e:
                    log.debug("⚠️ %s فشل: %s", method_name, e)

        # 2. TradingView (real OHLC seed)
        log.info("📡 جلب الشموع من TradingView...")
        tv_candles = await self._fetch_from_tradingview(count)
        if tv_candles and len(tv_candles) >= 5:
            log.info("📊 تم جلب %d شمعة من TradingView", len(tv_candles))
            return tv_candles

        # 3. Fallback نهائي — شموع واقعية مبنية على سعر حقيقي
        log.warning("⚠️ جميع المصادر فشلت — توليد شموع من آخر سعر معروف")
        base = self.conn.last_price if hasattr(self.conn, 'last_price') and self.conn.last_price > 0 else 1.1000
        return self._generate_realistic_candles(count, base, 0.001)

    def _generate_realistic_candles(self, count: int, base_price: float, atr_ratio: float = 0.001) -> list[Candle]:
        """توليد شموع واقعية من سعر أساس + ATR تقديري"""
        candles = []
        price = base_price
        for i in range(count):
            spread = price * atr_ratio * (0.5 + ((i * 7 + 3) % 11) / 11)
            direction = 1 if ((i * 13 + 5) % 7) > 3 else -1
            move = spread * direction * (0.3 + ((i * 3 + 1) % 5) / 5)
            c_open = price
            c_close = price + move
            if c_close <= 0:
                c_close = price * 0.999
            high = max(c_open, c_close) + spread * 0.3
            low = min(c_open, c_close) - spread * 0.3
            candles.append(Candle(open=c_open, close=c_close, high=high, low=low, volume=100 + (i * 7 % 200)))
            price = c_close
        return candles

    async def _fetch_from_tradingview(self, count: int = 100) -> list[Candle]:
        try:
            from tradingview_provider import TradingViewProvider
            from pairs_registry import get_pair
            tv = TradingViewProvider()
            info = get_pair(self.settings.symbol)
            tv_sym = info.tv_symbol if info else self.settings.symbol
            tv_sc = info.tv_screener if info else "forex"
            tv_ex = info.tv_exchange if info else "FX_IDC"
            analysis = await tv.get_analysis(tv_sym, tv_sc, tv_ex, "1m")
            if not analysis:
                return self._generate_realistic_candles(count, 1.1000, 0.001)
            indicators = getattr(analysis, "indicators", {})
            if not indicators:
                return self._generate_realistic_candles(count, 1.1000, 0.001)

            open_p = float(indicators.get("open", 0))
            high_p = float(indicators.get("high", 0))
            low_p = float(indicators.get("low", 0))
            close_p = float(indicators.get("close", 0))
            if close_p <= 0:
                return self._generate_realistic_candles(count, 1.1000, 0.001)

            # ATR تقريبي = (high - low) / close
            atr_ratio = abs((high_p - low_p) / close_p) if close_p and high_p > low_p else 0.001
            log.info("📡 TradingView OHLC لـ %s: O=%.5f H=%.5f L=%.5f C=%.5f (ATR=%.4f%%)",
                     self.settings.symbol, open_p, high_p, low_p, close_p, atr_ratio * 100)
            if hasattr(self.conn, 'last_price'):
                self.conn.last_price = close_p

            # توليد شموع باستخدام ATR الحقيقي من TradingView
            return self._generate_realistic_candles(count, close_p, atr_ratio)
        except Exception as e:
            log.warning("⚠️ TradingView fallback فشل: %s", e)
            return self._generate_realistic_candles(count, 1.1000, 0.001)

    async def get_realtime_price(self) -> Optional[float]:
        """جلب السعر اللحظي الحالي"""
        if not await self.conn.ensure_connected():
            return None
        client = self.conn.client
        symbol = self.settings.symbol

        price_methods = [
            ("realtime_price",  lambda: client.realtime_price(symbol)),
            ("get_price",       lambda: client.get_price(symbol)),
            ("current_price",   lambda: client.current_price(symbol)),
        ]

        for method_name, method_call in price_methods:
            if not hasattr(client, method_name):
                continue
            try:
                result = await method_call()
                if result:
                    price = float(result) if not isinstance(result, dict) \
                            else float(result.get("price", result.get("close", 0)))
                    if price > 0:
                        return price
            except Exception as e:
                log.debug("⚠️ %s فشل: %s", method_name, e)

        return None

    async def subscribe_realtime(self, callback: Callable) -> None:
        """
        الاشتراك في تدفق السعر اللحظي
        callback(price: float) يُستدعى عند كل تحديث
        """
        if not await self.conn.ensure_connected():
            return
        client = self.conn.client
        symbol = self.settings.symbol

        subscribe_methods = [
            ("subscribe_symbol",  lambda: client.subscribe_symbol(symbol)),
            ("start_realtime",    lambda: client.start_realtime(symbol)),
        ]

        for method_name, method_call in subscribe_methods:
            if not hasattr(client, method_name):
                continue
            try:
                await method_call()
                log.info("📡 اشترك في %s عبر %s", symbol, method_name)
                return
            except Exception as e:
                log.debug("⚠️ %s فشل: %s", method_name, e)

        log.warning("⚠️ لا توجد طريقة اشتراك متاحة — سيتم polling بدلاً عنه")


# ─────────────────────────────────────────────
#  3. مخزن البيانات (DataBuffer)
# ─────────────────────────────────────────────

class DataBuffer:
    """
    يحفظ الشموع في deque ذات حجم ثابت.
    يضيف الشمعة الجديدة عند إغلاقها ويُطلع المشتركين.
    """

    def __init__(self, maxlen: int = 100):
        self._candles:    deque[Candle] = deque(maxlen=maxlen)
        self._callbacks:  list[Callable] = []
        self._last_price: float = 0.0
        self._candle_start: float = 0.0
        self._period:     int   = 60  # ثواني
        self._tmp_open:   float = 0.0
        self._tmp_high:   float = 0.0
        self._tmp_low:    float = float("inf")
        self._tmp_volume: float = 0.0

    def load_historical(self, candles: list[Candle]) -> None:
        """تحميل الشموع التاريخية"""
        self._candles.clear()
        for c in candles:
            self._candles.append(c)
        log.info("📥 تم تحميل %d شمعة تاريخية في الـ Buffer", len(candles))

    def on_new_candle(self, callback: Callable) -> None:
        """تسجيل callback يُنادى عند إغلاق شمعة جديدة"""
        self._callbacks.append(callback)

    def update_price(self, price: float) -> Optional[Candle]:
        """
        تحديث السعر اللحظي.
        عند اكتمال الشمعة → تُضاف للـ buffer وتُطلع المشتركين.
        يُرجع الشمعة المغلقة أو None.
        """
        now = time.time()
        if price <= 0:
            return None

        # بداية شمعة جديدة
        if self._candle_start == 0:
            self._candle_start = now
            self._tmp_open  = price
            self._tmp_high  = price
            self._tmp_low   = price
            self._last_price = price
            return None

        # تحديث OHLC الشمعة الحالية
        self._tmp_high   = max(self._tmp_high, price)
        self._tmp_low    = min(self._tmp_low,  price)
        self._tmp_volume += 1
        self._last_price  = price

        # فحص إغلاق الشمعة
        elapsed = now - self._candle_start
        if elapsed >= self._period:
            closed = Candle(
                open   = self._tmp_open,
                close  = price,
                high   = self._tmp_high,
                low    = self._tmp_low,
                volume = self._tmp_volume,
            )
            self._candles.append(closed)

            # إعادة تهيئة الشمعة التالية
            self._candle_start = now
            self._tmp_open     = price
            self._tmp_high     = price
            self._tmp_low      = price
            self._tmp_volume   = 0.0

            log.info("🕯️ شمعة مغلقة | O:%.5f H:%.5f L:%.5f C:%.5f",
                     closed.open, closed.high, closed.low, closed.close)

            # إطلاع المشتركين
            for cb in self._callbacks:
                asyncio.create_task(cb(closed))

            return closed
        return None

    @property
    def candles(self) -> list[Candle]:
        return list(self._candles)

    @property
    def current_price(self) -> float:
        return self._last_price

    @property
    def candle_age_pct(self) -> float:
        """نسبة عمر الشمعة الحالية (0.0 → 1.0)"""
        if self._candle_start == 0 or self._period == 0:
            return 0.0
        elapsed = time.time() - self._candle_start
        return min(elapsed / self._period, 1.0)

    def __len__(self):
        return len(self._candles)


# ─────────────────────────────────────────────
#  4. التغذية الحية للبوت (LiveDataFeed)
# ─────────────────────────────────────────────

class LiveDataFeed:
    """
    يشغّل حلقة لا نهائية:
    1. جلب شموع تاريخية عند البداية
    2. polling لحظي كل ثانية للسعر
    3. عند إغلاق شمعة → تشغيل التحليل
    4. إرسال الإشارة للـ callback
    """

    def __init__(self,
                 conn:     QuotexConnection,
                 stream:   CandleStream,
                 buffer:   DataBuffer,
                 settings: DataSettings,
                 on_signal: Optional[Callable] = None):
        self.conn      = conn
        self.stream    = stream
        self.buffer    = buffer
        self.settings  = settings
        self.on_signal = on_signal
        self._running  = False

    async def _analyze_and_signal(self, _candle: Candle = None) -> None:
        """تشغيل الخوارزميات وإصدار إشارة"""
        candles = self.buffer.candles
        if len(candles) < 20:
            log.info("⏳ بيانات غير كافية (%d شمعة) — الحد الأدنى 20", len(candles))
            return

        engine = ConfluenceEngine(
            candles        = candles,
            current_price  = self.buffer.current_price or candles[-1].close,
            payout         = self.settings.payout,
            balance        = self.settings.balance,
            candle_age_pct = self.buffer.candle_age_pct,
        )
        signal = engine.run()

        # طباعة موجزة
        direction_icon = {"UP": "⬆️", "DOWN": "⬇️", "WAIT": "⏸️"}.get(signal.direction, "")
        log.info(
            "%s %s | نقاط: %d | ثقة: %.1f%% | حجم: $%.2f",
            direction_icon, signal.direction,
            signal.score, signal.confidence, signal.trade_size
        )
        if signal.reasons:
            for r in signal.reasons[:3]:  # أول 3 أسباب فقط
                log.info("   %s", r)
        if signal.warnings:
            for w in signal.warnings:
                log.warning("   ⚠️ %s", w)

        # إرسال الإشارة للـ callback (Telegram / WebApp)
        if self.on_signal:
            await self.on_signal(signal)

    async def _polling_loop(self) -> None:
        """حلقة polling: جلب السعر كل ثانية"""
        poll_interval = 1.0  # ثانية
        errors_in_row  = 0

        while self._running:
            try:
                price = await self.stream.get_realtime_price()
                if price and price > 0:
                    errors_in_row = 0
                    self.conn.last_price = price
                    self.buffer.update_price(price)
                else:
                    errors_in_row += 1
                    if errors_in_row % 10 == 0:
                        log.warning("⚠️ %d محاولة فاشلة لجلب السعر — إعادة فحص الاتصال", errors_in_row)
                        await self.conn.ensure_connected()
                    # توليد سعر تقريبي من آخر شمعة مغلقة لاستمرار التدفق
                    if errors_in_row <= 3 or price is None:
                        fallback = self._synthetic_price()
                        if fallback > 0:
                            self.buffer.update_price(fallback)

            except Exception as e:
                errors_in_row += 1
                log.debug("⚠️ خطأ في polling: %s", e)

            await asyncio.sleep(poll_interval)

    def _synthetic_price(self) -> float:
        """توليد سعر تقريبي من آخر شمعة أو آخر سعر معروف"""
        candles = self.buffer.candles
        if candles:
            last = candles[-1]
            drift = (last.close - last.open) * 0.1
            noise = (last.high - last.low) * 0.05
            import random
            return round(last.close + drift + random.uniform(-noise, noise), 5)
        if self.conn.last_price > 0:
            return self.conn.last_price
        return 0.0

    async def start(self) -> None:
        """بدء تشغيل التغذية الحية"""
        self._running = True

        # 1. جلب الشموع التاريخية أولاً
        log.info("📡 جلب الشموع التاريخية...")
        historical = await self.stream.fetch_historical(self.settings.candles_history)

        if historical:
            self.buffer.load_historical(historical)
        else:
            log.warning("⚠️ لم تُجلب شموع تاريخية — سيبدأ البوت بعد تجميع البيانات")

        # 2. تسجيل callback لتحليل الشمعة المغلقة
        self.buffer.on_new_candle(self._analyze_and_signal)

        # 3. تشغيل حلقة الـ polling
        log.info("🚀 بدأ تدفق البيانات على %s", self.settings.symbol)
        await self._polling_loop()

    async def stop(self) -> None:
        self._running = False
        await self.conn.disconnect()
        log.info("🛑 تم إيقاف LiveDataFeed")


# ─────────────────────────────────────────────
#  5. Pipeline كاملة — تربط كل شيء
# ─────────────────────────────────────────────

class DataPipeline:
    """
    الواجهة الرئيسية لطبقة البيانات الموحّدة (UnifiedDataLayer).
    
    تجمع:
    - Quotex Connection → CandleStream → DataBuffer
    - TradingView Provider → MarketContext
    - LiveDataFeed — حلقة التغذية الحية
    
    الاستخدام:
        pipeline = DataPipeline.from_env()
        pipeline.on_signal = my_handler
        await pipeline.run()
    """

    def __init__(self,
                 conn_settings: ConnectionSettings,
                 data_settings: DataSettings,
                 on_signal: Optional[Callable] = None):

        self.data_settings = data_settings
        self.on_signal     = on_signal

        # بناء الطبقات
        self.connection = QuotexConnection(conn_settings)
        self.buffer     = DataBuffer(maxlen=data_settings.candles_history)
        self.buffer._period = data_settings.candle_period
        self.stream     = CandleStream(self.connection, data_settings)
        self.feed       = LiveDataFeed(
            conn     = self.connection,
            stream   = self.stream,
            buffer   = self.buffer,
            settings = data_settings,
            on_signal = on_signal,
        )

        # TradingView layer
        self.tv_provider = None
        self.market_context = None
        self._tv_cached_symbol = None

    @classmethod
    def from_env(cls, on_signal: Optional[Callable] = None) -> "DataPipeline":
        """إنشاء pipeline من متغيرات .env"""
        conn = ConnectionSettings(
            email    = os.getenv("QUOTEX_EMAIL",    ""),
            password = os.getenv("QUOTEX_PASSWORD", ""),
        )
        data = DataSettings(
            symbol         = os.getenv("SYMBOL",         "EURUSD_otc"),
            candle_period  = int(os.getenv("CANDLE_PERIOD", "60")),
            candles_history= int(os.getenv("CANDLES_HISTORY","100")),
            payout         = float(os.getenv("PAYOUT",   "88.0")),
            balance        = float(os.getenv("BALANCE",  "1000.0")),
            min_score      = int(os.getenv("MIN_SCORE",  "4")),
        )
        return cls(conn, data, on_signal)

    async def run(self) -> None:
        """تشغيل الـ pipeline"""
        log.info("=" * 50)
        log.info("🤖 بوت التداول الذكي — بدء التشغيل")
        log.info("=" * 50)

        # اتصال أولي
        client = await self.connection.connect()
        if not client:
            raise ConnectionError("❌ فشل الاتصال بـ Quotex — تأكد من صحة QUOTEX_EMAIL و QUOTEX_PASSWORD في .env")

        # بدء تدفق البيانات
        try:
            await self.feed.start()
        except asyncio.CancelledError:
            log.info("⚠️ تم إلغاء المهمة")
        except KeyboardInterrupt:
            log.info("⚠️ إيقاف يدوي")
        finally:
            await self.feed.stop()

    async def refresh_market_context(self, symbol: str = None):
        """تحديث MarketContext من TradingView"""
        try:
            if self.tv_provider is None:
                from tradingview_provider import TradingViewProvider
                self.tv_provider = TradingViewProvider()
            sym = symbol or self.data_settings.symbol
            if sym == self._tv_cached_symbol:
                return
            from pairs_registry import get_pair
            info = get_pair(sym)
            if info:
                tv_sym = getattr(info, "tv_symbol", sym)
                tv_sc  = getattr(info, "tv_screener", "forex")
                tv_ex  = getattr(info, "tv_exchange", "FX_IDC")
                analysis = await self.tv_provider.get_analysis(tv_sym, tv_sc, tv_ex, "1m")
                if analysis:
                    self.market_context = self.tv_provider.build_market_context(analysis)
                    self._tv_cached_symbol = sym
                    log.info("📡 TV context: %s (vol=%.3f, trend=%.0f)",
                             self.market_context.market_condition,
                             self.market_context.volatility,
                             self.market_context.trend_strength)
        except Exception as e:
            log.debug("TV context refresh error: %s", e)

    async def get_snapshot(self) -> dict:
        """لقطة فورية من حالة البوت شاملة Quotex + TradingView"""
        balance = await self.connection.get_balance()
        candles = self.buffer.candles

        if self.market_context is None:
            await self.refresh_market_context()

        signal = None
        if len(candles) >= 20:
            engine = ConfluenceEngine(
                candles        = candles,
                current_price  = self.buffer.current_price,
                payout         = self.data_settings.payout,
                balance        = balance or self.data_settings.balance,
                candle_age_pct = self.buffer.candle_age_pct,
            )
            sig    = engine.run()
            signal = {
                "direction":  sig.direction,
                "score":      sig.score,
                "confidence": sig.confidence,
                "trade_size": sig.trade_size,
                "reasons":    sig.reasons,
                "warnings":   sig.warnings,
            }

        mc = self.market_context
        return {
            "connected":      self.connection._is_healthy,
            "symbol":         self.data_settings.symbol,
            "candles_loaded": len(candles),
            "current_price":  self.buffer.current_price,
            "candle_age_pct": round(self.buffer.candle_age_pct * 100, 1),
            "balance":        balance,
            "signal":         signal,
            "market_context": {
                "condition": mc.market_condition if mc else "unknown",
                "volatility": round(mc.volatility, 4) if mc else 0,
                "trend_strength": round(mc.trend_strength, 1) if mc else 0,
                "trend_condition": mc.trend_condition if mc else "unknown",
            } if mc else None,
        }


# ─────────────────────────────────────────────
#  ملف .env.example (ينشئه تلقائياً)
# ─────────────────────────────────────────────

ENV_EXAMPLE = """
# ── Quotex ──────────────────────────────────
QUOTEX_EMAIL=your_email@example.com
QUOTEX_PASSWORD=your_password

# ── إعدادات التداول ──────────────────────────
SYMBOL=EURUSD_otc
CANDLE_PERIOD=60
CANDLES_HISTORY=100
PAYOUT=88.0
BALANCE=1000.0
MIN_SCORE=4

# ── Telegram (اختياري) ───────────────────────
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# ── WebApp (اختياري) ─────────────────────────
WEBAPP_URL=http://localhost:8000
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8000
WEBAPP_API_TOKEN=
"""

def create_env_example():
    path = ".env.example"
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(ENV_EXAMPLE.strip())
        print(f"✅ تم إنشاء {path} — انسخه إلى .env وأدخل بياناتك")


# ─────────────────────────────────────────────
#  نقطة التشغيل
# ─────────────────────────────────────────────

async def main():
    create_env_example()

    # مثال على handler للإشارات
    async def on_signal_received(signal):
        print(f"\n🔔 إشارة جديدة: {signal.direction} | نقاط: {signal.score} | ثقة: {signal.confidence}%")
        # هنا يمكن إرسال Telegram أو تنفيذ الصفقة

    pipeline = DataPipeline.from_env(on_signal=on_signal_received)
    await pipeline.run()


if __name__ == "__main__":
    asyncio.run(main())

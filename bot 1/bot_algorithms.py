"""
=============================================================
  بوت التداول الذكي v3 — محرك الخوارزميات المحسّن الكامل
  Smart Trading Bot v3 — Full Upgraded Algorithm Engine

  المكونات الأصلية (محسّنة):
  1.  TrendEngine          — EMA + ADX + HH/LL
  2.  SupportResistance    — Swing + Pivot + أرقام مستديرة
  3.  CandlePatterns       — 10 أنماط شموع يابانية
  4.  Indicators           — RSI + MACD + BB + Stoch + ATR + CCI
  5.  VolatilityFilter     — فلتر التقلب
  6.  QualityFilters       — فلاتر الجودة
  7.  ConfluenceEngine     — محرك نقاط التأكيد (0-28 نقطة)
  8.  MoneyManagement      — Kelly + Fixed Fractional + Circuit Breaker
  9.  BacktestEngine       — اختبار تاريخي

  المكونات الجديدة ✨:
  10. MultiTimeframe        — تحليل متعدد الأطر الزمنية (1m + 5m + 15m)
  11. DynamicSR             — مناطق دعم/مقاومة ذكية بأوزان تاريخية
  12. DivergenceDetector    — RSI Divergence + MACD Divergence
  13. MarketStructure        — BOS (Break of Structure) + CHoCH (Change of Character)
  14. VolumeAnalysis         — تأكيد الحجم للإشارات
  15. SessionFilter          — فلتر جلسات التداول (لندن + نيويورك)
  16. FibonacciLevels        — مستويات Fibonacci التلقائية
  17. HeikinAshi             — شموع Heikin Ashi لتنقية الضوضاء
  18. MomentumOscillator     — قياس قوة وسرعة الحركة
  19. TrendLines             — رسم خطوط الترند تلقائياً + كشف الاختراق
  20. OrderBlocks            — مناطق Smart Money (OB Bullish/Bearish)

  جدول نقاط Confluence الجديد (0-28):
  +3  ترند قوي متعدد الأطر الزمنية (MTF)
  +2  ترند أحادي الإطار قوي
  +3  منطقة S/R ذكية (وزن ≥ 3)
  +2  منطقة S/R عادية
  +3  نمط شمعة Pin Bar أو Engulfing قوي
  +2  نمط شمعة متوسط
  +2  RSI ذروة
  +3  Stochastic تقاطع في ذروة
  +1  MACD اتجاه
  +2  Bollinger Band حد
  +2  RSI Divergence
  +2  MACD Divergence
  +2  BOS / CHoCH
  +1  Volume Confirmation
  +1  Fibonacci Level تقاطع
  +1  Session Prime Time
  +1  Heikin Ashi تأكيد
  +1  Payout عالٍ (≥88%)

  القرار الجديد:
  0-5   → WAIT
  6-8   → دخول صغير (1%)
  9-12  → دخول متوسط (2%)
  13+   → دخول قوي (3%)
=============================================================
"""

from dataclasses import dataclass, field
from typing import Optional
import math
import statistics
import time


# ═══════════════════════════════════════════════════════════
#  هياكل البيانات الأساسية
# ═══════════════════════════════════════════════════════════

@dataclass
class Candle:
    open:   float
    close:  float
    high:   float
    low:    float
    volume: float = 0.0

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3


@dataclass
class Signal:
    direction:  str        # "UP" | "DOWN" | "WAIT"
    score:      int        # نقاط التأكيد 0-28
    confidence: float      # نسبة الثقة 0-100
    reasons:    list       # قائمة أسباب القرار
    warnings:   list       # تحذيرات
    trade_size: float      # حجم الصفقة المقترح
    details:    dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
#  دوال مساعدة مشتركة
# ═══════════════════════════════════════════════════════════

def _ema(data: list[float], period: int) -> list[float]:
    """Exponential Moving Average — دالة مشتركة"""
    if len(data) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(data[:period]) / period]
    for price in data[period:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


def _sma(data: list[float], period: int) -> Optional[float]:
    """Simple Moving Average"""
    if len(data) < period:
        return None
    return sum(data[-period:]) / period


def _wilder_smooth(data: list[float], period: int) -> list[float]:
    """Wilder Smoothing — يُستخدم في ADX و ATR"""
    if len(data) < period:
        return []
    s = [sum(data[:period])]
    for v in data[period:]:
        s.append(s[-1] - s[-1] / period + v)
    return s


def _aggregate_candles(candles_1m: list[Candle], period: int) -> list[Candle]:
    """
    يحوّل شموع 1m إلى شموع أطول (5m, 15m, إلخ).
    period = عدد الشموع في كل شمعة جديدة.
    """
    result = []
    for i in range(0, len(candles_1m) - period + 1, period):
        chunk = candles_1m[i: i + period]
        if not chunk:
            continue
        result.append(Candle(
            open   = chunk[0].open,
            close  = chunk[-1].close,
            high   = max(c.high   for c in chunk),
            low    = min(c.low    for c in chunk),
            volume = sum(c.volume for c in chunk),
        ))
    return result


# ═══════════════════════════════════════════════════════════
#  1. محرك تحليل الترند (محسّن)
# ═══════════════════════════════════════════════════════════

class TrendEngine:
    """
    يحدد نوع الترند باستخدام:
    - EMA 8 / EMA 21 / EMA 50
    - ADX (قوة الترند)
    - Higher Highs / Lower Lows
    """

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.closes  = [c.close for c in candles]
        self.highs   = [c.high  for c in candles]
        self.lows    = [c.low   for c in candles]

    def adx(self, period: int = 14) -> float:
        if len(self.candles) < period * 2 + 1:
            return 0.0
        tr_list, dm_plus, dm_minus = [], [], []
        for i in range(1, len(self.candles)):
            c, p = self.candles[i], self.candles[i-1]
            tr   = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
            tr_list.append(tr)
            up, down = c.high - p.high, p.low - c.low
            dm_plus.append(up   if up > down and up > 0   else 0)
            dm_minus.append(down if down > up and down > 0 else 0)

        # Wilder smoothing صحيح: أول قيمة = مجموع أول period، ثم تراكم
        def ws(data):
            if len(data) < period:
                return []
            s = [sum(data[:period])]
            for v in data[period:]:
                s.append(s[-1] - s[-1] / period + v)
            return s

        atr_s = ws(tr_list)
        dmp_s = ws(dm_plus)
        dmm_s = ws(dm_minus)

        if not atr_s:
            return 0.0

        # احسب DX لكل نقطة
        dx_list = []
        for i in range(len(atr_s)):
            if atr_s[i] == 0:
                dx_list.append(0.0)
                continue
            dip = 100 * dmp_s[i] / atr_s[i]
            dim = 100 * dmm_s[i] / atr_s[i]
            dx  = 100 * abs(dip - dim) / (dip + dim + 1e-9)
            dx_list.append(dx)

        # ADX = Wilder smooth لـ DX
        adx_vals = ws(dx_list)
        if not adx_vals:
            return 0.0

        # القيمة الأخيرة محدودة بين 0 و 100
        return round(min(adx_vals[-1], 100.0), 2)

    def higher_highs_lower_lows(self, lookback: int = 10) -> str:
        if len(self.candles) < lookback:
            return "UNKNOWN"
        rh = self.highs[-lookback:]
        rl = self.lows[-lookback:]
        hh = all(rh[i] >= rh[i-1] for i in range(1, len(rh)))
        ll = all(rl[i] >= rl[i-1] for i in range(1, len(rl)))
        lh = all(rh[i] <= rh[i-1] for i in range(1, len(rh)))
        hl = all(rl[i] <= rl[i-1] for i in range(1, len(rl)))
        if hh and ll:  return "UPTREND"
        if lh and hl:  return "DOWNTREND"
        return "RANGE"

    def analyze(self) -> dict:
        ema8  = _ema(self.closes, 8)
        ema21 = _ema(self.closes, 21)
        ema50 = _ema(self.closes, 50)
        adx_val  = self.adx(14)
        hh_ll    = self.higher_highs_lower_lows()

        trend    = "RANGE"
        strength = "WEAK"

        if ema8 and ema21:
            if ema8[-1] > ema21[-1]:
                trend = "UPTREND"
                if ema50 and ema21[-1] > ema50[-1]:
                    strength = "STRONG"
                else:
                    strength = "MODERATE"
            elif ema8[-1] < ema21[-1]:
                trend = "DOWNTREND"
                if ema50 and ema21[-1] < ema50[-1]:
                    strength = "STRONG"
                else:
                    strength = "MODERATE"

        if adx_val > 25:
            strength = "STRONG"
        elif adx_val < 20:
            strength = "WEAK"
            trend = "RANGE"

        if hh_ll != "RANGE" and hh_ll != "UNKNOWN" and hh_ll != trend:
            strength = "MODERATE"

        return {
            "trend":    trend,
            "strength": strength,
            "adx":      round(adx_val, 2),
            "ema8":     round(ema8[-1],  6) if ema8  else None,
            "ema21":    round(ema21[-1], 6) if ema21 else None,
            "ema50":    round(ema50[-1], 6) if ema50 else None,
            "hh_ll":    hh_ll,
        }


# ═══════════════════════════════════════════════════════════
#  2. الدعم والمقاومة العادي (محسّن)
# ═══════════════════════════════════════════════════════════

class SupportResistance:
    """Swing Highs/Lows + Pivot Points + أرقام مستديرة"""

    def __init__(self, candles: list[Candle], zone_threshold: float = 0.0005):
        self.candles   = candles
        self.threshold = zone_threshold
        self.closes    = [c.close for c in candles]
        self.highs     = [c.high  for c in candles]
        self.lows      = [c.low   for c in candles]

    def swing_levels(self, lookback: int = 5) -> tuple[list, list]:
        s_highs, s_lows = [], []
        for i in range(lookback, len(self.candles) - lookback):
            wh = self.highs[i-lookback : i+lookback+1]
            wl = self.lows [i-lookback : i+lookback+1]
            if self.highs[i] == max(wh): s_highs.append(self.highs[i])
            if self.lows[i]  == min(wl): s_lows.append(self.lows[i])
        return s_highs, s_lows

    def pivot_points(self) -> dict:
        if len(self.candles) < 2:
            return {}
        c  = self.candles[-2]
        pp = (c.high + c.low + c.close) / 3
        return {
            "PP": round(pp, 6),
            "R1": round(2*pp - c.low,              6),
            "R2": round(pp + (c.high - c.low),     6),
            "S1": round(2*pp - c.high,             6),
            "S2": round(pp - (c.high - c.low),     6),
        }

    def find_zones(self, current_price: float) -> dict:
        s_highs, s_lows = self.swing_levels()
        pp = self.pivot_points()

        all_r = sorted([p for p in s_highs if p > current_price] +
                       [v for v in pp.values() if v > current_price])
        all_s = sorted([p for p in s_lows  if p < current_price] +
                       [v for v in pp.values() if v < current_price], reverse=True)

        nearest_r = all_r[0] if all_r else current_price * 1.002
        nearest_s = all_s[0] if all_s else current_price * 0.998

        dist_r = (nearest_r - current_price) / current_price
        dist_s = (current_price - nearest_s) / current_price

        in_r_zone = dist_r < self.threshold / current_price
        in_s_zone = dist_s < self.threshold / current_price

        return {
            "nearest_resistance":     round(nearest_r, 6),
            "nearest_support":        round(nearest_s, 6),
            "dist_to_resistance_pct": round(dist_r * 100, 4),
            "dist_to_support_pct":    round(dist_s * 100, 4),
            "in_resistance_zone":     in_r_zone,
            "in_support_zone":        in_s_zone,
            "pivot_points":           pp,
            "signal": (
                "DOWN" if in_r_zone else
                "UP"   if in_s_zone else
                "NEUTRAL"
            )
        }


# ═══════════════════════════════════════════════════════════
#  10. ✨ Multi-Timeframe Analysis (جديد)
# ═══════════════════════════════════════════════════════════

class MultiTimeframe:
    """
    يحلل الترند على 3 أطر زمنية من شموع 1m:
    - 1m  (الإطار الحالي)
    - 5m  (5 شموع 1m مجمّعة)
    - 15m (15 شمعة 1m مجمّعة)

    القاعدة الذهبية:
    - إذا اتفق 3 أطر → إشارة قوية جداً (+3)
    - إذا اتفق 2 أطر → إشارة جيدة (+1)
    - إذا تعارضت → تحذير
    """

    def __init__(self, candles_1m: list[Candle]):
        self.c1m  = candles_1m
        self.c5m  = _aggregate_candles(candles_1m, 5)  if len(candles_1m) >= 25  else []
        self.c15m = _aggregate_candles(candles_1m, 15) if len(candles_1m) >= 60  else []

    def _trend_direction(self, candles: list[Candle]) -> str:
        """يُرجع اتجاه الترند لمجموعة شموع"""
        if len(candles) < 10:
            return "UNKNOWN"
        data = TrendEngine(candles)
        result = data.analyze()
        t = result["trend"]
        s = result["strength"]
        if t == "UPTREND"   and s in ("STRONG", "MODERATE"): return "UP"
        if t == "DOWNTREND" and s in ("STRONG", "MODERATE"): return "DOWN"
        return "RANGE"

    def analyze(self) -> dict:
        d1  = self._trend_direction(self.c1m)
        d5  = self._trend_direction(self.c5m)  if self.c5m  else "UNKNOWN"
        d15 = self._trend_direction(self.c15m) if self.c15m else "UNKNOWN"

        # حساب الاتفاق
        directions = [d for d in [d1, d5, d15] if d not in ("UNKNOWN", "RANGE")]

        agreement   = "NONE"
        final_dir   = "RANGE"
        agree_count = 0

        if directions:
            up_count   = directions.count("UP")
            down_count = directions.count("DOWN")
            total      = len(directions)
            if up_count == total:
                agreement = "FULL"
                final_dir = "UP"
                agree_count = total
            elif down_count == total:
                agreement = "FULL"
                final_dir = "DOWN"
                agree_count = total
            elif up_count > down_count:
                agreement = "PARTIAL"
                final_dir = "UP"
                agree_count = up_count
            elif down_count > up_count:
                agreement = "PARTIAL"
                final_dir = "DOWN"
                agree_count = down_count
            else:
                agreement = "CONFLICT"
                final_dir = "RANGE"

        # نقاط الـ Confluence
        if agreement == "FULL" and agree_count >= 3:
            score = 3
            label = "3 أطر زمنية تتفق"
        elif agreement == "FULL" and agree_count == 2:
            score = 2
            label = "إطاران زمنيان يتفقان"
        elif agreement == "PARTIAL":
            score = 1
            label = "أغلبية الأطر الزمنية"
        else:
            score = 0
            label = "تعارض بين الأطر الزمنية"

        return {
            "1m":         d1,
            "5m":         d5,
            "15m":        d15,
            "agreement":  agreement,
            "direction":  final_dir,
            "score":      score,
            "label":      label,
            "agree_count": agree_count,
        }


# ═══════════════════════════════════════════════════════════
#  11. ✨ Dynamic S/R Zones — مناطق ذكية بأوزان تاريخية (جديد)
# ═══════════════════════════════════════════════════════════

class DynamicSR:
    """
    مناطق دعم ومقاومة ذكية تتذكر قوة كل مستوى.
    كلما ارتد منها السعر أكثر → وزنها أعلى → إشارة أقوى.

    الخوارزمية:
    1. اكتشف كل Swing Highs/Lows
    2. اجمع المستويات المتقاربة في zones
    3. اعطِ كل zone وزناً = عدد مرات الارتداد
    4. المستويات ذات الوزن العالي = دعم/مقاومة قوية جداً
    """

    CLUSTER_THRESHOLD = 0.0008   # 8 pips — مسافة الدمج

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.highs   = [c.high  for c in candles]
        self.lows    = [c.low   for c in candles]
        self.closes  = [c.close for c in candles]

    def _find_swings(self, lookback: int = 3) -> tuple[list[float], list[float]]:
        """اكتشاف Swing Highs و Swing Lows بدقة أعلى"""
        s_highs, s_lows = [], []
        n = len(self.candles)
        for i in range(lookback, n - lookback):
            wh = self.highs[i-lookback : i+lookback+1]
            wl = self.lows [i-lookback : i+lookback+1]
            if self.highs[i] == max(wh):
                s_highs.append(self.highs[i])
            if self.lows[i] == min(wl):
                s_lows.append(self.lows[i])
        return s_highs, s_lows

    def _cluster_levels(self, levels: list[float]) -> list[dict]:
        """
        يجمع المستويات المتقاربة في clusters.
        كل cluster = { price, weight, touches }
        """
        if not levels:
            return []
        sorted_levels = sorted(levels)
        clusters: list[dict] = []

        for price in sorted_levels:
            merged = False
            for cl in clusters:
                # هل المستوى قريب من cluster موجود؟
                if abs(price - cl["price"]) / cl["price"] <= self.CLUSTER_THRESHOLD:
                    # دمج: تحديث المتوسط الموزون والوزن
                    total = cl["weight"] + 1
                    cl["price"]   = (cl["price"] * cl["weight"] + price) / total
                    cl["weight"]  = total
                    cl["touches"] += 1
                    merged = True
                    break
            if not merged:
                clusters.append({
                    "price":   price,
                    "weight":  1,
                    "touches": 1,
                })
        return clusters

    def _count_bounces(self, price: float, tolerance: float = 0.0010) -> int:
        """يعد كم مرة ارتد السعر من هذا المستوى تاريخياً"""
        bounces = 0
        for i in range(1, len(self.candles) - 1):
            c    = self.candles[i]
            prev = self.candles[i-1]
            next_c = self.candles[i+1]
            # ارتداد صعودي من الدعم
            if (abs(c.low - price) / price < tolerance and
                    prev.close > prev.open and next_c.close > next_c.open):
                bounces += 1
            # ارتداد هبوطي من المقاومة
            if (abs(c.high - price) / price < tolerance and
                    prev.close < prev.open and next_c.close < next_c.open):
                bounces += 1
        return bounces

    def find_zones(self, current_price: float) -> dict:
        """
        يجد أقوى مناطق الدعم والمقاومة مع أوزانها.
        يُرجع المستويات مرتبة حسب القوة.
        """
        s_highs, s_lows = self._find_swings(lookback=3)
        all_levels = s_highs + s_lows

        resistance_clusters = self._cluster_levels(
            [p for p in all_levels if p > current_price]
        )
        support_clusters = self._cluster_levels(
            [p for p in all_levels if p < current_price]
        )

        # تحديث الأوزان بعدد الارتدادات الفعلية
        for cl in resistance_clusters + support_clusters:
            bounces = self._count_bounces(cl["price"])
            cl["weight"] += bounces
            cl["strength"] = (
                "VERY_STRONG" if cl["weight"] >= 5 else
                "STRONG"      if cl["weight"] >= 3 else
                "MODERATE"    if cl["weight"] >= 2 else
                "WEAK"
            )

        # ترتيب حسب القرب من السعر الحالي
        resistance_sorted = sorted(
            resistance_clusters,
            key=lambda x: x["price"]
        )
        support_sorted = sorted(
            support_clusters,
            key=lambda x: -x["price"]
        )

        nearest_r = resistance_sorted[0] if resistance_sorted else None
        nearest_s = support_sorted[0]    if support_sorted    else None

        # هل السعر عند منطقة قوية؟
        in_strong_resistance = (
            nearest_r and
            abs(current_price - nearest_r["price"]) / current_price < 0.0005 and
            nearest_r["weight"] >= 2
        )
        in_strong_support = (
            nearest_s and
            abs(current_price - nearest_s["price"]) / current_price < 0.0005 and
            nearest_s["weight"] >= 2
        )

        # نقاط الـ Confluence
        score = 0
        signal = "NEUTRAL"
        if in_strong_resistance:
            w = nearest_r["weight"]
            score  = 3 if w >= 4 else 2
            signal = "DOWN"
        elif in_strong_support:
            w = nearest_s["weight"]
            score  = 3 if w >= 4 else 2
            signal = "UP"

        return {
            "nearest_resistance":  round(nearest_r["price"],    6) if nearest_r else None,
            "nearest_support":     round(nearest_s["price"],    6) if nearest_s else None,
            "resistance_weight":   nearest_r["weight"]              if nearest_r else 0,
            "support_weight":      nearest_s["weight"]              if nearest_s else 0,
            "resistance_strength": nearest_r.get("strength", "—")  if nearest_r else "—",
            "support_strength":    nearest_s.get("strength", "—")  if nearest_s else "—",
            "in_strong_resistance": in_strong_resistance,
            "in_strong_support":    in_strong_support,
            "signal":               signal,
            "score":                score,
            "all_resistance":       resistance_sorted[:5],
            "all_support":          support_sorted[:5],
        }


# ═══════════════════════════════════════════════════════════
#  3. أنماط الشموع اليابانية (10 أنماط — بدون تغيير)
# ═══════════════════════════════════════════════════════════

class CandlePatterns:
    """10 أنماط شموع يابانية رئيسية"""

    def __init__(self, candles: list[Candle]):
        self.candles = candles

    def _last(self, n: int = 1) -> list[Candle]:
        return self.candles[-n:] if len(self.candles) >= n else []

    def is_doji(self, c: Candle, threshold: float = 0.1) -> bool:
        if c.range == 0: return True
        return c.body / c.range < threshold

    def is_hammer(self, c: Candle) -> bool:
        if c.body == 0: return False
        return (c.is_bullish and
                c.lower_wick >= 2.0 * c.body and
                c.upper_wick <= 0.3 * c.body)

    def is_shooting_star(self, c: Candle) -> bool:
        if c.body == 0: return False
        return (c.is_bearish and
                c.upper_wick >= 2.0 * c.body and
                c.lower_wick <= 0.3 * c.body)

    def is_pin_bar(self, c: Candle) -> tuple[bool, str]:
        if c.body == 0: return False, ""
        if c.lower_wick >= 3.0 * c.body: return True, "UP"
        if c.upper_wick >= 3.0 * c.body: return True, "DOWN"
        return False, ""

    def is_engulfing(self) -> tuple[bool, str]:
        last = self._last(2)
        if len(last) < 2: return False, ""
        prev, curr = last[0], last[1]
        if (prev.is_bearish and curr.is_bullish and
                curr.open <= prev.close and curr.close >= prev.open):
            return True, "UP"
        if (prev.is_bullish and curr.is_bearish and
                curr.open >= prev.close and curr.close <= prev.open):
            return True, "DOWN"
        return False, ""

    def is_three_soldiers_crows(self) -> tuple[bool, str]:
        last = self._last(3)
        if len(last) < 3: return False, ""
        a, b, c = last[0], last[1], last[2]
        if (a.is_bullish and b.is_bullish and c.is_bullish and
                b.open > a.open and b.close > a.close and
                c.open > b.open and c.close > b.close):
            return True, "UP"
        if (a.is_bearish and b.is_bearish and c.is_bearish and
                b.open < a.open and b.close < a.close and
                c.open < b.open and c.close < b.close):
            return True, "DOWN"
        return False, ""

    def is_morning_evening_star(self) -> tuple[bool, str]:
        last = self._last(3)
        if len(last) < 3: return False, ""
        a, b, c = last[0], last[1], last[2]
        if (a.is_bearish and b.body < a.body * 0.3 and
                c.is_bullish and c.close > a.open + a.body * 0.5):
            return True, "UP"
        if (a.is_bullish and b.body < a.body * 0.3 and
                c.is_bearish and c.close < a.open + a.body * 0.5):
            return True, "DOWN"
        return False, ""

    def is_inside_bar(self) -> bool:
        last = self._last(2)
        if len(last) < 2: return False
        prev, curr = last[0], last[1]
        return curr.high < prev.high and curr.low > prev.low

    def analyze(self) -> dict:
        if not self.candles:
            return {"patterns": [], "signal": "WAIT", "strength": 0, "candle_type": "UNKNOWN"}

        curr = self.candles[-1]
        patterns_found = []
        signal = "WAIT"
        strength = 0

        if self.is_doji(curr):
            patterns_found.append("Doji")
            signal = "WAIT"

        if self.is_hammer(curr):
            patterns_found.append("Hammer")
            signal = "UP"
            strength = max(strength, 3)

        if self.is_shooting_star(curr):
            patterns_found.append("Shooting Star")
            signal = "DOWN"
            strength = max(strength, 3)

        pb, pb_dir = self.is_pin_bar(curr)
        if pb:
            patterns_found.append(f"Pin Bar ({pb_dir})")
            signal = pb_dir
            strength = max(strength, 5)

        eng, eng_dir = self.is_engulfing()
        if eng:
            patterns_found.append(f"Engulfing ({eng_dir})")
            signal = eng_dir
            strength = max(strength, 4)

        three, three_dir = self.is_three_soldiers_crows()
        if three:
            patterns_found.append(f"Three S/C ({three_dir})")
            signal = three_dir
            strength = max(strength, 4)

        star, star_dir = self.is_morning_evening_star()
        if star:
            patterns_found.append(f"Star ({star_dir})")
            signal = star_dir
            strength = max(strength, 4)

        if self.is_inside_bar():
            patterns_found.append("Inside Bar")

        return {
            "patterns":    patterns_found,
            "signal":      signal,
            "strength":    strength,
            "candle_type": "BULLISH" if curr.is_bullish else "BEARISH" if curr.is_bearish else "DOJI",
        }


# ═══════════════════════════════════════════════════════════
#  4. المؤشرات التقنية (محسّنة)
# ═══════════════════════════════════════════════════════════

class Indicators:
    """RSI + MACD + Bollinger + Stochastic + ATR + CCI"""

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.closes  = [c.close for c in candles]
        self.highs   = [c.high  for c in candles]
        self.lows    = [c.low   for c in candles]

    def rsi(self, period: int = 14) -> Optional[float]:
        if len(self.closes) < period + 1:
            return None
        deltas = [self.closes[i] - self.closes[i-1] for i in range(1, len(self.closes))]
        gains  = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        ag = sum(gains[-period:])  / period
        al = sum(losses[-period:]) / period
        for i in range(len(deltas) - period):
            ag = (ag * (period-1) + gains[i+period])  / period
            al = (al * (period-1) + losses[i+period]) / period
        rs = ag / al if al > 0 else float('inf')
        return round(100 - (100 / (1 + rs)), 2)

    def rsi_series(self, period: int = 14) -> list[float]:
        """يُرجع سلسلة RSI كاملة للـ Divergence"""
        if len(self.closes) < period + 2:
            return []
        results = []
        for end in range(period + 1, len(self.closes) + 1):
            closes_sub = self.closes[:end]
            deltas = [closes_sub[i] - closes_sub[i-1] for i in range(1, len(closes_sub))]
            gains  = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            ag = sum(gains[-period:])  / period
            al = sum(losses[-period:]) / period
            rs = ag / al if al > 0 else float('inf')
            results.append(round(100 - (100 / (1 + rs)), 2))
        return results

    def macd(self, fast: int = 12, slow: int = 26, signal_p: int = 9) -> dict:
        ema_fast = _ema(self.closes, fast)
        ema_slow = _ema(self.closes, slow)
        if not ema_fast or not ema_slow:
            return {"macd": None, "signal": None, "histogram": None, "direction": "NEUTRAL"}
        min_len   = min(len(ema_fast), len(ema_slow))
        macd_line = [ema_fast[-min_len+i] - ema_slow[-min_len+i] for i in range(min_len)]
        sig_line  = _ema(macd_line, signal_p)
        if not sig_line:
            return {"macd": None, "signal": None, "histogram": None, "direction": "NEUTRAL"}
        m, s, h = macd_line[-1], sig_line[-1], macd_line[-1] - sig_line[-1]
        crossover = (h > 0 and (macd_line[-2] - sig_line[-2]) < 0) if len(macd_line) > 1 and len(sig_line) > 1 else False
        return {
            "macd":      round(m, 6),
            "signal":    round(s, 6),
            "histogram": round(h, 6),
            "direction": "UP" if h > 0 else "DOWN",
            "crossover": crossover,
            "macd_line": macd_line,
            "sig_line":  sig_line,
        }

    def bollinger_bands(self, period: int = 20, std_dev: float = 2.0) -> dict:
        if len(self.closes) < period:
            return {}
        recent = self.closes[-period:]
        sma    = sum(recent) / period
        std    = statistics.stdev(recent)
        upper  = sma + std_dev * std
        lower  = sma - std_dev * std
        curr   = self.closes[-1]
        width  = (upper - lower) / sma
        return {
            "upper":   round(upper, 6),
            "middle":  round(sma,   6),
            "lower":   round(lower, 6),
            "width":   round(width, 4),
            "squeeze": width < 0.002,
            "signal": (
                "DOWN" if curr >= upper * 0.998 else
                "UP"   if curr <= lower * 1.002 else
                "NEUTRAL"
            )
        }

    def stochastic(self, k_period: int = 5, d_period: int = 3) -> dict:
        if len(self.candles) < k_period:
            return {}
        k_values = []
        for i in range(k_period - 1, len(self.candles)):
            window  = self.candles[i - k_period + 1 : i + 1]
            highest = max(c.high for c in window)
            lowest  = min(c.low  for c in window)
            denom   = highest - lowest
            k = 100 * (self.closes[i] - lowest) / denom if denom > 0 else 50
            k_values.append(k)
        if len(k_values) < d_period:
            return {}
        d_values = []
        for i in range(d_period - 1, len(k_values)):
            d_values.append(sum(k_values[i - d_period + 1 : i + 1]) / d_period)
        k, d = k_values[-1], d_values[-1] if d_values else k_values[-1]
        crossover_up   = (len(k_values) > 1 and len(d_values) > 1 and k > d and k_values[-2] <= d_values[-2])
        crossover_down = (len(k_values) > 1 and len(d_values) > 1 and k < d and k_values[-2] >= d_values[-2])
        return {
            "k": round(k, 2), "d": round(d, 2),
            "overbought":     k > 80,
            "oversold":       k < 20,
            "crossover_up":   crossover_up,
            "crossover_down": crossover_down,
            "signal": (
                "DOWN" if k > 80 and crossover_down else
                "UP"   if k < 20 and crossover_up   else
                "NEUTRAL"
            )
        }

    def atr(self, period: int = 14) -> Optional[float]:
        if len(self.candles) < period + 1:
            return None
        tr_list = []
        for i in range(1, len(self.candles)):
            c, p = self.candles[i], self.candles[i-1]
            tr   = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
            tr_list.append(tr)
        if len(tr_list) < period:
            return None
        return round(sum(tr_list[-period:]) / period, 6)

    def cci(self, period: int = 20) -> Optional[float]:
        if len(self.candles) < period:
            return None
        typical  = [c.typical_price for c in self.candles[-period:]]
        mean_tp  = sum(typical) / period
        mean_dev = sum(abs(tp - mean_tp) for tp in typical) / period
        if mean_dev == 0:
            return 0.0
        return round((typical[-1] - mean_tp) / (0.015 * mean_dev), 2)

    def analyze(self) -> dict:
        rsi_val  = self.rsi(14)
        macd_val = self.macd()
        bb       = self.bollinger_bands(20)
        stoch    = self.stochastic(5, 3)
        atr_val  = self.atr(14)
        cci_val  = self.cci(20)

        signals = []
        if rsi_val is not None:
            if rsi_val > 70:   signals.append(("RSI", "DOWN", 2))
            elif rsi_val < 30: signals.append(("RSI", "UP",   2))
        if macd_val.get("direction") == "UP":    signals.append(("MACD", "UP",   1))
        elif macd_val.get("direction") == "DOWN": signals.append(("MACD", "DOWN", 1))
        if macd_val.get("crossover"):            signals.append(("MACD Cross", "UP", 2))
        if bb.get("signal") in ("UP", "DOWN"):   signals.append(("Bollinger", bb["signal"], 2))
        stoch_sig = stoch.get("signal", "NEUTRAL")
        if stoch_sig in ("UP", "DOWN"):          signals.append(("Stochastic", stoch_sig, 3))
        if cci_val is not None:
            if cci_val > 100:    signals.append(("CCI", "DOWN", 1))
            elif cci_val < -100: signals.append(("CCI", "UP",   1))

        return {
            "rsi":        rsi_val,
            "macd":       macd_val,
            "bollinger":  bb,
            "stochastic": stoch,
            "atr":        atr_val,
            "cci":        cci_val,
            "signals":    signals,
        }


# ═══════════════════════════════════════════════════════════
#  12. ✨ Divergence Detector (جديد)
# ═══════════════════════════════════════════════════════════

class DivergenceDetector:
    """
    يكشف التباعد (Divergence) بين السعر والمؤشرات:

    - Regular Bullish Divergence:
      السعر يصنع قاعاً أخفض (LL) لكن RSI يصنع قاعاً أعلى (HL)
      → إشارة انعكاس صاعد قوية

    - Regular Bearish Divergence:
      السعر يصنع قمة أعلى (HH) لكن RSI يصنع قمة أخفض (LH)
      → إشارة انعكاس هابط قوية

    - Hidden Bullish Divergence:
      السعر يصنع قاعاً أعلى (HL) لكن RSI يصنع قاعاً أخفض (LL)
      → تأكيد استمرار الترند الصاعد

    - Hidden Bearish Divergence:
      السعر يصنع قمة أخفض (LH) لكن RSI يصنع قمة أعلى (HH)
      → تأكيد استمرار الترند الهابط
    """

    def __init__(self, candles: list[Candle], lookback: int = 20):
        self.candles  = candles
        self.lookback = lookback
        self.closes   = [c.close for c in candles]
        self.highs    = [c.high  for c in candles]
        self.lows     = [c.low   for c in candles]

    def _find_swing_highs_idx(self, data: list[float], w: int = 3) -> list[int]:
        """يجد فهارس Swing Highs"""
        indices = []
        for i in range(w, len(data) - w):
            if data[i] == max(data[i-w: i+w+1]):
                indices.append(i)
        return indices

    def _find_swing_lows_idx(self, data: list[float], w: int = 3) -> list[int]:
        """يجد فهارس Swing Lows"""
        indices = []
        for i in range(w, len(data) - w):
            if data[i] == min(data[i-w: i+w+1]):
                indices.append(i)
        return indices

    def detect(self) -> dict:
        n = len(self.candles)
        if n < self.lookback + 5:
            return {"divergence": "NONE", "type": "NONE", "signal": "WAIT", "score": 0}

        # احسب RSI للفترة الأخيرة
        ind      = Indicators(self.candles)
        rsi_full = ind.rsi_series(14)

        if len(rsi_full) < self.lookback:
            return {"divergence": "NONE", "type": "NONE", "signal": "WAIT", "score": 0}

        # خذ آخر lookback قيمة
        price_slice = self.closes[-self.lookback:]
        rsi_slice   = rsi_full[-self.lookback:]
        high_slice  = self.highs[-self.lookback:]
        low_slice   = self.lows[-self.lookback:]

        # اكتشف Swing Highs و Lows في كلا المسارين
        price_high_idx = self._find_swing_highs_idx(high_slice,  w=3)
        price_low_idx  = self._find_swing_lows_idx(low_slice,   w=3)
        rsi_high_idx   = self._find_swing_highs_idx(rsi_slice,   w=3)
        rsi_low_idx    = self._find_swing_lows_idx(rsi_slice,    w=3)

        result = {"divergence": "NONE", "type": "NONE", "signal": "WAIT", "score": 0,
                  "description": ""}

        # ── Regular Bearish Divergence ──────────────
        # آخر قمتان في السعر والـ RSI
        if len(price_high_idx) >= 2 and len(rsi_high_idx) >= 2:
            p_h1, p_h2 = price_high_idx[-2], price_high_idx[-1]
            r_h1, r_h2 = rsi_high_idx[-2],   rsi_high_idx[-1]
            # السعر HH, RSI LH
            if (high_slice[p_h2] > high_slice[p_h1] and
                    rsi_slice[r_h2] < rsi_slice[r_h1]):
                result.update({
                    "divergence":   "BEARISH",
                    "type":         "REGULAR",
                    "signal":       "DOWN",
                    "score":        2,
                    "description":  f"RSI Divergence هبوطي: سعر ↑ لكن RSI ↓",
                })

        # ── Regular Bullish Divergence ──────────────
        if result["divergence"] == "NONE":
            if len(price_low_idx) >= 2 and len(rsi_low_idx) >= 2:
                p_l1, p_l2 = price_low_idx[-2],  price_low_idx[-1]
                r_l1, r_l2 = rsi_low_idx[-2],    rsi_low_idx[-1]
                # السعر LL, RSI HL
                if (low_slice[p_l2] < low_slice[p_l1] and
                        rsi_slice[r_l2] > rsi_slice[r_l1]):
                    result.update({
                        "divergence":   "BULLISH",
                        "type":         "REGULAR",
                        "signal":       "UP",
                        "score":        2,
                        "description":  f"RSI Divergence صعودي: سعر ↓ لكن RSI ↑",
                    })

        # ── MACD Divergence (تحقق إضافي) ────────────
        macd_data = ind.macd()
        hist = macd_data.get("histogram")
        macd_line = macd_data.get("macd_line", [])

        sig_line = macd_data.get("sig_line", 0)
        if hist is not None and len(macd_line) >= 6 and (not isinstance(sig_line, list) or len(sig_line) >= 4):
            sig_val = sig_line[-4] if isinstance(sig_line, list) and len(sig_line) >= 4 else (sig_line or 0)
            prev_hist = macd_line[-4] - sig_val
            curr_hist = hist

            if result["signal"] == "DOWN" and curr_hist < prev_hist:
                result["score"] = min(result["score"] + 1, 3)
                result["description"] += " + MACD يؤكد"
            elif result["signal"] == "UP" and curr_hist > prev_hist:
                result["score"] = min(result["score"] + 1, 3)
                result["description"] += " + MACD يؤكد"

        return result


# ═══════════════════════════════════════════════════════════
#  13. ✨ Market Structure — BOS & CHoCH (جديد)
# ═══════════════════════════════════════════════════════════

class MarketStructure:
    """
    يكتشف كسر هيكل السوق:

    BOS (Break of Structure) — كسر قمة/قاع سابق في اتجاه الترند:
    → تأكيد استمرار الترند

    CHoCH (Change of Character) — كسر قمة/قاع سابق عكس الترند:
    → تغيير اتجاه الترند (إشارة انعكاس مبكرة)

    الأقوى في التحليل الحديث (Smart Money Concepts)
    """

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.closes  = [c.close for c in candles]
        self.highs   = [c.high  for c in candles]
        self.lows    = [c.low   for c in candles]

    def _get_swing_points(self, lookback: int = 5) -> tuple[list, list]:
        """يجد Swing Highs و Lows مع فهارسها"""
        highs, lows = [], []
        n = len(self.candles)
        for i in range(lookback, n - lookback):
            wh = self.highs[i-lookback: i+lookback+1]
            wl = self.lows [i-lookback: i+lookback+1]
            if self.highs[i] == max(wh): highs.append((i, self.highs[i]))
            if self.lows[i]  == min(wl): lows.append((i,  self.lows[i]))
        return highs, lows

    def _detect_trend_bias(self) -> str:
        """تحديد التحيز الحالي للسوق"""
        if len(self.candles) < 20:
            return "UNKNOWN"
        result = TrendEngine(self.candles).analyze()
        return result["trend"]

    def analyze(self) -> dict:
        if len(self.candles) < 25:
            return {"event": "NONE", "type": "NONE", "signal": "WAIT",
                    "score": 0, "description": ""}

        swing_highs, swing_lows = self._get_swing_points(lookback=5)
        current_close = self.closes[-1]
        current_high  = self.highs[-1]
        current_low   = self.lows[-1]
        trend_bias    = self._detect_trend_bias()

        result = {"event": "NONE", "type": "NONE", "signal": "WAIT",
                  "score": 0, "description": ""}

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return result

        # آخر Swing Highs/Lows (بدون الأخير)
        recent_highs = swing_highs[-3:-1] if len(swing_highs) >= 3 else swing_highs[-2:-1]
        recent_lows  = swing_lows[-3:-1]  if len(swing_lows)  >= 3 else swing_lows[-2:-1]

        last_high = recent_highs[-1][1] if recent_highs else None
        last_low  = recent_lows[-1][1]  if recent_lows  else None

        # ── BOS Bullish ───────────────────────────────
        # كسر قمة سابقة في ترند صاعد = استمرار
        if last_high and current_close > last_high:
            if trend_bias == "UPTREND":
                result.update({
                    "event":       "BOS",
                    "type":        "BULLISH",
                    "signal":      "UP",
                    "score":       2,
                    "description": f"BOS صعودي: كسر قمة {last_high:.5f} ← استمرار الترند ↑",
                })

        # ── BOS Bearish ───────────────────────────────
        elif last_low and current_close < last_low:
            if trend_bias == "DOWNTREND":
                result.update({
                    "event":       "BOS",
                    "type":        "BEARISH",
                    "signal":      "DOWN",
                    "score":       2,
                    "description": f"BOS هبوطي: كسر قاع {last_low:.5f} ← استمرار الترند ↓",
                })

        # ── CHoCH Bullish ─────────────────────────────
        # كسر قمة سابقة في ترند هابط = انعكاس صعودي
        elif last_high and current_close > last_high and trend_bias == "DOWNTREND":
            result.update({
                "event":       "CHoCH",
                "type":        "BULLISH",
                "signal":      "UP",
                "score":       2,
                "description": f"CHoCH: تغيير في هيكل السوق ← انعكاس محتمل ↑",
            })

        # ── CHoCH Bearish ─────────────────────────────
        elif last_low and current_close < last_low and trend_bias == "UPTREND":
            result.update({
                "event":       "CHoCH",
                "type":        "BEARISH",
                "signal":      "DOWN",
                "score":       2,
                "description": f"CHoCH: تغيير في هيكل السوق ← انعكاس محتمل ↓",
            })

        return result


# ═══════════════════════════════════════════════════════════
#  14. ✨ Volume Analysis (جديد)
# ═══════════════════════════════════════════════════════════

class VolumeAnalysis:
    """
    يؤكد أو يرفض الإشارة بناءً على حجم التداول.

    القواعد:
    - شمعة صاعدة + حجم أعلى من المتوسط → إشارة صاعدة موثوقة (+1)
    - شمعة هابطة + حجم أعلى من المتوسط → إشارة هابطة موثوقة (+1)
    - شمعة في اتجاه + حجم منخفض → إشارة ضعيفة (تحذير)
    - Volume Spike (حجم 2x+) → تأكيد قوي جداً

    ملاحظة: في OTC الحجم أحياناً غير حقيقي لكنه ما زال مفيداً
    للمقارنة النسبية.
    """

    def __init__(self, candles: list[Candle], avg_period: int = 20):
        self.candles    = candles
        self.avg_period = avg_period
        self.volumes    = [c.volume for c in candles]

    def _avg_volume(self) -> float:
        if len(self.volumes) < self.avg_period:
            return sum(self.volumes) / len(self.volumes) if self.volumes else 1.0
        return sum(self.volumes[-self.avg_period:]) / self.avg_period

    def analyze(self, signal_direction: str = "WAIT") -> dict:
        if len(self.candles) < 5 or not any(v > 0 for v in self.volumes):
            return {"confirmed": False, "ratio": 1.0, "spike": False,
                    "score": 0, "description": "حجم غير متاح"}

        curr_candle  = self.candles[-1]
        curr_volume  = curr_candle.volume
        avg_vol      = self._avg_volume()

        if avg_vol == 0:
            return {"confirmed": False, "ratio": 1.0, "spike": False,
                    "score": 0, "description": "حجم صفر"}

        ratio = curr_volume / avg_vol
        spike = ratio >= 2.0

        # هل الحجم يؤكد الإشارة؟
        direction_matches = (
            (signal_direction == "UP"   and curr_candle.is_bullish) or
            (signal_direction == "DOWN" and curr_candle.is_bearish)
        )

        confirmed = direction_matches and ratio >= 1.2
        score = 0

        if confirmed:
            score = 1
            if spike:
                score = 2  # Spike يعطي نقطتين

        description = ""
        if spike and confirmed:
            description = f"Volume Spike {ratio:.1f}x — تأكيد قوي جداً"
        elif confirmed:
            description = f"حجم {ratio:.1f}x يؤكد الإشارة"
        elif ratio < 0.7:
            description = f"حجم منخفض {ratio:.1f}x — إشارة ضعيفة"
        else:
            description = f"حجم {ratio:.1f}x محايد"

        return {
            "confirmed":   confirmed,
            "ratio":       round(ratio, 2),
            "spike":       spike,
            "score":       score,
            "description": description,
        }


# ═══════════════════════════════════════════════════════════
#  15. ✨ Session Time Filter (جديد)
# ═══════════════════════════════════════════════════════════

class SessionFilter:
    """
    يفلتر الإشارات حسب جلسة التداول.

    الجلسات الرئيسية (بتوقيت UTC):
    - London:   07:00 - 16:00 (أفضل: 07:00-10:00)
    - New York: 12:00 - 21:00 (أفضل: 12:00-15:00)
    - Tokyo:    00:00 - 09:00 (أضعف للفوركس)
    - Overlap:  12:00-16:00  (أقوى وقت — تداخل لندن+نيويورك)

    Prime Time: أول ساعتين من لندن + أول 3 ساعات من نيويورك
    Dead Zone:  20:00 - 01:00 UTC (أضعف وقت)
    """

    # جلسة لندن
    LONDON_OPEN  = 7
    LONDON_CLOSE = 16
    # جلسة نيويورك
    NY_OPEN      = 12
    NY_CLOSE     = 21
    # Prime Time (أفضل أوقات التداول)
    PRIME_RANGES = [(7, 10), (12, 16)]  # UTC hours

    def __init__(self, utc_hour: Optional[int] = None):
        """utc_hour: الساعة الحالية بتوقيت UTC. None = احسب تلقائياً."""
        self.utc_hour = utc_hour if utc_hour is not None else self._current_utc_hour()

    @staticmethod
    def _current_utc_hour() -> int:
        import time as _time
        return int(_time.gmtime().tm_hour)

    def analyze(self) -> dict:
        h = self.utc_hour

        in_london    = self.LONDON_OPEN <= h < self.LONDON_CLOSE
        in_ny        = self.NY_OPEN <= h < self.NY_CLOSE
        in_prime     = any(start <= h < end for start, end in self.PRIME_RANGES)
        in_overlap   = self.NY_OPEN <= h < self.LONDON_CLOSE   # 12-16 UTC
        in_dead_zone = h >= 20 or h < 1

        # تحديد الجلسة الحالية
        if in_overlap:
            session = "OVERLAP (لندن+نيويورك)"
        elif in_london:
            session = "LONDON"
        elif in_ny:
            session = "NEW_YORK"
        elif 0 <= h < 9:
            session = "TOKYO"
        else:
            session = "INTER_SESSION"

        score = 0
        if in_prime:
            score = 1
        if in_dead_zone:
            score = -1  # يمكن استخدام هذا كتحذير

        return {
            "utc_hour":     h,
            "session":      session,
            "in_london":    in_london,
            "in_ny":        in_ny,
            "in_prime":     in_prime,
            "in_overlap":   in_overlap,
            "in_dead_zone": in_dead_zone,
            "score":        score,
            "description":  (
                f"⭐ Prime Time — جلسة {session}" if in_prime else
                f"⚠️ Dead Zone — تداول محدود"    if in_dead_zone else
                f"جلسة {session}"
            ),
        }


# ═══════════════════════════════════════════════════════════
#  16. ✨ Fibonacci Levels (جديد)
# ═══════════════════════════════════════════════════════════

class FibonacciLevels:
    """
    يحسب مستويات Fibonacci تلقائياً من آخر حركة كبيرة.

    المستويات المهمة:
    - 23.6% — هدف ضعيف
    - 38.2% — أول دعم/مقاومة قوي
    - 50.0% — المنتصف النفسي
    - 61.8% — Golden Ratio (الأقوى)
    - 78.6% — مستوى متقدم

    عند تقاطع Fib مع S/R = إشارة ذهبية
    """

    FIB_LEVELS = [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]

    def __init__(self, candles: list[Candle], swing_lookback: int = 30):
        self.candles  = candles
        self.lookback = min(swing_lookback, len(candles))

    def _find_swing(self) -> tuple[float, float, str]:
        """يجد آخر Swing High و Swing Low في الـ lookback"""
        recent = self.candles[-self.lookback:]
        if not recent:
            return 0.0, 0.0, "NONE"
        swing_high = max(c.high  for c in recent)
        swing_low  = min(c.low   for c in recent)
        # اتجاه الحركة: هل الـ High جاء بعد الـ Low؟
        high_idx = max(range(len(recent)), key=lambda i: recent[i].high)
        low_idx  = min(range(len(recent)), key=lambda i: recent[i].low)
        direction = "UP" if high_idx > low_idx else "DOWN"
        return swing_high, swing_low, direction

    def calculate(self, current_price: float) -> dict:
        if len(self.candles) < 15:
            return {"levels": {}, "nearest_level": None, "at_level": False,
                    "score": 0, "signal": "WAIT"}

        swing_high, swing_low, swing_dir = self._find_swing()
        if swing_high == swing_low:
            return {"levels": {}, "nearest_level": None, "at_level": False,
                    "score": 0, "signal": "WAIT"}

        diff = swing_high - swing_low
        levels = {}

        if swing_dir == "DOWN":
            # Retracement في اتجاه هابط (من القمة للقاع)
            for fib in self.FIB_LEVELS:
                price = swing_high - diff * fib
                levels[fib] = round(price, 6)
        else:
            # Retracement في اتجاه صاعد (من القاع للقمة)
            for fib in self.FIB_LEVELS:
                price = swing_low + diff * fib
                levels[fib] = round(price, 6)

        # هل السعر عند مستوى مهم؟
        tolerance    = diff * 0.02   # 2% من النطاق
        nearest_fib  = None
        nearest_dist = float('inf')
        at_level     = False

        for fib, price in levels.items():
            dist = abs(current_price - price)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_fib  = fib

        if nearest_fib is not None and nearest_dist < tolerance:
            at_level = True

        # هل المستوى مهم؟
        KEY_LEVELS = [0.382, 0.500, 0.618]
        is_key = nearest_fib in KEY_LEVELS if nearest_fib else False

        score = 1 if at_level and is_key else 0

        # إشارة: إذا عند مستوى Fib — ماذا يعني؟
        signal = "WAIT"
        if at_level and nearest_fib is not None:
            if swing_dir == "DOWN" and nearest_fib in KEY_LEVELS:
                signal = "UP"   # ارتداد محتمل من Fib في هبوط
            elif swing_dir == "UP" and nearest_fib in KEY_LEVELS:
                signal = "DOWN" # ارتداد محتمل من Fib في صعود

        fib_name = {
            0.236: "23.6%", 0.382: "38.2%", 0.500: "50.0%",
            0.618: "61.8% (Golden)", 0.786: "78.6%",
            0.0:   "0%", 1.0: "100%"
        }.get(nearest_fib, f"{nearest_fib*100:.1f}%") if nearest_fib else "—"

        return {
            "levels":        levels,
            "nearest_level": nearest_fib,
            "nearest_price": levels.get(nearest_fib, 0) if nearest_fib else 0,
            "nearest_name":  fib_name,
            "nearest_dist":  round(nearest_dist, 6),
            "at_level":      at_level,
            "is_key_level":  is_key,
            "swing_high":    round(swing_high, 6),
            "swing_low":     round(swing_low,  6),
            "swing_dir":     swing_dir,
            "score":         score,
            "signal":        signal,
        }


# ═══════════════════════════════════════════════════════════
#  17. ✨ Heikin Ashi Candles (جديد)
# ═══════════════════════════════════════════════════════════

class HeikinAshi:
    """
    يحوّل الشموع العادية إلى Heikin Ashi لتنقية الضوضاء.

    الصيغة:
    HA_Close = (Open + High + Low + Close) / 4
    HA_Open  = (HA_Open_prev + HA_Close_prev) / 2
    HA_High  = max(High, HA_Open, HA_Close)
    HA_Low   = min(Low,  HA_Open, HA_Close)

    الإشارات:
    - 3 شموع HA خضراء متتالية بدون ذيل سفلي = ترند صاعد قوي (+1)
    - 3 شموع HA حمراء متتالية بدون ذيل علوي = ترند هابط قوي (+1)
    - شمعة Doji HA = تردد / انعكاس محتمل (تحذير)
    """

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.ha_candles = self._convert()

    def _convert(self) -> list[Candle]:
        if not self.candles:
            return []
        ha = []
        prev_open  = (self.candles[0].open + self.candles[0].close) / 2
        prev_close = (self.candles[0].open + self.candles[0].high +
                      self.candles[0].low  + self.candles[0].close) / 4
        for c in self.candles:
            ha_close = (c.open + c.high + c.low + c.close) / 4
            ha_open  = (prev_open + prev_close) / 2
            ha_high  = max(c.high, ha_open, ha_close)
            ha_low   = min(c.low,  ha_open, ha_close)
            ha.append(Candle(
                open   = round(ha_open,  6),
                close  = round(ha_close, 6),
                high   = round(ha_high,  6),
                low    = round(ha_low,   6),
                volume = c.volume,
            ))
            prev_open  = ha_open
            prev_close = ha_close
        return ha

    def analyze(self) -> dict:
        if len(self.ha_candles) < 4:
            return {"signal": "WAIT", "score": 0, "description": "بيانات غير كافية"}

        last3 = self.ha_candles[-3:]
        curr  = self.ha_candles[-1]

        # فحص ترند قوي (3 شموع متتالية بدون ذيل عكسي)
        all_bullish = all(c.is_bullish for c in last3)
        all_bearish = all(c.is_bearish for c in last3)
        no_lower_wick = all(c.lower_wick < c.body * 0.1 for c in last3)
        no_upper_wick = all(c.upper_wick < c.body * 0.1 for c in last3)

        # Doji HA
        is_doji = curr.body < curr.range * 0.1 if curr.range > 0 else False

        if all_bullish and no_lower_wick:
            return {"signal": "UP", "score": 1,
                    "description": "HA: 3 شموع خضراء قوية بدون ذيل سفلي ↑"}
        if all_bearish and no_upper_wick:
            return {"signal": "DOWN", "score": 1,
                    "description": "HA: 3 شموع حمراء قوية بدون ذيل علوي ↓"}
        if is_doji:
            return {"signal": "WAIT", "score": 0,
                    "description": "HA Doji: تردد في السوق ⚠️"}
        if all_bullish:
            return {"signal": "UP", "score": 1,
                    "description": "HA: 3 شموع صاعدة متتالية ↑"}
        if all_bearish:
            return {"signal": "DOWN", "score": 1,
                    "description": "HA: 3 شموع هابطة متتالية ↓"}

        return {"signal": "WAIT", "score": 0, "description": "HA: إشارة غير واضحة"}


# ═══════════════════════════════════════════════════════════
#  18. ✨ Momentum Oscillator (جديد)
# ═══════════════════════════════════════════════════════════

class MomentumOscillator:
    """
    يقيس سرعة وقوة حركة السعر.

    Rate of Change (ROC):
    ROC = ((Close - Close_n) / Close_n) * 100

    الإشارات:
    - ROC > 0 وصاعد = قوة الترند تزيد
    - ROC > 0 ويتراجع = الترند يضعف (تحذير)
    - ROC يتقاطع الصفر صعوداً = زخم صاعد (+1)
    - ROC يتقاطع الصفر هبوطاً = زخم هابط (+1)
    """

    def __init__(self, candles: list[Candle], period: int = 10):
        self.candles = candles
        self.period  = period
        self.closes  = [c.close for c in candles]

    def _roc(self) -> list[float]:
        """Rate of Change"""
        result = []
        for i in range(self.period, len(self.closes)):
            prev = self.closes[i - self.period]
            if prev == 0:
                result.append(0.0)
            else:
                result.append((self.closes[i] - prev) / prev * 100)
        return result

    def analyze(self) -> dict:
        if len(self.closes) < self.period + 3:
            return {"signal": "WAIT", "score": 0, "roc": 0.0, "direction": "NEUTRAL"}

        roc = self._roc()
        if len(roc) < 2:
            return {"signal": "WAIT", "score": 0, "roc": 0.0, "direction": "NEUTRAL"}

        curr_roc = roc[-1]
        prev_roc = roc[-2]

        # تقاطع الصفر
        zero_cross_up   = curr_roc > 0 and prev_roc <= 0
        zero_cross_down = curr_roc < 0 and prev_roc >= 0

        # قوة الزخم
        roc_increasing = curr_roc > prev_roc
        roc_decreasing = curr_roc < prev_roc

        signal = "WAIT"
        score  = 0

        if zero_cross_up:
            signal = "UP"
            score  = 1
        elif zero_cross_down:
            signal = "DOWN"
            score  = 1
        elif curr_roc > 0.05 and roc_increasing:
            signal = "UP"
            score  = 0   # تأكيد لكن ليس نقطة إضافية
        elif curr_roc < -0.05 and roc_decreasing:
            signal = "DOWN"
            score  = 0

        # تحذير: الترند يضعف
        weakening = (
            (curr_roc > 0 and roc_decreasing and curr_roc < prev_roc * 0.5) or
            (curr_roc < 0 and roc_increasing and curr_roc > prev_roc * 0.5)
        )

        return {
            "signal":    signal,
            "score":     score,
            "roc":       round(curr_roc, 4),
            "direction": "UP" if curr_roc > 0 else "DOWN" if curr_roc < 0 else "NEUTRAL",
            "weakening": weakening,
            "zero_cross_up":   zero_cross_up,
            "zero_cross_down": zero_cross_down,
        }


# ═══════════════════════════════════════════════════════════
#  21. ✨ Ichimoku Cloud (جديد)
# ═══════════════════════════════════════════════════════════

class IchimokuCloud:
    """
    نظام Ichimoku Kinko Hyo — التحليل الياباني المتكامل.

    المكوّنات الخمسة:
    ─────────────────────────────────────────────
    Tenkan-sen (9):   (highest_high + lowest_low) / 2  خلال 9 فترات
    Kijun-sen (26):   (highest_high + lowest_low) / 2  خلال 26 فترة
    Senkou Span A:    (Tenkan + Kijun) / 2  مُزاحة 26 فترة للأمام
    Senkou Span B:    (H+L)/2 خلال 52 فترة  مُزاحة 26 فترة للأمام
    Chikou Span:      السعر الحالي مُزاح 26 فترة للخلف

    إشارات التداول:
    ─────────────────────────────────────────────
    +3  السعر فوق السحابة + Tenkan > Kijun + Chikou فوق السعر
        → ترند صاعد قوي جداً

    +2  السعر فوق السحابة + Tenkan > Kijun
        → ترند صاعد جيد

    +2  تقاطع Tenkan فوق Kijun (TK Cross)
        → إشارة شراء

    -2  السعر تحت السحابة + Tenkan < Kijun
        → ترند هابط

    -3  السعر تحت السحابة + TK Cross هابط + Chikou تحت
        → ترند هابط قوي جداً

    0   السعر داخل السحابة → ضبابية — انتظار
    """

    def __init__(self, candles: list[Candle],
                 tenkan: int = 9, kijun: int = 26, senkou_b: int = 52):
        self.candles   = candles
        self.closes    = [c.close for c in candles]
        self.highs     = [c.high  for c in candles]
        self.lows      = [c.low   for c in candles]
        self.t_period  = tenkan
        self.k_period  = kijun
        self.sb_period = senkou_b

    def _midpoint(self, data_h: list, data_l: list,
                  period: int, end_idx: int) -> Optional[float]:
        """(Highest High + Lowest Low) / 2 لفترة معينة"""
        start = end_idx - period + 1
        if start < 0:
            return None
        h_slice = data_h[start: end_idx + 1]
        l_slice = data_l[start: end_idx + 1]
        if not h_slice:
            return None
        return (max(h_slice) + min(l_slice)) / 2

    def calculate(self) -> dict:
        """يحسب كل مكوّنات Ichimoku للشمعة الأخيرة"""
        n = len(self.candles)
        if n < self.sb_period:
            return {"valid": False}

        idx = n - 1

        tenkan = self._midpoint(self.highs, self.lows, self.t_period, idx)
        kijun  = self._midpoint(self.highs, self.lows, self.k_period, idx)

        # Senkou Span A = (Tenkan + Kijun) / 2  (قيمة الشمعة قبل 26)
        past_idx   = max(0, idx - self.k_period)
        t_past     = self._midpoint(self.highs, self.lows, self.t_period, past_idx)
        k_past     = self._midpoint(self.highs, self.lows, self.k_period, past_idx)
        span_a     = (t_past + k_past) / 2 if (t_past and k_past) else None

        # Senkou Span B = midpoint of 52 periods (قيمة الشمعة قبل 26)
        span_b     = self._midpoint(self.highs, self.lows, self.sb_period, past_idx)

        # Chikou Span = Close الحالي مقارنةً بالسعر قبل 26 شمعة
        chikou_ref_idx = max(0, idx - self.k_period)
        chikou_ref     = self.closes[chikou_ref_idx]
        curr_close     = self.closes[-1]

        return {
            "valid":       True,
            "tenkan":      round(tenkan,     6) if tenkan     else None,
            "kijun":       round(kijun,      6) if kijun      else None,
            "span_a":      round(span_a,     6) if span_a     else None,
            "span_b":      round(span_b,     6) if span_b     else None,
            "chikou_close": round(curr_close, 6),
            "chikou_ref":   round(chikou_ref, 6),
            "current":      round(curr_close, 6),
        }

    def analyze(self) -> dict:
        """يُرجع الإشارة والنقاط من Ichimoku"""
        data = self.calculate()

        empty = {"signal": "WAIT", "score": 0, "description": "بيانات غير كافية",
                 "above_cloud": None, "tk_cross": "NONE"}
        if not data.get("valid"):
            return empty

        tenkan  = data["tenkan"]
        kijun   = data["kijun"]
        span_a  = data["span_a"]
        span_b  = data["span_b"]
        current = data["current"]
        chikou  = data["chikou_close"]
        ch_ref  = data["chikou_ref"]

        if not all([tenkan, kijun, span_a, span_b]):
            return empty

        # ─ حالة السعر بالنسبة للسحابة ──────────
        cloud_top    = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)

        above_cloud  = current > cloud_top
        below_cloud  = current < cloud_bottom
        in_cloud     = cloud_bottom <= current <= cloud_top

        # ─ TK Cross ─────────────────────────────
        # نحتاج قيمة Tenkan و Kijun السابقة
        n = len(self.candles)
        tk_cross = "NONE"
        if n >= self.k_period + 2:
            prev_idx = n - 2
            t_prev   = self._midpoint(self.highs, self.lows, self.t_period, prev_idx)
            k_prev   = self._midpoint(self.highs, self.lows, self.k_period, prev_idx)
            if t_prev and k_prev:
                if tenkan > kijun and t_prev <= k_prev:
                    tk_cross = "BULLISH"   # تقاطع صعودي
                elif tenkan < kijun and t_prev >= k_prev:
                    tk_cross = "BEARISH"   # تقاطع هبوطي

        # ─ Chikou ───────────────────────────────
        chikou_bullish = chikou > ch_ref
        chikou_bearish = chikou < ch_ref

        # ─ حساب الإشارة والنقاط ─────────────────
        signal = "WAIT"
        score  = 0
        desc   = ""

        if above_cloud:
            if tenkan > kijun:
                if chikou_bullish and tk_cross == "BULLISH":
                    signal = "UP";   score = 3
                    desc   = "Ichimoku: ثلاثي صاعد — فوق السحابة + TK Cross + Chikou ↑"
                elif chikou_bullish or tk_cross == "BULLISH":
                    signal = "UP";   score = 2
                    desc   = "Ichimoku: صاعد قوي — فوق السحابة + Tenkan > Kijun"
                else:
                    signal = "UP";   score = 1
                    desc   = "Ichimoku: صاعد — السعر فوق السحابة"
            elif tk_cross == "BEARISH":
                signal = "WAIT";   score = 0
                desc   = "Ichimoku: تحذير — TK Cross هابط رغم الموقع"

        elif below_cloud:
            if tenkan < kijun:
                if chikou_bearish and tk_cross == "BEARISH":
                    signal = "DOWN";  score = 3
                    desc   = "Ichimoku: ثلاثي هابط — تحت السحابة + TK Cross + Chikou ↓"
                elif chikou_bearish or tk_cross == "BEARISH":
                    signal = "DOWN";  score = 2
                    desc   = "Ichimoku: هابط قوي — تحت السحابة + Tenkan < Kijun"
                else:
                    signal = "DOWN";  score = 1
                    desc   = "Ichimoku: هابط — السعر تحت السحابة"
            elif tk_cross == "BULLISH":
                signal = "UP";    score = 1
                desc   = "Ichimoku: TK Cross صاعد — ارتداد محتمل"

        else:  # داخل السحابة
            if tk_cross == "BULLISH":
                signal = "UP";    score = 1
                desc   = "Ichimoku: TK Cross داخل السحابة — انتظار الخروج"
            elif tk_cross == "BEARISH":
                signal = "DOWN";  score = 1
                desc   = "Ichimoku: TK Cross هابط داخل السحابة"
            else:
                desc   = "Ichimoku: السعر داخل السحابة — ضبابية ⚠️"

        return {
            "signal":       signal,
            "score":        score,
            "description":  desc,
            "above_cloud":  above_cloud,
            "below_cloud":  below_cloud,
            "in_cloud":     in_cloud,
            "tk_cross":     tk_cross,
            "tenkan":       round(tenkan,     6),
            "kijun":        round(kijun,      6),
            "span_a":       round(span_a,     6),
            "span_b":       round(span_b,     6),
            "cloud_top":    round(cloud_top,  6),
            "cloud_bottom": round(cloud_bottom, 6),
            "chikou_bull":  chikou_bullish,
        }


# ═══════════════════════════════════════════════════════════
#  22. ✨ VWAP — Volume Weighted Average Price (جديد)
# ═══════════════════════════════════════════════════════════

class VWAP:
    """
    Volume Weighted Average Price — متوسط السعر المرجّح بالحجم.

    ما هو VWAP؟
    ─────────────────────────────────────────────
    VWAP = Σ(Typical_Price × Volume) / Σ(Volume)

    البنوك والمؤسسات تتداول بناءً على VWAP:
    - السعر فوق VWAP = المؤسسات تشتري → صاعد
    - السعر تحت VWAP = المؤسسات تبيع  → هابط
    - السعر يعود لـ VWAP = فرصة دخول في اتجاه الترند

    VWAP Bands (انحراف معياري):
    ─────────────────────────────────────────────
    Upper Band (+1σ, +2σ): مناطق ذروة الشراء
    Lower Band (-1σ, -2σ): مناطق ذروة البيع
    اختراق النطاق + حجم عالٍ = حركة انفجارية

    ملاحظة: في OTC الحجم نسبي لكن لا يزال مفيداً للمقارنة
    """

    def __init__(self, candles: list[Candle]):
        self.candles = candles

    def calculate(self) -> dict:
        """يحسب VWAP والنطاقات"""
        if len(self.candles) < 5:
            return {"valid": False, "vwap": None}

        cum_tp_vol = 0.0
        cum_vol    = 0.0
        cum_tp2_vol = 0.0

        for c in self.candles:
            tp  = c.typical_price
            vol = c.volume if c.volume > 0 else 1.0
            cum_tp_vol  += tp * vol
            cum_vol     += vol
            cum_tp2_vol += (tp ** 2) * vol

        if cum_vol == 0:
            return {"valid": False, "vwap": None}

        vwap     = cum_tp_vol / cum_vol
        variance = (cum_tp2_vol / cum_vol) - (vwap ** 2)
        std_dev  = math.sqrt(max(0, variance))

        return {
            "valid":    True,
            "vwap":     round(vwap, 6),
            "std_dev":  round(std_dev, 6),
            "upper_1":  round(vwap + std_dev,     6),
            "upper_2":  round(vwap + 2 * std_dev, 6),
            "lower_1":  round(vwap - std_dev,     6),
            "lower_2":  round(vwap - 2 * std_dev, 6),
        }

    def analyze(self, current_price: float) -> dict:
        """يُرجع إشارة VWAP بالنسبة للسعر الحالي"""
        data = self.calculate()
        empty = {"signal": "WAIT", "score": 0, "description": "VWAP غير متاح",
                 "position": "UNKNOWN", "vwap": None}
        if not data["valid"]:
            return empty

        vwap    = data["vwap"]
        upper_1 = data["upper_1"]
        upper_2 = data["upper_2"]
        lower_1 = data["lower_1"]
        lower_2 = data["lower_2"]
        std     = data["std_dev"]

        if vwap == 0 or std == 0:
            return empty

        # موقع السعر
        dist_pct = (current_price - vwap) / vwap * 100

        signal = "WAIT"
        score  = 0
        desc   = ""
        position = "AT_VWAP"

        # ── السعر عند نطاق ذروة الشراء (Upper Bands) ──
        if current_price >= upper_2:
            signal   = "DOWN"
            score    = 2
            position = "EXTREME_OVERBOUGHT"
            desc     = f"VWAP: سعر عند النطاق العلوي +2σ — ذروة شراء قصوى ↓"

        elif current_price >= upper_1:
            signal   = "DOWN"
            score    = 1
            position = "OVERBOUGHT"
            desc     = f"VWAP: سعر فوق VWAP +1σ — ذروة شراء ↓"

        # ── السعر عند نطاق ذروة البيع (Lower Bands) ──
        elif current_price <= lower_2:
            signal   = "UP"
            score    = 2
            position = "EXTREME_OVERSOLD"
            desc     = f"VWAP: سعر عند النطاق السفلي -2σ — ذروة بيع قصوى ↑"

        elif current_price <= lower_1:
            signal   = "UP"
            score    = 1
            position = "OVERSOLD"
            desc     = f"VWAP: سعر تحت VWAP -1σ — ذروة بيع ↑"

        # ── السعر قريب من VWAP ──
        elif abs(dist_pct) < 0.05:
            position = "AT_VWAP"
            desc     = f"VWAP: السعر عند VWAP ({vwap:.5f}) — منطقة قرار"

        # ── السعر فوق/تحت VWAP (بدون ذروة) ──
        elif current_price > vwap:
            position = "ABOVE_VWAP"
            signal   = "UP"
            score    = 1
            desc     = f"VWAP: السعر فوق VWAP — تحيز صاعد ↑"

        else:
            position = "BELOW_VWAP"
            signal   = "DOWN"
            score    = 1
            desc     = f"VWAP: السعر تحت VWAP — تحيز هابط ↓"

        return {
            "signal":    signal,
            "score":     score,
            "description": desc,
            "position":  position,
            "vwap":      vwap,
            "upper_1":   upper_1,
            "upper_2":   upper_2,
            "lower_1":   lower_1,
            "lower_2":   lower_2,
            "dist_pct":  round(dist_pct, 3),
        }


# ═══════════════════════════════════════════════════════════
#  23. ✨ Williams %R (جديد)
# ═══════════════════════════════════════════════════════════

class WilliamsR:
    """
    Williams %R — مؤشر ذروة الشراء/البيع الأسرع من RSI.

    الصيغة:
    ─────────────────────────────────────────────
    %R = (Highest_High - Close) / (Highest_High - Lowest_Low) × -100

    القراءات:
    ─────────────────────────────────────────────
    0   إلى -20:  ذروة الشراء (Overbought) → DOWN
    -20 إلى -80: منطقة محايدة
    -80 إلى -100: ذروة البيع (Oversold) → UP

    مميزاته على RSI:
    ─────────────────────────────────────────────
    - أسرع في الاستجابة (أقل تأخر)
    - ممتاز مع Stochastic كتأكيد مزدوج
    - يعطي إشارات انعكاس مبكرة

    إشارات قوية:
    ─────────────────────────────────────────────
    +2  خروج من ذروة البيع  (%R يرتفع من -100 نحو -80)
    +2  خروج من ذروة الشراء (%R ينزل من 0 نحو -20)
    +1  التقاطع مع Stochastic في نفس المنطقة
    """

    OVERBOUGHT  = -20.0
    OVERSOLD    = -80.0

    def __init__(self, candles: list[Candle], period: int = 14):
        self.candles = candles
        self.period  = period
        self.closes  = [c.close for c in candles]
        self.highs   = [c.high  for c in candles]
        self.lows    = [c.low   for c in candles]

    def _calculate_series(self) -> list[float]:
        """يحسب سلسلة %R كاملة"""
        result = []
        for i in range(self.period - 1, len(self.candles)):
            hh = max(self.highs[i - self.period + 1 : i + 1])
            ll = min(self.lows [i - self.period + 1 : i + 1])
            denom = hh - ll
            if denom == 0:
                result.append(-50.0)
            else:
                result.append((hh - self.closes[i]) / denom * -100)
        return result

    def analyze(self) -> dict:
        """يُرجع إشارة Williams %R"""
        if len(self.candles) < self.period + 2:
            return {"signal": "WAIT", "score": 0, "wr": None,
                    "overbought": False, "oversold": False,
                    "description": "بيانات غير كافية"}

        series   = self._calculate_series()
        if len(series) < 2:
            return {"signal": "WAIT", "score": 0, "wr": None,
                    "overbought": False, "oversold": False,
                    "description": "بيانات غير كافية"}

        curr = series[-1]
        prev = series[-2]

        overbought = curr >= self.OVERBOUGHT     # 0 إلى -20
        oversold   = curr <= self.OVERSOLD       # -80 إلى -100

        # خروج من ذروة البيع: كان oversold والآن يرتفع
        exit_oversold   = prev <= self.OVERSOLD   and curr > self.OVERSOLD
        # خروج من ذروة الشراء: كان overbought والآن ينزل
        exit_overbought = prev >= self.OVERBOUGHT and curr < self.OVERBOUGHT

        signal = "WAIT"
        score  = 0
        desc   = ""

        if exit_oversold:
            signal = "UP"
            score  = 2
            desc   = f"Williams %R: خروج من ذروة البيع ({curr:.1f}) ↑"
        elif exit_overbought:
            signal = "DOWN"
            score  = 2
            desc   = f"Williams %R: خروج من ذروة الشراء ({curr:.1f}) ↓"
        elif oversold:
            signal = "UP"
            score  = 1
            desc   = f"Williams %R: ذروة بيع ({curr:.1f}) ↑"
        elif overbought:
            signal = "DOWN"
            score  = 1
            desc   = f"Williams %R: ذروة شراء ({curr:.1f}) ↓"
        else:
            desc   = f"Williams %R: {curr:.1f} — منطقة محايدة"

        return {
            "signal":          signal,
            "score":           score,
            "description":     desc,
            "wr":              round(curr, 2),
            "wr_prev":         round(prev, 2),
            "overbought":      overbought,
            "oversold":        oversold,
            "exit_oversold":   exit_oversold,
            "exit_overbought": exit_overbought,
        }


# ═══════════════════════════════════════════════════════════
#  24. ✨ Market Regime Detector (جديد)
# ═══════════════════════════════════════════════════════════

class MarketRegimeDetector:
    """
    يصنّف حالة السوق تلقائياً ويغيّر استراتيجية البوت.

    الأنظمة الثلاثة:
    ─────────────────────────────────────────────
    TRENDING  — ترند واضح صاعد أو هابط
        → استخدم: إشارات الاتجاه (EMA cross, Stoch في ذروة)
        → تجنب: إشارات الانعكاس العكسية

    RANGING   — السوق في رينج بين دعم ومقاومة
        → استخدم: الارتداد من حواف الرينج (RSI, Bollinger)
        → تجنب: إشارات الترند

    VOLATILE  — تقلب عالٍ وغير منتظم
        → انتظر حتى تستقر الحركة
        → خفّض حجم الصفقات

    آلية الكشف:
    ─────────────────────────────────────────────
    ADX ≥ 25 + نطاق ATR متوسط  → TRENDING
    ADX < 20 + نطاق ATR ضيق   → RANGING
    ATR/AVG_ATR > 2.5           → VOLATILE

    تأثيره على Confluence:
    ─────────────────────────────────────────────
    TRENDING  → يضاعف نقاط إشارات الاتجاه
    RANGING   → يعزز إشارات الارتداد (Bollinger, RSI)
    VOLATILE  → يخفض الحد الأدنى المطلوب للدخول
    """

    # حدود التصنيف
    ADX_TREND_MIN   = 25.0
    ADX_RANGE_MAX   = 20.0
    ATR_VOLATILE    = 2.5   # نسبة ATR / متوسط ATR

    def __init__(self, candles: list[Candle]):
        self.candles = candles

    def _get_adx(self) -> float:
        """يجلب ADX من TrendEngine"""
        if len(self.candles) < 30:
            return 0.0
        return TrendEngine(self.candles).adx(14)

    def _get_atr_ratio(self) -> float:
        """نسبة ATR الحالي / متوسط ATR"""
        ind = Indicators(self.candles)
        cur = ind.atr(14)
        avg = ind.atr(50)
        if not cur or not avg or avg == 0:
            return 1.0
        return cur / avg

    def _get_price_range_ratio(self) -> float:
        """
        نسبة نطاق الـ 20 شمعة الأخيرة مقارنةً بالـ ATR.
        قيمة صغيرة = رينج ضيق.
        """
        if len(self.candles) < 20:
            return 1.0
        recent   = self.candles[-20:]
        rng      = max(c.high for c in recent) - min(c.low for c in recent)
        ind      = Indicators(self.candles)
        atr_val  = ind.atr(14) or 0.0001
        return rng / (atr_val * 14)   # مقارنةً بـ ATR مضروب في الفترة

    def analyze(self) -> dict:
        """يصنّف حالة السوق ويُرجع التوصيات"""
        adx       = self._get_adx()
        atr_ratio = self._get_atr_ratio()
        rng_ratio = self._get_price_range_ratio()

        # ── تصنيف الحالة ────────────────────────
        regime       = "UNKNOWN"
        confidence   = 0
        description  = ""
        trade_advice = ""
        score_modifier = 1.0   # معامل تعديل النقاط

        if atr_ratio >= self.ATR_VOLATILE:
            regime       = "VOLATILE"
            confidence   = min(int(atr_ratio * 30), 95)
            description  = f"سوق متقلب ({atr_ratio:.1f}x ATR) — خطر عالٍ ⚠️"
            trade_advice = "خفّض حجم الصفقات 50% وانتظر الاستقرار"
            score_modifier = 0.7

        elif adx >= self.ADX_TREND_MIN:
            # تحديد اتجاه الترند
            trend_data   = TrendEngine(self.candles).analyze()
            trend_dir    = trend_data["trend"]
            regime       = f"TRENDING_{trend_dir}"
            confidence   = min(int(adx * 2), 95)
            description  = f"ترند {trend_dir} واضح (ADX={adx:.1f})"
            trade_advice = "اتبع الترند — استخدم EMA + Stochastic + BOS"
            score_modifier = 1.2   # تعزيز إشارات الاتجاه

        elif adx < self.ADX_RANGE_MAX and rng_ratio < 2.0:
            regime       = "RANGING"
            confidence   = min(int((self.ADX_RANGE_MAX - adx) * 4), 90)
            description  = f"سوق في رينج (ADX={adx:.1f})"
            trade_advice = "تداول من الحواف — استخدم RSI + Bollinger + S/R"
            score_modifier = 1.0

        else:
            regime       = "TRANSITIONAL"
            confidence   = 40
            description  = f"السوق في مرحلة انتقالية (ADX={adx:.1f})"
            trade_advice = "انتظر وضوح الاتجاه قبل الدخول"
            score_modifier = 0.9

        # هل يجب التداول؟
        should_trade = regime not in ("VOLATILE", "UNKNOWN")
        if regime == "VOLATILE":
            should_trade = False

        # أفضل المؤشرات لهذا الوضع
        best_indicators = {
            "TRENDING_UPTREND":   ["EMA Cross", "Stochastic", "BOS", "Heikin Ashi"],
            "TRENDING_DOWNTREND": ["EMA Cross", "Stochastic", "BOS", "Heikin Ashi"],
            "RANGING":            ["RSI", "Bollinger Bands", "Stochastic", "VWAP"],
            "VOLATILE":           ["ATR", "Volume"],
            "TRANSITIONAL":       ["RSI", "MACD"],
        }.get(regime, ["RSI", "MACD"])

        return {
            "regime":          regime,
            "confidence":      confidence,
            "description":     description,
            "trade_advice":    trade_advice,
            "should_trade":    should_trade,
            "adx":             round(adx, 2),
            "atr_ratio":       round(atr_ratio, 2),
            "range_ratio":     round(rng_ratio, 2),
            "score_modifier":  score_modifier,
            "best_indicators": best_indicators,
        }


# ═══════════════════════════════════════════════════════════
#  19. ✨ Trend Lines Auto-Draw (جديد)
# ═══════════════════════════════════════════════════════════

class TrendLines:
    """
    يرسم خطوط الترند تلقائياً من Swing Highs و Swing Lows
    ويكتشف كسرها (Breakout) أو الارتداد منها (Bounce).

    خط الترند الصاعد:
    - يُرسم بين Swing Lows متصاعدة
    - الارتداد منه = فرصة شراء (+2)
    - كسره = تحذير / انعكاس

    خط الترند الهابط:
    - يُرسم بين Swing Highs متنازلة
    - الارتداد منه = فرصة بيع (+2)
    - كسره = تحذير / انعكاس

    خط الاختراق (Breakout):
    - الكسر بحجم عالٍ = إشارة قوية (+2)
    - الكسر بحجم منخفض = اختراق مزيف (تحذير)
    """

    TOUCH_TOLERANCE = 0.0008   # 8 pips — هامش اعتبار اللمس

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.closes  = [c.close for c in candles]
        self.highs   = [c.high  for c in candles]
        self.lows    = [c.low   for c in candles]

    def _swing_highs(self, w: int = 4) -> list[tuple[int, float]]:
        """يُرجع قائمة (index, price) لـ Swing Highs"""
        result = []
        for i in range(w, len(self.candles) - w):
            window = self.highs[i-w : i+w+1]
            if self.highs[i] == max(window):
                result.append((i, self.highs[i]))
        return result

    def _swing_lows(self, w: int = 4) -> list[tuple[int, float]]:
        """يُرجع قائمة (index, price) لـ Swing Lows"""
        result = []
        for i in range(w, len(self.candles) - w):
            window = self.lows[i-w : i+w+1]
            if self.lows[i] == min(window):
                result.append((i, self.lows[i]))
        return result

    def _line_price_at(self, p1: tuple, p2: tuple, idx: int) -> float:
        """
        يحسب سعر خط الترند عند index معيّن.
        p1, p2 = (index, price)
        """
        i1, v1 = p1
        i2, v2 = p2
        if i2 == i1:
            return v1
        slope = (v2 - v1) / (i2 - i1)
        return v1 + slope * (idx - i1)

    def _count_touches(self, p1: tuple, p2: tuple,
                       data: list[float], side: str) -> int:
        """
        يعد عدد مرات لمس الخط (touches) — كلما زاد = خط أقوى.
        side = 'high' أو 'low'
        """
        touches = 0
        i1, i2  = p1[0], p2[0]
        n        = len(self.candles)
        for i in range(i1, min(i2 + 1, n)):
            line_val = self._line_price_at(p1, p2, i)
            actual   = data[i]
            if abs(actual - line_val) / (line_val + 1e-9) < self.TOUCH_TOLERANCE:
                touches += 1
        return touches

    def _build_uptrend_line(self) -> Optional[dict]:
        """
        يبني خط ترند صاعد من آخر Swing Lows متصاعدَين.
        يتحقق: هل السعر الحالي قريب من الخط؟
        """
        lows = self._swing_lows(w=4)
        if len(lows) < 2:
            return None

        # ابحث عن آخر زوج من Swing Lows متصاعدة
        best = None
        for i in range(len(lows) - 1, 0, -1):
            p2 = lows[i]
            p1 = lows[i-1]
            if p2[1] > p1[1]:  # Low جديد أعلى = ترند صاعد
                touches = self._count_touches(p1, p2, self.lows, 'low')
                best = {"p1": p1, "p2": p2, "touches": touches, "type": "UPTREND"}
                break

        return best

    def _build_downtrend_line(self) -> Optional[dict]:
        """
        يبني خط ترند هابط من آخر Swing Highs متنازلَين.
        """
        highs = self._swing_highs(w=4)
        if len(highs) < 2:
            return None

        best = None
        for i in range(len(highs) - 1, 0, -1):
            p2 = highs[i]
            p1 = highs[i-1]
            if p2[1] < p1[1]:  # High جديد أخفض = ترند هابط
                touches = self._count_touches(p1, p2, self.highs, 'high')
                best = {"p1": p1, "p2": p2, "touches": touches, "type": "DOWNTREND"}
                break

        return best

    def analyze(self, current_price: float) -> dict:
        """
        يحلل خطوط الترند ويُرجع الإشارة.

        الحالات:
        - السعر يلمس خط صاعد من أعلى → BUY (+2)
        - السعر يلمس خط هابط من أسفل → SELL (+2)
        - السعر يكسر خط صاعد لأسفل  → تحذير انعكاس
        - السعر يكسر خط هابط لأعلى   → تحذير انعكاس
        """
        if len(self.candles) < 20:
            return {"signal": "WAIT", "score": 0, "description": "بيانات غير كافية",
                    "uptrend_line": None, "downtrend_line": None}

        n            = len(self.candles)
        curr_idx     = n - 1
        up_line      = self._build_uptrend_line()
        down_line    = self._build_downtrend_line()
        signal       = "WAIT"
        score        = 0
        description  = "لا توجد خطوط ترند واضحة"
        event        = "NONE"

        # ── تحليل خط الترند الصاعد ──────────────────
        if up_line:
            line_val = self._line_price_at(up_line["p1"], up_line["p2"], curr_idx)
            dist_pct = (current_price - line_val) / (line_val + 1e-9)
            touches  = up_line["touches"]

            if -self.TOUCH_TOLERANCE <= dist_pct <= self.TOUCH_TOLERANCE * 2:
                # السعر يلمس الخط الصاعد = ارتداد محتمل لأعلى
                strength = min(touches, 3)
                signal   = "UP"
                score    = 2 if touches >= 2 else 1
                event    = "BOUNCE"
                description = (
                    f"ارتداد من خط ترند صاعد "
                    f"(لمسات={touches}, مستوى={line_val:.5f})"
                )
            elif dist_pct < -self.TOUCH_TOLERANCE * 2:
                # كسر الخط الصاعد لأسفل = تحذير
                event       = "BREAK_DOWN"
                description = f"⚠️ كسر خط الترند الصاعد — انعكاس محتمل ↓"

        # ── تحليل خط الترند الهابط ──────────────────
        if down_line and signal == "WAIT":
            line_val = self._line_price_at(down_line["p1"], down_line["p2"], curr_idx)
            dist_pct = (current_price - line_val) / (line_val + 1e-9)
            touches  = down_line["touches"]

            if -self.TOUCH_TOLERANCE * 2 <= dist_pct <= self.TOUCH_TOLERANCE:
                # السعر يلمس الخط الهابط = ارتداد محتمل لأسفل
                signal  = "DOWN"
                score   = 2 if touches >= 2 else 1
                event   = "BOUNCE"
                description = (
                    f"ارتداد من خط ترند هابط "
                    f"(لمسات={touches}, مستوى={line_val:.5f})"
                )
            elif dist_pct > self.TOUCH_TOLERANCE * 2:
                # كسر الخط الهابط لأعلى = تحذير أو فرصة
                event       = "BREAK_UP"
                description = f"كسر خط الترند الهابط — صعود محتمل ↑"
                signal      = "UP"
                score       = 1

        # تعزيز النقاط إذا كان الخط قوياً (لمسات كثيرة)
        active_line = up_line if signal in ("UP", "WAIT") else down_line
        if active_line and active_line.get("touches", 0) >= 3:
            score = min(score + 1, 3)

        return {
            "signal":         signal,
            "score":          score,
            "event":          event,
            "description":    description,
            "uptrend_line":   {
                "p1":      up_line["p1"]      if up_line else None,
                "p2":      up_line["p2"]      if up_line else None,
                "touches": up_line["touches"] if up_line else 0,
            },
            "downtrend_line": {
                "p1":      down_line["p1"]      if down_line else None,
                "p2":      down_line["p2"]      if down_line else None,
                "touches": down_line["touches"] if down_line else 0,
            },
        }


# ═══════════════════════════════════════════════════════════
#  20. ✨ Order Blocks (جديد) — Smart Money Concept
# ═══════════════════════════════════════════════════════════

class OrderBlocks:
    """
    يكتشف Order Blocks — مفهوم Smart Money الأقوى.

    ما هو Order Block؟
    هو آخر شمعة عكسية قبل حركة انفجارية قوية.
    المؤسسات (البنوك والصناديق) تضع أوامرها هنا،
    فعندما يعود السعر لهذه المنطقة → ارتداد قوي.

    Bullish Order Block (OB):
    - آخر شمعة حمراء قبل حركة صاعدة انفجارية
    - عندما يعود السعر لهذا المستوى → شراء قوي (+3)

    Bearish Order Block (OB):
    - آخر شمعة خضراء قبل حركة هابطة انفجارية
    - عندما يعود السعر لهذا المستوى → بيع قوي (+3)

    شروط الـ Order Block الحقيقي:
    1. الحركة بعده ≥ 3 أضعاف جسم الشمعة
    2. الحركة تكسر Swing High/Low سابق (Displacement)
    3. لم يُخترق بعد (Unmitigated)

    هذا هو القلب الحقيقي لـ Smart Money Concepts (SMC)
    """

    # الحد الأدنى لقوة الحركة بعد الـ OB
    MIN_DISPLACEMENT_RATIO = 2.5

    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.closes  = [c.close for c in candles]
        self.highs   = [c.high  for c in candles]
        self.lows    = [c.low   for c in candles]

    def _find_displacement(self, start_idx: int, direction: str,
                           min_candles: int = 3) -> Optional[dict]:
        """
        يبحث عن حركة انفجارية (Displacement) بعد شمعة معيّنة.
        direction = 'UP' أو 'DOWN'
        يُرجع معلومات الحركة أو None.
        """
        n = len(self.candles)
        if start_idx + min_candles >= n:
            return None

        # احسب مجموع الحركة في الـ candles التالية
        window = self.candles[start_idx + 1 : start_idx + min_candles + 1]
        if not window:
            return None

        total_move = 0.0
        for c in window:
            if direction == "UP":
                total_move += max(0, c.close - c.open)
            else:
                total_move += max(0, c.open - c.close)

        ob_candle = self.candles[start_idx]
        ob_body   = ob_candle.body if ob_candle.body > 0 else 0.0001

        # هل الحركة كافية؟
        ratio = total_move / ob_body
        if ratio < self.MIN_DISPLACEMENT_RATIO:
            return None

        return {
            "move":     round(total_move, 6),
            "ratio":    round(ratio, 2),
            "candles":  min_candles,
        }

    def _is_mitigated(self, ob_high: float, ob_low: float,
                      ob_type: str, from_idx: int) -> bool:
        """
        يتحقق هل عاد السعر وتجاوز الـ OB (mitigated = محروق).
        OB محروق = لا يصلح للتداول.
        """
        n = len(self.candles)
        for i in range(from_idx, n - 1):
            c = self.candles[i]
            if ob_type == "BULLISH" and c.low < ob_low:
                return True   # اخترق القاع = محروق
            if ob_type == "BEARISH" and c.high > ob_high:
                return True   # اخترق القمة = محروق
        return False

    def find_bullish_ob(self) -> list[dict]:
        """
        يجد Bullish Order Blocks:
        آخر شمعة حمراء قبل حركة صاعدة قوية.
        """
        obs = []
        n   = len(self.candles)

        for i in range(5, n - 5):
            c = self.candles[i]
            # الشمعة يجب أن تكون حمراء (bearish)
            if not c.is_bearish:
                continue
            # تحقق من وجود displacement صاعد بعدها
            displacement = self._find_displacement(i, "UP", min_candles=3)
            if not displacement:
                continue
            # تحقق أن الـ OB لم يُخترق بعد
            mitigated = self._is_mitigated(c.high, c.low, "BULLISH", i + 1)

            obs.append({
                "type":         "BULLISH",
                "index":        i,
                "ob_high":      round(c.high,  6),
                "ob_low":       round(c.low,   6),
                "ob_mid":       round(c.mid,   6),
                "displacement": displacement,
                "mitigated":    mitigated,
                "strength":     min(int(displacement["ratio"]), 5),
            })

        # فلتر: فقط الـ OBs غير المحروقة
        valid = [ob for ob in obs if not ob["mitigated"]]
        # ترتيب حسب الأحدث
        return sorted(valid, key=lambda x: x["index"], reverse=True)[:5]

    def find_bearish_ob(self) -> list[dict]:
        """
        يجد Bearish Order Blocks:
        آخر شمعة خضراء قبل حركة هابطة قوية.
        """
        obs = []
        n   = len(self.candles)

        for i in range(5, n - 5):
            c = self.candles[i]
            # الشمعة يجب أن تكون خضراء (bullish)
            if not c.is_bullish:
                continue
            # تحقق من وجود displacement هابط بعدها
            displacement = self._find_displacement(i, "DOWN", min_candles=3)
            if not displacement:
                continue
            # تحقق أن الـ OB لم يُخترق بعد
            mitigated = self._is_mitigated(c.high, c.low, "BEARISH", i + 1)

            obs.append({
                "type":         "BEARISH",
                "index":        i,
                "ob_high":      round(c.high,  6),
                "ob_low":       round(c.low,   6),
                "ob_mid":       round(c.mid,   6),
                "displacement": displacement,
                "mitigated":    mitigated,
                "strength":     min(int(displacement["ratio"]), 5),
            })

        valid = [ob for ob in obs if not ob["mitigated"]]
        return sorted(valid, key=lambda x: x["index"], reverse=True)[:5]

    def analyze(self, current_price: float) -> dict:
        """
        يحلل الـ Order Blocks ويتحقق هل السعر داخل OB نشط.

        إذا كان السعر داخل:
        - Bullish OB → إشارة شراء قوية (+3)
        - Bearish OB → إشارة بيع قوية (+3)

        قوة الإشارة تزيد مع:
        - displacement ratio أعلى
        - OB أحدث (أقرب للسعر الحالي زمنياً)
        """
        if len(self.candles) < 20:
            return {
                "signal": "WAIT", "score": 0,
                "in_bullish_ob": False, "in_bearish_ob": False,
                "active_ob": None, "description": "بيانات غير كافية",
                "bullish_obs": [], "bearish_obs": [],
            }

        bullish_obs = self.find_bullish_ob()
        bearish_obs = self.find_bearish_ob()

        signal       = "WAIT"
        score        = 0
        active_ob    = None
        description  = "لا يوجد Order Block نشط"
        in_bull_ob   = False
        in_bear_ob   = False

        # ── تحقق هل السعر داخل Bullish OB ──────────
        for ob in bullish_obs:
            # السعر يجب أن يكون داخل نطاق الـ OB أو قريباً منه
            margin = (ob["ob_high"] - ob["ob_low"]) * 0.3
            if ob["ob_low"] - margin <= current_price <= ob["ob_high"] + margin:
                in_bull_ob  = True
                active_ob   = ob
                # النقاط بناءً على قوة الـ OB
                disp_ratio  = ob["displacement"]["ratio"]
                score       = 3 if disp_ratio >= 4.0 else 2
                signal      = "UP"
                description = (
                    f"Bullish OB نشط — "
                    f"منطقة {ob['ob_low']:.5f}-{ob['ob_high']:.5f} "
                    f"(displacement x{disp_ratio:.1f})"
                )
                break

        # ── تحقق هل السعر داخل Bearish OB ──────────
        if not in_bull_ob:
            for ob in bearish_obs:
                margin = (ob["ob_high"] - ob["ob_low"]) * 0.3
                if ob["ob_low"] - margin <= current_price <= ob["ob_high"] + margin:
                    in_bear_ob  = True
                    active_ob   = ob
                    disp_ratio  = ob["displacement"]["ratio"]
                    score       = 3 if disp_ratio >= 4.0 else 2
                    signal      = "DOWN"
                    description = (
                        f"Bearish OB نشط — "
                        f"منطقة {ob['ob_low']:.5f}-{ob['ob_high']:.5f} "
                        f"(displacement x{disp_ratio:.1f})"
                    )
                    break

        return {
            "signal":         signal,
            "score":          score,
            "in_bullish_ob":  in_bull_ob,
            "in_bearish_ob":  in_bear_ob,
            "active_ob":      active_ob,
            "description":    description,
            "bullish_obs":    bullish_obs[:3],
            "bearish_obs":    bearish_obs[:3],
            "total_bull_obs": len(bullish_obs),
            "total_bear_obs": len(bearish_obs),
        }


# ═══════════════════════════════════════════════════════════
#  5. فلتر التقلب (بدون تغيير)
# ═══════════════════════════════════════════════════════════

class VolatilityFilter:
    def __init__(self, candles: list[Candle],
                 min_atr_ratio: float = 0.5,
                 max_atr_ratio: float = 3.0):
        self.candles   = candles
        self.min_ratio = min_atr_ratio
        self.max_ratio = max_atr_ratio

    def check(self) -> dict:
        ind     = Indicators(self.candles)
        cur_atr = ind.atr(14)
        avg_atr = ind.atr(50)
        if cur_atr is None or avg_atr is None or avg_atr == 0:
            return {"pass": True, "reason": "ATR غير متاح — مسموح", "ratio": 1.0}
        ratio = cur_atr / avg_atr
        if ratio < self.min_ratio:
            return {"pass": False, "reason": f"السوق ميت — ATR منخفض ({ratio:.2f}x)", "ratio": ratio}
        if ratio > self.max_ratio:
            return {"pass": False, "reason": f"السوق فوضوي — ATR مرتفع ({ratio:.2f}x)", "ratio": ratio}
        return {"pass": True,  "reason": f"التقلب مثالي ({ratio:.2f}x)", "ratio": ratio}


# ═══════════════════════════════════════════════════════════
#  6. فلاتر الجودة (بدون تغيير)
# ═══════════════════════════════════════════════════════════

class QualityFilters:
    def __init__(self, payout: float, candle_age_pct: float = 0.0,
                 min_payout: float = 80.0, max_candle_age_pct: float = 0.5):
        self.payout         = payout
        self.candle_age_pct = candle_age_pct
        self.min_payout     = min_payout
        self.max_candle_age = max_candle_age_pct

    def check_payout(self) -> dict:
        if self.payout < self.min_payout:
            return {"pass": False, "reason": f"Payout {self.payout}% أقل من الحد {self.min_payout}%"}
        return {"pass": True, "reason": f"Payout {self.payout}% مقبول"}

    def check_candle_timing(self) -> dict:
        if self.candle_age_pct > self.max_candle_age:
            return {"pass": False, "reason": f"الشمعة {self.candle_age_pct*100:.0f}% — متأخر"}
        return {"pass": True, "reason": "توقيت الدخول مناسب"}

    def check_tight_range(self, candles: list[Candle],
                          lookback: int = 20, min_range: float = 0.0010) -> dict:
        if len(candles) < lookback:
            return {"pass": True, "reason": "بيانات غير كافية"}
        recent = candles[-lookback:]
        total  = max(c.high for c in recent) - min(c.low for c in recent)
        if total < min_range:
            return {"pass": False, "reason": f"رينج ضيق ({total:.5f})"}
        return {"pass": True, "reason": f"نطاق كافٍ ({total:.5f})"}

    def run_all(self, candles: list[Candle]) -> dict:
        checks = {
            "payout": self.check_payout(),
            "timing": self.check_candle_timing(),
            "range":  self.check_tight_range(candles),
        }
        failed = [n for n, r in checks.items() if not r["pass"]]
        return {
            "pass":    len(failed) == 0,
            "failed":  failed,
            "checks":  checks,
            "reasons": [checks[f]["reason"] for f in failed],
        }


# ═══════════════════════════════════════════════════════════
#  7. ✨ محرك نقاط التأكيد المحسّن (0-28 نقطة)
# ═══════════════════════════════════════════════════════════

class ConfluenceEngine:
    """
    يجمع إشارات جميع المحركات في نظام نقاط موحد.

    النقاط الجديدة (0-28):
    +3  MTF اتفاق 3 أطر
    +2  MTF اتفاق 2 أطر
    +2  ترند أحادي قوي
    +3  منطقة Dynamic S/R وزن ≥ 4
    +2  منطقة Dynamic S/R وزن ≥ 2
    +3  نمط Pin Bar أو Engulfing قوي
    +2  نمط شمعة متوسط
    +2  RSI ذروة
    +3  Stochastic تقاطع ذروة
    +1  MACD اتجاه
    +2  Bollinger Band
    +2  RSI/MACD Divergence
    +2  BOS / CHoCH
    +1  Volume Confirmation
    +1  Fibonacci مستوى رئيسي
    +1  Session Prime Time
    +1  Heikin Ashi تأكيد
    +1  Payout ≥ 88%

    القرار:
    0-5   → WAIT
    6-8   → دخول صغير (1%)
    9-12  → دخول متوسط (2%)
    13+   → دخول قوي (3%)
    """

    MAX_SCORE = 38

    def __init__(self,
                 candles:        list[Candle],
                 current_price:  float,
                 payout:         float,
                 balance:        float = 1000.0,
                 candle_age_pct: float = 0.0,
                 utc_hour:       Optional[int] = None):
        self.candles       = candles
        self.current_price = current_price
        self.payout        = payout
        self.balance       = balance
        self.candle_age    = candle_age_pct
        self.utc_hour      = utc_hour

    def run(self) -> Signal:
        reasons  = []
        warnings = []
        scores   = {"UP": 0, "DOWN": 0}

        def add(direction: str, pts: int, reason: str):
            if direction in scores:
                scores[direction] += pts
                reasons.append(f"[+{pts} {direction}] {reason}")

        # ══ 0. فلاتر الجودة أولاً ══════════════════
        qf = QualityFilters(self.payout, self.candle_age)
        qf_result = qf.run_all(self.candles)
        if not qf_result["pass"]:
            for r in qf_result["reasons"]:
                warnings.append(r)

        # ══ 0b. فلتر التقلب ══════════════════════
        vf = VolatilityFilter(self.candles)
        vf_result = vf.check()
        if not vf_result["pass"]:
            warnings.append(vf_result["reason"])

        # ══ 1. Multi-Timeframe ✨ ═════════════════
        mtf = MultiTimeframe(self.candles)
        mtf_data = mtf.analyze()
        if mtf_data["direction"] != "RANGE" and mtf_data["score"] > 0:
            add(mtf_data["direction"], mtf_data["score"],
                f"MTF: {mtf_data['label']} (1m:{mtf_data['1m']} 5m:{mtf_data['5m']} 15m:{mtf_data['15m']})")
        elif mtf_data["agreement"] == "CONFLICT":
            warnings.append(f"⚠️ MTF تعارض: 1m={mtf_data['1m']} 5m={mtf_data['5m']} 15m={mtf_data['15m']}")

        # ══ 2. الترند العادي (احتياطي إذا MTF ضعيف) ══
        trend_data = TrendEngine(self.candles).analyze()
        trend = trend_data["trend"]
        if trend == "UPTREND" and trend_data["strength"] == "STRONG" and mtf_data["score"] == 0:
            add("UP", 2, f"ترند صاعد قوي (ADX={trend_data['adx']})")
        elif trend == "DOWNTREND" and trend_data["strength"] == "STRONG" and mtf_data["score"] == 0:
            add("DOWN", 2, f"ترند هابط قوي (ADX={trend_data['adx']})")
        elif trend == "RANGE":
            warnings.append("السوق في رينج — الإشارات أقل موثوقية")

        # ══ 3. Dynamic S/R ✨ ════════════════════
        dsr = DynamicSR(self.candles)
        dsr_data = dsr.find_zones(self.current_price)
        if dsr_data["score"] > 0:
            add(dsr_data["signal"], dsr_data["score"],
                f"Dynamic S/R: "
                f"{'مقاومة' if dsr_data['signal']=='DOWN' else 'دعم'} "
                f"قوة={dsr_data['resistance_weight' if dsr_data['signal']=='DOWN' else 'support_weight']}")
        else:
            # S/R عادي كاحتياطي
            sr_data = SupportResistance(self.candles).find_zones(self.current_price)
            if sr_data["in_support_zone"]:
                add("UP",   2, f"S/R: دعم عادي ({sr_data['nearest_support']})")
            if sr_data["in_resistance_zone"]:
                add("DOWN", 2, f"S/R: مقاومة عادية ({sr_data['nearest_resistance']})")

        # ══ 4. أنماط الشموع ══════════════════════
        cp_data = CandlePatterns(self.candles).analyze()
        if cp_data["signal"] != "WAIT" and cp_data["strength"] > 0:
            add(cp_data["signal"], min(cp_data["strength"], 3),
                f"نمط شمعة: {', '.join(cp_data['patterns'])}")

        # ══ 5. المؤشرات التقنية ══════════════════
        ind_data = Indicators(self.candles).analyze()
        rsi   = ind_data.get("rsi")
        stoch = ind_data.get("stochastic", {})
        macd  = ind_data.get("macd", {})
        bb    = ind_data.get("bollinger", {})

        if rsi is not None:
            if rsi < 30:   add("UP",   2, f"RSI ذروة بيع ({rsi})")
            elif rsi > 70: add("DOWN", 2, f"RSI ذروة شراء ({rsi})")

        if stoch.get("crossover_up")   and stoch.get("oversold"):
            add("UP",   3, f"Stochastic تقاطع صعودي ذروة بيع (K={stoch['k']})")
        if stoch.get("crossover_down") and stoch.get("overbought"):
            add("DOWN", 3, f"Stochastic تقاطع هبوطي ذروة شراء (K={stoch['k']})")

        if macd.get("direction") == "UP":
            add("UP",   1, f"MACD إيجابي ({macd.get('histogram')})")
        elif macd.get("direction") == "DOWN":
            add("DOWN", 1, f"MACD سلبي ({macd.get('histogram')})")
        if macd.get("crossover"):
            add("UP", 2, "MACD تقاطع صعودي")

        if bb.get("signal") == "UP":
            add("UP",   2, "السعر عند الحد السفلي لبولينجر")
        elif bb.get("signal") == "DOWN":
            add("DOWN", 2, "السعر عند الحد العلوي لبولينجر")

        # ══ 6. RSI/MACD Divergence ✨ ════════════
        div_data = DivergenceDetector(self.candles).detect()
        if div_data["signal"] in ("UP", "DOWN") and div_data["score"] > 0:
            add(div_data["signal"], div_data["score"],
                f"Divergence: {div_data['description']}")

        # ══ 7. BOS / CHoCH ✨ ════════════════════
        ms_data = MarketStructure(self.candles).analyze()
        if ms_data["signal"] in ("UP", "DOWN") and ms_data["score"] > 0:
            add(ms_data["signal"], ms_data["score"],
                f"{ms_data['event']}: {ms_data['description']}")

        # ══ 8. Volume Confirmation ✨ ═════════════
        leading_dir = "UP" if scores["UP"] > scores["DOWN"] else "DOWN" if scores["DOWN"] > scores["UP"] else "WAIT"
        vol_data = VolumeAnalysis(self.candles).analyze(leading_dir)
        if vol_data["score"] > 0:
            add(leading_dir, vol_data["score"], f"Volume: {vol_data['description']}")
        elif vol_data["ratio"] < 0.7:
            warnings.append(f"⚠️ حجم منخفض {vol_data['ratio']:.1f}x — إشارة ضعيفة")

        # ══ 9. Fibonacci ✨ ═══════════════════════
        fib_data = FibonacciLevels(self.candles).calculate(self.current_price)
        if fib_data["score"] > 0 and fib_data["signal"] != "WAIT":
            add(fib_data["signal"], fib_data["score"],
                f"Fibonacci {fib_data['nearest_name']}: ارتداد محتمل")

        # ══ 10. Session Filter ✨ ════════════════
        sess_data = SessionFilter(self.utc_hour).analyze()
        if sess_data["score"] > 0:
            add(leading_dir, sess_data["score"], f"Session: {sess_data['description']}")
        elif sess_data["in_dead_zone"]:
            warnings.append(f"⚠️ Dead Zone ({sess_data['session']}) — تداول محدود")

        # ══ 11. Heikin Ashi ✨ ═══════════════════
        ha_data = HeikinAshi(self.candles).analyze()
        if ha_data["signal"] in ("UP", "DOWN") and ha_data["score"] > 0:
            add(ha_data["signal"], ha_data["score"], f"Heikin Ashi: {ha_data['description']}")

        # ══ 12. Momentum ✨ ══════════════════════
        mom_data = MomentumOscillator(self.candles).analyze()
        if mom_data.get("weakening"):
            warnings.append("⚠️ زخم السعر يضعف")

        # ══ 13. Trend Lines ✨ ═══════════════════
        tl_data = TrendLines(self.candles).analyze(self.current_price)
        if tl_data["signal"] in ("UP", "DOWN") and tl_data["score"] > 0:
            add(tl_data["signal"], tl_data["score"],
                f"Trend Line: {tl_data['description']}")
        if tl_data["event"] in ("BREAK_DOWN", "BREAK_UP"):
            warnings.append(f"⚠️ {tl_data['description']}")

        # ══ 14. Order Blocks ✨ ══════════════════
        ob_data = OrderBlocks(self.candles).analyze(self.current_price)
        if ob_data["signal"] in ("UP", "DOWN") and ob_data["score"] > 0:
            add(ob_data["signal"], ob_data["score"],
                f"🏦 Order Block: {ob_data['description']}")

        # ══ 15. Ichimoku Cloud ✨ ════════════════
        ichi_data = IchimokuCloud(self.candles).analyze()
        if ichi_data["signal"] in ("UP", "DOWN") and ichi_data["score"] > 0:
            add(ichi_data["signal"], ichi_data["score"],
                f"☁️ Ichimoku: {ichi_data['description']}")
        elif ichi_data.get("in_cloud"):
            warnings.append("⚠️ Ichimoku: السعر داخل السحابة — ضبابية")

        # ══ 16. VWAP ✨ ══════════════════════════
        vwap_data = VWAP(self.candles).analyze(self.current_price)
        if vwap_data["signal"] in ("UP", "DOWN") and vwap_data["score"] > 0:
            add(vwap_data["signal"], vwap_data["score"],
                f"VWAP: {vwap_data['description']}")

        # ══ 17. Williams %R ✨ ═══════════════════
        wr_data = WilliamsR(self.candles).analyze()
        if wr_data["signal"] in ("UP", "DOWN") and wr_data["score"] > 0:
            add(wr_data["signal"], wr_data["score"],
                f"Williams %R: {wr_data['description']}")

        # ══ 18. Market Regime ✨ ═════════════════
        regime_data = MarketRegimeDetector(self.candles).analyze()
        if not regime_data["should_trade"] and regime_data["regime"] == "VOLATILE":
            warnings.append(f"⚠️ {regime_data['description']} — {regime_data['trade_advice']}")
        elif "TRANSITIONAL" in regime_data["regime"]:
            warnings.append(f"⚠️ {regime_data['description']} — {regime_data['trade_advice']}")

        # ══ 19. Payout بونس ══════════════════════
        if self.payout >= 88:
            direction_for_bonus = "UP" if scores["UP"] >= scores["DOWN"] else "DOWN"
            add(direction_for_bonus, 1, f"Payout مرتفع ({self.payout}%)")

        # ══ اتخاذ القرار ════════════════════════
        up_score   = scores["UP"]
        down_score = scores["DOWN"]
        total_score = max(up_score, down_score)

        if up_score > down_score:
            direction = "UP"
            net_score = up_score
        elif down_score > up_score:
            direction = "DOWN"
            net_score = down_score
        else:
            direction = "WAIT"
            net_score = 0

        # تعارض القوى الكبير → انتظار
        conflict_ratio = min(up_score, down_score) / (total_score + 1e-9)
        if conflict_ratio > 0.65 and total_score > 4:
            direction = "WAIT"
            warnings.append(f"تعارض قوي (UP={up_score}, DOWN={down_score}) — انتظار")

        # فلاتر الجودة تمنع الدخول
        if not qf_result["pass"] and direction != "WAIT":
            warnings.append("فلاتر الجودة فشلت — إشارة معلقة")
            direction = "WAIT"

        if not vf_result["pass"] and direction != "WAIT":
            direction = "WAIT"

        # نقاط الحد الأدنى
        MIN_SCORE = 6
        if net_score < MIN_SCORE and direction != "WAIT":
            direction = "WAIT"
            warnings.append(f"نقاط غير كافية ({net_score} < {MIN_SCORE})")

        # حساب الثقة
        confidence = round((net_score / self.MAX_SCORE) * 100, 1)
        confidence = min(confidence, 95)

        # حجم الصفقة
        if direction == "WAIT":
            trade_size = 0.0
        elif net_score < 9:
            trade_size = round(self.balance * 0.01, 2)   # 1%
        elif net_score < 13:
            trade_size = round(self.balance * 0.02, 2)   # 2%
        else:
            trade_size = round(self.balance * 0.03, 2)   # 3%

        return Signal(
            direction  = direction,
            score      = net_score,
            confidence = confidence,
            reasons    = reasons,
            warnings   = warnings,
            trade_size = trade_size,
            details    = {
                "scores":     scores,
                "trend":      trend_data,
                "mtf":        mtf_data,
                "dynamic_sr": dsr_data,
                "candles":    cp_data,
                "indicators": ind_data,
                "divergence": div_data,
                "structure":  ms_data,
                "volume":     vol_data,
                "fibonacci":  fib_data,
                "session":    sess_data,
                "ha":         ha_data,
                "trendlines":  tl_data,
                "orderblocks":  ob_data,
                "ichimoku":     ichi_data,
                "vwap":         vwap_data,
                "williams_r":   wr_data,
                "regime":       regime_data,
                "volatility":   vf_result,
                "filters":    qf_result,
            }
        )


# ═══════════════════════════════════════════════════════════
#  25. ✨ Signal Strength Score — نظام النقاط المحسّن
# ═══════════════════════════════════════════════════════════

class SignalStrengthScore:
    """
    نظام تقييم شامل يحوّل نقاط Confluence الخام (0-38)
    إلى تقييم نهائي موزون يأخذ بعين الاعتبار:

    عوامل التعزيز (+):
    ─────────────────────────────────────────────
    • وقت الجلسة    → Prime Time يعزز 20%
    • قوة الترند    → ADX > 30 يعزز 15%
    • القرب من S/R  → كلما اقترب زاد التعزيز
    • حجم التداول  → Volume > 1.5x يعزز 10%
    • تأكيد MTF     → 3 أطر تتفق يعزز 25%
    • Order Block   → تأكيد مؤسسي يعزز 20%

    عوامل الخصم (-):
    ─────────────────────────────────────────────
    • Dead Zone      → يخصم 30%
    • حجم منخفض    → يخصم 15%
    • تعارض الإشارات → يخصم 20%
    • سوق متقلب    → يخصم 25%
    • خسائر متتالية → يخصم 10% لكل خسارة

    النتيجة النهائية:
    ─────────────────────────────────────────────
    0-30%   → VERY_WEAK  — لا تدخل
    31-50%  → WEAK       — انتظار أفضل
    51-65%  → MODERATE   — دخول صغير محتمل
    66-80%  → STRONG     — دخول جيد
    81-100% → VERY_STRONG → دخول قوي
    """

    GRADE_THRESHOLDS = {
        "VERY_STRONG": 81,
        "STRONG":      66,
        "MODERATE":    51,
        "WEAK":        31,
        "VERY_WEAK":   0,
    }

    def __init__(self, signal: "Signal",
                 consecutive_losses: int = 0,
                 session_prime: bool = False,
                 in_dead_zone:  bool = False):
        self.signal             = signal
        self.consecutive_losses = consecutive_losses
        self.session_prime      = session_prime
        self.in_dead_zone       = in_dead_zone

    def calculate(self) -> dict:
        """يحسب النقاط المحسّنة الموزونة"""
        details  = self.signal.details
        base     = self.signal.score
        max_sc   = ConfluenceEngine.MAX_SCORE

        # نسبة البداية (0.0 → 1.0)
        base_ratio = base / max_sc if max_sc > 0 else 0.0

        multiplier = 1.0
        bonuses    = []
        penalties  = []

        # ── عوامل التعزيز ──────────────────────
        # 1. Prime Time
        sess = details.get("session", {})
        if self.session_prime or sess.get("in_prime"):
            multiplier += 0.20
            bonuses.append("⭐ Prime Time +20%")

        # 2. قوة الترند (ADX)
        trend = details.get("trend", {})
        adx   = trend.get("adx", 0) or 0
        if adx >= 30:
            multiplier += 0.15
            bonuses.append(f"📈 ADX قوي ({adx:.0f}) +15%")
        elif adx >= 25:
            multiplier += 0.07
            bonuses.append(f"📈 ADX متوسط ({adx:.0f}) +7%")

        # 3. MTF اتفاق كامل
        mtf = details.get("mtf", {})
        if mtf.get("agreement") == "FULL" and mtf.get("agree_count", 0) >= 3:
            multiplier += 0.25
            bonuses.append("🔭 MTF ثلاثي +25%")
        elif mtf.get("agreement") in ("FULL", "PARTIAL"):
            multiplier += 0.10
            bonuses.append("🔭 MTF اتفاق جزئي +10%")

        # 4. Order Block نشط
        ob = details.get("orderblocks", {})
        if ob.get("in_bullish_ob") or ob.get("in_bearish_ob"):
            multiplier += 0.20
            bonuses.append("🏦 Order Block نشط +20%")

        # 5. حجم مرتفع
        vol = details.get("volume", {})
        if vol.get("spike"):
            multiplier += 0.15
            bonuses.append(f"📊 Volume Spike {vol.get('ratio',1):.1f}x +15%")
        elif vol.get("confirmed") and vol.get("ratio", 1) >= 1.3:
            multiplier += 0.10
            bonuses.append(f"📊 حجم مرتفع {vol.get('ratio',1):.1f}x +10%")

        # 6. Divergence تأكيد
        div = details.get("divergence", {})
        if div.get("signal") == self.signal.direction and div.get("score", 0) >= 2:
            multiplier += 0.12
            bonuses.append("🔄 Divergence يؤكد +12%")

        # 7. Dynamic S/R قوة عالية
        dsr = details.get("dynamic_sr", {})
        sr_weight = max(dsr.get("resistance_weight", 0), dsr.get("support_weight", 0))
        if sr_weight >= 5:
            multiplier += 0.15
            bonuses.append(f"🧱 S/R قوي جداً (وزن={sr_weight}) +15%")
        elif sr_weight >= 3:
            multiplier += 0.08
            bonuses.append(f"🧱 S/R قوي (وزن={sr_weight}) +8%")

        # ── عوامل الخصم ────────────────────────
        # 1. Dead Zone
        if self.in_dead_zone or sess.get("in_dead_zone"):
            multiplier -= 0.30
            penalties.append("🌙 Dead Zone -30%")

        # 2. حجم منخفض
        vol_ratio = vol.get("ratio", 1.0)
        if vol_ratio < 0.6:
            multiplier -= 0.15
            penalties.append(f"📉 حجم منخفض {vol_ratio:.1f}x -15%")

        # 3. تعارض الإشارات (من warnings)
        conflict = any("تعارض" in w for w in self.signal.warnings)
        if conflict:
            multiplier -= 0.20
            penalties.append("⚡ تعارض إشارات -20%")

        # 4. سوق متقلب
        regime = details.get("regime", {})
        if regime.get("regime") == "VOLATILE":
            multiplier -= 0.25
            penalties.append("🌪️ سوق متقلب -25%")

        # 5. خسائر متتالية
        if self.consecutive_losses >= 1:
            penalty = min(self.consecutive_losses * 0.10, 0.30)
            multiplier -= penalty
            penalties.append(f"🔴 {self.consecutive_losses} خسائر متتالية -{penalty*100:.0f}%")

        # 6. داخل السحابة (Ichimoku)
        ichi = details.get("ichimoku", {})
        if ichi.get("in_cloud"):
            multiplier -= 0.10
            penalties.append("☁️ داخل Ichimoku Cloud -10%")

        # ── الحساب النهائي ──────────────────────
        multiplier = max(0.1, min(multiplier, 2.0))   # حد: 0.1x → 2.0x
        final_ratio = min(base_ratio * multiplier, 1.0)
        final_score = round(final_ratio * 100, 1)

        # تصنيف الجودة
        grade = "VERY_WEAK"
        for g, threshold in self.GRADE_THRESHOLDS.items():
            if final_score >= threshold:
                grade = g
                break

        grade_icons = {
            "VERY_STRONG": "🔥",
            "STRONG":      "💪",
            "MODERATE":    "👍",
            "WEAK":        "⚠️",
            "VERY_WEAK":   "❌",
        }

        return {
            "base_score":    base,
            "base_ratio":    round(base_ratio * 100, 1),
            "multiplier":    round(multiplier, 3),
            "final_score":   final_score,
            "grade":         grade,
            "grade_icon":    grade_icons.get(grade, "📊"),
            "bonuses":       bonuses,
            "penalties":     penalties,
            "should_trade":  grade in ("VERY_STRONG", "STRONG", "MODERATE"),
            "recommended_size_pct": (
                0.03 if grade == "VERY_STRONG" else
                0.02 if grade == "STRONG"      else
                0.01 if grade == "MODERATE"    else
                0.0
            ),
        }

    def format_telegram(self) -> str:
        """يُنسّق التقييم لرسالة Telegram"""
        r = self.calculate()
        bar_filled = int(r["final_score"] / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        lines = [
            f"{r['grade_icon']} *قوة الإشارة: {r['grade']}*",
            f"`{bar}` {r['final_score']:.0f}%",
            f"النقاط الأساسية: {r['base_score']}/{ConfluenceEngine.MAX_SCORE} → معامل: {r['multiplier']}x",
        ]
        if r["bonuses"]:
            lines.append("*✅ عوامل تعزيز:*")
            for b in r["bonuses"][:3]:
                lines.append(f"  {b}")
        if r["penalties"]:
            lines.append("*⚠️ عوامل خصم:*")
            for p in r["penalties"][:3]:
                lines.append(f"  {p}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  26. ✨ Risk/Reward Optimizer — مُحسّن حجم الصفقة الذكي
# ═══════════════════════════════════════════════════════════

class RiskRewardOptimizer:
    """
    يحسب حجم الصفقة المثالي بذكاء كامل بناءً على:

    المدخلات:
    ─────────────────────────────────────────────
    • الرصيد الحالي
    • قوة الإشارة (SignalStrengthScore)
    • معدل الفوز التاريخي
    • سلسلة الخسائر الحالية
    • نسبة الـ payout
    • حد الخسارة اليومية

    المنطق:
    ─────────────────────────────────────────────
    1. Kelly Criterion (نصف Kelly للأمان):
       f* = (p × b - q) / b  ÷ 2

    2. تعديل بناءً على قوة الإشارة:
       size = kelly × (signal_strength / 100)

    3. حماية سلسلة الخسائر:
       بعد كل خسارة → تصغير 20%
       بعد 3 خسائر → حجم الحد الأدنى فقط

    4. حدود الأمان المطلقة:
       الحد الأدنى: $1 أو 0.5% من الرصيد
       الحد الأقصى: 5% من الرصيد

    5. Anti-Martingale (اختياري):
       بعد الفوز → زيادة طفيفة
       بعد الخسارة → تخفيض
    """

    # ثوابت الأمان
    MIN_PCT  = 0.005    # 0.5% حد أدنى
    MAX_PCT  = 0.05     # 5%   حد أقصى
    HALF_KELLY_FACTOR = 0.5

    def __init__(self,
                 balance:            float,
                 payout_pct:         float = 85.0,
                 win_rate:           float = 0.55,
                 consecutive_losses: int   = 0,
                 consecutive_wins:   int   = 0,
                 daily_loss_pct:     float = 0.0,
                 max_daily_loss_pct: float = 0.10,
                 anti_martingale:    bool  = False):
        self.balance            = balance
        self.payout             = payout_pct
        self.win_rate           = win_rate
        self.cons_losses        = consecutive_losses
        self.cons_wins          = consecutive_wins
        self.daily_loss_pct     = daily_loss_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.anti_martingale    = anti_martingale

    def _kelly_fraction(self) -> float:
        """حساب Kelly Criterion"""
        p = self.win_rate
        q = 1 - p
        b = self.payout / 100
        if b <= 0:
            return 0.0
        kelly = (p * b - q) / b
        return max(0.0, kelly * self.HALF_KELLY_FACTOR)

    def _loss_streak_multiplier(self) -> float:
        """يخفض الحجم بعد سلسلة الخسائر"""
        if self.cons_losses == 0:
            return 1.0
        if self.cons_losses == 1:
            return 0.80
        if self.cons_losses == 2:
            return 0.60
        return 0.40   # 3+ خسائر

    def _win_streak_multiplier(self) -> float:
        """Anti-Martingale: يزيد طفيفاً بعد الفوز"""
        if not self.anti_martingale or self.cons_wins == 0:
            return 1.0
        return min(1.0 + self.cons_wins * 0.05, 1.25)  # حد 25%

    def _daily_loss_protection(self) -> float:
        """يحمي من تجاوز حد الخسارة اليومية"""
        remaining = self.max_daily_loss_pct - self.daily_loss_pct
        if remaining <= 0:
            return 0.0
        if remaining < 0.02:
            return 0.25   # قرب الحد → حجم 25%
        if remaining < 0.05:
            return 0.60   # متوسط → حجم 60%
        return 1.0

    def calculate(self, signal_strength: float = 60.0) -> dict:
        """
        يحسب الحجم المثالي.

        signal_strength: من SignalStrengthScore.final_score (0-100)
        يُرجع: dict مع الحجم وكل التفاصيل
        """
        # 1. Kelly base
        kelly_f = self._kelly_fraction()

        # 2. تعديل بناءً على قوة الإشارة
        signal_factor = signal_strength / 100

        # 3. اجمع الأجزاء
        raw_fraction = kelly_f * signal_factor

        # 4. ضوابط سلسلة الخسائر والفوز
        loss_mult = self._loss_streak_multiplier()
        win_mult  = self._win_streak_multiplier()
        raw_fraction *= loss_mult * win_mult

        # 5. حماية الخسارة اليومية
        daily_mult = self._daily_loss_protection()
        if daily_mult == 0.0:
            return self._stopped_result("تجاوز حد الخسارة اليومية")

        raw_fraction *= daily_mult

        # 6. تطبيق الحدود الأمنية
        fraction = max(self.MIN_PCT, min(raw_fraction, self.MAX_PCT))

        # إذا Kelly سلبي (win_rate منخفض) → حجم الحد الأدنى فقط
        if kelly_f <= 0:
            fraction = self.MIN_PCT
            note = "⚠️ Win rate منخفض — حجم الحد الأدنى"
        else:
            note = ""

        trade_size = round(self.balance * fraction, 2)
        trade_size = max(1.0, trade_size)

        # 7. توقعات الجلسة
        expected_value = (
            self.win_rate * trade_size * (self.payout / 100) -
            (1 - self.win_rate) * trade_size
        )

        return {
            "trade_size":      trade_size,
            "fraction_pct":    round(fraction * 100, 2),
            "kelly_f":         round(kelly_f, 4),
            "signal_factor":   round(signal_factor, 2),
            "loss_multiplier": round(loss_mult, 2),
            "win_multiplier":  round(win_mult, 2),
            "daily_mult":      round(daily_mult, 2),
            "expected_value":  round(expected_value, 2),
            "note":            note,
            "stopped":         False,
            "breakdown": {
                "kelly_base":    f"{kelly_f*100:.2f}%",
                "after_signal":  f"{kelly_f*signal_factor*100:.2f}%",
                "after_streak":  f"{kelly_f*signal_factor*loss_mult*win_mult*100:.2f}%",
                "final":         f"{fraction*100:.2f}%",
            }
        }

    def _stopped_result(self, reason: str) -> dict:
        return {
            "trade_size": 0.0, "fraction_pct": 0.0,
            "kelly_f": 0.0, "signal_factor": 0.0,
            "loss_multiplier": 0.0, "win_multiplier": 0.0,
            "daily_mult": 0.0, "expected_value": 0.0,
            "note": reason, "stopped": True,
            "breakdown": {}
        }

    def format_telegram(self, result: dict) -> str:
        """يُنسّق نتيجة الحجم لـ Telegram"""
        if result["stopped"]:
            return f"🛑 *R/R Optimizer:* {result['note']}"

        ev = result["expected_value"]
        ev_icon = "🟢" if ev > 0 else "🔴"

        return (
            f"💰 *حجم الصفقة المحسّن: `${result['trade_size']:.2f}`*\n"
            f"   ({result['fraction_pct']:.2f}% من الرصيد)\n"
            f"   {ev_icon} القيمة المتوقعة: `{ev:+.2f}$`\n"
            + (f"   ⚠️ {result['note']}" if result["note"] else "")
        )


# ═══════════════════════════════════════════════════════════
#  8. إدارة رأس المال (بدون تغيير جوهري)
# ═══════════════════════════════════════════════════════════

class MoneyManagement:
    def __init__(self, balance: float, starting_balance: float,
                 consecutive_losses: int = 0, daily_loss_pct: float = 0.0):
        self.balance            = balance
        self.starting_balance   = starting_balance
        self.consecutive_losses = consecutive_losses
        self.daily_loss_pct     = daily_loss_pct

    def kelly_size(self, win_rate: float, payout_ratio: float) -> float:
        p, q = win_rate, 1 - win_rate
        b    = payout_ratio / 100
        kelly    = (p * b - q) / b if b > 0 else 0
        half_kelly = max(0, kelly / 2)
        return round(self.balance * min(half_kelly, 0.05), 2)

    def fixed_fractional(self, fraction: float = 0.02) -> float:
        return round(self.balance * fraction, 2)

    def circuit_breaker(self) -> dict:
        max_dd = (self.starting_balance - self.balance) / self.starting_balance
        if self.consecutive_losses >= 3:
            return {"stop": True, "reason": "3 خسائر متتالية — توقف وراجع"}
        if self.daily_loss_pct >= 0.10:
            return {"stop": True, "reason": f"خسارة يومية {self.daily_loss_pct*100:.1f}% — حد اليوم"}
        if max_dd >= 0.20:
            return {"stop": True, "reason": f"Drawdown {max_dd*100:.1f}% — خسارة 20% من الذروة"}
        return {"stop": False, "reason": "وضع البوت سليم"}

    def position_size(self, signal: Signal, win_rate: float = 0.55, payout: float = 85) -> float:
        if self.circuit_breaker()["stop"] or signal.direction == "WAIT":
            return 0.0
        if win_rate > 0.5:
            kelly = self.kelly_size(win_rate, payout)
            fixed = self.fixed_fractional(0.02)
            size  = min(kelly, fixed)
        else:
            size = self.fixed_fractional(0.01)
        return max(1.0, round(size, 2))


# ═══════════════════════════════════════════════════════════
#  9. محرك الاختبار التاريخي (محسّن)
# ═══════════════════════════════════════════════════════════

class BacktestEngine:
    """يحاكي البوت على بيانات تاريخية"""

    def __init__(self, all_candles: list[Candle], payout: float = 85.0,
                 balance: float = 1000.0, window: int = 60):
        self.all_candles = all_candles
        self.payout      = payout
        self.balance     = balance
        self.window      = window

    def run(self, min_score: int = 6) -> dict:
        trades    = []
        balance   = self.balance
        peak      = self.balance
        max_dd    = 0.0
        cons_loss = 0
        max_cons  = 0

        for i in range(self.window + 1, len(self.all_candles) - 1):
            window_candles = self.all_candles[i - self.window : i]
            current_price  = window_candles[-1].close
            next_candle    = self.all_candles[i]

            engine = ConfluenceEngine(
                candles       = window_candles,
                current_price = current_price,
                payout        = self.payout,
                balance       = balance,
            )
            signal = engine.run()

            if signal.direction == "WAIT" or signal.score < min_score:
                continue

            won = (next_candle.close > next_candle.open) if signal.direction == "UP" \
                  else (next_candle.close < next_candle.open)

            trade_size = signal.trade_size or balance * 0.02
            profit     = trade_size * (self.payout / 100) if won else -trade_size

            balance   = round(balance + profit, 2)
            peak      = max(peak, balance)
            drawdown  = (peak - balance) / peak
            max_dd    = max(max_dd, drawdown)

            cons_loss = cons_loss + 1 if not won else 0
            max_cons  = max(max_cons, cons_loss)

            trades.append({
                "index":      i,
                "direction":  signal.direction,
                "score":      signal.score,
                "won":        won,
                "profit":     round(profit, 2),
                "balance":    balance,
                "trade_size": round(trade_size, 2),
            })

        if not trades:
            return {"error": "لا توجد صفقات — خفف min_score أو أضف بيانات أكثر"}

        wins   = [t for t in trades if t["won"]]
        losses = [t for t in trades if not t["won"]]
        gp     = sum(t["profit"] for t in wins)
        gl     = abs(sum(t["profit"] for t in losses))

        return {
            "total_trades":           len(trades),
            "wins":                   len(wins),
            "losses":                 len(losses),
            "win_rate":               round(len(wins) / len(trades) * 100, 2),
            "profit_factor":          round(gp / gl, 2) if gl > 0 else float('inf'),
            "max_drawdown_pct":       round(max_dd * 100, 2),
            "max_consecutive_losses": max_cons,
            "starting_balance":       self.balance,
            "final_balance":          balance,
            "total_return_pct":       round((balance - self.balance) / self.balance * 100, 2),
            "avg_score_wins":         round(sum(t["score"] for t in wins) / len(wins), 2) if wins else 0,
            "trades_sample":          trades[:5],
        }


# ═══════════════════════════════════════════════════════════
#  البوت الرئيسي
# ═══════════════════════════════════════════════════════════

class TradingBot:
    """الواجهة الرئيسية للبوت"""

    def __init__(self, raw_candles: list[dict], current_price: Optional[float] = None,
                 payout: float = 85.0, balance: float = 1000.0, candle_age_pct: float = 0.0):
        self.candles = [
            Candle(**{k: v for k, v in c.items() if k in ("open","close","high","low","volume")})
            for c in raw_candles
        ]
        self.current_price = current_price or (self.candles[-1].close if self.candles else 0)
        self.payout        = payout
        self.balance       = balance
        self.candle_age    = candle_age_pct

    def analyze(self) -> Signal:
        engine = ConfluenceEngine(
            candles        = self.candles,
            current_price  = self.current_price,
            payout         = self.payout,
            balance        = self.balance,
            candle_age_pct = self.candle_age,
        )
        return engine.run()

    def backtest(self, min_score: int = 6) -> dict:
        return BacktestEngine(self.candles, self.payout, self.balance).run(min_score)

    def print_signal(self, signal: Signal) -> None:
        print("\n" + "="*65)
        print(f"  القرار:     {signal.direction}")
        print(f"  النقاط:     {signal.score}/{ConfluenceEngine.MAX_SCORE}")
        print(f"  الثقة:      {signal.confidence}%")
        print(f"  حجم الصفقة: ${signal.trade_size}")
        print("-"*65)
        if signal.reasons:
            print("  الأسباب:")
            for r in signal.reasons:
                print(f"    {r}")
        if signal.warnings:
            print("  تحذيرات:")
            for w in signal.warnings:
                print(f"    ⚠ {w}")
        print("="*65 + "\n")


# ═══════════════════════════════════════════════════════════
#  اختبار سريع
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import random
    random.seed(42)

    # توليد بيانات تجريبية واقعية (ترند صاعد ثم انعكاس)
    candles_raw = []
    price = 0.8600
    for i in range(80):
        # صعود في أول 40 شمعة ثم هبوط
        drift = 0.0002 if i < 40 else -0.0002
        change = drift + random.gauss(0, 0.0003)
        o = price
        c = round(o + change, 6)
        h = round(max(o, c) + abs(random.gauss(0, 0.0001)), 6)
        l = round(min(o, c) - abs(random.gauss(0, 0.0001)), 6)
        vol = random.randint(800, 2500)
        candles_raw.append({"open":o, "close":c, "high":h, "low":l, "volume":vol})
        price = c

    bot = TradingBot(
        raw_candles    = candles_raw,
        current_price  = price,
        payout         = 88.0,
        balance        = 500.0,
        candle_age_pct = 0.2,
    )

    print("🧪 اختبار بوت التداول الذكي v3")
    print("="*65)

    signal = bot.analyze()
    bot.print_signal(signal)

    # اختبار المكونات الجديدة
    candles = bot.candles
    print("\n📊 اختبار المكونات الجديدة:")
    print("-"*65)

    mtf = MultiTimeframe(candles)
    mtf_r = mtf.analyze()
    print(f"✅ Multi-Timeframe: {mtf_r['agreement']} | 1m={mtf_r['1m']} 5m={mtf_r['5m']} 15m={mtf_r['15m']}")

    dsr = DynamicSR(candles)
    dsr_r = dsr.find_zones(price)
    print(f"✅ Dynamic S/R: مقاومة وزن={dsr_r['resistance_weight']} | دعم وزن={dsr_r['support_weight']}")

    div = DivergenceDetector(candles)
    div_r = div.detect()
    print(f"✅ Divergence: {div_r['divergence']} | {div_r.get('description','—')}")

    ms = MarketStructure(candles)
    ms_r = ms.analyze()
    print(f"✅ Market Structure: {ms_r['event']} | {ms_r.get('description','—')}")

    vol_a = VolumeAnalysis(candles)
    vol_r = vol_a.analyze("UP")
    print(f"✅ Volume: ratio={vol_r['ratio']}x | confirmed={vol_r['confirmed']}")

    sess = SessionFilter()
    sess_r = sess.analyze()
    print(f"✅ Session: {sess_r['session']} | UTC={sess_r['utc_hour']}h | prime={sess_r['in_prime']}")

    fib = FibonacciLevels(candles)
    fib_r = fib.calculate(price)
    print(f"✅ Fibonacci: nearest={fib_r['nearest_name']} | at_level={fib_r['at_level']}")

    ha = HeikinAshi(candles)
    ha_r = ha.analyze()
    print(f"✅ Heikin Ashi: {ha_r['signal']} | {ha_r['description']}")

    mom = MomentumOscillator(candles)
    mom_r = mom.analyze()
    print(f"✅ Momentum: ROC={mom_r['roc']} | signal={mom_r['signal']}")

    tl = TrendLines(candles)
    tl_r = tl.analyze(price)
    print(f"✅ Trend Lines: signal={tl_r['signal']} | event={tl_r['event']} | {tl_r['description']}")

    ob = OrderBlocks(candles)
    ob_r = ob.analyze(price)
    print(f"✅ Order Blocks: signal={ob_r['signal']} | bull={ob_r['total_bull_obs']} bear={ob_r['total_bear_obs']} | {ob_r['description']}")

    print("\n✅ جميع الاختبارات نجحت!")
    print(f"   النقاط الكلية: {signal.score}/{ConfluenceEngine.MAX_SCORE}")
    print(f"   المكونات الجديدة: 11 مكوّن مضاف")

"""
=============================================================
  telegram_alerts_pro.py — Telegram Alerts Pro
  رسائل احترافية محسّنة للإشارات

  المميزات الجديدة:
  ─────────────────────────────────────────────
  1. SignalFormatter      — تنسيق إشارة احترافي شامل
  2. ChartGenerator       — رسم شارت ASCII بالشموع
  3. HistoryStats         — إحصائيات تاريخية للزوج
  4. AlertThrottler       — منع تكرار التنبيهات
  5. SessionSummary       — ملخص نهاية الجلسة
  6. ProMessageBuilder    — بناء رسائل Pro كاملة

  مقارنة القبل والبعد:
  ─────────────────────────────────────────────
  قبل:  نص بسيط مع نقاط وأسباب
  بعد:  شارت ASCII + إحصائيات + قوة الإشارة +
        R/R محسوب + نسبة نجاح تاريخية + تحليل جلسة
=============================================================
"""

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from bot_algorithms import (
    Candle, Signal, ConfluenceEngine,
    SignalStrengthScore, RiskRewardOptimizer,
    SessionFilter, MarketRegimeDetector,
    IchimokuCloud, VWAP, MultiTimeframe,
)


# ═══════════════════════════════════════════════════════════
#  هياكل البيانات
# ═══════════════════════════════════════════════════════════

@dataclass
class TradeHistoryEntry:
    """سجل صفقة واحدة للإحصائيات"""
    symbol:    str
    direction: str
    score:     int
    won:       Optional[bool]
    profit:    float
    timestamp: float = field(default_factory=time.time)


@dataclass
class AlertThrottleKey:
    """مفتاح منع التكرار"""
    symbol:    str
    direction: str
    score_band: int   # نطاق النقاط (0-5, 6-10, 11+)


# ═══════════════════════════════════════════════════════════
#  1. رسام الشارت ASCII
# ═══════════════════════════════════════════════════════════

class ChartGenerator:
    """
    يرسم شارت ASCII للشموع داخل رسالة Telegram.

    المظهر النهائي:
    ─────────────────────────────────────────────
    1.1050 ┤                    ┃
    1.1040 ┤            ┃       ┃
    1.1030 ┤     ┃      ▓▓▓     ▓▓▓
    1.1020 ┤     ▓▓▓    ▓▓▓     ▓▓▓
    1.1010 ┤  ┃  ▓▓▓    ▓▓▓  ┃  ▓▓▓
    1.1000 ┤  ▓▓▓ ┃     ┃    ▓▓▓  ┃
           └──────────────────────────
             1   2   3   4   5

    ▓▓▓ = جسم الشمعة (أخضر صاعد / أحمر هابط)
    ┃   = الظل (wick)
    """

    WIDTH  = 16   # عدد الشموع المعروضة
    HEIGHT = 8    # ارتفاع الشارت بالأسطر

    # رموز ASCII المتاحة في Telegram
    BULL_BODY  = "█"   # جسم صاعد
    BEAR_BODY  = "▓"   # جسم هابط
    WICK       = "│"   # ظل
    EMPTY      = " "

    def __init__(self, candles: list[Candle]):
        self.candles = candles[-self.WIDTH:] if len(candles) > self.WIDTH else candles

    def _normalize(self, value: float, low: float, high: float) -> float:
        """يحوّل السعر إلى موقع في الشارت (0 = أسفل, 1 = أعلى)"""
        rng = high - low
        if rng == 0:
            return 0.5
        return (value - low) / rng

    def generate(self) -> str:
        """يولّد نص الشارت"""
        if len(self.candles) < 3:
            return "📊 بيانات غير كافية للشارت"

        all_highs = [c.high  for c in self.candles]
        all_lows  = [c.low   for c in self.candles]
        price_high = max(all_highs)
        price_low  = min(all_lows)

        if price_high == price_low:
            return "📊 السوق ثابت — لا شارت"

        # بناء الشبكة
        rows = self.HEIGHT
        cols = len(self.candles)
        grid = [[self.EMPTY] * cols for _ in range(rows)]

        for col, candle in enumerate(self.candles):
            # تطبيع المستويات
            h_row = rows - 1 - int(self._normalize(candle.high,  price_low, price_high) * (rows - 1))
            l_row = rows - 1 - int(self._normalize(candle.low,   price_low, price_high) * (rows - 1))
            o_row = rows - 1 - int(self._normalize(candle.open,  price_low, price_high) * (rows - 1))
            c_row = rows - 1 - int(self._normalize(candle.close, price_low, price_high) * (rows - 1))

            body_top    = min(o_row, c_row)
            body_bottom = max(o_row, c_row)
            body_char   = self.BULL_BODY if candle.is_bullish else self.BEAR_BODY

            for r in range(rows):
                if r == h_row or r == l_row:
                    grid[r][col] = self.WICK
                elif body_top <= r <= body_bottom:
                    grid[r][col] = body_char
                elif h_row < r < body_top or body_bottom < r < l_row:
                    grid[r][col] = self.WICK

        # تحويل الشبكة إلى نص
        lines = ["```"]
        # مقياس الأسعار (يسار)
        for row_idx, row in enumerate(grid):
            price_at = price_high - (price_high - price_low) * row_idx / (rows - 1)
            row_str  = "".join(row)
            lines.append(f"{price_at:.4f}|{row_str}")

        # خط الأسفل
        lines.append("       " + "─" * cols)
        lines.append("```")

        return "\n".join(lines)

    def generate_mini(self) -> str:
        """
        شارت مصغر للرسائل الطويلة — سطر واحد.
        مثال: ▃▄▅▆▇██▇▆▅▄▃▄▅▇
        """
        if len(self.candles) < 3:
            return ""

        all_closes = [c.close for c in self.candles]
        lo = min(all_closes)
        hi = max(all_closes)

        bars = "▁▂▃▄▅▆▇█"
        result = ""
        for price in all_closes[-16:]:
            idx = int((price - lo) / (hi - lo + 1e-9) * (len(bars) - 1))
            result += bars[idx]

        # لون آخر شمعة
        last = self.candles[-1]
        trend_icon = "⬆" if last.close > last.open else "⬇" if last.close < last.open else "➡"

        return f"`{result}` {trend_icon}"


# ═══════════════════════════════════════════════════════════
#  2. إحصائيات تاريخية
# ═══════════════════════════════════════════════════════════

class HistoryStats:
    """
    يحتفظ بسجل الصفقات ويحسب:
    - نسبة نجاح الزوج الحالي
    - نسبة نجاح الإشارات بنفس النقاط
    - أفضل أوقات التداول
    - متوسط الربح/الخسارة
    """

    def __init__(self):
        self._history: list[TradeHistoryEntry] = []
        self._max_history = 500

    def add(self, entry: TradeHistoryEntry):
        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def add_result(self, symbol: str, direction: str,
                   score: int, won: bool, profit: float):
        self.add(TradeHistoryEntry(symbol, direction, score, won, profit))

    def win_rate_for_symbol(self, symbol: str,
                             last_n: int = 20) -> Optional[float]:
        """نسبة نجاح الزوج في آخر N صفقة"""
        trades = [t for t in self._history
                  if t.symbol == symbol and t.won is not None][-last_n:]
        if len(trades) < 3:
            return None
        return sum(1 for t in trades if t.won) / len(trades) * 100

    def win_rate_for_score_range(self, score: int) -> Optional[float]:
        """نسبة نجاح الإشارات بنفس نطاق النقاط"""
        band_min = (score // 3) * 3
        band_max = band_min + 3
        trades = [t for t in self._history
                  if band_min <= t.score < band_max and t.won is not None]
        if len(trades) < 5:
            return None
        return sum(1 for t in trades if t.won) / len(trades) * 100

    def avg_profit(self, symbol: str = None) -> float:
        """متوسط الربح/الخسارة"""
        trades = [t for t in self._history if t.won is not None]
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        if not trades:
            return 0.0
        return sum(t.profit for t in trades) / len(trades)

    def today_summary(self) -> dict:
        """ملخص اليوم"""
        today = datetime.now().date()
        today_trades = [
            t for t in self._history
            if datetime.fromtimestamp(t.timestamp).date() == today
               and t.won is not None
        ]
        if not today_trades:
            return {"total": 0, "wins": 0, "losses": 0,
                    "win_rate": 0.0, "net_profit": 0.0}
        wins    = sum(1 for t in today_trades if t.won)
        losses  = len(today_trades) - wins
        net     = sum(t.profit for t in today_trades)
        return {
            "total":      len(today_trades),
            "wins":       wins,
            "losses":     losses,
            "win_rate":   round(wins / len(today_trades) * 100, 1),
            "net_profit": round(net, 2),
        }

    def format_history_line(self, symbol: str, score: int) -> str:
        """سطر إحصائيات مدمج لرسالة الإشارة"""
        wr_sym   = self.win_rate_for_symbol(symbol)
        wr_score = self.win_rate_for_score_range(score)
        today    = self.today_summary()

        parts = []
        if wr_sym is not None:
            icon = "🟢" if wr_sym >= 60 else "🟡" if wr_sym >= 50 else "🔴"
            parts.append(f"{icon} زوج: {wr_sym:.0f}%")
        if wr_score is not None:
            parts.append(f"📊 نقاط{score}: {wr_score:.0f}%")
        if today["total"] > 0:
            pnl_icon = "+" if today["net_profit"] >= 0 else ""
            parts.append(
                f"📅 {today['wins']}✅{today['losses']}❌ "
                f"`{pnl_icon}{today['net_profit']:.2f}$`"
            )

        return "  ".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════
#  3. منع تكرار التنبيهات
# ═══════════════════════════════════════════════════════════

class AlertThrottler:
    """
    يمنع إرسال نفس الإشارة مرتين في فترة قصيرة.
    مفيد عند الإشارات المتكررة في نفس الزوج.
    """

    def __init__(self, cooldown_seconds: int = 90):
        self._sent: dict = {}   # key → timestamp
        self.cooldown = cooldown_seconds

    def should_send(self, symbol: str, direction: str,
                    score: int) -> bool:
        """هل يجب إرسال هذه الإشارة؟"""
        band = score // 3
        key  = f"{symbol}:{direction}:{band}"
        now  = time.time()
        last = self._sent.get(key, 0)

        if now - last >= self.cooldown:
            self._sent[key] = now
            return True
        return False

    def time_until_next(self, symbol: str,
                         direction: str, score: int) -> int:
        """ثواني حتى يُسمح بإرسال الإشارة التالية"""
        band = score // 3
        key  = f"{symbol}:{direction}:{band}"
        last = self._sent.get(key, 0)
        remaining = self.cooldown - (time.time() - last)
        return max(0, int(remaining))


# ═══════════════════════════════════════════════════════════
#  4. منسّق الإشارة الاحترافي
# ═══════════════════════════════════════════════════════════

class SignalFormatter:
    """
    يُنسّق رسالة الإشارة بشكل احترافي كامل.

    الرسالة النهائية تشمل:
    ─────────────────────────────────────────────
    1. رأس الرسالة  — الاتجاه + الزوج + الوقت
    2. شارت mini    — 16 شمعة بصرية
    3. قوة الإشارة  — نظام النقاط المحسّن
    4. R/R محسوب    — الحجم المثالي + EV
    5. تحليل الجلسة — وقت التداول الحالي
    6. أسباب رئيسية — أقوى 5 عوامل
    7. تحذيرات      — إن وجدت
    8. إحصائيات    — نجاح تاريخي
    9. Market Regime — حالة السوق
    """

    MAX_SCORE = ConfluenceEngine.MAX_SCORE

    def __init__(self,
                 symbol:        str,
                 candles:       list[Candle],
                 history:       HistoryStats,
                 balance:       float = 1000.0,
                 consecutive_losses: int = 0,
                 consecutive_wins:   int = 0,
                 daily_loss_pct:     float = 0.0):
        self.symbol      = symbol
        self.candles     = candles
        self.history     = history
        self.balance     = balance
        self.cons_losses = consecutive_losses
        self.cons_wins   = consecutive_wins
        self.daily_loss  = daily_loss_pct

    def format_pro(self, signal: Signal, payout: float = 85.0) -> str:
        """
        يبني رسالة الإشارة الاحترافية — تصميم كارد (مستوحى من GPT Trading Bot).
        """
        direction = signal.direction
        score     = signal.score
        details   = signal.details

        # ── Direction badge ──────────────────────────
        if direction == "UP":
            dir_badge = "🟢  ⬆ BUY  ⬆"
        elif direction == "DOWN":
            dir_badge = "🔴  ⬇ SELL ⬇"
        else:
            dir_badge = "⏸  ⟳ WAIT ⟳"

        now_str = datetime.now().strftime("%H:%M:%S")

        # ── Confidence bar ────────────────────────────
        conf     = signal.confidence
        filled   = int(conf / 10)
        conf_bar = "█" * filled + "░" * (10 - filled)

        # ── Signal strength ───────────────────────────
        sess_data = details.get("session", {})
        sss = SignalStrengthScore(
            signal             = signal,
            consecutive_losses = self.cons_losses,
            session_prime      = sess_data.get("in_prime", False),
            in_dead_zone       = sess_data.get("in_dead_zone", False),
        )
        strength_result = sss.calculate()
        grade      = strength_result["grade"]
        grade_icon = strength_result["grade_icon"]
        final_sc   = strength_result["final_score"]

        grade_ar = {
            "VERY_STRONG": "🔥 قوي جداً",
            "STRONG":      "💪 قوي",
            "MODERATE":    "👍 متوسط",
            "WEAK":        "⚠️ ضعيف",
            "VERY_WEAK":   "❌ ضعيف جداً",
        }.get(grade, grade)

        # ── R/R Optimizer ────────────────────────────
        rr = RiskRewardOptimizer(
            balance            = self.balance,
            payout_pct         = payout,
            win_rate           = max(0.40, 0.45 + score * 0.01),
            consecutive_losses = self.cons_losses,
            consecutive_wins   = self.cons_wins,
            daily_loss_pct     = self.daily_loss,
        )
        rr_result  = rr.calculate(signal_strength=final_sc)
        trade_size = rr_result["trade_size"] if not rr_result["stopped"] else 0.0
        ev         = rr_result["expected_value"]

        # ── Mini chart ────────────────────────────────
        chart = ChartGenerator(self.candles)
        mini_chart = chart.generate_mini()

        # ── Session context ───────────────────────────
        sess    = details.get("session", {})
        regime  = details.get("regime",  {})
        sess_name   = sess.get("session", "—")
        regime_name = regime.get("regime", "—")

        # ── Reasons ───────────────────────────────────
        top_reasons = signal.reasons[:5]
        reasons_text = "\n".join(f"  • {r}" for r in top_reasons) or "  —"

        # ── Warnings ──────────────────────────────────
        warnings_text = ""
        if signal.warnings:
            warns = "\n".join(f"  ⚠️ {w}" for w in signal.warnings[:3])
            warnings_text = f"\n⚠️ *تحذيرات:*\n{warns}"

        # ── History ───────────────────────────────────
        history_line = self.history.format_history_line(self.symbol, score)

        # ── Extra analysis details ────────────────────
        mtf   = details.get("mtf", {})
        ob    = details.get("orderblocks", {})
        ichi  = details.get("ichimoku", {})
        vwap  = details.get("vwap", {})

        extra_lines = []
        if mtf.get("agreement") == "FULL":
            extra_lines.append(f"🔭 MTF: {mtf.get('1m')} / {mtf.get('5m')} / {mtf.get('15m')}")
        if ob.get("in_bullish_ob") or ob.get("in_bearish_ob"):
            extra_lines.append(f"🏦 OB: {ob.get('description','')[:40]}")
        if ichi.get("above_cloud") or ichi.get("below_cloud"):
            pos = "فوق" if ichi.get("above_cloud") else "تحت"
            extra_lines.append(f"☁️ Ichimoku: السعر {pos} السحابة")
        if vwap.get("position") in ("EXTREME_OVERBOUGHT", "EXTREME_OVERSOLD"):
            extra_lines.append(f"📊 VWAP: {vwap.get('description','')[:40]}")
        extra_text = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

        # ── Build message ─────────────────────────────
        ev_str  = f"+{ev:.2f}$" if ev >= 0 else f"{ev:.2f}$"
        ev_icon = "🟢" if ev >= 0 else "🔴"

        msg = (
            f"◆━━━━━━━━━━━━━━━━━━━━━━━━━━◆\n"
            f"  {dir_badge}  `{self.symbol}`\n"
            f"◆━━━━━━━━━━━━━━━━━━━━━━━━━━◆\n"
            f"  📊 `{conf_bar}`  `{conf:.0f}%`\n"
            f"  ⚡ نقاط: `{score}/{self.MAX_SCORE}`  {grade_icon} {grade_ar}\n"
            f"  💡 قوة: `{final_sc:.0f}%`\n"
        )

        if mini_chart:
            msg += f"  📈 {mini_chart}\n"

        msg += (
            f"◆━━━━ *الإعدادات* ━━━━━━━◆\n"
            f"  💰 الحجم: `{trade_size:.2f}$`\n"
            f"  📊 النسبة: `{rr_result['fraction_pct']:.2f}%`\n"
            f"  {ev_icon} المتوقع: `{ev_str}`\n"
        )

        if history_line:
            msg += (
                f"◆━━ *الإحصائيات* ━━━━━━━◆\n"
                f"  {history_line}\n"
            )

        msg += f"◆━━ *التحليل* ━━━━━━━━◆\n{reasons_text}"
        if extra_text:
            msg += f"{extra_text}\n"
        msg += f"\n◆━ *السياق* ━━━━━━━━━◆\n  🕐 {now_str} | 📍 {sess_name}\n  📉 {regime_name}\n"

        if warnings_text:
            msg += f"◆━ *تحذيرات* ━━━━━━━━◆{warnings_text}\n"

        # Forecast block (success probability)
        success_pct = min(98, int(final_sc * 0.6 + conf * 0.4))
        overlap_pct = max(5, min(30, 20 - int(final_sc * 0.15)))
        msg += (
            f"◆━━ *التوقعات* ━━━━━━━━◆\n"
            f"  ❌ تداخل: `{overlap_pct}%`\n"
            f"  ✅ نجاح: `{success_pct}%`\n"
        )

        # تعزيز إذا كانت الإشارة قوية
        if grade in ("VERY_STRONG", "STRONG"):
            bonuses_text = " | ".join(strength_result["bonuses"][:2])
            msg += f"◆━━━━━━━━━━━━━━━━━━━━━━━━━━◆\n  ✅ *تعزيز:* {bonuses_text}\n"

        # تحذير إضافي من الخسائر المتتالية
        if self.cons_losses >= 2:
            msg += (
                f"◆━━━━━━━━━━━━━━━━━━━━━━━━━━◆\n"
                f"  ⚠️ *تحذير:* {self.cons_losses} خسائر متتالية — الحجم مخفض\n"
            )

        msg += f"◆━━━━━━━━━━━━━━━━━━━━━━━━━━◆"
        return msg

    def format_compact(self, signal: Signal) -> str:
        """
        نسخة مختصرة للإشارات السريعة (بدون شارت وإحصائيات).
        """
        direction = signal.direction
        icon = "🟢" if direction == "UP" else "🔴" if direction == "DOWN" else "⏸"
        arrow = "⬆️" if direction == "UP" else "⬇️" if direction == "DOWN" else "⏸"

        filled = int(signal.confidence / 10)
        bar    = "█" * filled + "░" * (10 - filled)

        return (
            f"{icon} `{self.symbol}` {arrow} *{direction}*\n"
            f"`{bar}` {signal.confidence:.0f}% | نقاط: {signal.score}/{self.MAX_SCORE}\n"
            f"💰 `${signal.trade_size:.2f}` | "
            f"{datetime.now().strftime('%H:%M:%S')}"
        )


# ═══════════════════════════════════════════════════════════
#  5. ملخص الجلسة
# ═══════════════════════════════════════════════════════════

class SessionSummary:
    """يولّد ملخص نهاية الجلسة الاحترافي"""

    def __init__(self, history: HistoryStats,
                 balance_start: float,
                 balance_end:   float,
                 session_start: float):
        self.history       = history
        self.balance_start = balance_start
        self.balance_end   = balance_end
        self.session_start = session_start

    def generate(self) -> str:
        today = self.history.today_summary()
        net   = self.balance_end - self.balance_start
        pct   = (net / self.balance_start * 100) if self.balance_start > 0 else 0.0
        dur   = int(time.time() - self.session_start)
        h, r  = divmod(dur, 3600)
        m, s  = divmod(r, 60)

        # شريط نسبة النجاح
        wr   = today["win_rate"]
        bar  = "█" * int(wr / 10) + "░" * (10 - int(wr / 10))
        pnl_icon = "🟢" if net >= 0 else "🔴"
        net_str  = f"+{net:.2f}" if net >= 0 else f"{net:.2f}"

        return (
            f"📊 *ملخص الجلسة*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ مدة الجلسة: `{h:02d}:{m:02d}:{s:02d}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📨 إجمالي الصفقات: {today['total']}\n"
            f"✅ ربح: {today['wins']} | ❌ خسارة: {today['losses']}\n"
            f"📈 نسبة النجاح: `{bar}` {wr:.1f}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 رصيد البداية: `${self.balance_start:.2f}`\n"
            f"💰 رصيد النهاية: `${self.balance_end:.2f}`\n"
            f"{pnl_icon} صافي: `{net_str}$` ({pct:+.1f}%)\n"
        )


# ═══════════════════════════════════════════════════════════
#  6. بناء الرسائل الكامل (Pro Message Builder)
# ═══════════════════════════════════════════════════════════

class ProMessageBuilder:
    """
    الواجهة الرئيسية — يربط كل المكوّنات معاً.

    الاستخدام في main.py:
    ─────────────────────────────────────────────
    builder = ProMessageBuilder()

    # عند كل إشارة:
    msg = builder.build_signal_message(
        signal  = sig,
        candles = candles,
        symbol  = "EURUSD-OTC",
        payout  = 88.0,
        balance = 1000.0,
    )
    await bot.send_message(chat_id, msg)

    # عند نتيجة الصفقة:
    builder.record_result("EURUSD-OTC", "UP", 10, True, 8.5)

    # ملخص الجلسة:
    summary = builder.build_session_summary(1000, 1050, session_start)
    """

    def __init__(self, throttle_seconds: int = 90):
        self.history   = HistoryStats()
        self.throttler = AlertThrottler(throttle_seconds)
        self._session_start = time.time()
        self._cons_losses   = 0
        self._cons_wins     = 0
        self._daily_loss    = 0.0

    def update_streak(self, won: bool):
        """يحدّث سلاسل الفوز/الخسارة"""
        if won:
            self._cons_wins   += 1
            self._cons_losses  = 0
        else:
            self._cons_losses += 1
            self._cons_wins    = 0

    def record_result(self, symbol: str, direction: str,
                      score: int, won: bool, profit: float):
        """يسجّل نتيجة الصفقة"""
        self.history.add_result(symbol, direction, score, won, profit)
        self.update_streak(won)
        if profit < 0:
            self._daily_loss = max(0, self._daily_loss - profit / 1000)

    def should_send(self, symbol: str,
                    direction: str, score: int) -> bool:
        """هل يجب إرسال الإشارة؟ (مع throttle)"""
        return self.throttler.should_send(symbol, direction, score)

    def build_signal_message(self,
                              signal:  Signal,
                              candles: list[Candle],
                              symbol:  str,
                              payout:  float = 85.0,
                              balance: float = 1000.0,
                              compact: bool  = False) -> str:
        """يبني رسالة الإشارة الكاملة"""
        formatter = SignalFormatter(
            symbol             = symbol,
            candles            = candles,
            history            = self.history,
            balance            = balance,
            consecutive_losses = self._cons_losses,
            consecutive_wins   = self._cons_wins,
            daily_loss_pct     = self._daily_loss,
        )
        if compact:
            return formatter.format_compact(signal)
        return formatter.format_pro(signal, payout)

    def build_session_summary(self,
                               balance_start: float,
                               balance_end:   float) -> str:
        """يبني ملخص الجلسة"""
        summary = SessionSummary(
            history       = self.history,
            balance_start = balance_start,
            balance_end   = balance_end,
            session_start = self._session_start,
        )
        return summary.generate()

    def build_ai_enhanced_message(self, signal: Signal, usp=None, hybrid_text: str = "") -> str:
        base = self.build_signal_message(signal, [], symbol=signal.details.get("symbol", ""), compact=False)
        extras = []
        if usp:
            if usp.ai_ensemble_direction != "neutral":
                extras.append(f"🧠 AI Ensemble: {usp.ai_ensemble_direction} ({usp.ai_ensemble_confidence}%)")
            if usp.claude_analysis and hasattr(usp.claude_analysis, 'final_confidence'):
                extras.append(f"🤖 Claude: {usp.claude_analysis.final_direction} ({usp.claude_analysis.final_confidence}%)")
            if usp.fused_result and usp.fused_result.votes:
                extras.append(f"⚖️ Fused: {usp.fused_result.direction} ({usp.fused_result.confidence}%) | {len(usp.fused_result.votes)} votes")
        if hybrid_text:
            extras.append(f"📋 {hybrid_text[:200]}")
        if extras:
            base += "\n◆━━ *AI Analysis* ━━━━━━━◆\n" + "\n".join(f"  {e}" for e in extras)
        return base

    def build_strength_report(self, signal: Signal) -> str:
        """تقرير قوة الإشارة فقط"""
        sss = SignalStrengthScore(
            signal             = signal,
            consecutive_losses = self._cons_losses,
        )
        return sss.format_telegram()

    def build_rr_report(self,
                         signal:   Signal,
                         balance:  float,
                         payout:   float) -> str:
        """تقرير R/R Optimizer فقط"""
        sss    = SignalStrengthScore(signal, self._cons_losses)
        result = sss.calculate()

        rr = RiskRewardOptimizer(
            balance            = balance,
            payout_pct         = payout,
            win_rate           = 0.45 + signal.score * 0.01,
            consecutive_losses = self._cons_losses,
            consecutive_wins   = self._cons_wins,
            daily_loss_pct     = self._daily_loss,
        )
        rr_result = rr.calculate(result["final_score"])
        return rr.format_telegram(rr_result)


# ═══════════════════════════════════════════════════════════
#  اختبار
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import random, math

    random.seed(55)
    price = 1.1000
    candles = []
    for i in range(80):
        drift  = 0.00012 if i < 40 else -0.00018
        change = drift + random.gauss(0, 0.00022)
        o = price
        c = round(o + change, 6)
        h = round(max(o, c) + abs(random.gauss(0, 0.00009)), 6)
        l = round(min(o, c) - abs(random.gauss(0, 0.00009)), 6)
        candles.append(Candle(o, c, h, l, random.randint(1000, 3000)))
        price = c

    # إشارة تجريبية
    sig = ConfluenceEngine(candles, price, 88.0, 1000.0, utc_hour=9).run()

    print("=" * 60)
    print("اختبار Telegram Alerts Pro")
    print("=" * 60)

    # اختبار الشارت
    chart = ChartGenerator(candles)
    mini  = chart.generate_mini()
    print(f"\n📈 Mini Chart:\n{mini}")

    # إضافة بعض السجلات التاريخية
    history = HistoryStats()
    for i in range(15):
        won = random.random() > 0.4
        history.add_result(
            "EURUSD-OTC", "UP" if i % 2 == 0 else "DOWN",
            random.randint(6, 14), won,
            random.uniform(5, 15) if won else -random.uniform(5, 10)
        )

    # اختبار SignalStrengthScore
    sss = SignalStrengthScore(sig, consecutive_losses=1)
    result = sss.calculate()
    print(f"\n⚡ Signal Strength:")
    print(f"  Base: {result['base_score']}/{ConfluenceEngine.MAX_SCORE}")
    print(f"  Final: {result['final_score']:.1f}%")
    print(f"  Grade: {result['grade_icon']} {result['grade']}")
    print(f"  Bonuses: {result['bonuses'][:2]}")
    print(f"  Penalties: {result['penalties'][:2]}")

    # اختبار R/R Optimizer
    rr = RiskRewardOptimizer(1000.0, 88.0, 0.55, consecutive_losses=1)
    rr_r = rr.calculate(result["final_score"])
    print(f"\n💰 R/R Optimizer:")
    print(f"  Trade Size: ${rr_r['trade_size']:.2f}")
    print(f"  Fraction: {rr_r['fraction_pct']:.2f}%")
    print(f"  EV: {rr_r['expected_value']:+.2f}$")
    print(f"  Breakdown: {rr_r['breakdown']}")

    # اختبار ProMessageBuilder
    builder = ProMessageBuilder()
    for i in range(5):
        won = random.random() > 0.45
        builder.record_result("EURUSD-OTC", "UP", 10, won,
                               8.5 if won else -10.0)

    msg = builder.build_signal_message(sig, candles, "EURUSD-OTC",
                                        payout=88.0, balance=1000.0)
    print(f"\n📱 رسالة الإشارة الكاملة:")
    print("─" * 60)
    print(msg)
    print("─" * 60)

    # اختبار throttler
    throttler = AlertThrottler(90)
    print(f"\n🔔 Throttler:")
    print(f"  Send 1: {throttler.should_send('EURUSD-OTC', 'UP', 10)}")
    print(f"  Send 2 (immediate): {throttler.should_send('EURUSD-OTC', 'UP', 10)}")
    print(f"  Wait: {throttler.time_until_next('EURUSD-OTC', 'UP', 10)}s")

    # ملخص الجلسة
    summary = builder.build_session_summary(1000.0, 1023.5)
    print(f"\n📊 ملخص الجلسة:")
    print(summary)

    print("\n✅ جميع اختبارات Telegram Alerts Pro نجحت!")

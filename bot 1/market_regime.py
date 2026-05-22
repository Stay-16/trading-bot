from __future__ import annotations

import logging
from typing import Optional

from indicators_library import calc_adx, calc_atr, calc_rsi, _sma

log = logging.getLogger("MarketRegime")


class MarketRegimeFilter:
    """
    يحدد حالة السوق (Trending / Ranging / Volatile) بناءً على ADX + ATR
    ويختار الاستراتيجية المناسبة تلقائياً.
    """

    def __init__(self,
                 adx_trend_threshold: float = 25.0,
                 adx_strong_trend: float = 40.0,
                 atr_volatile_pct: float = 0.015):
        self.adx_trend_threshold = adx_trend_threshold
        self.adx_strong_trend = adx_strong_trend
        self.atr_volatile_pct = atr_volatile_pct
        self._last_regime: str = "unknown"
        self._last_strategy: str = "confluence"

    def analyze(self, highs: list[float], lows: list[float], closes: list[float],
                volumes: Optional[list[float]] = None) -> dict:
        if not closes or len(closes) < 20:
            return {"regime": "unknown", "strategy": "confluence", "adx": 25, "confidence": 50}

        adx_data = calc_adx(highs, lows, closes)
        adx = adx_data.get("adx", 25)
        di_plus = adx_data.get("di_plus", 20)
        di_minus = adx_data.get("di_minus", 20)
        atr_val = calc_atr(highs, lows, closes)
        atr_pct = atr_val / closes[-1] if closes[-1] else 0
        rsi = calc_rsi(closes)
        price_vs_sma = (closes[-1] - _sma(closes, 50)) / _sma(closes, 50) * 100 if _sma(closes, 50) else 0

        # تحديد النظام
        if adx >= self.adx_strong_trend:
            regime = "strong_trend"
            strategy = "trend_following"
            conf = min(95, 60 + adx * 0.8)
        elif adx >= self.adx_trend_threshold:
            regime = "trending"
            if di_plus > di_minus:
                strategy = "trend_following"
            else:
                strategy = "trend_following"
            conf = min(90, 50 + adx * 0.6)
        elif atr_pct >= self.atr_volatile_pct:
            regime = "volatile"
            strategy = "breakout_retest"
            conf = 65
        elif adx < 20:
            regime = "ranging"
            # Mean reversion مناسب للأسواق الجانبية
            if 30 <= rsi <= 70:
                strategy = "mean_reversion"
                conf = 80
            else:
                strategy = "mean_reversion"
                conf = 65
        else:
            regime = "transitional"
            strategy = "confluence"
            conf = 60

        # تعديل الثقة حسب المؤشرات الإضافية
        if abs(price_vs_sma) > 3:
            conf -= 5
        if 30 <= rsi <= 70:
            conf += 5
        if di_plus > di_minus and di_plus - di_minus > 10:
            conf += 5

        self._last_regime = regime
        self._last_strategy = strategy

        return {
            "regime": regime,
            "regime_label": self._regime_label(regime),
            "strategy": strategy,
            "strategy_label": self._strategy_label(strategy),
            "adx": round(adx, 1),
            "di_plus": round(di_plus, 1),
            "di_minus": round(di_minus, 1),
            "atr_pct": round(atr_pct * 100, 3),
            "rsi": round(rsi, 1),
            "confidence": min(95, int(conf)),
        }

    def adjust_signal_confidence(self, base_confidence: int, regime_info: dict) -> int:
        """تعديل الثقة الأساسية حسب حالة السوق"""
        regime = regime_info.get("regime", "unknown")
        if regime == "strong_trend":
            return min(95, base_confidence + 10)
        if regime == "trending":
            return min(95, base_confidence + 5)
        if regime == "volatile":
            return max(0, base_confidence - 10)
        if regime == "ranging":
            return max(0, base_confidence - 5)
        return base_confidence

    def select_strategy(self, regime_info: dict) -> str:
        return regime_info.get("strategy", "confluence")

    @staticmethod
    def _regime_label(r: str) -> str:
        return {
            "strong_trend": "اتجاه قوي 🚀",
            "trending": "اتجاه 📈",
            "ranging": "جانبي ⏸️",
            "volatile": "متقلب 🌊",
            "transitional": "انتقالي 🔄",
        }.get(r, "غير معروف")

    @staticmethod
    def _strategy_label(s: str) -> str:
        return {
            "trend_following": "اتباع الاتجاه",
            "mean_reversion": "عودة للمتوسط",
            "breakout_retest": "اختراق + إعادة اختبار",
            "confluence": "Confluence متعدد",
        }.get(s, "قياسي")

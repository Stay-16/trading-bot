from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("Indicators")


def _sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0
    return sum(values[-period:]) / period


def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0
    k = 2.0 / (period + 1)
    result = sum(values[:period]) / period
    for v in values[period:]:
        result = v * k + result * (1 - k)
    return result


def _highest(values: list[float], period: int) -> float:
    return max(values[-period:]) if len(values) >= period and values else (max(values) if values else 0)


def _lowest(values: list[float], period: int) -> float:
    return min(values[-period:]) if len(values) >= period and values else (min(values) if values else 0)


# ── RSI 14 ───────────────────────────────────
def calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_g = gains / period
    avg_l = losses / period
    if avg_l == 0:
        return 100.0 if avg_g > 0 else 50.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


# ── ATR 14 ───────────────────────────────────
def calc_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    n = len(highs)
    if n < 2:
        return 0.0
    trs = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if not trs:
        return 0.0
    return sum(trs[-period:]) / min(period, len(trs))


# ── Ichimoku Cloud ───────────────────────────
def calc_ichimoku(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, float]:
    n = len(closes)
    if n < 52:
        return {"tenkan": 0, "kijun": 0, "senkou_a": 0, "senkou_b": 0, "chikou": 0, "cloud_green": 0}
    tenkan = (_highest(highs, 9) + _lowest(lows, 9)) / 2
    kijun = (_highest(highs, 26) + _lowest(lows, 26)) / 2
    senkou_a = (tenkan + kijun) / 2
    senkou_b = (_highest(highs, 52) + _lowest(lows, 52)) / 2
    chikou = closes[-26] if n >= 26 else closes[-1]
    cloud_green = 1 if senkou_a > senkou_b else -1
    return {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b,
            "chikou": chikou, "cloud_green": cloud_green}


# ── ADX + DI+ / DI- ─────────────────────────
def calc_adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> dict[str, float]:
    n = len(highs)
    if n < period + 1:
        return {"adx": 25.0, "di_plus": 20.0, "di_minus": 20.0}
    tr_list: list[float] = []
    dm_plus_list: list[float] = []
    dm_minus_list: list[float] = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        dm_plus = up_move if up_move > down_move and up_move > 0 else 0
        dm_minus = down_move if down_move > up_move and down_move > 0 else 0
        dm_plus_list.append(dm_plus)
        dm_minus_list.append(dm_minus)
    if not tr_list:
        return {"adx": 25.0, "di_plus": 20.0, "di_minus": 20.0}
    use = min(period, len(tr_list))
    atr_val = sum(tr_list[-use:]) / use
    if atr_val == 0:
        return {"adx": 25.0, "di_plus": 20.0, "di_minus": 20.0}
    di_plus = (sum(dm_plus_list[-use:]) / use) / atr_val * 100
    di_minus = (sum(dm_minus_list[-use:]) / use) / atr_val * 100
    dx = abs(di_plus - di_minus) / (di_plus + di_minus) * 100 if (di_plus + di_minus) > 0 else 0
    adx = _ema([dx] * period + [dx], period) if period > 0 else dx
    return {"adx": round(adx, 2), "di_plus": round(di_plus, 2), "di_minus": round(di_minus, 2)}


# ── On Balance Volume (OBV) ──────────────────
def calc_obv(closes: list[float], volumes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0
    obv = 0.0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i] if i < len(volumes) else 0
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i] if i < len(volumes) else 0
    return obv


# ── Volume Profile (POC, VAH, VAL) ──────────
def calc_volume_profile(highs: list[float], lows: list[float], volumes: list[float],
                        num_bins: int = 12) -> dict[str, float]:
    if not highs or not lows:
        return {"poc": 0, "vah": 0, "val": 0}
    high = max(highs)
    low = min(lows)
    if high == low:
        return {"poc": high, "vah": high, "val": high}
    bin_size = (high - low) / num_bins
    bins: list[dict] = [{"low": low + i * bin_size, "high": low + (i + 1) * bin_size, "vol": 0.0} for i in range(num_bins)]
    for i in range(min(len(highs), len(lows), len(volumes))):
        mid = (highs[i] + lows[i]) / 2
        idx = min(int((mid - low) / bin_size), num_bins - 1)
        bins[idx]["vol"] += volumes[i] if volumes[i] else 0
    bins.sort(key=lambda b: b["vol"], reverse=True)
    poc = (bins[0]["low"] + bins[0]["high"]) / 2 if bins else high
    total_vol = sum(b["vol"] for b in bins)
    if total_vol == 0:
        return {"poc": poc, "vah": high, "val": low}
    sorted_bins = sorted(bins, key=lambda b: b["low"])
    cum_vol = 0.0
    vah = high
    val = low
    for b in sorted_bins:
        cum_vol += b["vol"]
        if cum_vol >= total_vol * 0.7:
            vah = b["high"]
            break
    cum_vol = 0.0
    for b in reversed(sorted_bins):
        cum_vol += b["vol"]
        if cum_vol >= total_vol * 0.7:
            val = b["low"]
            break
    return {"poc": round(poc, 5), "vah": round(vah, 5), "val": round(val, 5)}

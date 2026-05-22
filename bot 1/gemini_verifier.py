from __future__ import annotations

import logging
import os
import tempfile
from io import BytesIO
from typing import Optional

import mplfinance as mpf
import pandas as pd
from google import genai
from google.genai import types as genai_types
from PIL import Image

from bot_algorithms import Candle

log = logging.getLogger("GeminiVerifier")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "Open": [c.open for c in candles],
            "High": [c.high for c in candles],
            "Low": [c.low for c in candles],
            "Close": [c.close for c in candles],
            "Volume": [c.volume for c in candles],
        }
    )
    now = pd.Timestamp.now()
    df.index = pd.date_range(end=now, periods=len(candles), freq="min")
    return df


def generate_chart_image(candles: list[Candle], symbol: str, title: str = "") -> bytes:
    if len(candles) < 10:
        candles = candles * 10
        candles = candles[:60]

    df = _candles_to_df(candles)

    ema9 = df["Close"].ewm(span=9).mean()
    ema21 = df["Close"].ewm(span=21).mean()
    mid = df["Close"].rolling(20).mean()
    std = df["Close"].rolling(20).std()
    bb_upper = mid + 2 * std
    bb_lower = mid - 2 * std

    extra = [
        mpf.make_addplot(ema9, color="#2196F3", width=0.7, label="EMA 9"),
        mpf.make_addplot(ema21, color="#FF9800", width=0.7, label="EMA 21"),
        mpf.make_addplot(bb_upper, color="#4CAF50", width=0.5, linestyle="dashed", label="BB Upper"),
        mpf.make_addplot(bb_lower, color="#F44336", width=0.5, linestyle="dashed", label="BB Lower"),
    ]

    vol = mpf.make_addplot(df["Volume"], panel=1, color="#607D8B", width=0.6, label="Volume")

    mc = mpf.make_marketcolors(
        up="#26A69A", down="#EF5350", edge="inherit", wick="inherit", volume="inherit"
    )
    sty = mpf.make_mpf_style(
        marketcolors=mc,
        gridstyle="",
        y_on_right=False,
        facecolor="#1a1a2e",
        figcolor="#1a1a2e",
        rc={
            "text.color": "#e0e0e0",
            "axes.labelcolor": "#e0e0e0",
            "axes.facecolor": "#16213e",
            "axes.edgecolor": "#2a2a4a",
        },
    )

    buf = BytesIO()
    fig, axes = mpf.plot(
        df,
        type="candle",
        style=sty,
        addplot=extra + [vol],
        volume=True,
        xrotation=0,
        figsize=(12, 7),
        panel_ratios=(4, 1),
        tight_layout=True,
        returnfig=True,
    )

    title_txt = title or f"{symbol} — {len(candles)} candles"
    axes[0].set_title(title_txt, color="#e0e0e0", fontsize=11, fontweight="bold")
    axes[0].legend(loc="upper left", fontsize=7, labelcolor="#e0e0e0")
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#1a1a2e")
    buf.seek(0)
    return buf.read()


def _build_technical_report(signal, candles: list[Candle], symbol: str) -> str:
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    price = closes[-1] if closes else 0

    report = f"""Symbol: {symbol}
Current Price: {price}
Signal Direction: {signal.direction}
Signal Score: {signal.score}/38
Signal Confidence: {signal.confidence:.1f}%
Trade Size: ${signal.trade_size:.2f}

Technical Indicators:
• RSI (14): {_calc_rsi(closes):.1f}
• ADX: {_calc_adx(highs, lows, closes):.1f}
• ATR: {_calc_atr(highs, lows, closes):.5f}
• EMA 9: {_calc_ema(closes, 9):.5f}
• EMA 21: {_calc_ema(closes, 21):.5f}
• Candle Count: {len(candles)}

Signal Reasons:
"""
    for i, r in enumerate(signal.reasons[:8], 1):
        report += f"  {i}. {r}\n"

    if signal.warnings:
        report += "\nWarnings:\n"
        for w in signal.warnings[:3]:
            report += f"  ⚠ {w}\n"

    return report


async def analyze_with_gemini(
    image_bytes: bytes, technical_report: str
) -> tuple[str, str]:
    if not GEMINI_API_KEY:
        return "NO_KEY", "GEMINI_API_KEY not set in .env"

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        chart_img = Image.open(BytesIO(image_bytes))

        prompt = f"""Analyze this trade setup.

TECHNICAL DATA:
{technical_report}

INSTRUCTIONS:
1. Visually examine the chart image for Price Action (support/resistance, trendlines, candlestick patterns).
2. Cross-check the visual patterns against the numerical technical data.
3. If the visual analysis CONTRADICTS the numerical signal, or if risk looks too high -> respond CANCEL.
4. If both visual AND numerical agree -> respond CONFIRMED with a detailed Arabic Telegram message.

RESPONSE FORMAT (strict):
First line must be either:
"🔴 DECISION: CANCEL" (if signal is rejected)
or
"🟢 DECISION: CONFIRMED" (if signal is accepted)

Then provide analysis in Arabic."""

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[chart_img, prompt],
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1024,
            ),
        )

        text = response.text.strip()
        decision = "CANCEL"
        if "CONFIRMED" in text and "CANCEL" not in text.split("\n")[0]:
            decision = "CONFIRMED"
        return decision, text

    except Exception as e:
        log.error("Gemini API error: %s", e)
        return "ERROR", f"Gemini API error: {e}"


def _calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / period / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def _calc_adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < period * 2:
        return 25.0
    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0.0)
        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0.0)
    if not tr_list or sum(tr_list[-period:]) == 0:
        return 25.0
    atr = sum(tr_list[-period:]) / period
    pdi = (sum(plus_dm[-period:]) / period) / atr * 100
    ndi = (sum(minus_dm[-period:]) / period) / atr * 100
    dx = abs(pdi - ndi) / (pdi + ndi) * 100 if (pdi + ndi) > 0 else 0
    return dx


def _calc_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    trs = []
    for i in range(1, min(len(closes), period + 1)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


def _calc_ema(closes: list[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

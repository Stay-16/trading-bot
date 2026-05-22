from __future__ import annotations

import logging
import os
import time
from io import BytesIO
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf
import pandas as pd
from PIL import Image

from bot_algorithms import Candle

log = logging.getLogger("GeminiVerifier")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ── OHLC → DataFrame ─────────────────────────────
def _candles_to_ohlc(candles: list[Candle]) -> list[dict]:
    now = int(time.time())
    return [
        {
            "Time": now - (len(candles) - i) * 60,
            "Open": c.open,
            "High": c.high,
            "Low": c.low,
            "Close": c.close,
            "Volume": c.volume,
        }
        for i, c in enumerate(candles)
    ]


def _ohlc_to_df(ohlc: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(ohlc)
    df["Time"] = pd.to_datetime(df["Time"], unit="s")
    df.set_index("Time", inplace=True)
    return df


# ── توليد الشارت (سريع، بدون متصفح) ──────────────
def generate_fast_matplotlib_chart(
    ohlc_data: list[dict],
    asset_name: str,
    output_path: Optional[str] = None,
) -> Optional[str]:
    try:
        if len(ohlc_data) < 5:
            ohlc_data = ohlc_data * 10
            ohlc_data = ohlc_data[:60]

        df = _ohlc_to_df(ohlc_data)

        mc = mpf.make_marketcolors(
            up="#26A69A", down="#EF5350", edge="inherit", wick="inherit", volume="in"
        )
        s = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            gridstyle="--",
            facecolor="#1a1a2e",
            figcolor="#1a1a2e",
        )

        if not output_path:
            output_path = f"chart_{asset_name.replace('/', '_')}_{int(time.time())}.png"

        mpf.plot(
            df,
            type="candle",
            style=s,
            title=f"\n{asset_name}",
            savefig=output_path,
            figsize=(12, 6),
            volume=True,
        )
        log.info("Chart generated: %s", output_path)
        return output_path
    except Exception as e:
        log.error("Chart generation failed: %s", e)
        return None


# ── واجهة التوافق مع Candle objects ──────────────
def generate_chart_image(candles: list[Candle], symbol: str, title: str = "") -> bytes:
    """يحول Candle → OHLC → شارت → يعيد bytes"""
    ohlc = _candles_to_ohlc(candles)
    path = generate_fast_matplotlib_chart(ohlc, symbol)
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        try:
            os.remove(path)
        except Exception:
            pass
        return data
    return b""


# ── بناء التقرير الفني ────────────────────────────
def _build_technical_report(sig, candles: list[Candle], symbol: str) -> str:
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    price = closes[-1] if closes else 0

    report = f"""Symbol: {symbol}
Current Price: {price}
Signal Direction: {sig.direction}
Signal Score: {sig.score}/38
Signal Confidence: {sig.confidence:.1f}%
Trade Size: ${sig.trade_size:.2f}

Technical Indicators:
- RSI (14): {_calc_rsi(closes):.1f}
- ADX: {_calc_adx(highs, lows, closes):.1f}
- ATR: {_calc_atr(highs, lows, closes):.5f}
- EMA 9: {_calc_ema(closes, 9):.5f}
- EMA 21: {_calc_ema(closes, 21):.5f}
- Candle Count: {len(candles)}

Signal Reasons:
"""
    for i, r in enumerate(sig.reasons[:8], 1):
        report += f"  {i}. {r}\n"

    if sig.warnings:
        report += "\nWarnings:\n"
        for w in sig.warnings[:3]:
            report += f"  ! {w}\n"

    return report


# ── إرسال لـ Gemini ──────────────────────────────
async def analyze_with_gemini(
    image_bytes: bytes, technical_report: str
) -> tuple[str, str]:
    if not GEMINI_API_KEY:
        return "NO_KEY", "GEMINI_API_KEY not set in .env"

    try:
        from google import genai as _genai
        from google.genai import types as _types

        client = _genai.Client(api_key=GEMINI_API_KEY)
        chart_img = Image.open(BytesIO(image_bytes))

        system_instruction = (
            "أنت خبير محترف ومسؤول إدارة المخاطر في أسواق الخيارات الثنائية (Binary Options) على منصة Quotex.\n"
            "وظيفتك الأساسية هي مراجعة إشارات بوت التداول ومطابقتها بصرياً مع شارت الشموع اليابانية المولد محلياً والمرفق لك.\n"
            "تأمل بنية الشموع (Price Action): ابحث عن القمم والقيعان اللحظية، اتجاه الزخم، طول ذيول الشموع (الرفض السعري)، ونماذج الشموع الانعكاسية.\n"
            "إذا كانت مؤشرات البوت الرقمية تعطي إشارة بيع (PUT) بينما الشموع الأخيرة تظهر صعوداً اندفاعياً قوياً جداً وبدون ذيول علوية، "
            "أو إذا كانت نسبة نجاح الصفقة المتوقعة بناءً على دمج (الأرقام + الشارت البصري) أقل من 75%، قم بإلغاء الصفقة لحماية الحساب.\n\n"
            "قواعد الرد الإلزامية الصارمة:\n"
            "- في حالة الإلغاء: يجب أن تبدأ ردك بعبارة '🔴 DECISION: CANCEL' مع ذكر السبب باختصار في سطر واحد فقط.\n"
            "- في حالة التأكيد والموافقة: يجب أن تبدأ ردك بعبارة '🟢 DECISION: CONFIRMED' ثم صغ رسالة تداول عربية منسقة جاهزة للتليجرام مباشرة."
        )

        user_prompt = f"""
        الرجاء مراجعة الصفقة ومطابقة المعطيات الرقمية مع الشارت البصري المولد محلياً:

        📊 مؤشرات البوت الرقمية:
        {technical_report}

        إذا كانت الصفقة قوية ومتوافقة (CONFIRMED)، صغ الرسالة لتشمل:
        - نوع الإشارة (شراء CALL / بيع PUT) والزوج المالي.
        - نسبة نجاح الذكاء الاصطناعي الإجمالية (AI Success Rate).
        - ملخص تحليل سلوك السعر البصري (AI Price Action Brief).
        - التوصية الفنية المعتمدة ووقت انتهاء الصفقة (Duration).
        """

        log.info("Sending to Gemini (%s)...", GEMINI_MODEL)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[chart_img, user_prompt],
            config=_types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,
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


# ── دالة مركزية متكاملة ──────────────────────────
def verify_and_send_signal(
    asset_name: str, raw_ohlc_data: list[dict], technical_signals_text: str
):
    """
    الدالة المركزية فائقة السرعة:
    1. توليد الشارت محلياً (matplotlib)
    2. إرسال لـ Gemini
    3. إرسال النتيجة للتليجرام
    """
    import asyncio

    start = time.time()
    log.info("Processing %s...", asset_name)

    chart_file = generate_fast_matplotlib_chart(raw_ohlc_data, asset_name)
    if not chart_file:
        log.error("Chart generation failed")
        return

    result = asyncio.run(analyze_with_gemini(chart_file, technical_signals_text))

    if not result or result[0] == "ERROR":
        log.warning("Gemini failed, signal blocked")
        return

    decision, ai_text = result

    if "CANCEL" in ai_text:
        log.info("CANCEL: %s", ai_text[:100])
    else:
        log.info("CONFIRMED - sending to Telegram")
        _send_to_telegram(ai_text, chart_file)

    elapsed = time.time() - start
    log.info("Total: %.2f seconds", elapsed)


def _send_to_telegram(caption_text: str, image_path: str):
    if not _TELEGRAM_BOT_TOKEN or not _TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials not configured")
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendPhoto"
        with open(image_path, "rb") as photo_file:
            payload = {
                "chat_id": _TELEGRAM_CHAT_ID,
                "caption": caption_text,
                "parse_mode": "Markdown",
            }
            files = {"photo": photo_file}
            resp = requests.post(url, data=payload, files=files)
        if resp.status_code == 200:
            log.info("Signal sent to Telegram")
        else:
            log.warning("Telegram error: %s", resp.text)
    except Exception as e:
        log.error("Telegram send error: %s", e)


# ── Indicators mini (standalone) ─────────────────
def _calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains = losses = 0.0
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
    trs, pds, nds = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pds.append(up if up > dn and up > 0 else 0.0)
        nds.append(dn if dn > up and dn > 0 else 0.0)
    if not trs or sum(trs[-period:]) == 0:
        return 25.0
    atr = sum(trs[-period:]) / period
    pdi = (sum(pds[-period:]) / period) / atr * 100
    ndi = (sum(nds[-period:]) / period) / atr * 100
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
    mult = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = (p - ema) * mult + ema
    return ema

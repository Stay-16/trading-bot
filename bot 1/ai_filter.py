from __future__ import annotations

import logging
import os
import time
from io import BytesIO
from typing import Optional

from PIL import Image
from google import genai
from google.genai import types as genai_types

from gemini_verifier import generate_chart_image as _fallback_chart, _build_technical_report as _fallback_report

log = logging.getLogger("AIFilter")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Selenium (اختياري — يتطلب تثبيت chromium)
_SELENIUM_AVAILABLE = False
_SELENIUM = None
_CHROME_OPTS = None
try:
    import selenium.webdriver as _SELENIUM
    from selenium.webdriver.chrome.options import Options as _CHROME_OPTS
    _SELENIUM_AVAILABLE = True
except Exception:
    pass


def _get_quotex_url(asset: str) -> str:
    """يبني رابط Quotex للزوج المطلوب"""
    base = "https://qxbroker.com/ar/demo-trade/chart"
    sym = asset.replace("/", "_").upper()
    return f"{base}/{sym}"


async def screenshot_quotex(asset: str, output_dir: str = None) -> Optional[str]:
    """يلتقط صورة شارت Quotex باستخدام Selenium headless. يعيد None إذا فشل."""
    if not _SELENIUM_AVAILABLE:
        log.warning("Selenium غير متاح. جرب: pip install selenium")
        return None

    if not output_dir:
        output_dir = os.getenv("TEMP", "/tmp")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"quotex_{asset.replace('/', '_')}_{int(time.time())}.png")

    opts = _CHROME_OPTS()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")

    profile_dir = os.path.join(os.getcwd(), "chrome_quotex_profile")
    opts.add_argument(f"--user-data-dir={profile_dir}")

    driver = None
    try:
        driver = _SELENIUM.Chrome(options=opts)
        url = _get_quotex_url(asset)
        log.info("فتح %s", url)
        driver.get(url)
        time.sleep(5)
        driver.save_screenshot(path)
        log.info("تم حفظ الصورة: %s", path)
        return path
    except Exception as e:
        log.warning("Selenium screenshot فشل: %s", e)
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


async def analyze_with_gemini(
    image_bytes: bytes, technical_report: str
) -> tuple[str, str]:
    """يرسل صورة + تقرير فني لـ Gemini ويتلقى قرار CONFIRMED/CANCEL"""
    return await _analyze_gemini_core(image_bytes, technical_report)


async def analyze_quotex_signal(asset: str, technical_report: str) -> tuple[str, str, Optional[str]]:
    """
    دالة متكاملة:
    1. يحاول تصوير Quotex عبر Selenium فقط إذا USE_SELENIUM=true
    2. إذا فشل أو غير مفعل → يستخدم fallback chart من gemini_verifier
    3. يرسل لـ Gemini
    يعيد (decision, gemini_text, screenshot_path)
    """
    image_path = None
    image_bytes = None

    # المحاولة الأولى: Selenium (فقط إذا مفعل يدوياً)
    use_selenium = os.getenv("USE_SELENIUM", "false").lower() == "true"
    if use_selenium and _SELENIUM_AVAILABLE:
        log.info("USE_SELENIUM=true — تصوير Quotex عبر Selenium")
        screenshot_path = await screenshot_quotex(asset)
        if screenshot_path and os.path.exists(screenshot_path):
            image_path = screenshot_path
            with open(screenshot_path, "rb") as f:
                image_bytes = f.read()
    else:
        log.info("USE_SELENIUM مطفأ — استخدام fallback (matplotlib chart)")

    # المحاولة الثانية: Fallback (matplotlib chart)
    if image_bytes is None:
        log.info("استخدام matplotlib chart (fallback)")
        from bot_algorithms import Candle
        candles = []
        try:
            import main as _m
            if hasattr(_m, 'B') and _m.B.pipeline:
                candles = _m.B.pipeline.buffer.candles
        except Exception:
            pass
        if candles:
            try:
                png = _fallback_chart(candles, asset, title=f"{asset} — AI Filter")
                image_bytes = png
            except Exception as e:
                log.warning("Fallback chart فشل: %s", e)
                return "ERROR", "فشل التقاط الشارت", None

    if image_bytes is None:
        return "ERROR", "لا توجد صورة شارت", None

    decision, text = await _analyze_gemini_core(image_bytes, technical_report)
    return decision, text, image_path


async def _analyze_gemini_core(image_bytes: bytes, technical_report: str) -> tuple[str, str]:
    """النواة المشتركة لإرسال الصورة + التقرير لـ Gemini"""
    if not GEMINI_API_KEY:
        return "NO_KEY", "GEMINI_API_KEY not set in .env"

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        chart_img = Image.open(BytesIO(image_bytes))

        system_instruction = (
            "أنت خبير محترف في إدارة المخاطر وتحليل سلوك السعر (Price Action) لمنصة Quotex.\n"
            "مهمتك هي مراجعة إشارات البوت ومطابقتها بصرياً مع الشارت المرفق.\n"
            "انظر إلى الشموع اليابانية: هل هناك رفض سعري (Wicks)، دعم/مقاومة بصرية، زخم؟\n"
            "الخيارات الثنائية تعتمد على حركة الشموع اللحظية — الغِ الصفقة فوراً إذا رأيت خطورة.\n\n"
            "قواعد الرد:\n"
            "- إذا الصفقة خطيرة: ابدأ بـ '🔴 DECISION: CANCEL' مع سبب مختصر.\n"
            "- إذا الصفقة ممتازة: ابدأ بـ '🟢 DECISION: CONFIRMED' مع رسالة تداول عربية احترافية."
        )

        user_prompt = f"""
        راجع البيانات الفنية وطابقها مع الشارت المرفق:

        📊 المؤشرات الرقمية:
        {technical_report}

        إذا CONFIRMED، نسق رسالة التليجرام:
        - نوع الإشارة (CALL/PUT) والزوج
        - AI Success Rate
        - تحليل بصري لسلوك السعر
        - إدارة المخاطر
        """

        log.info("إرسال لـ Gemini (%s)...", GEMINI_MODEL)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[chart_img, user_prompt],
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
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

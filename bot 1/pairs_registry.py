"""
=============================================================
  سجل الأزواج الكامل لـ Quotex + محدد الزوج الذكي
  Complete Quotex Pairs Registry + Smart Pair Selector

  المكونات:
  1. QUOTEX_PAIRS     — جميع أزواج Quotex (70+ زوج)
  2. PairInfo         — بيانات كل زوج
  3. PairSelector     — يختار أفضل زوج تلقائياً
  4. PairScanner      — يمسح كل الأزواج ويرتبها
=============================================================
"""

from dataclasses import dataclass, field
from typing import Optional
import os


# ─────────────────────────────────────────────
#  هيكل بيانات الزوج
# ─────────────────────────────────────────────

@dataclass
class PairInfo:
    display_name:    str          # "EUR/USD"
    quotex_symbol:   str          # "EURUSD-OTC" كما تطلبه pyquotex
    tv_symbol:       str          # "EURUSD" لـ TradingView
    tv_screener:     str          # "forex" / "crypto" / "america"
    tv_exchange:     str          # "OANDA" / "FX_IDC" / "NASDAQ"
    pair_type:       str          # "otc" / "regular" / "crypto" / "stock" / "commodity"
    category:        str          # "major" / "minor" / "exotic" / "crypto" ...
    min_payout:      float = 75.0 # الحد الأدنى لقبول الصفقة
    typical_spread:  float = 0.0  # متوسط الفارق
    active:          bool  = True  # هل يعمل حالياً
    notes:           str   = ""


# ─────────────────────────────────────────────
#  جميع أزواج Quotex — 70+ زوج
# ─────────────────────────────────────────────

QUOTEX_PAIRS: dict[str, PairInfo] = {

    # ══════════════════════════════════════════
    #  عملات رئيسية — OTC (الأفضل للتداول الليلي وعطل نهاية الأسبوع)
    # ══════════════════════════════════════════
    "EURUSD_otc": PairInfo(
        display_name="EUR/USD OTC", quotex_symbol="EURUSD-OTC",
        tv_symbol="EURUSD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="major", min_payout=80.0,
        notes="الأكثر سيولة — إشارات أوضح"
    ),
    "GBPUSD_otc": PairInfo(
        display_name="GBP/USD OTC", quotex_symbol="GBPUSD-OTC",
        tv_symbol="GBPUSD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="major", min_payout=80.0,
        notes="تقلب عالٍ — إشارات قوية"
    ),
    "USDJPY_otc": PairInfo(
        display_name="USD/JPY OTC", quotex_symbol="USDJPY-OTC",
        tv_symbol="USDJPY", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="major", min_payout=80.0,
    ),
    "USDCHF_otc": PairInfo(
        display_name="USD/CHF OTC", quotex_symbol="USDCHF-OTC",
        tv_symbol="USDCHF", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="major", min_payout=78.0,
    ),
    "AUDUSD_otc": PairInfo(
        display_name="AUD/USD OTC", quotex_symbol="AUDUSD-OTC",
        tv_symbol="AUDUSD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="major", min_payout=80.0,
    ),
    "NZDUSD_otc": PairInfo(
        display_name="NZD/USD OTC", quotex_symbol="NZDUSD-OTC",
        tv_symbol="NZDUSD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="major", min_payout=78.0,
    ),
    "USDCAD_otc": PairInfo(
        display_name="USD/CAD OTC", quotex_symbol="USDCAD-OTC",
        tv_symbol="USDCAD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="major", min_payout=78.0,
    ),

    # ── Crosses OTC ───────────────────────────
    "EURJPY_otc": PairInfo(
        display_name="EUR/JPY OTC", quotex_symbol="EURJPY-OTC",
        tv_symbol="EURJPY", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=80.0,
        notes="تقلب عالٍ وإشارات واضحة"
    ),
    "EURGBP_otc": PairInfo(
        display_name="EUR/GBP OTC", quotex_symbol="EURGBP-OTC",
        tv_symbol="EURGBP", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=80.0,
    ),
    "EURCHF_otc": PairInfo(
        display_name="EUR/CHF OTC", quotex_symbol="EURCHF-OTC",
        tv_symbol="EURCHF", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "EURAUD_otc": PairInfo(
        display_name="EUR/AUD OTC", quotex_symbol="EURAUD-OTC",
        tv_symbol="EURAUD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=80.0,
    ),
    "EURCAD_otc": PairInfo(
        display_name="EUR/CAD OTC", quotex_symbol="EURCAD-OTC",
        tv_symbol="EURCAD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "EURNZD_otc": PairInfo(
        display_name="EUR/NZD OTC", quotex_symbol="EURNZD-OTC",
        tv_symbol="EURNZD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=80.0,
        notes="ظهر في الفيديو — payout عالٍ"
    ),
    "GBPJPY_otc": PairInfo(
        display_name="GBP/JPY OTC", quotex_symbol="GBPJPY-OTC",
        tv_symbol="GBPJPY", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=80.0,
        notes="تقلب عالٍ جداً — للمحترفين"
    ),
    "GBPCHF_otc": PairInfo(
        display_name="GBP/CHF OTC", quotex_symbol="GBPCHF-OTC",
        tv_symbol="GBPCHF", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "GBPAUD_otc": PairInfo(
        display_name="GBP/AUD OTC", quotex_symbol="GBPAUD-OTC",
        tv_symbol="GBPAUD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "GBPCAD_otc": PairInfo(
        display_name="GBP/CAD OTC", quotex_symbol="GBPCAD-OTC",
        tv_symbol="GBPCAD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "GBPNZD_otc": PairInfo(
        display_name="GBP/NZD OTC", quotex_symbol="GBPNZD-OTC",
        tv_symbol="GBPNZD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "AUDJPY_otc": PairInfo(
        display_name="AUD/JPY OTC", quotex_symbol="AUDJPY-OTC",
        tv_symbol="AUDJPY", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=80.0,
    ),
    "AUDCHF_otc": PairInfo(
        display_name="AUD/CHF OTC", quotex_symbol="AUDCHF-OTC",
        tv_symbol="AUDCHF", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "AUDCAD_otc": PairInfo(
        display_name="AUD/CAD OTC", quotex_symbol="AUDCAD-OTC",
        tv_symbol="AUDCAD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "AUDNZD_otc": PairInfo(
        display_name="AUD/NZD OTC", quotex_symbol="AUDNZD-OTC",
        tv_symbol="AUDNZD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "NZDJPY_otc": PairInfo(
        display_name="NZD/JPY OTC", quotex_symbol="NZDJPY-OTC",
        tv_symbol="NZDJPY", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "NZDCHF_otc": PairInfo(
        display_name="NZD/CHF OTC", quotex_symbol="NZDCHF-OTC",
        tv_symbol="NZDCHF", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=80.0,
        notes="ظهر في الفيديو"
    ),
    "NZDCAD_otc": PairInfo(
        display_name="NZD/CAD OTC", quotex_symbol="NZDCAD-OTC",
        tv_symbol="NZDCAD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "CADJPY_otc": PairInfo(
        display_name="CAD/JPY OTC", quotex_symbol="CADJPY-OTC",
        tv_symbol="CADJPY", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "CADCHF_otc": PairInfo(
        display_name="CAD/CHF OTC", quotex_symbol="CADCHF-OTC",
        tv_symbol="CADCHF", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),
    "CHFJPY_otc": PairInfo(
        display_name="CHF/JPY OTC", quotex_symbol="CHFJPY-OTC",
        tv_symbol="CHFJPY", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="minor", min_payout=78.0,
    ),

    # ── أزواج غريبة OTC ───────────────────────
    "USDPKR_otc": PairInfo(
        display_name="USD/PKR OTC", quotex_symbol="USDPKR-OTC",
        tv_symbol="USDPKR", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=85.0,
        notes="ظهر في الفيديو — payout عالٍ جداً"
    ),
    "USDIDR_otc": PairInfo(
        display_name="USD/IDR OTC", quotex_symbol="USDIDR-OTC",
        tv_symbol="USDIDR", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=88.0,
        notes="ظهر في الفيديو — payout 92% أحياناً"
    ),
    "USDDZD_otc": PairInfo(
        display_name="USD/DZD OTC", quotex_symbol="USDDZ-OTC",
        tv_symbol="USDDZ", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=85.0,
        notes="دينار جزائري"
    ),
    "USDEGP_otc": PairInfo(
        display_name="USD/EGP OTC", quotex_symbol="USDEGP-OTC",
        tv_symbol="USDEGP", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=85.0,
        notes="ظهر في الفيديو"
    ),
    "USDSGD_otc": PairInfo(
        display_name="USD/SGD OTC", quotex_symbol="USDSGD-OTC",
        tv_symbol="USDSGD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=80.0,
    ),
    "USDHKD_otc": PairInfo(
        display_name="USD/HKD OTC", quotex_symbol="USDHKD-OTC",
        tv_symbol="USDHKD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=78.0,
    ),
    "USDZAR_otc": PairInfo(
        display_name="USD/ZAR OTC", quotex_symbol="USDZAR-OTC",
        tv_symbol="USDZAR", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=80.0,
    ),
    "USDMXN_otc": PairInfo(
        display_name="USD/MXN OTC", quotex_symbol="USDMXN-OTC",
        tv_symbol="USDMXN", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=80.0,
    ),
    "USDBRL_otc": PairInfo(
        display_name="USD/BRL OTC", quotex_symbol="USDBRL-OTC",
        tv_symbol="USDBRL", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=82.0,
    ),
    "USDINR_otc": PairInfo(
        display_name="USD/INR OTC", quotex_symbol="USDINR-OTC",
        tv_symbol="USDINR", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=85.0,
        notes="ظهر في الفيديو"
    ),
    "USDPHP_otc": PairInfo(
        display_name="USD/PHP OTC", quotex_symbol="USDPHP-OTC",
        tv_symbol="USDPHP", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=82.0,
    ),
    "USDNGN_otc": PairInfo(
        display_name="USD/NGN OTC", quotex_symbol="USDNGN-OTC",
        tv_symbol="USDNGN", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=80.0,
    ),
    "USDARS_otc": PairInfo(
        display_name="USD/ARS OTC", quotex_symbol="USDARS-OTC",
        tv_symbol="USDARS", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=80.0,
    ),
    "USDBDT_otc": PairInfo(
        display_name="USD/BDT OTC", quotex_symbol="USDBDT-OTC",
        tv_symbol="USDBDT", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=80.0,
    ),
    "USDMXN_otc2": PairInfo(
        display_name="NZD/CAD OTC", quotex_symbol="NZDCAD-OTC",
        tv_symbol="NZDCAD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=78.0,
    ),
    "EURSGD_otc": PairInfo(
        display_name="EUR/SGD OTC", quotex_symbol="EURSGD-OTC",
        tv_symbol="EURSGD", tv_screener="forex", tv_exchange="FX_IDC",
        pair_type="otc", category="exotic", min_payout=78.0,
    ),

    # ══════════════════════════════════════════
    #  عملات رئيسية — Regular (أوقات السوق فقط)
    # ══════════════════════════════════════════
    "EURUSD": PairInfo(
        display_name="EUR/USD", quotex_symbol="EURUSD",
        tv_symbol="EURUSD", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="major", min_payout=75.0,
    ),
    "GBPUSD": PairInfo(
        display_name="GBP/USD", quotex_symbol="GBPUSD",
        tv_symbol="GBPUSD", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="major", min_payout=75.0,
    ),
    "USDJPY": PairInfo(
        display_name="USD/JPY", quotex_symbol="USDJPY",
        tv_symbol="USDJPY", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="major", min_payout=75.0,
    ),
    "AUDUSD": PairInfo(
        display_name="AUD/USD", quotex_symbol="AUDUSD",
        tv_symbol="AUDUSD", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="major", min_payout=75.0,
    ),
    "USDCAD": PairInfo(
        display_name="USD/CAD", quotex_symbol="USDCAD",
        tv_symbol="USDCAD", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="major", min_payout=75.0,
    ),
    "USDCHF": PairInfo(
        display_name="USD/CHF", quotex_symbol="USDCHF",
        tv_symbol="USDCHF", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="major", min_payout=75.0,
    ),
    "NZDUSD": PairInfo(
        display_name="NZD/USD", quotex_symbol="NZDUSD",
        tv_symbol="NZDUSD", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="major", min_payout=75.0,
    ),
    "EURJPY": PairInfo(
        display_name="EUR/JPY", quotex_symbol="EURJPY",
        tv_symbol="EURJPY", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "EURGBP": PairInfo(
        display_name="EUR/GBP", quotex_symbol="EURGBP",
        tv_symbol="EURGBP", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "EURCHF": PairInfo(
        display_name="EUR/CHF", quotex_symbol="EURCHF",
        tv_symbol="EURCHF", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "EURAUD": PairInfo(
        display_name="EUR/AUD", quotex_symbol="EURAUD",
        tv_symbol="EURAUD", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "GBPJPY": PairInfo(
        display_name="GBP/JPY", quotex_symbol="GBPJPY",
        tv_symbol="GBPJPY", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "GBPCHF": PairInfo(
        display_name="GBP/CHF", quotex_symbol="GBPCHF",
        tv_symbol="GBPCHF", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "AUDJPY": PairInfo(
        display_name="AUD/JPY", quotex_symbol="AUDJPY",
        tv_symbol="AUDJPY", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "AUDCHF": PairInfo(
        display_name="AUD/CHF", quotex_symbol="AUDCHF",
        tv_symbol="AUDCHF", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),
    "CADJPY": PairInfo(
        display_name="CAD/JPY", quotex_symbol="CADJPY",
        tv_symbol="CADJPY", tv_screener="forex", tv_exchange="OANDA",
        pair_type="regular", category="minor", min_payout=75.0,
    ),

    # ══════════════════════════════════════════
    #  كريبتو — OTC
    # ══════════════════════════════════════════
    "BTCUSD_otc": PairInfo(
        display_name="BTC/USD OTC", quotex_symbol="BTCUSD-OTC",
        tv_symbol="BTCUSD", tv_screener="crypto", tv_exchange="BINANCE",
        pair_type="crypto", category="crypto", min_payout=75.0,
        notes="تقلب شديد — استراتيجية مختلفة"
    ),
    "ETHUSD_otc": PairInfo(
        display_name="ETH/USD OTC", quotex_symbol="ETHUSD-OTC",
        tv_symbol="ETHUSD", tv_screener="crypto", tv_exchange="BINANCE",
        pair_type="crypto", category="crypto", min_payout=75.0,
    ),
    "LTCUSD_otc": PairInfo(
        display_name="LTC/USD OTC", quotex_symbol="LTCUSD-OTC",
        tv_symbol="LTCUSD", tv_screener="crypto", tv_exchange="BINANCE",
        pair_type="crypto", category="crypto", min_payout=75.0,
    ),
    "XRPUSD_otc": PairInfo(
        display_name="XRP/USD OTC", quotex_symbol="XRPUSD-OTC",
        tv_symbol="XRPUSD", tv_screener="crypto", tv_exchange="BINANCE",
        pair_type="crypto", category="crypto", min_payout=75.0,
    ),

    # ══════════════════════════════════════════
    #  سلع — OTC
    # ══════════════════════════════════════════
    "XAUUSD_otc": PairInfo(
        display_name="Gold/USD OTC", quotex_symbol="XAUUSD-OTC",
        tv_symbol="XAUUSD", tv_screener="cfd", tv_exchange="OANDA",
        pair_type="commodity", category="commodity", min_payout=78.0,
        notes="الذهب — إشارات ترند قوية"
    ),
    "XAGUSD_otc": PairInfo(
        display_name="Silver/USD OTC", quotex_symbol="XAGUSD-OTC",
        tv_symbol="XAGUSD", tv_screener="cfd", tv_exchange="OANDA",
        pair_type="commodity", category="commodity", min_payout=75.0,
        notes="الفضة"
    ),
    "XBRUSD_otc": PairInfo(
        display_name="Brent Oil OTC", quotex_symbol="XBRUSD-OTC",
        tv_symbol="UKOIL", tv_screener="cfd", tv_exchange="OANDA",
        pair_type="commodity", category="commodity", min_payout=75.0,
        notes="نفط برنت"
    ),
    "XTIUSD_otc": PairInfo(
        display_name="WTI Oil OTC", quotex_symbol="XTIUSD-OTC",
        tv_symbol="USOIL", tv_screener="cfd", tv_exchange="OANDA",
        pair_type="commodity", category="commodity", min_payout=75.0,
        notes="نفط خام WTI"
    ),

    # ══════════════════════════════════════════
    #  أسهم — OTC
    # ══════════════════════════════════════════
    "AAPL_otc": PairInfo(
        display_name="Apple OTC", quotex_symbol="AAPL-OTC",
        tv_symbol="AAPL", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
    "GOOGL_otc": PairInfo(
        display_name="Google OTC", quotex_symbol="GOOGL-OTC",
        tv_symbol="GOOGL", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
    "AMZN_otc": PairInfo(
        display_name="Amazon OTC", quotex_symbol="AMZN-OTC",
        tv_symbol="AMZN", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
    "TSLA_otc": PairInfo(
        display_name="Tesla OTC", quotex_symbol="TSLA-OTC",
        tv_symbol="TSLA", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
    "MSFT_otc": PairInfo(
        display_name="Microsoft OTC", quotex_symbol="MSFT-OTC",
        tv_symbol="MSFT", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
    "META_otc": PairInfo(
        display_name="Meta OTC", quotex_symbol="META-OTC",
        tv_symbol="META", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
    "NFLX_otc": PairInfo(
        display_name="Netflix OTC", quotex_symbol="NFLX-OTC",
        tv_symbol="NFLX", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
    "NVDA_otc": PairInfo(
        display_name="NVIDIA OTC", quotex_symbol="NVDA-OTC",
        tv_symbol="NVDA", tv_screener="america", tv_exchange="NASDAQ",
        pair_type="stock", category="stock", min_payout=75.0,
    ),
}

# ── فهارس سريعة ───────────────────────────────
OTC_PAIRS      = {k: v for k, v in QUOTEX_PAIRS.items() if v.pair_type == "otc"}
REGULAR_PAIRS  = {k: v for k, v in QUOTEX_PAIRS.items() if v.pair_type == "regular"}
FOREX_PAIRS    = {k: v for k, v in QUOTEX_PAIRS.items() if v.tv_screener == "forex"}
CRYPTO_PAIRS   = {k: v for k, v in QUOTEX_PAIRS.items() if v.pair_type == "crypto"}
STOCK_PAIRS    = {k: v for k, v in QUOTEX_PAIRS.items() if v.pair_type == "stock"}
COMMODITY_PAIRS= {k: v for k, v in QUOTEX_PAIRS.items() if v.pair_type == "commodity"}
MAJOR_PAIRS    = {k: v for k, v in QUOTEX_PAIRS.items() if v.category == "major"}
EXOTIC_PAIRS   = {k: v for k, v in QUOTEX_PAIRS.items() if v.category == "exotic"}

# أزواج مميزة من الفيديو
VIDEO_PAIRS = [
    "EURUSD_otc", "EURGBP_otc", "EURNZD_otc",
    "USDPKR_otc", "USDIDR_otc", "USDINR_otc",
    "NZDCHF_otc", "AUDUSD_otc", "GBPUSD_otc",
]


# ─────────────────────────────────────────────
#  دوال مساعدة
# ─────────────────────────────────────────────

def get_pair(key: str) -> Optional[PairInfo]:
    """جلب معلومات زوج بمفتاحه"""
    # جرب مباشرة
    if key in QUOTEX_PAIRS:
        return QUOTEX_PAIRS[key]
    # جرب بصيغ مختلفة
    for variant in [
        key.lower(), key.upper(),
        key.replace("-", "_"), key.replace("/", ""),
        key.replace("/", "").lower() + "_otc",
    ]:
        if variant in QUOTEX_PAIRS:
            return QUOTEX_PAIRS[variant]
    return None


def get_by_quotex_symbol(quotex_symbol: str) -> Optional[PairInfo]:
    """البحث بـ quotex_symbol"""
    for info in QUOTEX_PAIRS.values():
        if info.quotex_symbol.upper() == quotex_symbol.upper():
            return info
    return None


def list_pairs(
    pair_type: Optional[str] = None,
    category:  Optional[str] = None,
    min_payout: float = 0.0,
    active_only: bool = True,
) -> list[tuple[str, PairInfo]]:
    """قائمة الأزواج مع فلاتر"""
    result = []
    for key, info in QUOTEX_PAIRS.items():
        if active_only and not info.active:
            continue
        if pair_type and info.pair_type != pair_type:
            continue
        if category and info.category != category:
            continue
        if info.min_payout < min_payout:
            continue
        result.append((key, info))
    return result


# ─────────────────────────────────────────────
#  محدد الزوج الذكي
# ─────────────────────────────────────────────

@dataclass
class PairScore:
    key:         str
    info:        PairInfo
    payout:      float = 0.0
    signal_score: int  = 0
    total_score: float = 0.0
    reason:      str   = ""


class PairSelector:
    """
    يختار أفضل زوج للتداول تلقائياً بناءً على:
    - payout المباشر من Quotex
    - قوة الإشارة التقنية
    - فئة الزوج وموثوقيته
    """

    # أوزان التقييم
    W_PAYOUT   = 0.50   # 50% أهمية للـ payout
    W_SIGNAL   = 0.35   # 35% أهمية للإشارة التقنية
    W_CATEGORY = 0.15   # 15% أهمية لفئة الزوج

    # مكافأة الفئة
    CATEGORY_BONUS = {
        "major":     1.0,
        "minor":     0.9,
        "exotic":    1.1,   # exotic payout عادة أعلى
        "crypto":    0.7,
        "stock":     0.8,
        "commodity": 0.85,
    }

    def __init__(self,
                 preferred_types: list[str] = None,
                 min_payout: float = 80.0,
                 max_pairs_to_scan: int = 15):
        self.preferred_types   = preferred_types or ["otc"]
        self.min_payout        = min_payout
        self.max_pairs_to_scan = max_pairs_to_scan

    def score_pair(self,
                   key: str,
                   info: PairInfo,
                   payout: float,
                   signal_score: int = 0) -> PairScore:
        """يحسب نقاط الزوج"""
        # نقاط الـ payout (0-100 مطبعة على 0-1)
        payout_norm = max(0, (payout - 75) / 25)  # 75% = 0، 100% = 1

        # نقاط الإشارة (0-18 مطبعة على 0-1)
        signal_norm = min(signal_score / 18, 1.0)

        # مكافأة الفئة
        cat_bonus = self.CATEGORY_BONUS.get(info.category, 0.8)

        total = (
            payout_norm  * self.W_PAYOUT +
            signal_norm  * self.W_SIGNAL +
            cat_bonus    * self.W_CATEGORY
        )

        reason = (
            f"payout={payout:.0f}% "
            f"signal={signal_score}/18 "
            f"cat={info.category}"
        )

        return PairScore(
            key=key, info=info,
            payout=payout, signal_score=signal_score,
            total_score=round(total, 4), reason=reason
        )

    def get_candidates(self) -> list[tuple[str, PairInfo]]:
        """يجلب الأزواج المرشحة للمسح"""
        candidates = list_pairs(
            pair_type  = None,
            min_payout = self.min_payout,
            active_only= True,
        )
        # فلتر حسب النوع المفضل
        if self.preferred_types:
            candidates = [
                (k, v) for k, v in candidates
                if v.pair_type in self.preferred_types
            ]
        return candidates[:self.max_pairs_to_scan]

    def rank(self,
             scored: list[PairScore],
             top_n: int = 5) -> list[PairScore]:
        """يرتب الأزواج ويُرجع أفضل N"""
        return sorted(scored, key=lambda x: x.total_score, reverse=True)[:top_n]


# ─────────────────────────────────────────────
#  ماسح الأزواج
# ─────────────────────────────────────────────

class PairScanner:
    """
    يمسح الأزواج المتاحة من Quotex ويحصل على:
    - الـ payout الحالي لكل زوج
    - بيانات شموع سريعة
    - يُرجع الأزواج مرتبة حسب الأفضلية
    
    يُستخدم عند بداية الجلسة لاختيار أفضل زوج
    """

    def __init__(self, connection, selector: PairSelector = None):
        self.conn     = connection
        self.selector = selector or PairSelector()

    async def get_payout(self, quotex_symbol: str) -> float:
        """
        يجلب الـ payout الحالي من Quotex.
        يجرب عدة طرق.
        """
        client = self.conn.client
        if not client:
            return 0.0

        payout_methods = [
            "get_payout",
            "get_payment",
            "get_profit_percent",
        ]
        for method_name in payout_methods:
            if not hasattr(client, method_name):
                continue
            try:
                result = await getattr(client, method_name)(quotex_symbol)
                if result:
                    payout = float(result) if not isinstance(result, dict) \
                             else float(result.get("payout",
                                        result.get("profit", 0)))
                    if 50 <= payout <= 100:
                        return payout
            except Exception:
                pass
        return 0.0

    async def scan(self,
                   fetch_payout: bool = True,
                   top_n: int = 5) -> list[PairScore]:
        """
        يمسح الأزواج المرشحة ويُرجع أفضل N.
        
        fetch_payout=False → استخدم min_payout الافتراضي (أسرع)
        fetch_payout=True  → اجلب الـ payout الفعلي (أدق)
        """
        import logging
        log = logging.getLogger("PairScanner")
        
        await self.conn.ensure_connected()
        candidates = self.selector.get_candidates()
        log.info("🔍 مسح %d زوج...", len(candidates))

        scored = []
        for key, info in candidates:
            payout = info.min_payout  # افتراضي
            if fetch_payout and self.conn.client:
                live_payout = await self.get_payout(info.quotex_symbol)
                if live_payout > 0:
                    payout = live_payout

            if payout < self.selector.min_payout:
                continue

            ps = self.selector.score_pair(key, info, payout)
            scored.append(ps)

        ranked = self.selector.rank(scored, top_n)
        for i, ps in enumerate(ranked, 1):
            log.info("  %d. %s — payout=%.0f%% score=%.3f",
                     i, ps.info.display_name, ps.payout, ps.total_score)
        return ranked

    async def best_pair(self) -> Optional[PairScore]:
        """يُرجع أفضل زوج واحد"""
        ranked = await self.scan(top_n=1)
        return ranked[0] if ranked else None


# ─────────────────────────────────────────────
#  دمج الأزواج مع data_layer
# ─────────────────────────────────────────────

def apply_pair_to_pipeline(pipeline, key: str) -> bool:
    """
    يطبق الزوج المختار على الـ pipeline.
    يُستخدم بعد PairScanner.best_pair()
    """
    info = get_pair(key)
    if not info:
        return False
    pipeline.data_settings.symbol         = info.quotex_symbol
    pipeline.stream.settings.symbol       = info.quotex_symbol
    pipeline.data_settings.payout         = info.min_payout
    return True


# ─────────────────────────────────────────────
#  تقرير سريع
# ─────────────────────────────────────────────

def print_pairs_summary():
    total    = len(QUOTEX_PAIRS)
    otc      = len(OTC_PAIRS)
    regular  = len(REGULAR_PAIRS)
    crypto   = len(CRYPTO_PAIRS)
    stocks   = len(STOCK_PAIRS)
    commodities = len(COMMODITY_PAIRS)
    high_pay = len([v for v in QUOTEX_PAIRS.values() if v.min_payout >= 85])

    print(f"""
╔══════════════════════════════════════╗
║      سجل أزواج Quotex الكامل        ║
╠══════════════════════════════════════╣
║  إجمالي الأزواج:     {total:<4}              ║
║  OTC (فوركس):        {otc:<4}              ║
║  Regular (فوركس):    {regular:<4}              ║
║  كريبتو:             {crypto:<4}              ║
║  أسهم:               {stocks:<4}              ║
║  سلع:                {commodities:<4}              ║
║  payout ≥ 85%:       {high_pay:<4}              ║
╚══════════════════════════════════════╝
""")


if __name__ == "__main__":
    print_pairs_summary()

    print("أزواج OTC الرئيسية (payout ≥ 80%):")
    high_otc = list_pairs(pair_type="otc", min_payout=80.0)
    for key, info in sorted(high_otc, key=lambda x: x[1].min_payout, reverse=True):
        print(f"  {info.display_name:<22} | {info.quotex_symbol:<18} | payout≥{info.min_payout:.0f}%"
              + (f" ← {info.notes}" if info.notes else ""))

    print(f"\nأزواج الفيديو:")
    for key in VIDEO_PAIRS:
        info = QUOTEX_PAIRS.get(key)
        if info:
            print(f"  ✓ {info.display_name:<22} | {info.quotex_symbol}")

"""
بوت التداول الذكي v3.0 — نقطة التشغيل الوحيدة
python main.py

التحسينات في v3:
✅ إصلاح قراءة ANTHROPIC_API_KEY
✅ إصلاح بطء جلب الشموع (تحميل تاريخي فوري)
✅ دمج telegram_alerts_pro (رسائل احترافية)
✅ دمج SignalStrengthScore + RiskRewardOptimizer
✅ دمج bot_algorithms v3 (38 نقطة، 24 مكوّن)
✅ دمج ml_engine (اختياري)
✅ تحسين msg_signal و msg_status و msg_stats
"""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path)

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest

# ── إعداد اللوج ───────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(message)s",
    datefmt = "%H:%M:%S",
    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler("bot.log", maxBytes=5_242_880, backupCount=3, encoding="utf-8"),
    ]
)
log = logging.getLogger("Bot")

# ── استيراد ملفات البوت ──────────────────────────────────
from bot_algorithms import (
    Candle, ConfluenceEngine, Signal,
    SignalStrengthScore, RiskRewardOptimizer,
)
from data_layer       import DataPipeline
from trade_executor   import (
    Database, TradeManager,
    fmt_trade_opened, fmt_trade_closed, fmt_full_stats,
)
from pairs_registry   import (
    QUOTEX_PAIRS, OTC_PAIRS,
    apply_pair_to_pipeline, get_pair, list_pairs,
)
from ai_analyst       import AIAnalystPipeline
from telegram_alerts_pro import ProMessageBuilder

# ── UI layer (design + interface separated) ──
import ui as ui_layer

# ── Shared modules from bot2 integration ──────
from shared.asset_mapping import (
    quotex_symbol_to_api_symbol, normalize_quotex_symbol,
)
from shared.broker_connection import BrokerConnectionService
from shared.execution_service import TradeExecutionService
from tradingview_provider import TradingViewProvider, MarketContext
from shared.decision_engine import WeightedDecisionEngine, build_fused_votes
from shared.risk_manager import FusedRiskManager
from shared.unified_signal import UnifiedSignalPackage, FusedResult
from shared.db_reporter import DBReporter
from shared.auto_executor import AutoExecuteGate
from shared.adaptive_thresholds import AdaptiveThresholds
from shared.portfolio_manager import PortfolioManager
from shared.self_optimizer import SelfOptimizer
from market_regime import MarketRegimeFilter
from backtesting import BacktestingEngine
from indicators_library import calc_ichimoku, calc_obv, calc_volume_profile, calc_adx, calc_rsi, calc_atr
from gemini_verifier import generate_chart_image, analyze_with_gemini, _build_technical_report

# ── Advanced AI (from bot2) — يحل محل MLPredictor تدريجياً ──
try:
    from advanced_ai import AdvancedAISystem
    ADV_AI_AVAILABLE = True
except ImportError:
    ADV_AI_AVAILABLE = False
    log.warning("⚠️ advanced_ai غير متاح — يتطلب sklearn, numpy")


# ══════════════════════════════════════════════════════════
#  ─── إصلاح #1: قراءة API KEY الصحيحة ───
# ══════════════════════════════════════════════════════════

def get_api_key() -> str:
    """يقرأ GEMINI_API_KEY ويتحقق منه"""
    key = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    invalid = {"", "your_key_here", "ضع_مفتاح_هنا", "none", "null"}
    if key.lower() in invalid or len(key) < 10:
        return ""
    return key


def ai_enabled() -> bool:
    return bool(get_api_key())


# ══════════════════════════════════════════════════════════
#  الحالة المركزية للبوت
# ══════════════════════════════════════════════════════════

class BotCore:
    def __init__(self):
        self.app:        Optional[Application]       = None
        self.pipeline:   Optional[DataPipeline]      = None
        self.db:         Optional[Database]          = None
        self.manager:    Optional[TradeManager]      = None
        self.ai:         Optional[AIAnalystPipeline] = None
        self.ml:         Optional[object]               = None
        self.advanced_ai: Optional[AdvancedAISystem] = None
        self._task:      Optional[asyncio.Task]      = None

        # حالة التشغيل
        self.is_running:  bool  = False
        self.paper_mode:  bool  = False
        self.chat_id:     Optional[int] = None
        self.start_time:  float = 0.0

        # إحصائيات الجلسة
        self.total_signals:      int = 0
        self.wins:               int = 0
        self.losses:             int = 0
        self.consecutive_losses: int = 0
        self.consecutive_wins:   int = 0

        # payout حقيقي من Quotex
        self._live_payouts: dict[str, float] = {}

        # ── caches from bot2 ──────────────────────────────
        self.balance_cache: dict     = {}
        self.active_trades: dict     = {}
        self._last_reconnect: float  = 0.0
        self._reconnect_lock         = asyncio.Lock()
        self._broker_conn_service    = None
        self._execution_svc          = None
        self.tv_provider             = TradingViewProvider(cache_ttl=int(os.getenv("TV_CACHE_TTL", "60")))

        # ─── إصلاح #2: حد أدنى معقول للشموع ───
        self.min_candles: int = 5

        # ── الزوج المعلق قبل تشغيل البوت ──
        self._pending_pair: Optional[str] = None

        # ─── جديد: ProMessageBuilder مدمج ───
        self.alert_builder: ProMessageBuilder = ProMessageBuilder(
            throttle_seconds=int(os.getenv("ALERT_THROTTLE", "60"))
        )

        # ترقيم الصفحات للأزواج — key → page
        self._pair_pages: dict[str, int] = {}

        # حالة واجهة التداول الجديدة
        self.auto_mode: bool = False
        self._selected_market: str = "live"
        self._selected_asset: str = "forex"
        self._pairs_page: int = 0
        self._stats_period: str = "day"

        # ── Fused modules from bot2 integration ────────────
        self.risk_manager: FusedRiskManager = FusedRiskManager(
            risk_per_trade_pct=float(os.getenv("RISK_PER_TRADE", "0.02")),
            daily_loss_limit_pct=float(os.getenv("MAX_DAILY_LOSS", "0.10")),
            max_consecutive_losses=int(os.getenv("MAX_CONS_LOSSES", "3")),
            min_trade_amount=float(os.getenv("MIN_TRADE", "1.0")),
            max_trade_amount=float(os.getenv("MAX_TRADE", "50.0")),
            max_concurrent_trades=int(os.getenv("MAX_CONCURRENT_TRADES", "3")),
            max_exposure_pct=float(os.getenv("MAX_EXPOSURE_PCT", "0.30")),
        )
        self.decision_engine: WeightedDecisionEngine = WeightedDecisionEngine(
            min_confidence_score=int(os.getenv("MIN_CONFIDENCE", "70"))
        )
        self.db_reporter: Optional[DBReporter] = None
        self.auto_gate: AutoExecuteGate = AutoExecuteGate(
            min_confluence_score=int(os.getenv("AUTO_MIN_CONFLUENCE", "9")),
            min_ensemble_confidence=int(os.getenv("AUTO_MIN_CONFIDENCE", "70")),
        )
        self.adaptive: AdaptiveThresholds = AdaptiveThresholds()
        self.portfolio: PortfolioManager = PortfolioManager(
            total_budget=float(os.getenv("BALANCE", "1000")),
            min_pair_budget=float(os.getenv("MIN_PAIR_BUDGET", "50")),
        )
        self.optimizer: SelfOptimizer = SelfOptimizer()
        self.regime_filter: MarketRegimeFilter = MarketRegimeFilter()
        self._last_regime: dict = {}
        self.backtest_engine: Optional[BacktestingEngine] = None
        self._pending_trades: dict[str, dict] = {}

    # ── خصائص مريحة ──────────────────────────────────────

    @property
    def win_rate(self) -> float:
        t = self.wins + self.losses
        return self.wins / t * 100 if t > 0 else 0.0

    @property
    def uptime(self) -> str:
        if not self.start_time:
            return "—"
        s = int(time.time() - self.start_time)
        h, r = divmod(s, 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @property
    def symbol(self) -> str:
        return self.pipeline.data_settings.symbol if self.pipeline else "—"

    @property
    def balance(self) -> float:
        if self.manager:
            return self.manager.stats.balance_current
        return float(os.getenv("BALANCE", "1000"))

    @property
    def price(self) -> float:
        if self.pipeline and self.pipeline.buffer:
            p = self.pipeline.buffer.current_price
            return p if p > 0 else 0.0
        return 0.0

    @property
    def candles_count(self) -> int:
        if self.pipeline and self.pipeline.buffer:
            return len(self.pipeline.buffer.candles)
        return 0

    def get_payout(self, symbol: str = None) -> float:
        """يُرجع الـ payout الحقيقي من Quotex، أو من .env، أو الافتراضي"""
        sym = symbol or self.symbol
        if sym in self._live_payouts:
            return self._live_payouts[sym]
        info = get_pair(sym)
        env_payout = float(os.getenv("PAYOUT", "88"))
        if info:
            return max(info.min_payout, env_payout)
        return env_payout

    # ── إرسال رسالة Telegram ──────────────────────────────

    async def send(self, text: str, markup=None, disable_preview: bool = True):
        if not self.chat_id or not self.app:
            return
        try:
            await self.app.bot.send_message(
                chat_id               = self.chat_id,
                text                  = text,
                parse_mode            = ParseMode.MARKDOWN,
                reply_markup          = markup,
                disable_web_page_preview = disable_preview,
            )
            return
        except Exception as e:
            log.error("send_message (Markdown) error: %s", e)
        # Retry with HTML
        try:
            await self.app.bot.send_message(
                chat_id               = self.chat_id,
                text                  = text,
                parse_mode            = ParseMode.HTML,
                reply_markup          = markup,
                disable_web_page_preview = True,
            )
            return
        except Exception as e:
            log.error("send_message (HTML) error: %s", e)
        # Retry without any parse mode
        try:
            await self.app.bot.send_message(
                chat_id               = self.chat_id,
                text                  = text,
                reply_markup          = markup,
                disable_web_page_preview = True,
            )
        except Exception as e:
            log.error("send_message (plain) error: %s", e)

    async def send_photo(self, photo: bytes, caption: str, markup=None):
        """إرسال صورة إشارة (BUY/SELL) مع كابشن"""
        if not self.chat_id or not self.app:
            return
        try:
            from telegram import InputFile
            await self.app.bot.send_photo(
                chat_id=self.chat_id,
                photo=InputFile(photo, filename="signal.png"),
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=markup,
            )
            return
        except Exception as e:
            log.error("send_photo (Markdown) error: %s", e)
        # Retry caption without Markdown
        try:
            from telegram import InputFile
            await self.app.bot.send_photo(
                chat_id=self.chat_id,
                photo=InputFile(photo, filename="signal.png"),
                caption=caption,
                reply_markup=markup,
            )
            return
        except Exception as e:
            log.error("send_photo (plain) error: %s", e)
        # Final fallback: send caption as text without Markdown
        await self._send_raw(caption, markup)

    async def _send_raw(self, text: str, markup=None):
        """إرسال نص بدون Markdown"""
        if not self.chat_id or not self.app:
            return
        try:
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.error("_send_raw error: %s", e)

    # ── جلب الـ payout الحقيقي من Quotex ─────────────────

    async def fetch_live_payouts(self):
        if not self.pipeline or not self.pipeline.connection.client:
            log.warning("⚠️ لا يوجد اتصال بـ Quotex لجلب الـ payout")
            return
        client    = self.pipeline.connection.client
        fetched   = 0

        # 1. Bulk fetch via get_payment() — كل الأزواج مرة واحدة
        try:
            from data_layer import call_quotex_method
            raw = await call_quotex_method(client, "get_payment")
            if isinstance(raw, dict):
                from pairs_registry import QUOTEX_PAIRS
                for name, data in raw.items():
                    if isinstance(data, dict):
                        p = float(data.get("payment", 0))
                        if 50 <= p <= 100:
                            name_clean = name.replace("-", "_").replace(" ", "_").upper()
                            # طابق الاسم مع QUOTEX_PAIRS
                            for pk in QUOTEX_PAIRS:
                                if name_clean in pk.upper() or pk.upper() in name_clean:
                                    self._live_payouts[pk] = p
                                    fetched += 1
                                    break
                            # سجل للزوج الحالي أيضاً
                            if name_clean.replace("_", "") in self.symbol.replace("_", "").replace("-", ""):
                                self._live_payouts[self.symbol] = p
            if fetched > 0:
                log.info("💰 تم جلب %d payout حقيقي عبر get_payment()", fetched)
                return
        except Exception as e:
            log.debug("get_payment bulk فشل: %s", e)

        # 2. Per-asset fallback
        conn = self.pipeline.connection
        from pairs_registry import QUOTEX_PAIRS
        for sym in list(QUOTEX_PAIRS.keys())[:10]:
            try:
                live = await conn.fetch_live_payout(sym)
                if live and 50 <= live <= 100:
                    self._live_payouts[sym] = live
                    fetched += 1
            except Exception:
                pass

        if fetched:
            log.info("💰 تم جلب %d payout", fetched)
        else:
            log.info("💰 لم نتمكن من جلب payout حقيقي — استخدام .env")

        log.info("💰 payout جاهز لـ %d زوج", fetched)


# ── instance عالمي ───────────────────────────────────────
B = BotCore()


# ── broker / execution services lazy init ────────────────
def _now_ts() -> float:
    return time.time()


def _get_client():
    return B.pipeline.connection.client if B.pipeline else None


async def _connect_with_retry(max_retries=3):
    if B.pipeline:
        client = await B.pipeline.connection.connect()
        return client
    return None


async def _ensure_connection(max_retries=3):
    if B.pipeline:
        ok = await B.pipeline.connection.ensure_connected()
        return B.pipeline.connection.client if ok else None
    return None


async def _refresh_connection(min_interval=8):
    if B.pipeline:
        return await B.pipeline.connection.ensure_connected()
    return False


def get_broker_connection_service():
    if B._broker_conn_service is None:
        B._broker_conn_service = BrokerConnectionService(
            get_client=_get_client,
            connect_with_retry=_connect_with_retry,
            balance_cache=B.balance_cache,
            now_ts=_now_ts,
            reconnect_lock=B._reconnect_lock,
            get_last_reconnect_at=lambda: B._last_reconnect,
            set_last_reconnect_at=lambda v: setattr(B, '_last_reconnect', v),
        )
    return B._broker_conn_service


def get_execution_service():
    if B._execution_svc is None:
        B._execution_svc = TradeExecutionService(
            get_client=_get_client,
            ensure_connection=_ensure_connection,
            refresh_connection=_refresh_connection,
            symbol_to_api_symbol=quotex_symbol_to_api_symbol,
            active_trades=B.active_trades,
            balance_cache=B.balance_cache,
            execution_lock=asyncio.Lock(),
        )
    return B._execution_svc


# ══════════════════════════════════════════════════════════
#  لوحات التحكم (Keyboards) — thin wrappers over ui.py
# ══════════════════════════════════════════════════════════

def kb_main():
    return ui_layer.build_main_keyboard(B.is_running, B.paper_mode)


def kb_pairs_category():
    return ui_layer.build_pairs_category_keyboard()


def kb_pairs_list(pairs: list, back_cb: str = "pairs_menu"):
    page = B._pair_pages.get(back_cb, 0)
    return ui_layer.build_pairs_keyboard(
        pairs, B.get_payout, B.symbol, B._pair_pages, page=page
    )


def kb_result(sid: str):
    return ui_layer.build_result_keyboard(sid)


def kb_settings():
    return ui_layer.build_settings_keyboard()


def kb_duration():
    cur = int(os.getenv("TRADE_DURATION", "60"))
    return ui_layer.build_duration_keyboard(cur)


def kb_journal():
    return ui_layer.build_journal_keyboard()


# ══════════════════════════════════════════════════════════
#  رسائل Telegram (مُحسَّنة مع Alerts Pro)
# ══════════════════════════════════════════════════════════

def msg_welcome() -> str:
    return ui_layer.build_main_text(
        is_running=B.is_running,
        paper_mode=B.paper_mode,
        win_rate=B.win_rate,
        balance=B.balance,
        symbol=B.symbol,
        price=B.price,
        uptime=B.uptime,
        ai_enabled=ai_enabled(),
        ml_available=B.ml is not None,
        total_signals=B.total_signals,
        wins=B.wins,
        losses=B.losses,
    )


def msg_help() -> str:
    return ui_layer.build_help_text()


def msg_status() -> str:
    return ui_layer.build_status_text(
        is_running=B.is_running,
        paper_mode=B.paper_mode,
        is_connected=bool(B.pipeline and B.pipeline.connection._is_healthy),
        ai_enabled=ai_enabled(),
        ml_available=B.ml is not None,
        symbol=B.symbol,
        payout=B.get_payout(),
        price=B.price,
        candles_count=B.candles_count,
        candle_age_pct=B.pipeline.buffer.candle_age_pct if B.pipeline else 0,
        balance=B.balance,
        uptime=B.uptime,
    )


def msg_stats() -> str:
    today = B.alert_builder.history.today_summary()
    return ui_layer.build_stats_text(
        total_signals=B.total_signals,
        wins=B.wins,
        losses=B.losses,
        win_rate=B.win_rate,
        balance=B.balance,
        payout=B.get_payout(),
        consecutive_losses=B.consecutive_losses,
        consecutive_wins=B.consecutive_wins,
        uptime=B.uptime,
        today=today,
    )


async def _safe_reply(msg_or_update, text: str, **kwargs):
    """إرسال مع Markdown — إذا فشل بسبب تنسيق خاطئ، يعيد بدون Markdown"""
    try:
        await msg_or_update.reply_text(text, **kwargs)
    except Exception:
        kwargs.pop("parse_mode", None)
        await msg_or_update.reply_text(text, **kwargs)


def msg_signal_pro(sig: Signal, candles: list, hybrid_text: str = "") -> str:
    """
    يستخدم ProMessageBuilder للرسائل الاحترافية
    """
    if hybrid_text:
        sss    = SignalStrengthScore(sig, B.consecutive_losses)
        sr     = sss.calculate()
        rr     = RiskRewardOptimizer(
            balance            = B.balance,
            payout_pct         = B.get_payout(),
            win_rate           = 0.45 + sig.score * 0.01,
            consecutive_losses = B.consecutive_losses,
            consecutive_wins   = B.consecutive_wins,
        )
        rr_r   = rr.calculate(sr["final_score"])
        ev_str = f"{rr_r['expected_value']:+.2f}$"
        ev_ic  = "🟢" if rr_r["expected_value"] >= 0 else "🔴"

        addon = (
            f"\n◆━━━━━━━━━━━━━━━━━━━━━━━━━━◆\n"
            f"  {sr['grade_icon']} *قوة:* `{sr['final_score']:.0f}%` — {sr['grade']}\n"
            f"  💰 الحجم: `${rr_r['trade_size']:.2f}` ({rr_r['fraction_pct']:.2f}%)\n"
            f"  {ev_ic} المتوقع: `{ev_str}`\n"
        )
        if sr["bonuses"]:
            addon += "  ✅ " + " | ".join(sr["bonuses"][:2]) + "\n"
        if sr["penalties"]:
            addon += "  ⚠️ " + " | ".join(sr["penalties"][:1]) + "\n"

        return hybrid_text + addon

    try:
        return B.alert_builder.build_signal_message(
            signal  = sig,
            candles = candles,
            symbol  = B.symbol,
            payout  = B.get_payout(),
            balance = B.balance,
        )
    except Exception as e:
        log.warning("ProMessageBuilder error: %s — fallback", e)
        return _msg_signal_fallback(sig)


def _msg_signal_fallback(sig: Signal) -> str:
    """رسالة بسيطة احتياطية إذا فشل ProMessageBuilder"""
    icon  = "🟢" if sig.direction == "UP" else "🔴" if sig.direction == "DOWN" else "⏸"
    arrow = "⬆️ صعود" if sig.direction == "UP" else "⬇️ نزول" if sig.direction == "DOWN" else "⏸ انتظار"
    filled = int(sig.confidence / 10)
    bar    = "█" * filled + "░" * (10 - filled)

    if sig.score >= 20:   strength = "🔥 قوي جداً"
    elif sig.score >= 14: strength = "💪 قوي"
    elif sig.score >= 9:  strength = "👍 جيد"
    elif sig.score >= 6:  strength = "⚠️ ضعيف"
    else:                 strength = "❌ لا تدخل"

    reas  = "\n".join(f"  • {r}" for r in sig.reasons[:5]) or "  —"
    warns = ("\n⚠️ *تحذيرات:*\n" + "\n".join(f"  ⚠️ {w}" for w in sig.warnings[:3])) \
            if sig.warnings else ""

    grade_icons = {"VERY_STRONG": "🔥", "STRONG": "💪", "MODERATE": "👍", "WEAK": "⚠️", "VERY_WEAK": "❌"}
    grades = {"VERY_STRONG": "قوي جداً", "STRONG": "قوي", "MODERATE": "متوسط", "WEAK": "ضعيف", "VERY_WEAK": "ضعيف جداً"}
    grade_str = ""
    if sig.score >= 20: grade_str = f"{grade_icons['VERY_STRONG']} {grades['VERY_STRONG']}"
    elif sig.score >= 14: grade_str = f"{grade_icons['STRONG']} {grades['STRONG']}"
    elif sig.score >= 9: grade_str = f"{grade_icons['MODERATE']} {grades['MODERATE']}"
    elif sig.score >= 6: grade_str = f"{grade_icons['WEAK']} {grades['WEAK']}"
    else: grade_str = f"{grade_icons['VERY_WEAK']} {grades['VERY_WEAK']}"

    return ui_layer.build_signal_caption(
        direction=sig.direction,
        symbol=B.symbol,
        score=sig.score,
        max_score=38,
        confidence=sig.confidence,
        strength_grade=grade_str.split()[-1] if grade_str else "ضعيف",
        strength_icon=grade_str.split()[0] if grade_str else "❌",
        strength_label=grade_str,
        trade_size=sig.trade_size,
        overlap_pct=max(5, min(30, 20 - int(sig.score * 0.15))),
        success_pct=min(98, int(sig.confidence * 0.4 + sig.score * 1.5)),
        payout=B.get_payout(),
        reasons=sig.reasons[:5],
        warnings=sig.warnings[:3],
    )


def msg_settings() -> str:
    return ui_layer.build_settings_text()


def msg_ai_status() -> str:
    if ai_enabled():
        key = get_api_key()
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        stats = B.ai.stats if B.ai else {}
        return ui_layer.build_ai_status_text(
            enabled=True,
            api_key_masked=masked,
            total_calls=stats.get("total_ai_calls", 0),
            total_cost=stats.get("total_cost_usd", 0),
            cache_hit_rate=stats.get("cache", {}).get("hit_rate", 0),
        )
    key_raw = os.getenv("ANTHROPIC_API_KEY", "").strip()
    hint = ""
    if key_raw and not key_raw.startswith("sk-ant"):
        hint = f"\n⚠️ المفتاح الموجود لا يبدأ بـ `sk-ant`:\n`{key_raw[:15]}...`"
    elif key_raw in ("sk-ant-...", "ضع_مفتاح_claude_هنا"):
        hint = "\n⚠️ لم تضع مفتاحاً حقيقياً بعد"
    return ui_layer.build_ai_status_text(enabled=False, key_hint=hint)


def msg_ml_status() -> str:
    if B.ml and B.ml.model.trained:
        m = B.ml.model
        return ui_layer.build_ml_status_text(
            available=True,
            trees=len(m.trees),
            accuracy=m.accuracy,
            train_size=m.train_size,
        )
    return ui_layer.build_ml_status_text(available=False)


# ══════════════════════════════════════════════════════════
#  شموع تجريبية احتياطية
# ══════════════════════════════════════════════════════════

def _make_demo_candles(n: int = 50, base_price: float = 1.1000) -> list[Candle]:
    """يصنع شموع تجريبية واقعية للتحليل الفوري"""
    import random, math
    random.seed(int(time.time()) % 10000)
    candles = []
    price   = base_price
    for i in range(n):
        drift  = 0.0001 * math.sin(i * 0.3)
        change = drift + random.gauss(0, 0.00025)
        o = price
        c = round(o + change, 6)
        h = round(max(o, c) + abs(random.gauss(0, 0.0001)), 6)
        l = round(min(o, c) - abs(random.gauss(0, 0.0001)), 6)
        candles.append(Candle(o, c, h, l, random.randint(800, 2500)))
        price = c
    return candles


# ══════════════════════════════════════════════════════════
#  Callbacks الرئيسية
# ══════════════════════════════════════════════════════════

async def on_new_signal(signal: Signal, hybrid_text: str = "", usp=None):
    """يُستدعى عند كل إشارة جديدة — يُرسلها عبر Telegram + Dashboard"""
    B.total_signals += 1
    sid = str(B.total_signals)

    signal.clear = None  # mark for UI
    image = ui_layer.get_signal_image(signal.direction)
    if image:
        strength_pct = _calc_strength_pct(signal)
        caption = ui_layer.build_signal_caption(
            direction=signal.direction,
            symbol=B.symbol,
            score=signal.score,
            max_score=38,
            confidence=signal.confidence,
            strength_grade="",
            strength_icon="",
            strength_label="",
            trade_size=signal.trade_size,
            overlap_pct=max(5, min(30, 20 - int(signal.score * 0.15))),
            success_pct=min(98, int(signal.confidence * 0.4 + signal.score * 1.5)),
            payout=B.get_payout(),
            reasons=signal.reasons[:5],
            warnings=signal.warnings[:3],
            strength_pct=strength_pct,
        )
        await B.send_photo(image, caption, markup=kb_result(sid))

    # رسالة نصية بالإشارة
    try:
        await B.send(fmt_signal_direction(signal))
    except Exception as e:
        log.debug("fmt_signal_direction error: %s", e)

    # AI-enhanced text message
    if B.alert_builder and usp:
        try:
            enhanced = B.alert_builder.build_ai_enhanced_message(signal, usp, hybrid_text)
            await B.send(enhanced)
        except Exception as e:
            log.debug("AI message error: %s", e)

    # تسجيل الإشارة في TradeManager
    if B.manager:
        await B.manager.handle_signal(signal)


async def on_trade_event(event_type: str, trade, result):
    """يُستدعى عند فتح/إغلاق صفقة — مع مراقبة متقدمة وتعلم مستمر"""
    if event_type == "opened":
        B.risk_manager.register_trade(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            direction=trade.signal_direction,
            amount=trade.trade_size,
        )
        await B.send(fmt_trade_opened(trade))

    elif event_type == "closed" and result:
        B.risk_manager.unregister_trade(trade.trade_id)
        text = fmt_trade_closed(trade, result)
        if B.manager:
            s = B.manager.stats
            text += (
                f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅{s.wins} ❌{s.losses} "
                f"| {s.win_rate:.1f}% | `${s.balance_current:.2f}`"
            )

        # ── Advanced AI online learning + performance tracking ──
        if B.advanced_ai:
            try:
                # Build rich trade data for AI learning
                candles = B.pipeline.buffer.candles if B.pipeline else []
                price_sequence = []
                market_condition = "normal"
                if candles and len(candles) >= 5:
                    last = candles[-1]
                    price_sequence = [last.open, last.high, last.low, last.close,
                                      getattr(last, 'volume', 0)]
                    vol = (last.high - last.low) / (last.close or 1)
                    market_condition = "high_vol" if vol > 0.03 else "low_vol" if vol < 0.01 else "normal"

                trade_data = {
                    "result": result.value,
                    "profit": trade.profit,
                    "amount": trade.trade_size,
                    "pair": trade.symbol,
                    "confidence": trade.confidence,
                    "timeframe": "1m",
                    "direction": trade.signal_direction if hasattr(trade, 'signal_direction') else "unknown",
                    "risk_level": "low" if trade.confidence and trade.confidence >= 80 else "medium" if trade.confidence and trade.confidence >= 60 else "high",
                    "market_condition": market_condition,
                    "price_sequence": price_sequence,
                }
                B.advanced_ai.learn_from_trade(trade_data)
            except Exception as e:
                log.debug("AI learn error: %s", e)

        # ── Performance stats from AI ─────────────────────
        perf = ""
        if B.advanced_ai:
            try:
                stats = B.advanced_ai.get_performance_stats()
                if stats.get("total_trades", 0) > 0:
                    perf = (
                        f"\n🧠 AI Stats: {stats['total_trades']}T "
                        f"| WR: {stats['win_rate']:.1f}% "
                        f"| PF: {stats['profit_factor']:.2f} "
                        f"| Exp: {stats['expectancy']:.2f}"
                    )
            except Exception:
                pass

        await B.send(text + perf)


# ── التحليل الأولي بعد بدء البوت ───────────────────────────
async def _send_initial_analysis():
    """يُستدعى بعد بدء الـ pipeline — يحلل الشموع التاريخية ويرسل تحليل كامل"""
    try:
        await asyncio.sleep(3)
        if not B.pipeline or not B.pipeline.buffer or not B.pipeline.buffer.candles:
            await B.send("🧠 *AI Analyzing...*\n⏳ جاري جمع البيانات...")
            await asyncio.sleep(5)
        if B.pipeline and B.pipeline.buffer:
            candles = B.pipeline.buffer.candles
            price = B.price or (candles[-1].close if candles else 0)
            a = build_market_analysis(candles, price)
            await B.send(f"🧠 *AI Analyzing...* ✅\n" + fmt_market_analysis(a))
    except Exception as e:
        log.debug("Initial analysis error: %s", e)


# ══════════════════════════════════════════════════════════
#  تشغيل / إيقاف البوت
# ══════════════════════════════════════════════════════════

async def do_start(symbol_key: str = None) -> tuple[bool, str]:
    if B.is_running:
        return False, "البوت يعمل بالفعل"

    # ── 1. قاعدة البيانات ────────────────────────────────
    if not B.db:
        B.db = Database(os.getenv("DB_PATH", "trades.db"))
        await B.db.connect()
        B.db_reporter = DBReporter(B.db)

    # ── 2. Claude AI ─────────────────────────────────────
    # ─── إصلاح #1: التحقق الدقيق من المفتاح ───
    api_key = get_api_key()
    B.ai = AIAnalystPipeline(
        api_key            = api_key,
        min_algo_score     = int(os.getenv("MIN_SCORE",         "6")),
        min_ai_confidence  = int(os.getenv("MIN_AI_CONFIDENCE", "60")),
        cache_ttl          = int(os.getenv("AI_CACHE_TTL",      "45")),
        enable_ai          = bool(api_key),
    )
    log.info(
        "🧠 AI: %s | key: %s",
        "مفعّل ✅" if api_key else "معطل ❌",
        api_key[:8] + "..." if api_key else "none",
    )

    # ── 3. Advanced AI (bot2) — ensemble + online learning ──
    if ADV_AI_AVAILABLE:
        try:
            B.advanced_ai = AdvancedAISystem(model_dir=".")
            log.info("🧠 Advanced AI: %d models, %d samples",
                     len(B.advanced_ai.models), len(B.advanced_ai.training_data))
        except Exception as e:
            log.warning("⚠️ Advanced AI فشل: %s", e)
            B.advanced_ai = None

    # ── 4. DataPipeline ───────────────────────────────────
    B.pipeline = DataPipeline.from_env()
    if symbol_key:
        apply_pair_to_pipeline(B.pipeline, symbol_key)

    # ── 5. بدون إشارات تلقائية — فقط pipeline للبيانات ──
    # (الإشارات يدوياً فقط من confirm_start في on_button)

    # ── 6. TradeManager ───────────────────────────────────
    B.manager = TradeManager(
        pipeline               = B.pipeline,
        db                     = B.db,
        on_result              = on_trade_event,
        trade_duration         = int(os.getenv("TRADE_DURATION",  "60")),
        paper_mode             = True,
        min_score              = int(os.getenv("MIN_SCORE",        "6")),
        max_daily_loss_pct     = float(os.getenv("MAX_DAILY_LOSS", "0.10")),
        max_consecutive_losses = int(os.getenv("MAX_CONS_LOSSES",  "3")),
    )
    await B.manager.initialize()

    # ── 7. تشغيل Pipeline في الخلفية ─────────────────────
    async def _run():
        try:
            await B.pipeline.run()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("Pipeline error: %s", e)
            B.is_running = False
            await B.send(f"❌ *البوت توقف بسبب خطأ:*\n`{str(e)[:300]}`")

    B._task      = asyncio.create_task(_run())
    B.is_running = True
    B.start_time = time.time()

    # ── 8. تحليل السوق الأولي (Initial AI Analysis) ──
    asyncio.create_task(_send_initial_analysis())

    # ── 9. جلب payout حقيقي في الخلفية ───────────────────
    asyncio.create_task(B.fetch_live_payouts())

    # ── 10. Connection health watchdog ──────────────
    async def _health_watchdog():
        was_connected = True
        while B.is_running:
            await asyncio.sleep(60)
            connected = B.pipeline and B.pipeline.feed and getattr(B.pipeline.feed, '_running', False)
            if not connected and was_connected:
                await B.send("⚠️ *Connection Lost* — Bot is disconnected from Quotex. Attempting reconnect...")
                was_connected = False
            elif connected and not was_connected:
                await B.send("✅ *Reconnected* — Bot is back online.")
                was_connected = True
    asyncio.create_task(_health_watchdog())

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    mode_label = "📋 تجريبي" if B.paper_mode else "💵 حقيقي"
    ai_label   = "🧠 Gemini مفعّل" if (gemini_key and len(gemini_key) >= 10) else "⚙️ خوارزميات فقط"
    ml_label   = " + 🤖 ML" if B.ml else ""
    return True, f"✅ يعمل | {mode_label} | {ai_label}{ml_label}"


# ── تحليل السوق الكامل (Support/Resistance + جميع المقاييس) ──
def build_market_analysis(candles: list, price: float) -> dict:
    """تحليل كامل: دعم/مقاومة، RSI، ترند، تقلب، قوة، احتمالية تداخل، نسبة نجاح"""
    if not candles or len(candles) < 5:
        return {"current_price": price, "strength": 50, "overlap_prob": 30, "success_rate": 50}
    closes = [c.close for c in candles]
    highs  = [c.high  for c in candles]
    lows   = [c.low   for c in candles]
    n = len(closes)
    # S/R levels
    lookback = min(20, n)
    resistance = max(highs[-lookback:])
    support    = min(lows[-lookback:])
    pivot = (highs[-1] + lows[-1] + closes[-1]) / 3
    # RSI
    rsi = 50.0
    if n > 14:
        gains = losses = 0.0
        for i in range(-14, 0):
            diff = closes[i] - closes[i-1]
            if diff >= 0: gains += diff
            else:        losses -= diff
        avg_g = gains / 14; avg_l = losses / 14
        if avg_l > 0: rsi = 100.0 - (100.0 / (1.0 + avg_g/avg_l))
        elif avg_g > 0: rsi = 100.0
    # ATR (تقلب)
    trs = []
    for i in range(1, min(14, n)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    volatility = sum(trs)/len(trs) if trs else 0
    # EMA سريع/بطيء للترند
    ema_short = sum(closes[-5:])/5 if n>=5 else closes[-1]
    ema_long  = sum(closes[-20:])/20 if n>=20 else closes[-1]
    trend = "صاعد 📈" if ema_short > ema_long else "هابط 📉"
    avg_vol = (max(highs[-5:])-min(lows[-5:]))/closes[-1] if n>=5 and closes[-1] else 0.005
    market_cond = "منخفض" if avg_vol < 0.005 else "متوسط" if avg_vol < 0.015 else "مرتفع"
    # قوة الأصل
    strength = min(95, 50 + (50-abs(rsi-50)) + (10 if abs(rsi-50)>15 else 0))
    # ── Ichimoku Cloud ─────────────────────────
    ichimoku = calc_ichimoku(highs, lows, closes)
    # ── OBV ─────────────────────────────────────
    volumes = [getattr(c, 'volume', 100) for c in candles]
    obv = calc_obv(closes, volumes)
    obv_signal = "صاعد 📈" if obv > 0 else "هابط 📉"
    # ── Volume Profile ──────────────────────────
    vp = calc_volume_profile(highs, lows, volumes)
    # ── ADX ─────────────────────────────────────
    adx_data = calc_adx(highs, lows, closes)
    adx = adx_data.get("adx", 25)
    # احتمالية التداخل (overlap) — من التقلب + ADX
    norm_vol = min(volatility/price*100 if price else 0.5, 3)
    overlap_prob = min(norm_vol*20 + (15 if adx < 25 else 5), 75)
    # اتجاه متوقع
    direction = "PUT 📉" if rsi > 55 else "CALL 📈" if rsi < 45 else "محايد ⏸️"
    # حجم التداول (نسبي)
    volume_pct = min(95, 60 + (100-strength)*0.4)
    # نسبة نجاح متوقعة
    score_est = 50
    if 25 <= rsi <= 75: score_est += 10
    if abs(rsi-50) > 12: score_est += 10
    if adx >= 25: score_est += 10
    if ichimoku.get("cloud_green", 0) and ema_short > ema_long: score_est += 8
    if abs(ema_short-ema_long)/ema_long > 0.0005: score_est += 7
    if obv_signal == "صاعد 📈": score_est += 5
    if resistance != support: score_est += 5
    success_rate = min(score_est + 15, 98)
    return dict(current_price=round(price,5), resistance=round(resistance,5),
                support=round(support,5), pivot=round(pivot,5), trend=trend,
                rsi=round(rsi,1), volatility=round(volatility,5),
                strength=round(strength,1), overlap_prob=round(overlap_prob,1),
                success_rate=round(success_rate,1), direction=direction,
                volume_pct=round(volume_pct,1), market_condition=market_cond,
                ichimoku_tenkan=round(ichimoku["tenkan"],5), ichimoku_kijun=round(ichimoku["kijun"],5),
                cloud_green=ichimoku["cloud_green"], obv_signal=obv_signal,
                vp_poc=round(vp["poc"],5), vp_vah=round(vp["vah"],5), vp_val=round(vp["val"],5),
                adx=round(adx,1))

def fmt_market_analysis(a: dict) -> str:
    """تنسيق تحليل السوق لرسالة Telegram مع Ichimoku و ADX و OBV و Volume Profile"""
    cloud = "🟢 إيشيموكو: اختراق سحابة صاعدة" if a.get("cloud_green") == 1 else "🔴 إيشيموكو: اختراق سحابة هابطة" if a.get("cloud_green") == -1 else "⚪ إيشيموكو: محايد"
    obv = f"📊 OBV: {a.get('obv_signal', '—')}"
    adx_label = f"🌪️ ADX({a.get('adx', '?')}): {'اتجاه' if a.get('adx', 0) >= 25 else 'جانبي'}"
    return (
        f"📊 *تحليل السوق — {B.symbol}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 السعر الحالي: `{a['current_price']}`\n"
        f"🔴 المقاومة:     `{a['resistance']}`\n"
        f"🟢 الدعم:        `{a['support']}`\n"
        f"📌 البيفوت:      `{a['pivot']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 الاتجاه:      {a['trend']}\n"
        f"📉 RSI:          `{a['rsi']}`\n"
        f"🌪️ ADX:         `{a.get('adx', '?')}` | {adx_label}\n"
        f"🌊 التقلب:       `{a['market_condition']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏋️ قوة الأصل:    `{a['strength']}%`\n"
        f"📊 حجم التداول:  `{a['volume_pct']}%`\n"
        f"{cloud}\n"
        f"{obv}\n"
        f"📊 Volume Profile POC: `{a.get('vp_poc', '—')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 الاتجاه المتوقع: {a['direction']}\n"
        f"⚠️ احتمالية التداخل: `{a['overlap_prob']}%`\n"
        f"✅ نسبة نجاح متوقعة: `{a['success_rate']}%` 🎯\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_تحليل {len(B.pipeline.buffer.candles) if B.pipeline else 0} شمعة_"
    )

def fmt_wait_signal(signal) -> str:
    """تنسيق رسالة WAIT"""
    return (
        f"⏸️ *WAIT — لا توجد إشارة واضحة*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 النقاط: `{signal.score}/38` — "
        f"{'منخفضة جداً' if signal.score < 6 else 'غير كافية'}\n"
        f"{'💡 ' + signal.reasons[0] if signal.reasons else ''}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 سأواصل التحليل..."
    )

def fmt_signal_direction(signal) -> str:
    """تنسيق رسالة BUY/SELL محسّنة"""
    emoji = "🟢" if signal.direction == "UP" else "🔴"
    label = "شراء (BUY)" if signal.direction == "UP" else "بيع (SELL)"
    return (
        f"{emoji} *{label}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"الأصل: `{B.symbol}`\n"
        f"التايم فريم: `1 دقيقة`\n"
        f"الاتجاه: `{label}`\n"
        f"الثقة: `{signal.confidence}%`\n"
        f"النقاط: `{signal.score}/38`\n"
        f"حجم التداول: `${signal.trade_size:.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{'💡 ' + chr(10).join(signal.reasons[:3]) if signal.reasons else ''}"
    )

# ── Smart entry timing ───────────────────────────────────
def calculate_seconds_to_new_candle(timeframe_minutes: int) -> int:
    """حساب الثواني المتبقية للشمعة الجديدة — لدقة دخول أعلى"""
    current_time = datetime.now()
    remainder = current_time.minute % timeframe_minutes
    if remainder == 0:
        return 0
    return (timeframe_minutes - remainder) * 60 - current_time.second


async def do_stop():
    B.is_running = False
    if B._task and not B._task.done():
        B._task.cancel()
        try:
            await B._task
        except asyncio.CancelledError:
            pass
    if B.pipeline:
        await B.pipeline.feed.stop()
    if B.db and B.manager:
        await B.db.update_daily_summary(B.balance)
        # إرسال ملخص الجلسة
        summary = B.alert_builder.build_session_summary(
            B.manager.stats.balance_start,
            B.balance,
        )
        await B.send(summary)
    B.pipeline = B.manager = B._task = None
    B.balance_cache.clear()
    B.active_trades.clear()
    B._broker_conn_service = None
    B._execution_svc = None
    log.info("⏹ Bot stopped")


# ══════════════════════════════════════════════════════════
#  أوامر Telegram
# ══════════════════════════════════════════════════════════

async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    B.chat_id = u.effective_chat.id
    if not B.is_running:
        ok, detail = await do_start()
        if ok:
            await u.message.reply_text(
                f"✅ *البوت يعمل الآن*\n{detail}\n"
                f"الزوج: `{B.symbol}`\n"
                f"_انتظر لحظات لتحليل السوق_",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(),
            )
        else:
            await u.message.reply_text(
                msg_welcome(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
            )
    else:
        await u.message.reply_text(
            msg_welcome(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )


async def cmd_help(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(msg_help(), parse_mode=ParseMode.MARKDOWN)


async def cmd_status(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        msg_status(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
    )


def _calc_strength_pct(sig: Signal) -> float:
    """حساب 💡 قوة الإشارة باستخدام SignalStrengthScore"""
    try:
        sss = SignalStrengthScore(sig, B.consecutive_losses)
        return sss.calculate()["final_score"]
    except Exception:
        return 0.0


async def _send_signal_msg(target, sig: Signal, text: str = "", sid: str = ""):
    """يرسل إشارة مع صورة للـ UP/DOWN أو رسالة WAIT"""
    # تحديد حالة Gemini
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    gemini_status = "🤖 Gemini AI" if (gemini_key and len(gemini_key) >= 10) else "⚙️ بدون AI"

    if sig.direction == "WAIT":
        gemini_line = f"{'🤖 Gemini: CONFIRMED' if any('CONFIRMED' in r for r in sig.reasons) else gemini_status}\n"
        msg = (
            f"⏸️ *WAIT — لا توجد إشارة واضحة*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 النقاط: `{sig.score}/38`\n"
            f"📉 الثقة: `{sig.confidence:.0f}%`\n"
            f"{gemini_line}"
        )
        if sig.reasons:
            msg += f"💡 {sig.reasons[0]}\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n🔄 جرب زوج أو مدة أخرى"
        await B.send_message(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_result(sid))
        return

    image = ui_layer.get_signal_image(sig.direction)
    if image:
        strength_pct = _calc_strength_pct(sig)
        # إضافة حالة Gemini للـ caption
        has_gemini = any("CONFIRMED" in r or "Gemini" in r for r in sig.reasons)
        reasons_display = sig.reasons[:4]
        if has_gemini:
            reasons_display.append("🤖 Gemini: CONFIRMED (بصري)")
        else:
            reasons_display.append(f"{gemini_status}")
        caption = ui_layer.build_signal_caption(
            direction=sig.direction,
            symbol=B.symbol,
            score=sig.score,
            max_score=38,
            confidence=sig.confidence,
            strength_grade="",
            strength_icon="",
            strength_label="",
            trade_size=sig.trade_size,
            overlap_pct=max(5, min(30, 20 - int(sig.score * 0.15))),
            success_pct=min(98, int(sig.confidence * 0.4 + sig.score * 1.5)),
            payout=B.get_payout(),
            reasons=reasons_display,
            warnings=sig.warnings[:3],
            strength_pct=strength_pct,
        )
        await B.send_photo(image, caption, markup=kb_result(sid))


# ── تسجيل النتيجة التلقائي ─────────────────────────────
def _record_trade_outcome(direction: str, entry_price: float, trade_amount: float):
    """يحسب الربح/الخسارة ويسجلها في كل الأنظمة"""
    current_price = B.price
    if current_price <= 0:
        return
    if direction == "UP":
        won = current_price > entry_price
    else:
        won = current_price < entry_price

    payout = B.get_payout()
    profit = trade_amount * (payout / 100) if won else -trade_amount

    if won:
        B.wins += 1
        B.consecutive_losses = 0
        B.consecutive_wins += 1
        if B.manager:
            B.manager.stats.wins += 1
            B.manager.stats.consecutive_losses = 0
    else:
        B.losses += 1
        B.consecutive_losses += 1
        B.consecutive_wins = 0
        if B.manager:
            B.manager.stats.losses += 1
            B.manager.stats.consecutive_losses += 1

    B.alert_builder.record_result(B.symbol, "WIN" if won else "LOSS", 0, won, profit)
    B.risk_manager.record_trade_result(profit=profit)

    if not won and B.consecutive_losses >= 3:
        critical = (
            f"🚨 *Circuit Breaker*\n"
            f"{B.consecutive_losses} خسائر متتالية | الرصيد: `${B.balance:.2f}`\n"
            f"سيتم تقليل حجم الصفقة حتى ربح."
        )
        try:
            asyncio.create_task(B.send(critical))
        except Exception:
            pass

    return profit, won


async def _auto_check_trade(trade_id: str):
    """بعد TRADE_DURATION ثانية، يتحقق تلقائياً من نتيجة الصفقة ويسجلها"""
    info = B._pending_trades.get(trade_id)
    if not info:
        return
    entry_price = info["entry_price"]
    direction = info["direction"]
    trade_amount = info["trade_amount"]
    duration = info["duration"]
    msg = info.get("msg")

    await asyncio.sleep(duration)
    result = _record_trade_outcome(direction, entry_price, trade_amount)
    if result is None:
        return
    profit, won = result

    del B._pending_trades[trade_id]

    status_text = (
        f"{'✅ *ربح!* 🎉' if won else '❌ *خسارة*'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 الربح: `{'$+' if won else '$'}{profit:.2f}`\n"
        f"✅ `{B.wins}`  ❌ `{B.losses}`  |  📊 `{B.win_rate:.1f}%`\n"
        f"💰 الرصيد: `${B.balance:.2f}`"
    )
    if msg:
        try:
            await B.send(status_text)
        except Exception:
            pass

    # تغذية ML
    try:
        candles = B.pipeline.buffer.candles if B.pipeline else []
        if len(candles) >= 5:
            last = candles[-1]
            features = [last.close, last.high, last.low, last.open, last.volume,
                        last.close - last.open, last.high - last.low,
                        last.close / (candles[-2].close or 1) - 1]
            B.advanced_ai.learn_from_trade({
                "result": "win" if won else "loss",
                "profit": profit,
                "amount": trade_amount,
                "pair": B.symbol,
                "features": features,
            })
    except Exception:
        pass


async def cmd_signal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    candles = B.pipeline.buffer.candles if B.pipeline else []
    price = B.price
    if price <= 0 and candles:
        price = candles[-1].close

    # Smart entry: انتظر الشمعة الجديدة لو المستخدم طلب --smart
    if c.args and "--smart" in c.args:
        secs = calculate_seconds_to_new_candle(1)
        if secs > 10:
            await u.message.reply_text(
                f"🎯 *Smart Entry*\n⏳ ننتظر شمعة جديدة: {secs} ثانية",
                parse_mode=ParseMode.MARKDOWN,
            )
            await asyncio.sleep(secs)
            # أعد جلب الشموع بعد الانتظار
            candles = B.pipeline.buffer.candles if B.pipeline else []
            price = B.price
            if price <= 0 and candles:
                price = candles[-1].close

    if len(candles) < B.min_candles:
        if B.is_running:
            base = price if price > 0 else 1.1000
            candles = _make_demo_candles(60, base)
            price   = candles[-1].close
        else:
            await u.message.reply_text(
                "⏳ *البوت متوقف*\n"
                "اضغط *تشغيل البوت* أولاً من /start",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(),
            )
            return
    else:
        price = price if price > 0 else candles[-1].close

    sig  = ConfluenceEngine(candles, price, B.get_payout(), B.balance).run()
    await _send_signal_msg(u.message, sig, sid="manual")

    # تسجيل نتيجة تلقائي بعد TRADE_DURATION
    if sig.direction != "WAIT" and sig.trade_size > 0:
        tid = f"trade_{time.time_ns()}"
        B._pending_trades[tid] = {
            "entry_price": price, "direction": sig.direction,
            "trade_amount": sig.trade_size,
            "duration": int(os.getenv("TRADE_DURATION", "60")),
            "msg": u.message,
        }
        asyncio.create_task(_auto_check_trade(tid))


async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if B.manager and B.db:
        data = await B.manager.get_full_stats()
        await u.message.reply_text(
            fmt_full_stats(data), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )
    else:
        await u.message.reply_text(
            msg_stats(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )


async def cmd_backtest(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not B.pipeline or not B.pipeline.buffer or len(B.pipeline.buffer.candles) < 30:
        await u.message.reply_text("⚠️ *البيانات غير كافية* — يجب أن يكون البوت شغالاً ولديه 30+ شمعة.", parse_mode=ParseMode.MARKDOWN)
        return
    await u.message.reply_text("🔄 *جارٍ تشغيل الـ Backtesting...*\nقد يستغرق بضع ثوانٍ.", parse_mode=ParseMode.MARKDOWN)
    try:
        candles = B.pipeline.buffer.candles
        engine = BacktestingEngine(
            initial_balance=B.balance,
            payout_pct=B.get_payout(),
            min_score=int(os.getenv("MIN_SCORE", "6")),
        )
        result = await engine.run(list(candles), payout=B.get_payout() / 100.0)
        await u.message.reply_text(engine.result_to_text(result), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await u.message.reply_text(f"❌ *خطأ:* `{str(e)[:200]}`", parse_mode=ParseMode.MARKDOWN)
        log.error("Backtest error: %s", e)


async def cmd_pairs(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "💰 *اختر فئة الأزواج:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_pairs_category(),
    )


async def cmd_payout(u: Update, c: ContextTypes.DEFAULT_TYPE):
    lines = ["💰 *العوائد المتاحة:*\n━━━━━━━━━━━━━━━━━━━━━━━━"]
    otc_pairs = sorted(
        list_pairs(pair_type="otc", min_payout=80.0),
        key=lambda x: B.get_payout(x[0]), reverse=True,
    )
    for key, info in otc_pairs[:15]:
        payout    = B.get_payout(key)
        live_mark = "🟢" if key in B._live_payouts else "🔴"
        active    = "▶️ " if B.symbol == info.quotex_symbol else "   "
        lines.append(f"{active}`{info.display_name}` {live_mark} `{payout:.0f}%`")
    lines.append("\n🟢 = حقيقي من Quotex | 🔴 = تقديري")
    await u.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_setpair(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text(
            "الاستخدام: `/setpair EURUSD-OTC`\nأو `/pairs` لرؤية القائمة",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    key  = c.args[0].replace("-", "_").lower()
    info = get_pair(key) or get_pair(c.args[0])
    if not info:
        await u.message.reply_text(
            f"❌ الزوج `{c.args[0]}` غير موجود.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if B.pipeline:
        apply_pair_to_pipeline(B.pipeline, key)
    payout = B.get_payout(key)
    await u.message.reply_text(
        f"✅ *تم تغيير الزوج*\n"
        f"الزوج: `{info.display_name}`\n"
        f"الرمز: `{info.quotex_symbol}`\n"
        f"العائد: `{payout:.0f}%`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(),
    )


async def cmd_setbalance(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("الاستخدام: `/setbalance 500`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        bal = float(c.args[0])
        if B.pipeline: B.pipeline.data_settings.balance = bal
        if B.manager:  B.manager.stats.balance_current  = bal
        await u.message.reply_text(f"✅ الرصيد: `${bal:.2f}`", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await u.message.reply_text("❌ رقم غير صحيح.")


async def cmd_setduration(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text("الاستخدام: `/setduration 60`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        dur = int(c.args[0])
        if not (30 <= dur <= 300):
            await u.message.reply_text("❌ المدة بين 30 و 300 ثانية.")
            return
        os.environ["TRADE_DURATION"] = str(dur)
        if B.manager: B.manager.duration = dur
        await u.message.reply_text(f"✅ مدة الصفقة: `{dur}` ثانية", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await u.message.reply_text("❌ رقم غير صحيح.")


async def cmd_setscore(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args:
        await u.message.reply_text(
            "الاستخدام: `/setscore 6`\nالنطاق: 1-20 (النقاط من 38)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        sc = int(c.args[0])
        if not (1 <= sc <= 30):
            await u.message.reply_text("❌ النقاط بين 1 و 30.")
            return
        os.environ["MIN_SCORE"] = str(sc)
        if B.manager: B.manager.min_score = sc
        warn = "⚠️ منخفض جداً — صفقات أكثر وخسائر محتملة" if sc < 6 else ""
        await u.message.reply_text(
            f"✅ الحد الأدنى: `{sc}` / 38\n{warn}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except ValueError:
        await u.message.reply_text("❌ رقم غير صحيح.")


async def cmd_mode(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args or c.args[0] not in ("paper", "real"):
        mode = "📋 تجريبي" if B.paper_mode else "💵 حقيقي"
        await u.message.reply_text(
            f"الوضع الحالي: {mode}\n`/mode paper` أو `/mode real`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    B.paper_mode = (c.args[0] == "paper")
    if B.manager: B.manager.paper = B.paper_mode
    label = "📋 تجريبي" if B.paper_mode else "💵 حقيقي ⚠️"
    await u.message.reply_text(
        f"✅ الوضع: *{label}*", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
    )


async def cmd_ai(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(msg_ai_status(), parse_mode=ParseMode.MARKDOWN)


async def cmd_ml(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(msg_ml_status(), parse_mode=ParseMode.MARKDOWN)


async def cmd_journal(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not B.db:
        await u.message.reply_text("⚠️ البوت لم يبدأ بعد.")
        return
    recent = await B.db.get_recent_trades(10)
    if not recent:
        await u.message.reply_text(
            ui_layer.build_log_text(), parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_journal(),
        )
        return
    logs = []
    for t in recent:
        ts = datetime.fromtimestamp(t["opened_at"]) if t.get("opened_at") else None
        logs.append({
            "result": t["result"],
            "symbol": t["symbol"],
            "profit": t["profit"],
            "opened_at": ts,
        })
    await u.message.reply_text(
        ui_layer.build_log_text(logs), parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_journal(),
    )


async def cmd_export(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not B.db:
        await u.message.reply_text("⚠️ البوت لم يبدأ بعد.")
        return
    path = "trades_export.csv"
    await B.db.export_csv(path)
    try:
        with open(path, "rb") as f:
            await u.message.reply_document(
                f,
                filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                caption  = "📄 تصدير الصفقات الكاملة",
            )
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")


async def cmd_report(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not B.db_reporter:
        await u.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
        return
    weekly = await B.db_reporter.report_weekly()
    best = await B.db_reporter.report_best_pairs()
    await u.message.reply_text(
        f"{weekly}\n\n{best}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_scan(u: Update, c: ContextTypes.DEFAULT_TYPE):
    from shared.pair_scanner import scan_top_trade_setups
    await u.message.reply_text("🔍 *جارٍ مسح أفضل الأزواج...*", parse_mode=ParseMode.MARKDOWN)
    try:
        results = await scan_top_trade_setups(
            get_payout_fn=B.get_payout,
            pipeline=B.pipeline,
            market=B._selected_market,
            top_n=5,
            balance=B.balance,
        )
        if not results:
            await u.message.reply_text("📭 لا توجد نتائج — جرب لاحقاً")
            return
        lines = ["🔍 *أفضل 5 أزواج للتداول:*\n━━━━━━━━━━━━━━━━━━"]
        for r in results:
            emoji = "🟢" if r["direction"] == "call" else "🔴" if r["direction"] == "put" else "⚪"
            lines.append(
                f"{emoji} {r['display_name']}\n"
                f"  • الاتجاه: {r['direction']} | نقاط: {r['score']}\n"
                f"  • الثقة: {r['confidence']:.0f}% | Payout: {r['payout']:.0f}%\n"
                f"  • {r['reasons'][0] if r['reasons'] else ''}"
            )
        await u.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await u.message.reply_text(f"❌ خطأ في المسح: {e}")
        log.error("Scan error: %s", e)


async def cmd_accuracy(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not B.db_reporter:
        await u.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
        return
    report = await B.db_reporter.report_model_accuracy()
    await u.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)


async def cmd_optimize(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not B.db:
        await u.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
        return
    await u.message.reply_text("🔄 *جارٍ التحسين الأسبوعي...*", parse_mode=ParseMode.MARKDOWN)
    try:
        report = await B.optimizer.weekly_optimize(B.db, B.advanced_ai)
        await u.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")
        log.error("Optimize error: %s", e)


async def cmd_portfolio(u: Update, c: ContextTypes.DEFAULT_TYPE):
    summary = B.portfolio.summary()
    await u.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════
#  معالج أزرار Inline
# ══════════════════════════════════════════════════════════

async def on_button(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    d = q.data
    B.chat_id = u.effective_chat.id

    # ── Online learning helper ─────────────────────────
    async def _learn(outcome: str, profit: float):
        if not B.advanced_ai:
            return
        try:
            candles = B.pipeline.buffer.candles if B.pipeline else []
            if len(candles) < 5:
                return
            last = candles[-1]
            features = [last.close, last.high, last.low, last.open, last.volume,
                        last.close - last.open, last.high - last.low,
                        last.close / (candles[-2].close or 1) - 1]
            B.advanced_ai.learn_from_trade({
                "result": outcome,
                "profit": profit,
                "amount": abs(profit),
                "pair": B.symbol,
                "features": features,
            })
        except Exception:
            pass

    # ── تشغيل ──────────────────────────────────────────
    if d in ("start", "start_bot"):
        if B.is_running:
            await q.message.reply_text("⚠️ البوت يعمل بالفعل.", reply_markup=kb_main())
            return
        msg_wait = await q.message.reply_text("🔄 جاري تشغيل البوت...")
        symbol_key = B._pending_pair
        B._pending_pair = None
        ok, detail = await do_start(symbol_key=symbol_key)
        try:
            await msg_wait.delete()
        except Exception:
            pass
        if ok:
            await q.message.reply_text(
                f"✅ *تم إعادة التشغيل*\n{detail}\n\n"
                f"الزوج: `{B.symbol}`\n",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(),
            )
        else:
            await q.message.reply_text(
                f"❌ *فشل التشغيل*\n{detail}\n\nتحقق من `.env` وأعد المحاولة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(),
            )

    # ── إيقاف ──────────────────────────────────────────
    elif d == "stop":
        await do_stop()
        await q.message.reply_text(
            "⏹ *تم إيقاف البوت*\nيمكنك تشغيله مجدداً في أي وقت.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(),
        )

    # ── تحليل فوري / الإشارة التالية ──────────────────
    elif d == "signal":
        candles = B.pipeline.buffer.candles if B.pipeline else []
        price   = B.price
        if price <= 0 and candles:
            price = candles[-1].close

        if len(candles) < B.min_candles:
            if B.is_running:
                base    = price if price > 0 else 1.1000
                candles = _make_demo_candles(60, base)
                price   = candles[-1].close
            else:
                await q.message.reply_text(
                    "⏳ *البوت متوقف* — اضغط تشغيل أولاً",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_main(),
                )
                return
        else:
            price = price if price > 0 else candles[-1].close

        sig = ConfluenceEngine(candles, price, B.get_payout(), B.balance).run()
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            closes = [c.close for c in candles]
            regime = B.regime_filter.analyze(highs, lows, closes)
            B._last_regime = regime
            sig.confidence = B.regime_filter.adjust_signal_confidence(sig.confidence, regime)
            sig.reasons.append(f"🌍 {regime.get('regime_label', '')} | {regime.get('strategy_label', '')}")
        except Exception:
            pass
        # Gemini verification (ai_filter مع fallback إلى gemini_verifier)
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key and len(candles) >= 10:
            try:
                await q.message.reply_text("🔍 *AI Filter Verifying...* ⏳", parse_mode=ParseMode.MARKDOWN)
                from ai_filter import analyze_quotex_signal, _analyze_gemini_core
                from gemini_verifier import generate_chart_image as _gc, _build_technical_report as _br
                report = _br(sig, candles, B.symbol)
                decision, gemini_text, _ = await analyze_quotex_signal(B.symbol, report)
                if decision == "CANCEL":
                    await q.message.reply_text(
                        f"🛑 *تم إلغاء الإشارة* — AI Filter رفضها\n📋 {gemini_text[:600]}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=ui_layer.build_signal_keyboard(is_running=True),
                    )
                    return
                elif decision == "CONFIRMED":
                    sig.reasons.append("🤖 AI Filter: CONFIRMED (بصري + رقمي)")
                    sig.confidence = min(95, sig.confidence * 1.05)
            except Exception as e:
                log.warning("AI Filter skipped: %s", e)
        await _send_signal_msg(q.message, sig, sid="manual")
        if sig.direction != "WAIT" and sig.trade_size > 0:
            tid = f"trade_{time.time_ns()}"
            B._pending_trades[tid] = {
                "entry_price": price, "direction": sig.direction,
                "trade_amount": sig.trade_size,
                "duration": int(os.getenv("TRADE_DURATION", "60")),
                "msg": q.message,
            }
            asyncio.create_task(_auto_check_trade(tid))

    # ── الحالة ─────────────────────────────────────────
    elif d == "status":
        await q.message.reply_text(
            msg_status(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )

    elif d == "nav_status":
        await q.message.reply_text(
            msg_status(), parse_mode=ParseMode.MARKDOWN, reply_markup=ui_layer.build_status_keyboard()
        )

    elif d == "nav_stats":
        if B.manager and B.db:
            data = await B.manager.get_full_stats()
            await q.message.reply_text(
                fmt_full_stats(data), parse_mode=ParseMode.MARKDOWN,
                reply_markup=ui_layer.build_stats_keyboard()
            )
        else:
            await q.message.reply_text(
                msg_stats(), parse_mode=ParseMode.MARKDOWN,
                reply_markup=ui_layer.build_stats_keyboard()
            )

    # ── الإحصائيات ─────────────────────────────────────
    elif d == "stats":
        if B.manager and B.db:
            data = await B.manager.get_full_stats()
            await q.message.reply_text(
                fmt_full_stats(data), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
            )
        else:
            await q.message.reply_text(
                msg_stats(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
            )

    # ── قائمة الأزواج ──────────────────────────────────
    elif d == "pairs_menu":
        await q.message.reply_text(
            "💰 *اختر فئة الأزواج:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_category(),
        )

    elif d == "pairs_video":
        video_keys = [
            "EURUSD_otc","EURGBP_otc","EURNZD_otc","USDPKR_otc",
            "USDIDR_otc","USDINR_otc","NZDCHF_otc","GBPUSD_otc",
        ]
        pairs = [(k, QUOTEX_PAIRS[k]) for k in video_keys if k in QUOTEX_PAIRS]
        await q.message.reply_text(
            "⭐ *أزواج payout عالٍ:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_list(pairs, "pairs_menu"),
        )

    elif d == "pairs_major_otc":
        pairs = list_pairs(pair_type="otc", category="major")
        pairs_s = sorted(pairs, key=lambda x: B.get_payout(x[0]), reverse=True)
        await q.message.reply_text(
            "🌍 *الأزواج الرئيسية OTC:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_list(pairs_s, "pairs_menu"),
        )

    elif d == "pairs_exotic_otc":
        pairs = list_pairs(pair_type="otc", category="exotic")
        pairs_s = sorted(pairs, key=lambda x: B.get_payout(x[0]), reverse=True)
        await q.message.reply_text(
            "💎 *الأزواج الغريبة OTC:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_list(pairs_s, "pairs_menu"),
        )

    elif d == "pairs_all_otc":
        pairs = list_pairs(pair_type="otc", min_payout=75.0)
        pairs_s = sorted(pairs, key=lambda x: B.get_payout(x[0]), reverse=True)
        await q.message.reply_text(
            "🔢 *كل الأزواج OTC:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_list(pairs_s, "pairs_menu"),
        )

    elif d == "pairs_live":
        pairs = list_pairs(pair_type="regular")
        await q.message.reply_text(
            "🌐 *الأزواج الحقيقية (Live):*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_list(pairs, "pairs_menu"),
        )

    elif d == "pairs_otc":
        pairs_s = sorted(list_pairs(pair_type="otc"), key=lambda x: B.get_payout(x[0]), reverse=True)
        await q.message.reply_text(
            "🔵 *أزواج OTC:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_list(pairs_s, "pairs_menu"),
        )

    elif d == "pairs_regular":
        pairs = list_pairs(pair_type="regular")
        await q.message.reply_text(
            "📊 *الأزواج العادية:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_pairs_list(pairs, "pairs_menu"),
        )

    # ── اختيار زوج ─────────────────────────────────────
    elif d.startswith("setpair_"):
        key  = d.replace("setpair_", "")
        info = get_pair(key)
        if info:
            B._pending_pair = key
            if B.pipeline:
                apply_pair_to_pipeline(B.pipeline, key)
            payout = B.get_payout(key)
            await q.message.reply_text(
                f"✅ *تم تغيير الزوج*\n`{info.display_name}` | `{payout:.0f}%`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(),
            )

    # ── تحديث payout ───────────────────────────────────
    elif d == "refresh_payout":
        await q.message.reply_text("🔄 جاري جلب العوائد الحقيقية من Quotex...")
        await B.fetch_live_payouts()
        count = len(B._live_payouts)
        await q.message.reply_text(
            f"✅ تم تحديث العوائد لـ {count} زوج" if count > 0
            else "⚠️ لم يُجلب أي payout — تأكد من الاتصال بـ Quotex",
            reply_markup=kb_settings(),
        )

    # ── الإعدادات ──────────────────────────────────────
    elif d == "settings":
        await q.message.reply_text(
            msg_settings(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_settings()
        )

    # ── قائمة المدة ────────────────────────────────────
    elif d == "duration_menu":
        cur = int(os.getenv("TRADE_DURATION", "60"))
        await q.message.reply_text(
            f"⏱ *اختيار مدة الصفقة*\nالحالية: `{cur}` ثانية",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_duration(),
        )

    # ── تغيير المدة ────────────────────────────────────
    elif d.startswith("dur_"):
        dur = int(d.replace("dur_", ""))
        if 30 <= dur <= 300:
            os.environ["TRADE_DURATION"] = str(dur)
            if B.manager: B.manager.duration = dur
            await q.message.reply_text(
                f"✅ *تم تغيير المدة*\n⏱ `{dur}` ثانية",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_settings(),
            )

    # ── حالة AI ────────────────────────────────────────
    elif d == "ai_status":
        await q.message.reply_text(msg_ai_status(), parse_mode=ParseMode.MARKDOWN)

    # ── حالة ML ────────────────────────────────────────
    elif d == "ml_status":
        await q.message.reply_text(msg_ml_status(), parse_mode=ParseMode.MARKDOWN)

    # ── تبديل الوضع ────────────────────────────────────
    elif d == "toggle_mode":
        B.paper_mode = not B.paper_mode
        if B.manager: B.manager.paper = B.paper_mode
        label = "📋 تجريبي" if B.paper_mode else "💵 حقيقي ⚠️"
        await q.message.reply_text(
            f"✅ الوضع الآن: *{label}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(),
        )

    # ── رجوع ───────────────────────────────────────────
    elif d == "back":
        await q.message.reply_text(
            msg_welcome(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )

    elif d == "nav_dashboard":
        await q.message.reply_text(
            msg_welcome(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )

    # ── تعليمات ────────────────────────────────────────
    elif d == "help":
        await q.message.reply_text(
            msg_help(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main()
        )

    # ── سجل الصفقات ────────────────────────────────────
    elif d == "journal":
        await cmd_journal(u, c)

    elif d == "export_journal":
        await cmd_export(u, c)

    # ── noop ───────────────────────────────────────────
    elif d == "noop":
        await q.answer()

    # ── شاشة التداول اليدوي ───────────────────────────
    elif d == "nav_trading":
        await q.message.reply_text(
            ui_layer.build_trading_text(B.symbol),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_trading_keyboard(
                B._selected_market, B._selected_asset
            ),
        )

    # ── شاشة الأزواج (من التداول اليدوي) ─────────────
    elif d == "nav_pairs":
        pairs = _get_pairs_for_market(B._selected_market, B._selected_asset)
        page = B._pairs_page
        await q.message.reply_text(
            ui_layer.build_pairs_text(B.symbol, page=page),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_pairs_keyboard(pairs, B.get_payout, B.symbol, {}, page=page),
        )

    # ── شاشة انتهاء المدة ────────────────────────────
    elif d == "nav_expiry":
        dur = int(os.getenv("TRADE_DURATION", "60"))
        await q.message.reply_text(
            ui_layer.build_expiry_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_expiry_keyboard(dur),
        )

    # ── شاشة التداول التلقائي ────────────────────────
    elif d == "nav_auto":
        dur = int(os.getenv("TRADE_DURATION", "60"))
        trade_size = float(os.getenv("TRADE_AMOUNT", "10"))
        await q.message.reply_text(
            ui_layer.build_auto_text(B.balance, B.symbol, dur, trade_size),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_auto_keyboard(B.is_running),
        )

    # ── اختيار نوع السوق (Trading screen) ─────────────
    elif d in ("market_otc", "market_live"):
        B._selected_market = d.split("_")[1]
        await q.message.edit_text(
            ui_layer.build_trading_text(B.symbol),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_trading_keyboard(
                B._selected_market, B._selected_asset
            ),
        )

    elif d.startswith("asset_") and d.split("_")[1] in ("forex", "crypto", "stocks", "indices", "commodities"):
        B._selected_asset = d.split("_")[1]
        await q.message.edit_text(
            ui_layer.build_trading_text(B.symbol),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_trading_keyboard(
                B._selected_market, B._selected_asset
            ),
        )

    # ── اختيار الزوج (شاشة الأزواج الجديدة) ─────────
    elif d.startswith("pair_"):
        key = d.replace("pair_", "")
        info = get_pair(key)
        if info:
            B._pending_pair = key
            if B.pipeline:
                apply_pair_to_pipeline(B.pipeline, key)
            payout = B.get_payout(key)
            dur = int(os.getenv("TRADE_DURATION", "60"))
            await q.message.reply_text(
                f"✅ *تم تغيير الزوج*\n`{info.display_name}` | `{payout:.0f}%`\n"
                f"⏳ اختر المدة للبدء",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ui_layer.build_expiry_keyboard(dur),
            )
        else:
            await q.message.reply_text(f"❌ الزوج `{key}` غير موجود", parse_mode=ParseMode.MARKDOWN)

    # ── التنقل بين صفحات الأزواج ─────────────────────
    elif d == "pairs_prev":
        B._pairs_page = max(0, B._pairs_page - 1)
        pairs = _get_pairs_for_market(B._selected_market, B._selected_asset)
        await q.message.edit_text(
            ui_layer.build_pairs_text(B.symbol, page=B._pairs_page),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_pairs_keyboard(pairs, B.get_payout, B.symbol, {}, page=B._pairs_page),
        )

    elif d == "pairs_next":
        pairs = _get_pairs_for_market(B._selected_market, B._selected_asset)
        total_pages = max(1, (len(pairs) + 8 - 1) // 8)
        B._pairs_page = min(B._pairs_page + 1, total_pages - 1)
        await q.message.edit_text(
            ui_layer.build_pairs_text(B.symbol, page=B._pairs_page),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_pairs_keyboard(pairs, B.get_payout, B.symbol, {}, page=B._pairs_page),
        )

    # ── تأكيد وبدء التحليل اليدوي ────────────────────
    elif d == "confirm_start":
        await q.message.reply_text(
            f"🧠 *AI Analyzing...* ⏳\n"
            f"الأصل: `{B.symbol if B.pipeline else '—'}` — التايم فريم: `1 minute`\n"
            f"⏳ جاري تحليل السوق...",
            parse_mode=ParseMode.MARKDOWN,
        )

        candles = B.pipeline.buffer.candles if B.pipeline else []
        price = B.price
        if price <= 0 and candles:
            price = candles[-1].close
        if len(candles) < B.min_candles:
            base = price if price > 0 else 1.1000
            candles = _make_demo_candles(60, base)
            price = candles[-1].close
        else:
            price = price if price > 0 else candles[-1].close

        await asyncio.sleep(2)

        # 1. التحليل الأساسي
        sig = ConfluenceEngine(candles, price, B.get_payout(), B.balance).run()

        # 2. تحليل حالة السوق (ADX + DI+/DI-)
        try:
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            closes = [c.close for c in candles]
            regime = B.regime_filter.analyze(highs, lows, closes)
            B._last_regime = regime
            # تعديل الثقة حسب حالة السوق
            sig.confidence = B.regime_filter.adjust_signal_confidence(sig.confidence, regime)
            sig.reasons.append(f"🌍 {regime.get('regime_label', '')} | {regime.get('strategy_label', '')}")
        except Exception:
            pass

        # 3. التحقق عبر AI Filter (Selenium Quotex > fallback matplotlib)
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key and len(candles) >= 10:
            try:
                await q.message.reply_text("🔍 *AI Filter Verifying...* ⏳", parse_mode=ParseMode.MARKDOWN)
                from ai_filter import analyze_quotex_signal, _analyze_gemini_core
                from gemini_verifier import _build_technical_report as _br
                report = _br(sig, candles, B.symbol)
                decision, gemini_text, _ = await analyze_quotex_signal(B.symbol, report)
                if decision == "CANCEL":
                    await q.message.reply_text(
                        f"🛑 *تم إلغاء الإشارة* — AI Filter رفضها\n📋 {gemini_text[:600]}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=ui_layer.build_signal_keyboard(is_running=True),
                    )
                    return
                elif decision == "CONFIRMED":
                    sig.reasons.append("🤖 AI Filter: CONFIRMED (بصري + رقمي)")
                    sig.confidence = min(95, sig.confidence * 1.05)
            except Exception as e:
                log.warning("AI Filter skipped: %s", e)

        await _send_signal_msg(q.message, sig, sid="manual")
        if sig.direction != "WAIT" and sig.trade_size > 0:
            tid = f"trade_{time.time_ns()}"
            B._pending_trades[tid] = {
                "entry_price": price, "direction": sig.direction,
                "trade_amount": sig.trade_size,
                "duration": int(os.getenv("TRADE_DURATION", "60")),
                "msg": q.message,
            }
            asyncio.create_task(_auto_check_trade(tid))

    # ── إعدادات جديدة ────────────────────────────────
    elif d == "nav_settings":
        await q.message.reply_text(
            msg_settings(), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_settings()
        )

    elif d == "settings_alerts":
        await q.message.reply_text(
            ui_layer.build_settings_alerts_text(
                B.get_payout(),
                int(os.getenv("TRADE_DURATION", "60")),
                len(B._live_payouts) > 0,
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_settings_alerts_keyboard(),
        )

    elif d == "settings_ai":
        await q.message.reply_text(
            ui_layer.build_settings_ai_text(ai_enabled(), B.ml is not None),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_settings_ai_keyboard(),
        )

    elif d == "settings_signals":
        await q.message.reply_text(
            ui_layer.build_settings_signals_text(
                B.symbol,
                int(os.getenv("MIN_SCORE", "6")),
                B.paper_mode,
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_settings_signals_keyboard(),
        )

    elif d in ("settings_amounts", "settings_connection", "settings_lang"):
        await q.message.reply_text(
            "⚙️ *قيد التطوير*\nهذا القسم قيد الإعداد.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_settings(),
        )

    elif d == "settings_reset":
        B._selected_market = "otc"
        B._selected_asset = "forex"
        B._pairs_page = 0
        await q.message.reply_text(
            "✅ *تمت إعادة ضبط الإعدادات*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_settings(),
        )

    # ── تصفية الإحصائيات ─────────────────────────────
    elif d in ("stats_day", "stats_week", "stats_month"):
        if B.manager and B.db:
            data = await B.manager.get_full_stats()
            await q.message.reply_text(
                fmt_full_stats(data), parse_mode=ParseMode.MARKDOWN,
                reply_markup=ui_layer.build_stats_keyboard()
            )
        else:
            await q.message.reply_text(
                msg_stats(), parse_mode=ParseMode.MARKDOWN,
                reply_markup=ui_layer.build_stats_keyboard()
            )

    # ── مسح السجل ────────────────────────────────────
    elif d == "clear_log":
        if B.db:
            await B.db.clear_trades()
        await q.message.reply_text("🗑️ *تم مسح سجل الصفقات*", parse_mode=ParseMode.MARKDOWN)

    # ── سجل الصفقات ──────────────────────────────────
    elif d == "nav_log":
        if not B.db:
            await q.message.reply_text("⚠️ البوت لم يبدأ بعد.")
        else:
            recent = await B.db.get_recent_trades(10)
            if not recent:
                await q.message.reply_text(
                    ui_layer.build_log_text(), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_journal(),
                )
            else:
                logs = []
                for t in recent:
                    ts = datetime.fromtimestamp(t["opened_at"]) if t.get("opened_at") else None
                    logs.append({"result": t["result"], "symbol": t["symbol"], "profit": t["profit"], "opened_at": ts})
                await q.message.reply_text(
                    ui_layer.build_log_text(logs), parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_journal(),
                )

    # ── إيقاف التلقائي ───────────────────────────────
    elif d == "stop_auto":
        B.auto_mode = False
        await do_stop()
        await q.message.reply_text(
            "⏹ *تم إيقاف التداول التلقائي*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(),
        )

    # ── تشغيل التلقائي ───────────────────────────────
    elif d == "auto_mode":
        B.auto_mode = True
        if not B.is_running:
            msg_wait = await q.message.reply_text("🔄 جاري تشغيل التداول التلقائي...")
            symbol_key = B._pending_pair
            B._pending_pair = None
            ok, detail = await do_start(symbol_key=symbol_key)
            try:
                await msg_wait.delete()
            except Exception:
                pass
            if not ok:
                await q.message.reply_text(
                    f"❌ *فشل التشغيل*\n{detail}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=ui_layer.build_auto_keyboard(False),
                )
                return
        await q.message.reply_text(
            "🤖 *التداول التلقائي نشط*\n سيختار البوت أفضل الإشارات ويتداول تلقائياً.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ui_layer.build_auto_keyboard(B.is_running),
        )

    # ── أوامر جديدة من لوحة التحكم ─────────────────────
    elif d == "cmd_scan":
        from shared.pair_scanner import scan_top_trade_setups
        await q.message.reply_text("🔍 *جارٍ مسح أفضل الأزواج...*", parse_mode=ParseMode.MARKDOWN)
        try:
            results = await scan_top_trade_setups(
                get_payout_fn=B.get_payout, pipeline=B.pipeline,
                market=B._selected_market, top_n=5, balance=B.balance,
            )
            if not results:
                await q.message.reply_text("📭 لا توجد نتائج — جرب لاحقاً")
            else:
                lines = ["🔍 *أفضل 5 أزواج للتداول:*\n━━━━━━━━━━━━━━━━━━"]
                for r in results:
                    emoji = "🟢" if r["direction"] == "call" else "🔴" if r["direction"] == "put" else "⚪"
                    lines.append(f"{emoji} {r['display_name']}\n  • الاتجاه: {r['direction']} | نقاط: {r['score']}\n  • الثقة: {r['confidence']:.0f}% | Payout: {r['payout']:.0f}%\n  • {r['reasons'][0] if r['reasons'] else ''}")
                await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await q.message.reply_text(f"❌ خطأ في المسح: {e}")
            log.error("Scan error: %s", e)
    elif d == "cmd_report":
        if not B.db_reporter:
            await q.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
        else:
            weekly = await B.db_reporter.report_weekly()
            best = await B.db_reporter.report_best_pairs()
            await q.message.reply_text(f"{weekly}\n\n{best}", parse_mode=ParseMode.MARKDOWN)
    elif d == "cmd_accuracy":
        if not B.db_reporter:
            await q.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
        else:
            report = await B.db_reporter.report_model_accuracy()
            await q.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)
    elif d == "cmd_portfolio":
        summary = B.portfolio.summary()
        await q.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)
    elif d == "cmd_optimize":
        if not B.db:
            await q.message.reply_text("⚠️ قاعدة البيانات غير متصلة")
        else:
            await q.message.reply_text("🔄 *جارٍ التحسين الأسبوعي...*", parse_mode=ParseMode.MARKDOWN)
            try:
                report = await B.optimizer.weekly_optimize(B.db, B.advanced_ai)
                await q.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                await q.message.reply_text(f"❌ {e}")
                log.error("Optimize error: %s", e)

    # ── تسجيل النتائج تلقائياً (تم استبدال الأزرار اليدوية) ──
    elif d.startswith("win_") or d.startswith("loss_") or d.startswith("skip_"):
        await q.message.reply_text(
            "✅ *التسجيل تلقائي الآن*\n"
            "النتيجة تُحتسب بعد انتهاء مدة الصفقة (TRADE_DURATION) بدون تدخل يدوي.",
            parse_mode=ParseMode.MARKDOWN,
        )


def _get_pairs_for_market(market: str, asset: str = "forex"):
    if market == "otc":
        return list_pairs(pair_type="otc")
    type_map = {"forex": "regular", "crypto": "crypto", "stocks": "stock", "commodities": "commodity"}
    pt = type_map.get(asset)
    if pt:
        return list_pairs(pair_type=pt)
    return [(k, v) for k, v in list_pairs() if v.pair_type != "otc"]


# ══════════════════════════════════════════════════════════
#  نقطة التشغيل الرئيسية
# ══════════════════════════════════════════════════════════

def main():
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token or token in ("ضع_توكن_البوت_هنا", ""):
        print("❌ TELEGRAM_TOKEN غير موجود في .env")
        print("   1. افتح @BotFather في Telegram")
        print("   2. أرسل /newbot")
        print("   3. انسخ التوكن إلى .env")
        sys.exit(1)

    quotex_email = os.getenv("QUOTEX_EMAIL", "")
    if not quotex_email or quotex_email == "بريدك_في_كيوتكس":
        print("⚠️  QUOTEX_EMAIL غير محدد — الاتصال بـ Quotex سيفشل")

    # ─── طباعة ملخص التشغيل ───
    print("=" * 58)
    print("  🤖 بوت التداول الذكي v3.0")
    print(f"  الوضع: {'📋 تجريبي' if B.paper_mode else '💵 حقيقي'}")
    print(f"  الأزواج: {len(QUOTEX_PAIRS)}")
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    print(f"  Gemini AI: {'مفعّل ✅' if gemini_key and len(gemini_key) >= 10 else 'معطّل ❌ (أضف GEMINI_API_KEY في .env)'}")
    print(f"  Advanced AI: {'متاح' if ADV_AI_AVAILABLE else 'معطّل (يتطلب sklearn)'}")
    print(f"  نقاط Confluence: 0-38 (24 مكوّن)")
    print(f"  WebApp: http://127.0.0.1:8081 (شغّل run_webapp.py منفصلاً)")
    print("=" * 58)

    print("🔄 الاتصال بـ Telegram...")
    try:
        _req = HTTPXRequest(connect_timeout=15, read_timeout=15)
        app = Application.builder().token(token).request(_req).build()
        B.app = app
    except Exception as e:
        print(f"❌ فشل الاتصال بـ Telegram: {e}")
        sys.exit(1)

    # ─── تسجيل الأوامر ───
    commands = [
        ("start",       cmd_start),
        ("help",        cmd_help),
        ("status",      cmd_status),
        ("signal",      cmd_signal),
        ("stats",       cmd_stats),
        ("pairs",       cmd_pairs),
        ("payout",      cmd_payout),
        ("setpair",     cmd_setpair),
        ("setbalance",  cmd_setbalance),
        ("setduration", cmd_setduration),
        ("setscore",    cmd_setscore),
        ("mode",        cmd_mode),
        ("ai",          cmd_ai),
        ("ml",          cmd_ml),
        ("export",      cmd_export),
        ("journal",     cmd_journal),
        ("report",      cmd_report),
        ("scan",        cmd_scan),
        ("accuracy",    cmd_accuracy),
        ("backtest",    cmd_backtest),
        ("optimize",    cmd_optimize),
        ("portfolio",   cmd_portfolio),
    ]
    for cmd, fn in commands:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(on_button))

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        log.error("❌ خطأ: %s", context.error)
    app.add_error_handler(error_handler)

    async def post_init(application: Application):
        try:
            await application.bot.set_my_commands([
                BotCommand(cmd, desc) for cmd, desc in [
                    ("start",       "فتح البوت — تشغيل تلقائي"),
                    ("status",      "الحالة التفصيلية"),
                    ("signal",      "تحليل فوري للسوق"),
                    ("stats",       "الإحصائيات الكاملة"),
                    ("pairs",       "قائمة الأزواج"),
                    ("payout",      "عرض عوائد الأزواج"),
                    ("backtest",    "اختبار على الشموع الحالية"),
                    ("scan",        "مسح أفضل الأزواج"),
                    ("help",        "قائمة الأوامر"),
                ]
            ])
        except Exception as e:
            log.warning("post_init set_my_commands فشل: %s", e)
        print("✅ البوت شغال — افتح Telegram وأرسل /start")

    async def post_shutdown(application: Application):
        if B.is_running:
            await do_stop()

    app.post_init = post_init
    app.post_shutdown = post_shutdown
    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        log.error("Telegram polling error: %s", e)
        print(f"\n❌ خطأ في تشغيل البوت: {e}")
    finally:
        if B.is_running:
            try:
                asyncio.run(do_stop())
            except Exception as e:
                log.error("do_stop error: %s", e)
        log.info("Bot terminated")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 تم الإيقاف بيد المستخدم")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ خطأ غير متوقع: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

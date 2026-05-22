"""
=============================================================
  منفذ الصفقات + قاعدة البيانات
  Trade Executor + Database Layer

  المكونات:
  1. Database        — SQLite لحفظ كل صفقة وإشارة
  2. TradeExecutor   — تنفيذ الصفقة على Quotex
  3. TradeManager    — يربط الإشارة → التنفيذ → النتيجة → DB
  4. SessionStats    — إحصائيات الجلسة الحية
=============================================================
"""

import asyncio
import inspect
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Callable, Optional
import aiosqlite

from bot_algorithms import Signal
from data_layer import DataPipeline
from shared.execution_service import TradeExecutionService, build_candidate_assets
from shared.asset_mapping import quotex_symbol_to_api_symbol

log = logging.getLogger("TradeExecutor")

DB_PATH = os.getenv("DB_PATH", "trades.db")


# ─────────────────────────────────────────────
#  هياكل البيانات
# ─────────────────────────────────────────────

class TradeResult(Enum):
    WIN      = "win"
    LOSS     = "loss"
    TIE      = "tie"
    PENDING  = "pending"
    SKIPPED  = "skipped"
    ERROR    = "error"


@dataclass
class TradeRecord:
    signal_direction: str
    symbol:           str
    payout:           float
    trade_size:       float
    score:            int
    confidence:       float
    entry_price:      float
    reasons:          str          # JSON string
    opened_at:        float = field(default_factory=time.time)
    closed_at:        float = 0.0
    exit_price:       float = 0.0
    result:           str   = TradeResult.PENDING.value
    profit:           float = 0.0
    trade_id:         str   = ""   # ID من Quotex
    db_id:            int   = 0


@dataclass
class SessionStats:
    balance_start:    float = 0.0
    balance_current:  float = 0.0
    total_signals:    int   = 0
    trades_opened:    int   = 0
    wins:             int   = 0
    losses:           int   = 0
    ties:             int   = 0
    skipped:          int   = 0
    consecutive_wins:  int  = 0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    session_start:    float = field(default_factory=time.time)

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        return (self.wins / decided * 100) if decided > 0 else 0.0

    @property
    def net_profit(self) -> float:
        return self.balance_current - self.balance_start

    @property
    def profit_pct(self) -> float:
        if self.balance_start <= 0:
            return 0.0
        return (self.net_profit / self.balance_start) * 100

    @property
    def uptime_str(self) -> str:
        secs = int(time.time() - self.session_start)
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


# ─────────────────────────────────────────────
#  1. قاعدة البيانات
# ─────────────────────────────────────────────

class Database:
    """
    SQLite async — يحفظ كل إشارة وصفقة ونتيجة.
    يعطيك إحصائيات حقيقية لتحسين البوت.
    """

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._create_tables()
        log.info("🗄️  قاعدة البيانات جاهزة: %s", self.path)

    async def _create_tables(self):
        await self._db.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id         TEXT,
            symbol           TEXT NOT NULL,
            direction        TEXT NOT NULL,
            payout           REAL,
            trade_size       REAL,
            score            INTEGER,
            confidence       REAL,
            entry_price      REAL,
            exit_price       REAL,
            reasons          TEXT,
            result           TEXT DEFAULT 'pending',
            profit           REAL DEFAULT 0,
            opened_at        REAL,
            closed_at        REAL,
            created_date     TEXT
        );

        CREATE TABLE IF NOT EXISTS signals (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol           TEXT,
            direction        TEXT,
            score            INTEGER,
            confidence       REAL,
            trade_executed   INTEGER DEFAULT 0,
            skip_reason      TEXT,
            created_at       REAL,
            created_date     TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_summary (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            date             TEXT UNIQUE,
            trades           INTEGER DEFAULT 0,
            wins             INTEGER DEFAULT 0,
            losses           INTEGER DEFAULT 0,
            win_rate         REAL DEFAULT 0,
            net_profit       REAL DEFAULT 0,
            balance_end      REAL DEFAULT 0,
            updated_at       REAL
        );

        CREATE INDEX IF NOT EXISTS idx_trades_date   ON trades(created_date);
        CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_trades_result ON trades(result);
        """)
        await self._db.commit()

    # ── كتابة ─────────────────────────────────

    async def save_trade(self, trade: TradeRecord) -> int:
        today = date.today().isoformat()
        cur = await self._db.execute("""
            INSERT INTO trades
            (trade_id, symbol, direction, payout, trade_size, score,
             confidence, entry_price, reasons, result, profit,
             opened_at, created_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trade.trade_id, trade.symbol, trade.signal_direction,
            trade.payout, trade.trade_size, trade.score,
            trade.confidence, trade.entry_price, trade.reasons,
            trade.result, trade.profit, trade.opened_at, today
        ))
        await self._db.commit()
        return cur.lastrowid

    async def update_trade_result(self, db_id: int,
                                   result: str, profit: float,
                                   exit_price: float = 0.0):
        await self._db.execute("""
            UPDATE trades
            SET result=?, profit=?, exit_price=?, closed_at=?
            WHERE id=?
        """, (result, profit, exit_price, time.time(), db_id))
        await self._db.commit()

    async def save_signal(self, signal: Signal, symbol: str,
                           executed: bool, skip_reason: str = "") -> int:
        today = date.today().isoformat()
        cur = await self._db.execute("""
            INSERT INTO signals
            (symbol, direction, score, confidence,
             trade_executed, skip_reason, created_at, created_date)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            symbol, signal.direction, signal.score, signal.confidence,
            1 if executed else 0, skip_reason, time.time(), today
        ))
        await self._db.commit()
        return cur.lastrowid

    # ── قراءة ─────────────────────────────────

    async def get_today_stats(self) -> dict:
        today = date.today().isoformat()
        cur = await self._db.execute("""
            SELECT
                COUNT(*)                              AS total,
                SUM(CASE WHEN result='win'  THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) AS losses,
                SUM(profit)                           AS net_profit,
                AVG(score)                            AS avg_score,
                AVG(confidence)                       AS avg_confidence
            FROM trades
            WHERE created_date=? AND result != 'pending'
        """, (today,))
        row = await cur.fetchone()
        if not row or row["total"] == 0:
            return {"total":0,"wins":0,"losses":0,"net_profit":0.0,
                    "win_rate":0.0,"avg_score":0.0,"avg_confidence":0.0}
        total = row["total"] or 0
        wins  = row["wins"]  or 0
        losses = row["losses"] or 0
        return {
            "total":         total,
            "wins":          wins,
            "losses":        losses,
            "net_profit":    round(row["net_profit"] or 0, 2),
            "win_rate":      round(wins / (wins+losses) * 100, 1) if (wins+losses) > 0 else 0.0,
            "avg_score":     round(row["avg_score"] or 0, 1),
            "avg_confidence": round(row["avg_confidence"] or 0, 1),
        }

    async def get_best_symbols(self, days: int = 7) -> list:
        cur = await self._db.execute("""
            SELECT symbol,
                   COUNT(*) AS total,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) AS wins,
                   SUM(profit) AS net_profit
            FROM trades
            WHERE result != 'pending'
              AND opened_at > ?
            GROUP BY symbol
            ORDER BY wins*1.0/COUNT(*) DESC
            LIMIT 5
        """, (time.time() - days * 86400,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_recent_trades(self, limit: int = 10) -> list:
        cur = await self._db.execute("""
            SELECT symbol, direction, score, result, profit, trade_size, opened_at
            FROM trades
            ORDER BY opened_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_equity_curve(self, days: int = 30) -> list:
        cur = await self._db.execute("""
            SELECT date, net_profit, balance_end, wins, losses, trades
            FROM daily_summary
            ORDER BY date ASC
            LIMIT ?
        """, (days,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_all_trades_for_analysis(self) -> list:
        cur = await self._db.execute("""
            SELECT profit, result, score, confidence, symbol, direction, opened_at
            FROM trades
            WHERE result IN ('win','loss')
            ORDER BY opened_at ASC
        """)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_daily_summary(self, balance: float):
        today = date.today().isoformat()
        stats = await self.get_today_stats()
        await self._db.execute("""
            INSERT INTO daily_summary
                (date, trades, wins, losses, win_rate, net_profit, balance_end, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
                trades=excluded.trades, wins=excluded.wins,
                losses=excluded.losses, win_rate=excluded.win_rate,
                net_profit=excluded.net_profit, balance_end=excluded.balance_end,
                updated_at=excluded.updated_at
        """, (
            today, stats["total"], stats["wins"], stats["losses"],
            stats["win_rate"], stats["net_profit"], balance, time.time()
        ))
        await self._db.commit()

    async def get_pair_stats(self, pair: str) -> dict:
        cur = await self._db.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) AS wins,
                   SUM(profit) AS net_profit,
                   AVG(score) AS avg_score,
                   AVG(confidence) AS avg_confidence
            FROM trades
            WHERE symbol=? AND result != 'pending'
        """, (pair,))
        row = await cur.fetchone()
        if not row:
            return {"total":0,"wins":0,"net_profit":0,"avg_score":0,"avg_confidence":0}
        return dict(row)

    async def get_signal_stats(self, days: int = 7) -> dict:
        cur = await self._db.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN trade_executed=1 THEN 1 ELSE 0 END) AS executed,
                   SUM(CASE WHEN skip_reason!='' AND skip_reason IS NOT NULL THEN 1 ELSE 0 END) AS skipped
            FROM signals
            WHERE created_at > ?
        """, (time.time() - days * 86400,))
        row = await cur.fetchone()
        return dict(row) if row else {"total":0,"executed":0,"skipped":0}

    async def export_csv(self, path: str = "trades_export.csv"):
        import csv
        cur = await self._db.execute(
            "SELECT * FROM trades ORDER BY opened_at DESC"
        )
        rows = await cur.fetchall()
        if not rows:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(r) for r in rows])
        log.info("📄 تم تصدير %d صفقة إلى %s", len(rows), path)

    async def close(self):
        if self._db:
            await self._db.close()


# ─────────────────────────────────────────────
#  2. منفذ الصفقات
# ─────────────────────────────────────────────

class TradeExecutor:
    """
    ينفذ الصفقة على Quotex عبر pyquotex.
    يجرب كل طرق الشراء/البيع المتاحة في المكتبة.
    يراقب النتيجة وينتظر إغلاق الصفقة.
    """

    # أسماء دوال الشراء المحتملة في pyquotex
    BUY_METHODS  = ["buy", "place_deal", "open_option",
                    "buy_digital_spot", "place_order"]
    SELL_METHODS = ["sell", "place_deal", "open_option",
                    "buy_digital_spot", "place_order"]

    def __init__(self, pipeline: DataPipeline):
        self.pipeline = pipeline

    @property
    def client(self):
        return self.pipeline.connection.client

    async def _ensure_connected(self) -> bool:
        return await self.pipeline.connection.ensure_connected()

    async def get_balance(self) -> float:
        return await self.pipeline.connection.get_balance()

    def _get_client(self):
        return self.pipeline.connection.client

    async def execute(self,
                      signal:    Signal,
                      symbol:    str,
                      duration:  int = 60) -> tuple[bool, str, float]:
        """
        ينفذ الصفقة — يستخدم نهج bot2 (تجربة صيغ أسماء الأصول) ثم الرجوع للنهج القديم.
        يُرجع: (success, trade_id, entry_price)
        """
        if not await self._ensure_connected():
            return False, "", 0.0

        direction  = signal.direction.upper()
        trade_size = signal.trade_size
        client     = self.client
        entry_price = self.pipeline.buffer.current_price or 0.0

        if not client:
            log.error("❌ لا يوجد client — تعذّر التنفيذ")
            return False, "", 0.0

        # ── Primary: bot2 candidate asset approach ──────────
        api_asset = quotex_symbol_to_api_symbol(symbol)
        candidates = build_candidate_assets(symbol, api_asset)
        log.info("🔍 تجربة %d صيغة اسم للزوج %s", len(candidates), symbol)

        direct_buy = getattr(client, "buy", None)
        if direct_buy:
            for candidate in candidates:
                try:
                    normalized = str(candidate).lower()
                    timeout = 36 if "otc" in normalized else 28
                    if inspect.iscoroutinefunction(direct_buy):
                        result = await asyncio.wait_for(
                            direct_buy(float(trade_size), candidate, direction, int(duration)),
                            timeout=timeout,
                        )
                    else:
                        result = await asyncio.wait_for(
                            asyncio.to_thread(direct_buy, float(trade_size), candidate, direction, int(duration)),
                            timeout=timeout,
                        )
                    trade_id = self._extract_trade_id(result)
                    if trade_id or result:
                        log.info("✅ صفقة مفتوحة | %s %s $%.2f | ID: %s",
                                 symbol, direction, trade_size, trade_id)
                        return True, str(trade_id), entry_price
                except asyncio.TimeoutError:
                    log.warning("⏰ انتهت مهلة %s بصيغة %s", symbol, candidate)
                    await self._ensure_connected()
                    await asyncio.sleep(2)
                    continue
                except Exception as e:
                    log.debug("⚠️ صيغة %s فشلت: %s", candidate, e)
                    continue

        # ── Fallback: old approach (method × direction) ─────
        log.info("📋 الرجوع للنهج القديم — method × direction")
        direction_map = {
            "UP":   ["call", "CALL", "up",   "UP",   "higher", "HIGHER"],
            "DOWN": ["put",  "PUT",  "down", "DOWN", "lower",  "LOWER"],
        }
        directions_to_try = direction_map.get(direction, [direction.lower()])

        for method_name in self.BUY_METHODS:
            if not hasattr(client, method_name):
                continue
            for dir_str in directions_to_try:
                try:
                    method = getattr(client, method_name)
                    result = await method(symbol, trade_size, dir_str, duration)
                    trade_id = self._extract_trade_id(result)
                    if trade_id or result:
                        log.info("✅ صفقة مفتوحة (fallback) | %s %s $%.2f | ID: %s",
                                 symbol, direction, trade_size, trade_id)
                        return True, str(trade_id), entry_price
                except TypeError:
                    try:
                        method = getattr(client, method_name)
                        result = await method(symbol, trade_size, dir_str)
                        trade_id = self._extract_trade_id(result)
                        if trade_id or result:
                            return True, str(trade_id), entry_price
                    except Exception:
                        pass
                except Exception as e:
                    log.debug("⚠️ %s(%s) فشل: %s", method_name, dir_str, e)

        log.error("❌ فشل تنفيذ الصفقة — لا توجد طريقة متاحة")
        return False, "", entry_price

    async def wait_for_result(self,
                               trade_id: str,
                               duration: int = 60,
                               payout:   float = 0.85) -> tuple[TradeResult, float, float]:
        """
        ينتظر نتيجة الصفقة بعد انتهاء المدة.
        يُرجع: (result, profit_or_loss, exit_price)
        """
        await asyncio.sleep(duration + 2)  # انتظر انتهاء الشمعة + هامش

        if not await self._ensure_connected():
            return TradeResult.ERROR, 0.0, 0.0

        client     = self.client
        exit_price = self.pipeline.buffer.current_price or 0.0

        # جرب استعلام نتيجة الصفقة
        result_methods = [
            "get_trade_result",
            "check_win",
            "get_optioninfo",
            "get_order_result",
        ]

        for method_name in result_methods:
            if not hasattr(client, method_name):
                continue
            try:
                raw = await getattr(client, method_name)(trade_id)
                result, profit = self._parse_result(raw, payout)
                if result != TradeResult.PENDING:
                    log.info("📊 نتيجة الصفقة %s: %s | ربح/خسارة: %.2f",
                             trade_id, result.value, profit)
                    return result, profit, exit_price
            except Exception as e:
                log.debug("⚠️ %s فشل: %s", method_name, e)

        # fallback: قارن سعر الدخول والخروج
        log.warning("⚠️ لم يتم التحقق من النتيجة — استخدام مقارنة الأسعار")
        return TradeResult.PENDING, 0.0, exit_price

    @staticmethod
    def _extract_trade_id(result) -> str:
        if result is None:
            return ""
        if isinstance(result, (int, str)):
            return str(result)
        if isinstance(result, dict):
            for key in ("id", "trade_id", "order_id", "deal_id"):
                if key in result:
                    return str(result[key])
        if isinstance(result, (list, tuple)) and result:
            return str(result[0])
        return str(result) if result else ""

    @staticmethod
    def _parse_result(raw, payout: float) -> tuple[TradeResult, float]:
        """تحليل رد الـ API لمعرفة النتيجة"""
        if raw is None:
            return TradeResult.PENDING, 0.0

        # صيغة dict
        if isinstance(raw, dict):
            status = str(raw.get("result", raw.get("status", ""))).lower()
            amount = float(raw.get("profit", raw.get("amount", 0)))
            if "win" in status or amount > 0:
                return TradeResult.WIN,  abs(amount)
            if "loss" in status or "lose" in status:
                return TradeResult.LOSS, -abs(amount)
            if "tie" in status or "draw" in status:
                return TradeResult.TIE,  0.0

        # صيغة bool
        if isinstance(raw, bool):
            return (TradeResult.WIN, payout) if raw else (TradeResult.LOSS, -1.0)

        # صيغة string
        raw_str = str(raw).lower()
        if "win"  in raw_str: return TradeResult.WIN,  payout
        if "loss" in raw_str: return TradeResult.LOSS, -1.0
        if "tie"  in raw_str: return TradeResult.TIE,  0.0

        return TradeResult.PENDING, 0.0


# ─────────────────────────────────────────────
#  3. مدير الصفقات — يربط كل شيء
# ─────────────────────────────────────────────

class TradeManager:
    """
    الطبقة الرئيسية التي تربط:
    إشارة → فلترة → تنفيذ → انتظار → نتيجة → DB → Telegram
    """

    def __init__(self,
                 pipeline:    DataPipeline,
                 db:          Database,
                 on_result:   Optional[Callable] = None,
                 trade_duration: int  = 60,
                 paper_mode:     bool = True,
                 min_score:      int  = 4,
                 max_daily_loss_pct: float = 0.10,
                 max_consecutive_losses: int = 3):

        self.pipeline   = pipeline
        self.db         = db
        self.executor   = TradeExecutor(pipeline)
        self.on_result  = on_result      # callback → Telegram
        self.duration   = trade_duration
        self.paper      = paper_mode     # True = لا تنفذ فعلياً
        self.min_score  = min_score
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_cons_losses    = max_consecutive_losses

        self.stats     = SessionStats()
        self._lock     = asyncio.Lock()  # منع صفقتين في نفس الوقت
        self._in_trade = False

    async def initialize(self):
        """تهيئة الجلسة وجلب الرصيد الأولي"""
        balance = await self.executor.get_balance()
        self.stats.balance_start   = balance
        self.stats.balance_current = balance
        self.stats.session_start   = time.time()
        await self.db.update_daily_summary(balance)
        log.info("💰 رصيد البداية: $%.2f | وضع: %s",
                 balance, "تجريبي 📋" if self.paper else "حقيقي 💵")

    async def handle_signal(self, signal: Signal) -> None:
        """
        يُستدعى من DataPipeline عند كل إشارة.
        يقرر: هل ينفذ؟ لماذا؟ ثم ينفذ ويسجل.
        """
        self.stats.total_signals += 1
        symbol = self.pipeline.data_settings.symbol

        # ── فلاتر ما قبل التنفيذ ──────────────────
        skip_reason = self._pre_trade_check(signal)
        if skip_reason:
            self.stats.skipped += 1
            await self.db.save_signal(signal, symbol,
                                       executed=False, skip_reason=skip_reason)
            log.info("⏭  تخطي الإشارة: %s", skip_reason)
            return

        await self.db.save_signal(signal, symbol, executed=True)

        async with self._lock:
            if self._in_trade:
                log.info("⏳ صفقة قائمة بالفعل — تخطي")
                return
            self._in_trade = True

        try:
            await self._execute_trade(signal, symbol)
        finally:
            self._in_trade = False

    def _pre_trade_check(self, signal: Signal) -> str:
        """يُرجع سبب التخطي أو "" إذا مسموح بالدخول"""
        if signal.direction == "WAIT":
            return "إشارة WAIT"
        if signal.score < self.min_score:
            return f"نقاط منخفضة ({signal.score} < {self.min_score})"
        if self.stats.consecutive_losses >= self.max_cons_losses:
            return f"circuit breaker: {self.stats.consecutive_losses} خسائر متتالية"
        # فحص الخسارة اليومية
        if self.stats.balance_start > 0:
            daily_loss = (self.stats.balance_start - self.stats.balance_current) \
                         / self.stats.balance_start
            if daily_loss >= self.max_daily_loss_pct:
                return f"حد الخسارة اليومية ({daily_loss*100:.1f}%)"
        return ""

    async def _execute_trade(self, signal: Signal, symbol: str):
        """ينفذ الصفقة فعلياً أو يحاكيها في Paper Mode"""
        payout     = self.pipeline.data_settings.payout
        trade_size = signal.trade_size
        import json
        reasons_json = json.dumps(signal.reasons[:5], ensure_ascii=False)

        # ── Paper Mode (محاكاة) ────────────────────
        if self.paper:
            log.info("📋 [PAPER] %s %s $%.2f | نقاط: %d",
                     symbol, signal.direction, trade_size, signal.score)
            trade = TradeRecord(
                signal_direction = signal.direction,
                symbol           = symbol,
                payout           = payout,
                trade_size       = trade_size,
                score            = signal.score,
                confidence       = signal.confidence,
                entry_price      = self.pipeline.buffer.current_price,
                reasons          = reasons_json,
                trade_id         = f"PAPER_{int(time.time())}",
            )
            db_id = await self.db.save_trade(trade)
            trade.db_id = db_id
            self.stats.trades_opened += 1

            # محاكاة انتظار النتيجة
            await asyncio.sleep(min(self.duration, 5))
            sim_result, sim_profit = self._simulate_result(signal, payout, trade_size)
            await self._record_result(trade, sim_result, sim_profit,
                                       self.pipeline.buffer.current_price)
            return

        # ── Live Mode ──────────────────────────────
        log.info("🔥 [LIVE] تنفيذ %s %s $%.2f",
                 symbol, signal.direction, trade_size)
        success, trade_id, entry_price = await self.executor.execute(
            signal, symbol, self.duration
        )
        if not success:
            log.error("❌ فشل تنفيذ الصفقة")
            return

        trade = TradeRecord(
            signal_direction = signal.direction,
            symbol           = symbol,
            payout           = payout,
            trade_size       = trade_size,
            score            = signal.score,
            confidence       = signal.confidence,
            entry_price      = entry_price,
            reasons          = reasons_json,
            trade_id         = trade_id,
        )
        db_id = await self.db.save_trade(trade)
        trade.db_id = db_id
        self.stats.trades_opened += 1

        # إبلاغ Telegram بفتح الصفقة
        if self.on_result:
            await self.on_result("opened", trade, None)

        # انتظار النتيجة
        result, profit, exit_price = await self.executor.wait_for_result(
            trade_id, self.duration, payout / 100
        )
        await self._record_result(trade, result, profit, exit_price)

    async def _record_result(self, trade: TradeRecord,
                              result: TradeResult,
                              profit: float,
                              exit_price: float):
        """يسجل النتيجة في DB والإحصائيات ويبلغ Telegram"""
        # تحديث DB
        await self.db.update_trade_result(
            trade.db_id, result.value, profit, exit_price
        )

        # تحديث الإحصائيات
        balance = await self.executor.get_balance()
        self.stats.balance_current = balance if balance > 0 \
                                     else self.stats.balance_current + profit

        if result == TradeResult.WIN:
            self.stats.wins += 1
            self.stats.consecutive_wins   += 1
            self.stats.consecutive_losses  = 0
        elif result == TradeResult.LOSS:
            self.stats.losses += 1
            self.stats.consecutive_losses += 1
            self.stats.consecutive_wins    = 0
            self.stats.max_consecutive_losses = max(
                self.stats.max_consecutive_losses,
                self.stats.consecutive_losses
            )
        elif result == TradeResult.TIE:
            self.stats.ties += 1
            self.stats.consecutive_losses = 0
            self.stats.consecutive_wins   = 0

        await self.db.update_daily_summary(self.stats.balance_current)

        icon = {"win":"✅","loss":"❌","tie":"➖","pending":"⏳","error":"⚠️"
                }.get(result.value, "❓")
        log.info(
            "%s %s | ربح/خسارة: %+.2f | الرصيد: %.2f | نجاح: %.1f%%",
            icon, result.value.upper(), profit,
            self.stats.balance_current, self.stats.win_rate
        )

        # إبلاغ Telegram بالنتيجة
        if self.on_result:
            await self.on_result("closed", trade, result)

    @staticmethod
    def _simulate_result(signal: Signal,
                          payout: float,
                          trade_size: float) -> tuple[TradeResult, float]:
        """
        محاكاة نتيجة واقعية في Paper Mode.
        نسبة النجاح مبنية على نقاط الإشارة.
        """
        import random
        # نسبة النجاح تزيد مع ارتفاع النقاط
        base_rate = 0.45
        score_bonus = signal.score * 0.025   # كل نقطة تضيف 2.5%
        win_rate = min(base_rate + score_bonus, 0.80)

        won = random.random() < win_rate
        if won:
            profit = round(trade_size * (payout / 100), 2)
            return TradeResult.WIN, profit
        else:
            return TradeResult.LOSS, -trade_size

    async def get_full_stats(self) -> dict:
        """إحصائيات كاملة للـ Telegram /stats"""
        today_db = await self.db.get_today_stats()
        recent   = await self.db.get_recent_trades(5)
        best_sym = await self.db.get_best_symbols(7)
        return {
            "session":  self.stats,
            "today_db": today_db,
            "recent":   recent,
            "best_symbols": best_sym,
        }


# ─────────────────────────────────────────────
#  4. تنسيق رسائل النتائج للـ Telegram
# ─────────────────────────────────────────────

def fmt_trade_opened(trade: TradeRecord) -> str:
    arrow = "⬆️" if trade.signal_direction == "UP" else "⬇️"
    mode  = "📋 تجريبي" if trade.trade_id.startswith("PAPER") else "💵 حقيقي"
    return (
        f"🔔 *صفقة مفتوحة* {mode}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 `{trade.symbol}` {arrow} *{trade.signal_direction}*\n"
        f"💰 الحجم: `${trade.trade_size:.2f}`\n"
        f"📈 النقاط: {trade.score} | الثقة: {trade.confidence:.0f}%\n"
        f"💲 سعر الدخول: `{trade.entry_price:.5f}`\n"
        f"🕐 `{datetime.now().strftime('%H:%M:%S')}`"
    )


def fmt_trade_closed(trade: TradeRecord, result: TradeResult) -> str:
    icons = {
        TradeResult.WIN:  ("✅", "ربح"),
        TradeResult.LOSS: ("❌", "خسارة"),
        TradeResult.TIE:  ("➖", "تعادل"),
    }
    icon, label = icons.get(result, ("❓", "غير معروف"))
    profit_str = f"+${trade.profit:.2f}" if trade.profit > 0 else f"-${abs(trade.profit):.2f}"
    return (
        f"{icon} *نتيجة الصفقة: {label}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 `{trade.symbol}` | {trade.signal_direction}\n"
        f"💵 الربح/الخسارة: *{profit_str}*\n"
        f"🕐 `{datetime.now().strftime('%H:%M:%S')}`"
    )


def fmt_full_stats(data: dict) -> str:
    s    = data["session"]
    td   = data["today_db"]
    best = data.get("best_symbols", [])

    best_text = ""
    if best:
        best_text = "\n*🏆 أفضل الأزواج (7 أيام):*\n"
        for b in best[:3]:
            total = b.get("total", 1)
            wins  = b.get("wins", 0)
            wr    = round(wins / total * 100, 1) if total > 0 else 0
            best_text += f"  `{b['symbol']}` — {wr}% ({wins}/{total})\n"

    return (
        f"📊 *إحصائيات كاملة*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*الجلسة الحالية:*\n"
        f"  إشارات: {s.total_signals} | صفقات: {s.trades_opened}\n"
        f"  ✅ {s.wins} | ❌ {s.losses} | نسبة: {s.win_rate:.1f}%\n"
        f"  ربح صافي: `{'+'if s.net_profit>=0 else ''}{s.net_profit:.2f}$`\n"
        f"  رصيد: `${s.balance_current:.2f}`\n"
        f"  وقت التشغيل: {s.uptime_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*اليوم (من DB):*\n"
        f"  صفقات: {td['total']} | نجاح: {td['win_rate']:.1f}%\n"
        f"  صافي: `{td['net_profit']:+.2f}$`\n"
        f"  متوسط نقاط: {td['avg_score']:.1f}\n"
        f"{best_text}"
    )

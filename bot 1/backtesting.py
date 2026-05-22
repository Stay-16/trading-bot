from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from bot_algorithms import Candle, ConfluenceEngine, Signal
from indicators_library import calc_rsi, calc_atr, calc_adx

log = logging.getLogger("Backtest")


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    total_profit: float = 0.0
    final_balance: float = 0.0
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    duration_seconds: float = 0.0


class BacktestingEngine:
    """
    محاكاة تاريخية كاملة لأي فترة زمنية.
    يحاكي ConfluenceEngine + RiskManager + TradeManager.
    """

    def __init__(self,
                 initial_balance: float = 1000.0,
                 payout_pct: float = 88.0,
                 trade_duration_sec: int = 60,
                 risk_per_trade: float = 0.02,
                 min_score: int = 6,
                 max_consecutive_losses: int = 3):
        self.initial_balance = initial_balance
        self.payout_pct = payout_pct
        self.trade_duration = trade_duration_sec
        self.risk_per_trade = risk_per_trade
        self.min_score = min_score
        self.max_consecutive_losses = max_consecutive_losses

    def _calc_trade_size(self, balance: float, confidence: float, score: int) -> float:
        base = balance * self.risk_per_trade
        conf_mult = min(1.0, confidence / 100.0)
        score_mult = min(1.0, score / 20.0)
        return round(base * max(0.5, (conf_mult + score_mult) / 2), 2)

    async def run(self,
                  candles: list[Candle],
                  payout: Optional[float] = None,
                  on_trade: Optional[Callable] = None) -> BacktestResult:
        start_t = time.time()
        result = BacktestResult()
        balance = self.initial_balance
        equity_curve = [balance]
        consecutive_losses = 0

        if not candles or len(candles) < 30:
            log.warning("بيانات غير كافية للـ backtest")
            return result

        payout = payout or self.payout_pct
        total_profit = 0.0

        for i in range(20, len(candles) - 1):
            if balance <= 0:
                break
            window = candles[:i + 1]
            current = candles[i]
            next_candle = candles[i + 1]

            # محاكاة ConfluenceEngine
            engine = ConfluenceEngine(
                candles=window,
                current_price=current.close,
                payout=payout,
                balance=balance,
            )
            signal = engine.run()

            if signal.direction == "WAIT" or signal.score < self.min_score:
                equity_curve.append(balance)
                continue

            if consecutive_losses >= self.max_consecutive_losses:
                equity_curve.append(balance)
                continue

            # فتح صفقة
            trade_size = self._calc_trade_size(balance, signal.confidence, signal.score)
            direction_up = signal.direction == "UP"

            # تحديد الربح/الخسارة بناءً على الشمعة التالية
            if direction_up:
                won = next_candle.close > current.close
            else:
                won = next_candle.close < current.close

            profit = trade_size * (payout / 100.0) if won else -trade_size

            balance += profit
            total_profit += profit

            if won:
                consecutive_losses = 0
                result.wins += 1
            else:
                consecutive_losses += 1
                result.losses += 1

            result.total_trades += 1
            equity_curve.append(balance)

            trade_record = {
                "index": i,
                "time": getattr(current, 'timestamp', i),
                "direction": signal.direction,
                "score": signal.score,
                "confidence": signal.confidence,
                "trade_size": trade_size,
                "profit": round(profit, 2),
                "won": won,
                "balance": round(balance, 2),
            }
            result.trades.append(trade_record)

            if on_trade:
                await on_trade(trade_record)

        # حساب الإحصائيات
        result.total_trades = len(result.trades)
        result.win_rate = (result.wins / result.total_trades * 100) if result.total_trades > 0 else 0
        result.total_profit = round(total_profit, 2)
        result.final_balance = round(balance, 2)

        if result.wins > 0:
            result.avg_win = sum(t["profit"] for t in result.trades if t["won"]) / result.wins
        if result.losses > 0:
            result.avg_loss = abs(sum(t["profit"] for t in result.trades if not t["won"])) / result.losses

        if result.losses > 0 and result.wins > 0:
            total_gain = sum(t["profit"] for t in result.trades if t["won"])
            total_loss = abs(sum(t["profit"] for t in result.trades if not t["won"]))
            result.profit_factor = total_gain / total_loss if total_loss > 0 else 0

        if result.avg_win > 0 and result.avg_loss > 0:
            wr = result.win_rate / 100
            result.expectancy = (wr * result.avg_win) - ((1 - wr) * result.avg_loss)

        # Sharpe Ratio
        returns = []
        for t in result.trades:
            returns.append(t["profit"] / (self.initial_balance * self.risk_per_trade))
        if len(returns) > 1:
            avg_r = sum(returns) / len(returns)
            std_r = math.sqrt(sum((r - avg_r) ** 2 for r in returns) / (len(returns) - 1)) if len(returns) > 1 else 0
            result.sharpe_ratio = round((avg_r / std_r) * math.sqrt(252), 2) if std_r > 0 else 0
            neg_returns = [r for r in returns if r < 0]
            if neg_returns:
                down_std = math.sqrt(sum(r ** 2 for r in neg_returns) / len(neg_returns))
                result.sortino_ratio = round((avg_r / down_std) * math.sqrt(252), 2) if down_std > 0 else 0

        # Max Drawdown
        peak = equity_curve[0]
        max_dd = 0.0
        for val in equity_curve:
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown_pct = round(max_dd, 2)

        result.equity_curve = equity_curve
        result.duration_seconds = round(time.time() - start_t, 2)

        log.info("Backtest done: %d trades, WR=%.1f%%, PF=%.2f, Sharpe=%.2f, MaxDD=%.1f%%",
                 result.total_trades, result.win_rate, result.profit_factor,
                 result.sharpe_ratio, result.max_drawdown_pct)
        return result

    def result_to_text(self, r: BacktestResult) -> str:
        return (
            f"📊 *نتائج Backtesting*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 الصفقات: `{r.total_trades}`\n"
            f"✅ المكاسب: `{r.wins}`  ❌ الخسائر: `{r.losses}`\n"
            f"📊 نسبة النجاح: `{r.win_rate:.1f}%`\n"
            f"💰 عامل الربح: `{r.profit_factor:.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📐 Sharpe: `{r.sharpe_ratio}`\n"
            f"📐 Sortino: `{r.sortino_ratio}`\n"
            f"📉 Max Drawdown: `{r.max_drawdown_pct:.1f}%`\n"
            f"🏆 متوسط الربح: `${r.avg_win:.2f}`\n"
            f"💸 متوسط الخسارة: `${r.avg_loss:.2f}`\n"
            f"🎯 Expectancy: `${r.expectancy:.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 الرصيد النهائي: `${r.final_balance:.2f}`\n"
            f"📈 صافي الربح: `${r.total_profit:.2f}`\n"
            f"⏱️ وقت المحاكاة: `{r.duration_seconds}s`"
        )

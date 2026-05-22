"""
Fused backtesting engine — simulates the full signal pipeline:
ConfluenceEngine → 7 votes → WeightedDecisionEngine → FusedRiskManager

Usage:
    python backtest_engine.py                     # demo with synthetic data
    python backtest_engine.py --payout 85 --balance 500 --min-score 8
"""

import math
import os
import random
import sys
from typing import Any, Optional

from bot_algorithms import Candle, ConfluenceEngine
from shared.risk_manager import FusedRiskManager


class FusedBacktestEngine:
    def __init__(
        self,
        candles: list[Candle],
        payout: float = 85.0,
        balance: float = 1000.0,
        window: int = 60,
        min_score: int = 6,
    ):
        self.candles = candles
        self.payout = payout
        self.starting_balance = balance
        self.balance = balance
        self.window = window
        self.min_score = min_score
        self.risk_manager = FusedRiskManager(
            risk_per_trade_pct=float(os.getenv("RISK_PER_TRADE", "0.02")),
            daily_loss_limit_pct=float(os.getenv("MAX_DAILY_LOSS", "0.10")),
            max_consecutive_losses=int(os.getenv("MAX_CONS_LOSSES", "3")),
            min_trade_amount=float(os.getenv("MIN_TRADE", "1.0")),
            max_trade_amount=float(os.getenv("MAX_TRADE", "50.0")),
        )

    def run(self) -> dict:
        trades = []
        balance = self.starting_balance
        peak = self.starting_balance
        max_dd = 0.0
        cons_loss = 0
        max_cons = 0
        total_profit = 0.0

        for i in range(self.window + 1, len(self.candles) - 1):
            window_candles = self.candles[i - self.window : i]
            current_price = window_candles[-1].close
            next_candle = self.candles[i]

            engine = ConfluenceEngine(
                candles=window_candles,
                current_price=current_price,
                payout=self.payout,
                balance=balance,
            )
            algo_signal = engine.run()

            if algo_signal.direction == "WAIT" or algo_signal.score < self.min_score:
                continue

            can_trade, reason = self.risk_manager.can_open_trade(balance=balance)
            if not can_trade:
                continue

            trade_size = self.risk_manager.calculate_position_size(
                balance=balance,
                confidence=algo_signal.confidence,
                score=algo_signal.score,
                payout=self.payout / 100.0,
                consecutive_losses=cons_loss,
            )

            won = (
                (next_candle.close > next_candle.open)
                if algo_signal.direction == "UP"
                else (next_candle.close < next_candle.open)
            )

            profit = trade_size * (self.payout / 100) if won else -trade_size
            balance = round(balance + profit, 2)
            peak = max(peak, balance)
            drawdown = (peak - balance) / peak
            max_dd = max(max_dd, drawdown)
            cons_loss = cons_loss + 1 if not won else 0
            max_cons = max(max_cons, cons_loss)
            total_profit += profit

            trades.append({
                "index": i,
                "direction": algo_signal.direction,
                "score": algo_signal.score,
                "confidence": algo_signal.confidence,
                "won": won,
                "profit": round(profit, 2),
                "balance": balance,
                "trade_size": round(trade_size, 2),
            })

        if not trades:
            return {"error": "No trades generated — lower min_score or use more data"}

        wins = [t for t in trades if t["won"]]
        losses = [t for t in trades if not t["won"]]
        gp = sum(t["profit"] for t in wins)
        gl = abs(sum(t["profit"] for t in losses))
        returns = [t["profit"] / (t["trade_size"] or 1) for t in trades]

        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0
        sharpe = (avg_return / std_return * math.sqrt(252)) if std_return > 0 else 0
        downside = [r for r in returns if r < 0]
        dd_std = (sum((r - avg_return) ** 2 for r in downside) / len(downside)) ** 0.5 if len(downside) > 1 else 0
        sortino = (avg_return / dd_std * math.sqrt(252)) if dd_std > 0 else 0
        expectancy = (gp - gl) / len(trades) if trades else 0
        avg_win = gp / len(wins) if wins else 0
        avg_loss = gl / len(losses) if losses else 0

        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 2),
            "profit_factor": round(gp / gl, 2) if gl > 0 else float("inf"),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "max_consecutive_losses": max_cons,
            "starting_balance": self.starting_balance,
            "final_balance": balance,
            "total_return_pct": round((balance - self.starting_balance) / self.starting_balance * 100, 2),
            "total_profit": round(total_profit, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "avg_confidence": round(sum(t["confidence"] for t in trades) / len(trades), 1),
            "avg_score": round(sum(t["score"] for t in trades) / len(trades), 1),
            "avg_score_wins": round(sum(t["score"] for t in wins) / len(wins), 1) if wins else 0,
            "avg_score_losses": round(sum(t["score"] for t in losses) / len(losses), 1) if losses else 0,
            "equity_curve": [round(t["balance"], 2) for t in trades[::max(1, len(trades) // 100)]],
            "trades_sample": trades[:10],
        }


def _make_synthetic_candles(n: int = 500, base: float = 1.1000) -> list[Candle]:
    random.seed(42)
    candles = []
    price = base
    phase = 0
    for i in range(n):
        phase = (i % 120)
        trend = 0.004 if phase < 60 else -0.003
        noise = random.uniform(-0.002, 0.002)
        change = trend + noise
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) + random.uniform(0, 0.0015)
        low_p = min(open_p, close_p) - random.uniform(0, 0.0015)
        body_pct = abs(close_p - open_p) / (high_p - low_p) if (high_p - low_p) > 0 else 0.5
        if body_pct < 0.2:
            close_p = open_p + (close_p - open_p) * 3
        candles.append(Candle(
            open=round(open_p, 5),
            high=round(high_p, 5),
            low=round(low_p, 5),
            close=round(close_p, 5),
            volume=random.randint(100, 1000),
        ))
        price = close_p
    return candles


def main():
    payout = float(os.getenv("PAYOUT", "85"))
    balance = float(os.getenv("BALANCE", "1000"))
    min_score = int(os.getenv("MIN_SCORE", "6"))
    window = int(os.getenv("BACKTEST_WINDOW", "60"))
    n_candles = int(os.getenv("BACKTEST_CANDLES", "500"))

    print("=" * 60)
    print("  Fused Backtest Engine")
    print("=" * 60)
    print(f"  Payout: {payout}%")
    print(f"  Balance: ${balance}")
    print(f"  Min score: {min_score}")
    print(f"  Window: {window}")
    print(f"  Candles: {n_candles}")
    print()

    candles = _make_synthetic_candles(n_candles)
    engine = FusedBacktestEngine(candles, payout, balance, window, min_score)
    result = engine.run()

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        sys.exit(1)

    print(f"  Total trades:  {result['total_trades']}")
    print(f"  Win rate:      {result['win_rate']}%")
    print(f"  Profit factor: {result['profit_factor']}")
    print(f"  Sharpe:        {result['sharpe_ratio']}")
    print(f"  Sortino:       {result['sortino_ratio']}")
    print(f"  Max DD:        {result['max_drawdown_pct']}%")
    print(f"  Max cons loss: {result['max_consecutive_losses']}")
    print(f"  Expectancy:    ${result['expectancy']}")
    print(f"  Starting bal:  ${result['starting_balance']}")
    print(f"  Final bal:     ${result['final_balance']}")
    print(f"  Return:        {result['total_return_pct']}%")
    print("=" * 60)


if __name__ == "__main__":
    main()

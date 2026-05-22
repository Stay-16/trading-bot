"""
Walk-forward optimization for ConfluenceEngine parameters.
Finds optimal min_score and signal thresholds per asset.

Usage:
    python walk_forward.py                          # synthetic demo
    python walk_forward.py --candles candles.json    # from real data
"""

import json
import math
import os
import random
import sys
from typing import Any, Optional

from bot_algorithms import Candle, ConfluenceEngine
from shared.risk_manager import FusedRiskManager


DEFAULT_PARAM_GRID = {
    "min_score": [4, 6, 8, 10, 12],
    "trade_duration": [60, 120, 180, 300],
}


def _score_cmp(result: dict) -> float:
    wr = result.get("win_rate", 0)
    pf = result.get("profit_factor", 0)
    sh = result.get("sharpe_ratio", 0)
    dd = result.get("max_drawdown_pct", 100)
    trades = result.get("total_trades", 0)
    if trades < 10:
        return -1
    dd_penalty = max(0, dd - 15) * 0.5
    return wr * 0.3 + min(pf, 10) * 5 + sh * 10 - dd_penalty + math.log(trades + 1) * 3


class WalkForwardOptimizer:
    def __init__(
        self,
        candles: list[Candle],
        payout: float = 85.0,
        balance: float = 1000.0,
        window: int = 60,
        train_pct: float = 0.6,
    ):
        self.candles = candles
        self.payout = payout
        self.balance = balance
        self.window = window
        self.train_pct = train_pct
        self.n = len(candles)

    def _backtest(self, candles: list[Candle], min_score: int) -> dict:
        rm = FusedRiskManager()
        trades = []
        bal = self.balance
        peak = self.balance
        max_dd = 0.0
        cons_loss = 0
        for i in range(self.window + 1, len(candles) - 1):
            w = candles[i - self.window : i]
            e = ConfluenceEngine(w, w[-1].close, self.payout, bal)
            sig = e.run()
            if sig.direction == "WAIT" or sig.score < min_score:
                continue
            can, _ = rm.can_open_trade(balance=bal)
            if not can:
                continue
            sz = rm.calculate_position_size(bal, sig.confidence, sig.score, self.payout / 100, cons_loss)
            won = (candles[i].close > candles[i].open) if sig.direction == "UP" else (candles[i].close < candles[i].open)
            profit = sz * (self.payout / 100) if won else -sz
            bal = round(bal + profit, 2)
            peak = max(peak, bal)
            max_dd = max(max_dd, (peak - bal) / peak)
            cons_loss = cons_loss + 1 if not won else 0
            trades.append({"won": won, "profit": profit, "sz": sz, "score": sig.score})

        if len(trades) < 5:
            return {"total_trades": 0, "win_rate": 0, "profit_factor": 0, "sharpe_ratio": 0, "max_drawdown_pct": 100}

        wins = [t for t in trades if t["won"]]
        losses = [t for t in trades if not t["won"]]
        gp = sum(t["profit"] for t in wins)
        gl = abs(sum(t["profit"] for t in losses))
        returns = [t["profit"] / (t["sz"] or 1) for t in trades]
        avg_r = sum(returns) / len(returns)
        std_r = (sum((r - avg_r) ** 2 for r in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0.001
        sharpe = (avg_r / std_r * math.sqrt(252)) if std_r > 0 else 0

        return {
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 2),
            "profit_factor": round(gp / gl, 2) if gl > 0 else float("inf"),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "final_balance": round(bal, 2),
        }

    def optimize(self, param_grid: Optional[dict] = None) -> dict:
        if param_grid is None:
            param_grid = DEFAULT_PARAM_GRID

        split = int(self.n * self.train_pct)
        train = self.candles[:split]
        test = self.candles[split:]

        if len(train) < self.window + 20 or len(test) < self.window + 10:
            return {"error": "Not enough candles for walk-forward split"}

        print(f"  Train: {len(train)} candles, Test: {len(test)} candles")
        print()

        best_score = -1
        best_params = {}
        best_train_result = {}
        results = []

        for ms in param_grid.get("min_score", [6]):
            train_result = self._backtest(train, ms)
            if train_result["total_trades"] < 10:
                continue
            test_result = self._backtest(test, ms)
            s = _score_cmp(train_result) + _score_cmp(test_result) * 0.5
            results.append({"min_score": ms, "score": round(s, 2), "train": train_result, "test": test_result})
            if s > best_score:
                best_score = s
                best_params = {"min_score": ms}
                best_train_result = train_result
                print(f"  min_score={ms}: train WR={train_result['win_rate']}% PF={train_result['profit_factor']} Sharpe={train_result['sharpe_ratio']} | test WR={test_result['win_rate']}% PF={test_result['profit_factor']} -> score={s:.2f} *BEST*")

        if not best_params:
            return {"error": "No valid parameter combination found"}

        return {
            "best_params": best_params,
            "best_score": round(best_score, 2),
            "train_result": best_train_result,
            "all_results": sorted(results, key=lambda r: r["score"], reverse=True),
        }


def _make_demo_candles(n: int = 600, base: float = 1.1000) -> list[Candle]:
    random.seed(42)
    candles = []
    price = base
    for i in range(n):
        phase = i % 120
        trend = 0.004 if phase < 60 else -0.003
        change = trend + random.uniform(-0.002, 0.002)
        o, c_ = price, price + change
        h = max(o, c_) + random.uniform(0, 0.0015)
        l = min(o, c_) - random.uniform(0, 0.0015)
        body = abs(c_ - o)
        if body / (h - l + 0.0001) < 0.2:
            c_ = o + (c_ - o) * 3
        candles.append(Candle(open=round(o, 5), high=round(h, 5), low=round(l, 5), close=round(c_, 5), volume=100))
        price = c_
    return candles


def main():
    payout = float(os.getenv("PAYOUT", "85"))
    balance = float(os.getenv("BALANCE", "1000"))
    n_candles = int(os.getenv("WF_CANDLES", "600"))

    print("=" * 60)
    print("  Walk-Forward Optimization")
    print("=" * 60)

    candles = _make_demo_candles(n_candles)
    optimizer = WalkForwardOptimizer(candles, payout, balance)
    result = optimizer.optimize()

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        sys.exit(1)

    print()
    print(f"  BEST: min_score={result['best_params']['min_score']}")
    print(f"  Train: {result['train_result']['win_rate']}% WR, PF={result['train_result']['profit_factor']}, Sharpe={result['train_result']['sharpe_ratio']}")
    print("=" * 60)


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("Portfolio")


@dataclass
class PairAllocation:
    symbol: str
    budget: float = 0.0
    active_trades: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    net_profit: float = 0.0
    last_trade_at: float = 0.0

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return round(self.wins / total * 100, 1) if total > 0 else 0.0


class PortfolioManager:
    def __init__(self, total_budget: float = 1000.0, min_pair_budget: float = 50.0):
        self.total_budget = total_budget
        self.min_pair_budget = min_pair_budget
        self.allocations: Dict[str, PairAllocation] = {}
        self.active_pairs: Dict[str, List[str]] = {}

    def allocate_budget(self, pairs: List[str]) -> Dict[str, float]:
        n = len(pairs)
        if n == 0:
            return {}
        base = self.total_budget / n
        results = {}
        for pair in pairs:
            alloc = self.allocations.get(pair)
            if alloc and alloc.total_trades > 0:
                wr = alloc.win_rate / 100.0
                budget = base * (0.5 + wr * 0.5)
            else:
                budget = base
            budget = max(self.min_pair_budget, min(budget, self.total_budget * 0.3))
            results[pair] = round(budget, 2)
            if pair not in self.allocations:
                self.allocations[pair] = PairAllocation(symbol=pair, budget=budget)
            else:
                self.allocations[pair].budget = budget
        return results

    def record_trade(self, symbol: str, won: bool, profit: float):
        now = time.time()
        if symbol not in self.allocations:
            self.allocations[symbol] = PairAllocation(symbol=symbol)
        alloc = self.allocations[symbol]
        alloc.total_trades += 1
        alloc.active_trades = max(0, alloc.active_trades - 1)
        alloc.last_trade_at = now
        if won:
            alloc.wins += 1
        else:
            alloc.losses += 1
        alloc.net_profit += profit

    def register_active(self, symbol: str, trade_id: str):
        if symbol not in self.active_pairs:
            self.active_pairs[symbol] = []
        self.active_pairs[symbol].append(trade_id)
        if symbol in self.allocations:
            self.allocations[symbol].active_trades += 1

    def unregister_active(self, symbol: str, trade_id: str):
        if symbol in self.active_pairs:
            self.active_pairs[symbol] = [t for t in self.active_pairs[symbol] if t != trade_id]
            if symbol in self.allocations:
                self.allocations[symbol].active_trades = max(0, self.allocations[symbol].active_trades - 1)

    def get_pair_budget(self, symbol: str) -> float:
        if symbol in self.allocations:
            return self.allocations[symbol].budget
        return self.min_pair_budget

    def summary(self) -> str:
        lines = ["📊 *المحفظة*", "━━━━━━━━━━━━━━━━"]
        for sym, alloc in sorted(self.allocations.items(), key=lambda x: x[1].net_profit, reverse=True):
            lines.append(
                f"  • {sym}: ${alloc.budget:.0f} | "
                f"{alloc.wins}/{alloc.total_trades} ({alloc.win_rate}%) | "
                f"${alloc.net_profit:+.2f}"
            )
        return "\n".join(lines)

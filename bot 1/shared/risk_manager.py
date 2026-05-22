import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple


CORRELATION_GROUPS = {
    "forex_majors": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"],
    "forex_minors": ["EURGBP", "EURJPY", "GBPJPY", "EURAUD", "GBPAUD", "EURCAD", "GBPCAD"],
    "otc_forex": ["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "EURJPY-OTC", "GBPJPY-OTC"],
    "otc_second": ["AUDCAD-OTC", "AUDJPY-OTC", "AUDNZD-OTC", "CADJPY-OTC", "CHFJPY-OTC"],
    "indices": ["US30", "US100", "US500", "UK100", "GER40", "JPN225"],
    "commodities": ["XAUUSD", "XAGUSD", "XTIUSD", "XBRUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD"],
}


@dataclass
class UserRiskState:
    trading_day: str = ""
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    trades_today: int = 0


class FusedRiskManager:
    """
    Unified Risk Manager:
    - Per-user state tracking + daily reset
    - Kelly position sizing with signal strength integration
    - Consecutive loss circuit breaker
    - Portfolio risk: max concurrent, correlation groups, global exposure
    - SignalStrengthScore + RiskRewardOptimizer integration
    """

    def __init__(
        self,
        risk_per_trade_pct: float = 0.02,
        daily_loss_limit_pct: float = 0.10,
        max_consecutive_losses: int = 3,
        min_trade_amount: float = 1.0,
        max_trade_amount: float = 50.0,
        kelly_fraction_cap: float = 0.25,
        max_concurrent_trades: int = 3,
        max_exposure_pct: float = 0.30,
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.min_trade_amount = min_trade_amount
        self.max_trade_amount = max_trade_amount
        self.kelly_fraction_cap = kelly_fraction_cap
        self.max_concurrent_trades = max_concurrent_trades
        self.max_exposure_pct = max_exposure_pct
        self._states: Dict[int, UserRiskState] = {}
        self.active_trades: Dict[str, dict] = {}
        self._load_active_trades()

    def _active_trades_path(self) -> str:
        return os.getenv("ACTIVE_TRADES_PATH", "active_trades.json")

    def _load_active_trades(self):
        path = self._active_trades_path()
        try:
            if os.path.exists(path):
                with open(path) as f:
                    self.active_trades = json.load(f)
        except Exception:
            self.active_trades = {}

    def _save_active_trades(self):
        try:
            with open(self._active_trades_path(), "w") as f:
                json.dump(self.active_trades, f, indent=2)
        except Exception:
            pass

    def register_trade(self, trade_id: str, symbol: str, direction: str, amount: float):
        self.active_trades[trade_id] = {
            "symbol": symbol,
            "direction": direction,
            "amount": amount,
            "opened_at": datetime.utcnow().isoformat(),
        }
        self._save_active_trades()

    def unregister_trade(self, trade_id: str):
        self.active_trades.pop(trade_id, None)
        self._save_active_trades()

    def _find_group(self, symbol: str) -> Optional[str]:
        symbol_upper = symbol.upper().replace("-OTC", "-OTC").split("/")[0]
        for group, members in CORRELATION_GROUPS.items():
            for m in members:
                if m.upper() in symbol_upper or symbol_upper in m.upper():
                    return group
        return None

    def _portfolio_exposure(self) -> float:
        return sum(t["amount"] for t in self.active_trades.values())

    def _concurrent_in_group(self, symbol: str, direction: str) -> int:
        group = self._find_group(symbol)
        if not group:
            return 0
        return sum(
            1 for t in self.active_trades.values()
            if t.get("symbol", "").upper() in [m.upper() for m in CORRELATION_GROUPS[group]]
            and t.get("direction") == direction
        )

    def _today(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _get_state(self, user_id: int = 0) -> UserRiskState:
        if user_id not in self._states:
            self._states[user_id] = UserRiskState(trading_day=self._today())
        state = self._states[user_id]
        if state.trading_day != self._today():
            state.trading_day = self._today()
            state.daily_pnl = 0.0
            state.consecutive_losses = 0
            state.trades_today = 0
        return state

    def can_open_trade(
        self,
        user_id: int = 0,
        balance: Optional[float] = None,
        symbol: Optional[str] = None,
        direction: Optional[str] = None,
        trade_amount: Optional[float] = None,
    ) -> Tuple[bool, str]:
        state = self._get_state(user_id)
        if state.consecutive_losses >= self.max_consecutive_losses:
            return False, f"Circuit breaker: {state.consecutive_losses} consecutive losses"
        if balance and balance > 0:
            daily_loss = abs(min(state.daily_pnl, 0.0))
            limit = balance * self.daily_loss_limit_pct
            if daily_loss >= limit:
                return False, f"Daily loss limit reached ({daily_loss:.2f}/{limit:.2f})"

        # ── Portfolio risk checks ──
        n_active = len(self.active_trades)
        if n_active >= self.max_concurrent_trades:
            return False, f"Max concurrent trades ({self.max_concurrent_trades}) reached"

        if symbol and direction:
            same_dir = self._concurrent_in_group(symbol, direction)
            if same_dir >= 1:
                return False, f"Already trading {direction} position in {symbol}'s group"

        if trade_amount and balance and balance > 0:
            total_exposure = self._portfolio_exposure() + trade_amount
            exposure_pct = total_exposure / balance
            if exposure_pct > self.max_exposure_pct:
                pct_used = round(self._portfolio_exposure() / balance * 100, 1)
                return False, f"Global exposure limit: {pct_used}% + this trade would exceed {self.max_exposure_pct*100}%"

        return True, "allowed"

    def calculate_position_size(
        self, balance: float, confidence: int = 50,
        score: int = 0, payout: float = 0.85,
        consecutive_losses: int = 0,
        signal_details: Optional[dict] = None,
    ) -> float:
        if balance <= 0:
            return self.min_trade_amount

        # Kelly Criterion (half-Kelly for safety)
        win_prob = max(0.01, min(0.99, confidence / 100.0))
        payout_ratio = max(0.01, payout)
        kelly = ((payout_ratio * win_prob) - (1 - win_prob)) / payout_ratio
        capped = max(0.0, min(self.risk_per_trade_pct, kelly * self.kelly_fraction_cap))

        # Signal strength multiplier (0-38 score → ×1.0 to ×1.5)
        score_mult = 1.0 + (score / 38.0) * 0.5
        capped *= score_mult

        # Loss streak protection
        loss_mult = 1.0
        if consecutive_losses >= 3:
            loss_mult = 0.20
        elif consecutive_losses == 2:
            loss_mult = 0.40
        elif consecutive_losses == 1:
            loss_mult = 0.70
        capped *= loss_mult

        # Portfolio cap
        available_cap = max(0, balance * self.max_exposure_pct - self._portfolio_exposure())
        if balance > 0:
            capped = min(capped, available_cap / balance)

        # Signal strength integration (if details provided)
        if signal_details:
            try:
                from bot_algorithms import Signal
                fake_sig = Signal(direction="UP", score=score, confidence=confidence,
                                  reasons=[], warnings=[], trade_size=0, details=signal_details)
                sss = SignalStrengthScore(fake_sig, consecutive_losses=consecutive_losses)
                sss_result = sss.calculate()
                strength_pct = sss_result.get("final_score", 50) / 100.0
                capped *= max(0.3, strength_pct)
            except Exception:
                pass

        size = balance * capped
        return round(max(self.min_trade_amount, min(size, self.max_trade_amount, available_cap)), 2)

    def record_trade_result(self, user_id: int = 0, profit: float = 0.0) -> Dict[str, float]:
        state = self._get_state(user_id)
        state.daily_pnl += profit
        state.trades_today += 1
        if profit < 0:
            state.consecutive_losses += 1
        else:
            state.consecutive_losses = 0
        return {
            "daily_pnl": round(state.daily_pnl, 2),
            "consecutive_losses": state.consecutive_losses,
            "trades_today": state.trades_today,
        }

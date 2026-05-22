from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import DefaultDict, Dict, Tuple

from bot_config import RiskSettings


@dataclass
class UserRiskState:
    trading_day: str
    daily_pnl: float = 0.0
    consecutive_losses: int = 0


class RiskManager:
    def __init__(self, settings: RiskSettings):
        self.settings = settings
        self._state: DefaultDict[int, UserRiskState] = defaultdict(self._new_state)

    def _new_state(self) -> UserRiskState:
        return UserRiskState(trading_day=self._today())

    def _today(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _ensure_current_day(self, user_id: int) -> UserRiskState:
        state = self._state[user_id]
        today = self._today()
        if state.trading_day != today:
            state.trading_day = today
            state.daily_pnl = 0.0
            state.consecutive_losses = 0
        return state

    def can_open_trade(self, user_id: int, balance: float | None = None) -> Tuple[bool, str]:
        state = self._ensure_current_day(user_id)

        if state.consecutive_losses >= self.settings.max_consecutive_losses:
            return False, "تم إيقاف التداول مؤقتًا بسبب الخسائر المتتالية."

        if balance and balance > 0:
            daily_loss_limit = balance * self.settings.daily_loss_limit_pct
            if abs(min(state.daily_pnl, 0.0)) >= daily_loss_limit:
                return False, "تم الوصول إلى الحد اليومي للخسارة."

        return True, "مسموح"

    def calculate_position_size(self, balance: float | None, confidence: int) -> float:
        if not balance or balance <= 0:
            return self.settings.min_trade_amount

        win_probability = max(0.01, min(0.99, confidence / 100))
        payout = max(0.01, self.settings.expected_payout)
        kelly_fraction = ((payout * win_probability) - (1 - win_probability)) / payout
        capped_fraction = max(
            0.0,
            min(
                self.settings.risk_per_trade_pct,
                kelly_fraction * self.settings.kelly_fraction_cap,
            ),
        )

        size = balance * capped_fraction
        return round(
            max(self.settings.min_trade_amount, min(size, self.settings.max_trade_amount)),
            2,
        )

    def record_trade_result(self, user_id: int, profit: float) -> Dict[str, float]:
        state = self._ensure_current_day(user_id)
        state.daily_pnl += profit
        if profit < 0:
            state.consecutive_losses += 1
        else:
            state.consecutive_losses = 0

        return {
            "daily_pnl": round(state.daily_pnl, 2),
            "consecutive_losses": state.consecutive_losses,
        }

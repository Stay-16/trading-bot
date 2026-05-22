from dataclasses import dataclass
from typing import Optional

from data_layer import MarketDataLayer
from decision_core import BinaryOptionsDecisionCore, DecisionPayload
from execution_layer import ExecutionLayer, ExecutionRequest
from risk_management import RiskManager
from signal_engine import SignalEngine


@dataclass(frozen=True)
class AnalysisOutcome:
    direction: str
    confidence: int
    features: object
    market_context: dict
    decision: DecisionPayload


@dataclass(frozen=True)
class ExecutionOutcome:
    allowed: bool
    reason: str
    amount: float
    success: bool = False
    trade_id: str = ""


class TradingOrchestrator:
    """Coordinates the full architecture end-to-end."""

    def __init__(
        self,
        data_layer: MarketDataLayer,
        signal_engine: SignalEngine,
        decision_core: BinaryOptionsDecisionCore,
        risk_manager: RiskManager,
        execution_layer: ExecutionLayer,
        timeframe_map: dict,
    ) -> None:
        self.data_layer = data_layer
        self.signal_engine = signal_engine
        self.decision_core = decision_core
        self.risk_manager = risk_manager
        self.execution_layer = execution_layer
        self.timeframe_map = timeframe_map

    async def analyze_market(self, pairdict: dict, timeframe: str) -> AnalysisOutcome:
        snapshot = await self.data_layer.fetch_snapshot(pairdict, timeframe)
        package = await self.signal_engine.analyze(snapshot)
        decision = self.decision_core.decide(package)

        market_context = {
            "volatility": snapshot.context.volatility,
            "trend_strength": snapshot.context.trend_strength,
            "market_condition": snapshot.context.market_condition,
            "trend_condition": snapshot.context.trend_condition,
            "decision_reasons": decision.result.reasons,
            "candle_pattern": package.candle_pattern,
            "price_sequence": package.price_sequence,
            "lstm_signal": package.lstm_signal,
        }

        package.ai_prediction["direction"] = decision.result.direction
        package.ai_prediction["confidence"] = decision.result.confidence
        package.ai_prediction["decision_score"] = decision.result.weighted_score
        package.ai_prediction["risk_level"] = decision.risk_level

        return AnalysisOutcome(
            direction=decision.result.direction,
            confidence=decision.result.confidence,
            features=package.features,
            market_context=market_context,
            decision=decision,
        )

    async def prepare_execution(
        self,
        user_id: int,
        pairdict: dict,
        timeframe: str,
        confidence: int,
    ) -> ExecutionOutcome:
        balance = await self.execution_layer.get_balance()
        can_trade, reason = self.risk_manager.can_open_trade(user_id, balance)
        if not can_trade:
            return ExecutionOutcome(allowed=False, reason=reason, amount=0.0)

        amount = self.risk_manager.calculate_position_size(balance, confidence)
        return ExecutionOutcome(allowed=True, reason="allowed", amount=amount)

    async def execute_trade(
        self,
        direction: str,
        asset: str,
        amount: float,
        duration: int,
    ) -> ExecutionOutcome:
        request = ExecutionRequest(
            direction=direction,
            asset=asset,
            amount=amount,
            duration=duration,
        )
        success, trade_id = await self.execution_layer.execute(request)
        return ExecutionOutcome(
            allowed=True,
            reason="executed" if success else trade_id,
            amount=amount,
            success=success,
            trade_id=trade_id if success else "",
        )

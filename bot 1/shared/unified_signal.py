from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class SignalVote:
    name: str
    direction: str
    confidence: int
    weight: float
    reason: str


@dataclass
class FusedResult:
    direction: str
    confidence: int
    weighted_score: float
    votes: List[SignalVote]
    reasons: List[str]


@dataclass
class UnifiedSignalPackage:
    confluence_score: int = 0
    confluence_direction: str = "WAIT"
    confluence_reasons: list = field(default_factory=list)

    tv_direction: str = "neutral"
    tv_confidence: int = 50
    tv_recommendation: str = "NEUTRAL"

    ml_direction: str = "neutral"
    ml_confidence: int = 50
    ml_method: str = "unavailable"

    ai_ensemble_direction: str = "neutral"
    ai_ensemble_confidence: int = 50

    fused_votes: List[SignalVote] = field(default_factory=list)
    fused_result: Optional[FusedResult] = None

    claude_analysis: Optional[Any] = None
    claude_confidence: int = 0

    final_direction: str = "WAIT"
    final_confidence: int = 0
    final_reasons: list = field(default_factory=list)
    final_warnings: list = field(default_factory=list)
    trade_size: float = 0.0
    raw_score: int = 0
    details: dict = field(default_factory=dict)

    def add_reason(self, reason: str):
        self.final_reasons.append(reason)

    def add_warning(self, warning: str):
        self.final_warnings.append(warning)

    def to_signal(self):
        from bot_algorithms import Signal
        return Signal(
            direction=self.final_direction,
            score=self.raw_score or self.confluence_score,
            confidence=self.final_confidence,
            reasons=self.final_reasons,
            warnings=self.final_warnings,
            trade_size=self.trade_size,
            details=self.details,
        )

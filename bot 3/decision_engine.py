from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class SignalVote:
    name: str
    direction: str
    confidence: int
    weight: float
    reason: str


@dataclass(frozen=True)
class DecisionResult:
    direction: str
    confidence: int
    weighted_score: float
    votes: List[SignalVote]
    reasons: List[str]


class WeightedDecisionEngine:
    def __init__(self, min_confidence_score: int = 75):
        self.min_confidence_score = min_confidence_score

    def decide(self, votes: List[SignalVote]) -> DecisionResult:
        if not votes:
            return DecisionResult(
                direction="neutral",
                confidence=0,
                weighted_score=0.0,
                votes=[],
                reasons=["No votes provided"],
            )

        call_score = 0.0
        put_score = 0.0
        reasons: List[str] = []

        for vote in votes:
            normalized_confidence = max(0, min(100, vote.confidence)) / 100
            contribution = vote.weight * normalized_confidence
            reasons.append(f"{vote.name}: {vote.reason}")

            if vote.direction == "call":
                call_score += contribution
            elif vote.direction == "put":
                put_score += contribution

        total_weight = sum(vote.weight for vote in votes) or 1.0
        net_score = abs(call_score - put_score) / total_weight
        confidence = int(min(95, max(call_score, put_score) / total_weight * 100))

        if call_score > put_score:
            direction = "call"
        elif put_score > call_score:
            direction = "put"
        else:
            direction = "neutral"

        if confidence < self.min_confidence_score:
            direction = "neutral"

        return DecisionResult(
            direction=direction,
            confidence=confidence,
            weighted_score=round(net_score * 100, 2),
            votes=votes,
            reasons=reasons,
        )

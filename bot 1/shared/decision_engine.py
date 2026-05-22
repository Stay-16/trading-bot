from dataclasses import dataclass, field
from typing import List, Optional


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
    def __init__(self, min_confidence_score: int = 70):
        self.min_confidence_score = min_confidence_score

    def decide(self, votes: List[SignalVote]) -> DecisionResult:
        if not votes:
            return DecisionResult(direction="WAIT", confidence=0, weighted_score=0.0, votes=[], reasons=["No votes"])

        call_score = 0.0
        put_score = 0.0
        reasons = []

        for vote in votes:
            norm_conf = max(0, min(100, vote.confidence)) / 100.0
            contrib = vote.weight * norm_conf
            reasons.append(f"{vote.name}: {vote.reason}")

            if vote.direction in ("UP", "call", "CALL"):
                call_score += contrib
            elif vote.direction in ("DOWN", "put", "PUT"):
                put_score += contrib

        total_weight = sum(v.weight for v in votes) or 1.0
        confidence = int(min(95, max(call_score, put_score) / total_weight * 100))

        if call_score > put_score:
            direction = "UP"
        elif put_score > call_score:
            direction = "DOWN"
        else:
            direction = "WAIT"

        if confidence < self.min_confidence_score:
            direction = "WAIT"

        net_score = abs(call_score - put_score) / total_weight
        return DecisionResult(
            direction=direction,
            confidence=confidence,
            weighted_score=round(net_score * 100, 2),
            votes=votes,
            reasons=reasons,
        )


def build_fused_votes(
    confluence_score: int,
    confluence_direction: str,
    tv_direction: str = "neutral",
    tv_confidence: int = 50,
    tv_rec: str = "NEUTRAL",
    ai_direction: str = "neutral",
    ai_confidence: int = 50,
    ai_method: str = "unavailable",
    lstm_direction: str = "neutral",
    lstm_confidence: int = 50,
    market_context: Optional[dict] = None,
) -> List[SignalVote]:
    """Build 7 votes: 6 from bot2 + Confluence as 7th with 25% weight."""
    votes = [
        SignalVote(name="traditional", direction=tv_direction, confidence=tv_confidence,
                   weight=0.18, reason=f"TradingView={tv_rec}"),
        SignalVote(name="ai_model", direction=ai_direction, confidence=ai_confidence,
                   weight=0.18, reason=f"Method={ai_method}"),
        SignalVote(name="lstm", direction=lstm_direction, confidence=lstm_confidence,
                   weight=0.15, reason=f"Method={lstm_direction}"),
    ]

    # Trend filter from confluence details
    trend_dir = "UP" if confluence_direction == "UP" else "DOWN" if confluence_direction == "DOWN" else "WAIT"
    trend_conf = min(70, 30 + confluence_score)
    votes.append(SignalVote(name="trend_filter", direction=trend_dir,
                            confidence=trend_conf, weight=0.12,
                            reason=f"Confluence score={confluence_score}/38"))

    # Volatility filter
    vol_dir = "WAIT"
    vol_conf = 50
    if market_context:
        volatility = market_context.get("volatility", 0)
        if volatility > 0.03:
            vol_dir = "WAIT"
            vol_conf = 35
        elif volatility < 0.01:
            vol_conf = 65
    votes.append(SignalVote(name="volatility_filter", direction=vol_dir,
                            confidence=vol_conf, weight=0.07, reason="Market vol filter"))

    # Candle pattern / momentum
    votes.append(SignalVote(name="candle_pattern", direction=trend_dir,
                            confidence=min(60, confluence_score * 2), weight=0.05,
                            reason=f"Confluence momentum"))  # CAND-1-REMOVAL

    # ── 7th vote: ConfluenceEngine (25% weight) ───────────
    conf_map = {"UP": "call", "DOWN": "put", "WAIT": "neutral"}
    conf_dir = conf_map.get(confluence_direction, "neutral")
    conf_pct = min(95, int(confluence_score * 2.5))
    votes.append(SignalVote(name="confluence_engine", direction=conf_dir,
                            confidence=conf_pct, weight=0.25,
                            reason=f"Confluence {confluence_score}/38 points"))

    return votes

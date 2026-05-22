from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple

from shared.unified_signal import UnifiedSignalPackage

log = logging.getLogger("AutoExec")


class AutoExecuteGate:
    def __init__(
        self,
        min_confluence_score: int = 9,
        min_ensemble_confidence: int = 70,
        require_claude_agreement: bool = True,
        max_consecutive_losses: int = 3,
    ):
        self.min_confluence = min_confluence_score
        self.min_ensemble = min_ensemble_confidence
        self.require_claude = require_claude_agreement
        self.max_cons_losses = max_consecutive_losses

    def evaluate(self, usp: UnifiedSignalPackage, consecutive_losses: int = 0) -> Tuple[bool, str]:
        reasons = []

        if usp.confluence_score < self.min_confluence:
            reasons.append(f"Confluence {usp.confluence_score} < {self.min_confluence}")
        else:
            reasons.append(f"Confluence {usp.confluence_score} >= {self.min_confluence}")

        if usp.final_confidence < self.min_ensemble:
            reasons.append(f"Confidence {usp.final_confidence}% < {self.min_ensemble}%")
        else:
            reasons.append(f"Confidence {usp.final_confidence}% >= {self.min_ensemble}%")

        if usp.final_direction in ("WAIT", "neutral"):
            reasons.append("Final direction is WAIT")
        else:
            reasons.append(f"Direction: {usp.final_direction}")

        if self.require_claude and usp.claude_analysis is None:
            reasons.append("Claude AI not available")
        elif self.require_claude and usp.claude_analysis:
            claude_dir = getattr(usp.claude_analysis, 'final_direction', 'WAIT')
            if claude_dir != usp.final_direction and claude_dir != 'WAIT':
                reasons.append(f"Claude disagrees ({claude_dir} vs {usp.final_direction})")
            else:
                reasons.append("Claude agrees")

        if consecutive_losses >= self.max_cons_losses:
            reasons.append(f"Circuit breaker: {consecutive_losses} losses")
        else:
            reasons.append(f"Loss streak OK ({consecutive_losses})")

        passed = all([
            usp.confluence_score >= self.min_confluence,
            usp.final_confidence >= self.min_ensemble,
            usp.final_direction not in ("WAIT", "neutral"),
            consecutive_losses < self.max_cons_losses,
        ])
        return passed, " | ".join(reasons)

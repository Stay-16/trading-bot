from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

log = logging.getLogger("Adaptive")


@dataclass
class AdaptiveThresholds:
    min_confluence: int = 6
    min_confidence: int = 60
    max_trade_size_pct: float = 0.05
    base_thresholds: Dict[str, int] = None

    def __post_init__(self):
        if self.base_thresholds is None:
            self.base_thresholds = {
                "normal": {"min_confluence": 7, "min_confidence": 60},
                "trending": {"min_confluence": 6, "min_confidence": 55},
                "ranging": {"min_confluence": 8, "min_confidence": 65},
                "volatile": {"min_confluence": 10, "min_confidence": 75},
                "quiet": {"min_confluence": 7, "min_confidence": 60},
            }

    def adjust(self, market_condition: str = "normal") -> "AdaptiveThresholds":
        key = "normal"
        if market_condition in ("high_vol", "volatile", "VOLATILE"):
            key = "volatile"
        elif market_condition in ("trending", "TRENDING"):
            key = "trending"
        elif market_condition in ("ranging", "RANGING"):
            key = "ranging"
        elif market_condition in ("low_vol", "quiet"):
            key = "quiet"
        base = self.base_thresholds.get(key, self.base_thresholds["normal"])
        return AdaptiveThresholds(
            min_confluence=base.get("min_confluence", self.min_confluence),
            min_confidence=base.get("min_confidence", self.min_confidence),
            max_trade_size_pct=self.max_trade_size_pct,
            base_thresholds=self.base_thresholds,
        )

    def should_execute(self, score: int, confidence: float) -> bool:
        return score >= self.min_confluence and confidence >= self.min_confidence

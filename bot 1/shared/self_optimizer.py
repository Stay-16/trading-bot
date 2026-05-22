from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("Optimizer")


class SelfOptimizer:
    def __init__(self, model_weights_path: str = "advanced_ai_model_weights.json"):
        self.weights_path = model_weights_path
        self.performance: Dict[str, List[dict]] = {}

    async def analyze_performance(self, db) -> dict:
        cur = await db._db.execute("""
            SELECT score, confidence, result, profit, symbol, opened_at
            FROM trades
            WHERE result IN ('win','loss')
            ORDER BY opened_at DESC
            LIMIT 500
        """)
        rows = await cur.fetchall()
        if not rows:
            return {}
        total = len(rows)
        wins = sum(1 for r in rows if r["result"] == "win")
        profit = sum((r["profit"] or 0) for r in rows)

        by_score = {}
        for r in rows:
            bracket = (r["score"] or 0) // 5 * 5
            if bracket not in by_score:
                by_score[bracket] = {"total": 0, "wins": 0}
            by_score[bracket]["total"] += 1
            if r["result"] == "win":
                by_score[bracket]["wins"] += 1

        score_insight = {}
        for bracket, data in sorted(by_score.items()):
            wr = data["wins"] / data["total"] * 100 if data["total"] > 0 else 0
            score_insight[f"{bracket}-{bracket+4}"] = {
                "win_rate": round(wr, 1),
                "trades": data["total"],
            }

        return {
            "total": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "net_profit": round(profit, 2),
            "by_score": score_insight,
            "best_score_bracket": max(score_insight, key=lambda k: score_insight[k]["win_rate"]) if score_insight else None,
        }

    def adjust_weights(self, analysis: dict) -> dict:
        if not analysis.get("by_score"):
            return {}
        adjustments = {}
        for bracket, info in analysis["by_score"].items():
            wr = info["win_rate"]
            if wr < 40 and info["trades"] >= 10:
                adjustments[bracket] = -0.1
            elif wr > 70 and info["trades"] >= 10:
                adjustments[bracket] = 0.05
        return adjustments

    async def weekly_optimize(self, db, advanced_ai=None) -> str:
        analysis = await self.analyze_performance(db)
        if not analysis:
            return "📭 لا توجد بيانات كافية للتحسين"

        adj = self.adjust_weights(analysis)
        lines = [
            "🔄 *التحسين الأسبوعي التلقائي*",
            "━━━━━━━━━━━━━━━━",
            f"  • إجمالي الصفقات: {analysis['total']}",
            f"  • نسبة النجاح: {analysis['win_rate']}%",
            f"  • صافي الربح: ${analysis['net_profit']:.2f}",
        ]
        if analysis.get("best_score_bracket"):
            lines.append(f"  • أفضل نقاط: {analysis['best_score_bracket']}")

        if adj:
            lines.append("")
            lines.append("*تعديلات الأوزان:*")
            for bracket, change in adj.items():
                lines.append(f"  • {bracket}: {change:+.2f}")

        if advanced_ai and analysis["by_score"]:
            try:
                best_bracket = max(analysis["by_score"], key=lambda k: analysis["by_score"][k]["win_rate"])
                current_weights = getattr(advanced_ai, 'model_weights', {})
                for name in current_weights:
                    if analysis["total"] > 50:
                        current_weights[name] = min(2.0, current_weights.get(name, 1.0) + 0.05)
                    else:
                        current_weights[name] = max(0.5, current_weights.get(name, 1.0) - 0.05)
                lines.append(f"  • نموذج: {len(current_weights)} أوزان محدّثة")
            except Exception as e:
                log.debug("Weight adjust error: %s", e)

        return "\n".join(lines)

from __future__ import annotations

import logging
import time
from datetime import datetime

from ui import _esc

log = logging.getLogger("DBReporter")


class DBReporter:
    def __init__(self, db):
        self.db = db

    async def report_today(self) -> str:
        stats = await self.db.get_today_stats()
        t = stats["total"]
        w = stats["wins"]
        l = stats["losses"]
        wr = stats["win_rate"]
        lines = [
            "📊 *تقرير اليوم*",
            "━━━━━━━━━━━━━━━━",
            f"  • الإجمالي: {t}",
            f"  • فوز: {w} | خسارة: {l}",
            f"  • نسبة نجاح: {wr:.1f}%",
            f"  • صافي الربح: ${stats['net_profit']:.2f}",
            f"  • متوسط النقاط: {stats['avg_score']:.1f}",
            f"  • متوسط الثقة: {stats['avg_confidence']:.1f}%",
        ]
        return "\n".join(lines)

    async def report_best_pairs(self, days: int = 7) -> str:
        rows = await self.db.get_best_symbols(days)
        if not rows:
            return "📭 لا توجد بيانات كافية"
        lines = ["🏆 *أفضل الأزواج (آخر 7 أيام)*", "━━━━━━━━━━━━━━━━"]
        for r in rows:
            total = r["total"] or 0
            wins = r["wins"] or 0
            wr = round(wins / total * 100, 1) if total > 0 else 0
            profit = round(r["net_profit"] or 0, 2)
            lines.append(f"  • {r['symbol']}: {wins}/{total} ({wr}%) | ${profit}")
        return "\n".join(lines)

    async def report_weekly(self) -> str:
        today = datetime.utcnow()
        days_7 = await self.db.get_equity_curve(7)
        days_30 = await self.db.get_equity_curve(30)
        total_7 = sum(d.get("trades", 0) or 0 for d in days_7)
        wins_7 = sum(d.get("wins", 0) or 0 for d in days_7)
        profit_7 = sum(d.get("net_profit", 0) or 0 for d in days_7)
        total_30 = sum(d.get("trades", 0) or 0 for d in days_30)
        wins_30 = sum(d.get("wins", 0) or 0 for d in days_30)
        profit_30 = sum(d.get("net_profit", 0) or 0 for d in days_30)
        lines = [
            f"📈 *التقرير الأسبوعي* — {today.strftime('%Y-%m-%d')}",
            "━━━━━━━━━━━━━━━━",
            f"*آخر 7 أيام:*",
            f"  • صفقات: {total_7}",
            f"  • فوز: {wins_7}",
            f"  • ربح: ${profit_7:.2f}",
            "",
            f"*آخر 30 يوم:*",
            f"  • صفقات: {total_30}",
            f"  • فوز: {wins_30}",
            f"  • ربح: ${profit_30:.2f}",
        ]
        return "\n".join(lines)

    async def report_model_accuracy(self) -> str:
        cur = await self.db._db.execute("""
            SELECT score, confidence, result, profit
            FROM trades
            WHERE result IN ('win','loss')
              AND opened_at > ?
            ORDER BY opened_at DESC
            LIMIT 500
        """, (time.time() - 30 * 86400,))
        rows = await cur.fetchall()
        if not rows:
            return "📭 لا توجد بيانات"
        total = len(rows)
        wins = sum(1 for r in rows if r["result"] == "win")
        high_conf = [r for r in rows if (r["confidence"] or 0) >= 70]
        high_wins = sum(1 for r in high_conf if r["result"] == "win")
        high_total = len(high_conf)
        high_wr = round(high_wins / high_total * 100, 1) if high_total > 0 else 0
        med_conf = [r for r in rows if 50 <= (r["confidence"] or 0) < 70]
        med_wins = sum(1 for r in med_conf if r["result"] == "win")
        med_total = len(med_conf)
        med_wr = round(med_wins / med_total * 100, 1) if med_total > 0 else 0
        low_conf = [r for r in rows if (r["confidence"] or 0) < 50]
        low_wins = sum(1 for r in low_conf if r["result"] == "win")
        low_total = len(low_conf)
        low_wr = round(low_wins / low_total * 100, 1) if low_total > 0 else 0
        lines = [
            "📊 *دقة النماذج (آخر 30 يوم)*",
            "━━━━━━━━━━━━━━━━",
            f"  • الإجمالي: {total} | فوز: {wins} ({round(wins/total*100,1)}%)",
            "",
            "*حسب الثقة:*",
            f"  • عالية (≥70%): {high_total} صفقة — دقة {high_wr}%",
            f"  • متوسطة (50-69%): {med_total} صفقة — دقة {med_wr}%",
            f"  • منخفضة (<50%): {low_total} صفقة — دقة {low_wr}%",
        ]
        return "\n".join(lines)

    async def report_pair_stats(self, pair: str) -> str:
        cur = await self.db._db.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) AS wins,
                   SUM(profit) AS net_profit,
                   AVG(score) AS avg_score,
                   AVG(confidence) AS avg_confidence
            FROM trades
            WHERE symbol=? AND result != 'pending'
        """, (pair,))
        row = await cur.fetchone()
        if not row or (row["total"] or 0) == 0:
            return f"📭 لا توجد بيانات للزوج {pair}"
        total = row["total"] or 0
        wins = row["wins"] or 0
        losses = total - wins
        wr = round(wins / total * 100, 1) if total > 0 else 0
        lines = [
            f"📊 *إحصائيات {pair}*",
            "━━━━━━━━━━━━━━━━",
            f"  • إجمالي: {total}",
            f"  • فوز: {wins} | خسارة: {losses}",
            f"  • نسبة نجاح: {wr}%",
            f"  • صافي الربح: ${row['net_profit']:.2f}",
            f"  • متوسط النقاط: {row['avg_score']:.1f}",
            f"  • متوسط الثقة: {row['avg_confidence']:.1f}%",
        ]
        return "\n".join(lines)

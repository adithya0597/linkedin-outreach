"""Template performance analytics — tracks response rates, comparisons, and trends."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, OutreachORM

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_CHAR_BUCKETS = [
    (0, 100, "0-100"),
    (101, 200, "101-200"),
    (201, 300, "201-300"),
    (301, 400, "301-400"),
]


class TemplateAnalytics:
    """Analyze outreach template performance from the database."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_template_stats(self) -> list[dict]:
        """Per-template statistics: total drafted, sent, responded, response rate, avg char count."""
        sent_case = case(
            (OutreachORM.stage.in_(["Sent", "Responded"]), 1), else_=0
        )
        responded_case = case(
            (OutreachORM.stage == "Responded", 1), else_=0
        )

        rows = (
            self.session.query(
                OutreachORM.template_type,
                func.count(OutreachORM.id).label("total_drafted"),
                func.sum(sent_case).label("total_sent"),
                func.sum(responded_case).label("total_responded"),
                func.avg(OutreachORM.character_count).label("avg_char_count"),
            )
            .group_by(OutreachORM.template_type)
            .all()
        )

        results = []
        for row in rows:
            total_sent = int(row.total_sent or 0)
            total_responded = int(row.total_responded or 0)
            response_rate = (
                round(total_responded / total_sent * 100, 1)
                if total_sent > 0
                else 0.0
            )
            results.append(
                {
                    "template": row.template_type,
                    "total_drafted": int(row.total_drafted or 0),
                    "total_sent": total_sent,
                    "total_responded": total_responded,
                    "response_rate": response_rate,
                    "avg_char_count": round(float(row.avg_char_count or 0), 1),
                }
            )
        logger.debug("Template stats computed for {} templates", len(results))
        return results

    def get_template_comparison(self) -> dict:
        """Compare connection_request variants (a/b/c) by response rate."""
        stats = self.get_template_stats()
        cr_stats = [
            s
            for s in stats
            if s["template"].startswith("connection_request_")
        ]

        if not cr_stats:
            return {
                "best_template": None,
                "worst_template": None,
                "templates": [],
                "recommendation": "No connection request data available.",
            }

        # Only consider templates with >= 3 sends for recommendation
        qualified = [s for s in cr_stats if s["total_sent"] >= 3]

        if not qualified:
            best = max(cr_stats, key=lambda s: s["response_rate"])
            worst = min(cr_stats, key=lambda s: s["response_rate"])
            return {
                "best_template": best["template"],
                "worst_template": worst["template"],
                "templates": cr_stats,
                "recommendation": (
                    "Insufficient data: no template has 3+ sends yet. "
                    "Keep testing all variants."
                ),
            }

        best = max(qualified, key=lambda s: s["response_rate"])
        worst = min(qualified, key=lambda s: s["response_rate"])
        return {
            "best_template": best["template"],
            "worst_template": worst["template"],
            "templates": cr_stats,
            "recommendation": (
                f"Use '{best['template']}' — "
                f"{best['response_rate']}% response rate "
                f"({best['total_responded']}/{best['total_sent']} sends)."
            ),
        }

    def get_tier_template_stats(self) -> dict:
        """Cross-tabulate tier x template: {tier: {template: {sent, responded, rate}}}."""
        rows = (
            self.session.query(
                CompanyORM.tier,
                OutreachORM.template_type,
                OutreachORM.stage,
            )
            .join(CompanyORM, OutreachORM.company_id == CompanyORM.id)
            .all()
        )

        table: dict[str, dict[str, dict[str, int | float]]] = defaultdict(
            lambda: defaultdict(lambda: {"sent": 0, "responded": 0, "rate": 0.0})
        )

        for tier, template, stage in rows:
            if stage in ("Sent", "Responded"):
                table[tier][template]["sent"] += 1
            if stage == "Responded":
                table[tier][template]["responded"] += 1

        # Calculate rates
        result: dict = {}
        for tier, templates in table.items():
            result[tier] = {}
            for template, counts in templates.items():
                sent = counts["sent"]
                responded = counts["responded"]
                result[tier][template] = {
                    "sent": sent,
                    "responded": responded,
                    "rate": round(responded / sent * 100, 1) if sent > 0 else 0.0,
                }

        logger.debug("Tier-template stats computed for {} tiers", len(result))
        return result

    def get_weekly_trends(self, weeks: int = 4) -> list[dict]:
        """Per-week breakdown of sends, responses, rates, and top template."""
        cutoff = datetime.now() - timedelta(weeks=weeks)

        rows = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.sent_at.isnot(None),
                OutreachORM.sent_at >= cutoff,
            )
            .all()
        )

        # Group by ISO week
        week_data: dict[str, dict] = defaultdict(
            lambda: {
                "total_sent": 0,
                "total_responded": 0,
                "templates": defaultdict(int),
            }
        )

        for row in rows:
            iso = row.sent_at.isocalendar()
            week_start = datetime.fromisocalendar(iso[0], iso[1], 1).strftime(
                "%Y-%m-%d"
            )
            week_data[week_start]["total_sent"] += 1
            week_data[week_start]["templates"][row.template_type] += 1
            if row.stage == "Responded":
                week_data[week_start]["total_responded"] += 1

        results = []
        for week_start in sorted(week_data.keys()):
            data = week_data[week_start]
            sent = data["total_sent"]
            responded = data["total_responded"]
            top_template = (
                max(data["templates"], key=data["templates"].get)
                if data["templates"]
                else None
            )
            results.append(
                {
                    "week_start": week_start,
                    "total_sent": sent,
                    "total_responded": responded,
                    "rate": round(responded / sent * 100, 1) if sent > 0 else 0.0,
                    "top_template": top_template,
                }
            )

        logger.debug("Weekly trends computed for {} weeks", len(results))
        return results

    def get_day_of_week_analysis(self) -> list[dict]:
        """Response rates by day of week (Mon-Sun). Only includes days with data."""
        rows = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.sent_at.isnot(None))
            .all()
        )
        day_data: dict[int, dict] = {}
        for row in rows:
            day_num = row.sent_at.weekday()
            if day_num not in day_data:
                day_data[day_num] = {"sent": 0, "responded": 0}
            day_data[day_num]["sent"] += 1
            if row.stage == "Responded":
                day_data[day_num]["responded"] += 1

        results = []
        for day_num in sorted(day_data.keys()):
            d = day_data[day_num]
            rate = round(d["responded"] / d["sent"] * 100, 1) if d["sent"] > 0 else 0.0
            results.append({
                "day": DAY_NAMES[day_num],
                "day_number": day_num,
                "total_sent": d["sent"],
                "total_responded": d["responded"],
                "response_rate": rate,
            })
        logger.debug("Day-of-week analysis computed for {} days", len(results))
        return results

    def get_char_count_correlation(self) -> list[dict]:
        """Character count buckets vs response rate."""
        rows = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.sent_at.isnot(None))
            .all()
        )
        buckets: dict[str, dict] = {}
        for row in rows:
            cc = row.character_count or 0
            label = "400+"
            for lo, hi, lbl in _CHAR_BUCKETS:
                if lo <= cc <= hi:
                    label = lbl
                    break
            if label not in buckets:
                buckets[label] = {"sent": 0, "responded": 0}
            buckets[label]["sent"] += 1
            if row.stage == "Responded":
                buckets[label]["responded"] += 1

        # Sort by bucket order
        order = ["0-100", "101-200", "201-300", "301-400", "400+"]
        results = []
        for label in order:
            if label in buckets:
                d = buckets[label]
                rate = round(d["responded"] / d["sent"] * 100, 1) if d["sent"] > 0 else 0.0
                results.append({
                    "bucket": label,
                    "total_sent": d["sent"],
                    "total_responded": d["responded"],
                    "response_rate": rate,
                })
        logger.debug("Char count correlation computed for {} buckets", len(results))
        return results

    def export_csv(self, path: str) -> int:
        """Export all template stats to CSV. Returns number of rows written."""
        stats = self.get_template_stats()
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "template", "total_drafted", "total_sent",
                "total_responded", "response_rate", "avg_char_count",
            ])
            writer.writeheader()
            for row in stats:
                writer.writerow(row)
        logger.info("Exported {} template stats to {}", len(stats), path)
        return len(stats)

    def export_report(self) -> str:
        """Generate a full markdown report with all analytics sections."""
        lines = ["# Template Analytics Report", ""]

        # Section 1: Template Stats
        lines.append("## Template Performance")
        lines.append("")
        stats = self.get_template_stats()
        if stats:
            lines.append(
                "| Template | Drafted | Sent | Responded | Rate | Avg Chars |"
            )
            lines.append(
                "|----------|---------|------|-----------|------|-----------|"
            )
            for s in stats:
                lines.append(
                    f"| {s['template']} | {s['total_drafted']} | "
                    f"{s['total_sent']} | {s['total_responded']} | "
                    f"{s['response_rate']}% | {s['avg_char_count']} |"
                )
        else:
            lines.append("No outreach data available.")
        lines.append("")

        # Section 2: Template Comparison
        lines.append("## Connection Request Comparison")
        lines.append("")
        comparison = self.get_template_comparison()
        lines.append(f"**Best:** {comparison['best_template']}")
        lines.append(f"**Worst:** {comparison['worst_template']}")
        lines.append(f"**Recommendation:** {comparison['recommendation']}")
        lines.append("")

        # Section 3: Tier Breakdown
        lines.append("## Tier x Template Breakdown")
        lines.append("")
        tier_stats = self.get_tier_template_stats()
        if tier_stats:
            for tier, templates in sorted(tier_stats.items()):
                lines.append(f"### {tier}")
                lines.append("")
                lines.append("| Template | Sent | Responded | Rate |")
                lines.append("|----------|------|-----------|------|")
                for template, counts in sorted(templates.items()):
                    lines.append(
                        f"| {template} | {counts['sent']} | "
                        f"{counts['responded']} | {counts['rate']}% |"
                    )
                lines.append("")
        else:
            lines.append("No tier data available.")
            lines.append("")

        # Section 4: Weekly Trends
        lines.append("## Weekly Trends")
        lines.append("")
        trends = self.get_weekly_trends()
        if trends:
            lines.append(
                "| Week | Sent | Responded | Rate | Top Template |"
            )
            lines.append(
                "|------|------|-----------|------|--------------|"
            )
            for t in trends:
                lines.append(
                    f"| {t['week_start']} | {t['total_sent']} | "
                    f"{t['total_responded']} | {t['rate']}% | "
                    f"{t['top_template']} |"
                )
        else:
            lines.append("No weekly data available.")
        lines.append("")

        report = "\n".join(lines)
        logger.info("Analytics report generated ({} chars)", len(report))
        return report

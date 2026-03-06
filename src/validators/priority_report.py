"""Priority report — re-score companies and generate tier-grouped priority matrix."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM
from src.pipeline.orchestrator import Pipeline
from src.validators.domain_scorer import DomainMatchScorer


class PriorityReporter:
    """Generate prioritized reports grouped by tier and domain."""

    def __init__(self, session: Session):
        self.session = session
        self.pipeline = Pipeline(session)
        self.domain_scorer = DomainMatchScorer()

    def generate_priority_matrix(self, include_semantic: bool = True) -> dict:
        """Score all companies and group by tier.

        Calls Pipeline.score_all(include_semantic), then groups companies by tier,
        sorted by fit_score DESC within each tier.

        Returns dict with tiers (tier_name -> list of company dicts), total_scored, avg_score.
        """
        # Re-score all companies
        score_result = self.pipeline.score_all(include_semantic=include_semantic)

        # Fetch all non-disqualified companies
        companies = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.is_disqualified == False)  # noqa: E712
            .order_by(CompanyORM.fit_score.desc().nullslast())
            .all()
        )

        # Group by tier
        tiers: dict[str, list[dict]] = {}
        total_score = 0.0
        count = 0

        for company in companies:
            tier = company.tier or "Untiered"
            if tier not in tiers:
                tiers[tier] = []

            # Get domain match
            domain_score, domain_name = self.domain_scorer.score_domain_match(company)

            company_dict = {
                "name": company.name,
                "fit_score": company.fit_score or 0,
                "h1b_status": company.h1b_status or "Unknown",
                "stage": company.stage or "To apply",
                "domain": domain_name,
                "domain_score": domain_score,
                "hiring_manager": company.hiring_manager or "",
                "data_completeness": company.data_completeness or 0,
            }
            tiers[tier].append(company_dict)
            total_score += company.fit_score or 0
            count += 1

        # Sort within each tier by fit_score DESC
        for tier_name in tiers:
            tiers[tier_name].sort(key=lambda x: x["fit_score"], reverse=True)

        avg_score = round(total_score / count, 2) if count > 0 else 0

        return {
            "tiers": tiers,
            "total_scored": score_result.get("scored", count),
            "avg_score": avg_score,
        }

    def get_domain_breakdown(self) -> dict:
        """Group companies by their best-match experience domain.

        Uses DomainMatchScorer.batch_score() to score all companies,
        then groups by domain.

        Returns dict: {domain_name: {companies: list, avg_score: float, count: int}}
        """
        companies = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.is_disqualified == False)  # noqa: E712
            .all()
        )

        scored = self.domain_scorer.batch_score(companies)

        domains: dict[str, dict] = {}
        for company, score, domain in scored:
            if domain not in domains:
                domains[domain] = {"companies": [], "total_score": 0, "count": 0}
            domains[domain]["companies"].append(company.name)
            domains[domain]["total_score"] += score
            domains[domain]["count"] += 1

        # Calculate averages
        result = {}
        for domain, data in domains.items():
            result[domain] = {
                "companies": data["companies"],
                "avg_score": round(data["total_score"] / data["count"], 2) if data["count"] > 0 else 0,
                "count": data["count"],
            }

        return result

    def export_markdown(self, output_path: str | None = None) -> str:
        """Export priority matrix as markdown.

        Args:
            output_path: Optional file path to write. If None, just returns string.

        Returns:
            Markdown formatted report string.
        """
        matrix = self.generate_priority_matrix(include_semantic=False)

        lines = []
        lines.append("# Priority Matrix Report")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Total Scored:** {matrix['total_scored']}")
        lines.append(f"**Average Score:** {matrix['avg_score']}")
        lines.append("")

        for tier_name, companies in sorted(matrix["tiers"].items()):
            lines.append(f"## {tier_name}")
            lines.append("")
            lines.append("| # | Company | Fit Score | H1B | Domain | Stage |")
            lines.append("|---|---------|-----------|-----|--------|-------|")

            for i, c in enumerate(companies, 1):
                lines.append(
                    f"| {i} | {c['name']} | {c['fit_score']:.0f} | "
                    f"{c['h1b_status']} | {c['domain']} | {c['stage']} |"
                )
            lines.append("")

        report = "\n".join(lines)

        if output_path:
            Path(output_path).write_text(report)
            logger.info(f"Priority report exported to {output_path}")

        return report

    def export_notion_update(self, dry_run: bool = False) -> dict:
        """Update Notion fit scores for re-scored companies.

        Returns dict with updated, unchanged, errors.
        """
        import os

        from src.integrations.notion_sync import NotionCRM

        result = {"updated": 0, "unchanged": 0, "errors": []}

        companies = (
            self.session.query(CompanyORM)
            .filter(
                CompanyORM.is_disqualified == False,  # noqa: E712
                CompanyORM.fit_score.isnot(None),
            )
            .all()
        )

        if dry_run:
            result["updated"] = len(companies)
            return result

        api_key = os.getenv("NOTION_API_KEY", "")
        db_id = os.getenv("NOTION_DATABASE_ID", "")
        if not api_key:
            result["errors"].append("NOTION_API_KEY not set")
            return result

        crm = NotionCRM(api_key=api_key, database_id=db_id)

        async def _update():
            for company in companies:
                try:
                    page_id = await crm.find_page_by_name(company.name)
                    if page_id:
                        await crm._request(
                            "PATCH",
                            f"https://api.notion.com/v1/pages/{page_id}",
                            json={
                                "properties": {
                                    "Fit Score": {"number": company.fit_score},
                                }
                            },
                        )
                        result["updated"] += 1
                    else:
                        result["unchanged"] += 1
                except Exception as e:
                    result["errors"].append(f"{company.name}: {e}")

        asyncio.run(_update())
        return result

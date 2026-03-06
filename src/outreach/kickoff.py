"""Tier 1 kickoff — unified workflow: draft → sequence → send report."""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, ContactORM, OutreachORM
from src.outreach.batch_engine import BatchOutreachEngine


class Tier1Kickoff:
    """Chain draft_all → build_sequence → send report into a single workflow."""

    def __init__(self, session: Session):
        self.session = session
        self.engine = BatchOutreachEngine(session)

    def get_ready_companies(self) -> list[dict]:
        """Get Tier 1 companies ready for outreach (not disqualified, no existing OutreachORM records).

        Returns list of dicts: [{company: CompanyORM, contact: ContactORM|None}]
        """
        companies = (
            self.session.query(CompanyORM)
            .filter(
                CompanyORM.tier == "Tier 1 - HIGH",
                CompanyORM.is_disqualified == False,  # noqa: E712
            )
            .order_by(CompanyORM.fit_score.desc().nullslast())
            .all()
        )

        ready = []
        for company in companies:
            # Skip if already has outreach records
            existing = (
                self.session.query(OutreachORM)
                .filter(OutreachORM.company_id == company.id)
                .first()
            )
            if existing:
                continue

            # Get best contact
            contact = (
                self.session.query(ContactORM)
                .filter(ContactORM.company_id == company.id)
                .order_by(ContactORM.contact_score.desc())
                .first()
            )
            ready.append({"company": company, "contact": contact})

        return ready

    def run(self, dry_run: bool = False) -> dict:
        """Run Tier 1 kickoff: draft → sequence → send report.

        Args:
            dry_run: If True, return ready companies without creating records.

        Returns:
            Dict with drafted, sequences_built, report, errors.
        """
        ready = self.get_ready_companies()
        result = {
            "drafted": 0,
            "sequences_built": 0,
            "report": "",
            "errors": [],
            "companies": [r["company"].name for r in ready],
        }

        if dry_run:
            result["report"] = self.generate_send_report(ready, dry_run=True)
            return result

        for item in ready:
            company = item["company"]
            contact = item["contact"]
            try:
                # Step 1: Draft
                drafts = self.engine.draft_for_company(
                    company, contact, template_types=["connection_request"]
                )
                result["drafted"] += len(drafts)

                # Step 2: Build sequence
                if contact:
                    sequence = self.engine.build_sequence(
                        company.name, contact.name
                    )
                    if sequence:
                        result["sequences_built"] += 1
            except Exception as e:
                result["errors"].append(f"{company.name}: {e}")
                logger.error(f"Kickoff failed for {company.name}: {e}")

        self.session.commit()

        # Step 3: Generate report
        result["report"] = self.generate_send_report(ready)
        return result

    def generate_send_report(
        self, ready: list[dict] | None = None, dry_run: bool = False
    ) -> str:
        """Generate markdown send report.

        Args:
            ready: List of ready company dicts. If None, fetches from DB.
            dry_run: If True, label as dry run.

        Returns:
            Markdown formatted report string.
        """
        if ready is None:
            ready = self.get_ready_companies()

        lines = []
        mode = " (DRY RUN)" if dry_run else ""
        lines.append(f"# Tier 1 Kickoff Report{mode}")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Companies:** {len(ready)}")
        lines.append("")

        if not ready:
            lines.append("No Tier 1 companies ready for outreach.")
            return "\n".join(lines)

        lines.append("| # | Company | Contact | Fit Score | Template | LinkedIn |")
        lines.append("|---|---------|---------|-----------|----------|----------|")

        for i, item in enumerate(ready, 1):
            company = item["company"]
            contact = item["contact"]
            contact_name = contact.name if contact else "TBD"
            fit = company.fit_score or 0
            template = "connection_request_a.j2"
            linkedin = company.linkedin_url or ""

            # Get outreach record for char count if exists
            outreach = (
                self.session.query(OutreachORM)
                .filter(OutreachORM.company_id == company.id)
                .first()
            )
            if outreach:
                template = outreach.template_type or template

            lines.append(
                f"| {i} | {company.name} | {contact_name} | {fit:.0f} | {template} | {linkedin} |"
            )

        lines.append("")
        lines.append(f"**Total ready:** {len(ready)}")
        return "\n".join(lines)

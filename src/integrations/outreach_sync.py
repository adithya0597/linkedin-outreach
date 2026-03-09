"""Outreach stage sync — push OutreachORM stages to Notion Applications DB."""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, OutreachORM
from src.integrations.notion_base import NOTION_BASE
from src.integrations.notion_sync import NotionCRM

# Map outreach stages to Notion Application stages
STAGE_MAPPING = {
    "Sent": "Applied",
    "Responded": "Applied",
}


class OutreachNotionSync:
    """Push outreach stages from OutreachORM to Notion Applications database."""

    def __init__(self, api_key: str, applications_db_id: str, session: Session):
        self.crm = NotionCRM(api_key=api_key, database_id=applications_db_id)
        self.session = session

    def _get_outreach_by_company(self) -> dict[str, list[OutreachORM]]:
        """Group outreach records by company name, excluding Not Started."""
        records = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.stage.notin_(["Not Started"]))
            .all()
        )

        grouped: dict[str, list[OutreachORM]] = {}
        for record in records:
            grouped.setdefault(record.company_name, []).append(record)
        return grouped

    def _get_best_stage(self, records: list[OutreachORM]) -> str:
        """Get the best (highest priority) stage for a company's outreach records.
        Priority: Responded > Sent
        """
        stages = {r.stage for r in records}
        if "Responded" in stages:
            return "Responded"
        if "Sent" in stages:
            return "Sent"
        return "Sent"  # fallback

    def _build_sequence_summary(self, records: list[OutreachORM]) -> str:
        """Build a sequence progress summary string for a company."""
        # Sort by creation
        sorted_records = sorted(records, key=lambda r: r.created_at or datetime.min)
        total = len(sorted_records)
        sent_count = sum(1 for r in sorted_records if r.stage in ("Sent", "Responded"))

        parts = []
        for r in sorted_records:
            if r.stage in ("Sent", "Responded"):
                step = r.sequence_step or "unknown"
                date = r.sent_at.strftime("%Y-%m-%d") if r.sent_at else "pending"
                parts.append(f"{step} {r.stage.lower()} {date}")

        summary = f"Step {sent_count}/{total}: " + "; ".join(parts) if parts else f"0/{total} steps"
        return summary

    async def sync_all_outreach_stages(self, dry_run: bool = False) -> dict:
        """Sync outreach stages to Notion.

        For each company with outreach records (not "Not Started"):
        - Determine best stage (Responded > Sent)
        - Map to Notion stage via STAGE_MAPPING
        - Update Notion via NotionCRM.update_company_stage()

        Returns dict with synced, skipped, errors, stage_counts.
        """
        grouped = self._get_outreach_by_company()
        result = {
            "synced": 0,
            "skipped": 0,
            "errors": [],
            "stage_counts": {"Sent": 0, "Responded": 0},
        }

        for company_name, records in grouped.items():
            best_stage = self._get_best_stage(records)
            notion_stage = STAGE_MAPPING.get(best_stage, "Applied")
            result["stage_counts"][best_stage] = result["stage_counts"].get(best_stage, 0) + 1

            if dry_run:
                result["synced"] += 1
                continue

            try:
                page_id = await self.crm.update_company_stage(company_name, notion_stage)
                if page_id:
                    result["synced"] += 1
                else:
                    result["skipped"] += 1
                    logger.warning(f"Company not found in Notion: {company_name}")
            except Exception as e:
                result["errors"].append(f"{company_name}: {e}")
                logger.error(f"Notion sync failed for {company_name}: {e}")

        return result

    async def sync_sequence_progress(self, dry_run: bool = False) -> dict:
        """Sync sequence progress summaries to Notion Notes field.

        Returns dict with updated, skipped.
        """
        grouped = self._get_outreach_by_company()
        result = {"updated": 0, "skipped": 0}

        for company_name, records in grouped.items():
            summary = self._build_sequence_summary(records)

            if dry_run:
                result["updated"] += 1
                continue

            try:
                page_id = await self.crm.find_page_by_name(company_name)
                if page_id:
                    # Update Notes field with sequence progress
                    await self.crm._request(
                        "PATCH",
                        f"{NOTION_BASE}/pages/{page_id}",
                        json={
                            "properties": {
                                "Notes": {
                                    "rich_text": [{"text": {"content": summary}}]
                                }
                            }
                        },
                    )
                    result["updated"] += 1
                else:
                    result["skipped"] += 1
            except Exception as e:
                result["skipped"] += 1
                logger.error(f"Sequence sync failed for {company_name}: {e}")

        return result

    def generate_sync_report(self) -> dict:
        """Generate a sync status report.

        Returns dict with total_companies, stage_counts, companies.
        """
        grouped = self._get_outreach_by_company()
        stage_counts: dict[str, int] = {}

        for company_name, records in grouped.items():
            best = self._get_best_stage(records)
            stage_counts[best] = stage_counts.get(best, 0) + 1

        return {
            "total_companies": len(grouped),
            "stage_counts": stage_counts,
            "companies": list(grouped.keys()),
        }

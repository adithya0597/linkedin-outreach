"""Company data enrichment — parse text fields to fill structured data."""

from __future__ import annotations

import re

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM

# Regex patterns for extracting structured data from text
LOCATION_PATTERNS = [
    re.compile(r"(?:based in|headquartered in|hq:?\s*)([\w\s]+,\s*[A-Z]{2})", re.IGNORECASE),
    re.compile(r"(?:located in|offices? in)\s+([\w\s]+,\s*[A-Z]{2})", re.IGNORECASE),
]

EMPLOYEE_PATTERNS = [
    re.compile(r"(\d[\d,]*)\s*(?:\+\s*)?employees?", re.IGNORECASE),
    re.compile(r"team\s+of\s+(\d[\d,]*)", re.IGNORECASE),
    re.compile(r"(\d[\d,]*)\s*(?:\+\s*)?people", re.IGNORECASE),
]

FUNDING_PATTERNS = [
    re.compile(r"(Series\s+[A-F])", re.IGNORECASE),
    re.compile(r"(Pre-Seed|Seed)\s*(?:round|stage|funding)?", re.IGNORECASE),
]

# Fields to check for completeness (9 fields)
COMPLETENESS_FIELDS = [
    "description", "hq_location", "employees", "funding_stage",
    "h1b_status", "role", "hiring_manager", "salary_range", "website",
]


class CompanyEnricher:
    """Parse existing text fields to fill missing structured fields."""

    def __init__(self, session: Session):
        self.session = session

    def _get_text_corpus(self, company: CompanyORM) -> str:
        """Combine all text fields into a searchable corpus."""
        parts = [
            company.description or "",
            company.notes or "",
            company.ai_product_description or "",
            company.why_fit or "",
            company.validation_notes or "",
        ]
        return " ".join(parts)

    def _extract_location(self, text: str) -> str | None:
        """Extract location from text using regex patterns."""
        for pattern in LOCATION_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return None

    def _extract_employees(self, text: str) -> int | None:
        """Extract employee count from text."""
        for pattern in EMPLOYEE_PATTERNS:
            match = pattern.search(text)
            if match:
                count_str = match.group(1).replace(",", "")
                try:
                    return int(count_str)
                except ValueError:
                    continue
        return None

    def _extract_funding(self, text: str) -> str | None:
        """Extract funding stage from text."""
        for pattern in FUNDING_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return None

    def enrich_from_description(self, company: CompanyORM) -> dict:
        """Parse description/notes for location, employee count, funding stage.

        Only fills empty/default fields. Returns dict of changes made.
        """
        text = self._get_text_corpus(company)
        if not text.strip():
            return {}

        changes = {}

        # Location
        if not company.hq_location or company.hq_location == "":
            location = self._extract_location(text)
            if location:
                company.hq_location = location
                changes["hq_location"] = location

        # Employees
        if company.employees is None or company.employees == 0:
            employees = self._extract_employees(text)
            if employees:
                company.employees = employees
                changes["employees"] = employees

        # Funding stage
        if not company.funding_stage or company.funding_stage in ("Unknown", ""):
            funding = self._extract_funding(text)
            if funding:
                company.funding_stage = funding
                changes["funding_stage"] = funding

        if changes:
            self.session.flush()
            logger.info(f"Enriched {company.name}: {changes}")

        return changes

    def _calculate_completeness(self, company: CompanyORM) -> float:
        """Calculate data completeness percentage for a company (0-100)."""
        filled = 0
        for field in COMPLETENESS_FIELDS:
            value = getattr(company, field, None)
            if value is not None and value != "" and value != 0 and str(value) != "Unknown":
                filled += 1
        return round(filled / len(COMPLETENESS_FIELDS) * 100, 1)

    def compute_all_completeness(self) -> dict:
        """Recalculate data_completeness for all companies.

        Returns dict with updated count and avg_completeness.
        """
        companies = self.session.query(CompanyORM).all()
        total_completeness = 0.0
        updated = 0

        for company in companies:
            new_completeness = self._calculate_completeness(company)
            company.data_completeness = new_completeness
            total_completeness += new_completeness
            updated += 1

        self.session.commit()
        avg = round(total_completeness / updated, 1) if updated > 0 else 0

        logger.info(f"Updated completeness for {updated} companies (avg: {avg}%)")
        return {"updated": updated, "avg_completeness": avg}

    def get_skeleton_records(self, threshold: float = 50) -> list[CompanyORM]:
        """Query companies below completeness threshold, not disqualified."""
        return (
            self.session.query(CompanyORM)
            .filter(
                CompanyORM.data_completeness < threshold,
                CompanyORM.is_disqualified == False,  # noqa: E712
            )
            .order_by(CompanyORM.data_completeness)
            .all()
        )

    def batch_enrich(self, threshold: float = 50) -> dict:
        """Enrich all skeleton records.

        Returns dict with enriched, skipped, errors, fields_filled.
        """
        skeletons = self.get_skeleton_records(threshold)
        result = {
            "enriched": 0,
            "skipped": 0,
            "errors": [],
            "fields_filled": {"hq_location": 0, "employees": 0, "funding_stage": 0},
        }

        for company in skeletons:
            try:
                changes = self.enrich_from_description(company)
                if changes:
                    result["enriched"] += 1
                    for field in changes:
                        if field in result["fields_filled"]:
                            result["fields_filled"][field] += 1
                else:
                    result["skipped"] += 1
            except Exception as e:
                result["errors"].append(f"{company.name}: {e}")
                logger.error(f"Enrichment failed for {company.name}: {e}")

        # Recalculate completeness for all enriched
        self.compute_all_completeness()
        self.session.commit()

        logger.info(
            f"Batch enrichment: {result['enriched']} enriched, "
            f"{result['skipped']} skipped, {len(result['errors'])} errors"
        )
        return result

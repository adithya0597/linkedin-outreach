"""Deterministic company validator — PASS/FAIL against target criteria."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.config.enums import (
    FundingStage,
    H1BStatus,
    PortalTier,
    SourcePortal,
    ValidationResult,
)
from src.db.database import get_engine, get_session
from src.db.orm import CompanyORM


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    evidence: str


@dataclass
class ValidationReport:
    company_name: str
    result: ValidationResult
    checks: list[ValidationCheck] = field(default_factory=list)
    notes: str = ""

    def __str__(self) -> str:
        icon = "✅" if self.result == ValidationResult.PASS else "❌"
        if self.result == ValidationResult.BORDERLINE:
            icon = "⚠️"

        lines = [f"\n{icon} {self.company_name}: {self.result.value}\n"]
        for check in self.checks:
            status = "✅" if check.passed else "❌"
            lines.append(f"  {status} {check.name}: {check.evidence}")
        if self.notes:
            lines.append(f"\n  Notes: {self.notes}")
        return "\n".join(lines)


class CompanyValidator:
    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = str(Path(__file__).parent.parent.parent / "config" / "criteria.yaml")
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

    def validate(self, company: CompanyORM) -> ValidationReport:
        """Run all 6 validation checks against a company record."""
        checks: list[ValidationCheck] = []

        # 1. Employee count
        if company.employees:
            max_emp = self.config["primary_criteria"]["max_employees"]
            passed = company.employees < max_emp
            checks.append(ValidationCheck(
                "Employees < 1,000",
                passed,
                f"~{company.employees} employees ({company.employees_range})",
            ))
        else:
            checks.append(ValidationCheck(
                "Employees < 1,000",
                True,  # No data = benefit of doubt
                f"No data ({company.employees_range or 'unknown'})",
            ))

        # 2. Funding stage
        funding = company.funding_stage
        valid_stages = self.config["primary_criteria"]["valid_funding_stages"]
        funding_passed = funding in valid_stages
        checks.append(ValidationCheck(
            "Seed–Series C",
            funding_passed,
            f"{funding} — {company.funding_amount}",
        ))

        # 3. AI-native
        checks.append(ValidationCheck(
            "AI-Native Product",
            company.is_ai_native,
            company.ai_product_description or company.description or "Marked as AI-native",
        ))

        # 4. US HQ
        hq = company.hq_location.lower() if company.hq_location else ""
        us_indicators = [
            "ca", "ny", "tx", "wa", "usa", "united states", "san francisco",
            "new york", "seattle", "austin", "remote", "palo alto", "redwood",
            "mountain view", "los angeles", "boston", "chicago", "denver",
            "phoenix", "irving", "dallas", "sf", "nyc", "alameda",
        ]
        us_passed = any(ind in hq for ind in us_indicators) or not hq
        checks.append(ValidationCheck(
            "US HQ",
            us_passed,
            company.hq_location or "Unknown — benefit of doubt",
        ))

        # 5. H1B Sponsorship (tiered)
        portal = company.source_portal
        source_portal_enum = None
        for sp in SourcePortal:
            if sp.value == portal:
                source_portal_enum = sp
                break

        if source_portal_enum and source_portal_enum.tier == PortalTier.TIER_3:
            checks.append(ValidationCheck(
                "H1B Sponsorship",
                True,
                f"N/A — Tier 3 portal ({portal}), auto-pass",
            ))
        else:
            h1b = company.h1b_status
            if h1b == H1BStatus.EXPLICIT_NO.value:
                checks.append(ValidationCheck(
                    "H1B Sponsorship",
                    False,
                    f"❌ Explicit No — {company.h1b_details}",
                ))
            else:
                checks.append(ValidationCheck(
                    "H1B Sponsorship",
                    True,
                    f"{h1b} — {company.h1b_details or 'No data = still include'}",
                ))

        # 6. Not disqualified
        disqualified_names = [n.lower() for n in self.config["disqualifiers"]["specific_companies"]]
        is_dq = company.name.lower() in disqualified_names
        if not is_dq and company.is_disqualified:
            is_dq = True
        checks.append(ValidationCheck(
            "Not Disqualified",
            not is_dq,
            company.disqualification_reason or "No disqualifiers found",
        ))

        # Determine overall result
        all_passed = all(c.passed for c in checks)
        funding_failed = not checks[1].passed  # Index 1 = funding check

        if all_passed:
            result = ValidationResult.PASS
        elif funding_failed and company.name in ("Cursor",):
            result = ValidationResult.BORDERLINE
        else:
            result = ValidationResult.FAIL

        return ValidationReport(
            company_name=company.name,
            result=result,
            checks=checks,
        )

    def validate_by_name(self, name: str, db_path: str = "data/outreach.db") -> str:
        """Look up company by name and validate."""
        engine = get_engine(db_path)
        session = get_session(engine)
        company = session.query(CompanyORM).filter(
            CompanyORM.name.ilike(f"%{name}%")
        ).first()
        session.close()

        if not company:
            return f"❌ Company '{name}' not found in database. Run `outreach seed` first."

        report = self.validate(company)
        return str(report)

    def batch_validate(self, db_path: str = "data/outreach.db") -> list[ValidationReport]:
        """Validate all companies in the database."""
        engine = get_engine(db_path)
        session = get_session(engine)
        companies = session.query(CompanyORM).all()
        reports = [self.validate(c) for c in companies]
        session.close()
        return reports

"""Data quality gates — check completeness, duplicates, criteria violations, score anomalies."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session
from thefuzz import fuzz

from src.db.orm import CompanyORM


class QualityAuditor:
    def __init__(self, session: Session):
        self.session = session

    def check_completeness(self) -> list[str]:
        """Find skeleton records with low data completeness."""
        issues = []
        companies = self.session.query(CompanyORM).filter(
            CompanyORM.data_completeness < 40
        ).all()
        for c in companies:
            issues.append(f"SKELETON: {c.name} — {c.data_completeness}% complete")
        return issues

    def check_duplicates(self) -> list[str]:
        """Find potential duplicate companies using fuzzy matching."""
        issues = []
        companies = self.session.query(CompanyORM.id, CompanyORM.name).all()
        names = [(c.id, c.name) for c in companies]

        seen = set()
        for i, (id1, name1) in enumerate(names):
            for id2, name2 in names[i + 1:]:
                ratio = fuzz.ratio(name1.lower(), name2.lower())
                if ratio > 85 and (id1, id2) not in seen:
                    issues.append(
                        f"DUPLICATE: '{name1}' (#{id1}) ≈ '{name2}' (#{id2}) — {ratio}% match"
                    )
                    seen.add((id1, id2))
        return issues

    def check_criteria_violations(self) -> list[str]:
        """Find companies that violate stated target criteria."""
        issues = []
        companies = self.session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).all()

        invalid_stages = {"Series D", "Series E", "Series F", "Public"}

        for c in companies:
            # Funding stage violations
            if c.funding_stage in invalid_stages:
                issues.append(
                    f"CRITERIA: {c.name} — {c.funding_stage} {c.funding_amount} "
                    f"exceeds Seed-Series C criteria"
                )

            # Employee count violations
            if c.employees and c.employees >= 1000:
                issues.append(
                    f"CRITERIA: {c.name} — {c.employees} employees exceeds <1000 limit"
                )

            # H1B explicit no
            if c.h1b_status == "Explicit No":
                issues.append(
                    f"CRITERIA: {c.name} — H1B explicitly denied: {c.h1b_details}"
                )

        return issues

    def check_score_anomalies(self) -> list[str]:
        """Find companies with suspicious fit scores."""
        issues = []
        companies = self.session.query(CompanyORM).filter(
            CompanyORM.fit_score.isnot(None)
        ).all()

        # Check for identical scores (cookie-cutter)
        score_groups: dict[float, list[str]] = {}
        for c in companies:
            if c.fit_score is not None:
                score_groups.setdefault(c.fit_score, []).append(c.name)

        for score, names in score_groups.items():
            if len(names) >= 3:
                issues.append(
                    f"ANOMALY: {len(names)} companies share identical score {score}: "
                    f"{', '.join(names[:5])}"
                )

        return issues

    def check_stale_data(self, max_days: int = 30) -> list[str]:
        """Find records that haven't been updated recently."""
        from datetime import datetime, timedelta

        from src.db.orm import JobPostingORM

        cutoff = datetime.now() - timedelta(days=max_days)
        issues = []
        stale = self.session.query(CompanyORM).filter(
            CompanyORM.updated_at < cutoff
        ).count()
        if stale > 0:
            issues.append(f"STALE: {stale} companies not updated in {max_days} days")

        stale_postings = self.session.query(JobPostingORM).filter(
            JobPostingORM.discovered_date < cutoff,
            JobPostingORM.is_active == True,  # noqa: E712
        ).count()
        if stale_postings > 0:
            issues.append(f"STALE: {stale_postings} active job postings older than {max_days} days")

        return issues

    def archive_stale_postings(self, max_days: int = 30) -> int:
        """Mark stale job postings as inactive. Returns count archived."""
        from datetime import datetime, timedelta

        from src.db.orm import JobPostingORM

        cutoff = datetime.now() - timedelta(days=max_days)
        stale = self.session.query(JobPostingORM).filter(
            JobPostingORM.discovered_date < cutoff,
            JobPostingORM.is_active == True,  # noqa: E712
        ).all()

        count = 0
        for posting in stale:
            posting.is_active = False
            count += 1

        self.session.commit()
        return count

    def full_audit(self) -> str:
        """Run all quality checks and return formatted report."""
        total = self.session.query(func.count(CompanyORM.id)).scalar()

        completeness = self.check_completeness()
        duplicates = self.check_duplicates()
        criteria = self.check_criteria_violations()
        anomalies = self.check_score_anomalies()
        stale = self.check_stale_data()

        all_issues = completeness + duplicates + criteria + anomalies + stale

        lines = [
            "\n=== DATA QUALITY AUDIT ===",
            f"Total companies: {total}",
            f"Total issues: {len(all_issues)}",
            "",
        ]

        sections = [
            ("Completeness", completeness),
            ("Duplicates", duplicates),
            ("Criteria Violations", criteria),
            ("Score Anomalies", anomalies),
            ("Stale Data", stale),
        ]

        for name, issues in sections:
            lines.append(f"--- {name} ({len(issues)} issues) ---")
            for issue in issues:
                lines.append(f"  {issue}")
            if not issues:
                lines.append("  ✅ No issues found")
            lines.append("")

        return "\n".join(lines)

    def enforce_gate(self, threshold: int = 0) -> tuple[bool, str]:
        """Returns (passed, report). Fails if critical issues exceed threshold."""
        criteria = self.check_criteria_violations()
        report = self.full_audit()
        passed = len(criteria) <= threshold
        return passed, report

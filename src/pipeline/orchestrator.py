"""Pipeline orchestrator — chains scan → validate → score → h1b → dedup → sync → notify."""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM
from src.validators.company_validator import CompanyValidator, ValidationResult
from src.validators.scoring_engine import FitScoringEngine


class Pipeline:
    def __init__(self, session: Session):
        self.session = session
        self.validator = CompanyValidator()
        self.scorer = FitScoringEngine()

    def validate_all(self) -> dict:
        """Run validation on all non-disqualified companies."""
        companies = self.session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).all()

        results = {"passed": 0, "failed": 0, "borderline": 0}
        for company in companies:
            report = self.validator.validate(company)
            company.validation_result = report.result.value
            company.validation_notes = str(report)

            if report.result == ValidationResult.PASS:
                results["passed"] += 1
            elif report.result == ValidationResult.FAIL:
                results["failed"] += 1
                company.is_disqualified = True
                company.disqualification_reason = "; ".join(
                    c.evidence for c in report.checks if not c.passed
                )
            else:
                results["borderline"] += 1
                company.needs_review = True

            company.updated_at = datetime.now()

        self.session.commit()
        logger.info(
            f"Validation complete: {results['passed']} passed, "
            f"{results['failed']} failed, {results['borderline']} borderline"
        )
        return results

    def score_all(self, include_semantic: bool = False) -> dict:
        """Score all validated (non-disqualified) companies."""
        companies = self.session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).all()

        scored = 0
        for company in companies:
            breakdown = self.scorer.score(company, include_semantic=include_semantic)
            company.fit_score = round(breakdown.total, 2)
            company.score_h1b = breakdown.h1b_score
            company.score_criteria = breakdown.criteria_score
            company.score_tech_overlap = breakdown.tech_overlap_score
            company.score_salary = breakdown.salary_score
            company.score_profile_jd = breakdown.profile_jd_similarity
            company.score_domain_company = breakdown.domain_company_similarity
            company.score_domain_match = breakdown.domain_match_bonus
            company.updated_at = datetime.now()
            scored += 1

        self.session.commit()
        logger.info(f"Scored {scored} companies")

        # Return top 10
        top = self.session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).order_by(CompanyORM.fit_score.desc()).limit(10).all()

        return {
            "scored": scored,
            "top_10": [(c.name, c.fit_score, c.tier) for c in top],
        }

    def verify_h1b(self) -> dict:
        """Run H1B verification on unverified, non-disqualified companies."""
        import asyncio

        from src.validators.h1b_verifier import H1BVerifier

        companies = self.session.query(CompanyORM).filter(
            CompanyORM.h1b_status.in_(["Unknown", "", None]),
            CompanyORM.is_disqualified == False,  # noqa: E712
        ).all()

        if not companies:
            logger.info("No companies need H1B verification")
            return {"verified": 0, "confirmed": 0, "explicit_no": 0, "unknown": 0}

        verifier = H1BVerifier()
        results = asyncio.run(verifier.batch_verify(companies, session=self.session))

        counts = {"verified": len(results), "confirmed": 0, "explicit_no": 0, "unknown": 0}
        for r in results:
            if r.status.value == "Confirmed":
                counts["confirmed"] += 1
            elif r.status.value == "Explicit No":
                counts["explicit_no"] += 1
            else:
                counts["unknown"] += 1

        logger.info(
            f"H1B verified {counts['verified']}: "
            f"{counts['confirmed']} confirmed, {counts['explicit_no']} no, {counts['unknown']} unknown"
        )
        return counts

    async def scan_all(
        self,
        portals: list[str] | None = None,
        keywords: list[str] | None = None,
        days: int = 30,
    ) -> dict:
        """Run scraper search across portals, persist results."""
        import time

        from src.scrapers.persistence import persist_scan_results
        from src.scrapers.registry import build_default_registry

        registry = build_default_registry()
        if portals:
            scrapers = []
            for p in portals:
                try:
                    scrapers.append(registry.get_scraper(p))
                except KeyError:
                    logger.warning(f"Unknown portal '{p}', skipping")
        else:
            scrapers = registry.get_all_scrapers()

        kws = keywords or ["AI Engineer", "ML Engineer"]

        total_found = 0
        total_new = 0
        total_new_companies = 0
        for s in scrapers:
            if not s.is_healthy():
                continue
            start = time.time()
            try:
                postings = await s.search(kws, days=days)
                found, new, new_co = persist_scan_results(
                    self.session, s.name, postings, duration=time.time() - start
                )
                total_found += found
                total_new += new
                total_new_companies += new_co
            except Exception as e:
                logger.error(f"Scan failed for {s.name}: {e}")

        # Check health after scan
        from src.pipeline.health_monitor import HealthMonitor
        monitor = HealthMonitor(self.session)
        alerts = monitor.get_alerts()
        for alert in alerts:
            logger.warning(
                f"Portal health alert: {alert.portal} — "
                f"{alert.consecutive_failures} consecutive failures"
            )

        return {
            "total_found": total_found,
            "total_new": total_new,
            "total_new_companies": total_new_companies,
            "portals_scanned": len(scrapers),
        }

    async def scan_smart(
        self,
        keywords: list[str] | None = None,
        enrich_h1b: bool = True,
    ) -> dict:
        """Run smart scan with portal scorer filtering and H1B enrichment."""
        from src.pipeline.smart_scan import SmartScanOrchestrator

        orchestrator = SmartScanOrchestrator(self.session)
        return await orchestrator.run_smart_scan(
            keywords=keywords,
            enrich_h1b=enrich_h1b,
            scan_type="full",
        )

    def _notion_sync(self) -> dict | None:
        """Sync local DB with Notion after pipeline run."""
        import asyncio
        import os

        from src.integrations.notion_bidirectional import ConflictStrategy, NotionBidirectionalSync

        api_key = os.environ.get("NOTION_API_KEY", "")
        db_id = os.environ.get("NOTION_DB_ID", "") or os.environ.get(
            "NOTION_DATABASE_ID", ""
        )
        if not api_key or not db_id:
            return None
        syncer = NotionBidirectionalSync(api_key, db_id, self.session)
        return asyncio.run(
            syncer.full_sync(strategy=ConflictStrategy.NEWEST_WINS)
        )

    def run(
        self,
        validate: bool = True,
        score: bool = True,
        verify_h1b: bool = False,
        include_semantic: bool = False,
        scan: bool = False,
        smart: bool = False,
        scan_portals: list[str] | None = None,
    ) -> dict:
        """Run the full pipeline: scan → validate → h1b → score → sync."""
        import asyncio

        results = {}

        if scan:
            if smart:
                results["scan"] = asyncio.run(self.scan_smart())
            else:
                results["scan"] = asyncio.run(self.scan_all(portals=scan_portals))

        if validate:
            results["validation"] = self.validate_all()

        if verify_h1b:
            results["h1b"] = self.verify_h1b()

        if score:
            results["scoring"] = self.score_all(include_semantic=include_semantic)

        try:
            results["notion_sync"] = self._notion_sync()
        except Exception as e:
            logger.error(f"Notion sync failed: {e}")
            results["notion_sync"] = {"error": str(e)}

        logger.info("Pipeline run complete")
        return results

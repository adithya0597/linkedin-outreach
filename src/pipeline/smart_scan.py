"""Smart scan orchestrator — integrates PortalScorer for intelligent portal selection."""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger
from sqlalchemy.orm import Session

from src.db.h1b_lookup import apply_known_statuses
from src.validators.portal_scorer import PortalScorer


class SmartScanOrchestrator:
    """Orchestrates scans with portal scoring for automatic skip/promote decisions."""

    def __init__(self, session: Session, config_path: str | None = None):
        self.session = session
        self.scorer = PortalScorer(session)

        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "schedule.yaml"
            )
        with open(config_path) as f:
            self.schedule_config = yaml.safe_load(f)

    def get_smart_portal_list(self, base_portals: list[str] | None = None) -> list[str]:
        """Filter portals by scorer — exclude demoted portals.

        Args:
            base_portals: Optional list of portals to filter. If None, uses all scored portals.

        Returns:
            List of portal names with demoted ones excluded.
        """
        scores = self.scorer.score_all()
        demoted = {s.portal for s in scores if s.recommendation == "demote"}

        if base_portals:
            filtered = [p for p in base_portals if p not in demoted]
        else:
            # All known portals minus demoted
            all_portals = {s.portal for s in scores}
            filtered = sorted(all_portals - demoted)

        if demoted:
            logger.info(f"Smart scan: skipping demoted portals: {sorted(demoted)}")

        return filtered

    def get_rescan_portals(self) -> list[str]:
        """Get portals for afternoon rescan — promoted + configured afternoon list.

        Returns:
            Combined list of promoted portals and configured afternoon_rescan portals.
        """
        scores = self.scorer.score_all()
        promoted = {s.portal for s in scores if s.recommendation == "promote"}

        # Get configured afternoon rescan list
        afternoon_config = (
            self.schedule_config
            .get("schedules", {})
            .get("afternoon_rescan", {})
            .get("portals", [])
        )

        # Combine: promoted + configured afternoon
        combined = set(afternoon_config) | promoted
        return sorted(combined)

    async def run_smart_scan(
        self,
        portals: list[str] | None = None,
        keywords: list[str] | None = None,
        enrich_h1b: bool = True,
        scan_type: str = "full",
    ) -> dict:
        """Run a scan with smart portal filtering and optional H1B enrichment.

        Args:
            portals: Specific portals to scan (filtered through scorer).
            keywords: Search keywords. Defaults to Pipeline defaults.
            enrich_h1b: Whether to run H1B enrichment post-scan.
            scan_type: "full" or "rescan".

        Returns:
            Dict with scan_results, skipped_portals, h1b_enriched, portal_scores.
        """
        from src.pipeline.orchestrator import Pipeline

        # Get smart portal list
        smart_portals = self.get_rescan_portals() if scan_type == "rescan" else self.get_smart_portal_list(portals)

        # Calculate skipped
        all_scores = self.scorer.score_all()
        skipped = [s.portal for s in all_scores if s.recommendation == "demote"]

        # Run the scan via Pipeline
        pipeline = Pipeline(self.session)
        scan_results = await pipeline.scan_all(
            portals=smart_portals if smart_portals else None,
            keywords=keywords,
        )

        # Post-scan H1B enrichment
        h1b_enriched = 0
        if enrich_h1b:
            h1b_enriched = apply_known_statuses(self.session)
            if h1b_enriched > 0:
                logger.info(f"H1B enrichment: updated {h1b_enriched} companies")

        # Build portal scores summary
        portal_scores = {
            s.portal: {
                "total": s.total,
                "recommendation": s.recommendation,
            }
            for s in all_scores
        }

        return {
            "scan_results": scan_results,
            "skipped_portals": skipped,
            "h1b_enriched": h1b_enriched,
            "portal_scores": portal_scores,
        }

    def get_scan_report(self) -> dict:
        """Generate a summary report with portal scores and recommendations.

        Returns:
            Dict with scores list and summary counts.
        """
        scores = self.scorer.score_all()
        return {
            "scores": [
                {
                    "portal": s.portal,
                    "velocity": s.velocity_score,
                    "afternoon_delta": s.afternoon_delta_score,
                    "conversion": s.conversion_score,
                    "total": s.total,
                    "recommendation": s.recommendation,
                }
                for s in scores
            ],
            "summary": {
                "total_portals": len(scores),
                "promoted": sum(1 for s in scores if s.recommendation == "promote"),
                "demoted": sum(1 for s in scores if s.recommendation == "demote"),
                "hold": sum(1 for s in scores if s.recommendation == "hold"),
            },
        }

"""Daily orchestrator — runs full enrichment-score-queue-followup-sync pipeline."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session


class DailyOrchestrator:
    """Orchestrate the complete daily pipeline: scan -> enrich -> score -> queue -> followup -> sync."""

    def __init__(self, session: Session, config_path: str | None = None):
        self.session = session
        self.config_path = config_path
        self._results: dict = {}

    def _run_scan(self) -> dict:
        """Stage 0: Run smart portal scan."""
        from src.pipeline.smart_scan import SmartScanOrchestrator

        orchestrator = SmartScanOrchestrator(self.session)
        portals = orchestrator.get_smart_portal_list()
        result = asyncio.run(orchestrator.run_smart_scan(
            portals=portals,
            scan_type="full",
        ))
        return result

    def _run_enrichment(self) -> dict:
        """Stage 1: Enrich skeleton company records."""
        from src.pipeline.enrichment import CompanyEnricher

        enricher = CompanyEnricher(self.session)
        return enricher.batch_enrich()

    def _run_scoring(self) -> dict:
        """Stage 2: Score all non-disqualified companies."""
        from src.pipeline.orchestrator import Pipeline

        pipeline = Pipeline(self.session)
        return pipeline.score_all()

    def _run_send_queue(self) -> list[dict]:
        """Stage 3: Generate prioritized daily send queue."""
        from src.outreach.send_queue import SendQueueManager

        manager = SendQueueManager(self.session)
        return manager.generate_daily_queue()

    def _run_followup_check(self) -> dict:
        """Stage 4: Check for overdue and upcoming follow-ups."""
        from src.outreach.followup_manager import FollowUpManager

        manager = FollowUpManager(self.session)
        return manager.generate_daily_alert()

    def _run_sync(self, dry_run: bool = False) -> dict:
        """Stage 5: Sync outreach stages to Notion."""
        import os

        from src.integrations.outreach_sync import OutreachNotionSync

        api_key = os.environ.get("NOTION_API_KEY", "")
        db_id = os.environ.get("NOTION_DB_ID", "")
        syncer = OutreachNotionSync(api_key, db_id, self.session)
        return asyncio.run(syncer.sync_all_outreach_stages(dry_run=dry_run))

    def run_full_day(
        self,
        dry_run: bool = False,
        skip_scan: bool = False,
        skip_enrich: bool = False,
    ) -> dict:
        """Execute all pipeline stages in order.

        Each stage is wrapped in try/except so a failure in one doesn't block the rest.

        Returns dict with keys: scan, enrichment, scoring, send_queue, followups, sync,
        total_time, timestamp.
        """
        start = time.time()
        results: dict = {
            "scan": None,
            "enrichment": None,
            "scoring": None,
            "send_queue": None,
            "followups": None,
            "sync": None,
            "total_time": 0.0,
            "timestamp": datetime.now().isoformat(),
        }

        # Stage 1: Scan
        if not skip_scan:
            try:
                logger.info("Stage 1/6: Running portal scan...")
                results["scan"] = self._run_scan()
            except Exception as e:
                logger.error(f"Scan stage failed: {e}")
                results["scan"] = {"error": str(e)}
        else:
            logger.info("Stage 1/6: Scan skipped")
            results["scan"] = {"skipped": True}

        # Stage 2: Enrichment
        if not skip_enrich:
            try:
                logger.info("Stage 2/6: Running enrichment...")
                results["enrichment"] = self._run_enrichment()
            except Exception as e:
                logger.error(f"Enrichment stage failed: {e}")
                results["enrichment"] = {"error": str(e)}
        else:
            logger.info("Stage 2/6: Enrichment skipped")
            results["enrichment"] = {"skipped": True}

        # Stage 3: Scoring
        try:
            logger.info("Stage 3/6: Running scoring...")
            results["scoring"] = self._run_scoring()
        except Exception as e:
            logger.error(f"Scoring stage failed: {e}")
            results["scoring"] = {"error": str(e)}

        # Stage 4: Send queue
        try:
            logger.info("Stage 4/6: Generating send queue...")
            results["send_queue"] = self._run_send_queue()
        except Exception as e:
            logger.error(f"Send queue stage failed: {e}")
            results["send_queue"] = {"error": str(e)}

        # Stage 5: Follow-up check
        try:
            logger.info("Stage 5/6: Checking follow-ups...")
            results["followups"] = self._run_followup_check()
        except Exception as e:
            logger.error(f"Follow-up check failed: {e}")
            results["followups"] = {"error": str(e)}

        # Stage 6: Notion sync
        try:
            logger.info("Stage 6/6: Syncing to Notion...")
            results["sync"] = self._run_sync(dry_run=dry_run)
        except Exception as e:
            logger.error(f"Notion sync failed: {e}")
            results["sync"] = {"error": str(e)}

        results["total_time"] = round(time.time() - start, 3)
        self._results = results

        logger.info(f"Daily pipeline complete in {results['total_time']}s")
        return results

    def generate_daily_summary(self) -> str:
        """Generate a markdown summary of the most recent run results."""
        r = self._results
        if not r:
            return "No pipeline run results available."

        lines = [
            f"# Daily Pipeline Summary",
            f"**Timestamp:** {r.get('timestamp', 'N/A')}",
            f"**Total Time:** {r.get('total_time', 0)}s",
            "",
        ]

        # Scan
        lines.append("## Scan")
        scan = r.get("scan")
        if scan and isinstance(scan, dict):
            if scan.get("skipped") is True:
                lines.append("Skipped.")
            elif scan.get("error"):
                lines.append(f"Error: {scan['error']}")
            else:
                scan_results = scan.get("scan_results", {})
                lines.append(
                    f"- Found: {scan_results.get('total_found', 0)}, "
                    f"New: {scan_results.get('total_new', 0)}"
                )
        lines.append("")

        # Enrichment
        lines.append("## Enrichment")
        enrich = r.get("enrichment")
        if enrich and isinstance(enrich, dict):
            if enrich.get("skipped") is True:
                lines.append("Skipped.")
            elif enrich.get("error"):
                lines.append(f"Error: {enrich['error']}")
            else:
                lines.append(
                    f"- Enriched: {enrich.get('enriched', 0)}, "
                    f"Skipped: {enrich.get('skipped', 0)}, "
                    f"Errors: {len(enrich.get('errors', []))}"
                )
        lines.append("")

        # Scoring
        lines.append("## Scoring")
        scoring = r.get("scoring")
        if scoring and isinstance(scoring, dict):
            if scoring.get("error"):
                lines.append(f"Error: {scoring['error']}")
            else:
                lines.append(f"- Scored: {scoring.get('scored', 0)} companies")
                top = scoring.get("top_10", [])
                if top:
                    lines.append("- Top 5:")
                    for name, score, tier in top[:5]:
                        lines.append(f"  - {name}: {score} ({tier})")
        lines.append("")

        # Send Queue
        lines.append("## Send Queue")
        queue = r.get("send_queue")
        if isinstance(queue, list):
            lines.append(f"- {len(queue)} messages ready to send")
        elif isinstance(queue, dict) and queue.get("error"):
            lines.append(f"Error: {queue['error']}")
        lines.append("")

        # Follow-ups
        lines.append("## Follow-ups")
        followups = r.get("followups")
        if followups and isinstance(followups, dict):
            if followups.get("error"):
                lines.append(f"Error: {followups['error']}")
            else:
                lines.append(
                    f"- Overdue: {len(followups.get('overdue', []))}, "
                    f"Due today: {len(followups.get('due_today', []))}, "
                    f"Due this week: {len(followups.get('due_this_week', []))}"
                )
                lines.append(
                    f"- Active sequences: {followups.get('total_active_sequences', 0)}"
                )
        lines.append("")

        # Sync
        lines.append("## Notion Sync")
        sync = r.get("sync")
        if sync and isinstance(sync, dict):
            if sync.get("error"):
                lines.append(f"Error: {sync['error']}")
            else:
                lines.append(
                    f"- Synced: {sync.get('synced', 0)}, "
                    f"Skipped: {sync.get('skipped', 0)}, "
                    f"Errors: {len(sync.get('errors', []))}"
                )
        lines.append("")

        return "\n".join(lines)

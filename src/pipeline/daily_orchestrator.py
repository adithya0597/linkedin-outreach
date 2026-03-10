"""Daily orchestrator — runs full 8-stage pipeline with per-stage timing."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session


class DailyOrchestrator:
    """Orchestrate the complete daily pipeline.

    Stages: SCAN -> ENRICH -> H1B_VERIFY -> SCORE -> DRAFT -> SEND_QUEUE -> FOLLOWUP -> NOTION_SYNC
    """

    TOTAL_STAGES = 8

    def __init__(self, session: Session, config_path: str | None = None):
        self.session = session
        self.config_path = config_path
        self._results: dict = {}

    def _run_scan(self) -> dict:
        """Stage 1: Run smart portal scan."""
        from src.pipeline.smart_scan import SmartScanOrchestrator

        orchestrator = SmartScanOrchestrator(self.session)
        portals = orchestrator.get_smart_portal_list()
        result = asyncio.run(orchestrator.run_smart_scan(
            portals=portals,
            scan_type="full",
        ))
        return result

    def _run_enrichment(self) -> dict:
        """Stage 2: Enrich skeleton company records."""
        from src.pipeline.enrichment import CompanyEnricher

        enricher = CompanyEnricher(self.session)
        return enricher.batch_enrich()

    def _run_h1b_verify(self) -> dict:
        """Stage 3: Apply known H1B statuses to unverified companies.

        Uses the known H1B lookup table to update companies with h1b_status='Unknown'.
        This ensures scoring has H1B data (H1B score = 0-15 pts).
        """
        from src.db.h1b_lookup import apply_known_statuses

        updated = apply_known_statuses(self.session)
        return {"updated": updated}

    def _run_scoring(self) -> dict:
        """Stage 4: Score all non-disqualified companies."""
        from src.pipeline.orchestrator import Pipeline

        pipeline = Pipeline(self.session)
        return pipeline.score_all()

    def _run_drafts(self, score_threshold: float = 60.0) -> dict:
        """Stage 5: Auto-generate outreach drafts for high-scoring companies.

        Only drafts for companies with fit_score >= score_threshold.
        """
        from src.outreach.batch_engine import BatchOutreachEngine

        engine = BatchOutreachEngine(self.session)

        # draft_all already filters by is_disqualified=False and orders by fit_score desc.
        # We pass no tier filter — the score_threshold is applied here by limiting the query.
        from src.db.orm import CompanyORM

        qualifying_count = (
            self.session.query(CompanyORM)
            .filter(
                CompanyORM.is_disqualified == False,  # noqa: E712
                CompanyORM.fit_score >= score_threshold,
            )
            .count()
        )

        if qualifying_count == 0:
            return {"drafted": 0, "skipped": 0, "over_limit": 0, "errors": [], "qualifying": 0}

        # Use limit to only draft for qualifying companies (those above threshold).
        # BatchOutreachEngine.draft_all orders by fit_score desc, so we take top N.
        result = engine.draft_all(limit=qualifying_count)
        result["qualifying"] = qualifying_count
        return result

    def _run_send_queue(self) -> list[dict]:
        """Stage 6: Generate prioritized daily send queue."""
        from src.outreach.send_queue import SendQueueManager

        manager = SendQueueManager(self.session)
        return manager.generate_daily_queue()

    def _run_followup_check(self) -> dict:
        """Stage 7: Check for overdue and upcoming follow-ups."""
        from src.outreach.followup_manager import FollowUpManager

        manager = FollowUpManager(self.session)
        return manager.generate_daily_alert()

    def _run_sync(self, dry_run: bool = False) -> dict:
        """Stage 8: Full bidirectional Notion sync."""
        import os

        from src.integrations.notion_bidirectional import ConflictStrategy, NotionBidirectionalSync

        api_key = os.environ.get("NOTION_API_KEY", "")
        db_id = os.environ.get("NOTION_DB_ID", "") or os.environ.get(
            "NOTION_DATABASE_ID", ""
        )
        if not api_key or not db_id:
            logger.warning("Notion credentials not set, skipping sync")
            return {"skipped": True, "reason": "no credentials"}
        syncer = NotionBidirectionalSync(api_key, db_id, self.session)
        return asyncio.run(
            syncer.full_sync(strategy=ConflictStrategy.NEWEST_WINS, dry_run=dry_run)
        )

    @staticmethod
    def _time_stage(func, *args, **kwargs) -> tuple:
        """Run a callable and return (result, elapsed_seconds)."""
        t0 = time.time()
        result = func(*args, **kwargs)
        elapsed = round(time.time() - t0, 3)
        return result, elapsed

    def run_full_day(
        self,
        dry_run: bool = False,
        skip_scan: bool = False,
        skip_enrich: bool = False,
        skip_h1b: bool = False,
        skip_drafts: bool = False,
        draft_score_threshold: float = 60.0,
    ) -> dict:
        """Execute all 8 pipeline stages in order.

        Each stage is wrapped in try/except so a failure in one doesn't block the rest.

        Stages:
            1. SCAN         — Portal scan for new postings
            2. ENRICH       — Fill skeleton company records
            3. H1B_VERIFY   — Apply known H1B statuses before scoring
            4. SCORE        — Score all non-disqualified companies
            5. DRAFT        — Auto-generate outreach drafts for high scorers
            6. SEND_QUEUE   — Prioritized daily send queue
            7. FOLLOWUP     — Overdue and upcoming follow-up checks
            8. NOTION_SYNC  — Bidirectional Notion sync

        Returns dict with keys: scan, enrichment, h1b_verify, scoring, drafts,
        send_queue, followups, sync, stage_timings, total_time, timestamp.
        """
        start = time.time()
        n = self.TOTAL_STAGES
        results: dict = {
            "scan": None,
            "enrichment": None,
            "h1b_verify": None,
            "scoring": None,
            "drafts": None,
            "send_queue": None,
            "followups": None,
            "sync": None,
            "stage_timings": {},
            "total_time": 0.0,
            "timestamp": datetime.now().isoformat(),
        }

        # Stage 1: Scan
        if not skip_scan:
            try:
                logger.info(f"Stage 1/{n}: Running portal scan...")
                results["scan"], elapsed = self._time_stage(self._run_scan)
                results["stage_timings"]["scan"] = elapsed
            except Exception as e:
                logger.error(f"Scan stage failed: {e}")
                results["scan"] = {"error": str(e)}
        else:
            logger.info(f"Stage 1/{n}: Scan skipped")
            results["scan"] = {"skipped": True}

        # Stage 2: Enrichment
        if not skip_enrich:
            try:
                logger.info(f"Stage 2/{n}: Running enrichment...")
                results["enrichment"], elapsed = self._time_stage(self._run_enrichment)
                results["stage_timings"]["enrichment"] = elapsed
            except Exception as e:
                logger.error(f"Enrichment stage failed: {e}")
                results["enrichment"] = {"error": str(e)}
        else:
            logger.info(f"Stage 2/{n}: Enrichment skipped")
            results["enrichment"] = {"skipped": True}

        # Stage 3: H1B Verification
        if not skip_h1b:
            try:
                logger.info(f"Stage 3/{n}: Running H1B verification...")
                results["h1b_verify"], elapsed = self._time_stage(self._run_h1b_verify)
                results["stage_timings"]["h1b_verify"] = elapsed
            except Exception as e:
                logger.error(f"H1B verification failed: {e}")
                results["h1b_verify"] = {"error": str(e)}
        else:
            logger.info(f"Stage 3/{n}: H1B verification skipped")
            results["h1b_verify"] = {"skipped": True}

        # Stage 4: Scoring
        try:
            logger.info(f"Stage 4/{n}: Running scoring...")
            results["scoring"], elapsed = self._time_stage(self._run_scoring)
            results["stage_timings"]["scoring"] = elapsed
        except Exception as e:
            logger.error(f"Scoring stage failed: {e}")
            results["scoring"] = {"error": str(e)}

        # Stage 5: Drafts
        if not skip_drafts:
            try:
                logger.info(f"Stage 5/{n}: Generating outreach drafts...")
                results["drafts"], elapsed = self._time_stage(
                    self._run_drafts, draft_score_threshold
                )
                results["stage_timings"]["drafts"] = elapsed
            except Exception as e:
                logger.error(f"Draft generation failed: {e}")
                results["drafts"] = {"error": str(e)}
        else:
            logger.info(f"Stage 5/{n}: Drafts skipped")
            results["drafts"] = {"skipped": True}

        # Stage 6: Send queue
        try:
            logger.info(f"Stage 6/{n}: Generating send queue...")
            results["send_queue"], elapsed = self._time_stage(self._run_send_queue)
            results["stage_timings"]["send_queue"] = elapsed
        except Exception as e:
            logger.error(f"Send queue stage failed: {e}")
            results["send_queue"] = {"error": str(e)}

        # Stage 7: Follow-up check
        try:
            logger.info(f"Stage 7/{n}: Checking follow-ups...")
            results["followups"], elapsed = self._time_stage(self._run_followup_check)
            results["stage_timings"]["followups"] = elapsed
        except Exception as e:
            logger.error(f"Follow-up check failed: {e}")
            results["followups"] = {"error": str(e)}

        # Stage 8: Notion sync
        try:
            logger.info(f"Stage 8/{n}: Syncing to Notion...")
            results["sync"], elapsed = self._time_stage(self._run_sync, dry_run=dry_run)
            results["stage_timings"]["sync"] = elapsed
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

        timings = r.get("stage_timings", {})

        def _timing_str(stage_key: str) -> str:
            t = timings.get(stage_key)
            return f" ({t}s)" if t is not None else ""

        lines = [
            f"# Daily Pipeline Summary",
            f"**Timestamp:** {r.get('timestamp', 'N/A')}",
            f"**Total Time:** {r.get('total_time', 0)}s",
            "",
        ]

        # Scan
        lines.append(f"## Scan{_timing_str('scan')}")
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
        lines.append(f"## Enrichment{_timing_str('enrichment')}")
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

        # H1B Verification
        lines.append(f"## H1B Verification{_timing_str('h1b_verify')}")
        h1b = r.get("h1b_verify")
        if h1b and isinstance(h1b, dict):
            if h1b.get("skipped") is True:
                lines.append("Skipped.")
            elif h1b.get("error"):
                lines.append(f"Error: {h1b['error']}")
            else:
                lines.append(f"- Updated: {h1b.get('updated', 0)} companies")
        lines.append("")

        # Scoring
        lines.append(f"## Scoring{_timing_str('scoring')}")
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

        # Drafts
        lines.append(f"## Drafts{_timing_str('drafts')}")
        drafts = r.get("drafts")
        if drafts and isinstance(drafts, dict):
            if drafts.get("skipped") is True:
                lines.append("Skipped.")
            elif drafts.get("error"):
                lines.append(f"Error: {drafts['error']}")
            else:
                lines.append(
                    f"- Drafted: {drafts.get('drafted', 0)}, "
                    f"Over limit: {drafts.get('over_limit', 0)}, "
                    f"Errors: {len(drafts.get('errors', []))}"
                )
                qualifying = drafts.get("qualifying")
                if qualifying is not None:
                    lines.append(f"- Qualifying companies (score >= threshold): {qualifying}")
        lines.append("")

        # Send Queue
        lines.append(f"## Send Queue{_timing_str('send_queue')}")
        queue = r.get("send_queue")
        if isinstance(queue, list):
            lines.append(f"- {len(queue)} messages ready to send")
        elif isinstance(queue, dict) and queue.get("error"):
            lines.append(f"Error: {queue['error']}")
        lines.append("")

        # Follow-ups
        lines.append(f"## Follow-ups{_timing_str('followups')}")
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
        lines.append(f"## Notion Sync{_timing_str('sync')}")
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

        # Per-stage timing table
        if timings:
            lines.append("## Stage Timings")
            for stage, t in timings.items():
                lines.append(f"- {stage}: {t}s")
            lines.append("")

        return "\n".join(lines)

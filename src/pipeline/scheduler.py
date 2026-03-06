"""Scan scheduler — APScheduler-based job scheduling."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from loguru import logger


class ScanScheduler:
    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "schedule.yaml"
            )
        self._config_path = config_path
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self._config_mtime = os.path.getmtime(config_path)

    def _maybe_reload_config(self) -> bool:
        """Check config mtime, reload if changed. Called before each job."""
        try:
            current_mtime = os.path.getmtime(self._config_path)
            if current_mtime > self._config_mtime:
                with open(self._config_path) as f:
                    self.config = yaml.safe_load(f)
                self._config_mtime = current_mtime
                logger.info(f"Config reloaded from {self._config_path}")
                return True
            return False
        except (OSError, yaml.YAMLError) as e:
            logger.warning(f"Config reload failed: {e}")
            return False

    def get_full_scan_portals(self) -> list[str]:
        """Return list of all portal keys for full morning scan."""
        portals_config_path = str(
            Path(__file__).parent.parent.parent / "config" / "portals.yaml"
        )
        with open(portals_config_path) as f:
            portals = yaml.safe_load(f)
        return list(portals["portals"].keys())

    def get_rescan_portals(self) -> list[str]:
        """Return list of portal keys for afternoon rescan."""
        return self.config["schedules"]["afternoon_rescan"]["portals"]

    def start(self) -> None:
        """Start the scheduler (blocking). Call from CLI."""
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.error("APScheduler not installed. Run: uv add apscheduler")
            return

        scheduler = BlockingScheduler()

        # Morning full scan — 8 AM (smart by default)
        scheduler.add_job(
            self._run_full_scan,
            CronTrigger.from_crontab(self.config["schedules"]["full_scan"]["cron"]),
            id="full_scan",
            name="Morning Full Scan",
        )

        # Afternoon rescan — 2 PM (smart by default)
        scheduler.add_job(
            self._run_rescan,
            CronTrigger.from_crontab(
                self.config["schedules"]["afternoon_rescan"]["cron"]
            ),
            id="afternoon_rescan",
            name="Afternoon Rescan",
        )

        # Weekly archive — Sunday midnight
        scheduler.add_job(
            self._run_archive,
            CronTrigger.from_crontab("0 0 * * 0"),
            id="weekly_archive",
            name="Weekly Stale Posting Archive",
        )

        # Follow-up alerts — 8:30 AM daily
        followup_cron = (
            self.config.get("schedules", {})
            .get("followup_alerts", {})
            .get("cron", "30 8 * * *")
        )
        scheduler.add_job(
            self._run_followup_alerts,
            CronTrigger.from_crontab(followup_cron),
            id="followup_alerts",
            name="Daily Follow-up Alerts",
        )

        logger.info(
            "Scheduler started. Full scan at 8 AM, follow-ups at 8:30 AM, "
            "rescan at 2 PM, archive Sundays."
        )
        try:
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
            logger.info("Scheduler stopped.")

    def _run_full_scan(self) -> None:
        """Execute full morning scan (smart by default)."""
        self._maybe_reload_config()
        self._run_smart_scan()

    def _run_rescan(self) -> None:
        """Execute afternoon rescan (smart by default)."""
        self._maybe_reload_config()
        self._run_smart_rescan()

    def _run_basic_scan(self) -> None:
        """Execute full morning scan (basic — no portal scorer filtering)."""
        import asyncio

        from src.db.database import get_engine, get_session, init_db
        from src.pipeline.orchestrator import Pipeline

        portals = self.get_full_scan_portals()
        logger.info(f"Running basic full scan across {len(portals)} portals")
        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            pipeline = Pipeline(session)
            asyncio.run(pipeline.scan_all(portals=portals))
        finally:
            session.close()

    def _run_basic_rescan(self) -> None:
        """Execute afternoon rescan (basic — no portal scorer filtering)."""
        import asyncio

        from src.db.database import get_engine, get_session, init_db
        from src.pipeline.orchestrator import Pipeline

        portals = self.get_rescan_portals()
        logger.info(f"Running basic rescan across {len(portals)} portals")
        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            pipeline = Pipeline(session)
            asyncio.run(pipeline.scan_all(portals=portals))
        finally:
            session.close()

    def _run_smart_scan(self) -> None:
        """Execute smart full scan using SmartScanOrchestrator."""
        import asyncio

        from src.db.database import get_engine, get_session, init_db
        from src.pipeline.smart_scan import SmartScanOrchestrator

        logger.info("Running smart full scan")
        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            orchestrator = SmartScanOrchestrator(session)
            asyncio.run(orchestrator.run_smart_scan(scan_type="full"))
        finally:
            session.close()

    def _run_smart_rescan(self) -> None:
        """Execute smart afternoon rescan using SmartScanOrchestrator."""
        import asyncio

        from src.db.database import get_engine, get_session, init_db
        from src.pipeline.smart_scan import SmartScanOrchestrator

        logger.info("Running smart afternoon rescan")
        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            orchestrator = SmartScanOrchestrator(session)
            asyncio.run(orchestrator.run_smart_scan(scan_type="rescan"))
        finally:
            session.close()

    def _run_followup_alerts(self) -> None:
        """Execute daily follow-up alert check."""
        self._maybe_reload_config()
        from src.db.database import get_engine, get_session, init_db
        from src.outreach.followup_manager import FollowUpManager

        logger.info("Running daily follow-up alert check")
        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            manager = FollowUpManager(session)
            alert = manager.generate_daily_alert()

            # Log overdue items as warnings
            for item in alert.get("overdue", []):
                logger.warning(
                    f"OVERDUE follow-up: {item['company_name']} — "
                    f"{item['last_step']} → {item['next_step']} "
                    f"({item['days_overdue']} days overdue)"
                )

            due_today = alert.get("due_today", [])
            if due_today:
                logger.info(f"Follow-ups due today: {len(due_today)}")

            active = alert.get("total_active_sequences", 0)
            logger.info(
                f"Follow-up summary: {len(alert.get('overdue', []))} overdue, "
                f"{len(due_today)} due today, {active} active sequences"
            )
        finally:
            session.close()

    def _run_archive(self) -> None:
        """Archive stale job postings."""
        from src.db.database import get_engine, get_session, init_db
        from src.validators.quality_gates import QualityAuditor

        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            auditor = QualityAuditor(session)
            count = auditor.archive_stale_postings()
            logger.info(f"Archived {count} stale postings")
        finally:
            session.close()

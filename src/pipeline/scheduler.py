"""Scan scheduler — APScheduler-based job scheduling."""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger


class ScanScheduler:
    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "schedule.yaml"
            )
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

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

        # Morning full scan — 8 AM
        scheduler.add_job(
            self._run_full_scan,
            CronTrigger.from_crontab(self.config["schedules"]["full_scan"]["cron"]),
            id="full_scan",
            name="Morning Full Scan",
        )

        # Afternoon rescan — 2 PM
        scheduler.add_job(
            self._run_rescan,
            CronTrigger.from_crontab(
                self.config["schedules"]["afternoon_rescan"]["cron"]
            ),
            id="afternoon_rescan",
            name="Afternoon Rescan",
        )

        logger.info("Scheduler started. Full scan at 8 AM, rescan at 2 PM.")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
            logger.info("Scheduler stopped.")

    def _run_full_scan(self) -> None:
        """Execute full morning scan."""
        import asyncio

        from src.db.database import get_engine, get_session, init_db
        from src.pipeline.orchestrator import Pipeline

        portals = self.get_full_scan_portals()
        logger.info(f"Running full scan across {len(portals)} portals")
        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            pipeline = Pipeline(session)
            asyncio.run(pipeline.scan_all(portals=portals))
        finally:
            session.close()

    def _run_rescan(self) -> None:
        """Execute afternoon rescan on high-velocity portals."""
        import asyncio

        from src.db.database import get_engine, get_session, init_db
        from src.pipeline.orchestrator import Pipeline

        portals = self.get_rescan_portals()
        logger.info(f"Running rescan across {len(portals)} portals")
        engine = get_engine()
        init_db(engine)
        session = get_session(engine)
        try:
            pipeline = Pipeline(session)
            asyncio.run(pipeline.scan_all(portals=portals))
        finally:
            session.close()

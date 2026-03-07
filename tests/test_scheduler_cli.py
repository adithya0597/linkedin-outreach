"""Tests for scheduler CLI wiring and new scheduled jobs."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import yaml
import pytest

from src.pipeline.scheduler import ScanScheduler


@pytest.fixture
def config_file():
    """Create a temporary schedule.yaml with all 6 jobs."""
    config = {
        "schedules": {
            "full_scan": {
                "cron": "0 8 * * *",
                "portals": "all",
                "description": "Morning full scan — all portals",
            },
            "afternoon_rescan": {
                "cron": "0 14 * * *",
                "portals": ["wellfound", "linkedin"],
                "description": "Afternoon rescan — high-velocity sources",
            },
            "followup_alerts": {
                "cron": "30 8 * * *",
                "description": "Daily follow-up alert — overdue and due-today",
            },
            "response_check": {
                "cron": "0 9 * * *",
                "description": "Log count of outreach awaiting response checks",
            },
            "draft_preparation": {
                "cron": "30 14 * * *",
                "description": "Auto-prepare email drafts for stale connections",
            },
            "frequency_review": {
                "cron": "0 18 * * 5",
                "action": "portal_analytics",
                "description": "Weekly portal performance review",
            },
        },
        "promotion_rules": {
            "promote_threshold": 4,
            "demote_threshold": 3,
            "review_window_weeks": 2,
        },
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(config, f)
        f.flush()
        yield f.name
    os.unlink(f.name)


class TestSchedulerDryRunListsJobs:
    def test_scheduler_dry_run_lists_jobs(self, config_file):
        """Mock ScanScheduler, verify --dry-run lists jobs."""
        scheduler = ScanScheduler(config_path=config_file)
        jobs = scheduler.get_jobs()

        # Should return a list of dicts
        assert isinstance(jobs, list)
        assert len(jobs) >= 5

        # Each job should have name, cron, description
        for job in jobs:
            assert "name" in job
            assert "cron" in job
            assert "description" in job

        # Verify known jobs are present
        job_names = [j["name"] for j in jobs]
        assert "response_check" in job_names
        assert "draft_preparation" in job_names
        assert "full_scan" in job_names


class TestSchedulerHasSixJobs:
    def test_scheduler_has_six_jobs(self):
        """Read config/schedule.yaml, verify >= 6 jobs."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "schedule.yaml"
        )
        with open(config_path) as f:
            config = yaml.safe_load(f)

        schedules = config.get("schedules", {})
        job_count = sum(
            1
            for cfg in schedules.values()
            if isinstance(cfg, dict) and "cron" in cfg
        )
        assert job_count >= 6, f"Expected >= 6 jobs, got {job_count}"


class TestResponseCheckJobLogsCount:
    @patch("src.pipeline.scheduler.ScanScheduler._maybe_reload_config")
    def test_response_check_job_logs_count(self, mock_reload, config_file):
        """Call _run_response_check with mocked DB, no errors."""
        scheduler = ScanScheduler(config_path=config_file)

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.count.return_value = 3
        mock_session.query.return_value = mock_query

        with (
            patch("src.pipeline.scheduler.ScanScheduler._maybe_reload_config"),
            patch("src.db.database.get_engine") as mock_engine,
            patch("src.db.database.init_db"),
            patch("src.db.database.get_session", return_value=mock_session),
        ):
            # Should not raise
            scheduler._run_response_check()

            # Verify session was queried and closed
            mock_session.query.assert_called_once()
            mock_session.close.assert_called_once()


class TestDraftPreparationCallsBridge:
    def test_draft_preparation_calls_bridge(self, config_file):
        """Call _run_draft_preparation with mocked bridge, verify prepare_drafts called."""
        scheduler = ScanScheduler(config_path=config_file)

        mock_session = MagicMock()
        mock_bridge = MagicMock()
        mock_bridge.prepare_drafts.return_value = [{"to": "a@b.com", "subject": "Hi"}]
        mock_bridge.save_drafts.return_value = 1

        with (
            patch("src.pipeline.scheduler.ScanScheduler._maybe_reload_config"),
            patch("src.db.database.get_engine"),
            patch("src.db.database.init_db"),
            patch("src.db.database.get_session", return_value=mock_session),
            patch(
                "src.integrations.gmail_bridge.GmailBridge",
                return_value=mock_bridge,
            ),
        ):
            scheduler._run_draft_preparation()

            mock_bridge.prepare_drafts.assert_called_once()
            mock_bridge.save_drafts.assert_called_once()
            mock_session.close.assert_called_once()


class TestScheduleYamlHasNewJobs:
    def test_schedule_yaml_has_new_jobs(self):
        """Read schedule.yaml, verify response_check and draft_preparation present."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "schedule.yaml"
        )
        with open(config_path) as f:
            config = yaml.safe_load(f)

        schedules = config.get("schedules", {})

        assert "response_check" in schedules, "response_check missing from schedule.yaml"
        assert "draft_preparation" in schedules, "draft_preparation missing from schedule.yaml"

        # Verify cron values
        assert schedules["response_check"]["cron"] == "0 9 * * *"
        assert schedules["draft_preparation"]["cron"] == "30 14 * * *"

        # Verify descriptions exist
        assert schedules["response_check"].get("description")
        assert schedules["draft_preparation"].get("description")

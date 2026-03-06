"""Tests for scheduler upgrade — follow-up alerts and smart scan."""

import pytest
from unittest.mock import patch, MagicMock

from src.pipeline.scheduler import ScanScheduler


@pytest.fixture
def scheduler(tmp_path):
    config = tmp_path / "schedule.yaml"
    config.write_text("""
schedules:
  full_scan:
    cron: "0 8 * * *"
    portals: "all"
    description: "Morning full scan"
  afternoon_rescan:
    cron: "0 14 * * *"
    portals:
      - "wellfound"
      - "yc"
    description: "Afternoon rescan"
  followup_alerts:
    cron: "30 8 * * *"
    description: "Daily follow-up alerts"
  frequency_review:
    cron: "0 18 * * 5"
    action: "portal_analytics"
    description: "Weekly review"
promotion_rules:
  promote_threshold: 4
  demote_threshold: 3
  review_window_weeks: 2
""")
    return ScanScheduler(config_path=str(config))


@patch("src.outreach.followup_manager.FollowUpManager.generate_daily_alert")
@patch("src.db.database.get_session")
@patch("src.db.database.init_db")
@patch("src.db.database.get_engine")
def test_followup_alerts_calls_manager(
    mock_engine, mock_init, mock_session, mock_alert, scheduler
):
    mock_sess = MagicMock()
    mock_session.return_value = mock_sess
    mock_alert.return_value = {
        "overdue": [],
        "due_today": [],
        "due_this_week": [],
        "total_active_sequences": 0,
    }

    scheduler._run_followup_alerts()

    mock_alert.assert_called_once()
    mock_sess.close.assert_called_once()


@patch("src.outreach.followup_manager.FollowUpManager.generate_daily_alert")
@patch("src.db.database.get_session")
@patch("src.db.database.init_db")
@patch("src.db.database.get_engine")
def test_followup_alerts_logs_overdue_warnings(
    mock_engine, mock_init, mock_session, mock_alert, scheduler
):
    from loguru import logger
    import io

    mock_sess = MagicMock()
    mock_session.return_value = mock_sess
    mock_alert.return_value = {
        "overdue": [
            {
                "company_name": "TestCo",
                "last_step": "connection_request",
                "next_step": "follow_up",
                "days_overdue": 2,
            }
        ],
        "due_today": [],
        "due_this_week": [],
        "total_active_sequences": 1,
    }

    # Add a loguru sink to capture log output
    log_output = io.StringIO()
    sink_id = logger.add(log_output, format="{level} {message}", level="WARNING")
    try:
        scheduler._run_followup_alerts()
        log_text = log_output.getvalue()
        assert "OVERDUE" in log_text and "TestCo" in log_text
    finally:
        logger.remove(sink_id)


@patch("src.pipeline.smart_scan.SmartScanOrchestrator.run_smart_scan")
@patch("src.db.database.get_session")
@patch("src.db.database.init_db")
@patch("src.db.database.get_engine")
def test_smart_scan_uses_orchestrator(
    mock_engine, mock_init, mock_session, mock_run, scheduler
):
    mock_sess = MagicMock()
    mock_session.return_value = mock_sess

    # run_smart_scan is async, mock it as a coroutine
    import asyncio

    async def fake_scan(**kwargs):
        pass

    mock_run.side_effect = fake_scan

    scheduler._run_smart_scan()

    mock_run.assert_called_once_with(scan_type="full")
    mock_sess.close.assert_called_once()


@patch("src.pipeline.smart_scan.SmartScanOrchestrator.run_smart_scan")
@patch("src.db.database.get_session")
@patch("src.db.database.init_db")
@patch("src.db.database.get_engine")
def test_smart_rescan_uses_orchestrator(
    mock_engine, mock_init, mock_session, mock_run, scheduler
):
    mock_sess = MagicMock()
    mock_session.return_value = mock_sess

    async def fake_scan(**kwargs):
        pass

    mock_run.side_effect = fake_scan

    scheduler._run_smart_rescan()

    mock_run.assert_called_once_with(scan_type="rescan")
    mock_sess.close.assert_called_once()


@patch("src.pipeline.scheduler.ScanScheduler._run_smart_scan")
def test_full_scan_delegates_to_smart_scan(mock_smart, scheduler):
    scheduler._run_full_scan()
    mock_smart.assert_called_once()


@patch("src.pipeline.scheduler.ScanScheduler._run_smart_rescan")
def test_rescan_delegates_to_smart_rescan(mock_smart, scheduler):
    scheduler._run_rescan()
    mock_smart.assert_called_once()


@patch("src.pipeline.orchestrator.Pipeline.scan_all")
@patch("src.db.database.get_session")
@patch("src.db.database.init_db")
@patch("src.db.database.get_engine")
def test_basic_scan_still_works(
    mock_engine, mock_init, mock_session, mock_scan_all, scheduler, tmp_path
):
    mock_sess = MagicMock()
    mock_session.return_value = mock_sess

    # Create a fake portals.yaml for get_full_scan_portals
    portals_yaml = tmp_path / "portals.yaml"
    portals_yaml.write_text("""
portals:
  wellfound: {}
  yc: {}
""")

    async def fake_scan(**kwargs):
        pass

    mock_scan_all.side_effect = fake_scan

    # Patch the portals config path
    with patch.object(
        scheduler,
        "get_full_scan_portals",
        return_value=["wellfound", "yc"],
    ):
        scheduler._run_basic_scan()

    mock_scan_all.assert_called_once()
    mock_sess.close.assert_called_once()


def test_config_reads_followup_alerts_cron(scheduler):
    cron = scheduler.config["schedules"]["followup_alerts"]["cron"]
    assert cron == "30 8 * * *"


@patch("apscheduler.schedulers.blocking.BlockingScheduler.start")
@patch("apscheduler.schedulers.blocking.BlockingScheduler.add_job")
def test_start_registers_four_jobs(mock_add_job, mock_start, scheduler):
    scheduler.start()

    assert mock_add_job.call_count == 4

    job_ids = [call.kwargs["id"] for call in mock_add_job.call_args_list]
    assert "full_scan" in job_ids
    assert "afternoon_rescan" in job_ids
    assert "weekly_archive" in job_ids
    assert "followup_alerts" in job_ids

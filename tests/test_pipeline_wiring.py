"""Tests for pipeline wiring — scan stage in DailyOrchestrator, HealthMonitor->AutoPromotion."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import yaml

from src.db.orm import ScanORM
from src.pipeline.auto_promotion import PortalAutoPromoter
from src.pipeline.daily_orchestrator import DailyOrchestrator
from src.pipeline.health_monitor import HealthMonitor


@pytest.fixture
def tmp_schedule(tmp_path):
    """Create a temporary schedule.yaml with afternoon rescan portals."""
    config = {
        "schedules": {
            "afternoon_rescan": {
                "portals": ["portal_a", "portal_b", "portal_c"]
            }
        }
    }
    path = tmp_path / "schedule.yaml"
    path.write_text(yaml.dump(config, default_flow_style=False))
    return str(path)


# ---------------------------------------------------------------------------
# DailyOrchestrator: _run_scan exists
# ---------------------------------------------------------------------------


def test_orchestrator_has_run_scan_method(session):
    """DailyOrchestrator has a _run_scan method."""
    orch = DailyOrchestrator(session)
    assert hasattr(orch, "_run_scan")
    assert callable(orch._run_scan)


# ---------------------------------------------------------------------------
# DailyOrchestrator: run_full_day includes scan key
# ---------------------------------------------------------------------------


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_drafts")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_h1b_verify")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scan")
def test_run_full_day_has_scan_key(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """run_full_day() result dict has a 'scan' key."""
    mock_scan.return_value = {"scan_results": {"total_found": 10, "total_new": 3}}
    mock_enrich.return_value = {"enriched": 0, "skipped": 0, "errors": []}
    mock_h1b.return_value = {"updated": 0}
    mock_score.return_value = {"scored": 0, "top_10": []}
    mock_drafts.return_value = {"drafted": 0, "skipped": 0, "over_limit": 0, "errors": []}
    mock_queue.return_value = []
    mock_followup.return_value = {
        "overdue": [], "due_today": [], "due_this_week": [],
        "total_active_sequences": 0,
    }
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert "scan" in result
    assert result["scan"]["scan_results"]["total_found"] == 10
    mock_scan.assert_called_once()


# ---------------------------------------------------------------------------
# DailyOrchestrator: scan runs first (before enrichment)
# ---------------------------------------------------------------------------


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_drafts")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_h1b_verify")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scan")
def test_scan_runs_before_enrichment(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Scan stage executes before enrichment (tracked via call order)."""
    call_order = []

    mock_scan.side_effect = lambda: call_order.append("scan") or {}
    mock_enrich.side_effect = lambda: call_order.append("enrich") or {}
    mock_h1b.side_effect = lambda: call_order.append("h1b") or {"updated": 0}
    mock_score.side_effect = lambda: call_order.append("score") or {}
    mock_drafts.side_effect = lambda *a, **kw: call_order.append("drafts") or {}
    mock_queue.side_effect = lambda: call_order.append("queue") or []
    mock_followup.side_effect = lambda: call_order.append("followup") or {
        "overdue": [], "due_today": [], "due_this_week": [], "total_active_sequences": 0
    }
    mock_sync.side_effect = lambda dry_run=False: call_order.append("sync") or {}

    orch = DailyOrchestrator(session)
    orch.run_full_day()

    assert call_order.index("scan") < call_order.index("enrich")


# ---------------------------------------------------------------------------
# DailyOrchestrator: skip_scan=True
# ---------------------------------------------------------------------------


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_drafts")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_h1b_verify")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scan")
def test_skip_scan_returns_skipped(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """skip_scan=True skips scan stage and result shows {'skipped': True}."""
    mock_enrich.return_value = {}
    mock_h1b.return_value = {"updated": 0}
    mock_score.return_value = {}
    mock_drafts.return_value = {"drafted": 0, "skipped": 0, "over_limit": 0, "errors": []}
    mock_queue.return_value = []
    mock_followup.return_value = {
        "overdue": [], "due_today": [], "due_this_week": [],
        "total_active_sequences": 0,
    }
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day(skip_scan=True)

    mock_scan.assert_not_called()
    assert result["scan"] == {"skipped": True}


# ---------------------------------------------------------------------------
# HealthMonitor: auto_demote_unhealthy returns unhealthy portals
# ---------------------------------------------------------------------------


def test_auto_demote_unhealthy_returns_failing_portals(session):
    """auto_demote_unhealthy() returns portals exceeding failure threshold."""
    now = datetime.now()
    # Create 3 consecutive failed scans for portal_x (threshold=3)
    for i in range(3):
        session.add(ScanORM(
            portal="portal_x",
            scan_type="full",
            started_at=now - timedelta(hours=i),
            companies_found=0,
            new_companies=0,
            errors=f"connection timeout attempt {i}",
            is_healthy=False,
        ))

    # Create 1 healthy scan for portal_y (below threshold)
    session.add(ScanORM(
        portal="portal_y",
        scan_type="full",
        started_at=now,
        companies_found=5,
        new_companies=2,
        errors="",
        is_healthy=True,
    ))
    session.commit()

    monitor = HealthMonitor(session, failure_threshold=3)
    unhealthy = monitor.auto_demote_unhealthy()

    assert "portal_x" in unhealthy
    assert "portal_y" not in unhealthy


# ---------------------------------------------------------------------------
# HealthMonitor: detect_zero_yield detects dormant portals
# ---------------------------------------------------------------------------


def test_detect_zero_yield_finds_dormant_portals(session):
    """detect_zero_yield() detects portals with 0 new companies in last N scans."""
    now = datetime.now()

    # Portal with 5 scans, all zero new_companies
    for i in range(5):
        session.add(ScanORM(
            portal="dead_portal",
            scan_type="full",
            started_at=now - timedelta(hours=i),
            companies_found=0,
            new_companies=0,
            errors="",
            is_healthy=True,
        ))

    # Portal with 5 scans, some new_companies
    for i in range(5):
        session.add(ScanORM(
            portal="active_portal",
            scan_type="full",
            started_at=now - timedelta(hours=i),
            companies_found=10,
            new_companies=2 if i % 2 == 0 else 0,
            errors="",
            is_healthy=True,
        ))

    # Portal with only 3 scans (below threshold of 5) -- should NOT be flagged
    for i in range(3):
        session.add(ScanORM(
            portal="young_portal",
            scan_type="full",
            started_at=now - timedelta(hours=i),
            companies_found=0,
            new_companies=0,
            errors="",
            is_healthy=True,
        ))

    session.commit()

    monitor = HealthMonitor(session)
    zero_yield = monitor.detect_zero_yield(threshold=5)

    assert "dead_portal" in zero_yield
    assert "active_portal" not in zero_yield
    assert "young_portal" not in zero_yield


# ---------------------------------------------------------------------------
# AutoPromoter: force_demote removes a portal from the list
# ---------------------------------------------------------------------------


def test_force_demote_removes_portal(session, tmp_schedule):
    """force_demote() removes a portal from afternoon rescan and writes to disk."""
    promoter = PortalAutoPromoter(session, config_path=tmp_schedule)
    result = promoter.force_demote("portal_b")

    assert result["removed"] is True
    assert result["portal"] == "portal_b"
    assert "portal_b" not in result["current_list"]
    assert "portal_a" in result["current_list"]
    assert "portal_c" in result["current_list"]

    # Verify the file was actually updated
    with open(tmp_schedule) as f:
        config = yaml.safe_load(f)
    written_portals = config["schedules"]["afternoon_rescan"]["portals"]
    assert "portal_b" not in written_portals
    assert "portal_a" in written_portals


def test_force_demote_nonexistent_portal(session, tmp_schedule):
    """force_demote() on a portal not in the list returns removed=False."""
    promoter = PortalAutoPromoter(session, config_path=tmp_schedule)
    result = promoter.force_demote("nonexistent_portal")

    assert result["removed"] is False
    assert result["portal"] == "nonexistent_portal"
    # Original list unchanged
    assert "portal_a" in result["current_list"]
    assert "portal_b" in result["current_list"]
    assert "portal_c" in result["current_list"]

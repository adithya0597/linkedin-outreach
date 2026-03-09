"""Tests for DailyOrchestrator — full daily pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.db.orm import CompanyORM, OutreachORM
from src.pipeline.daily_orchestrator import DailyOrchestrator


@pytest.fixture
def session_with_data(session):
    """Session pre-loaded with company and outreach data."""
    company = CompanyORM(
        name="TestCo",
        description="AI startup based in Austin, TX with 50 employees",
        is_ai_native=True,
        h1b_status="Confirmed",
        tier="Tier 1 - HIGH",
        funding_stage="Series A",
        employees=50,
        hq_location="Austin, TX",
    )
    session.add(company)
    session.flush()

    outreach = OutreachORM(
        company_id=company.id,
        company_name="TestCo",
        contact_name="Jane Doe",
        template_type="connection_request",
        content="Hello!",
        character_count=6,
        stage="Not Started",
        sequence_step="connection_request",
    )
    session.add(outreach)
    session.commit()
    return session


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
def test_full_run_calls_all_stages(
    mock_enrich, mock_score, mock_queue, mock_followup, mock_sync, session
):
    """Full run calls each stage in order."""
    mock_enrich.return_value = {"enriched": 1, "skipped": 0, "errors": []}
    mock_score.return_value = {"scored": 5, "top_10": []}
    mock_queue.return_value = [{"company_name": "TestCo"}]
    mock_followup.return_value = {
        "overdue": [], "due_today": [], "due_this_week": [],
        "total_active_sequences": 0,
    }
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    mock_enrich.assert_called_once()
    mock_score.assert_called_once()
    mock_queue.assert_called_once()
    mock_followup.assert_called_once()
    mock_sync.assert_called_once_with(dry_run=False)

    assert result["enrichment"] == {"enriched": 1, "skipped": 0, "errors": []}
    assert result["scoring"] == {"scored": 5, "top_10": []}
    assert len(result["send_queue"]) == 1
    assert result["followups"]["total_active_sequences"] == 0
    assert result["sync"]["synced"] == 0


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
def test_dry_run_passes_to_sync(
    mock_enrich, mock_score, mock_queue, mock_followup, mock_sync, session
):
    """dry_run=True is forwarded to sync stage."""
    mock_enrich.return_value = {}
    mock_score.return_value = {}
    mock_queue.return_value = []
    mock_followup.return_value = {"overdue": [], "due_today": [], "due_this_week": [], "total_active_sequences": 0}
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    orch.run_full_day(dry_run=True)

    mock_sync.assert_called_once_with(dry_run=True)


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
def test_skip_enrich_skips_enrichment(
    mock_enrich, mock_score, mock_queue, mock_followup, mock_sync, session
):
    """skip_enrich=True skips enrichment stage."""
    mock_score.return_value = {}
    mock_queue.return_value = []
    mock_followup.return_value = {"overdue": [], "due_today": [], "due_this_week": [], "total_active_sequences": 0}
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day(skip_enrich=True)

    mock_enrich.assert_not_called()
    assert result["enrichment"] == {"skipped": True}
    mock_score.assert_called_once()


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
def test_single_stage_failure_doesnt_block_others(
    mock_enrich, mock_score, mock_queue, mock_followup, mock_sync, session
):
    """A failure in one stage doesn't prevent the rest from running."""
    mock_enrich.side_effect = RuntimeError("enrichment exploded")
    mock_score.return_value = {"scored": 3, "top_10": []}
    mock_queue.return_value = []
    mock_followup.return_value = {"overdue": [], "due_today": [], "due_this_week": [], "total_active_sequences": 0}
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    # Enrichment failed with error dict
    assert "error" in result["enrichment"]
    assert "enrichment exploded" in result["enrichment"]["error"]

    # But remaining stages still ran
    mock_score.assert_called_once()
    mock_queue.assert_called_once()
    mock_followup.assert_called_once()
    mock_sync.assert_called_once()
    assert result["scoring"]["scored"] == 3


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
def test_returns_timing_info(
    mock_enrich, mock_score, mock_queue, mock_followup, mock_sync, session
):
    """Result includes total_time > 0 and a timestamp."""
    mock_enrich.return_value = {}
    mock_score.return_value = {}
    mock_queue.return_value = []
    mock_followup.return_value = {"overdue": [], "due_today": [], "due_this_week": [], "total_active_sequences": 0}
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert result["total_time"] >= 0
    assert "timestamp" in result
    assert "T" in result["timestamp"]  # ISO format


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
def test_daily_summary_includes_all_sections(
    mock_enrich, mock_score, mock_queue, mock_followup, mock_sync, session
):
    """generate_daily_summary returns markdown with all section headers."""
    mock_enrich.return_value = {"enriched": 2, "skipped": 1, "errors": []}
    mock_score.return_value = {
        "scored": 5,
        "top_10": [("Acme", 92.5, "Tier 1 - HIGH"), ("Beta", 85.0, "Tier 2 - STRONG")],
    }
    mock_queue.return_value = [{"company_name": "Acme"}]
    mock_followup.return_value = {
        "overdue": [{"company_name": "OldCo"}],
        "due_today": [],
        "due_this_week": [{"company_name": "SoonCo"}],
        "total_active_sequences": 3,
    }
    mock_sync.return_value = {"synced": 1, "skipped": 0, "errors": []}

    orch = DailyOrchestrator(session)
    orch.run_full_day()
    summary = orch.generate_daily_summary()

    assert "# Daily Pipeline Summary" in summary
    assert "## Enrichment" in summary
    assert "## Scoring" in summary
    assert "## Send Queue" in summary
    assert "## Follow-ups" in summary
    assert "## Notion Sync" in summary
    assert "Enriched: 2" in summary
    assert "Scored: 5" in summary
    assert "1 messages ready to send" in summary
    assert "Overdue: 1" in summary
    assert "Synced: 1" in summary


def test_daily_summary_no_results(session):
    """generate_daily_summary without a prior run returns a fallback message."""
    orch = DailyOrchestrator(session)
    summary = orch.generate_daily_summary()
    assert "No pipeline run results available" in summary


def test_empty_db_doesnt_crash(session):
    """Full run on an empty database completes without errors."""
    orch = DailyOrchestrator(session)

    # Patch sync since it needs env vars / network
    with patch.object(orch, "_run_sync", return_value={"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}):
        result = orch.run_full_day()

    assert result["total_time"] >= 0
    assert result["enrichment"] is not None
    assert result["scoring"] is not None
    assert isinstance(result["send_queue"], list)


def test_empty_db_scoring_returns_zero(session):
    """Scoring on empty DB returns scored=0."""
    orch = DailyOrchestrator(session)

    with patch.object(orch, "_run_sync", return_value={"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}):
        result = orch.run_full_day(skip_scan=True)

    assert result["scoring"]["scored"] == 0


@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_sync")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_followup_check")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_send_queue")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_scoring")
@patch("src.pipeline.daily_orchestrator.DailyOrchestrator._run_enrichment")
def test_multiple_stage_failures(
    mock_enrich, mock_score, mock_queue, mock_followup, mock_sync, session
):
    """Multiple stage failures are each captured independently."""
    mock_enrich.side_effect = RuntimeError("enrich boom")
    mock_score.side_effect = ValueError("score boom")
    mock_queue.return_value = []
    mock_followup.side_effect = RuntimeError("followup boom")
    mock_sync.return_value = {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert "error" in result["enrichment"]
    assert "error" in result["scoring"]
    assert isinstance(result["send_queue"], list)
    assert "error" in result["followups"]
    assert result["sync"]["synced"] == 0


def test_config_path_stored(session):
    """config_path parameter is stored on the orchestrator."""
    orch = DailyOrchestrator(session, config_path="/some/config.yaml")
    assert orch.config_path == "/some/config.yaml"

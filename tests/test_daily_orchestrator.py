"""Tests for DailyOrchestrator — full 8-stage daily pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.db.orm import CompanyORM, OutreachORM
from src.pipeline.daily_orchestrator import DailyOrchestrator

# ---------------------------------------------------------------------------
# Helpers — mock return values for all 8 stages
# ---------------------------------------------------------------------------

_MOCK_RETURNS = {
    "scan": {"scan_results": {"total_found": 10, "total_new": 3}},
    "enrich": {"enriched": 1, "skipped": 0, "errors": []},
    "h1b": {"updated": 2},
    "score": {"scored": 5, "top_10": []},
    "drafts": {"drafted": 3, "skipped": 0, "over_limit": 0, "errors": [], "qualifying": 3},
    "queue": [{"company_name": "TestCo"}],
    "followup": {
        "overdue": [], "due_today": [], "due_this_week": [],
        "total_active_sequences": 0,
    },
    "sync": {"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}},
}


def _set_all_mock_defaults(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync,
):
    """Wire up default return values for all 8 stage mocks."""
    mock_scan.return_value = _MOCK_RETURNS["scan"]
    mock_enrich.return_value = _MOCK_RETURNS["enrich"]
    mock_h1b.return_value = _MOCK_RETURNS["h1b"]
    mock_score.return_value = _MOCK_RETURNS["score"]
    mock_drafts.return_value = _MOCK_RETURNS["drafts"]
    mock_queue.return_value = _MOCK_RETURNS["queue"]
    mock_followup.return_value = _MOCK_RETURNS["followup"]
    mock_sync.return_value = _MOCK_RETURNS["sync"]


# Common patch decorator stack — patches all 8 stages.
# Decorator order: bottom (scan) -> top (sync).
# Function arg order: scan, enrich, h1b, score, drafts, queue, followup, sync.
_P = "src.pipeline.daily_orchestrator.DailyOrchestrator"

_ALL_PATCHES = (
    patch(f"{_P}._run_sync"),
    patch(f"{_P}._run_followup_check"),
    patch(f"{_P}._run_send_queue"),
    patch(f"{_P}._run_drafts"),
    patch(f"{_P}._run_scoring"),
    patch(f"{_P}._run_h1b_verify"),
    patch(f"{_P}._run_enrichment"),
    patch(f"{_P}._run_scan"),
)


def _apply_all_patches(func):
    """Apply all 8 stage patches to a test function."""
    for p in _ALL_PATCHES:
        func = p(func)
    return func


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Core: all stages called
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_full_run_calls_all_stages(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Full run calls each of the 8 stages."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    mock_scan.assert_called_once()
    mock_enrich.assert_called_once()
    mock_h1b.assert_called_once()
    mock_score.assert_called_once()
    mock_drafts.assert_called_once()
    mock_queue.assert_called_once()
    mock_followup.assert_called_once()
    mock_sync.assert_called_once_with(dry_run=False)

    assert result["enrichment"] == _MOCK_RETURNS["enrich"]
    assert result["h1b_verify"] == _MOCK_RETURNS["h1b"]
    assert result["scoring"] == _MOCK_RETURNS["score"]
    assert result["drafts"] == _MOCK_RETURNS["drafts"]
    assert len(result["send_queue"]) == 1
    assert result["followups"]["total_active_sequences"] == 0
    assert result["sync"]["synced"] == 0


# ---------------------------------------------------------------------------
# Result dict has all 8 stage keys
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_results_include_all_8_stage_keys(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Result dict contains all 8 stage keys plus metadata."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    expected_keys = {
        "scan", "enrichment", "h1b_verify", "scoring", "drafts",
        "send_queue", "followups", "sync",
        "stage_timings", "total_time", "timestamp",
    }
    assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# dry_run forwarded to sync
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_dry_run_passes_to_sync(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """dry_run=True is forwarded to sync stage."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    orch.run_full_day(dry_run=True)

    mock_sync.assert_called_once_with(dry_run=True)


# ---------------------------------------------------------------------------
# skip_enrich
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_skip_enrich_skips_enrichment(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """skip_enrich=True skips enrichment stage."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day(skip_enrich=True)

    mock_enrich.assert_not_called()
    assert result["enrichment"] == {"skipped": True}
    mock_score.assert_called_once()


# ---------------------------------------------------------------------------
# skip_h1b
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_skip_h1b_skips_verification(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """skip_h1b=True skips H1B verification stage."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day(skip_h1b=True)

    mock_h1b.assert_not_called()
    assert result["h1b_verify"] == {"skipped": True}
    # Scoring still runs
    mock_score.assert_called_once()


# ---------------------------------------------------------------------------
# skip_drafts
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_skip_drafts_skips_draft_generation(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """skip_drafts=True skips outreach draft generation."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day(skip_drafts=True)

    mock_drafts.assert_not_called()
    assert result["drafts"] == {"skipped": True}
    # Send queue still runs
    mock_queue.assert_called_once()


# ---------------------------------------------------------------------------
# H1B runs BEFORE scoring
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_h1b_runs_before_scoring(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """H1B verification executes before scoring (tracked via call order)."""
    call_order = []

    mock_scan.side_effect = lambda: call_order.append("scan") or {}
    mock_enrich.side_effect = lambda: call_order.append("enrich") or {}
    mock_h1b.side_effect = lambda: call_order.append("h1b") or {"updated": 0}
    mock_score.side_effect = lambda: call_order.append("score") or {}
    mock_drafts.side_effect = lambda *a, **kw: call_order.append("drafts") or {}
    mock_queue.side_effect = lambda: call_order.append("queue") or []
    mock_followup.side_effect = lambda: call_order.append("followup") or _MOCK_RETURNS["followup"]
    mock_sync.side_effect = lambda dry_run=False: call_order.append("sync") or {}

    orch = DailyOrchestrator(session)
    orch.run_full_day()

    assert call_order.index("h1b") < call_order.index("score")


# ---------------------------------------------------------------------------
# Drafts run AFTER scoring
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_drafts_run_after_scoring(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Outreach drafts execute after scoring."""
    call_order = []

    mock_scan.side_effect = lambda: call_order.append("scan") or {}
    mock_enrich.side_effect = lambda: call_order.append("enrich") or {}
    mock_h1b.side_effect = lambda: call_order.append("h1b") or {"updated": 0}
    mock_score.side_effect = lambda: call_order.append("score") or {}
    mock_drafts.side_effect = lambda *a, **kw: call_order.append("drafts") or {}
    mock_queue.side_effect = lambda: call_order.append("queue") or []
    mock_followup.side_effect = lambda: call_order.append("followup") or _MOCK_RETURNS["followup"]
    mock_sync.side_effect = lambda dry_run=False: call_order.append("sync") or {}

    orch = DailyOrchestrator(session)
    orch.run_full_day()

    assert call_order.index("score") < call_order.index("drafts")


# ---------------------------------------------------------------------------
# Full 8-stage order verification
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_full_8_stage_order(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """All 8 stages execute in the correct order."""
    call_order = []

    mock_scan.side_effect = lambda: call_order.append("scan") or {}
    mock_enrich.side_effect = lambda: call_order.append("enrich") or {}
    mock_h1b.side_effect = lambda: call_order.append("h1b") or {"updated": 0}
    mock_score.side_effect = lambda: call_order.append("score") or {}
    mock_drafts.side_effect = lambda *a, **kw: call_order.append("drafts") or {}
    mock_queue.side_effect = lambda: call_order.append("queue") or []
    mock_followup.side_effect = lambda: call_order.append("followup") or _MOCK_RETURNS["followup"]
    mock_sync.side_effect = lambda dry_run=False: call_order.append("sync") or {}

    orch = DailyOrchestrator(session)
    orch.run_full_day()

    assert call_order == ["scan", "enrich", "h1b", "score", "drafts", "queue", "followup", "sync"]


# ---------------------------------------------------------------------------
# Single stage failure doesn't block others
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_single_stage_failure_doesnt_block_others(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """A failure in one stage doesn't prevent the rest from running."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )
    mock_enrich.side_effect = RuntimeError("enrichment exploded")
    mock_score.return_value = {"scored": 3, "top_10": []}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    # Enrichment failed with error dict
    assert "error" in result["enrichment"]
    assert "enrichment exploded" in result["enrichment"]["error"]

    # But remaining stages still ran
    mock_h1b.assert_called_once()
    mock_score.assert_called_once()
    mock_drafts.assert_called_once()
    mock_queue.assert_called_once()
    mock_followup.assert_called_once()
    mock_sync.assert_called_once()
    assert result["scoring"]["scored"] == 3


# ---------------------------------------------------------------------------
# H1B failure doesn't block scoring
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_h1b_failure_doesnt_block_scoring(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """H1B verification failure doesn't prevent scoring from running."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )
    mock_h1b.side_effect = RuntimeError("h1b lookup failed")
    mock_score.return_value = {"scored": 5, "top_10": []}

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert "error" in result["h1b_verify"]
    assert "h1b lookup failed" in result["h1b_verify"]["error"]
    mock_score.assert_called_once()
    assert result["scoring"]["scored"] == 5


# ---------------------------------------------------------------------------
# Draft failure doesn't block send queue
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_draft_failure_doesnt_block_send_queue(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Draft generation failure doesn't prevent send queue from running."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )
    mock_drafts.side_effect = RuntimeError("template engine broke")
    mock_queue.return_value = [{"company_name": "TestCo"}]

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert "error" in result["drafts"]
    assert "template engine broke" in result["drafts"]["error"]
    mock_queue.assert_called_once()
    assert len(result["send_queue"]) == 1


# ---------------------------------------------------------------------------
# Timing: per-stage timings
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_returns_per_stage_timings(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Result includes per-stage timing data in stage_timings dict."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert "stage_timings" in result
    timings = result["stage_timings"]
    # All stages that ran should have timing entries
    for stage in ["scan", "enrichment", "h1b_verify", "scoring", "drafts", "send_queue", "followups", "sync"]:
        assert stage in timings, f"Missing timing for {stage}"
        assert isinstance(timings[stage], float)
        assert timings[stage] >= 0


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_returns_timing_info(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Result includes total_time > 0 and a timestamp."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert result["total_time"] >= 0
    assert "timestamp" in result
    assert "T" in result["timestamp"]  # ISO format


# ---------------------------------------------------------------------------
# Skipped stages don't get timing entries
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_skipped_stages_have_no_timing(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Skipped stages do not appear in stage_timings."""
    _set_all_mock_defaults(
        mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
        mock_queue, mock_followup, mock_sync,
    )

    orch = DailyOrchestrator(session)
    result = orch.run_full_day(
        skip_scan=True, skip_enrich=True, skip_h1b=True, skip_drafts=True
    )

    timings = result["stage_timings"]
    assert "scan" not in timings
    assert "enrichment" not in timings
    assert "h1b_verify" not in timings
    assert "drafts" not in timings
    # But scoring, send_queue, followups, sync should still be timed
    assert "scoring" in timings
    assert "send_queue" in timings
    assert "followups" in timings
    assert "sync" in timings


# ---------------------------------------------------------------------------
# Summary: all sections present
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_daily_summary_includes_all_sections(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """generate_daily_summary returns markdown with all section headers."""
    mock_scan.return_value = _MOCK_RETURNS["scan"]
    mock_enrich.return_value = {"enriched": 2, "skipped": 1, "errors": []}
    mock_h1b.return_value = {"updated": 3}
    mock_score.return_value = {
        "scored": 5,
        "top_10": [("Acme", 92.5, "Tier 1 - HIGH"), ("Beta", 85.0, "Tier 2 - STRONG")],
    }
    mock_drafts.return_value = {"drafted": 4, "over_limit": 1, "errors": [], "qualifying": 5}
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
    assert "## Scan" in summary
    assert "## Enrichment" in summary
    assert "## H1B Verification" in summary
    assert "## Scoring" in summary
    assert "## Drafts" in summary
    assert "## Send Queue" in summary
    assert "## Follow-ups" in summary
    assert "## Notion Sync" in summary
    assert "## Stage Timings" in summary
    assert "Enriched: 2" in summary
    assert "Updated: 3" in summary
    assert "Scored: 5" in summary
    assert "Drafted: 4" in summary
    assert "1 messages ready to send" in summary
    assert "Overdue: 1" in summary
    assert "Synced: 1" in summary


# ---------------------------------------------------------------------------
# Summary: no results
# ---------------------------------------------------------------------------


def test_daily_summary_no_results(session):
    """generate_daily_summary without a prior run returns a fallback message."""
    orch = DailyOrchestrator(session)
    summary = orch.generate_daily_summary()
    assert "No pipeline run results available" in summary


# ---------------------------------------------------------------------------
# Empty DB doesn't crash (scan + sync patched since they need network)
# ---------------------------------------------------------------------------


def test_empty_db_doesnt_crash(session):
    """Full run on an empty database completes without errors."""
    orch = DailyOrchestrator(session)

    with patch.object(orch, "_run_scan", return_value={}), \
         patch.object(orch, "_run_sync", return_value={"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}):
        result = orch.run_full_day()

    assert result["total_time"] >= 0
    assert result["enrichment"] is not None
    assert result["h1b_verify"] is not None
    assert result["scoring"] is not None
    assert isinstance(result["send_queue"], list)


def test_empty_db_scoring_returns_zero(session):
    """Scoring on empty DB returns scored=0."""
    orch = DailyOrchestrator(session)

    with patch.object(orch, "_run_scan", return_value={}), \
         patch.object(orch, "_run_sync", return_value={"synced": 0, "skipped": 0, "errors": [], "stage_counts": {}}):
        result = orch.run_full_day(skip_scan=True)

    assert result["scoring"]["scored"] == 0


# ---------------------------------------------------------------------------
# Multiple stage failures captured independently
# ---------------------------------------------------------------------------


@patch(f"{_P}._run_sync")
@patch(f"{_P}._run_followup_check")
@patch(f"{_P}._run_send_queue")
@patch(f"{_P}._run_drafts")
@patch(f"{_P}._run_scoring")
@patch(f"{_P}._run_h1b_verify")
@patch(f"{_P}._run_enrichment")
@patch(f"{_P}._run_scan")
def test_multiple_stage_failures(
    mock_scan, mock_enrich, mock_h1b, mock_score, mock_drafts,
    mock_queue, mock_followup, mock_sync, session
):
    """Multiple stage failures are each captured independently."""
    mock_scan.return_value = {}
    mock_enrich.side_effect = RuntimeError("enrich boom")
    mock_h1b.side_effect = RuntimeError("h1b boom")
    mock_score.side_effect = ValueError("score boom")
    mock_drafts.side_effect = RuntimeError("draft boom")
    mock_queue.return_value = []
    mock_followup.side_effect = RuntimeError("followup boom")
    mock_sync.return_value = _MOCK_RETURNS["sync"]

    orch = DailyOrchestrator(session)
    result = orch.run_full_day()

    assert "error" in result["enrichment"]
    assert "error" in result["h1b_verify"]
    assert "error" in result["scoring"]
    assert "error" in result["drafts"]
    assert isinstance(result["send_queue"], list)
    assert "error" in result["followups"]
    assert result["sync"]["synced"] == 0


# ---------------------------------------------------------------------------
# Config path stored
# ---------------------------------------------------------------------------


def test_config_path_stored(session):
    """config_path parameter is stored on the orchestrator."""
    orch = DailyOrchestrator(session, config_path="/some/config.yaml")
    assert orch.config_path == "/some/config.yaml"


# ---------------------------------------------------------------------------
# H1B verify integration
# ---------------------------------------------------------------------------


def test_h1b_verify_integration(session):
    """_run_h1b_verify actually calls h1b_lookup.apply_known_statuses."""
    # Add a company with Unknown H1B status that matches a known entry
    company = CompanyORM(
        name="LlamaIndex",
        h1b_status="Unknown",
        is_ai_native=True,
    )
    session.add(company)
    session.commit()

    orch = DailyOrchestrator(session)
    result = orch._run_h1b_verify()

    assert result["updated"] == 1
    session.refresh(company)
    assert company.h1b_status == "Confirmed"


# ---------------------------------------------------------------------------
# Drafts stage — integration with empty DB
# ---------------------------------------------------------------------------


def test_drafts_stage_empty_db(session):
    """_run_drafts on empty DB returns 0 qualifying and 0 drafted."""
    orch = DailyOrchestrator(session)
    result = orch._run_drafts(score_threshold=60.0)

    assert result["qualifying"] == 0
    assert result["drafted"] == 0


# ---------------------------------------------------------------------------
# TOTAL_STAGES constant
# ---------------------------------------------------------------------------


def test_total_stages_is_8():
    """DailyOrchestrator.TOTAL_STAGES is 8."""
    assert DailyOrchestrator.TOTAL_STAGES == 8

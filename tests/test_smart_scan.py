"""Tests for SmartScanOrchestrator and Pipeline smart scan integration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, ScanORM
from src.pipeline.smart_scan import SmartScanOrchestrator
from src.validators.portal_scorer import PortalScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def session_with_scans(session):
    """Create scan history with varied performance."""
    now = datetime.now()
    # High-performing portal (velocity >=8/day, conversion >=30%)
    for i in range(5):
        session.add(
            ScanORM(
                portal="wellfound",
                scan_type="full",
                started_at=now - timedelta(days=i),
                companies_found=20,
                new_companies=8,
                is_healthy=True,
            )
        )
    # Low-performing portal (should be demoted — low velocity, low conversion)
    for i in range(5):
        session.add(
            ScanORM(
                portal="bad_portal",
                scan_type="full",
                started_at=now - timedelta(days=i),
                companies_found=1,
                new_companies=0,
                is_healthy=True,
            )
        )
    # Medium portal (hold range)
    for i in range(5):
        session.add(
            ScanORM(
                portal="medium_portal",
                scan_type="full",
                started_at=now - timedelta(days=i),
                companies_found=8,
                new_companies=2,
                is_healthy=True,
            )
        )
    session.commit()
    return session


@pytest.fixture
def config_path(tmp_path):
    """Create a temporary schedule.yaml config."""
    config = tmp_path / "schedule.yaml"
    config.write_text(
        """\
schedules:
  full_scan:
    cron: "0 8 * * *"
    portals: "all"
  afternoon_rescan:
    cron: "0 14 * * *"
    portals:
      - "wellfound"
      - "linkedin"
      - "builtin"

promotion_rules:
  promote_threshold: 4
  demote_threshold: 3
  review_window_weeks: 2
"""
    )
    return str(config)


# ---------------------------------------------------------------------------
# TestSmartScanOrchestrator
# ---------------------------------------------------------------------------


class TestSmartScanOrchestrator:
    def test_excludes_demoted_portals(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)
        smart_list = orch.get_smart_portal_list()
        assert "bad_portal" not in smart_list

    def test_keeps_promoted_and_hold(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)
        smart_list = orch.get_smart_portal_list()
        # wellfound is high-performing (promoted or hold), should remain
        assert "wellfound" in smart_list
        # medium_portal should be hold, also remains
        assert "medium_portal" in smart_list

    def test_filters_base_portals(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)
        base = ["wellfound", "bad_portal", "medium_portal"]
        smart_list = orch.get_smart_portal_list(base_portals=base)
        assert "bad_portal" not in smart_list
        assert "wellfound" in smart_list

    def test_rescan_returns_promoted_plus_config(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)
        rescan = orch.get_rescan_portals()
        # Should include configured afternoon portals
        assert "wellfound" in rescan
        assert "linkedin" in rescan
        assert "builtin" in rescan
        # Promoted portals should also be included (wellfound is high-performing)

    def test_h1b_enrichment_called(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)

        with (
            patch("src.pipeline.smart_scan.apply_known_statuses", return_value=3) as mock_h1b,
            patch.object(orch, "get_smart_portal_list", return_value=["wellfound"]),
            patch("src.pipeline.orchestrator.Pipeline.scan_all", new_callable=AsyncMock, return_value={"total_found": 5}),
        ):
            result = asyncio.run(
                orch.run_smart_scan(enrich_h1b=True)
            )
            mock_h1b.assert_called_once_with(session_with_scans)
            assert result["h1b_enriched"] == 3

    def test_h1b_skip_when_disabled(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)

        with (
            patch("src.pipeline.smart_scan.apply_known_statuses") as mock_h1b,
            patch.object(orch, "get_smart_portal_list", return_value=["wellfound"]),
            patch("src.pipeline.orchestrator.Pipeline.scan_all", new_callable=AsyncMock, return_value={"total_found": 5}),
        ):
            result = asyncio.run(
                orch.run_smart_scan(enrich_h1b=False)
            )
            mock_h1b.assert_not_called()
            assert result["h1b_enriched"] == 0

    def test_get_scan_report_structure(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)
        report = orch.get_scan_report()
        assert "scores" in report
        assert "summary" in report
        assert isinstance(report["scores"], list)
        assert "total_portals" in report["summary"]
        assert "promoted" in report["summary"]
        assert "demoted" in report["summary"]
        assert "hold" in report["summary"]
        # Should have 3 portals scored
        assert report["summary"]["total_portals"] == 3

    def test_empty_scans_returns_all(self, session, config_path):
        """No scan history means no demotions — all portals pass through."""
        orch = SmartScanOrchestrator(session, config_path=config_path)
        smart_list = orch.get_smart_portal_list()
        # No scan history = no portals known, returns empty
        assert smart_list == []

    def test_empty_scans_base_portals_pass_through(self, session, config_path):
        """No scan history with explicit base_portals — all pass through."""
        orch = SmartScanOrchestrator(session, config_path=config_path)
        base = ["portal_a", "portal_b"]
        smart_list = orch.get_smart_portal_list(base_portals=base)
        assert smart_list == ["portal_a", "portal_b"]

    def test_scan_report_scores_have_all_fields(self, session_with_scans, config_path):
        orch = SmartScanOrchestrator(session_with_scans, config_path=config_path)
        report = orch.get_scan_report()
        for score_entry in report["scores"]:
            assert "portal" in score_entry
            assert "velocity" in score_entry
            assert "afternoon_delta" in score_entry
            assert "conversion" in score_entry
            assert "total" in score_entry
            assert "recommendation" in score_entry


# ---------------------------------------------------------------------------
# TestPipelineSmartIntegration
# ---------------------------------------------------------------------------


class TestPipelineSmartIntegration:
    def test_smart_true_routes_to_smart_scan(self, session):
        from src.pipeline.orchestrator import Pipeline

        pipeline = Pipeline(session)

        with patch.object(
            pipeline, "scan_smart", new_callable=AsyncMock, return_value={"smart": True}
        ) as mock_smart:
            result = pipeline.run(
                scan=True, smart=True, validate=False, score=False
            )
            mock_smart.assert_called_once()
            assert result["scan"] == {"smart": True}

    def test_smart_false_uses_regular(self, session):
        from src.pipeline.orchestrator import Pipeline

        pipeline = Pipeline(session)

        with patch.object(
            pipeline, "scan_all", new_callable=AsyncMock, return_value={"regular": True}
        ) as mock_scan:
            result = pipeline.run(
                scan=True, smart=False, validate=False, score=False
            )
            mock_scan.assert_called_once()
            assert result["scan"] == {"regular": True}

    def test_run_with_smart_flag(self, session):
        from src.pipeline.orchestrator import Pipeline

        pipeline = Pipeline(session)

        mock_result = {
            "scan_results": {"total_found": 10},
            "skipped_portals": [],
            "h1b_enriched": 0,
            "portal_scores": {},
        }
        with patch.object(
            pipeline, "scan_smart", new_callable=AsyncMock, return_value=mock_result
        ):
            result = pipeline.run(
                scan=True, smart=True, validate=False, score=False
            )
            assert "scan" in result
            assert result["scan"]["scan_results"]["total_found"] == 10
            assert result["scan"]["h1b_enriched"] == 0

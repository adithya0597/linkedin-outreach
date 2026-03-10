"""Tests for outreach stage sync to Notion."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from src.db.orm import CompanyORM, OutreachORM
from src.integrations.outreach_sync import STAGE_MAPPING, OutreachNotionSync


def _make_company(session, name):
    c = CompanyORM(name=name, tier="Tier 1 - HIGH")
    session.add(c)
    session.flush()
    return c


def _make_outreach(session, company, stage="Sent", step="connection_request", sent_at=None):
    o = OutreachORM(
        company_id=company.id,
        company_name=company.name,
        stage=stage,
        sequence_step=step,
        sent_at=sent_at or datetime.now(),
    )
    session.add(o)
    session.flush()
    return o


class TestStageMapping:
    def test_sent_maps_to_applied(self):
        assert STAGE_MAPPING["Sent"] == "Applied"

    def test_responded_maps_to_applied(self):
        assert STAGE_MAPPING["Responded"] == "Applied"


class TestGetOutreachByCompany:
    def test_excludes_not_started(self, session):
        c = _make_company(session, "AlphaCo")
        _make_outreach(session, c, stage="Not Started")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        grouped = sync._get_outreach_by_company()
        assert len(grouped) == 0

    def test_includes_sent_records(self, session):
        c = _make_company(session, "BetaCo")
        _make_outreach(session, c, stage="Sent")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        grouped = sync._get_outreach_by_company()
        assert "BetaCo" in grouped
        assert len(grouped["BetaCo"]) == 1


class TestGetBestStage:
    def test_responded_beats_sent(self, session):
        c = _make_company(session, "GammaCo")
        _make_outreach(session, c, stage="Sent", step="connection_request")
        _make_outreach(session, c, stage="Responded", step="follow_up")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        grouped = sync._get_outreach_by_company()
        best = sync._get_best_stage(grouped["GammaCo"])
        assert best == "Responded"

    def test_sent_only(self, session):
        c = _make_company(session, "DeltaCo")
        _make_outreach(session, c, stage="Sent")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        grouped = sync._get_outreach_by_company()
        best = sync._get_best_stage(grouped["DeltaCo"])
        assert best == "Sent"


class TestSyncDryRun:
    def test_dry_run_returns_counts_no_api_calls(self, session):
        c1 = _make_company(session, "EpsilonCo")
        _make_outreach(session, c1, stage="Sent")
        c2 = _make_company(session, "ZetaCo")
        _make_outreach(session, c2, stage="Responded")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        # Mock the CRM to verify no API calls in dry_run
        sync.crm.update_company_stage = AsyncMock()

        result = asyncio.run(sync.sync_all_outreach_stages(dry_run=True))
        assert result["synced"] == 2
        assert result["errors"] == []
        sync.crm.update_company_stage.assert_not_called()


class TestSyncWithMockedNotion:
    def test_sync_calls_notion_api(self, session):
        c = _make_company(session, "EtaCo")
        _make_outreach(session, c, stage="Sent")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        sync.crm.update_company_stage = AsyncMock(return_value="page-id-123")

        result = asyncio.run(sync.sync_all_outreach_stages(dry_run=False))
        assert result["synced"] == 1
        sync.crm.update_company_stage.assert_called_once_with("EtaCo", "Applied")

    def test_sync_handles_not_found(self, session):
        c = _make_company(session, "ThetaCo")
        _make_outreach(session, c, stage="Sent")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        sync.crm.update_company_stage = AsyncMock(return_value=None)

        result = asyncio.run(sync.sync_all_outreach_stages(dry_run=False))
        assert result["skipped"] == 1
        assert result["synced"] == 0

    def test_sync_handles_api_error(self, session):
        c = _make_company(session, "IotaCo")
        _make_outreach(session, c, stage="Sent")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        sync.crm.update_company_stage = AsyncMock(side_effect=Exception("API down"))

        result = asyncio.run(sync.sync_all_outreach_stages(dry_run=False))
        assert len(result["errors"]) == 1
        assert "IotaCo" in result["errors"][0]


class TestSequenceProgress:
    def test_sequence_summary_format(self, session):
        c = _make_company(session, "KappaCo")
        sent_time = datetime(2026, 3, 5, 10, 0, 0)
        _make_outreach(session, c, stage="Sent", step="connection_request", sent_at=sent_time)
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        grouped = sync._get_outreach_by_company()
        summary = sync._build_sequence_summary(grouped["KappaCo"])
        assert "Step 1/1" in summary
        assert "connection_request sent 2026-03-05" in summary

    def test_sequence_progress_dry_run(self, session):
        c = _make_company(session, "LambdaCo")
        _make_outreach(session, c, stage="Sent")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        result = asyncio.run(sync.sync_sequence_progress(dry_run=True))
        assert result["updated"] == 1


class TestSyncReport:
    def test_report_stage_counts(self, session):
        c1 = _make_company(session, "MuCo")
        _make_outreach(session, c1, stage="Sent")
        c2 = _make_company(session, "NuCo")
        _make_outreach(session, c2, stage="Responded")
        c3 = _make_company(session, "XiCo")
        _make_outreach(session, c3, stage="Not Started")
        session.commit()

        sync = OutreachNotionSync("fake-key", "fake-db", session)
        report = sync.generate_sync_report()

        assert report["total_companies"] == 2  # XiCo excluded (Not Started)
        assert report["stage_counts"]["Sent"] == 1
        assert report["stage_counts"]["Responded"] == 1
        assert "MuCo" in report["companies"]
        assert "NuCo" in report["companies"]
        assert "XiCo" not in report["companies"]

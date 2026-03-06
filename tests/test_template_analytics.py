"""Tests for template performance analytics."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.template_analytics import TemplateAnalytics


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def analytics(session):
    return TemplateAnalytics(session)


def _make_company(session, name, tier="Tier 1 - HIGH"):
    c = CompanyORM(name=name, tier=tier)
    session.add(c)
    session.flush()
    return c


def _make_outreach(
    session,
    company,
    template_type="connection_request_a",
    stage="Not Started",
    char_count=200,
    sent_at=None,
    response_at=None,
):
    o = OutreachORM(
        company_id=company.id,
        company_name=company.name,
        template_type=template_type,
        stage=stage,
        character_count=char_count,
        sent_at=sent_at,
        response_at=response_at,
    )
    session.add(o)
    session.flush()
    return o


class TestGetTemplateStats:
    def test_empty_db_returns_empty(self, analytics):
        assert analytics.get_template_stats() == []

    def test_response_rate_calculation(self, session, analytics):
        co = _make_company(session, "TestCo")
        now = datetime.now()
        # 4 sent, 2 responded => 50%
        _make_outreach(session, co, stage="Sent", sent_at=now)
        _make_outreach(session, co, stage="Sent", sent_at=now)
        _make_outreach(session, co, stage="Responded", sent_at=now, response_at=now)
        _make_outreach(session, co, stage="Responded", sent_at=now, response_at=now)
        session.commit()

        stats = analytics.get_template_stats()
        assert len(stats) == 1
        s = stats[0]
        assert s["template"] == "connection_request_a"
        assert s["total_drafted"] == 4
        assert s["total_sent"] == 4  # Sent + Responded both count as sent
        assert s["total_responded"] == 2
        assert s["response_rate"] == 50.0

    def test_zero_sends_no_division_by_zero(self, session, analytics):
        co = _make_company(session, "DraftOnly")
        _make_outreach(session, co, stage="Not Started")
        session.commit()

        stats = analytics.get_template_stats()
        assert len(stats) == 1
        assert stats[0]["response_rate"] == 0.0
        assert stats[0]["total_sent"] == 0

    def test_avg_char_count(self, session, analytics):
        co = _make_company(session, "CharCo")
        _make_outreach(session, co, char_count=100)
        _make_outreach(session, co, char_count=200)
        _make_outreach(session, co, char_count=300)
        session.commit()

        stats = analytics.get_template_stats()
        assert stats[0]["avg_char_count"] == 200.0


class TestGetTemplateComparison:
    def test_no_connection_requests(self, session, analytics):
        co = _make_company(session, "FollowCo")
        _make_outreach(session, co, template_type="follow_up_a", stage="Sent", sent_at=datetime.now())
        session.commit()

        result = analytics.get_template_comparison()
        assert result["best_template"] is None
        assert result["worst_template"] is None
        assert result["templates"] == []
        assert "No connection request data" in result["recommendation"]

    def test_comparison_picks_best_by_rate(self, session, analytics):
        co = _make_company(session, "ABTest")
        now = datetime.now()
        # Template A: 4 sent, 3 responded => 75%
        for _ in range(3):
            _make_outreach(session, co, template_type="connection_request_a", stage="Responded", sent_at=now, response_at=now)
        _make_outreach(session, co, template_type="connection_request_a", stage="Sent", sent_at=now)
        # Template B: 4 sent, 1 responded => 25%
        _make_outreach(session, co, template_type="connection_request_b", stage="Responded", sent_at=now, response_at=now)
        for _ in range(3):
            _make_outreach(session, co, template_type="connection_request_b", stage="Sent", sent_at=now)
        session.commit()

        result = analytics.get_template_comparison()
        assert result["best_template"] == "connection_request_a"
        assert result["worst_template"] == "connection_request_b"
        assert "connection_request_a" in result["recommendation"]

    def test_min_threshold_filtering(self, session, analytics):
        co = _make_company(session, "MinThresh")
        now = datetime.now()
        # Template A: 2 sent (below threshold), 2 responded => 100%
        _make_outreach(session, co, template_type="connection_request_a", stage="Responded", sent_at=now, response_at=now)
        _make_outreach(session, co, template_type="connection_request_a", stage="Responded", sent_at=now, response_at=now)
        # Template B: 1 sent (below threshold)
        _make_outreach(session, co, template_type="connection_request_b", stage="Sent", sent_at=now)
        session.commit()

        result = analytics.get_template_comparison()
        assert "Insufficient data" in result["recommendation"]
        # Still picks best/worst from available data
        assert result["best_template"] is not None
        assert result["worst_template"] is not None


class TestGetTierTemplateStats:
    def test_tier_breakdown_groups_correctly(self, session, analytics):
        t1_co = _make_company(session, "Tier1Co", tier="Tier 1 - HIGH")
        t2_co = _make_company(session, "Tier2Co", tier="Tier 2 - MEDIUM")
        now = datetime.now()
        _make_outreach(session, t1_co, stage="Sent", sent_at=now)
        _make_outreach(session, t1_co, stage="Responded", sent_at=now, response_at=now)
        _make_outreach(session, t2_co, stage="Sent", sent_at=now)
        session.commit()

        result = analytics.get_tier_template_stats()
        assert "Tier 1 - HIGH" in result
        assert "Tier 2 - MEDIUM" in result
        t1 = result["Tier 1 - HIGH"]["connection_request_a"]
        assert t1["sent"] == 2
        assert t1["responded"] == 1
        assert t1["rate"] == 50.0
        t2 = result["Tier 2 - MEDIUM"]["connection_request_a"]
        assert t2["sent"] == 1
        assert t2["responded"] == 0
        assert t2["rate"] == 0.0


class TestGetWeeklyTrends:
    def test_weekly_trends_groups_by_week(self, session, analytics):
        co = _make_company(session, "WeekCo")
        # This week
        now = datetime.now()
        _make_outreach(session, co, stage="Sent", sent_at=now)
        _make_outreach(session, co, stage="Responded", sent_at=now, response_at=now)
        # Last week
        last_week = now - timedelta(days=7)
        _make_outreach(session, co, stage="Sent", sent_at=last_week)
        session.commit()

        trends = analytics.get_weekly_trends(weeks=4)
        assert len(trends) >= 1  # At least this week
        # All entries should have required keys
        for t in trends:
            assert "week_start" in t
            assert "total_sent" in t
            assert "total_responded" in t
            assert "rate" in t
            assert "top_template" in t

    def test_empty_weekly_trends(self, analytics):
        assert analytics.get_weekly_trends() == []


class TestExportReport:
    def test_report_includes_all_sections(self, session, analytics):
        co = _make_company(session, "ReportCo")
        now = datetime.now()
        _make_outreach(
            session,
            co,
            template_type="connection_request_a",
            stage="Sent",
            sent_at=now,
        )
        session.commit()

        report = analytics.export_report()
        assert "# Template Analytics Report" in report
        assert "## Template Performance" in report
        assert "## Connection Request Comparison" in report
        assert "## Tier x Template Breakdown" in report
        assert "## Weekly Trends" in report

    def test_empty_report(self, analytics):
        report = analytics.export_report()
        assert "# Template Analytics Report" in report
        assert "No outreach data available." in report

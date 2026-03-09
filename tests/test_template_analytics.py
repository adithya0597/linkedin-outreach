"""Tests for template performance analytics, including day-of-week analysis,
character count correlation, and CSV export."""

from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime, timedelta

import pytest

from src.db.orm import CompanyORM, OutreachORM
from src.outreach.template_analytics import TemplateAnalytics


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


# ---------------------------------------------------------------------------
# V2 Tests: day-of-week analysis, char count correlation, CSV export
# ---------------------------------------------------------------------------


def _seed_outreach(session, company_name="TestCo", template="connection_request_a.j2",
                   stage="Sent", sent_at=None, char_count=250):
    company = session.query(CompanyORM).filter_by(name=company_name).first()
    if not company:
        company = CompanyORM(name=company_name, tier="Tier 2")
        session.add(company)
        session.flush()
    record = OutreachORM(
        company_id=company.id,
        company_name=company_name,
        template_type=template,
        stage=stage,
        sent_at=sent_at or datetime.now(),
        character_count=char_count,
    )
    session.add(record)
    session.commit()
    return record


class TestDayOfWeekAnalysis:
    def test_returns_correct_days(self, session):
        """Day of week analysis returns data grouped by weekday."""
        # 2026-03-02 is a Monday
        monday = datetime(2026, 3, 2, 10, 0, 0)
        tuesday = datetime(2026, 3, 3, 10, 0, 0)
        _seed_outreach(session, sent_at=monday, stage="Sent")
        _seed_outreach(session, sent_at=monday, stage="Responded")
        _seed_outreach(session, sent_at=tuesday, stage="Sent")

        analytics = TemplateAnalytics(session)
        result = analytics.get_day_of_week_analysis()

        assert len(result) == 2
        mon = next(r for r in result if r["day"] == "Monday")
        assert mon["total_sent"] == 2
        assert mon["total_responded"] == 1
        assert mon["response_rate"] == 50.0

    def test_empty_db(self, session):
        """Empty database returns empty list."""
        analytics = TemplateAnalytics(session)
        result = analytics.get_day_of_week_analysis()
        assert result == []


class TestCharCountCorrelation:
    def test_buckets(self, session):
        """Character count correlation correctly buckets by char count."""
        _seed_outreach(session, char_count=50, stage="Responded")
        _seed_outreach(session, char_count=150, stage="Sent")
        _seed_outreach(session, char_count=250, stage="Sent")
        _seed_outreach(session, char_count=350, stage="Responded")
        _seed_outreach(session, char_count=450, stage="Sent")

        analytics = TemplateAnalytics(session)
        result = analytics.get_char_count_correlation()

        buckets = {r["bucket"]: r for r in result}
        assert "0-100" in buckets
        assert buckets["0-100"]["total_sent"] == 1
        assert buckets["0-100"]["response_rate"] == 100.0
        assert "400+" in buckets

    def test_empty_db(self, session):
        """Empty database returns empty list for char count correlation."""
        analytics = TemplateAnalytics(session)
        result = analytics.get_char_count_correlation()
        assert result == []


class TestExportCSV:
    def test_creates_file(self, session):
        """export_csv creates a valid CSV file with correct headers."""
        _seed_outreach(session, template="connection_request_a.j2")
        _seed_outreach(session, template="follow_up_a.j2")

        analytics = TemplateAnalytics(session)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            path = f.name

        try:
            count = analytics.export_csv(path)
            assert count == 2

            with open(path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 2
            assert "template" in rows[0]
            assert "response_rate" in rows[0]
        finally:
            os.unlink(path)


class TestWeeklyTrendsConfigurable:
    def test_configurable_weeks(self, session):
        """get_weekly_trends(weeks=N) uses the correct cutoff."""
        # Seed a record 2 weeks ago
        two_weeks_ago = datetime.now() - timedelta(weeks=2)
        _seed_outreach(session, sent_at=two_weeks_ago)

        analytics = TemplateAnalytics(session)

        # With 4 weeks window, should include it
        result_4 = analytics.get_weekly_trends(weeks=4)
        assert len(result_4) >= 1

        # With 1 week window, should exclude it
        result_1 = analytics.get_weekly_trends(weeks=1)
        assert len(result_1) == 0

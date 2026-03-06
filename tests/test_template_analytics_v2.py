"""Tests for Template Analytics v2: day-of-week, char count correlation, CSV export."""

from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.template_analytics import TemplateAnalytics


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


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


def test_day_of_week_analysis_returns_correct_days(session):
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


def test_day_of_week_empty_db(session):
    """Empty database returns empty list."""
    analytics = TemplateAnalytics(session)
    result = analytics.get_day_of_week_analysis()
    assert result == []


def test_char_count_correlation_buckets(session):
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


def test_char_count_empty_db(session):
    """Empty database returns empty list for char count correlation."""
    analytics = TemplateAnalytics(session)
    result = analytics.get_char_count_correlation()
    assert result == []


def test_export_csv_creates_file(session):
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


def test_weekly_trends_configurable_weeks(session):
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

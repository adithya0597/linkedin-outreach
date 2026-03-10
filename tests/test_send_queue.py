"""Tests for SendQueueManager — daily send queue with rate limiting."""

from datetime import datetime, timedelta

from src.db.orm import CompanyORM, ContactORM, OutreachORM
from src.outreach.send_queue import WEEKLY_SEND_LIMIT, SendQueueManager


def _make_company(session, name, fit_score=80.0, tier="Tier 1 - HIGH", is_disqualified=False, careers_url="", linkedin_url=""):
    c = CompanyORM(
        name=name,
        fit_score=fit_score,
        tier=tier,
        is_disqualified=is_disqualified,
        careers_url=careers_url,
        linkedin_url=linkedin_url,
    )
    session.add(c)
    session.flush()
    return c


def _make_contact(session, name, company, contact_score=50.0, linkedin_url=""):
    ct = ContactORM(
        name=name,
        company_id=company.id,
        company_name=company.name,
        contact_score=contact_score,
        linkedin_url=linkedin_url,
    )
    session.add(ct)
    session.flush()
    return ct


def _make_outreach(session, company, stage="Not Started", sent_at=None, contact_name="Test Contact"):
    o = OutreachORM(
        company_id=company.id,
        company_name=company.name,
        contact_name=contact_name,
        stage=stage,
        sent_at=sent_at,
        template_type="connection_request_a.j2",
        content="Test message",
        character_count=50,
    )
    session.add(o)
    session.flush()
    return o


class TestGenerateDailyQueue:
    def test_sorted_by_fit_score_desc(self, session):
        """Queue items are returned sorted by fit_score descending."""
        c1 = _make_company(session, "LowFit Co", fit_score=60.0)
        c2 = _make_company(session, "HighFit Co", fit_score=95.0)
        c3 = _make_company(session, "MidFit Co", fit_score=80.0)
        _make_outreach(session, c1)
        _make_outreach(session, c2)
        _make_outreach(session, c3)
        session.commit()

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue()

        scores = [item["fit_score"] for item in queue]
        assert scores == [95.0, 80.0, 60.0]

    def test_respects_max_sends_limit(self, session):
        """Queue respects the max_sends parameter."""
        for i in range(5):
            c = _make_company(session, f"Company {i}", fit_score=80.0 + i)
            _make_outreach(session, c)
        session.commit()

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue(max_sends=2)

        assert len(queue) == 2

    def test_only_includes_not_started(self, session):
        """Queue only includes outreach with stage='Not Started'."""
        c1 = _make_company(session, "NotStarted Co", fit_score=90.0)
        c2 = _make_company(session, "Sent Co", fit_score=85.0)
        c3 = _make_company(session, "Responded Co", fit_score=80.0)
        _make_outreach(session, c1, stage="Not Started")
        _make_outreach(session, c2, stage="Sent", sent_at=datetime.now())
        _make_outreach(session, c3, stage="Responded")
        session.commit()

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue()

        assert len(queue) == 1
        assert queue[0]["company_name"] == "NotStarted Co"

    def test_empty_when_weekly_limit_hit(self, session):
        """Queue returns empty list when weekly send limit is reached."""
        now = datetime.now()
        for i in range(WEEKLY_SEND_LIMIT):
            c = _make_company(session, f"Sent Company {i}", fit_score=50.0)
            _make_outreach(session, c, stage="Sent", sent_at=now)
        # Also add a Not Started record that should NOT appear
        pending_co = _make_company(session, "Pending Co", fit_score=99.0)
        _make_outreach(session, pending_co, stage="Not Started")
        session.commit()

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue()

        assert queue == []

    def test_skips_disqualified_companies(self, session):
        """Queue skips companies where is_disqualified=True."""
        c1 = _make_company(session, "Good Co", fit_score=90.0, is_disqualified=False)
        c2 = _make_company(session, "Bad Co", fit_score=95.0, is_disqualified=True)
        _make_outreach(session, c1)
        _make_outreach(session, c2)
        session.commit()

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue()

        assert len(queue) == 1
        assert queue[0]["company_name"] == "Good Co"


class TestGetRateLimitStatus:
    def test_accurate_weekly_count(self, session):
        """Rate limit status accurately counts this week's sends."""
        now = datetime.now()
        # 3 sent this week
        for i in range(3):
            c = _make_company(session, f"Sent {i}", fit_score=50.0)
            _make_outreach(session, c, stage="Sent", sent_at=now)
        # 1 sent last week (should not count)
        old = _make_company(session, "Old Send", fit_score=50.0)
        _make_outreach(session, old, stage="Sent", sent_at=now - timedelta(days=10))
        session.commit()

        mgr = SendQueueManager(session)
        status = mgr.get_rate_limit_status()

        assert status["sent_this_week"] == 3
        assert status["limit"] == WEEKLY_SEND_LIMIT
        assert status["remaining"] == WEEKLY_SEND_LIMIT - 3


class TestGetLinkedInActions:
    def test_returns_urls_when_present(self, session):
        """Returns profile and careers URLs when company/contact have them."""
        c = _make_company(
            session,
            "URL Co",
            careers_url="https://urlco.com/careers",
            linkedin_url="https://linkedin.com/company/urlco",
        )
        _make_contact(
            session,
            "Jane Doe",
            c,
            contact_score=80.0,
            linkedin_url="https://linkedin.com/in/janedoe",
        )
        session.commit()

        mgr = SendQueueManager(session)
        actions = mgr.get_linkedin_actions("URL Co")

        assert actions["profile_url"] == "https://linkedin.com/in/janedoe"
        assert actions["careers_url"] == "https://urlco.com/careers"

    def test_returns_none_when_urls_missing(self, session):
        """Returns None for URLs when company/contact don't have them."""
        _make_company(session, "No URL Co")
        session.commit()

        mgr = SendQueueManager(session)
        actions = mgr.get_linkedin_actions("No URL Co")

        assert actions["profile_url"] is None
        assert actions["careers_url"] is None
        assert actions["connect_url"] is None
        assert actions["message_url"] is None

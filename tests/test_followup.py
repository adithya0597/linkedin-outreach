"""Tests for follow-up manager and sequence tracker."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.followup_manager import FollowUpManager
from src.outreach.sequence_tracker import SequenceTracker


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
def company(session):
    """A basic Tier 1 company."""
    c = CompanyORM(name="TestCorp", tier="Tier 1 - HIGH")
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def company_with_sent(session, company):
    """Company with a connection_request sent 10 days ago."""
    record = OutreachORM(
        company_id=company.id,
        company_name="TestCorp",
        contact_name="Jane Doe",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=10),
        sequence_step="connection_request",
    )
    session.add(record)
    session.commit()
    return company


@pytest.fixture
def company_with_recent_sent(session, company):
    """Company with a connection_request sent 1 day ago (within grace)."""
    record = OutreachORM(
        company_id=company.id,
        company_name="TestCorp",
        contact_name="Jane Doe",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=1),
        sequence_step="connection_request",
    )
    session.add(record)
    session.commit()
    return company


# ---------------------------------------------------------------------------
# TestFollowUpManager
# ---------------------------------------------------------------------------

class TestFollowUpManager:
    def test_empty_when_no_sent(self, session):
        """No sent records -> empty overdue list."""
        mgr = FollowUpManager(session)
        assert mgr.get_overdue_followups() == []

    def test_detects_overdue(self, session, company_with_sent):
        """Record sent 10 days ago with no follow-up -> overdue."""
        mgr = FollowUpManager(session)
        overdue = mgr.get_overdue_followups()
        assert len(overdue) == 1
        assert overdue[0]["company_name"] == "TestCorp"
        assert overdue[0]["last_step"] == "connection_request"
        assert overdue[0]["next_step"] == "follow_up"
        assert overdue[0]["days_overdue"] >= 5  # 10 - (3 gap + 2 grace)

    def test_not_overdue_within_grace(self, session, company_with_recent_sent):
        """Recently sent record should not be flagged as overdue."""
        mgr = FollowUpManager(session)
        overdue = mgr.get_overdue_followups()
        assert len(overdue) == 0

    def test_pending_within_window(self, session, company):
        """Follow-up due within 3 days returned by get_pending_followups."""
        # Sent 2 days ago -> follow_up due at day 3 -> 1 day from now
        record = OutreachORM(
            company_id=company.id,
            company_name="TestCorp",
            contact_name="Jane Doe",
            stage="Sent",
            sent_at=datetime.now() - timedelta(days=2),
            sequence_step="connection_request",
        )
        session.add(record)
        session.commit()

        mgr = FollowUpManager(session)
        pending = mgr.get_pending_followups(days_ahead=3)
        assert len(pending) == 1
        assert pending[0]["company_name"] == "TestCorp"
        assert pending[0]["step"] == "follow_up"

    def test_daily_alert_structure(self, session, company_with_sent):
        """Daily alert has required keys."""
        mgr = FollowUpManager(session)
        alert = mgr.generate_daily_alert()
        assert "overdue" in alert
        assert "due_today" in alert
        assert "due_this_week" in alert
        assert "total_active_sequences" in alert
        assert alert["total_active_sequences"] >= 1

    def test_next_template_suggestion(self, session):
        """Correct template for each step."""
        mgr = FollowUpManager(session)
        assert mgr.suggest_next_template("X", "pre_engagement") == "connection_request_a.j2"
        assert mgr.suggest_next_template("X", "connection_request") == "follow_up_a.j2"
        assert mgr.suggest_next_template("X", "follow_up") == "follow_up_b.j2"
        assert mgr.suggest_next_template("X", "deeper_engagement") == "inmail_a.j2"
        # Unknown step falls back
        assert mgr.suggest_next_template("X", "unknown") == "follow_up_a.j2"

    def test_already_followed_up_not_overdue(self, session, company_with_sent):
        """If next step already sent, not overdue."""
        # Add a follow_up that's already Sent
        follow_up = OutreachORM(
            company_id=company_with_sent.id,
            company_name="TestCorp",
            contact_name="Jane Doe",
            stage="Sent",
            sent_at=datetime.now() - timedelta(days=5),
            sequence_step="follow_up",
        )
        session.add(follow_up)
        session.commit()

        mgr = FollowUpManager(session)
        overdue = mgr.get_overdue_followups()
        # connection_request->follow_up should NOT be overdue since follow_up exists
        cr_overdue = [o for o in overdue if o["last_step"] == "connection_request"]
        assert len(cr_overdue) == 0


# ---------------------------------------------------------------------------
# TestSequenceTracker
# ---------------------------------------------------------------------------

class TestSequenceTracker:
    def test_mark_sent_updates_stage(self, session, company):
        """Stage changes to Sent when marking sent."""
        # Create a draft first
        draft = OutreachORM(
            company_id=company.id,
            company_name="TestCorp",
            contact_name="Jane Doe",
            stage="Not Started",
            sequence_step="connection_request",
        )
        session.add(draft)
        session.commit()

        tracker = SequenceTracker(session)
        result = tracker.mark_sent("TestCorp", "connection_request")
        assert result is not None
        assert result.stage == "Sent"

    def test_mark_sent_creates_if_no_draft(self, session, company):
        """Creates new record when no draft exists."""
        tracker = SequenceTracker(session)
        result = tracker.mark_sent("TestCorp", "follow_up", contact_name="Jane Doe")
        assert result is not None
        assert result.stage == "Sent"
        assert result.company_name == "TestCorp"
        assert result.sequence_step == "follow_up"

    def test_mark_sent_sets_sent_at(self, session, company):
        """sent_at populated with current time."""
        tracker = SequenceTracker(session)
        before = datetime.now()
        result = tracker.mark_sent("TestCorp", "connection_request")
        after = datetime.now()
        assert result is not None
        assert result.sent_at is not None
        assert before <= result.sent_at <= after

    def test_mark_responded_updates_stage(self, session, company):
        """Stage changes to Responded."""
        tracker = SequenceTracker(session)
        tracker.mark_sent("TestCorp", "connection_request", contact_name="Jane Doe")
        result = tracker.mark_responded("TestCorp", response_text="Interested!")
        assert result is not None
        assert result.stage == "Responded"
        assert result.response_text == "Interested!"

    def test_mark_responded_sets_response_at(self, session, company):
        """response_at populated with current time."""
        tracker = SequenceTracker(session)
        tracker.mark_sent("TestCorp", "connection_request")
        before = datetime.now()
        result = tracker.mark_responded("TestCorp")
        after = datetime.now()
        assert result is not None
        assert result.response_at is not None
        assert before <= result.response_at <= after

    def test_sequence_status_shows_progress(self, session, company):
        """Completed/remaining steps are correct."""
        tracker = SequenceTracker(session)
        tracker.mark_sent("TestCorp", "pre_engagement")
        tracker.mark_sent("TestCorp", "connection_request")

        status = tracker.get_sequence_status("TestCorp")
        assert status["company"] == "TestCorp"
        assert "pre_engagement" in status["steps_completed"]
        assert "connection_request" in status["steps_completed"]
        assert "follow_up" in status["steps_remaining"]
        assert status["total_sent"] == 2
        assert status["has_response"] is False

    def test_active_sequences_with_remaining(self, session, company):
        """Only incomplete sequences returned."""
        tracker = SequenceTracker(session)
        tracker.mark_sent("TestCorp", "connection_request")

        active = tracker.get_all_active_sequences()
        assert len(active) == 1
        assert active[0]["company"] == "TestCorp"
        assert len(active[0]["steps_remaining"]) > 0

    def test_unknown_company_returns_none(self, session):
        """mark_sent for unknown company returns None."""
        tracker = SequenceTracker(session)
        result = tracker.mark_sent("NonExistentCorp", "connection_request")
        assert result is None

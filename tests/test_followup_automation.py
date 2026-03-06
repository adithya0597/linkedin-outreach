"""Tests for follow-up automation: auto_draft_followups and queue_followups."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.followup_manager import FollowUpManager


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
    c = CompanyORM(name="AlphaCorp", tier="Tier 1 - HIGH")
    session.add(c)
    session.flush()
    return c


def _make_overdue(session, company, step="connection_request", days_ago=10):
    """Helper: create a Sent outreach record that is overdue for follow-up."""
    record = OutreachORM(
        company_id=company.id,
        company_name=company.name,
        contact_name="Jane Doe",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=days_ago),
        sequence_step=step,
    )
    session.add(record)
    session.commit()
    return record


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAutoDraftFollowups:
    def test_creates_drafts_for_overdue_items(self, session, company):
        """auto_draft_followups creates a draft OutreachORM for each overdue item."""
        _make_overdue(session, company, step="connection_request", days_ago=10)

        mgr = FollowUpManager(session)
        result = mgr.auto_draft_followups()

        assert result["drafted"] == 1
        assert result["skipped_duplicates"] == 0
        assert result["errors"] == []

        # Verify the draft record exists in the database
        draft = (
            session.query(OutreachORM)
            .filter(
                OutreachORM.company_name == "AlphaCorp",
                OutreachORM.sequence_step == "follow_up",
                OutreachORM.stage == "Not Started",
            )
            .first()
        )
        assert draft is not None
        assert draft.contact_name == "Jane Doe"
        assert draft.template_type == "follow_up_a.j2"

    def test_duplicate_drafts_are_skipped(self, session, company):
        """If a draft already exists for the same company + step, it is skipped."""
        _make_overdue(session, company, step="connection_request", days_ago=10)

        mgr = FollowUpManager(session)

        # First call creates the draft
        result1 = mgr.auto_draft_followups()
        assert result1["drafted"] == 1

        # Second call skips the duplicate
        result2 = mgr.auto_draft_followups()
        assert result2["drafted"] == 0
        assert result2["skipped_duplicates"] == 1

    def test_max_drafts_limit_is_respected(self, session):
        """max_drafts caps the number of drafts created."""
        # Create 3 companies with overdue follow-ups
        for i in range(3):
            c = CompanyORM(name=f"Corp{i}", tier="Tier 1 - HIGH")
            session.add(c)
            session.flush()
            _make_overdue(session, c, step="connection_request", days_ago=10)

        mgr = FollowUpManager(session)
        result = mgr.auto_draft_followups(max_drafts=2)

        assert result["drafted"] == 2
        assert result["errors"] == []

    def test_empty_overdue_produces_zero_drafts(self, session):
        """When no items are overdue, 0 drafts are created."""
        mgr = FollowUpManager(session)
        result = mgr.auto_draft_followups()

        assert result["drafted"] == 0
        assert result["skipped_duplicates"] == 0
        assert result["errors"] == []

    def test_return_dict_has_correct_keys(self, session):
        """Return dict always has drafted, skipped_duplicates, errors."""
        mgr = FollowUpManager(session)
        result = mgr.auto_draft_followups()

        assert "drafted" in result
        assert "skipped_duplicates" in result
        assert "errors" in result
        assert isinstance(result["drafted"], int)
        assert isinstance(result["skipped_duplicates"], int)
        assert isinstance(result["errors"], list)


class TestQueueFollowups:
    def test_returns_only_followup_steps(self, session, company):
        """queue_followups returns drafts with sequence_step > first step only."""
        # Draft for "follow_up" (step index 2) -> should be included
        follow_up_draft = OutreachORM(
            company_id=company.id,
            company_name="AlphaCorp",
            contact_name="Jane Doe",
            stage="Not Started",
            sequence_step="follow_up",
            template_type="follow_up_a.j2",
            content="Hey Jane, following up on my connection request.",
        )
        # Draft for "pre_engagement" (step index 0) -> should be excluded
        pre_engagement_draft = OutreachORM(
            company_id=company.id,
            company_name="AlphaCorp",
            contact_name="Jane Doe",
            stage="Not Started",
            sequence_step="pre_engagement",
            template_type="connection_request_a.j2",
            content="Liked your post on AI infrastructure.",
        )
        session.add_all([follow_up_draft, pre_engagement_draft])
        session.commit()

        mgr = FollowUpManager(session)
        queued = mgr.queue_followups()

        assert len(queued) == 1
        assert queued[0]["company_name"] == "AlphaCorp"
        assert queued[0]["sequence_step"] == "follow_up"
        assert queued[0]["contact_name"] == "Jane Doe"
        assert queued[0]["template_type"] == "follow_up_a.j2"
        assert queued[0]["content"] == "Hey Jane, following up on my connection request."

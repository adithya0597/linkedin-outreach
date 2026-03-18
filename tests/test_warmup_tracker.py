"""Tests for the warm-up sequence tracker.

Covers: enums, state transitions, action recording, scheduling logic,
ready contacts, daily actions, edge cases.
"""

from __future__ import annotations

import pytest

from src.db.orm import CompanyORM, WarmUpActionORM, WarmUpSequenceORM
from src.outreach.warmup_tracker import (
    REQUIRED_WARMUP_ACTIONS,
    VALID_WARMUP_TRANSITIONS,
    InvalidWarmUpTransitionError,
    WarmUpAction,
    WarmUpState,
    WarmUpTracker,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tracker(session):
    """Return a WarmUpTracker bound to the test session."""
    return WarmUpTracker(session)


@pytest.fixture()
def seed_company(session) -> CompanyORM:
    """Seed a single company and return it."""
    company = CompanyORM(name="Snorkel AI")
    session.add(company)
    session.commit()
    return company


@pytest.fixture()
def seed_two_companies(session) -> tuple[CompanyORM, CompanyORM]:
    """Seed two companies for multi-company tests."""
    c1 = CompanyORM(name="LlamaIndex")
    c2 = CompanyORM(name="LangChain")
    session.add_all([c1, c2])
    session.commit()
    return c1, c2


# ---------------------------------------------------------------------------
# 1. Enum value tests
# ---------------------------------------------------------------------------


class TestWarmUpActionEnum:
    def test_profile_view_value(self):
        assert WarmUpAction.PROFILE_VIEW.value == "PROFILE_VIEW"

    def test_like_post_value(self):
        assert WarmUpAction.LIKE_POST.value == "LIKE_POST"

    def test_comment_value(self):
        assert WarmUpAction.COMMENT.value == "COMMENT"

    def test_connect_value(self):
        assert WarmUpAction.CONNECT.value == "CONNECT"

    def test_message_value(self):
        assert WarmUpAction.MESSAGE.value == "MESSAGE"

    def test_all_actions_count(self):
        assert len(WarmUpAction) == 5

    def test_string_enum_roundtrip(self):
        for action in WarmUpAction:
            assert WarmUpAction(action.value) == action


class TestWarmUpStateEnum:
    def test_pending_value(self):
        assert WarmUpState.PENDING.value == "PENDING"

    def test_warming_value(self):
        assert WarmUpState.WARMING.value == "WARMING"

    def test_ready_value(self):
        assert WarmUpState.READY.value == "READY"

    def test_sent_value(self):
        assert WarmUpState.SENT.value == "SENT"

    def test_all_states_count(self):
        assert len(WarmUpState) == 4


# ---------------------------------------------------------------------------
# 2. Transition graph tests
# ---------------------------------------------------------------------------


class TestTransitionGraph:
    def test_pending_can_go_to_warming(self):
        assert WarmUpState.WARMING in VALID_WARMUP_TRANSITIONS[WarmUpState.PENDING]

    def test_pending_cannot_go_to_ready_directly(self):
        assert WarmUpState.READY not in VALID_WARMUP_TRANSITIONS[WarmUpState.PENDING]

    def test_warming_can_go_to_ready(self):
        assert WarmUpState.READY in VALID_WARMUP_TRANSITIONS[WarmUpState.WARMING]

    def test_ready_can_go_to_sent(self):
        assert WarmUpState.SENT in VALID_WARMUP_TRANSITIONS[WarmUpState.READY]

    def test_sent_is_terminal(self):
        assert VALID_WARMUP_TRANSITIONS[WarmUpState.SENT] == set()

    def test_no_backward_transitions(self):
        """No state should allow going back to PENDING."""
        for state in WarmUpState:
            if state == WarmUpState.PENDING:
                continue
            allowed = VALID_WARMUP_TRANSITIONS.get(state, set())
            assert WarmUpState.PENDING not in allowed


# ---------------------------------------------------------------------------
# 3. record_action tests
# ---------------------------------------------------------------------------


class TestRecordAction:
    def test_first_action_creates_sequence_in_warming(self, tracker, seed_company, session):
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        seq = (
            session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.company_id == seed_company.id)
            .first()
        )
        assert seq is not None
        assert seq.state == WarmUpState.WARMING.value

    def test_action_orm_created(self, tracker, seed_company, session):
        record = tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        assert record.id is not None
        assert record.action_type == WarmUpAction.PROFILE_VIEW.value
        assert record.contact_name == "Jane Smith"
        assert record.company_id == seed_company.id

    def test_notes_stored(self, tracker, seed_company, session):
        record = tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.LIKE_POST,
            notes="Liked their latest ML pipeline post"
        )
        assert record.notes == "Liked their latest ML pipeline post"

    def test_second_action_same_contact_stays_warming(self, tracker, seed_company, session):
        """If not all required actions done, state stays WARMING."""
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        # COMMENT is not a required action, so still WARMING
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.COMMENT
        )
        seq = (
            session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.company_id == seed_company.id)
            .first()
        )
        assert seq.state == WarmUpState.WARMING.value

    def test_all_required_actions_transitions_to_ready(self, tracker, seed_company, session):
        """Completing all required actions auto-transitions to READY."""
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        seq = (
            session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.company_id == seed_company.id)
            .first()
        )
        assert seq.state == WarmUpState.READY.value

    def test_action_after_sent_raises(self, tracker, seed_company, session):
        """Cannot record actions once the sequence is in SENT state."""
        # Complete warmup and mark sent
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        tracker.mark_sent(seed_company.id, "Jane Smith")

        with pytest.raises(InvalidWarmUpTransitionError, match="SENT"):
            tracker.record_action(
                seed_company.id, "Jane Smith", WarmUpAction.COMMENT
            )

    def test_invalid_company_raises(self, tracker):
        with pytest.raises(ValueError, match="Company not found"):
            tracker.record_action(
                9999, "Nobody", WarmUpAction.PROFILE_VIEW
            )

    def test_duplicate_action_type_idempotent_state(self, tracker, seed_company, session):
        """Recording the same action type twice should not break state."""
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        # Should have two action records but still WARMING (only PROFILE_VIEW done)
        count = (
            session.query(WarmUpActionORM)
            .filter(WarmUpActionORM.company_id == seed_company.id)
            .count()
        )
        assert count == 2
        seq = (
            session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.company_id == seed_company.id)
            .first()
        )
        assert seq.state == WarmUpState.WARMING.value

    def test_extra_actions_beyond_required(self, tracker, seed_company, session):
        """Actions beyond the required set still count, state goes READY."""
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.COMMENT
        )
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.LIKE_POST
        )
        seq = (
            session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.company_id == seed_company.id)
            .first()
        )
        assert seq.state == WarmUpState.READY.value


# ---------------------------------------------------------------------------
# 4. get_status tests
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_no_sequence_returns_pending(self, tracker, seed_company):
        status = tracker.get_status(seed_company.id, "Unknown Person")
        assert status["state"] == WarmUpState.PENDING.value
        assert status["completed_actions"] == []
        assert status["action_count"] == 0
        assert status["is_ready"] is False

    def test_status_after_one_action(self, tracker, seed_company):
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        status = tracker.get_status(seed_company.id, "Jane Smith")
        assert status["state"] == WarmUpState.WARMING.value
        assert "PROFILE_VIEW" in status["completed_actions"]
        assert status["action_count"] == 1
        assert status["is_ready"] is False

    def test_status_when_ready(self, tracker, seed_company):
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        status = tracker.get_status(seed_company.id, "Jane Smith")
        assert status["state"] == WarmUpState.READY.value
        assert status["remaining_actions"] == []
        assert status["is_ready"] is True

    def test_remaining_actions_correct(self, tracker, seed_company):
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        status = tracker.get_status(seed_company.id, "Jane Smith")
        remaining = status["remaining_actions"]
        assert "PROFILE_VIEW" not in remaining
        assert "LIKE_POST" in remaining


# ---------------------------------------------------------------------------
# 5. get_ready_contacts tests
# ---------------------------------------------------------------------------


class TestGetReadyContacts:
    def test_no_ready_contacts_returns_empty(self, tracker, seed_company):
        assert tracker.get_ready_contacts() == []

    def test_ready_contact_appears(self, tracker, seed_company):
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        ready = tracker.get_ready_contacts()
        assert len(ready) == 1
        assert ready[0]["contact_name"] == "Jane Smith"
        assert ready[0]["company_name"] == "Snorkel AI"
        assert ready[0]["state"] == WarmUpState.READY.value

    def test_sent_contact_does_not_appear(self, tracker, seed_company):
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        tracker.mark_sent(seed_company.id, "Jane Smith")
        assert tracker.get_ready_contacts() == []

    def test_multiple_ready_contacts(self, tracker, seed_two_companies):
        c1, c2 = seed_two_companies
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(c1.id, "John Doe", action)
            tracker.record_action(c2.id, "Alice Johnson", action)
        ready = tracker.get_ready_contacts()
        assert len(ready) == 2
        names = {r["contact_name"] for r in ready}
        assert names == {"John Doe", "Alice Johnson"}

    def test_warming_contact_not_in_ready(self, tracker, seed_company):
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        assert tracker.get_ready_contacts() == []


# ---------------------------------------------------------------------------
# 6. get_daily_actions tests
# ---------------------------------------------------------------------------


class TestGetDailyActions:
    def test_no_sequences_returns_empty(self, tracker):
        assert tracker.get_daily_actions() == []

    def test_pending_sequence_recommends_profile_view(self, tracker, seed_company, session):
        """A PENDING sequence should recommend PROFILE_VIEW first."""
        # Create a sequence manually in PENDING state
        seq = WarmUpSequenceORM(
            company_id=seed_company.id,
            contact_name="Jane Smith",
            state=WarmUpState.PENDING.value,
        )
        session.add(seq)
        session.commit()

        actions = tracker.get_daily_actions()
        assert len(actions) == 1
        assert actions[0]["recommended_action"] == WarmUpAction.PROFILE_VIEW.value
        assert actions[0]["contact_name"] == "Jane Smith"

    def test_warming_sequence_recommends_next_action(self, tracker, seed_company):
        """After PROFILE_VIEW, should recommend LIKE_POST next."""
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        actions = tracker.get_daily_actions()
        assert len(actions) == 1
        assert actions[0]["recommended_action"] == WarmUpAction.LIKE_POST.value

    def test_ready_sequence_no_recommendation(self, tracker, seed_company):
        """READY sequences should not produce recommendations."""
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        actions = tracker.get_daily_actions()
        assert len(actions) == 0

    def test_sent_sequence_no_recommendation(self, tracker, seed_company):
        """SENT sequences should not produce recommendations."""
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        tracker.mark_sent(seed_company.id, "Jane Smith")
        actions = tracker.get_daily_actions()
        assert len(actions) == 0

    def test_multiple_warming_sequences(self, tracker, seed_two_companies):
        c1, c2 = seed_two_companies
        tracker.record_action(c1.id, "John Doe", WarmUpAction.PROFILE_VIEW)
        tracker.record_action(c2.id, "Alice Johnson", WarmUpAction.PROFILE_VIEW)
        actions = tracker.get_daily_actions()
        assert len(actions) == 2
        names = {a["contact_name"] for a in actions}
        assert names == {"John Doe", "Alice Johnson"}


# ---------------------------------------------------------------------------
# 7. mark_sent tests
# ---------------------------------------------------------------------------


class TestMarkSent:
    def test_mark_sent_from_ready(self, tracker, seed_company, session):
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        seq = tracker.mark_sent(seed_company.id, "Jane Smith")
        assert seq.state == WarmUpState.SENT.value

    def test_mark_sent_from_pending_raises(self, tracker, seed_company, session):
        seq = WarmUpSequenceORM(
            company_id=seed_company.id,
            contact_name="Jane Smith",
            state=WarmUpState.PENDING.value,
        )
        session.add(seq)
        session.commit()

        with pytest.raises(InvalidWarmUpTransitionError, match="PENDING"):
            tracker.mark_sent(seed_company.id, "Jane Smith")

    def test_mark_sent_from_warming_raises(self, tracker, seed_company):
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        with pytest.raises(InvalidWarmUpTransitionError, match="WARMING"):
            tracker.mark_sent(seed_company.id, "Jane Smith")

    def test_mark_sent_nonexistent_raises(self, tracker, seed_company):
        with pytest.raises(ValueError, match="No warm-up sequence found"):
            tracker.mark_sent(seed_company.id, "Nobody")

    def test_mark_sent_twice_raises(self, tracker, seed_company):
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        tracker.mark_sent(seed_company.id, "Jane Smith")
        with pytest.raises(InvalidWarmUpTransitionError, match="SENT"):
            tracker.mark_sent(seed_company.id, "Jane Smith")


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_separate_contacts_same_company(self, tracker, seed_company, session):
        """Two contacts at the same company maintain independent sequences."""
        tracker.record_action(
            seed_company.id, "Contact A", WarmUpAction.PROFILE_VIEW
        )
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Contact B", action
            )

        status_a = tracker.get_status(seed_company.id, "Contact A")
        status_b = tracker.get_status(seed_company.id, "Contact B")

        assert status_a["state"] == WarmUpState.WARMING.value
        assert status_b["state"] == WarmUpState.READY.value

    def test_same_contact_different_companies(self, tracker, seed_two_companies, session):
        """Same contact name at different companies = independent sequences."""
        c1, c2 = seed_two_companies
        tracker.record_action(c1.id, "Shared Name", WarmUpAction.PROFILE_VIEW)
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(c2.id, "Shared Name", action)

        status_c1 = tracker.get_status(c1.id, "Shared Name")
        status_c2 = tracker.get_status(c2.id, "Shared Name")

        assert status_c1["state"] == WarmUpState.WARMING.value
        assert status_c2["state"] == WarmUpState.READY.value

    def test_completing_all_actions_at_once(self, tracker, seed_company, session):
        """Recording all required actions in one burst goes PENDING -> WARMING -> READY."""
        for action in REQUIRED_WARMUP_ACTIONS:
            tracker.record_action(
                seed_company.id, "Jane Smith", action
            )
        seq = (
            session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.company_id == seed_company.id)
            .first()
        )
        assert seq.state == WarmUpState.READY.value

    def test_action_count_in_ready_contacts(self, tracker, seed_company):
        """get_ready_contacts should report correct action_count."""
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.COMMENT
        )
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.LIKE_POST
        )
        ready = tracker.get_ready_contacts()
        assert len(ready) == 1
        assert ready[0]["action_count"] == 3

    def test_transition_path_finder(self):
        """Verify the static path finder handles all cases."""
        # Direct neighbor
        path = WarmUpTracker._find_transition_path(
            WarmUpState.PENDING, WarmUpState.WARMING
        )
        assert path == [WarmUpState.WARMING]

        # Multi-hop
        path = WarmUpTracker._find_transition_path(
            WarmUpState.PENDING, WarmUpState.READY
        )
        assert path == [WarmUpState.WARMING, WarmUpState.READY]

        # Full chain
        path = WarmUpTracker._find_transition_path(
            WarmUpState.PENDING, WarmUpState.SENT
        )
        assert path == [WarmUpState.WARMING, WarmUpState.READY, WarmUpState.SENT]

        # Same state
        path = WarmUpTracker._find_transition_path(
            WarmUpState.WARMING, WarmUpState.WARMING
        )
        assert path == []

        # Backward (impossible)
        path = WarmUpTracker._find_transition_path(
            WarmUpState.SENT, WarmUpState.PENDING
        )
        assert path is None

    def test_required_actions_set_immutable_from_outside(self):
        """REQUIRED_WARMUP_ACTIONS should contain PROFILE_VIEW and LIKE_POST."""
        assert WarmUpAction.PROFILE_VIEW in REQUIRED_WARMUP_ACTIONS
        assert WarmUpAction.LIKE_POST in REQUIRED_WARMUP_ACTIONS
        assert len(REQUIRED_WARMUP_ACTIONS) == 2


# ---------------------------------------------------------------------------
# 9. ORM relationship tests
# ---------------------------------------------------------------------------


class TestORMRelationships:
    def test_company_warmup_actions_relationship(self, tracker, seed_company, session):
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        session.refresh(seed_company)
        assert len(seed_company.warmup_actions) == 1
        assert seed_company.warmup_actions[0].action_type == "PROFILE_VIEW"

    def test_company_warmup_sequences_relationship(self, tracker, seed_company, session):
        tracker.record_action(
            seed_company.id, "Jane Smith", WarmUpAction.PROFILE_VIEW
        )
        session.refresh(seed_company)
        assert len(seed_company.warmup_sequences) == 1
        assert seed_company.warmup_sequences[0].contact_name == "Jane Smith"

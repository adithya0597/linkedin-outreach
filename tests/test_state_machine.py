from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.state_machine import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    OutreachStateMachine,
)


@pytest.fixture()
def session():
    """Create an in-memory SQLite database and return a session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture()
def sm(session):
    """Return an OutreachStateMachine bound to the test session."""
    return OutreachStateMachine(session)


@pytest.fixture()
def seed_company(session):
    """Seed a company with an outreach record at 'Not Started'."""
    company = CompanyORM(name="Acme AI")
    session.add(company)
    session.flush()
    outreach = OutreachORM(
        company_id=company.id,
        company_name="Acme AI",
        stage="Not Started",
    )
    session.add(outreach)
    session.commit()
    return outreach


# ---- Test 1: valid transition Not Started -> Sent succeeds ----

def test_valid_transition_not_started_to_sent(session, sm, seed_company):
    result = sm.transition("Acme AI", "Sent")
    assert result.stage == "Sent"
    assert result.sent_at is not None


# ---- Test 2: invalid transition Not Started -> Responded raises ----

def test_invalid_transition_raises(session, sm, seed_company):
    with pytest.raises(InvalidTransitionError):
        sm.transition("Acme AI", "Responded")


# ---- Test 3: can_transition returns correct bool ----

def test_can_transition_returns_correct_bool(session, sm, seed_company):
    assert sm.can_transition("Acme AI", "Sent") is True
    assert sm.can_transition("Acme AI", "Responded") is False


# ---- Test 4: get_available_transitions for Sent ----

def test_available_transitions_sent(session, sm, seed_company):
    sm.transition("Acme AI", "Sent")
    available = sm.get_available_transitions("Acme AI")
    assert available == ["No Answer", "Responded"]


# ---- Test 5: get_available_transitions for Responded ----

def test_available_transitions_responded(session, sm, seed_company):
    sm.transition("Acme AI", "Sent")
    sm.transition("Acme AI", "Responded")
    available = sm.get_available_transitions("Acme AI")
    assert available == ["Declined", "Interview"]


# ---- Test 6: audit trail records each transition with timestamp ----

def test_audit_trail_records_transitions(session, sm, seed_company):
    sm.transition("Acme AI", "Sent")
    trail = sm.get_audit_trail("Acme AI")
    assert len(trail) == 1
    entry = trail[0]
    assert entry["from_stage"] == "Not Started"
    assert entry["to_stage"] == "Sent"
    assert "timestamp" in entry


# ---- Test 7: re-send after No Answer -> Sent allowed ----

def test_resend_after_no_answer(session, sm, seed_company):
    sm.transition("Acme AI", "Sent")
    sm.transition("Acme AI", "No Answer")
    # Re-send should be allowed
    result = sm.transition("Acme AI", "Sent")
    assert result.stage == "Sent"


# ---- Test 8: company not found raises ValueError ----

def test_company_not_found_raises_value_error(session, sm):
    with pytest.raises(ValueError, match="Company not found"):
        sm.transition("NonExistent Corp", "Sent")


# ---- Test 9: metadata stored in audit trail ----

def test_metadata_stored_in_audit_trail(session, sm, seed_company):
    meta = {"channel": "LinkedIn", "template": "T3"}
    sm.transition("Acme AI", "Sent", metadata=meta)
    trail = sm.get_audit_trail("Acme AI")
    assert trail[0]["metadata"] == meta


# ---- Test 10: multiple transitions recorded in order ----

def test_multiple_transitions_in_order(session, sm, seed_company):
    sm.transition("Acme AI", "Sent")
    sm.transition("Acme AI", "Responded")
    sm.transition("Acme AI", "Interview")
    trail = sm.get_audit_trail("Acme AI")
    assert len(trail) == 3
    assert trail[0]["from_stage"] == "Not Started"
    assert trail[0]["to_stage"] == "Sent"
    assert trail[1]["from_stage"] == "Sent"
    assert trail[1]["to_stage"] == "Responded"
    assert trail[2]["from_stage"] == "Responded"
    assert trail[2]["to_stage"] == "Interview"

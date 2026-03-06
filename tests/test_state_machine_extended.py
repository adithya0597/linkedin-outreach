"""Extended tests for OutreachStateMachine: terminal states, circuit breaker, new transitions."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.state_machine import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    MAX_RESEND_CYCLES,
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


def _seed_outreach(session, company_name: str = "TestCo", stage: str = "Not Started") -> OutreachORM:
    """Helper: create a company + outreach record at the given stage."""
    company = CompanyORM(name=company_name)
    session.add(company)
    session.flush()
    outreach = OutreachORM(
        company_id=company.id,
        company_name=company_name,
        stage=stage,
    )
    session.add(outreach)
    session.commit()
    return outreach


# ---- Test 1: Interview -> Offer is valid ----

def test_interview_to_offer(session, sm):
    _seed_outreach(session, "OfferCo", "Interview")
    result = sm.transition("OfferCo", "Offer")
    assert result.stage == "Offer"
    assert result.response_at is not None


# ---- Test 2: Interview -> Rejected is valid ----

def test_interview_to_rejected(session, sm):
    _seed_outreach(session, "RejectCo", "Interview")
    result = sm.transition("RejectCo", "Rejected")
    assert result.stage == "Rejected"
    assert result.response_at is not None


# ---- Test 3: Declined is terminal (no transitions out) ----

def test_declined_is_terminal(session, sm):
    _seed_outreach(session, "DeclinedCo", "Declined")
    available = sm.get_available_transitions("DeclinedCo")
    assert available == []
    with pytest.raises(InvalidTransitionError, match="none \\(terminal state\\)"):
        sm.transition("DeclinedCo", "Sent")


# ---- Test 4: Offer is terminal (no transitions out) ----

def test_offer_is_terminal(session, sm):
    _seed_outreach(session, "OfferTermCo", "Offer")
    available = sm.get_available_transitions("OfferTermCo")
    assert available == []
    with pytest.raises(InvalidTransitionError, match="none \\(terminal state\\)"):
        sm.transition("OfferTermCo", "Sent")


# ---- Test 5: Rejected is terminal (no transitions out) ----

def test_rejected_is_terminal(session, sm):
    _seed_outreach(session, "RejTermCo", "Rejected")
    available = sm.get_available_transitions("RejTermCo")
    assert available == []
    with pytest.raises(InvalidTransitionError, match="none \\(terminal state\\)"):
        sm.transition("RejTermCo", "Interview")


# ---- Test 6: Circuit breaker blocks after MAX_RESEND_CYCLES ----

def test_circuit_breaker_blocks_after_max_cycles(session, sm):
    outreach = _seed_outreach(session, "LoopCo", "No Answer")

    # Manually build an audit trail with MAX_RESEND_CYCLES (3) No Answer -> Sent entries
    audit_lines = []
    for i in range(MAX_RESEND_CYCLES):
        audit_lines.append(json.dumps({
            "timestamp": f"2026-03-0{i+1}T10:00:00+00:00",
            "from_stage": "No Answer",
            "to_stage": "Sent",
            "metadata": {},
        }))
    outreach.audit_trail = "\n".join(audit_lines)
    session.commit()

    # The 4th attempt should be blocked by the circuit breaker
    with pytest.raises(InvalidTransitionError, match="Circuit breaker"):
        sm.transition("LoopCo", "Sent")

    # Verify the stage did NOT change
    assert outreach.stage == "No Answer"


# ---- Test 7: Circuit breaker allows transitions within limit ----

def test_circuit_breaker_allows_within_limit(session, sm):
    outreach = _seed_outreach(session, "OkCo", "No Answer")

    # Build audit trail with 2 cycles (under the limit of 3)
    audit_lines = []
    for i in range(MAX_RESEND_CYCLES - 1):
        audit_lines.append(json.dumps({
            "timestamp": f"2026-03-0{i+1}T10:00:00+00:00",
            "from_stage": "No Answer",
            "to_stage": "Sent",
            "metadata": {},
        }))
    outreach.audit_trail = "\n".join(audit_lines)
    session.commit()

    # Should succeed since we are at 2 cycles, below the limit of 3
    result = sm.transition("OkCo", "Sent")
    assert result.stage == "Sent"

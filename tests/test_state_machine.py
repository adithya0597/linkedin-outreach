from __future__ import annotations

import json

import pytest

from src.db.orm import CompanyORM, OutreachORM
from src.outreach.state_machine import (
    MAX_RESEND_CYCLES,
    VALID_TRANSITIONS,
    InvalidTransitionError,
    OutreachStateMachine,
)


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


# ---------------------------------------------------------------------------
# Extended tests: terminal states, circuit breaker, new transitions
# ---------------------------------------------------------------------------


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


def test_interview_to_offer(session, sm):
    _seed_outreach(session, "OfferCo", "Interview")
    result = sm.transition("OfferCo", "Offer")
    assert result.stage == "Offer"
    assert result.response_at is not None


def test_interview_to_rejected(session, sm):
    _seed_outreach(session, "RejectCo", "Interview")
    result = sm.transition("RejectCo", "Rejected")
    assert result.stage == "Rejected"
    assert result.response_at is not None


def test_declined_is_terminal(session, sm):
    _seed_outreach(session, "DeclinedCo", "Declined")
    available = sm.get_available_transitions("DeclinedCo")
    assert available == []
    with pytest.raises(InvalidTransitionError, match="none \\(terminal state\\)"):
        sm.transition("DeclinedCo", "Sent")


def test_offer_is_terminal(session, sm):
    _seed_outreach(session, "OfferTermCo", "Offer")
    available = sm.get_available_transitions("OfferTermCo")
    assert available == []
    with pytest.raises(InvalidTransitionError, match="none \\(terminal state\\)"):
        sm.transition("OfferTermCo", "Sent")


def test_rejected_is_terminal(session, sm):
    _seed_outreach(session, "RejTermCo", "Rejected")
    available = sm.get_available_transitions("RejTermCo")
    assert available == []
    with pytest.raises(InvalidTransitionError, match="none \\(terminal state\\)"):
        sm.transition("RejTermCo", "Interview")


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

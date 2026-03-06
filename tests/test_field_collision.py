"""Tests for the response_text / audit_trail field collision fix.

Verifies that OutreachORM has both columns and that writing to one
does not affect the other.
"""

import json

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from src.db.orm import Base, OutreachORM


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def test_outreach_has_both_columns():
    """OutreachORM must expose both response_text and audit_trail columns."""
    _, engine = _make_session()
    inspector = inspect(engine)
    col_names = [c["name"] for c in inspector.get_columns("outreach")]
    assert "response_text" in col_names
    assert "audit_trail" in col_names


def test_writing_audit_trail_does_not_affect_response_text():
    """Writing to audit_trail must leave response_text unchanged and vice versa."""
    session, _ = _make_session()

    record = OutreachORM(
        company_name="TestCo",
        response_text="Thanks for reaching out!",
        audit_trail="",
    )
    session.add(record)
    session.commit()

    # Update audit_trail only
    record.audit_trail = '{"event": "state_change", "to": "responded"}'
    session.commit()
    session.refresh(record)

    assert record.response_text == "Thanks for reaching out!"
    assert '"state_change"' in record.audit_trail

    # Update response_text only
    record.response_text = "Updated response"
    session.commit()
    session.refresh(record)

    assert record.response_text == "Updated response"
    assert '"state_change"' in record.audit_trail

    session.close()


def test_backward_compat_empty_audit_trail():
    """Existing records with empty/default audit_trail must still work."""
    session, _ = _make_session()

    record = OutreachORM(
        company_name="LegacyCo",
        response_text="Some response",
        # audit_trail intentionally omitted — should default to ""
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    assert record.audit_trail == ""
    assert record.response_text == "Some response"

    # Ensure the record is queryable
    fetched = session.query(OutreachORM).filter_by(company_name="LegacyCo").first()
    assert fetched is not None
    assert fetched.audit_trail == ""

    session.close()


def test_audit_trail_stores_newline_separated_json():
    """audit_trail must accept newline-separated JSON entries (StateMachine format)."""
    session, _ = _make_session()

    entries = [
        json.dumps({"event": "created", "stage": "Not Started", "ts": "2026-03-06T08:00:00"}),
        json.dumps({"event": "sent", "stage": "Sent", "ts": "2026-03-06T09:00:00"}),
        json.dumps({"event": "responded", "stage": "Responded", "ts": "2026-03-06T10:00:00"}),
    ]
    trail_text = "\n".join(entries)

    record = OutreachORM(
        company_name="TrailCo",
        audit_trail=trail_text,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    # Parse back each line as valid JSON
    lines = record.audit_trail.strip().split("\n")
    assert len(lines) == 3
    for line in lines:
        parsed = json.loads(line)
        assert "event" in parsed
        assert "stage" in parsed

    session.close()

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.response_tracker import (
    AUTO_REPLY,
    NEGATIVE,
    NEUTRAL,
    POSITIVE,
    REFERRAL,
    ResponseTracker,
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
def tracker(session):
    """Return a ResponseTracker bound to the test session."""
    return ResponseTracker(session)


@pytest.fixture()
def seed_sent(session):
    """Seed a company with a Sent outreach record (sent 2 days ago)."""
    company = CompanyORM(name="Acme AI", tier="Tier 1")
    session.add(company)
    session.flush()
    outreach = OutreachORM(
        company_id=company.id,
        company_name="Acme AI",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=2),
    )
    session.add(outreach)
    session.commit()
    return outreach


# ---- Test 1: log_response updates stage to Responded ----

def test_log_response_updates_stage(session, tracker, seed_sent):
    tracker.log_response("Acme AI", "Thanks, let's schedule an interview!")
    record = session.query(OutreachORM).filter(OutreachORM.company_name == "Acme AI").first()
    assert record.stage == "Responded"
    assert record.response_at is not None


# ---- Test 2: auto-classification interview -> POSITIVE ----

def test_auto_classify_positive(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "We'd love to schedule an interview with you")
    assert result["classification"] == POSITIVE


# ---- Test 3: auto-classification not hiring -> NEGATIVE ----

def test_auto_classify_negative(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "We are not hiring at this time")
    assert result["classification"] == NEGATIVE


# ---- Test 4: auto-classification out of office -> AUTO_REPLY ----

def test_auto_classify_auto_reply(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "I am out of office until next week")
    assert result["classification"] == AUTO_REPLY


# ---- Test 5: auto-classification refer -> REFERRAL ----

def test_auto_classify_referral(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "You should check with our recruiter")
    assert result["classification"] == REFERRAL


# ---- Test 6: manual classification overrides auto ----

def test_manual_classification_override(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "Generic message", classification=POSITIVE)
    assert result["classification"] == POSITIVE
    # Verify stored in response_text JSON
    record = session.query(OutreachORM).filter(OutreachORM.company_name == "Acme AI").first()
    data = json.loads(record.response_text)
    assert data["classification"] == POSITIVE


# ---- Test 7: response_time_days calculated correctly ----

def test_response_time_days(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "Sounds great, let's meet")
    assert result["response_time_days"] is not None
    # Sent 2 days ago, responded now -> ~2.0 days
    assert 1.5 <= result["response_time_days"] <= 2.5


# ---- Test 8: summary counts by classification ----

def test_response_summary_counts(session, tracker):
    # Seed multiple companies with sent records
    for name, text in [
        ("Alpha AI", "Let's schedule an interview"),
        ("Beta AI", "We are not hiring right now"),
        ("Gamma AI", "I am out of office"),
    ]:
        company = CompanyORM(name=name, tier="Tier 1")
        session.add(company)
        session.flush()
        outreach = OutreachORM(
            company_id=company.id,
            company_name=name,
            stage="Sent",
            sent_at=datetime.now() - timedelta(days=1),
        )
        session.add(outreach)
        session.commit()
        tracker.log_response(name, text)

    summary = tracker.get_response_summary()
    assert summary["total_responses"] == 3
    assert summary["by_classification"][POSITIVE] == 1
    assert summary["by_classification"][NEGATIVE] == 1
    assert summary["by_classification"][AUTO_REPLY] == 1
    assert len(summary["companies_responded"]) == 3


# ---- Test 9: next_actions returns correct recommendations ----

def test_next_actions_per_classification(session, tracker):
    for name, cls in [
        ("A Co", POSITIVE),
        ("B Co", NEGATIVE),
        ("C Co", REFERRAL),
        ("D Co", NEUTRAL),
        ("E Co", AUTO_REPLY),
    ]:
        company = CompanyORM(name=name, tier="Tier 2")
        session.add(company)
        session.flush()
        outreach = OutreachORM(
            company_id=company.id,
            company_name=name,
            stage="Sent",
            sent_at=datetime.now() - timedelta(days=1),
        )
        session.add(outreach)
        session.commit()
        tracker.log_response(name, "some text", classification=cls)

    actions = tracker.get_next_actions()
    action_map = {a["company"]: a for a in actions}

    assert action_map["A Co"]["recommended_action"] == "Schedule call"
    assert action_map["B Co"]["recommended_action"] == "Archive and move on"
    assert action_map["C Co"]["recommended_action"] == "Contact referred person"
    assert action_map["D Co"]["recommended_action"] == "Send follow-up"
    assert action_map["E Co"]["recommended_action"] == "Wait and retry"


# ---- Test 10: funnel calculates response_rate correctly ----

def test_response_funnel(session, tracker):
    company = CompanyORM(name="Funnel Co", tier="Tier 1")
    session.add(company)
    session.flush()

    # 2 drafted (Not Started)
    for _ in range(2):
        session.add(OutreachORM(
            company_id=company.id, company_name="Funnel Co", stage="Not Started",
        ))
    # 3 sent
    for _ in range(3):
        session.add(OutreachORM(
            company_id=company.id, company_name="Funnel Co", stage="Sent",
            sent_at=datetime.now() - timedelta(days=1),
        ))
    # 1 responded
    session.add(OutreachORM(
        company_id=company.id, company_name="Funnel Co", stage="Responded",
        sent_at=datetime.now() - timedelta(days=2),
        response_at=datetime.now(),
        response_text=json.dumps({"text": "yes", "classification": POSITIVE}),
    ))
    session.commit()

    funnel = tracker.get_response_funnel()
    assert funnel["total_drafted"] == 2
    assert funnel["total_sent"] == 3
    assert funnel["total_responded"] == 1
    # response_rate = 1 / (3+1) * 100 = 25.0
    assert funnel["response_rate"] == 25.0
    assert "Tier 1" in funnel["by_tier"]


# ---- Test 11: empty responses return empty summary ----

def test_empty_responses_summary(session, tracker):
    summary = tracker.get_response_summary()
    assert summary["total_responses"] == 0
    assert summary["companies_responded"] == []
    assert summary["avg_response_time_days"] == 0
    assert summary["fastest_response"] is None


# ---- Test 12: funnel with zero sends gives 0 response_rate ----

def test_funnel_zero_sends(session, tracker):
    funnel = tracker.get_response_funnel()
    assert funnel["response_rate"] == 0


# ---- Test 13: multiple responses from same company handled ----

def test_multiple_responses_same_company(session, tracker):
    company = CompanyORM(name="Multi Co", tier="Tier 2")
    session.add(company)
    session.flush()

    # Two sent records for same company
    for _ in range(2):
        session.add(OutreachORM(
            company_id=company.id,
            company_name="Multi Co",
            stage="Sent",
            sent_at=datetime.now() - timedelta(days=3),
        ))
    session.commit()

    # Log first response
    r1 = tracker.log_response("Multi Co", "Let me refer you to our team lead")
    assert r1["classification"] == REFERRAL

    # Log second response (second sent record)
    r2 = tracker.log_response("Multi Co", "We're not hiring now")
    assert r2["classification"] == NEGATIVE

    # Summary should show both
    summary = tracker.get_response_summary()
    assert summary["total_responses"] == 2
    assert summary["by_classification"][REFERRAL] == 1
    assert summary["by_classification"][NEGATIVE] == 1
    # Company appears only once in list
    assert summary["companies_responded"].count("Multi Co") == 1

"""Tests for response tracking -- log_response, auto-classification, response
summary, next actions, funnel, and the v2 score-based classifier.

Consolidated from: test_response_tracker.py, test_response_classifier_v2.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from src.db.orm import CompanyORM, OutreachORM
from src.outreach.response_tracker import (
    AUTO_REPLY,
    NEGATIVE,
    NEUTRAL,
    POSITIVE,
    REFERRAL,
    ResponseTracker,
    _auto_classify,
)


# ===========================================================================
# Fixtures
# ===========================================================================


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


# ===========================================================================
# Core response tracker tests (from test_response_tracker.py)
# ===========================================================================


def test_log_response_updates_stage(session, tracker, seed_sent):
    tracker.log_response("Acme AI", "Thanks, let's schedule an interview!")
    record = session.query(OutreachORM).filter(OutreachORM.company_name == "Acme AI").first()
    assert record.stage == "Responded"
    assert record.response_at is not None


def test_auto_classify_positive(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "We'd love to schedule an interview with you")
    assert result["classification"] == POSITIVE


def test_auto_classify_negative(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "We are not hiring at this time")
    assert result["classification"] == NEGATIVE


def test_auto_classify_auto_reply(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "I am out of office until next week")
    assert result["classification"] == AUTO_REPLY


def test_auto_classify_referral(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "You should check with our recruiter")
    assert result["classification"] == REFERRAL


def test_manual_classification_override(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "Generic message", classification=POSITIVE)
    assert result["classification"] == POSITIVE
    record = session.query(OutreachORM).filter(OutreachORM.company_name == "Acme AI").first()
    data = json.loads(record.response_text)
    assert data["classification"] == POSITIVE


def test_response_time_days(session, tracker, seed_sent):
    result = tracker.log_response("Acme AI", "Sounds great, let's meet")
    assert result["response_time_days"] is not None
    assert 1.5 <= result["response_time_days"] <= 2.5


def test_response_summary_counts(session, tracker):
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


def test_response_funnel(session, tracker):
    company = CompanyORM(name="Funnel Co", tier="Tier 1")
    session.add(company)
    session.flush()

    for _ in range(2):
        session.add(OutreachORM(
            company_id=company.id, company_name="Funnel Co", stage="Not Started",
        ))
    for _ in range(3):
        session.add(OutreachORM(
            company_id=company.id, company_name="Funnel Co", stage="Sent",
            sent_at=datetime.now() - timedelta(days=1),
        ))
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
    assert funnel["response_rate"] == 25.0
    assert "Tier 1" in funnel["by_tier"]


def test_empty_responses_summary(session, tracker):
    summary = tracker.get_response_summary()
    assert summary["total_responses"] == 0
    assert summary["companies_responded"] == []
    assert summary["avg_response_time_days"] == 0
    assert summary["fastest_response"] is None


def test_funnel_zero_sends(session, tracker):
    funnel = tracker.get_response_funnel()
    assert funnel["response_rate"] == 0


def test_multiple_responses_same_company(session, tracker):
    company = CompanyORM(name="Multi Co", tier="Tier 2")
    session.add(company)
    session.flush()

    for _ in range(2):
        session.add(OutreachORM(
            company_id=company.id,
            company_name="Multi Co",
            stage="Sent",
            sent_at=datetime.now() - timedelta(days=3),
        ))
    session.commit()

    r1 = tracker.log_response("Multi Co", "Let me refer you to our team lead")
    assert r1["classification"] == REFERRAL

    r2 = tracker.log_response("Multi Co", "We're not hiring now")
    assert r2["classification"] == NEGATIVE

    summary = tracker.get_response_summary()
    assert summary["total_responses"] == 2
    assert summary["by_classification"][REFERRAL] == 1
    assert summary["by_classification"][NEGATIVE] == 1
    assert summary["companies_responded"].count("Multi Co") == 1


# ===========================================================================
# V2 score-based classifier tests (from test_response_classifier_v2.py)
# ===========================================================================


def test_interested_positive():
    """New POSITIVE keyword 'interested' correctly classifies."""
    result = _auto_classify("interested in your background")
    assert result == POSITIVE


def test_unfortunately_overrides_positive():
    """Negative override word 'unfortunately' forces NEGATIVE even when
    positive keyword 'love to chat' also matches."""
    result = _auto_classify("unfortunately we love to chat but no positions")
    assert result == NEGATIVE


def test_tell_me_more_positive():
    """New POSITIVE keyword 'tell me more' works."""
    result = _auto_classify("tell me more about your experience")
    assert result == POSITIVE


def test_empty_string_neutral():
    """Empty input returns NEUTRAL."""
    assert _auto_classify("") == NEUTRAL


def test_auto_reply_wins_over_positive():
    """AUTO_REPLY is checked first and is definitive, even if text also
    contains positive keywords."""
    text = "I am out of office until Monday. I'm interested in continuing our chat."
    result = _auto_classify(text)
    assert result == AUTO_REPLY


def test_not_hiring_negative():
    """NEGATIVE keyword 'not hiring' works."""
    result = _auto_classify("not hiring right now")
    assert result == NEGATIVE


def test_great_fit_lets_talk_positive():
    """Multiple POSITIVE keywords ('great fit', 'let's talk') classify correctly."""
    result = _auto_classify("great fit, let's talk")
    assert result == POSITIVE


def test_sorry_unable_negative_override():
    """Negative override words 'sorry to' and 'unable' force NEGATIVE."""
    result = _auto_classify("sorry to say we're unable to move forward")
    assert result == NEGATIVE


def test_check_with_referral():
    """REFERRAL keyword 'check with' works."""
    result = _auto_classify("check with my colleague")
    assert result == REFERRAL


def test_pure_neutral():
    """Text with no keyword matches returns NEUTRAL."""
    result = _auto_classify("thanks for reaching out")
    assert result == NEUTRAL


def test_classify_response_public_api():
    """ResponseTracker.classify_response() delegates to the same classifier."""
    assert ResponseTracker.classify_response("let's connect soon") == POSITIVE
    assert ResponseTracker.classify_response("") == NEUTRAL


def test_tie_prefers_negative():
    """When positive and negative counts tie, NEGATIVE wins (conservative)."""
    result = _auto_classify("interested but honestly not a fit")
    assert result == NEGATIVE


def test_filled_position_negative():
    """New NEGATIVE keyword 'filled the position' works."""
    result = _auto_classify("We already filled the position last week")
    assert result == NEGATIVE


def test_forward_your_info_referral():
    """New REFERRAL keyword 'forward your info' works."""
    result = _auto_classify("I'll forward your info to the hiring team")
    assert result == REFERRAL


def test_whitespace_only_neutral():
    """Whitespace-only input returns NEUTRAL."""
    assert _auto_classify("   ") == NEUTRAL


def test_log_response_uses_v2_classifier(session, tracker, seed_sent):
    """Integration: log_response auto-classifies using the v2 engine."""
    result = tracker.log_response("Acme AI", "tell me more about your background")
    assert result["classification"] == POSITIVE
    assert result["next_action"] == "Schedule call"

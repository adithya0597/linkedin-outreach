"""Tests for the v2 score-based response classifier.

Validates expanded keyword lists, score-based classification (replacing
first-match-wins), and the negative override mechanism.
"""

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
    _auto_classify,
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


# ---- Test 1: "interested in your background" -> POSITIVE ----

def test_interested_positive():
    """New POSITIVE keyword 'interested' correctly classifies."""
    result = _auto_classify("interested in your background")
    assert result == POSITIVE


# ---- Test 2: KEY BUG FIX -- "unfortunately we love to chat but no positions" -> NEGATIVE ----

def test_unfortunately_overrides_positive():
    """Negative override word 'unfortunately' forces NEGATIVE even when
    positive keyword 'love to chat' also matches.  This was the v1 bug
    where first-match-wins returned POSITIVE."""
    result = _auto_classify("unfortunately we love to chat but no positions")
    assert result == NEGATIVE


# ---- Test 3: "tell me more about your experience" -> POSITIVE ----

def test_tell_me_more_positive():
    """New POSITIVE keyword 'tell me more' works."""
    result = _auto_classify("tell me more about your experience")
    assert result == POSITIVE


# ---- Test 4: empty string -> NEUTRAL ----

def test_empty_string_neutral():
    """Empty input returns NEUTRAL."""
    assert _auto_classify("") == NEUTRAL


# ---- Test 5: AUTO_REPLY wins over everything ----

def test_auto_reply_wins_over_positive():
    """AUTO_REPLY is checked first and is definitive, even if text also
    contains positive keywords."""
    text = "I am out of office until Monday. I'm interested in continuing our chat."
    result = _auto_classify(text)
    assert result == AUTO_REPLY


# ---- Test 6: "not hiring right now" -> NEGATIVE ----

def test_not_hiring_negative():
    """NEGATIVE keyword 'not hiring' works."""
    result = _auto_classify("not hiring right now")
    assert result == NEGATIVE


# ---- Test 7: "great fit, let's talk" -> POSITIVE ----

def test_great_fit_lets_talk_positive():
    """Multiple POSITIVE keywords ('great fit', 'let's talk') classify correctly."""
    result = _auto_classify("great fit, let's talk")
    assert result == POSITIVE


# ---- Test 8: "sorry to say we're unable to move forward" -> NEGATIVE ----

def test_sorry_unable_negative_override():
    """Negative override words 'sorry to' and 'unable' force NEGATIVE even
    without explicit negative keywords.  The override fires because 'unable'
    is in the override list.  Since no positive keywords match either,
    this should still be NEGATIVE via direct keyword match on the override
    logic or via negative keyword count."""
    result = _auto_classify("sorry to say we're unable to move forward")
    assert result == NEGATIVE


# ---- Test 9: "check with my colleague" -> REFERRAL ----

def test_check_with_referral():
    """REFERRAL keyword 'check with' works."""
    result = _auto_classify("check with my colleague")
    assert result == REFERRAL


# ---- Test 10: neutral text with no strong signals -> NEUTRAL ----

def test_pure_neutral():
    """Text with no keyword matches returns NEUTRAL."""
    result = _auto_classify("thanks for reaching out")
    assert result == NEUTRAL


# ---- Additional edge case tests ----

def test_classify_response_public_api():
    """ResponseTracker.classify_response() delegates to the same classifier."""
    assert ResponseTracker.classify_response("let's connect soon") == POSITIVE
    assert ResponseTracker.classify_response("") == NEUTRAL


def test_tie_prefers_negative():
    """When positive and negative counts tie, NEGATIVE wins (conservative)."""
    # 'interested' = 1 positive, 'not a fit' = 1 negative -> tie -> NEGATIVE
    # But 'interested' also triggers override check -- no override word present.
    # With equal counts, negative should win.
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

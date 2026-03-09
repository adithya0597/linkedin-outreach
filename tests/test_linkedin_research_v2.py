"""Tests for LinkedIn Research v2: dedup, expanded titles, score updates, mutual connections."""

from __future__ import annotations
from datetime import datetime

import pytest

from src.db.orm import CompanyORM, ContactORM
from src.integrations.linkedin_research import ContactResearcher, TITLE_PRIORITY, SEARCH_TITLES


@pytest.fixture()
def researcher(session):
    return ContactResearcher(session)


@pytest.fixture()
def company(session):
    c = CompanyORM(name="TestCorp", tier="Tier 1")
    session.add(c)
    session.commit()
    return c


def test_dedup_same_name_company(session, researcher, company):
    """Recording the same contact twice for the same company should update, not duplicate."""
    data = {"name": "Jane Doe", "title": "CTO", "linkedin_url": "https://linkedin.com/in/jane"}
    c1 = researcher.record_contact("TestCorp", data)

    data2 = {"name": "Jane Doe", "title": "VP Engineering", "linkedin_url": "https://linkedin.com/in/jane-new"}
    c2 = researcher.record_contact("TestCorp", data2)

    assert c1.id == c2.id  # Same record updated
    assert c2.title == "VP Engineering"
    total = session.query(ContactORM).filter_by(company_name="TestCorp").count()
    assert total == 1


def test_dedup_different_companies(session, researcher, company):
    """Same name at different companies should create separate records."""
    session.add(CompanyORM(name="OtherCorp", tier="Tier 2"))
    session.commit()

    data = {"name": "Jane Doe", "title": "CTO"}
    researcher.record_contact("TestCorp", data)
    researcher.record_contact("OtherCorp", data)

    total = session.query(ContactORM).count()
    assert total == 2


def test_expanded_title_priority_co_founder():
    """Co-Founder should be in TITLE_PRIORITY with priority 1."""
    assert "Co-Founder" in TITLE_PRIORITY
    assert TITLE_PRIORITY["Co-Founder"] == 1


def test_expanded_title_priority_staff_engineer():
    """Staff Engineer should be in TITLE_PRIORITY with priority 2."""
    assert "Staff Engineer" in TITLE_PRIORITY
    assert TITLE_PRIORITY["Staff Engineer"] == 2


def test_expanded_search_titles():
    """SEARCH_TITLES should include new entries."""
    assert "Co-Founder" in SEARCH_TITLES
    assert "Head of AI" in SEARCH_TITLES
    assert "Staff Engineer" in SEARCH_TITLES


def test_update_score_positive(session, researcher, company):
    """POSITIVE response should boost contact score by 15."""
    data = {"name": "John", "title": "CTO", "linkedin_degree": 2}
    researcher.record_contact("TestCorp", data)
    original = session.query(ContactORM).filter_by(name="John").first()
    original_score = original.contact_score

    result = researcher.update_score_from_response("John", "TestCorp", "POSITIVE")
    assert result is not None
    assert result.contact_score == min(original_score + 15.0, 100.0)


def test_update_score_negative(session, researcher, company):
    """NEGATIVE response should reduce contact score by 10."""
    data = {"name": "Bob", "title": "Recruiter", "linkedin_degree": 3}
    researcher.record_contact("TestCorp", data)
    original = session.query(ContactORM).filter_by(name="Bob").first()
    original_score = original.contact_score

    result = researcher.update_score_from_response("Bob", "TestCorp", "NEGATIVE")
    assert result is not None
    assert result.contact_score == max(original_score - 10.0, 0.0)


def test_record_mutual_connections(session, researcher, company):
    """record_mutual_connections should populate the mutual_connections field."""
    data = {"name": "Alice", "title": "VP Engineering"}
    researcher.record_contact("TestCorp", data)

    mutuals = ["Sam Smith", "Pat Jones", "Chris Lee"]
    result = researcher.record_mutual_connections("Alice", "TestCorp", mutuals)
    assert result is not None
    assert "Sam Smith" in result.mutual_connections
    assert "Pat Jones" in result.mutual_connections
    assert "Chris Lee" in result.mutual_connections

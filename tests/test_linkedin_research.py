"""Comprehensive tests for LinkedIn contact research module."""

from urllib.parse import quote_plus

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, ContactORM
from src.integrations.linkedin_research import (
    SEARCH_TITLES,
    TITLE_PRIORITY,
    ContactResearcher,
)


@pytest.fixture
def mem_engine():
    """In-memory SQLite engine with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def mem_session(mem_engine):
    """Session bound to in-memory engine."""
    factory = sessionmaker(bind=mem_engine)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def researcher(mem_session):
    """ContactResearcher wired to the in-memory session."""
    return ContactResearcher(mem_session)


@pytest.fixture
def seed_company(mem_session):
    """Insert a company and return it (flushed so .id is set)."""
    company = CompanyORM(
        name="Acme AI",
        description="AI-native startup",
        hq_location="San Francisco, CA",
        employees=50,
        funding_stage="Series A",
        is_ai_native=True,
        h1b_status="Confirmed",
    )
    mem_session.add(company)
    mem_session.commit()
    return company


# ---------------------------------------------------------------------------
# Search URL generation
# ---------------------------------------------------------------------------

class TestSearchUrls:
    def test_url_contains_linkedin_domain(self, researcher):
        results = researcher.find_hiring_contacts("Acme AI")
        for r in results:
            assert "linkedin.com/search/results/people" in r["search_url"]

    def test_url_is_properly_encoded(self, researcher):
        results = researcher.find_hiring_contacts("O'Reilly Media")
        for r in results:
            # quote_plus encodes the apostrophe
            assert "O%27Reilly" in r["search_url"] or "O%27" in r["search_url"]

    def test_all_search_titles_covered(self, researcher):
        results = researcher.find_hiring_contacts("TestCo")
        titles_in_results = {r["title"] for r in results}
        assert titles_in_results == set(SEARCH_TITLES)

    def test_result_count_matches_search_titles(self, researcher):
        results = researcher.find_hiring_contacts("TestCo")
        assert len(results) == len(SEARCH_TITLES)

    def test_company_name_in_every_result(self, researcher):
        results = researcher.find_hiring_contacts("LlamaIndex")
        for r in results:
            assert r["company"] == "LlamaIndex"

    def test_url_query_includes_title_and_company(self, researcher):
        results = researcher.find_hiring_contacts("Cursor")
        for r in results:
            expected_query = quote_plus(f"{r['title']} Cursor")
            assert expected_query in r["search_url"]


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:
    def test_cto_before_recruiter(self, researcher):
        results = researcher.find_hiring_contacts("TestCo")
        titles_ordered = [r["title"] for r in results]
        cto_idx = titles_ordered.index("CTO")
        recruiter_idx = titles_ordered.index("Recruiter")
        assert cto_idx < recruiter_idx

    def test_sorted_by_priority_ascending(self, researcher):
        results = researcher.find_hiring_contacts("TestCo")
        priorities = [r["priority"] for r in results]
        assert priorities == sorted(priorities)

    def test_vp_engineering_before_engineering_manager(self, researcher):
        results = researcher.find_hiring_contacts("TestCo")
        titles_ordered = [r["title"] for r in results]
        vp_idx = titles_ordered.index("VP Engineering")
        em_idx = titles_ordered.index("Engineering Manager")
        assert vp_idx < em_idx


# ---------------------------------------------------------------------------
# record_contact — company linking & score calculation
# ---------------------------------------------------------------------------

class TestRecordContact:
    def test_creates_contact_linked_to_company(self, researcher, seed_company, mem_session):
        contact = researcher.record_contact("Acme AI", {
            "name": "Jane Doe",
            "title": "CTO",
            "linkedin_url": "https://linkedin.com/in/janedoe",
            "linkedin_degree": 2,
        })
        assert contact.id is not None
        assert contact.company_id == seed_company.id
        assert contact.company_name == "Acme AI"
        # Persisted in DB
        from_db = mem_session.get(ContactORM, contact.id)
        assert from_db is not None
        assert from_db.name == "Jane Doe"

    def test_score_cto_degree2_open_profile_recent_posts(self, researcher, seed_company):
        """CTO(50) + degree2(10) + open_profile(10) + recent_posts(10) = 80."""
        contact = researcher.record_contact("Acme AI", {
            "name": "Alice Smith",
            "title": "CTO",
            "linkedin_degree": 2,
            "is_open_profile": True,
            "recent_posts": "Posted about AI infra last week",
        })
        assert contact.contact_score == 80.0

    def test_handles_unknown_company(self, researcher, mem_session):
        contact = researcher.record_contact("NonExistent Corp", {
            "name": "Bob Unknown",
            "title": "VP Engineering",
        })
        assert contact.company_id is None
        assert contact.company_name == "NonExistent Corp"
        # Still persisted
        from_db = mem_session.get(ContactORM, contact.id)
        assert from_db is not None

    def test_detects_recruiter_title(self, researcher, seed_company):
        contact = researcher.record_contact("Acme AI", {
            "name": "Recruiter Rita",
            "title": "Senior Recruiter",
        })
        assert contact.is_recruiter is True

    def test_non_recruiter_title(self, researcher, seed_company):
        contact = researcher.record_contact("Acme AI", {
            "name": "Engineer Ed",
            "title": "CTO",
        })
        assert contact.is_recruiter is False

    def test_talent_acquisition_is_recruiter(self, researcher, seed_company):
        contact = researcher.record_contact("Acme AI", {
            "name": "Talent Tina",
            "title": "Talent Acquisition Manager",
        })
        assert contact.is_recruiter is True

    def test_case_insensitive_company_lookup(self, researcher, seed_company):
        """Company lookup should be case-insensitive."""
        contact = researcher.record_contact("acme ai", {
            "name": "Case Test",
            "title": "Recruiter",
        })
        assert contact.company_id == seed_company.id

    def test_score_caps_at_100(self, researcher, seed_company):
        """Even with maximum bonuses, score should not exceed 100."""
        contact = researcher.record_contact("Acme AI", {
            "name": "Max Score",
            "title": "CTO",
            "linkedin_degree": 1,
            "is_open_profile": True,
            "recent_posts": "Very active poster",
            "followers": 10000,
        })
        assert contact.contact_score == 100.0

    def test_score_unknown_title(self, researcher, seed_company):
        """Unknown title gets base score of 5."""
        contact = researcher.record_contact("Acme AI", {
            "name": "Unknown Role",
            "title": "Chief Happiness Officer",
        })
        assert contact.contact_score == 5.0

    def test_follower_tiers(self, researcher, seed_company):
        """Test follower score brackets: 500+, 1000+, 5000+."""
        # 500-999: +2
        c1 = researcher.record_contact("Acme AI", {
            "name": "F500", "title": "Recruiter", "followers": 500,
        })
        # Recruiter(15) + followers_500(2) = 17
        assert c1.contact_score == 17.0

        # 1000-4999: +5
        c2 = researcher.record_contact("Acme AI", {
            "name": "F1000", "title": "Recruiter", "followers": 1000,
        })
        assert c2.contact_score == 20.0

        # 5000+: +10
        c3 = researcher.record_contact("Acme AI", {
            "name": "F5000", "title": "Recruiter", "followers": 5000,
        })
        assert c3.contact_score == 25.0

    def test_degree_scoring(self, researcher, seed_company):
        """Test linkedin_degree score: 1st=+20, 2nd=+10, 3rd=+5."""
        c1 = researcher.record_contact("Acme AI", {
            "name": "D1", "title": "Recruiter", "linkedin_degree": 1,
        })
        assert c1.contact_score == 35.0  # 15 + 20

        c2 = researcher.record_contact("Acme AI", {
            "name": "D2", "title": "Recruiter", "linkedin_degree": 2,
        })
        assert c2.contact_score == 25.0  # 15 + 10

        c3 = researcher.record_contact("Acme AI", {
            "name": "D3", "title": "Recruiter", "linkedin_degree": 3,
        })
        assert c3.contact_score == 20.0  # 15 + 5


# ---------------------------------------------------------------------------
# rank_contacts
# ---------------------------------------------------------------------------

class TestRankContacts:
    def test_returns_sorted_by_score_desc(self, researcher, seed_company):
        researcher.record_contact("Acme AI", {
            "name": "Low", "title": "Recruiter",
        })
        researcher.record_contact("Acme AI", {
            "name": "High", "title": "CTO", "linkedin_degree": 1,
            "is_open_profile": True, "recent_posts": "active",
        })
        researcher.record_contact("Acme AI", {
            "name": "Mid", "title": "Head of Engineering", "linkedin_degree": 2,
        })

        ranked = researcher.rank_contacts("Acme AI")
        scores = [c.contact_score for c in ranked]
        assert scores == sorted(scores, reverse=True)
        assert ranked[0].name == "High"

    def test_empty_for_unknown_company(self, researcher):
        ranked = researcher.rank_contacts("Ghost Corp")
        assert ranked == []

    def test_ranks_by_company_name_when_no_company_orm(self, researcher, mem_session):
        """Contacts with company_name but no company_id should still rank."""
        contact = ContactORM(
            name="Orphan Contact",
            title="VP Engineering",
            company_id=None,
            company_name="Orphan Inc",
            contact_score=40.0,
        )
        mem_session.add(contact)
        mem_session.commit()

        ranked = researcher.rank_contacts("Orphan Inc")
        assert len(ranked) == 1
        assert ranked[0].name == "Orphan Contact"


# ---------------------------------------------------------------------------
# check_profile_viewers
# ---------------------------------------------------------------------------

class TestCheckProfileViewers:
    def test_returns_url(self, researcher):
        result = researcher.check_profile_viewers()
        assert "viewers_url" in result
        assert "linkedin.com" in result["viewers_url"]

    def test_returns_template_with_required_keys(self, researcher):
        result = researcher.check_profile_viewers()
        template = result["template"]
        expected_keys = {
            "name", "title", "linkedin_url", "linkedin_degree",
            "is_open_profile", "followers", "location", "recent_posts",
        }
        assert set(template.keys()) == expected_keys

    def test_returns_instructions(self, researcher):
        result = researcher.check_profile_viewers()
        assert "instructions" in result
        assert "record_contact" in result["instructions"]


# ---------------------------------------------------------------------------
# TITLE_PRIORITY & SEARCH_TITLES constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_title_priority_cto_is_1(self):
        assert TITLE_PRIORITY["CTO"] == 1

    def test_title_priority_recruiter_is_5(self):
        assert TITLE_PRIORITY["Recruiter"] == 5

    def test_title_priority_head_of_engineering_is_2(self):
        assert TITLE_PRIORITY["Head of Engineering"] == 2

    def test_title_priority_engineering_manager_is_3(self):
        assert TITLE_PRIORITY["Engineering Manager"] == 3

    def test_title_priority_talent_acquisition_is_4(self):
        assert TITLE_PRIORITY["Talent Acquisition"] == 4

    def test_all_search_titles_in_priority_map(self):
        """Every title in SEARCH_TITLES must have an entry in TITLE_PRIORITY."""
        for title in SEARCH_TITLES:
            assert title in TITLE_PRIORITY, f"{title} missing from TITLE_PRIORITY"

    def test_search_titles_count(self):
        assert len(SEARCH_TITLES) == 9

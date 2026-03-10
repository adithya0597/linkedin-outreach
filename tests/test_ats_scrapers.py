"""Tests for Ashby + Greenhouse ATS scrapers, helpers, and composite key dedup."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config.enums import PortalTier, SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.ats_scraper import (
    AshbyScraper,
    GreenhouseScraper,
    _matches_keywords,
    _parse_h1b_from_description,
    _parse_salary_from_description,
    _strip_html,
)
from src.scrapers.persistence import _normalize

# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestParseH1BFromDescription:
    def test_h1b_mentioned(self):
        text = "We offer competitive pay.\nH1B visa sponsorship is available.\nApply now."
        mentioned, h1b_text = _parse_h1b_from_description(text)
        assert mentioned is True
        assert "H1B visa sponsorship" in h1b_text

    def test_h1b_dash_variant(self):
        text = "H-1B sponsorship provided for qualified candidates."
        mentioned, h1b_text = _parse_h1b_from_description(text)
        assert mentioned is True
        assert "H-1B" in h1b_text

    def test_visa_sponsorship(self):
        text = "This role offers visa sponsorship."
        mentioned, _h1b_text = _parse_h1b_from_description(text)
        assert mentioned is True

    def test_work_authorization(self):
        text = "Must have work authorization for the United States."
        mentioned, _h1b_text = _parse_h1b_from_description(text)
        assert mentioned is True

    def test_no_h1b_keywords(self):
        text = "We are looking for a senior engineer with Python experience."
        mentioned, h1b_text = _parse_h1b_from_description(text)
        assert mentioned is False
        assert h1b_text == ""

    def test_empty_text(self):
        mentioned, h1b_text = _parse_h1b_from_description("")
        assert mentioned is False
        assert h1b_text == ""

    def test_none_text(self):
        mentioned, _h1b_text = _parse_h1b_from_description(None)
        assert mentioned is False


class TestParseSalaryFromDescription:
    def test_salary_range_full(self):
        text = "The salary for this role is $150,000 - $200,000 per year."
        sal_str, sal_min, sal_max = _parse_salary_from_description(text)
        assert sal_min == 150000
        assert sal_max == 200000
        assert "150k" in sal_str
        assert "200k" in sal_str

    def test_salary_range_k_format(self):
        text = "Compensation: $150k-$200k"
        _sal_str, sal_min, sal_max = _parse_salary_from_description(text)
        assert sal_min == 150000
        assert sal_max == 200000

    def test_salary_plus(self):
        text = "Base salary of $180,000+"
        sal_str, sal_min, sal_max = _parse_salary_from_description(text)
        assert sal_min == 180000
        assert sal_max is None
        assert "180k" in sal_str

    def test_no_salary(self):
        text = "We offer competitive compensation."
        sal_str, sal_min, sal_max = _parse_salary_from_description(text)
        assert sal_str == ""
        assert sal_min is None
        assert sal_max is None

    def test_empty_text(self):
        sal_str, sal_min, _sal_max = _parse_salary_from_description("")
        assert sal_str == ""
        assert sal_min is None


class TestMatchesKeywords:
    def test_ai_in_title(self):
        assert _matches_keywords("AI Engineer", "") is True

    def test_ml_in_department(self):
        assert _matches_keywords("Software Engineer", "Machine Learning") is True

    def test_no_match(self):
        assert _matches_keywords("Sales Manager", "Marketing") is False

    def test_case_insensitive(self):
        assert _matches_keywords("Senior ML Engineer", "") is True

    def test_custom_keywords(self):
        assert _matches_keywords("Backend Dev", "", keywords=["backend"]) is True
        assert _matches_keywords("Frontend Dev", "", keywords=["backend"]) is False

    def test_llm_keyword(self):
        assert _matches_keywords("LLM Platform Engineer", "") is True

    def test_founding_engineer(self):
        assert _matches_keywords("Founding Engineer", "Engineering") is True


class TestStripHtml:
    def test_basic_html(self):
        html = "<p>Hello <b>world</b></p>"
        assert "Hello" in _strip_html(html)
        assert "world" in _strip_html(html)
        assert "<p>" not in _strip_html(html)

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_nested_tags(self):
        html = "<div><ul><li>Item 1</li><li>Item 2</li></ul></div>"
        result = _strip_html(html)
        assert "Item 1" in result
        assert "Item 2" in result


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("LlamaIndex") == "llamaindex"

    def test_strip_whitespace(self):
        assert _normalize("  Cursor  ") == "cursor"

    def test_remove_punctuation(self):
        assert _normalize("Hippocratic A.I.") == "hippocratic ai"

    def test_collapse_spaces(self):
        assert _normalize("Norm   AI") == "norm ai"

    def test_combined(self):
        assert _normalize("  LlamaIndex, Inc.  ") == "llamaindex inc"


# ---------------------------------------------------------------------------
# AshbyScraper tests
# ---------------------------------------------------------------------------


def _make_ashby_response(jobs: list[dict]) -> httpx.Response:
    """Build a mock httpx.Response with Ashby JSON payload."""
    content = json.dumps({"jobs": jobs}).encode()
    return httpx.Response(200, content=content, request=httpx.Request("GET", "https://api.ashbyhq.com/"))


SAMPLE_ASHBY_JOB = {
    "title": "AI Engineer",
    "location": "San Francisco, CA",
    "departmentName": "Engineering",
    "employmentType": "FullTime",
    "descriptionPlain": (
        "We are looking for an AI Engineer.\n"
        "Salary: $150,000 - $200,000/yr.\n"
        "H1B visa sponsorship is available for this role."
    ),
    "publishedAt": "2026-03-01T00:00:00Z",
    "jobUrl": "https://jobs.ashbyhq.com/llamaindex/ai-engineer",
}


@pytest.mark.asyncio
async def test_ashby_scraper_parses_jobs():
    scraper = AshbyScraper()
    mock_response = _make_ashby_response([SAMPLE_ASHBY_JOB])

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(scraper, "_get_client", return_value=mock_client):
        with patch.object(scraper, "_throttle", new_callable=AsyncMock):
            results = await scraper.search(keywords=["ai", "ml", "machine learning"], days=30)

    assert len(results) >= 1
    posting = results[0]
    assert posting.title == "AI Engineer"
    assert posting.source_portal == SourcePortal.ASHBY
    assert posting.h1b_mentioned is True
    assert posting.salary_min == 150000
    assert posting.salary_max == 200000


@pytest.mark.asyncio
async def test_ashby_scraper_filters_non_ai_jobs():
    """Non-AI jobs should be filtered out by keyword matching."""
    non_ai_job = {
        "title": "Sales Manager",
        "location": "New York",
        "departmentName": "Sales",
        "employmentType": "FullTime",
        "descriptionPlain": "Manage our sales team.",
        "publishedAt": "2026-03-01T00:00:00Z",
        "jobUrl": "https://jobs.ashbyhq.com/llamaindex/sales-manager",
    }
    mock_response = _make_ashby_response([non_ai_job])

    scraper = AshbyScraper()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(scraper, "_get_client", return_value=mock_client):
        with patch.object(scraper, "_throttle", new_callable=AsyncMock):
            results = await scraper.search(keywords=["ai", "ml", "machine learning"], days=30)

    assert len(results) == 0


@pytest.mark.asyncio
async def test_ashby_scraper_empty_response():
    """Empty jobs array should return empty results."""
    mock_response = _make_ashby_response([])

    scraper = AshbyScraper()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(scraper, "_get_client", return_value=mock_client):
        with patch.object(scraper, "_throttle", new_callable=AsyncMock):
            results = await scraper.search(keywords=["ai"], days=30)

    assert results == []


@pytest.mark.asyncio
async def test_ashby_portal_is_tier_2():
    scraper = AshbyScraper()
    assert scraper.portal == SourcePortal.ASHBY
    assert scraper.tier == PortalTier.TIER_2


# ---------------------------------------------------------------------------
# GreenhouseScraper tests
# ---------------------------------------------------------------------------


def _make_greenhouse_response(jobs: list[dict]) -> httpx.Response:
    """Build a mock httpx.Response with Greenhouse JSON payload."""
    content = json.dumps({"jobs": jobs}).encode()
    return httpx.Response(200, content=content, request=httpx.Request("GET", "https://boards-api.greenhouse.io/"))


SAMPLE_GREENHOUSE_JOB = {
    "title": "ML Engineer",
    "location": {"name": "Remote - US"},
    "departments": [{"name": "Engineering"}],
    "content": (
        "<p>We need an ML Engineer to build production systems.</p>"
        "<p>Salary: $160,000 - $210,000 per year.</p>"
        "<p>We provide H1B visa sponsorship.</p>"
    ),
    "absolute_url": "https://boards.greenhouse.io/snorkelai/jobs/12345",
    "updated_at": "2026-03-02T12:00:00Z",
}


@pytest.mark.asyncio
async def test_greenhouse_scraper_parses_jobs():
    scraper = GreenhouseScraper()
    mock_response = _make_greenhouse_response([SAMPLE_GREENHOUSE_JOB])

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(scraper, "_get_client", return_value=mock_client):
        with patch.object(scraper, "_throttle", new_callable=AsyncMock):
            results = await scraper.search(keywords=["ai", "ml", "machine learning"], days=30)

    assert len(results) >= 1
    posting = results[0]
    assert posting.title == "ML Engineer"
    assert posting.source_portal == SourcePortal.GREENHOUSE
    assert posting.h1b_mentioned is True
    assert posting.salary_min == 160000
    assert posting.salary_max == 210000
    assert "Remote" in posting.location


@pytest.mark.asyncio
async def test_greenhouse_scraper_strips_html():
    """Content field should be stripped of HTML tags."""
    job = {
        "title": "AI Research Engineer",
        "location": {"name": "San Francisco"},
        "departments": [],
        "content": "<div><h2>About the Role</h2><p>Build <b>AI</b> systems.</p></div>",
        "absolute_url": "https://boards.greenhouse.io/snorkelai/jobs/99999",
        "updated_at": "2026-03-02T00:00:00Z",
    }
    mock_response = _make_greenhouse_response([job])

    scraper = GreenhouseScraper()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(scraper, "_get_client", return_value=mock_client):
        with patch.object(scraper, "_throttle", new_callable=AsyncMock):
            results = await scraper.search(keywords=["ai", "ml", "machine learning"], days=30)

    assert len(results) == 1
    # Description should be plain text, not HTML
    assert "<div>" not in results[0].description
    assert "<p>" not in results[0].description


@pytest.mark.asyncio
async def test_greenhouse_scraper_filters_non_ai():
    non_ai = {
        "title": "Office Manager",
        "location": {"name": "NYC"},
        "departments": [{"name": "Operations"}],
        "content": "<p>Manage our office.</p>",
        "absolute_url": "https://boards.greenhouse.io/snorkelai/jobs/11111",
        "updated_at": "2026-03-01T00:00:00Z",
    }
    mock_response = _make_greenhouse_response([non_ai])

    scraper = GreenhouseScraper()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(scraper, "_get_client", return_value=mock_client):
        with patch.object(scraper, "_throttle", new_callable=AsyncMock):
            results = await scraper.search(keywords=["ai", "ml", "machine learning"], days=30)

    assert len(results) == 0


@pytest.mark.asyncio
async def test_greenhouse_portal_is_tier_2():
    scraper = GreenhouseScraper()
    assert scraper.portal == SourcePortal.GREENHOUSE
    assert scraper.tier == PortalTier.TIER_2


# ---------------------------------------------------------------------------
# Composite key dedup tests
# ---------------------------------------------------------------------------


def test_composite_dedup_same_job_different_urls():
    """Same (company, title) from different URLs should produce only 1 record."""

    from sqlalchemy.orm import Session

    from src.scrapers.persistence import persist_scan_results

    # Create a mock session
    session = MagicMock(spec=Session)

    # Mock DB queries — no existing records
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.all.return_value = []

    # Two postings: same company+title, different URLs
    posting1 = JobPosting(
        title="AI Engineer",
        company_name="Cursor",
        url="https://ashby.com/cursor/ai-engineer",
        source_portal=SourcePortal.ASHBY,
    )
    posting2 = JobPosting(
        title="AI Engineer",
        company_name="Cursor",
        url="https://greenhouse.io/cursor/ai-engineer",
        source_portal=SourcePortal.GREENHOUSE,
    )

    total, new, _companies = persist_scan_results(
        session, "Ashby", [posting1, posting2]
    )

    # Should add only 1 posting (second is a composite duplicate)
    assert total == 2  # total_found is always len(postings)
    assert new == 1  # Only 1 was actually inserted


def test_composite_dedup_different_jobs_same_company():
    """Different titles at the same company should both be inserted."""

    from sqlalchemy.orm import Session

    from src.scrapers.persistence import persist_scan_results

    session = MagicMock(spec=Session)
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.all.return_value = []

    posting1 = JobPosting(
        title="AI Engineer",
        company_name="Cursor",
        url="https://ashby.com/cursor/ai-engineer",
        source_portal=SourcePortal.ASHBY,
    )
    posting2 = JobPosting(
        title="ML Platform Engineer",
        company_name="Cursor",
        url="https://ashby.com/cursor/ml-platform-engineer",
        source_portal=SourcePortal.ASHBY,
    )

    _total, new, _companies = persist_scan_results(
        session, "Ashby", [posting1, posting2]
    )

    assert new == 2


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_registry_includes_ats_scrapers():
    """ATS scrapers should be registered in the default registry."""
    from src.scrapers.registry import build_default_registry

    registry = build_default_registry()
    ashby = registry.get_scraper("ashby")
    greenhouse = registry.get_scraper("greenhouse")

    assert ashby.portal == SourcePortal.ASHBY
    assert greenhouse.portal == SourcePortal.GREENHOUSE


def test_registry_total_count():
    """Registry should have 14 scrapers (12 original + 2 ATS)."""
    from src.scrapers.registry import build_default_registry

    registry = build_default_registry()
    all_scrapers = registry.get_all_scrapers()
    assert len(all_scrapers) == 17  # Lever removed from registry



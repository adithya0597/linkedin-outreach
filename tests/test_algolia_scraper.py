"""Tests for Algolia API-based scrapers (src/scrapers/algolia_scraper.py)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.config.enums import PortalTier, SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.algolia_scraper import (
    AlgoliaBaseScraper,
    WTTJAlgoliaScraper,
    YCAlgoliaScraper,
)


# ---------------------------------------------------------------------------
# Fixtures: Algolia response payloads
# ---------------------------------------------------------------------------

SAMPLE_YC_HIT = {
    "name": "NeuralTech",
    "slug": "neuraltech",
    "one_liner": "AI-powered code review",
    "batch": "W25",
    "is_remote": True,
    "all_locations": ["San Francisco, CA", "Remote"],
    "jobs": [
        {
            "title": "AI Engineer",
            "url": "https://www.workatastartup.com/companies/neuraltech/jobs/1001",
        },
        {
            "title": "ML Platform Engineer",
            "url": "https://www.workatastartup.com/companies/neuraltech/jobs/1002",
        },
    ],
}

SAMPLE_YC_HIT_NO_JOBS = {
    "name": "StealthAI",
    "slug": "stealthai",
    "one_liner": "Building AI tools",
    "batch": "S25",
    "is_remote": False,
    "all_locations": ["New York, NY"],
    "jobs": [],
}

SAMPLE_WTTJ_HIT = {
    "name": "Senior AI Engineer",
    "slug": "senior-ai-engineer-abc123",
    "company": {
        "name": "Datacraft",
        "slug": "datacraft",
    },
    "office": {
        "city": "Austin",
        "state": "TX",
        "country_code": "US",
    },
    "salary_min": 160000,
    "salary_max": 220000,
    "salary_currency": "USD",
    "remote": "full",
    "contract_type": "FULL_TIME",
    "published_at": "2026-03-01T00:00:00Z",
}

SAMPLE_WTTJ_HIT_NO_SALARY = {
    "name": "ML Ops Engineer",
    "slug": "ml-ops-engineer-def456",
    "company": {
        "name": "CloudML Inc",
        "slug": "cloudml",
    },
    "office": {
        "city": "San Francisco",
        "state": "CA",
        "country_code": "US",
    },
    "remote": "partial",
    "contract_type": "FULL_TIME",
    "published_at": "2026-03-02T12:00:00Z",
}


def _make_algolia_response(hits: list[dict], nb_pages: int = 1, page: int = 0) -> httpx.Response:
    """Build a mock Algolia API response."""
    content = json.dumps({
        "hits": hits,
        "nbHits": len(hits),
        "page": page,
        "nbPages": nb_pages,
        "hitsPerPage": 50,
    }).encode()
    return httpx.Response(
        200,
        content=content,
        request=httpx.Request("POST", "https://test-dsn.algolia.net/1/indexes/test/query"),
    )


def _make_error_response() -> httpx.Response:
    return httpx.Response(
        500,
        content=b"Internal Server Error",
        request=httpx.Request("POST", "https://test-dsn.algolia.net/1/indexes/test/query"),
    )


# ---------------------------------------------------------------------------
# YCAlgoliaScraper tests
# ---------------------------------------------------------------------------


class TestYCAlgoliaScraper:
    @pytest.mark.asyncio
    async def test_yc_algolia_search(self):
        """Mock Algolia POST response with hits, verify JobPostings."""
        scraper = YCAlgoliaScraper()
        mock_response = _make_algolia_response([SAMPLE_YC_HIT])

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        assert len(results) >= 1
        for posting in results:
            assert isinstance(posting, JobPosting)
            assert posting.source_portal == SourcePortal.YC

        titles = [p.title for p in results]
        assert "AI Engineer" in titles
        assert "ML Platform Engineer" in titles

    def test_yc_algolia_parse_hit(self):
        """Parse a single YC company hit with nested jobs."""
        scraper = YCAlgoliaScraper()
        postings = scraper._parse_yc_hit(SAMPLE_YC_HIT, keyword="ai")

        assert len(postings) == 2
        assert postings[0].title == "AI Engineer"
        assert postings[0].company_name == "NeuralTech"
        assert postings[0].work_model == "remote"
        assert "workatastartup.com" in postings[0].url

        assert postings[1].title == "ML Platform Engineer"
        assert postings[1].company_name == "NeuralTech"

    def test_yc_algolia_parse_hit_no_jobs(self):
        """Company with no jobs but matching one_liner creates a fallback posting."""
        scraper = YCAlgoliaScraper()
        postings = scraper._parse_yc_hit(SAMPLE_YC_HIT_NO_JOBS, keyword="AI")

        assert len(postings) == 1
        assert "StealthAI" in postings[0].title or "StealthAI" in postings[0].company_name
        assert postings[0].company_name == "StealthAI"

    def test_yc_portal_properties(self):
        """YC scraper should be Tier 3 (startup portal)."""
        scraper = YCAlgoliaScraper()
        assert scraper.portal == SourcePortal.YC
        assert scraper.tier == PortalTier.TIER_3


# ---------------------------------------------------------------------------
# WTTJAlgoliaScraper tests
# ---------------------------------------------------------------------------


class TestWTTJAlgoliaScraper:
    @pytest.mark.asyncio
    async def test_wttj_algolia_search(self):
        """Mock Algolia POST response, verify WTTJ JobPostings."""
        scraper = WTTJAlgoliaScraper()
        mock_response = _make_algolia_response([SAMPLE_WTTJ_HIT, SAMPLE_WTTJ_HIT_NO_SALARY])

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        assert len(results) >= 1
        for posting in results:
            assert isinstance(posting, JobPosting)
            assert posting.source_portal == SourcePortal.WTTJ

    def test_wttj_algolia_parse_hit(self):
        """Parse a WTTJ hit with company/location/salary."""
        scraper = WTTJAlgoliaScraper()
        posting = scraper._parse_wttj_hit(SAMPLE_WTTJ_HIT)

        assert posting is not None
        assert posting.title == "Senior AI Engineer"
        assert posting.company_name == "Datacraft"
        assert "Austin" in posting.location
        assert "TX" in posting.location
        assert posting.salary_min == 160000
        assert posting.salary_max == 220000
        assert posting.salary_range  # Non-empty
        assert "160" in posting.salary_range
        assert posting.work_model == "remote"
        assert posting.source_portal == SourcePortal.WTTJ
        assert posting.posted_date is not None
        assert "welcometothejungle.com" in posting.url

    def test_wttj_algolia_parse_hit_no_salary(self):
        """WTTJ hit without salary data should still parse correctly."""
        scraper = WTTJAlgoliaScraper()
        posting = scraper._parse_wttj_hit(SAMPLE_WTTJ_HIT_NO_SALARY)

        assert posting is not None
        assert posting.title == "ML Ops Engineer"
        assert posting.company_name == "CloudML Inc"
        assert posting.salary_range == ""
        assert posting.salary_min is None
        assert posting.salary_max is None
        assert posting.work_model == "hybrid"

    def test_wttj_algolia_parse_hit_empty(self):
        """Hit without a title returns None."""
        scraper = WTTJAlgoliaScraper()
        posting = scraper._parse_wttj_hit({"slug": "no-title"})
        assert posting is None

    def test_wttj_portal_properties(self):
        """WTTJ scraper should be Tier 2."""
        scraper = WTTJAlgoliaScraper()
        assert scraper.portal == SourcePortal.WTTJ
        assert scraper.tier == PortalTier.TIER_2


# ---------------------------------------------------------------------------
# Algolia pagination and error handling
# ---------------------------------------------------------------------------


class TestAlgoliaPagination:
    @pytest.mark.asyncio
    async def test_algolia_pagination(self):
        """Multiple pages should collect all hits."""
        scraper = YCAlgoliaScraper()

        page0_hit = {
            "name": "CompanyA",
            "slug": "company-a",
            "one_liner": "AI tools",
            "jobs": [{"title": "AI Engineer", "url": "https://example.com/a"}],
            "all_locations": [],
        }
        page1_hit = {
            "name": "CompanyB",
            "slug": "company-b",
            "one_liner": "ML platform",
            "jobs": [{"title": "ML Engineer", "url": "https://example.com/b"}],
            "all_locations": [],
        }

        responses = [
            _make_algolia_response([page0_hit], nb_pages=2, page=0),
            _make_algolia_response([page1_hit], nb_pages=2, page=1),
        ]

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=responses)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        # Should have results from both pages
        titles = [p.title for p in results]
        assert "AI Engineer" in titles
        assert "ML Engineer" in titles

    @pytest.mark.asyncio
    async def test_algolia_error_handling(self):
        """HTTP error should return empty results, not raise."""
        scraper = YCAlgoliaScraper()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = _make_error_response()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "Server Error",
            request=httpx.Request("POST", "https://test.algolia.net"),
            response=error_resp,
        ))

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        assert results == []

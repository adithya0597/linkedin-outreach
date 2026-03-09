"""Tests for Wellfound __NEXT_DATA__ scraper (src/scrapers/wellfound_nextdata.py)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.wellfound_nextdata import WellfoundNextDataScraper


# ---------------------------------------------------------------------------
# HTML fixtures with embedded __NEXT_DATA__
# ---------------------------------------------------------------------------

NEXT_DATA_WITH_JOBS = json.dumps({
    "props": {
        "pageProps": {
            "listings": [
                {
                    "title": "AI Engineer",
                    "company_name": "Acme AI",
                    "location": "San Francisco, CA",
                    "url": "https://wellfound.com/jobs/ai-engineer-123",
                    "remote": True,
                },
                {
                    "title": "ML Platform Engineer",
                    "companyName": "Beta ML",
                    "locationNames": ["New York, NY", "Remote"],
                    "slug": "ml-platform-456",
                },
            ]
        }
    }
})

NEXT_DATA_HTML = f"""
<html>
<head>
<script id="__NEXT_DATA__" type="application/json">{NEXT_DATA_WITH_JOBS}</script>
</head>
<body><div>Job listings page</div></body>
</html>
"""

NEXT_DATA_APOLLO = json.dumps({
    "props": {
        "pageProps": {
            "__APOLLO_STATE__": {
                "Startup:1001": {
                    "__typename": "StartupResult",
                    "name": "NeuralTech",
                    "jobs": [],
                },
                "JobListing:2001": {
                    "__typename": "JobListing",
                    "title": "Senior AI Researcher",
                    "startup": {"__ref": "Startup:1001"},
                    "locationNames": ["San Francisco, CA"],
                    "slug": "senior-ai-researcher",
                    "remote": False,
                    "compensation": {"min": 180000, "max": 250000},
                },
                "JobListing:2002": {
                    "__typename": "JobListing",
                    "title": "Founding Engineer",
                    "startup": {"name": "InlineStartup"},
                    "locationNames": ["Remote"],
                    "slug": "founding-engineer",
                    "remote": True,
                },
            }
        }
    }
})

APOLLO_HTML = f"""
<html>
<head>
<script id="__NEXT_DATA__" type="application/json">{NEXT_DATA_APOLLO}</script>
</head>
<body><div>Wellfound listings</div></body>
</html>
"""

NO_NEXT_DATA_HTML = """
<html>
<body>
<div>
  <a href="/jobs/some-job-slug">Software Engineer at StartupX</a>
  <a href="/jobs/another-job">AI Product Manager at StartupY</a>
  <a href="/about">About Us</a>
</div>
</body>
</html>
"""

EMPTY_HTML = "<html><body></body></html>"


# ---------------------------------------------------------------------------
# Helper to build mock httpx responses
# ---------------------------------------------------------------------------


def _make_response(html: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=html.encode(),
        request=httpx.Request("GET", "https://wellfound.com/role/l/software-engineer/ai"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWellfoundParseNextData:
    def test_wellfound_parse_next_data(self):
        """Mock HTML with __NEXT_DATA__ script tag containing job data."""
        scraper = WellfoundNextDataScraper()
        postings = scraper._parse_next_data(NEXT_DATA_HTML, keyword="ai")

        assert len(postings) >= 1
        titles = [p.title for p in postings]
        assert "AI Engineer" in titles

        ai_posting = next(p for p in postings if p.title == "AI Engineer")
        assert ai_posting.source_portal == SourcePortal.WELLFOUND

    def test_wellfound_parse_next_data_ml_engineer(self):
        """ML Platform Engineer with slug-based URL should be extracted."""
        scraper = WellfoundNextDataScraper()
        postings = scraper._parse_next_data(NEXT_DATA_HTML, keyword="ml")

        titles = [p.title for p in postings]
        assert "ML Platform Engineer" in titles

        ml_posting = next(p for p in postings if p.title == "ML Platform Engineer")
        assert "wellfound.com" in ml_posting.url


class TestWellfoundParseApolloState:
    def test_wellfound_parse_apollo_state(self):
        """Mock Apollo GraphQL cache with StartupResult/JobListing."""
        scraper = WellfoundNextDataScraper()
        postings = scraper._parse_next_data(APOLLO_HTML, keyword="ai")

        assert len(postings) >= 2

        titles = [p.title for p in postings]
        assert "Senior AI Researcher" in titles
        assert "Founding Engineer" in titles

        # Check startup name resolution from __ref
        researcher = next(p for p in postings if p.title == "Senior AI Researcher")
        assert researcher.company_name == "NeuralTech"

        # Check inline startup name
        founding = next(p for p in postings if p.title == "Founding Engineer")
        assert founding.company_name == "InlineStartup"

    def test_wellfound_parse_apollo_salary(self):
        """Salary should be parsed from compensation dict."""
        scraper = WellfoundNextDataScraper()
        postings = scraper._parse_next_data(APOLLO_HTML, keyword="ai")

        researcher = next(p for p in postings if p.title == "Senior AI Researcher")
        assert researcher.salary_range  # Non-empty salary range
        assert "180" in researcher.salary_range or "250" in researcher.salary_range


class TestWellfoundParseFallback:
    def test_wellfound_parse_fallback(self):
        """HTML without __NEXT_DATA__ falls back to link parsing."""
        scraper = WellfoundNextDataScraper()
        postings = scraper._parse_next_data(NO_NEXT_DATA_HTML, keyword="ai")

        assert len(postings) >= 1
        # Should find links with /jobs/ in href
        urls = [p.url for p in postings]
        assert any("wellfound.com/jobs/" in u for u in urls)


class TestWellfoundSearch:
    @pytest.mark.asyncio
    async def test_wellfound_search(self):
        """Mock httpx response with __NEXT_DATA__, verify JobPostings returned."""
        scraper = WellfoundNextDataScraper()
        mock_response = _make_response(NEXT_DATA_HTML)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        assert len(results) >= 1
        for posting in results:
            assert isinstance(posting, JobPosting)
            assert posting.source_portal == SourcePortal.WELLFOUND

    @pytest.mark.asyncio
    async def test_wellfound_empty_response(self):
        """Empty page returns empty list."""
        scraper = WellfoundNextDataScraper()
        mock_response = _make_response(EMPTY_HTML)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        assert results == []

    @pytest.mark.asyncio
    async def test_wellfound_deduplicates_urls(self):
        """Duplicate URLs from multiple keywords should be deduplicated."""
        scraper = WellfoundNextDataScraper()
        mock_response = _make_response(NEXT_DATA_HTML)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                # Search with two keywords that return the same page
                results = await scraper.search(keywords=["ai", "machine learning"], days=30)

        urls = [r.url for r in results if r.url]
        assert len(urls) == len(set(urls)), "URLs should be unique"

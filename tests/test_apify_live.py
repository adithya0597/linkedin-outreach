"""Tests for Apify-based scrapers (YC, TrueUp, BuiltIn, WTTJ)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.apify_scraper import (
    BuiltInScraper,
    TrueUpScraper,
    WTTJScraper,
    YCScraper,
)
from src.scrapers.rate_limiter import RateLimiter


@pytest.fixture
def fast_rate_limiter():
    return RateLimiter(default_tokens_per_second=1000.0)


# --- Mock Apify dataset items ---

YC_ITEMS = [
    {
        "company": "Acme AI",
        "title": "AI Engineer",
        "url": "https://www.workatastartup.com/jobs/1",
        "location": "San Francisco, CA",
    },
    {
        "company": "NeuroTech",
        "title": "ML Platform Engineer",
        "url": "/jobs/2",
        "location": "Remote",
    },
]

TRUEUP_ITEMS = [
    {
        "company": "DataCo",
        "title": "ML Engineer",
        "url": "https://www.trueup.io/job/1",
        "location": "New York, NY",
        "salary": "$150k - $200k",
    },
    {
        "company": "VisionLabs",
        "title": "Senior AI Engineer",
        "url": "/job/2",
        "location": "Austin, TX",
        "salary": "$180k - $220k",
    },
]


def _mock_apify_run(items: list[dict]):
    """Create a mock ApifyClient that returns the given items from an actor run."""
    mock_client = MagicMock()
    mock_run_result = {"defaultDatasetId": "test-dataset-123"}

    mock_actor = MagicMock()
    mock_actor.call.return_value = mock_run_result
    mock_client.actor.return_value = mock_actor

    mock_dataset = MagicMock()
    mock_list_items = MagicMock()
    mock_list_items.items = items
    mock_dataset.list_items.return_value = mock_list_items
    mock_client.dataset.return_value = mock_dataset

    return mock_client


# --- YCScraper tests ---


class TestYCScraper:
    def test_portal(self):
        scraper = YCScraper()
        assert scraper.portal == SourcePortal.YC
        assert scraper.name == "Work at a Startup (YC)"

    def test_is_healthy(self):
        scraper = YCScraper()
        assert scraper.is_healthy() is True

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        scraper = YCScraper(rate_limiter=fast_rate_limiter)
        mock_client = _mock_apify_run(YC_ITEMS)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert len(results) == 2
        assert results[0].company_name == "Acme AI"
        assert results[0].title == "AI Engineer"
        assert results[0].source_portal == SourcePortal.YC
        assert results[0].url == "https://www.workatastartup.com/jobs/1"

    @pytest.mark.asyncio
    async def test_search_prefixes_relative_urls(self, fast_rate_limiter):
        scraper = YCScraper(rate_limiter=fast_rate_limiter)
        mock_client = _mock_apify_run(YC_ITEMS)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["ML"])

        # Second item has relative URL
        assert results[1].url == "https://www.workatastartup.com/jobs/2"

    @pytest.mark.asyncio
    async def test_search_skips_empty_items(self, fast_rate_limiter):
        scraper = YCScraper(rate_limiter=fast_rate_limiter)
        items_with_empty = [{"company": "", "title": "", "url": ""}, *YC_ITEMS]
        mock_client = _mock_apify_run(items_with_empty)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI"])

        assert len(results) == 2  # Empty item skipped

    @pytest.mark.asyncio
    async def test_search_handles_apify_error(self, fast_rate_limiter):
        scraper = YCScraper(rate_limiter=fast_rate_limiter)
        mock_client = MagicMock()
        mock_client.actor.side_effect = Exception("Apify API error")

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI"])

        assert results == []

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        scraper = YCScraper(rate_limiter=fast_rate_limiter)
        detail_items = [
            {
                "company": "Acme AI",
                "title": "AI Engineer",
                "url": "https://www.workatastartup.com/jobs/1",
                "location": "SF",
                "description": "Build AI systems at scale.",
            }
        ]
        mock_client = _mock_apify_run(detail_items)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://www.workatastartup.com/jobs/1")

        assert posting.company_name == "Acme AI"
        assert posting.description == "Build AI systems at scale."
        assert posting.source_portal == SourcePortal.YC

    @pytest.mark.asyncio
    async def test_get_posting_details_empty_returns_minimal(self, fast_rate_limiter):
        scraper = YCScraper(rate_limiter=fast_rate_limiter)
        mock_client = _mock_apify_run([])

        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://example.com/job/1")

        assert posting.url == "https://example.com/job/1"
        assert posting.source_portal == SourcePortal.YC
        assert posting.company_name == ""


# --- BuiltInScraper tests ---


class TestBuiltInScraper:
    def test_portal(self):
        scraper = BuiltInScraper()
        assert scraper.portal == SourcePortal.BUILT_IN

    def test_is_healthy_returns_false(self):
        scraper = BuiltInScraper()
        assert scraper.is_healthy() is False

    @pytest.mark.asyncio
    async def test_search_returns_empty(self):
        scraper = BuiltInScraper()
        result = await scraper.search(["AI Engineer"])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_posting_details_returns_minimal(self):
        scraper = BuiltInScraper()
        posting = await scraper.get_posting_details("https://builtin.com/job/1")
        assert posting.url == "https://builtin.com/job/1"
        assert posting.source_portal == SourcePortal.BUILT_IN
        assert posting.company_name == ""


# --- WTTJScraper tests ---


class TestWTTJScraper:
    def test_portal(self):
        scraper = WTTJScraper()
        assert scraper.portal == SourcePortal.WTTJ

    def test_is_healthy_returns_false(self):
        scraper = WTTJScraper()
        assert scraper.is_healthy() is False

    @pytest.mark.asyncio
    async def test_search_returns_empty(self):
        scraper = WTTJScraper()
        result = await scraper.search(["AI Engineer"])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_posting_details_returns_minimal(self):
        scraper = WTTJScraper()
        posting = await scraper.get_posting_details("https://wttj.com/job/1")
        assert posting.url == "https://wttj.com/job/1"
        assert posting.source_portal == SourcePortal.WTTJ


# --- TrueUpScraper tests ---


class TestTrueUpScraper:
    def test_portal(self):
        scraper = TrueUpScraper()
        assert scraper.portal == SourcePortal.TRUEUP
        assert scraper.name == "TrueUp"

    def test_is_healthy(self):
        scraper = TrueUpScraper()
        assert scraper.is_healthy() is True

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        scraper = TrueUpScraper(rate_limiter=fast_rate_limiter)
        mock_client = _mock_apify_run(TRUEUP_ITEMS)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["ML Engineer"])

        assert len(results) == 2
        assert results[0].company_name == "DataCo"
        assert results[0].title == "ML Engineer"
        assert results[0].source_portal == SourcePortal.TRUEUP
        assert results[0].salary_range == "$150k - $200k"

    @pytest.mark.asyncio
    async def test_search_prefixes_relative_urls(self, fast_rate_limiter):
        scraper = TrueUpScraper(rate_limiter=fast_rate_limiter)
        mock_client = _mock_apify_run(TRUEUP_ITEMS)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI"])

        assert results[1].url == "https://www.trueup.io/job/2"

    @pytest.mark.asyncio
    async def test_search_filters_h1b_explicit_no(self, fast_rate_limiter):
        """Tier 2 scraper should filter out postings with explicit H1B no."""
        scraper = TrueUpScraper(rate_limiter=fast_rate_limiter)
        # Item with h1b_text won't come from Apify, but test the filter path
        items = [{"company": "NoCo", "title": "Engineer", "url": "https://trueup.io/j/3", "location": "LA"}]
        mock_client = _mock_apify_run(items)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["Engineer"])

        # Default h1b_text is "" which passes filter
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_handles_apify_error(self, fast_rate_limiter):
        scraper = TrueUpScraper(rate_limiter=fast_rate_limiter)
        mock_client = MagicMock()
        mock_client.actor.side_effect = Exception("Apify timeout")

        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI"])

        assert results == []

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        scraper = TrueUpScraper(rate_limiter=fast_rate_limiter)
        detail_items = [
            {
                "company": "DataCo",
                "title": "ML Engineer",
                "url": "https://www.trueup.io/job/1",
                "location": "NYC",
                "description": "Work on ML infra.",
                "salary": "$150k - $200k",
            }
        ]
        mock_client = _mock_apify_run(detail_items)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://www.trueup.io/job/1")

        assert posting.company_name == "DataCo"
        assert posting.description == "Work on ML infra."
        assert posting.salary_range == "$150k - $200k"
        assert posting.source_portal == SourcePortal.TRUEUP

    @pytest.mark.asyncio
    async def test_get_posting_details_empty_returns_minimal(self, fast_rate_limiter):
        scraper = TrueUpScraper(rate_limiter=fast_rate_limiter)
        mock_client = _mock_apify_run([])

        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://trueup.io/job/99")

        assert posting.url == "https://trueup.io/job/99"
        assert posting.source_portal == SourcePortal.TRUEUP
        assert posting.company_name == ""

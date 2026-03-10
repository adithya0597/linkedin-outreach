"""Tests for new source scrapers: Lever, JobSpy, HN Hiring, and JSON-LD parser.

Covers:
- src/scrapers/lever_scraper.py
- src/scrapers/jobspy_scraper.py
- src/scrapers/hn_hiring_scraper.py
- src/scrapers/jsonld_parser.py
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.models.job_posting import JobPosting
from src.scrapers.hn_hiring_scraper import HNHiringScraper
from src.scrapers.jobspy_scraper import JobSpyScraper
from src.scrapers.jsonld_parser import extract_jsonld_jobs
from src.scrapers.lever_scraper import LEVER_SLUGS, LeverScraper

# ---------------------------------------------------------------------------
# LeverScraper tests
# ---------------------------------------------------------------------------

SAMPLE_LEVER_JOBS = [
    {
        "text": "AI Engineer",
        "categories": {
            "department": "Engineering",
            "team": "AI/ML",
            "location": "San Francisco, CA",
            "commitment": "Full-time",
        },
        "descriptionPlain": (
            "We are building AI infrastructure.\n"
            "Salary: $160,000 - $220,000 per year.\n"
            "We provide H1B visa sponsorship for qualified candidates."
        ),
        "hostedUrl": "https://jobs.lever.co/testcompany/ai-engineer-123",
        "createdAt": 1709337600000,  # 2024-03-02 in ms
    },
    {
        "text": "Sales Manager",
        "categories": {
            "department": "Sales",
            "team": "Enterprise",
            "location": "New York, NY",
        },
        "descriptionPlain": "Manage enterprise sales team.",
        "hostedUrl": "https://jobs.lever.co/testcompany/sales-manager-456",
        "createdAt": 1709337600000,
    },
]


class TestLeverScraper:
    @pytest.mark.asyncio
    async def test_lever_search(self):
        """Mock Lever API response, verify JobPostings for AI roles."""
        scraper = LeverScraper()
        mock_response = httpx.Response(
            200,
            content=json.dumps(SAMPLE_LEVER_JOBS).encode(),
            request=httpx.Request("GET", "https://api.lever.co/v0/postings/testco?mode=json"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        # Temporarily add a slug for testing
        with (
            patch.dict(LEVER_SLUGS, {"test_company": "testco"}),
            patch.object(scraper, "_get_client", return_value=mock_client),
            patch.object(scraper, "_throttle", new_callable=AsyncMock),
        ):
            results = await scraper.search(keywords=["ai", "ml"], days=30)

        # Only AI Engineer should match (Sales Manager filtered out)
        assert len(results) == 1
        assert results[0].title == "AI Engineer"
        assert results[0].h1b_mentioned is True
        assert results[0].salary_min == 160000
        assert results[0].salary_max == 220000
        assert "lever.co" in results[0].url

    @pytest.mark.asyncio
    async def test_lever_empty_slugs(self):
        """No slugs configured returns empty list immediately."""
        scraper = LeverScraper()

        # Ensure LEVER_SLUGS is empty
        with patch.dict(LEVER_SLUGS, {}, clear=True):
            results = await scraper.search(keywords=["ai"], days=30)

        assert results == []

    @pytest.mark.asyncio
    async def test_lever_http_error(self):
        """HTTP error for a slug should skip that slug, not crash."""
        scraper = LeverScraper()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("GET", "https://api.lever.co/v0/postings/bad"),
            response=httpx.Response(404),
        ))

        with (
            patch.dict(LEVER_SLUGS, {"bad_company": "bad"}),
            patch.object(scraper, "_get_client", return_value=mock_client),
            patch.object(scraper, "_throttle", new_callable=AsyncMock),
        ):
            results = await scraper.search(keywords=["ai"], days=30)

        assert results == []

    def test_lever_name(self):
        """Lever scraper should report name as 'Lever'."""
        scraper = LeverScraper()
        assert scraper.name == "Lever"


# ---------------------------------------------------------------------------
# JobSpyScraper tests
# ---------------------------------------------------------------------------


class TestJobSpyScraper:
    def test_jobspy_not_installed(self):
        """Without jobspy library, is_healthy returns False."""
        scraper = JobSpyScraper()

        with patch.dict("sys.modules", {"jobspy": None}):
            # Force re-check by importing with None module
            with patch("builtins.__import__", side_effect=ImportError("no jobspy")):
                assert scraper.is_healthy() is False

    def test_jobspy_installed(self):
        """With jobspy library available, is_healthy returns True."""
        scraper = JobSpyScraper()

        mock_jobspy = MagicMock()
        with patch.dict("sys.modules", {"jobspy": mock_jobspy}):
            assert scraper.is_healthy() is True

    def test_jobspy_name(self):
        """JobSpy scraper should report name as 'JobSpy'."""
        scraper = JobSpyScraper()
        assert scraper.name == "JobSpy"

    @pytest.mark.asyncio
    async def test_jobspy_search_import_error(self):
        """search() returns empty when jobspy not installed."""
        scraper = JobSpyScraper()

        # Make the jobspy import inside search() fail
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "jobspy":
                raise ImportError("No module named 'jobspy'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            results = await scraper.search(keywords=["ai"], days=30)

        assert results == []


# ---------------------------------------------------------------------------
# HNHiringScraper tests
# ---------------------------------------------------------------------------

SAMPLE_HN_ITEMS = [
    {
        "text": "Acme AI | AI Engineer | San Francisco, CA | Remote | H1B",
        "id": "40001001",
        "url": "https://acmeai.com/jobs/1",
        "created_at": "2026-03-01T00:00:00Z",
    },
    {
        "text": "BetaML | ML Platform Engineer | New York, NY",
        "id": "40001002",
        "created_at": "2026-03-02T00:00:00Z",
    },
    {
        "text": "GammaCo | Senior Data Scientist | Remote | Hybrid",
        "id": "40001003",
        "created_at": "2026-03-03T00:00:00Z",
    },
]


class TestHNHiringScraper:
    @pytest.mark.asyncio
    async def test_hn_hiring_search(self):
        """Mock hnhiring.com response, verify parsing."""
        scraper = HNHiringScraper()
        mock_response = httpx.Response(
            200,
            content=json.dumps(SAMPLE_HN_ITEMS).encode(),
            request=httpx.Request("GET", "https://hnhiring.com/technologies/ai.json"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        assert len(results) >= 1
        for posting in results:
            assert isinstance(posting, JobPosting)
            assert posting.title  # Non-empty title
            assert posting.company_name  # Non-empty company

    def test_hn_hiring_parse_item(self):
        """Parse 'Company | Role | Location' format."""
        scraper = HNHiringScraper()

        item = {
            "text": "Acme AI | AI Engineer | San Francisco, CA | Remote | H1B",
            "id": "40001001",
            "url": "https://acmeai.com/jobs/1",
            "created_at": "2026-03-01T00:00:00Z",
        }

        posting = scraper._parse_hn_item(item)

        assert posting is not None
        assert posting.company_name == "Acme AI"
        assert posting.title == "AI Engineer"
        assert posting.location == "San Francisco, CA"
        assert posting.work_model == "remote"
        assert posting.h1b_mentioned is True
        assert posting.url == "https://acmeai.com/jobs/1"
        assert posting.posted_date is not None

    def test_hn_hiring_parse_item_no_url(self):
        """Item without URL builds HN link from ID."""
        scraper = HNHiringScraper()

        item = {
            "text": "StartupX | Founding Engineer | Remote",
            "id": "40002222",
        }

        posting = scraper._parse_hn_item(item)

        assert posting is not None
        assert "news.ycombinator.com/item?id=40002222" in posting.url

    def test_hn_hiring_parse_item_empty(self):
        """Empty item returns None."""
        scraper = HNHiringScraper()
        assert scraper._parse_hn_item({}) is None
        assert scraper._parse_hn_item({"text": ""}) is None

    def test_hn_hiring_parse_item_single_field(self):
        """Item with only company name generates fallback title."""
        scraper = HNHiringScraper()

        item = {"text": "SoloCompany", "id": "123"}
        posting = scraper._parse_hn_item(item)

        assert posting is not None
        assert posting.company_name == "SoloCompany"
        assert "Engineering" in posting.title  # Fallback title

    def test_hn_hiring_name(self):
        """HN Hiring scraper should report name as 'HN Hiring'."""
        scraper = HNHiringScraper()
        assert scraper.name == "HN Hiring"

    @pytest.mark.asyncio
    async def test_hn_hiring_404_fallback(self):
        """404 from hnhiring.com tries search endpoint, then Algolia fallback."""
        scraper = HNHiringScraper()

        # First call returns 404, second (search endpoint) also returns 404
        response_404 = httpx.Response(
            404,
            content=b"Not Found",
            request=httpx.Request("GET", "https://hnhiring.com/technologies/ai.json"),
        )
        response_search = httpx.Response(
            200,
            content=json.dumps(SAMPLE_HN_ITEMS[:1]).encode(),
            request=httpx.Request("GET", "https://hnhiring.com/search.json?q=ai"),
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=[response_404, response_search])

        with patch.object(scraper, "_get_client", return_value=mock_client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(keywords=["ai"], days=30)

        assert len(results) >= 1


# ---------------------------------------------------------------------------
# JSON-LD parser tests
# ---------------------------------------------------------------------------

SAMPLE_JSONLD_HTML = """
<html>
<head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Senior AI Engineer",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "TechStartup Inc"
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "San Francisco",
            "addressRegion": "CA",
            "addressCountry": "US"
        }
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "USD",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 180000,
            "maxValue": 250000
        }
    },
    "datePosted": "2026-03-01",
    "description": "Build AI systems. We offer <b>H1B visa sponsorship</b> for qualified candidates.",
    "url": "https://techstartup.com/careers/senior-ai-engineer",
    "jobLocationType": "remote"
}
</script>
</head>
<body><h1>Senior AI Engineer</h1></body>
</html>
"""

SAMPLE_JSONLD_LIST_HTML = """
<html>
<head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "ItemList",
    "itemListElement": [
        {
            "@type": "ListItem",
            "item": {
                "@type": "JobPosting",
                "title": "ML Engineer",
                "hiringOrganization": {"name": "ListCo"},
                "url": "https://listco.com/ml-engineer"
            }
        },
        {
            "@type": "ListItem",
            "item": {
                "@type": "JobPosting",
                "title": "Data Scientist",
                "hiringOrganization": {"name": "ListCo"},
                "url": "https://listco.com/data-scientist"
            }
        }
    ]
}
</script>
</head>
<body></body>
</html>
"""

SAMPLE_JSONLD_GRAPH_HTML = """
<html>
<head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@graph": [
        {
            "@type": "JobPosting",
            "title": "Backend Engineer",
            "hiringOrganization": {"name": "GraphCo"},
            "url": "https://graphco.com/backend"
        }
    ]
}
</script>
</head>
<body></body>
</html>
"""


class TestJsonLDExtract:
    def test_jsonld_extract_single_posting(self):
        """Extract single JobPosting from JSON-LD."""
        postings = extract_jsonld_jobs(SAMPLE_JSONLD_HTML, source_url="https://techstartup.com/careers")

        assert len(postings) == 1
        posting = postings[0]
        assert posting.title == "Senior AI Engineer"
        assert posting.company_name == "TechStartup Inc"
        assert "San Francisco" in posting.location
        assert "CA" in posting.location
        assert posting.salary_min == 180000
        assert posting.salary_max == 250000
        assert posting.salary_range  # Non-empty
        assert posting.h1b_mentioned is True
        assert posting.work_model == "remote"
        assert posting.posted_date is not None
        assert "techstartup.com" in posting.url

    def test_jsonld_extract_item_list(self):
        """Extract multiple JobPostings from ItemList JSON-LD."""
        postings = extract_jsonld_jobs(SAMPLE_JSONLD_LIST_HTML)

        assert len(postings) == 2
        titles = [p.title for p in postings]
        assert "ML Engineer" in titles
        assert "Data Scientist" in titles

    def test_jsonld_extract_graph(self):
        """Extract JobPostings from @graph JSON-LD."""
        postings = extract_jsonld_jobs(SAMPLE_JSONLD_GRAPH_HTML)

        assert len(postings) == 1
        assert postings[0].title == "Backend Engineer"
        assert postings[0].company_name == "GraphCo"

    def test_jsonld_extract_empty_html(self):
        """Empty HTML returns empty list."""
        assert extract_jsonld_jobs("") == []

    def test_jsonld_extract_no_jsonld(self):
        """HTML without JSON-LD returns empty list."""
        html = "<html><body><h1>No JSON-LD here</h1></body></html>"
        assert extract_jsonld_jobs(html) == []

    def test_jsonld_extract_invalid_json(self):
        """Invalid JSON in script tag is skipped."""
        html = """
        <html><head>
        <script type="application/ld+json">{this is not json}</script>
        </head><body></body></html>
        """
        result = extract_jsonld_jobs(html)
        assert result == []

    def test_jsonld_extract_non_job_type(self):
        """Non-JobPosting schema types are ignored."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Organization", "name": "SomeCo", "url": "https://someco.com"}
        </script>
        </head><body></body></html>
        """
        result = extract_jsonld_jobs(html)
        assert result == []

    def test_jsonld_extract_hiring_org_string(self):
        """hiringOrganization as string (not dict) should be handled."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@type": "JobPosting",
            "title": "AI Dev",
            "hiringOrganization": "StringCo"
        }
        </script>
        </head><body></body></html>
        """
        postings = extract_jsonld_jobs(html)
        assert len(postings) == 1
        assert postings[0].company_name == "StringCo"

"""Tests for httpx-based scrapers (mocked -- no real HTTP calls)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.config.enums import PortalTier, SourcePortal
from src.models.job_posting import JobPosting

# ---------------------------------------------------------------------------
# HTML fixtures matching the real portal structures
# ---------------------------------------------------------------------------

STARTUP_JOBS_HTML = """<html><body>
<div class="job-card">
  <h2 class="job-title"><a href="/jobs/ai-eng-acme">AI Engineer</a></h2>
  <div class="company-name">Acme AI</div>
  <div class="location">San Francisco, CA</div>
  <div class="salary">$150k - $200k</div>
</div>
<div class="job-card">
  <h2 class="job-title"><a href="/jobs/ml-eng-dataflow">ML Engineer</a></h2>
  <div class="company-name">DataFlow</div>
  <div class="location">New York, NY</div>
</div>
</body></html>"""

TOP_STARTUPS_HTML = """<html><head><title>Top Startup Jobs</title></head><body>
<div class="col-12 infinite-item">
  <div class="card card-body" id="item-card-filter">
    <div class="row">
      <div class="col-8 col-xl-5">
        <a href="http://acmeai.com/?utm_source=topstartups.io" id="startup-website-link" target="_blank">
          <h7>Acme AI</h7>
        </a>
        <br/>
        <a href="https://boards.greenhouse.io/acmeai/jobs/123" id="startup-website-link" target="_blank">
          <h5 id="job-title">AI Engineer</h5>
        </a>
        <h7><i class="fas fa-map-marker-alt"></i> San Francisco, CA</h7>
        <br/><h7><i class="fas fa-briefcase"></i> Experience: 3+ years</h7>
        <br/><h7><i class="far fa-clock"></i> Posted: 2 days ago</h7>
      </div>
      <div class="col-12 col-xl-3">
        <span class="badge bg-dark" id="company-size-tags">50-100 employees</span>
        <span class="badge bg-dark" id="funding-tags">Series A</span>
      </div>
      <div class="col-10 col-md-6 col-xl-3">
        <a class="btn btn-primary" href="https://boards.greenhouse.io/acmeai/jobs/123" id="apply-button" target="_blank">Apply</a>
      </div>
    </div>
  </div>
</div>
<div class="col-12 infinite-item">
  <div class="card card-body" id="item-card-filter">
    <div class="row">
      <div class="col-8 col-xl-5">
        <a href="http://vectordb.com" id="startup-website-link" target="_blank">
          <h7>VectorDB Inc</h7>
        </a>
        <br/>
        <a href="https://jobs.lever.co/vectordb/456" id="startup-website-link" target="_blank">
          <h5 id="job-title">ML Platform Engineer</h5>
        </a>
        <h7><i class="fas fa-map-marker-alt"></i> Remote (USA)</h7>
      </div>
      <div class="col-10 col-md-6 col-xl-3">
        <a class="btn btn-primary" href="https://jobs.lever.co/vectordb/456" id="apply-button" target="_blank">Apply</a>
      </div>
    </div>
  </div>
</div>
</body></html>"""

TOP_STARTUPS_404_HTML = """<html><head><title>404 - Page Not Found</title></head><body>
<h1>Page not found</h1>
</body></html>"""

AIJOBS_HTML = """<html><body>
<div class="container">
  <a class="tw-h-full card tw-card tw-block jobcardStyle1" href="https://aijobs.ai/job/senior-ai-engineer">
    <div class="tw-p-6 tw-h-full">
      <div class="tw-mb-5">
        <div class="tw-text-[#18191C] tw-text-lg tw-font-medium">
          Senior AI Engineer
        </div>
        <span class="tw-text-sm tw-text-[#767F8C]">Salary: from $190,000</span>
      </div>
      <div class="rt-single-icon-box">
        <div class="iconbox-content">
          <span class="tw-text-base tw-font-medium tw-text-[#18191C] tw-card-title">VectorDB Inc</span>
          <span class="tw-flex tw-items-center tw-gap-1 tw-text-[#18191C]">
            <span class="tw-location">United States</span>
          </span>
        </div>
      </div>
    </div>
  </a>
  <a class="tw-h-full card tw-card tw-block jobcardStyle1" href="https://aijobs.ai/job/ml-platform-engineer">
    <div class="tw-p-6 tw-h-full">
      <div class="tw-mb-5">
        <div class="tw-text-[#18191C] tw-text-lg tw-font-medium">
          ML Platform Engineer
        </div>
      </div>
      <div class="rt-single-icon-box">
        <div class="iconbox-content">
          <span class="tw-text-base tw-font-medium tw-text-[#18191C] tw-card-title">LLMCorp</span>
          <span class="tw-flex tw-items-center tw-gap-1 tw-text-[#18191C]">
            <span class="tw-location">San Francisco, CA</span>
          </span>
        </div>
      </div>
    </div>
  </a>
</div>
</body></html>"""

AIJOBS_DETAIL_HTML = """<html><body>
<div class="breadcrumbs-height job-details-title-box rt-pt-50 bg-white">
  <div class="container">
    <div class="post-info2">
      <div class="post-main-title2">Senior AI Engineer</div>
      <div class="tw-flex">
        <a href="https://aijobs.ai/company/vectordb">
          <p><span class="tw-text-[#474C54]">at</span><span>VectorDB Inc</span></p>
        </a>
      </div>
    </div>
  </div>
</div>
<div class="job-description-container">
  <p>We are looking for a Senior AI Engineer to build ML infrastructure.</p>
  <ul><li>3+ years experience</li><li>Python, PyTorch</li></ul>
</div>
<span class="tw-location">United States</span>
</body></html>"""

AIJOBS_H1B_NO_HTML = """<html><body>
<div class="container">
  <a class="tw-h-full card tw-card tw-block jobcardStyle1" href="https://aijobs.ai/job/no-sponsor">
    <div class="tw-p-6 tw-h-full">
      <div class="tw-mb-5">
        <div class="tw-text-[#18191C] tw-text-lg tw-font-medium">
          Data Scientist
        </div>
      </div>
      <div class="rt-single-icon-box">
        <div class="iconbox-content">
          <span class="tw-text-base tw-font-medium tw-text-[#18191C] tw-card-title">NoSponsorCo</span>
          <span class="tw-location">New York, NY</span>
        </div>
      </div>
    </div>
  </a>
</div>
</body></html>"""

EMPTY_HTML = "<html><body></body></html>"


def _mock_response(text: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=text,
        request=httpx.Request("GET", "https://example.com"),
    )


# ============================================================
# StartupJobsScraper Tests
# ============================================================


class TestStartupJobsScraper:

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(STARTUP_JOBS_HTML))

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert len(results) == 2
        assert results[0].title == "AI Engineer"
        assert results[0].company_name == "Acme AI"
        assert results[0].source_portal == SourcePortal.STARTUP_JOBS
        assert results[0].url == "https://startup.jobs/jobs/ai-eng-acme"
        assert results[0].location == "San Francisco, CA"
        assert results[0].salary_range == "$150k - $200k"

    @pytest.mark.asyncio
    async def test_search_second_card(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(STARTUP_JOBS_HTML))

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["ML"])

        assert results[1].title == "ML Engineer"
        assert results[1].company_name == "DataFlow"

    @pytest.mark.asyncio
    async def test_search_empty_html_returns_empty(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(EMPTY_HTML))

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results == []

    @pytest.mark.asyncio
    async def test_search_http_error_returns_empty(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results == []

    @pytest.mark.asyncio
    async def test_search_multiple_keywords(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(STARTUP_JOBS_HTML))

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer", "ML Engineer"])

        # 2 cards per keyword call = 4
        assert len(results) == 4

    @pytest.mark.asyncio
    async def test_tier_is_3(self):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        scraper = StartupJobsScraper()
        assert scraper.tier == PortalTier.TIER_3

    @pytest.mark.asyncio
    async def test_tier3_auto_passes_h1b(self):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        scraper = StartupJobsScraper()
        posting = JobPosting(h1b_text="will not sponsor")
        assert scraper.apply_h1b_filter(posting) is True

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        detail_html = """<html><body>
        <h1>AI Engineer</h1>
        <div class="company-name">Acme AI</div>
        <div class="job-description">Build ML systems</div>
        <div class="location">SF, CA</div>
        </body></html>"""

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(detail_html))

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://startup.jobs/jobs/1")

        assert posting.title == "AI Engineer"
        assert posting.company_name == "Acme AI"
        assert posting.description == "Build ML systems"
        assert posting.location == "SF, CA"
        assert posting.source_portal == SourcePortal.STARTUP_JOBS

    @pytest.mark.asyncio
    async def test_get_posting_details_http_error(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://startup.jobs/jobs/1")

        assert posting.url == "https://startup.jobs/jobs/1"
        assert posting.source_portal == SourcePortal.STARTUP_JOBS
        assert posting.title == ""


# ============================================================
# TopStartupsScraper Tests
# ============================================================


class TestTopStartupsScraper:

    @pytest.mark.asyncio
    async def test_healthy_by_default(self):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        scraper = TopStartupsScraper()
        assert scraper.is_healthy() is True

    @pytest.mark.asyncio
    async def test_search_with_cards(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(TOP_STARTUPS_HTML))

        scraper = TopStartupsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert len(results) == 2
        assert results[0].title == "AI Engineer"
        assert results[0].company_name == "Acme AI"
        assert results[0].url == "https://boards.greenhouse.io/acmeai/jobs/123"
        assert results[0].source_portal == SourcePortal.TOP_STARTUPS
        assert "San Francisco" in results[0].location

    @pytest.mark.asyncio
    async def test_search_second_card_details(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(TOP_STARTUPS_HTML))

        scraper = TopStartupsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["ML"])

        assert results[1].title == "ML Platform Engineer"
        assert results[1].company_name == "VectorDB Inc"
        assert results[1].url == "https://jobs.lever.co/vectordb/456"
        assert "Remote" in results[1].location

    @pytest.mark.asyncio
    async def test_search_empty_html_graceful(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(EMPTY_HTML))

        scraper = TopStartupsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results == []

    @pytest.mark.asyncio
    async def test_search_404_marks_unhealthy(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(TOP_STARTUPS_404_HTML))

        scraper = TopStartupsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results == []
        assert scraper.is_healthy() is False

    @pytest.mark.asyncio
    async def test_search_http_error_returns_empty(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        scraper = TopStartupsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results == []

    @pytest.mark.asyncio
    async def test_tier_is_3(self):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        scraper = TopStartupsScraper()
        assert scraper.tier == PortalTier.TIER_3

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        detail_html = """<html><body>
        <h1>AI Engineer at AcmeCo</h1>
        <div class="job-description">Build production ML pipelines</div>
        <div class="location">San Francisco, CA</div>
        </body></html>"""

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(detail_html))

        scraper = TopStartupsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://greenhouse.io/jobs/123")

        assert posting.title == "AI Engineer at AcmeCo"
        assert posting.description == "Build production ML pipelines"
        assert posting.source_portal == SourcePortal.TOP_STARTUPS

    @pytest.mark.asyncio
    async def test_get_posting_details_http_error(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import TopStartupsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        scraper = TopStartupsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://greenhouse.io/jobs/123")

        assert posting.url == "https://greenhouse.io/jobs/123"
        assert posting.source_portal == SourcePortal.TOP_STARTUPS


# ============================================================
# AIJobsScraper Tests
# ============================================================


class TestAIJobsScraper:

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(AIJOBS_HTML))

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert len(results) == 2
        assert results[0].title == "Senior AI Engineer"
        assert results[0].company_name == "VectorDB Inc"
        assert results[0].url == "https://aijobs.ai/job/senior-ai-engineer"
        assert results[0].location == "United States"
        assert results[0].source_portal == SourcePortal.AI_JOBS

    @pytest.mark.asyncio
    async def test_search_parses_salary(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(AIJOBS_HTML))

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results[0].salary_range == "from $190,000"

    @pytest.mark.asyncio
    async def test_search_second_card(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(AIJOBS_HTML))

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["ML"])

        assert results[1].title == "ML Platform Engineer"
        assert results[1].company_name == "LLMCorp"
        assert results[1].location == "San Francisco, CA"

    @pytest.mark.asyncio
    async def test_tier_is_2(self):
        from src.scrapers.httpx_scraper import AIJobsScraper

        scraper = AIJobsScraper()
        assert scraper.tier == PortalTier.TIER_2

    @pytest.mark.asyncio
    async def test_h1b_filter_rejects_no_sponsor(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        posting = JobPosting(h1b_text="will not sponsor")
        assert scraper.apply_h1b_filter(posting) is False

    @pytest.mark.asyncio
    async def test_h1b_filter_rejects_explicit_no(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        posting = JobPosting(h1b_text="explicit no")
        assert scraper.apply_h1b_filter(posting) is False

    @pytest.mark.asyncio
    async def test_h1b_filter_passes_unknown(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        posting = JobPosting(h1b_text="unknown")
        assert scraper.apply_h1b_filter(posting) is True

    @pytest.mark.asyncio
    async def test_h1b_filter_passes_empty(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        posting = JobPosting(h1b_text="")
        assert scraper.apply_h1b_filter(posting) is True

    @pytest.mark.asyncio
    async def test_search_empty_html_returns_empty(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(EMPTY_HTML))

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results == []

    @pytest.mark.asyncio
    async def test_search_http_error_returns_empty(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            results = await scraper.search(["AI Engineer"])

        assert results == []

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(AIJOBS_DETAIL_HTML))

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details(
                "https://aijobs.ai/job/senior-ai-engineer"
            )

        assert posting.title == "Senior AI Engineer"
        assert posting.company_name == "VectorDB Inc"
        assert "ML infrastructure" in posting.description
        assert posting.location == "United States"
        assert posting.source_portal == SourcePortal.AI_JOBS

    @pytest.mark.asyncio
    async def test_get_posting_details_http_error(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import AIJobsScraper

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        scraper = AIJobsScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_get_client", return_value=mock_client):
            posting = await scraper.get_posting_details("https://aijobs.ai/job/1")

        assert posting.url == "https://aijobs.ai/job/1"
        assert posting.source_portal == SourcePortal.AI_JOBS
        assert posting.title == ""


# ============================================================
# JobBoardAIScraper Tests
# ============================================================


# ============================================================
# Cross-scraper / integration tests
# ============================================================


class TestHttpxScraperBase:

    @pytest.mark.asyncio
    async def test_close_cleans_up_client(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        # Force client creation
        await scraper._get_client()
        assert scraper._client is not None
        await scraper.close()
        assert scraper._client is None

    @pytest.mark.asyncio
    async def test_get_client_reuses_instance(self, fast_rate_limiter):
        from src.scrapers.httpx_scraper import StartupJobsScraper

        scraper = StartupJobsScraper(rate_limiter=fast_rate_limiter)
        client1 = await scraper._get_client()
        client2 = await scraper._get_client()
        assert client1 is client2
        await scraper.close()

    @pytest.mark.asyncio
    async def test_all_scrapers_have_correct_portal(self):
        from src.scrapers.httpx_scraper import (
            AIJobsScraper,
            StartupJobsScraper,
            TopStartupsScraper,
        )

        assert StartupJobsScraper().portal == SourcePortal.STARTUP_JOBS
        assert TopStartupsScraper().portal == SourcePortal.TOP_STARTUPS
        assert AIJobsScraper().portal == SourcePortal.AI_JOBS

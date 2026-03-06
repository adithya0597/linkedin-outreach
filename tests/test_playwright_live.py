"""Tests for Playwright-based scrapers (mocked -- no real browser launches)."""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from src.config.enums import PortalTier, SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.rate_limiter import RateLimiter


@pytest.fixture
def fast_rate_limiter():
    return RateLimiter(default_tokens_per_second=1000.0)


def _make_mock_element(
    inner_text: str = "",
    href: str | None = None,
    is_present: bool = True,
):
    """Create a mock Playwright element with inner_text and get_attribute."""
    if not is_present:
        return None
    el = AsyncMock()
    el.inner_text = AsyncMock(return_value=inner_text)
    el.get_attribute = AsyncMock(return_value=href)
    return el


def _make_job_card(
    title: str = "AI Engineer",
    company: str = "TestCo",
    location: str = "San Francisco, CA",
    href: str = "https://example.com/job/1",
    salary: str = "",
    easy_apply: bool = False,
    top_applicant: bool = False,
    funding: str = "",
    company_size: str = "",
):
    """Create a mock job card element with sub-selectors."""
    card = AsyncMock()

    selector_map = {
        ".job-title": _make_mock_element(title),
        ".company-name": _make_mock_element(company),
        ".job-location": _make_mock_element(location),
        "a[href]": _make_mock_element(href=href),
        ".salary": _make_mock_element(salary),
        ".easy-apply-badge": _make_mock_element() if easy_apply else None,
        ".top-applicant-badge": _make_mock_element() if top_applicant else None,
        ".funding": _make_mock_element(funding),
        ".company-size": _make_mock_element(company_size),
    }

    async def query_selector(sel):
        return selector_map.get(sel)

    card.query_selector = AsyncMock(side_effect=query_selector)
    return card


def _make_mock_page(cards: list | None = None, detail_texts: dict | None = None):
    """Create a mock Playwright page."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()

    if cards is not None:
        page.query_selector_all = AsyncMock(return_value=cards)
    else:
        page.query_selector_all = AsyncMock(return_value=[])

    # No next/pagination button by default
    page.query_selector = AsyncMock(return_value=None)

    if detail_texts:
        # For get_posting_details: return elements for specific selectors
        async def detail_qs(sel):
            for key, value in detail_texts.items():
                if key in sel:
                    return _make_mock_element(value)
            return None

        page.query_selector = AsyncMock(side_effect=detail_qs)

    return page


def _make_mock_context(page):
    """Create a mock browser context wrapping a page."""
    ctx = AsyncMock()
    ctx.pages = [page]
    ctx.new_page = AsyncMock(return_value=page)
    ctx.close = AsyncMock()
    return ctx


# ============================================================
# JobrightScraper Tests
# ============================================================


class TestJobrightScraper:

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import JobrightScraper

        card = _make_job_card(
            title="AI Engineer",
            company="Acme AI",
            location="Remote",
            href="https://jobright.ai/jobs/123",
        )
        page = _make_mock_page(cards=[card])
        ctx = _make_mock_context(page)

        scraper = JobrightScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["AI engineer"])

        assert len(results) == 1
        assert results[0].title == "AI Engineer"
        assert results[0].company_name == "Acme AI"
        assert results[0].source_portal == SourcePortal.JOBRIGHT

    @pytest.mark.asyncio
    async def test_search_applies_h1b_filter(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import JobrightScraper

        card = _make_job_card(title="ML Engineer", company="NoSponsor Inc")
        page = _make_mock_page(cards=[card])
        ctx = _make_mock_context(page)

        scraper = JobrightScraper(rate_limiter=fast_rate_limiter)

        # Make apply_h1b_filter always reject
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock), \
             patch.object(scraper, "apply_h1b_filter", return_value=False):
            results = await scraper.search(["ML engineer"])

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_paginates(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import JobrightScraper

        card = _make_job_card(title="Data Scientist", company="PaginateCo")
        page = _make_mock_page(cards=[card])

        # Simulate a "next" button on first call, None on second
        next_btn = AsyncMock()
        next_btn.click = AsyncMock()
        call_count = 0

        original_qs = page.query_selector

        async def qs_side_effect(sel):
            nonlocal call_count
            if sel == "button.next-page":
                call_count += 1
                return next_btn if call_count <= 1 else None
            if original_qs.side_effect:
                return await original_qs.side_effect(sel)
            return None

        page.query_selector = AsyncMock(side_effect=qs_side_effect)
        ctx = _make_mock_context(page)

        scraper = JobrightScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["data science"])

        # Cards returned from two pages (same mock returns same card each time)
        assert len(results) >= 2
        assert next_btn.click.called

    @pytest.mark.asyncio
    async def test_search_skips_empty_title(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import JobrightScraper

        empty_card = _make_job_card(title="", company="GhostCo")
        page = _make_mock_page(cards=[empty_card])
        ctx = _make_mock_context(page)

        scraper = JobrightScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["engineer"])

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import JobrightScraper

        detail_texts = {
            "h1": "Senior AI Engineer",
            "company": "DetailCo",
            "description": "Build ML pipelines\nRequirements:\n- Python\n- PyTorch",
            "location": "Austin, TX",
        }
        page = _make_mock_page(detail_texts=detail_texts)
        ctx = _make_mock_context(page)

        scraper = JobrightScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            posting = await scraper.get_posting_details("https://jobright.ai/jobs/123")

        assert posting.title == "Senior AI Engineer"
        assert posting.source_portal == SourcePortal.JOBRIGHT
        assert posting.url == "https://jobright.ai/jobs/123"

    @pytest.mark.asyncio
    async def test_tier_is_2(self):
        from src.scrapers.playwright_scraper import JobrightScraper

        scraper = JobrightScraper()
        assert scraper.tier == PortalTier.TIER_2


# ============================================================
# HiringCafeScraper Tests
# ============================================================


class TestHiringCafeScraper:

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import HiringCafeScraper

        card = _make_job_card(
            title="ML Platform Engineer",
            company="CafeStartup",
            href="https://hiring.cafe/jobs/456",
        )
        page = _make_mock_page(cards=[card])
        ctx = _make_mock_context(page)

        scraper = HiringCafeScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["ML platform"])

        assert len(results) == 1
        assert results[0].title == "ML Platform Engineer"
        assert results[0].source_portal == SourcePortal.HIRING_CAFE

    @pytest.mark.asyncio
    async def test_tier3_auto_passes_h1b(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import HiringCafeScraper

        scraper = HiringCafeScraper(rate_limiter=fast_rate_limiter)
        assert scraper.tier == PortalTier.TIER_3

        posting = JobPosting(company_name="NoSponsor", h1b_text="no")
        assert scraper.apply_h1b_filter(posting) is True

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import HiringCafeScraper

        detail_texts = {
            "h1": "AI Backend Engineer",
            "company": "CafeCo",
            "description": "Full job description here.",
            "location": "New York, NY",
        }
        page = _make_mock_page(detail_texts=detail_texts)
        ctx = _make_mock_context(page)

        scraper = HiringCafeScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            posting = await scraper.get_posting_details("https://hiring.cafe/jobs/456")

        assert posting.title == "AI Backend Engineer"
        assert posting.source_portal == SourcePortal.HIRING_CAFE

    @pytest.mark.asyncio
    async def test_search_multiple_keywords(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import HiringCafeScraper

        card = _make_job_card(title="Engineer", company="Multi")
        page = _make_mock_page(cards=[card])
        ctx = _make_mock_context(page)

        scraper = HiringCafeScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["AI", "ML", "LLM"])

        # Same card returned for each keyword = 3 results
        assert len(results) == 3


# ============================================================
# WellfoundScraper Tests
# ============================================================


class TestWellfoundScraper:

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import WellfoundScraper

        card = _make_job_card(
            title="Founding AI Engineer",
            company="StartupXYZ",
            location="Remote",
            href="https://wellfound.com/company/startupxyz/jobs/123",
            salary="$150k-$200k",
        )
        page = _make_mock_page(cards=[card])
        ctx = _make_mock_context(page)

        scraper = WellfoundScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["AI engineer"])

        assert len(results) == 1
        assert results[0].title == "Founding AI Engineer"
        assert results[0].salary_range == "$150k-$200k"
        assert results[0].work_model == "remote"
        assert results[0].source_portal == SourcePortal.WELLFOUND

    @pytest.mark.asyncio
    async def test_tier3_auto_passes_h1b(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import WellfoundScraper

        scraper = WellfoundScraper(rate_limiter=fast_rate_limiter)
        assert scraper.tier == PortalTier.TIER_3

        posting = JobPosting(company_name="NoSponsor", h1b_text="will not sponsor")
        assert scraper.apply_h1b_filter(posting) is True

    @pytest.mark.asyncio
    async def test_work_model_detection(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import WellfoundScraper

        remote_card = _make_job_card(location="Remote - US")
        hybrid_card = _make_job_card(location="San Francisco (Hybrid)")
        onsite_card = _make_job_card(location="New York, NY")

        page = _make_mock_page(cards=[remote_card, hybrid_card, onsite_card])
        ctx = _make_mock_context(page)

        scraper = WellfoundScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["engineer"])

        assert results[0].work_model == "remote"
        assert results[1].work_model == "hybrid"
        assert results[2].work_model == "onsite"

    @pytest.mark.asyncio
    async def test_get_posting_details(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import WellfoundScraper

        detail_texts = {
            "h1": "Senior ML Engineer",
            "company": "WFCo",
            "description": "Build production ML systems.",
            "location": "Remote",
            "salary": "$160k-$220k",
        }
        page = _make_mock_page(detail_texts=detail_texts)
        ctx = _make_mock_context(page)

        scraper = WellfoundScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            posting = await scraper.get_posting_details("https://wellfound.com/jobs/123")

        assert posting.title == "Senior ML Engineer"
        assert posting.salary_range == "$160k-$220k"
        assert posting.source_portal == SourcePortal.WELLFOUND


# ============================================================
# LinkedInScraper Tests
# ============================================================


class TestLinkedInScraper:

    @pytest.mark.asyncio
    async def test_search_returns_postings(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import LinkedInScraper

        card = _make_job_card(
            title="AI Platform Engineer",
            company="LinkedCo",
            href="https://www.linkedin.com/jobs/view/123",
        )
        page = _make_mock_page(cards=[card])
        # Override query_selector_all to return cards for ".job-card-container"
        page.query_selector_all = AsyncMock(return_value=[card])
        ctx = _make_mock_context(page)

        scraper = LinkedInScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["AI platform"])

        assert len(results) == 1
        assert results[0].title == "AI Platform Engineer"
        assert results[0].source_portal == SourcePortal.LINKEDIN

    @pytest.mark.asyncio
    async def test_search_skips_easy_apply(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import LinkedInScraper

        easy_card = _make_job_card(
            title="Easy Apply Job",
            company="EasyCo",
            easy_apply=True,
        )
        normal_card = _make_job_card(
            title="Normal Job",
            company="NormalCo",
            easy_apply=False,
        )
        page = _make_mock_page()
        page.query_selector_all = AsyncMock(return_value=[easy_card, normal_card])
        ctx = _make_mock_context(page)

        scraper = LinkedInScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["engineer"])

        assert len(results) == 1
        assert results[0].title == "Normal Job"
        assert results[0].is_easy_apply is False

    @pytest.mark.asyncio
    async def test_search_detects_top_applicant(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import LinkedInScraper

        card = _make_job_card(
            title="Top Job",
            company="TopCo",
            top_applicant=True,
        )
        page = _make_mock_page()
        page.query_selector_all = AsyncMock(return_value=[card])
        ctx = _make_mock_context(page)

        scraper = LinkedInScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            results = await scraper.search(["engineer"])

        assert len(results) == 1
        assert results[0].is_top_applicant is True

    @pytest.mark.asyncio
    async def test_search_applies_h1b_filter(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import LinkedInScraper

        card = _make_job_card(title="AI Engineer", company="RejectCo")
        page = _make_mock_page()
        page.query_selector_all = AsyncMock(return_value=[card])
        ctx = _make_mock_context(page)

        scraper = LinkedInScraper(rate_limiter=fast_rate_limiter)
        assert scraper.tier == PortalTier.TIER_1

        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock), \
             patch.object(scraper, "apply_h1b_filter", return_value=False):
            results = await scraper.search(["AI engineer"])

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_posting_details_detects_h1b(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import LinkedInScraper

        detail_texts = {
            "h1": "ML Engineer",
            "company": "SponsorCo",
            "description": "We are hiring.\nWe offer H1B visa sponsorship for qualified candidates.\nApply now.",
            "location": "Austin, TX",
        }
        page = _make_mock_page(detail_texts=detail_texts)
        ctx = _make_mock_context(page)

        scraper = LinkedInScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            posting = await scraper.get_posting_details("https://linkedin.com/jobs/view/123")

        assert posting.h1b_mentioned is True
        assert "H1B" in posting.h1b_text or "h1b" in posting.h1b_text.lower()

    @pytest.mark.asyncio
    async def test_get_posting_details_no_h1b(self, fast_rate_limiter):
        from src.scrapers.playwright_scraper import LinkedInScraper

        detail_texts = {
            "h1": "Software Engineer",
            "company": "PlainCo",
            "description": "We build great software.\nApply now.",
            "location": "Seattle, WA",
        }
        page = _make_mock_page(detail_texts=detail_texts)
        ctx = _make_mock_context(page)

        scraper = LinkedInScraper(rate_limiter=fast_rate_limiter)
        with patch.object(scraper, "_launch", return_value=ctx), \
             patch.object(scraper, "_close", new_callable=AsyncMock):
            posting = await scraper.get_posting_details("https://linkedin.com/jobs/view/456")

        assert posting.h1b_mentioned is False
        assert posting.h1b_text == ""


# ============================================================
# Chrome Lock Tests
# ============================================================


class TestChromeLock:

    @pytest.mark.asyncio
    async def test_chrome_lock_prevents_concurrent_access(self, fast_rate_limiter):
        """Verify that _chrome_profile_lock serializes browser access."""
        from src.scrapers.playwright_scraper import JobrightScraper, HiringCafeScraper

        launch_order: list[str] = []

        card = _make_job_card(title="Test", company="LockCo")
        page = _make_mock_page(cards=[card])
        ctx = _make_mock_context(page)

        async def mock_launch_jobright(self_ref):
            launch_order.append("jobright_start")
            await asyncio.sleep(0.05)
            launch_order.append("jobright_end")
            return ctx

        async def mock_launch_hiring(self_ref):
            launch_order.append("hiring_start")
            await asyncio.sleep(0.05)
            launch_order.append("hiring_end")
            return ctx

        scraper1 = JobrightScraper(rate_limiter=fast_rate_limiter)
        scraper2 = HiringCafeScraper(rate_limiter=fast_rate_limiter)

        with patch.object(JobrightScraper, "_launch", mock_launch_jobright), \
             patch.object(HiringCafeScraper, "_launch", mock_launch_hiring), \
             patch.object(JobrightScraper, "_close", new_callable=AsyncMock), \
             patch.object(HiringCafeScraper, "_close", new_callable=AsyncMock):
            await asyncio.gather(
                scraper1.search(["test"]),
                scraper2.search(["test"]),
            )

        # Because of the lock, one scraper must fully finish before the other starts.
        # The second "start" must come after the first "end".
        first_start = launch_order[0]
        if first_start == "jobright_start":
            assert launch_order.index("jobright_end") < launch_order.index("hiring_start")
        else:
            assert launch_order.index("hiring_end") < launch_order.index("jobright_start")

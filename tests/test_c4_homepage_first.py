"""Tests for HomepageFirstScraper base class and portal implementations."""

from unittest.mock import AsyncMock, patch

import pytest

from src.config.enums import SourcePortal
from src.scrapers.homepage_first_scraper import (
    HiringCafeHomepageFirstScraper,
    HomepageFirstScraper,
    StartupJobsHomepageFirstScraper,
    WellfoundHomepageFirstScraper,
    WTTJHomepageFirstScraper,
    YCHomepageFirstScraper,
)


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.goto = AsyncMock()
    page.inner_text = AsyncMock(return_value="Job listings")
    page.wait_for_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock()
    return page


@pytest.fixture
def mock_behavior():
    behavior = AsyncMock()
    behavior.human_delay = AsyncMock()
    behavior.smooth_scroll = AsyncMock()
    return behavior


# ---------------------------------------------------------------------------
# Base class tests
# ---------------------------------------------------------------------------


class TestHomepageFirstBase:
    def test_is_blocked_detects_captcha(self):
        scraper = WellfoundHomepageFirstScraper()
        assert scraper._is_blocked("Please complete the CAPTCHA to continue")
        assert scraper._is_blocked("403 Forbidden - Access Denied")
        assert scraper._is_blocked("Checking your browser before accessing")
        assert not scraper._is_blocked("Software Engineer Jobs - 50 results")

    def test_is_blocked_case_insensitive(self):
        scraper = WellfoundHomepageFirstScraper()
        assert scraper._is_blocked("CAPTCHA required")
        assert scraper._is_blocked("Access Denied")
        assert scraper._is_blocked("JUST A MOMENT...")

    @pytest.mark.asyncio
    async def test_establish_session_success(self, mock_page, mock_behavior):
        scraper = WellfoundHomepageFirstScraper()
        mock_page.inner_text = AsyncMock(return_value="Find your next startup job")
        result = await scraper._establish_session(mock_page, mock_behavior)
        assert result is True
        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_establish_session_blocked(self, mock_page, mock_behavior):
        scraper = WellfoundHomepageFirstScraper()
        mock_page.inner_text = AsyncMock(return_value="Please verify you are human")
        result = await scraper._establish_session(mock_page, mock_behavior)
        assert result is False

    @pytest.mark.asyncio
    async def test_establish_session_navigation_error(self, mock_page, mock_behavior):
        scraper = WellfoundHomepageFirstScraper()
        mock_page.goto = AsyncMock(side_effect=Exception("timeout"))
        result = await scraper._establish_session(mock_page, mock_behavior)
        assert result is False

    def test_subclass_must_implement_parse_card(self):
        """Base class _parse_card raises NotImplementedError."""
        scraper = HomepageFirstScraper(SourcePortal.WELLFOUND)
        with pytest.raises(NotImplementedError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                scraper._parse_card(AsyncMock(), AsyncMock())
            )


# ---------------------------------------------------------------------------
# Wellfound
# ---------------------------------------------------------------------------


class TestWellfoundHomepageFirst:
    def test_portal_is_wellfound(self):
        scraper = WellfoundHomepageFirstScraper()
        assert scraper.portal == SourcePortal.WELLFOUND

    def test_homepage_url(self):
        scraper = WellfoundHomepageFirstScraper()
        assert scraper.HOMEPAGE_URL == "https://wellfound.com/"

    def test_search_url_template(self):
        scraper = WellfoundHomepageFirstScraper()
        assert "{kw}" in scraper.SEARCH_URL_TEMPLATE
        assert "wellfound.com" in scraper.SEARCH_URL_TEMPLATE

    @pytest.mark.asyncio
    async def test_search_calls_homepage_then_search(self):
        scraper = WellfoundHomepageFirstScraper()
        with patch.object(scraper, "_launch", new_callable=AsyncMock) as mock_launch, \
             patch.object(scraper, "_close", new_callable=AsyncMock) as mock_close, \
             patch.object(scraper, "_new_page_with_behavior") as mock_new_page, \
             patch.object(scraper, "_throttle", new_callable=AsyncMock):
            mock_page = AsyncMock()
            mock_page.inner_text = AsyncMock(return_value="Startup jobs")
            mock_page.wait_for_selector = AsyncMock()
            mock_page.query_selector_all = AsyncMock(return_value=[])
            mock_page.goto = AsyncMock()

            mock_beh = AsyncMock()
            mock_new_page.return_value = (mock_page, mock_beh)

            await scraper.search(["AI Engineer"], days=7)

            mock_launch.assert_called_once()
            mock_close.assert_called_once()
            # Verify homepage was visited first, then search URL
            calls = mock_page.goto.call_args_list
            assert len(calls) >= 2
            assert "wellfound.com/" in str(calls[0])
            assert "software-engineer" in str(calls[1])

    @pytest.mark.asyncio
    async def test_search_stops_on_homepage_block(self):
        scraper = WellfoundHomepageFirstScraper()
        with patch.object(scraper, "_launch", new_callable=AsyncMock), \
             patch.object(scraper, "_close", new_callable=AsyncMock), \
             patch.object(scraper, "_new_page_with_behavior") as mock_new_page:
            mock_page = AsyncMock()
            mock_page.inner_text = AsyncMock(return_value="Please verify you are human")
            mock_page.goto = AsyncMock()

            mock_new_page.return_value = (mock_page, AsyncMock())

            result = await scraper.search(["AI Engineer"])
            assert result == []


# ---------------------------------------------------------------------------
# startup.jobs
# ---------------------------------------------------------------------------


class TestStartupJobsHomepageFirst:
    def test_portal_is_startup_jobs(self):
        scraper = StartupJobsHomepageFirstScraper()
        assert scraper.portal == SourcePortal.STARTUP_JOBS

    def test_homepage_url(self):
        scraper = StartupJobsHomepageFirstScraper()
        assert scraper.HOMEPAGE_URL == "https://startup.jobs/"

    @pytest.mark.asyncio
    async def test_search_flow(self):
        scraper = StartupJobsHomepageFirstScraper()
        with patch.object(scraper, "_launch", new_callable=AsyncMock), \
             patch.object(scraper, "_close", new_callable=AsyncMock), \
             patch.object(scraper, "_new_page_with_behavior") as mock_new_page, \
             patch.object(scraper, "_throttle", new_callable=AsyncMock):
            mock_page = AsyncMock()
            mock_page.inner_text = AsyncMock(return_value="Find jobs at startups")
            mock_page.wait_for_selector = AsyncMock()
            mock_page.query_selector_all = AsyncMock(return_value=[])
            mock_page.goto = AsyncMock()

            mock_new_page.return_value = (mock_page, AsyncMock())

            result = await scraper.search(["ML Engineer"])
            assert result == []


# ---------------------------------------------------------------------------
# Hiring Cafe
# ---------------------------------------------------------------------------


class TestHiringCafeHomepageFirst:
    def test_portal_is_hiring_cafe(self):
        scraper = HiringCafeHomepageFirstScraper()
        assert scraper.portal == SourcePortal.HIRING_CAFE

    def test_search_url_template(self):
        scraper = HiringCafeHomepageFirstScraper()
        assert "hiring.cafe" in scraper.SEARCH_URL_TEMPLATE
        assert "country=US" in scraper.SEARCH_URL_TEMPLATE

    def test_homepage_url(self):
        scraper = HiringCafeHomepageFirstScraper()
        assert scraper.HOMEPAGE_URL == "https://hiring.cafe/"


# ---------------------------------------------------------------------------
# YC (Work at a Startup)
# ---------------------------------------------------------------------------


class TestYCHomepageFirst:
    def test_portal_is_yc(self):
        scraper = YCHomepageFirstScraper()
        assert scraper.portal == SourcePortal.YC

    def test_homepage_url(self):
        scraper = YCHomepageFirstScraper()
        assert scraper.HOMEPAGE_URL == "https://www.workatastartup.com/"

    def test_search_url_template(self):
        scraper = YCHomepageFirstScraper()
        assert "workatastartup.com" in scraper.SEARCH_URL_TEMPLATE


# ---------------------------------------------------------------------------
# WTTJ (Welcome to the Jungle)
# ---------------------------------------------------------------------------


class TestWTTJHomepageFirst:
    def test_portal_is_wttj(self):
        scraper = WTTJHomepageFirstScraper()
        assert scraper.portal == SourcePortal.WTTJ

    def test_search_url_has_region(self):
        scraper = WTTJHomepageFirstScraper()
        assert "North%20America" in scraper.SEARCH_URL_TEMPLATE

    def test_homepage_url(self):
        scraper = WTTJHomepageFirstScraper()
        assert scraper.HOMEPAGE_URL == "https://www.welcometothejungle.com/"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_homepage_first_scrapers_in_registry(self):
        from src.scrapers.registry import build_default_registry

        registry = build_default_registry()

        wellfound = registry.get_scraper("wellfound")
        assert isinstance(wellfound, WellfoundHomepageFirstScraper)

        startup_jobs = registry.get_scraper("startup_jobs")
        assert isinstance(startup_jobs, StartupJobsHomepageFirstScraper)

        hiring_cafe = registry.get_scraper("hiring_cafe")
        assert isinstance(hiring_cafe, HiringCafeHomepageFirstScraper)

        yc = registry.get_scraper("yc")
        assert isinstance(yc, YCHomepageFirstScraper)

        wttj = registry.get_scraper("wttj")
        assert isinstance(wttj, WTTJHomepageFirstScraper)

    def test_registry_count_unchanged(self):
        """Swapping 5 scrapers should not change total count (still 17)."""
        from src.scrapers.registry import build_default_registry

        registry = build_default_registry()
        assert len(registry.get_all_scrapers()) == 17

    def test_all_homepage_first_are_patchright_subclass(self):
        """All 5 homepage-first scrapers extend PatchrightScraper."""
        from src.scrapers.patchright_scraper import PatchrightScraper
        from src.scrapers.registry import build_default_registry

        registry = build_default_registry()
        for name in ("wellfound", "startup_jobs", "hiring_cafe", "yc", "wttj"):
            scraper = registry.get_scraper(name)
            assert isinstance(scraper, PatchrightScraper), f"{name} is not a PatchrightScraper"
            assert isinstance(scraper, HomepageFirstScraper), f"{name} is not a HomepageFirstScraper"

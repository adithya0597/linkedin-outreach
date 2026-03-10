"""Tests for Built In and JobBoard AI Patchright scrapers."""
from unittest.mock import AsyncMock, patch

import pytest

from src.config.enums import SourcePortal
from src.scrapers.builtin_scraper import BuiltInPatchrightScraper
from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper


class TestBuiltInScraper:
    def test_portal_is_builtin(self):
        scraper = BuiltInPatchrightScraper()
        assert scraper.portal == SourcePortal.BUILT_IN

    def test_homepage_url(self):
        scraper = BuiltInPatchrightScraper()
        assert scraper.HOMEPAGE_URL == "https://builtin.com/"

    def test_search_url_template(self):
        scraper = BuiltInPatchrightScraper()
        assert "builtin.com/jobs" in scraper.SEARCH_URL_TEMPLATE

    @pytest.mark.asyncio
    async def test_search_flow(self):
        scraper = BuiltInPatchrightScraper()
        with patch.object(scraper, "_launch", new_callable=AsyncMock), \
             patch.object(scraper, "_close", new_callable=AsyncMock), \
             patch.object(scraper, "_new_page_with_behavior") as mock_new_page:
            mock_page = AsyncMock()
            mock_page.inner_text = AsyncMock(return_value="Built In Jobs")
            mock_page.wait_for_selector = AsyncMock()
            mock_page.query_selector_all = AsyncMock(return_value=[])
            mock_page.goto = AsyncMock()

            mock_new_page.return_value = (mock_page, AsyncMock())

            results = await scraper.search(["AI Engineer"])
            assert results == []

    def test_is_blocked_check(self):
        scraper = BuiltInPatchrightScraper()
        assert scraper._is_blocked("Access Denied by HUMAN Security")
        assert not scraper._is_blocked("AI Engineer Jobs at startups")


class TestJobBoardAIScraper:
    def test_portal_is_jobboard_ai(self):
        scraper = JobBoardAIPatchrightScraper()
        assert scraper.portal == SourcePortal.JOBBOARD_AI

    def test_homepage_url(self):
        scraper = JobBoardAIPatchrightScraper()
        assert "thejobboard.ai" in scraper.HOMEPAGE_URL

    def test_search_url_template(self):
        scraper = JobBoardAIPatchrightScraper()
        assert "thejobboard.ai/jobs" in scraper.SEARCH_URL_TEMPLATE

    @pytest.mark.asyncio
    async def test_search_flow(self):
        scraper = JobBoardAIPatchrightScraper()
        with patch.object(scraper, "_launch", new_callable=AsyncMock), \
             patch.object(scraper, "_close", new_callable=AsyncMock), \
             patch.object(scraper, "_new_page_with_behavior") as mock_new_page:
            mock_page = AsyncMock()
            mock_page.inner_text = AsyncMock(return_value="AI Job Board")
            mock_page.wait_for_selector = AsyncMock()
            mock_page.query_selector_all = AsyncMock(return_value=[])
            mock_page.goto = AsyncMock()

            mock_new_page.return_value = (mock_page, AsyncMock())

            results = await scraper.search(["ML Engineer"])
            assert results == []


class TestRegistryIntegration:
    def test_builtin_in_registry(self):
        from src.scrapers.registry import build_default_registry
        registry = build_default_registry()
        scraper = registry.get_scraper("builtin")
        assert isinstance(scraper, BuiltInPatchrightScraper)

    def test_jobboard_ai_in_registry(self):
        from src.scrapers.registry import build_default_registry
        registry = build_default_registry()
        scraper = registry.get_scraper("jobboard_ai")
        assert isinstance(scraper, JobBoardAIPatchrightScraper)

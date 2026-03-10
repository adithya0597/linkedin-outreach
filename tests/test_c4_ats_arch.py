"""Tests for ATS slug fixes, HN Hiring, and architecture improvements."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scrapers.ats_scraper import (
    ASHBY_SLUGS,
    GREENHOUSE_SLUGS,
    AshbyScraper,
    GreenhouseScraper,
    _load_slugs_from_config,
)
from src.scrapers.hn_hiring_scraper import HNHiringScraper
from src.scrapers.concurrent_runner import ConcurrentScanRunner, ScanResult, SCRAPER_TIMEOUT
from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState
from src.scrapers.base_scraper import BaseScraper
from src.config.enums import SourcePortal


class TestAshbySlugCleanup:
    def test_disqualified_slugs_removed(self):
        assert "cursor" not in ASHBY_SLUGS
        assert "hippocratic_ai" not in ASHBY_SLUGS
        assert "evenup" not in ASHBY_SLUGS

    def test_valid_slugs_present(self):
        assert "llamaindex" in ASHBY_SLUGS
        assert "langchain" in ASHBY_SLUGS
        assert "norm_ai" in ASHBY_SLUGS
        assert "cinder" in ASHBY_SLUGS

    def test_slug_count(self):
        assert len(ASHBY_SLUGS) == 4


class TestConfigSlugLoading:
    def test_load_ashby_slugs_from_config(self):
        slugs = _load_slugs_from_config("ashby")
        # Config has ats_slugs for ashby
        assert isinstance(slugs, dict)

    def test_load_nonexistent_portal(self):
        slugs = _load_slugs_from_config("nonexistent_portal")
        assert slugs == {}


class TestHNHiringDirect:
    @pytest.mark.asyncio
    async def test_search_uses_algolia_directly(self):
        scraper = HNHiringScraper()
        with patch.object(scraper, "_get_client") as mock_client, \
             patch.object(scraper, "_search_hn_algolia", new_callable=AsyncMock) as mock_algolia:
            mock_algolia.return_value = []

            results = await scraper.search(["AI"], days=30)

            # Should call Algolia directly, not hnhiring.com
            mock_algolia.assert_called()

    def test_portal_is_hn_hiring(self):
        scraper = HNHiringScraper()
        assert "HN" in scraper.name


class TestConcurrentRunnerTimeout:
    def test_scraper_timeout_constant(self):
        assert SCRAPER_TIMEOUT == 120

    @pytest.mark.asyncio
    async def test_timeout_produces_timeout_outcome(self):
        runner = ConcurrentScanRunner(max_concurrent=1)

        class SlowScraper:
            name = "slow_portal"
            async def search(self, query, **kwargs):
                await asyncio.sleep(200)  # Exceeds timeout
                return []

        # Use a very short timeout for testing
        with patch("src.scrapers.concurrent_runner.SCRAPER_TIMEOUT", 0.1):
            results = await runner.run_all([SlowScraper()], query=None, filters={"days": 7})

        assert len(runner.results) == 1
        assert runner.results[0].outcome == "timeout"


class TestConcurrentRunnerCircuitBreaker:
    @pytest.mark.asyncio
    async def test_mcp_stub_skipped(self):
        runner = ConcurrentScanRunner()

        class Wrapper:
            def __init__(self):
                self.name = "Built In"
                self.portal_name = "Built In"
                from src.scrapers.mcp_scraper import MCPPlaywrightScraper
                self._scraper = MCPPlaywrightScraper(SourcePortal.BUILT_IN)

            async def search(self, query, **kw):
                return []

        wrapper = Wrapper()
        results = await runner.run_all([wrapper], query=None, filters={"days": 7})

        assert len(runner.results) == 1
        assert runner.results[0].outcome == "skipped"


class TestScanResult:
    def test_scan_result_default_outcome(self):
        r = ScanResult(portal="test", entries=[])
        assert r.outcome == "success"

    def test_scan_result_with_error(self):
        r = ScanResult(portal="test", entries=[], error="boom", outcome="error")
        assert r.outcome == "error"


class TestBaseScraperClose:
    @pytest.mark.asyncio
    async def test_base_scraper_has_close(self):
        # BaseScraper is abstract, but close() should be available
        assert hasattr(BaseScraper, "close")

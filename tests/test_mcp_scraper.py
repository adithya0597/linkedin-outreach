"""Tests for MCP Playwright scraper stub (src/scrapers/mcp_scraper.py)."""

from __future__ import annotations

import pytest

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.mcp_scraper import MCPPlaywrightScraper

# ---------------------------------------------------------------------------
# MCPPlaywrightScraper tests
# ---------------------------------------------------------------------------


class TestMCPPlaywrightScraper:
    def test_mcp_scraper_is_healthy(self):
        """MCP scrapers always report healthy (external browser session)."""
        scraper = MCPPlaywrightScraper(portal=SourcePortal.LINKEDIN)
        assert scraper.is_healthy() is True

    def test_mcp_scraper_is_healthy_any_portal(self):
        """Healthy check works regardless of portal."""
        for portal in [SourcePortal.WELLFOUND, SourcePortal.BUILT_IN, SourcePortal.JOBBOARD_AI]:
            scraper = MCPPlaywrightScraper(portal=portal)
            assert scraper.is_healthy() is True

    @pytest.mark.asyncio
    async def test_mcp_scraper_search_returns_empty(self):
        """search() is a stub -- always returns empty list."""
        scraper = MCPPlaywrightScraper(portal=SourcePortal.LINKEDIN)

        results = await scraper.search(keywords=["ai", "ml"], days=30)

        assert results == []
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_mcp_scraper_get_posting_details(self):
        """get_posting_details returns a minimal JobPosting with URL and portal."""
        scraper = MCPPlaywrightScraper(portal=SourcePortal.LINKEDIN)
        url = "https://www.linkedin.com/jobs/view/12345"

        posting = await scraper.get_posting_details(url)

        assert isinstance(posting, JobPosting)
        assert posting.url == url
        assert posting.source_portal == SourcePortal.LINKEDIN

    def test_mcp_scraper_portal_and_name(self):
        """Verify portal property and name property."""
        scraper = MCPPlaywrightScraper(portal=SourcePortal.BUILT_IN, skill_name="scan-builtin")
        assert scraper.portal == SourcePortal.BUILT_IN
        assert scraper.name == SourcePortal.BUILT_IN.value

    def test_mcp_scraper_default_skill_name(self):
        """Default skill name is derived from portal value."""
        scraper = MCPPlaywrightScraper(portal=SourcePortal.JOBBOARD_AI)
        # The _skill_name is built from portal.value
        assert scraper._skill_name == "scan-jobboard-ai"

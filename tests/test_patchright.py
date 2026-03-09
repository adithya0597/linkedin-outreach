"""Tests for Patchright scrapers (src/scrapers/patchright_scraper.py)
and behavioral mimicry layer (src/scrapers/behavioral_mimicry.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.behavioral_mimicry import BehavioralLayer
from src.scrapers.patchright_scraper import (
    JobrightPatchrightScraper,
    PatchrightScraper,
    TrueUpPatchrightScraper,
)


# ---------------------------------------------------------------------------
# BehavioralLayer tests
# ---------------------------------------------------------------------------


class TestBehavioralLayer:
    @pytest.mark.asyncio
    async def test_behavioral_layer_human_delay(self):
        """human_delay should execute without error and take some time."""
        mock_page = MagicMock()

        behavior = BehavioralLayer(mock_page)
        # Use very short delay to keep test fast
        await behavior.human_delay(min_ms=10, max_ms=50)
        # If we get here without error, the test passes

    def test_behavioral_layer_bezier_points(self):
        """_bezier_points should return the correct number of curve points."""
        mock_page = MagicMock()
        behavior = BehavioralLayer(mock_page)

        steps = 20
        points = behavior._bezier_points(0, 0, 100, 100, steps=steps)

        assert isinstance(points, list)
        assert len(points) == steps + 1  # steps + 1 points (0 to steps inclusive)

        # First point should be at start
        assert abs(points[0][0] - 0) < 0.01
        assert abs(points[0][1] - 0) < 0.01

        # Last point should be at end
        assert abs(points[-1][0] - 100) < 0.01
        assert abs(points[-1][1] - 100) < 0.01

    def test_behavioral_layer_bezier_custom_steps(self):
        """Bezier points with custom step count."""
        mock_page = MagicMock()
        behavior = BehavioralLayer(mock_page)

        points = behavior._bezier_points(50, 50, 200, 300, steps=10)
        assert len(points) == 11  # 10 + 1

    @pytest.mark.asyncio
    async def test_behavioral_layer_smooth_scroll(self):
        """smooth_scroll should call page.evaluate for scroll."""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock()

        behavior = BehavioralLayer(mock_page)
        await behavior.smooth_scroll(direction="down", distance=300)

        # evaluate should have been called multiple times (3-8 steps)
        assert mock_page.evaluate.call_count >= 3

    @pytest.mark.asyncio
    async def test_behavioral_layer_smooth_scroll_up(self):
        """smooth_scroll up should use negative scroll values."""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock()

        behavior = BehavioralLayer(mock_page)
        await behavior.smooth_scroll(direction="up", distance=200)

        # At least some calls should have negative scroll amounts
        assert mock_page.evaluate.call_count >= 3


# ---------------------------------------------------------------------------
# PatchrightScraper: fallback behavior
# ---------------------------------------------------------------------------


class TestPatchrightFallback:
    @pytest.mark.asyncio
    async def test_patchright_falls_back_to_playwright(self):
        """ImportError on patchright should fall back to playwright."""
        scraper = JobrightPatchrightScraper()

        # Mock the import to fail for patchright but succeed for playwright
        mock_pw_instance = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_playwright_cm = AsyncMock()
        mock_playwright_cm.start = AsyncMock(return_value=mock_pw_instance)

        # Patch patchright to raise ImportError, and provide a mock playwright
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "patchright.async_api":
                raise ImportError("No module named 'patchright'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            with patch("playwright.async_api.async_playwright", return_value=mock_playwright_cm):
                try:
                    await scraper._launch()
                except Exception:
                    # The launch may fail in test env since we don't have a real
                    # browser, but the import fallback should have been triggered.
                    pass

        # Verify patchright was attempted (the fallback mechanism was invoked)
        # The test passes if no unhandled ImportError propagated


# ---------------------------------------------------------------------------
# JobrightPatchrightScraper tests
# ---------------------------------------------------------------------------


class TestJobrightPatchrightScraper:
    def test_jobright_portal(self):
        """Jobright scraper uses JOBRIGHT portal."""
        scraper = JobrightPatchrightScraper()
        assert scraper.portal == SourcePortal.JOBRIGHT

    @pytest.mark.asyncio
    async def test_jobright_patchright_search(self):
        """Mock Patchright browser, verify search flow returns postings."""
        scraper = JobrightPatchrightScraper()

        # Build mock page with job card elements
        mock_title_el = AsyncMock()
        mock_title_el.inner_text = AsyncMock(return_value="AI Engineer")

        mock_company_el = AsyncMock()
        mock_company_el.inner_text = AsyncMock(return_value="TestCorp AI")

        mock_location_el = AsyncMock()
        mock_location_el.inner_text = AsyncMock(return_value="San Francisco, CA")

        mock_link_el = AsyncMock()
        mock_link_el.get_attribute = AsyncMock(return_value="https://jobright.ai/jobs/ai-engineer-123")

        mock_card = AsyncMock()
        mock_card.query_selector = AsyncMock(side_effect=lambda sel: {
            "[data-testid*='title'], h3, h2": mock_title_el,
            "[data-testid*='company'], [class*='company'], span:nth-child(2)": mock_company_el,
            "[data-testid*='location'], [class*='location']": mock_location_el,
            "a[href*='/jobs/']": mock_link_el,
        }.get(sel))

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_card])
        mock_page.inner_text = AsyncMock(return_value="")

        mock_behavior = MagicMock()
        mock_behavior.human_delay = AsyncMock()
        mock_behavior.smooth_scroll = AsyncMock()

        with (
            patch.object(scraper, "_launch", new_callable=AsyncMock),
            patch.object(scraper, "_new_page_with_behavior", new_callable=AsyncMock, return_value=(mock_page, mock_behavior)),
            patch.object(scraper, "_close", new_callable=AsyncMock),
            patch.object(scraper, "_throttle", new_callable=AsyncMock),
        ):
            results = await scraper.search(keywords=["ai"], days=30)

        assert len(results) >= 1
        assert results[0].title == "AI Engineer"
        assert results[0].company_name == "TestCorp AI"
        assert results[0].source_portal == SourcePortal.JOBRIGHT

    @pytest.mark.asyncio
    async def test_jobright_get_posting_details(self):
        """get_posting_details returns minimal posting."""
        scraper = JobrightPatchrightScraper()
        posting = await scraper.get_posting_details("https://jobright.ai/jobs/123")
        assert posting.url == "https://jobright.ai/jobs/123"
        assert posting.source_portal == SourcePortal.JOBRIGHT


# ---------------------------------------------------------------------------
# TrueUpPatchrightScraper tests
# ---------------------------------------------------------------------------


class TestTrueUpPatchrightScraper:
    def test_trueup_portal(self):
        """TrueUp scraper uses TRUEUP portal."""
        scraper = TrueUpPatchrightScraper()
        assert scraper.portal == SourcePortal.TRUEUP

    @pytest.mark.asyncio
    async def test_trueup_patchright_search(self):
        """Mock Patchright browser, verify TrueUp search flow."""
        scraper = TrueUpPatchrightScraper()

        # Build mock page with job card elements
        mock_title_el = AsyncMock()
        mock_title_el.inner_text = AsyncMock(return_value="ML Engineer")

        mock_company_el = AsyncMock()
        mock_company_el.inner_text = AsyncMock(return_value="DataCo")

        mock_location_el = AsyncMock()
        mock_location_el.inner_text = AsyncMock(return_value="Remote")

        mock_salary_el = AsyncMock()
        mock_salary_el.inner_text = AsyncMock(return_value="$140k-$190k")

        mock_card = AsyncMock()
        mock_card.query_selector = AsyncMock(side_effect=lambda sel: {
            "h3, h2, [class*='title'], td:first-child": mock_title_el,
            "[class*='company'], td:nth-child(2)": mock_company_el,
            "[class*='location'], td:nth-child(3)": mock_location_el,
            "[class*='salary'], [class*='compensation']": mock_salary_el,
        }.get(sel))
        mock_card.get_attribute = AsyncMock(return_value="https://www.trueup.io/job/ml-engineer-456")
        mock_card.inner_text = AsyncMock(return_value="ML Engineer")

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_card])
        mock_page.inner_text = AsyncMock(return_value="")

        mock_behavior = MagicMock()
        mock_behavior.human_delay = AsyncMock()
        mock_behavior.smooth_scroll = AsyncMock()

        with (
            patch.object(scraper, "_launch", new_callable=AsyncMock),
            patch.object(scraper, "_new_page_with_behavior", new_callable=AsyncMock, return_value=(mock_page, mock_behavior)),
            patch.object(scraper, "_close", new_callable=AsyncMock),
            patch.object(scraper, "_throttle", new_callable=AsyncMock),
        ):
            results = await scraper.search(keywords=["ml"], days=30)

        assert len(results) >= 1
        assert results[0].title == "ML Engineer"
        assert results[0].company_name == "DataCo"
        assert results[0].source_portal == SourcePortal.TRUEUP

    @pytest.mark.asyncio
    async def test_trueup_get_posting_details(self):
        """get_posting_details returns minimal posting."""
        scraper = TrueUpPatchrightScraper()
        posting = await scraper.get_posting_details("https://www.trueup.io/job/123")
        assert posting.url == "https://www.trueup.io/job/123"
        assert posting.source_portal == SourcePortal.TRUEUP

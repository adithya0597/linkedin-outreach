"""Tests for automated LinkedIn Patchright scraper."""
import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.linkedin_scraper import (
    MAX_PAGES,
    MAX_SCANS_PER_DAY,
    LinkedInPatchrightScraper,
)


class TestLinkedInSafety:
    def test_max_pages_is_5(self):
        assert MAX_PAGES == 5

    def test_max_scans_per_day_is_1(self):
        assert MAX_SCANS_PER_DAY == 1

    def test_captcha_detection(self):
        scraper = LinkedInPatchrightScraper()
        assert scraper._is_captcha("Please complete the security verification to continue")
        assert scraper._is_captcha("Let's do a quick security check")
        assert scraper._is_captcha("CAPTCHA required")
        assert not scraper._is_captcha("Software Engineer - 25 results")

    def test_daily_limit_check(self, tmp_path):
        scraper = LinkedInPatchrightScraper()
        with patch("src.scrapers.linkedin_scraper.SCAN_RECORD_PATH", tmp_path):
            # No record = can scan
            assert scraper._can_scan_today()

            # Record a scan
            today = date.today().isoformat()
            record = tmp_path / f"linkedin_{today}.json"
            record.write_text(json.dumps({"scan_count": 1}))

            # Now limit reached
            assert not scraper._can_scan_today()

    def test_record_scan(self, tmp_path):
        scraper = LinkedInPatchrightScraper()
        with patch("src.scrapers.linkedin_scraper.SCAN_RECORD_PATH", tmp_path):
            scraper._record_scan(10)

            today = date.today().isoformat()
            record = tmp_path / f"linkedin_{today}.json"
            assert record.exists()
            data = json.loads(record.read_text())
            assert data["scan_count"] == 1
            assert data["results"] == 10


class TestLinkedInLogin:
    @pytest.mark.asyncio
    async def test_check_login_logged_in(self):
        scraper = LinkedInPatchrightScraper()
        mock_page = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Feed | LinkedIn - Job search")
        mock_page.url = "https://www.linkedin.com/feed/"

        result = await scraper._check_login(mock_page)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_login_not_logged_in(self):
        scraper = LinkedInPatchrightScraper()
        mock_page = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Sign in to LinkedIn")
        mock_page.url = "https://www.linkedin.com/login"

        result = await scraper._check_login(mock_page)
        assert result is False


class TestLinkedInCardParsing:
    @pytest.mark.asyncio
    async def test_parse_card_with_data(self):
        scraper = LinkedInPatchrightScraper()

        mock_card = AsyncMock()

        # Mock title element
        mock_title = AsyncMock()
        mock_title.inner_text = AsyncMock(return_value="AI Engineer")

        # Mock company element
        mock_company = AsyncMock()
        mock_company.inner_text = AsyncMock(return_value="Acme AI")

        # Mock location element
        mock_location = AsyncMock()
        mock_location.inner_text = AsyncMock(return_value="San Francisco, CA")

        # Mock link element
        mock_link = AsyncMock()
        mock_link.get_attribute = AsyncMock(
            return_value="https://www.linkedin.com/jobs/view/12345"
        )

        # Configure card selectors
        async def mock_query_selector(selector):
            if "h3" in selector or "heading" in selector or "title" in selector:
                return mock_title
            if "h4" in selector or "company" in selector:
                return mock_company
            if "location" in selector or "metadata" in selector:
                return mock_location
            if "easy-apply" in selector:
                return None  # No easy apply
            if "top-applicant" in selector:
                return None
            if "jobs/view" in selector:
                return mock_link
            return None

        mock_card.query_selector = mock_query_selector

        posting = await scraper._parse_linkedin_card(mock_card)
        assert posting is not None
        assert posting.title == "AI Engineer"
        assert posting.company_name == "Acme AI"
        assert posting.location == "San Francisco, CA"
        assert posting.source_portal == SourcePortal.LINKEDIN
        assert not posting.is_easy_apply

    @pytest.mark.asyncio
    async def test_parse_card_empty_title_returns_none(self):
        scraper = LinkedInPatchrightScraper()
        mock_card = AsyncMock()
        mock_card.query_selector = AsyncMock(return_value=None)

        result = await scraper._parse_linkedin_card(mock_card)
        assert result is None


class TestLinkedInSearchFlow:
    @pytest.mark.asyncio
    async def test_search_respects_daily_limit(self):
        scraper = LinkedInPatchrightScraper()
        with patch.object(scraper, "_can_scan_today", return_value=False):
            results = await scraper.search(["AI Engineer"])
            assert results == []

    @pytest.mark.asyncio
    async def test_search_homepage_first(self, tmp_path):
        scraper = LinkedInPatchrightScraper()

        with (
            patch.object(scraper, "_launch", new_callable=AsyncMock),
            patch.object(scraper, "_close", new_callable=AsyncMock),
            patch.object(scraper, "_can_scan_today", return_value=True),
            patch.object(scraper, "_new_page_with_behavior") as mock_new_page,
            patch("src.scrapers.linkedin_scraper.SCAN_RECORD_PATH", tmp_path),
        ):
            mock_page = AsyncMock()
            mock_page.goto = AsyncMock()
            mock_page.inner_text = AsyncMock(return_value="LinkedIn Jobs")
            mock_page.url = "https://www.linkedin.com/jobs/"
            mock_page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
            mock_page.query_selector_all = AsyncMock(return_value=[])
            mock_page.query_selector = AsyncMock(return_value=None)

            mock_beh = AsyncMock()
            mock_new_page.return_value = (mock_page, mock_beh)

            await scraper.search(["AI Engineer"], days=7)

            # Should have navigated to jobs homepage first
            calls = mock_page.goto.call_args_list
            assert any("linkedin.com/jobs/" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_search_stops_on_captcha(self, tmp_path):
        scraper = LinkedInPatchrightScraper()

        with (
            patch.object(scraper, "_launch", new_callable=AsyncMock),
            patch.object(scraper, "_close", new_callable=AsyncMock),
            patch.object(scraper, "_can_scan_today", return_value=True),
            patch.object(scraper, "_new_page_with_behavior") as mock_new_page,
            patch("src.scrapers.linkedin_scraper.SCAN_RECORD_PATH", tmp_path),
        ):
            mock_page = AsyncMock()
            mock_page.goto = AsyncMock()
            # First call: homepage OK, second call: CAPTCHA
            mock_page.inner_text = AsyncMock(
                side_effect=[
                    "LinkedIn Jobs",  # homepage check (_check_login)
                    "LinkedIn Jobs",  # homepage CAPTCHA check
                    "Please complete the security verification",  # captcha on search
                ]
            )
            mock_page.url = "https://www.linkedin.com/jobs/"

            mock_beh = AsyncMock()
            mock_new_page.return_value = (mock_page, mock_beh)

            results = await scraper.search(["AI Engineer"], days=7)
            assert results == []


class TestLinkedInPortal:
    def test_portal_is_linkedin(self):
        scraper = LinkedInPatchrightScraper()
        assert scraper.portal == SourcePortal.LINKEDIN
        assert scraper.name == "LinkedIn"


class TestLinkedInRegistryIntegration:
    def test_linkedin_in_registry(self):
        from src.scrapers.registry import build_default_registry

        registry = build_default_registry()
        scraper = registry.get_scraper("linkedin")
        assert isinstance(scraper, LinkedInPatchrightScraper)

"""Tests for HiringCafeHttpxScraper -- keyword filter + Tier 2 reclassification."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.config.enums import PortalTier, SourcePortal
from src.scrapers.httpx_scraper import HiringCafeHttpxScraper, _matches_ai_keywords


class TestKeywordFilter:
    """AI/ML keyword filter for Hiring Cafe results."""

    def test_ai_engineer_passes(self):
        assert _matches_ai_keywords("AI Engineer")

    def test_ml_engineer_passes(self):
        assert _matches_ai_keywords("ML Engineer")

    def test_llm_engineer_passes(self):
        assert _matches_ai_keywords("LLM Engineer")

    def test_data_scientist_passes(self):
        assert _matches_ai_keywords("Senior Data Scientist")

    def test_founding_engineer_passes(self):
        assert _matches_ai_keywords("Founding Engineer")

    def test_genai_passes(self):
        assert _matches_ai_keywords("GenAI Platform Engineer")

    def test_hvac_filtered(self):
        assert not _matches_ai_keywords("HVAC Counter Sales Rock Star")

    def test_nurse_filtered(self):
        assert not _matches_ai_keywords("School Registered Nurse")

    def test_truck_driver_filtered(self):
        assert not _matches_ai_keywords("CDL Truck Driver")

    def test_department_match(self):
        assert _matches_ai_keywords("Software Engineer", department="Machine Learning")

    def test_custom_keywords(self):
        assert _matches_ai_keywords("Python Developer", keywords=["python"])
        assert not _matches_ai_keywords("Python Developer", keywords=["java"])


class TestHiringCafeTier:
    """Hiring Cafe must be Tier 2 (H1B cross-check required)."""

    def test_portal_tier_is_2(self):
        assert SourcePortal.HIRING_CAFE.tier == PortalTier.TIER_2

    def test_scraper_tier_is_2(self):
        scraper = HiringCafeHttpxScraper()
        assert scraper.tier == PortalTier.TIER_2

    def test_not_tier_3(self):
        """Hiring Cafe is NOT a startup portal -- it's a general aggregator."""
        assert SourcePortal.HIRING_CAFE.tier != PortalTier.TIER_3


class TestHiringCafeSearch:
    """Mock search tests for HiringCafeHttpxScraper."""

    @pytest.mark.asyncio
    async def test_ai_job_passes_filter(self):
        scraper = HiringCafeHttpxScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{
                "job_information": {"title": "AI Engineer"},
                "v5_processed_job_data": {
                    "company_name": "TestCo",
                    "formatted_workplace_location": "San Francisco, CA",
                    "workplace_type": "Remote",
                    "department": "Engineering",
                    "yearly_min_compensation": 150000,
                    "yearly_max_compensation": 200000,
                    "visa_sponsorship": True,
                    "estimated_publish_date": "2026-03-01T00:00:00Z",
                },
                "enriched_company_data": {"name": "TestCo"},
                "apply_url": "https://testco.com/apply",
                "requisition_id": "123",
            }]
        }
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response
        with patch.object(scraper, "_get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                # Use lowercase keywords to match the filter's lowercased comparison
                results = await scraper.search(["ai engineer"], days=30)

        assert len(results) >= 1
        assert results[0].title == "AI Engineer"
        assert results[0].company_name == "TestCo"

    @pytest.mark.asyncio
    async def test_non_ai_job_filtered_out(self):
        scraper = HiringCafeHttpxScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{
                "job_information": {"title": "HVAC Counter Sales Rock Star"},
                "v5_processed_job_data": {
                    "company_name": "HVACCo",
                    "formatted_workplace_location": "Dallas, TX",
                    "workplace_type": "On-site",
                    "department": "Sales",
                },
                "enriched_company_data": {"name": "HVACCo"},
                "apply_url": "https://hvacco.com/apply",
                "requisition_id": "456",
            }]
        }
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response
        with patch.object(scraper, "_get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                # Even with broad AI keywords, HVAC should be filtered out
                results = await scraper.search(["ai engineer"], days=30)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_salary_parsing(self):
        scraper = HiringCafeHttpxScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{
                "job_information": {"title": "ML Engineer"},
                "v5_processed_job_data": {
                    "company_name": "MLCo",
                    "formatted_workplace_location": "NYC",
                    "workplace_type": "",
                    "department": "",
                    "yearly_min_compensation": 150000,
                    "yearly_max_compensation": 200000,
                },
                "enriched_company_data": {},
                "apply_url": "https://mlco.com",
                "requisition_id": "789",
            }]
        }
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response
        with patch.object(scraper, "_get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(["ml engineer"], days=30)

        assert len(results) == 1
        assert results[0].salary_range == "$150k-$200k/yr"

    @pytest.mark.asyncio
    async def test_h1b_visa_no_filtered_by_tier2(self):
        """Tier 2 scraper filters out postings where visa_sponsorship=False."""
        scraper = HiringCafeHttpxScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{
                "job_information": {"title": "AI Engineer"},
                "v5_processed_job_data": {
                    "company_name": "VisaCo",
                    "formatted_workplace_location": "Remote",
                    "workplace_type": "Remote",
                    "department": "",
                    "visa_sponsorship": False,
                },
                "enriched_company_data": {},
                "apply_url": "https://visaco.com",
                "requisition_id": "101",
            }]
        }
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response
        with patch.object(scraper, "_get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(["ai engineer"], days=30)

        # Tier 2 apply_h1b_filter rejects h1b_text="no"
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_h1b_visa_yes_passes_tier2(self):
        """Tier 2 scraper keeps postings where visa_sponsorship=True."""
        scraper = HiringCafeHttpxScraper()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{
                "job_information": {"title": "AI Engineer"},
                "v5_processed_job_data": {
                    "company_name": "GoodCo",
                    "formatted_workplace_location": "Remote",
                    "workplace_type": "Remote",
                    "department": "",
                    "visa_sponsorship": True,
                },
                "enriched_company_data": {},
                "apply_url": "https://goodco.com",
                "requisition_id": "102",
            }]
        }
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response
        with patch.object(scraper, "_get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(scraper, "_throttle", new_callable=AsyncMock):
                results = await scraper.search(["ai engineer"], days=30)

        assert len(results) == 1
        assert results[0].h1b_text == "yes"
        assert results[0].h1b_mentioned is True

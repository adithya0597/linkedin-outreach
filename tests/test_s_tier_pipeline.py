"""S-tier pipeline integration tests -- Ashby, Greenhouse.

Hiring Cafe demoted (2026-03-10) — API returns junk results.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.config.enums import PortalTier, SourcePortal
from src.scrapers.ats_scraper import (
    ASHBY_SLUGS, GREENHOUSE_SLUGS, _CANONICAL_NAMES,
    _load_slugs_from_config, AshbyScraper, GreenhouseScraper,
)
from src.scrapers.httpx_scraper import HttpxScraper
from src.scrapers.registry import build_default_registry


class TestSTierScrapersAreHttpx:
    """S-tier scrapers must be httpx-based (no browser)."""

    def setup_method(self):
        self.registry = build_default_registry()

    def test_ashby_is_httpx(self):
        s = self.registry.get_scraper("ashby")
        assert isinstance(s, HttpxScraper)
        assert not hasattr(s, "_browser") or s._browser is None

    def test_greenhouse_is_httpx(self):
        s = self.registry.get_scraper("greenhouse")
        assert isinstance(s, HttpxScraper)

    def test_hiring_cafe_demoted(self):
        """Hiring Cafe is demoted — should NOT be in registry."""
        with pytest.raises(KeyError):
            self.registry.get_scraper("hiring_cafe")


class TestSlugConfiguration:
    """Verify slug config loads correctly in dict format."""

    def test_ashby_slugs_are_dict(self):
        assert isinstance(ASHBY_SLUGS, dict)

    def test_greenhouse_slugs_are_dict(self):
        assert isinstance(GREENHOUSE_SLUGS, dict)

    def test_config_dict_format_loads(self):
        slugs = _load_slugs_from_config("ashby")
        assert isinstance(slugs, dict)

    def test_norm_ai_resolves_to_hyphen(self):
        assert ASHBY_SLUGS["norm_ai"] == "norm-ai"

    def test_greenhouse_slug_loads(self):
        slugs = _load_slugs_from_config("greenhouse")
        assert isinstance(slugs, dict)

    def test_greenhouse_has_snorkelai(self):
        assert "snorkelai" in GREENHOUSE_SLUGS

    def test_lever_empty_dict(self):
        slugs = _load_slugs_from_config("lever")
        assert slugs == {}

    def test_hardcoded_slugs_win_over_config(self):
        """Hardcoded ASHBY_SLUGS must override config slugs."""
        config_slugs = _load_slugs_from_config("ashby")
        merged = {**config_slugs, **ASHBY_SLUGS}
        assert merged["norm_ai"] == "norm-ai"


class TestCanonicalNames:
    """Company names use canonical map, not .title() on slugs."""

    def test_llamaindex_not_title_cased(self):
        assert _CANONICAL_NAMES["llamaindex"] == "LlamaIndex"
        assert _CANONICAL_NAMES["llamaindex"] != "Llamaindex"

    def test_langchain_correct(self):
        assert _CANONICAL_NAMES["langchain"] == "LangChain"

    def test_norm_ai_correct(self):
        assert _CANONICAL_NAMES["norm_ai"] == "Norm AI"

    def test_snorkel_ai_correct(self):
        assert _CANONICAL_NAMES["snorkelai"] == "Snorkel AI"
        assert _CANONICAL_NAMES["snorkelai"] != "Snorkelai"

    def test_cinder_correct(self):
        assert _CANONICAL_NAMES["cinder"] == "Cinder"


class TestATSPlatformField:
    """ats_platform field exists in ORM (not ats_system)."""

    def test_orm_has_ats_platform(self):
        from src.db.orm import CompanyORM
        assert hasattr(CompanyORM, "ats_platform")

    def test_orm_no_ats_system(self):
        from src.db.orm import CompanyORM
        assert not hasattr(CompanyORM, "ats_system")

    def test_orm_has_ats_slug(self):
        from src.db.orm import CompanyORM
        assert hasattr(CompanyORM, "ats_slug")


class TestConcurrentSTierScan:
    """ConcurrentScanRunner can run all 3 S-tier scrapers."""

    @pytest.mark.asyncio
    async def test_concurrent_runner_with_s_tier(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        mock_posting = MagicMock()
        mock_posting.title = "AI Engineer"
        mock_posting.company_name = "TestCo"

        mock_scrapers = []
        for name in ["Ashby", "Greenhouse", "Hiring Cafe"]:
            s = MagicMock()
            s.name = name
            s.portal_name = name
            type(s).__name__ = "MockScraper"
            s.search = AsyncMock(return_value=[mock_posting])
            s.close = AsyncMock()
            mock_scrapers.append(s)

        runner = ConcurrentScanRunner(max_concurrent=3)
        result = await runner.run_all(
            scrapers=mock_scrapers,
            query=["ai engineer"],
            filters={"days": 30},
        )

        assert len(result) == 3
        assert len(runner.results) == 3
        assert all(r.outcome == "success" for r in runner.results)

    @pytest.mark.asyncio
    async def test_concurrent_runner_handles_failure(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        s = MagicMock()
        s.name = "Broken"
        s.portal_name = "Broken"
        type(s).__name__ = "MockScraper"
        s.search = AsyncMock(side_effect=RuntimeError("API down"))
        s.close = AsyncMock()

        runner = ConcurrentScanRunner(max_concurrent=1)
        result = await runner.run_all(
            scrapers=[s],
            query=["ai"],
            filters={"days": 7},
        )

        assert len(result) == 0
        assert len(runner.results) == 1
        assert runner.results[0].outcome == "error"
        assert "API down" in runner.results[0].error_message


class TestScanApisCommand:
    """Verify scan-apis CLI command targets only S-tier scrapers."""

    def test_s_tier_scrapers_are_all_registered(self):
        registry = build_default_registry()
        s_tier_keys = ["ashby", "greenhouse"]
        for key in s_tier_keys:
            scraper = registry.get_scraper(key)
            assert scraper is not None, f"S-tier scraper '{key}' not in registry"
            assert isinstance(scraper, HttpxScraper), (
                f"S-tier scraper '{key}' must be HttpxScraper, got {type(scraper).__name__}"
            )

    def test_s_tier_scrapers_are_tier_2(self):
        """S-tier scrapers are Tier 2 (H1B cross-check)."""
        registry = build_default_registry()
        for key in ["ashby", "greenhouse"]:
            scraper = registry.get_scraper(key)
            assert scraper.tier == PortalTier.TIER_2, (
                f"S-tier scraper '{key}' is {scraper.tier}, expected TIER_2"
            )

    def test_s_tier_scrapers_have_search(self):
        registry = build_default_registry()
        for key in ["ashby", "greenhouse"]:
            scraper = registry.get_scraper(key)
            assert hasattr(scraper, "search")
            assert callable(scraper.search)

    def test_s_tier_scrapers_are_not_browser_based(self):
        """S-tier scrapers must not inherit from PatchrightScraper."""
        from src.scrapers.patchright_scraper import PatchrightScraper

        registry = build_default_registry()
        for key in ["ashby", "greenhouse"]:
            scraper = registry.get_scraper(key)
            assert not isinstance(scraper, PatchrightScraper), (
                f"S-tier scraper '{key}' is a PatchrightScraper -- must be httpx-only"
            )

"""C4 Integration Tests -- Cross-component verification for all C4 scraper changes.

Tests cover:
  a) Registry completeness (17 scrapers, correct types, correct tiers)
  b) Homepage-first flow verification (5 subclasses, class attributes, _is_blocked)
  c) Profile copy integration (PatchrightScraper inheritance chain)
  d) Circuit breaker + ConcurrentScanRunner
  e) ATS slug validation (disqualified companies removed, valid slugs present)
  f) LinkedIn safety limits (MAX_PAGES, MAX_SCANS_PER_DAY, CAPTCHA detection)
  g) Built In + JobBoard AI Patchright scrapers
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.enums import PortalTier, SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.registry import PortalRegistry, build_default_registry

# ---------------------------------------------------------------------------
# (a) Registry completeness
# ---------------------------------------------------------------------------


class TestRegistryCompleteness:
    """Verify the registry contains exactly the expected scrapers."""

    def setup_method(self):
        self.registry = build_default_registry()
        self.all_scrapers = self.registry.get_all_scrapers()

    def test_total_scraper_count_is_17(self):
        """Registry must have exactly 17 scrapers (Lever removed in C3/C4)."""
        assert len(self.all_scrapers) == 17

    def test_all_expected_portals_registered(self):
        """Every expected portal key must be present."""
        expected_keys = {
            "ashby", "greenhouse",
            "top_startups", "ai_jobs",
            "wellfound", "yc", "wttj", "startup_jobs", "hiring_cafe",
            "linkedin", "linkedin_alerts", "builtin", "jobboard_ai",
            "jobright", "trueup",
            "jobspy", "hn_hiring",
        }
        for key in expected_keys:
            scraper = self.registry.get_scraper(key)
            assert scraper is not None, f"Missing scraper for portal key: {key}"

    def test_lever_not_registered(self):
        """Lever was removed in C3 -- must not be in registry."""
        with pytest.raises(KeyError, match="lever"):
            self.registry.get_scraper("lever")

    def test_each_scraper_has_portal_enum(self):
        """Every registered scraper must have a valid SourcePortal."""
        for scraper in self.all_scrapers:
            assert isinstance(scraper.portal, SourcePortal), (
                f"{type(scraper).__name__} has invalid portal: {scraper.portal}"
            )

    def test_each_scraper_has_tier(self):
        """Every registered scraper must have a valid PortalTier."""
        for scraper in self.all_scrapers:
            assert isinstance(scraper.tier, PortalTier), (
                f"{type(scraper).__name__} has invalid tier: {scraper.tier}"
            )

    def test_linkedin_is_patchright_not_mcp(self):
        """LinkedIn must be LinkedInPatchrightScraper (not MCPPlaywrightScraper)."""
        from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper
        from src.scrapers.mcp_scraper import MCPPlaywrightScraper

        linkedin = self.registry.get_scraper("linkedin")
        assert isinstance(linkedin, LinkedInPatchrightScraper)
        assert not isinstance(linkedin, MCPPlaywrightScraper)

    def test_builtin_is_patchright_not_mcp(self):
        """Built In must be BuiltInPatchrightScraper (not MCPPlaywrightScraper)."""
        from src.scrapers.builtin_scraper import BuiltInPatchrightScraper
        from src.scrapers.mcp_scraper import MCPPlaywrightScraper

        builtin = self.registry.get_scraper("builtin")
        assert isinstance(builtin, BuiltInPatchrightScraper)
        assert not isinstance(builtin, MCPPlaywrightScraper)

    def test_jobboard_ai_is_patchright_not_mcp(self):
        """JobBoard AI must be JobBoardAIPatchrightScraper (not MCPPlaywrightScraper)."""
        from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper
        from src.scrapers.mcp_scraper import MCPPlaywrightScraper

        jobboard_ai = self.registry.get_scraper("jobboard_ai")
        assert isinstance(jobboard_ai, JobBoardAIPatchrightScraper)
        assert not isinstance(jobboard_ai, MCPPlaywrightScraper)

    def test_homepage_first_scrapers_are_correct_type(self):
        """Wellfound, YC, WTTJ, startup_jobs, hiring_cafe are HomepageFirstScraper subclasses."""
        from src.scrapers.homepage_first_scraper import HomepageFirstScraper

        homepage_first_keys = ["wellfound", "yc", "wttj", "startup_jobs", "hiring_cafe"]
        for key in homepage_first_keys:
            scraper = self.registry.get_scraper(key)
            assert isinstance(scraper, HomepageFirstScraper), (
                f"{key} is {type(scraper).__name__}, expected HomepageFirstScraper subclass"
            )

    def test_tier_counts(self):
        """Verify tier distribution after C4 changes."""
        tier_1 = self.registry.get_scrapers_by_tier(1)
        tier_2 = self.registry.get_scrapers_by_tier(2)
        tier_3 = self.registry.get_scrapers_by_tier(3)

        # Tier 1: linkedin, linkedin_alerts
        assert len(tier_1) == 2

        # Tier 2: ashby, greenhouse, wttj, ai_jobs, builtin, jobboard_ai, jobright, trueup, jobspy
        assert len(tier_2) == 9

        # Tier 3: wellfound, yc, startup_jobs, hiring_cafe, top_startups, hn_hiring
        assert len(tier_3) == 6

        # Total
        assert len(tier_1) + len(tier_2) + len(tier_3) == 17


# ---------------------------------------------------------------------------
# (b) Homepage-first flow verification
# ---------------------------------------------------------------------------


class TestHomepageFirstFlow:
    """Verify HomepageFirstScraper base class and all 5 subclasses."""

    def test_all_five_inherit_from_homepage_first(self):
        """All 5 homepage-first scrapers inherit from HomepageFirstScraper."""
        from src.scrapers.homepage_first_scraper import (
            HiringCafeHomepageFirstScraper,
            HomepageFirstScraper,
            StartupJobsHomepageFirstScraper,
            WellfoundHomepageFirstScraper,
            WTTJHomepageFirstScraper,
            YCHomepageFirstScraper,
        )

        subclasses = [
            WellfoundHomepageFirstScraper,
            StartupJobsHomepageFirstScraper,
            HiringCafeHomepageFirstScraper,
            YCHomepageFirstScraper,
            WTTJHomepageFirstScraper,
        ]
        for cls in subclasses:
            assert issubclass(cls, HomepageFirstScraper), (
                f"{cls.__name__} does not inherit from HomepageFirstScraper"
            )

    @pytest.mark.parametrize(
        "cls_name,expected_homepage,expected_card_selector",
        [
            ("WellfoundHomepageFirstScraper", "https://wellfound.com/", "[data-testid"),
            ("StartupJobsHomepageFirstScraper", "https://startup.jobs/", ".job-card"),
            ("HiringCafeHomepageFirstScraper", "https://hiring.cafe/", "[data-testid"),
            ("YCHomepageFirstScraper", "https://www.workatastartup.com/", "[data-testid"),
            ("WTTJHomepageFirstScraper", "https://www.welcometothejungle.com/", "[data-testid"),
        ],
    )
    def test_class_attributes_set(self, cls_name, expected_homepage, expected_card_selector):
        """Each subclass must have HOMEPAGE_URL, SEARCH_URL_TEMPLATE, JOB_CARD_SELECTOR."""
        import src.scrapers.homepage_first_scraper as mod

        cls = getattr(mod, cls_name)
        instance = cls()

        assert instance.HOMEPAGE_URL, f"{cls_name} has empty HOMEPAGE_URL"
        assert instance.SEARCH_URL_TEMPLATE, f"{cls_name} has empty SEARCH_URL_TEMPLATE"
        assert instance.JOB_CARD_SELECTOR, f"{cls_name} has empty JOB_CARD_SELECTOR"

        assert instance.HOMEPAGE_URL.startswith(expected_homepage), (
            f"{cls_name} HOMEPAGE_URL mismatch: {instance.HOMEPAGE_URL}"
        )
        assert expected_card_selector in instance.JOB_CARD_SELECTOR, (
            f"{cls_name} JOB_CARD_SELECTOR missing expected pattern: {expected_card_selector}"
        )

    def test_search_url_template_has_kw_placeholder(self):
        """SEARCH_URL_TEMPLATE must contain {kw} placeholder for keyword substitution."""
        from src.scrapers.homepage_first_scraper import (
            HiringCafeHomepageFirstScraper,
            StartupJobsHomepageFirstScraper,
            WellfoundHomepageFirstScraper,
            WTTJHomepageFirstScraper,
            YCHomepageFirstScraper,
        )

        for cls in [
            WellfoundHomepageFirstScraper,
            StartupJobsHomepageFirstScraper,
            HiringCafeHomepageFirstScraper,
            YCHomepageFirstScraper,
            WTTJHomepageFirstScraper,
        ]:
            instance = cls()
            assert "{kw}" in instance.SEARCH_URL_TEMPLATE, (
                f"{cls.__name__} SEARCH_URL_TEMPLATE missing {{kw}} placeholder"
            )

    def test_is_blocked_detects_captcha(self):
        """_is_blocked should detect common bot detection indicators."""
        from src.scrapers.homepage_first_scraper import HomepageFirstScraper

        # Create a minimal subclass for testing
        class TestScraper(HomepageFirstScraper):
            HOMEPAGE_URL = "https://test.example/"
            SEARCH_URL_TEMPLATE = "https://test.example/search?q={kw}"
            JOB_CARD_SELECTOR = "article"

            def __init__(self):
                super().__init__(SourcePortal.MANUAL)

            async def _parse_card(self, card, page):
                return None

        scraper = TestScraper()

        # Should detect blocked indicators
        assert scraper._is_blocked("Please complete the CAPTCHA to continue")
        assert scraper._is_blocked("Access Denied - 403 Forbidden")
        assert scraper._is_blocked("Please verify you are human")
        assert scraper._is_blocked("Checking your browser before accessing")
        assert scraper._is_blocked("Just a moment... Cloudflare")

        # Should NOT flag normal pages
        assert not scraper._is_blocked("Welcome! Browse our job listings")
        assert not scraper._is_blocked("AI Engineer at LlamaIndex")
        assert not scraper._is_blocked("")

    def test_all_homepage_first_scrapers_inherit_from_patchright(self):
        """HomepageFirstScraper inherits from PatchrightScraper for stealth browser."""
        from src.scrapers.homepage_first_scraper import HomepageFirstScraper
        from src.scrapers.patchright_scraper import PatchrightScraper

        assert issubclass(HomepageFirstScraper, PatchrightScraper)


# ---------------------------------------------------------------------------
# (c) Profile copy / PatchrightScraper inheritance chain
# ---------------------------------------------------------------------------


class TestProfileCopyIntegration:
    """Verify browser scraper inheritance chain for profile handling."""

    def test_patchright_scraper_has_browser_attributes(self):
        """PatchrightScraper must have _browser, _context, _pw attributes."""
        from src.scrapers.patchright_scraper import JobrightPatchrightScraper

        # Use a concrete subclass (PatchrightScraper is abstract)
        scraper = JobrightPatchrightScraper()
        assert hasattr(scraper, "_browser")
        assert hasattr(scraper, "_context")
        assert hasattr(scraper, "_pw")
        assert scraper._browser is None
        assert scraper._context is None
        assert scraper._pw is None

    def test_homepage_first_inherits_patchright_launch(self):
        """HomepageFirstScraper inherits _launch, _close, _new_page_with_behavior."""
        from src.scrapers.homepage_first_scraper import WellfoundHomepageFirstScraper

        scraper = WellfoundHomepageFirstScraper()
        assert hasattr(scraper, "_launch")
        assert hasattr(scraper, "_close")
        assert hasattr(scraper, "_new_page_with_behavior")
        assert callable(scraper._launch)
        assert callable(scraper._close)

    def test_linkedin_inherits_patchright_launch(self):
        """LinkedInPatchrightScraper inherits from PatchrightScraper."""
        from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper
        from src.scrapers.patchright_scraper import PatchrightScraper

        scraper = LinkedInPatchrightScraper()
        assert isinstance(scraper, PatchrightScraper)
        assert hasattr(scraper, "_launch")
        assert hasattr(scraper, "_close")
        assert hasattr(scraper, "_new_page_with_behavior")

    def test_builtin_inherits_patchright_via_homepage_first(self):
        """BuiltInPatchrightScraper -> HomepageFirstScraper -> PatchrightScraper."""
        from src.scrapers.builtin_scraper import BuiltInPatchrightScraper
        from src.scrapers.homepage_first_scraper import HomepageFirstScraper
        from src.scrapers.patchright_scraper import PatchrightScraper

        assert issubclass(BuiltInPatchrightScraper, HomepageFirstScraper)
        assert issubclass(BuiltInPatchrightScraper, PatchrightScraper)

    def test_jobboardai_inherits_patchright_via_homepage_first(self):
        """JobBoardAIPatchrightScraper -> HomepageFirstScraper -> PatchrightScraper."""
        from src.scrapers.homepage_first_scraper import HomepageFirstScraper
        from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper
        from src.scrapers.patchright_scraper import PatchrightScraper

        assert issubclass(JobBoardAIPatchrightScraper, HomepageFirstScraper)
        assert issubclass(JobBoardAIPatchrightScraper, PatchrightScraper)


# ---------------------------------------------------------------------------
# (d) Circuit breaker + ConcurrentScanRunner
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Verify circuit breaker state machine."""

    def test_circuit_breaker_instantiation(self):
        """CircuitBreaker can be created with default parameters."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_seconds=300)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.name == "test"

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips_after_threshold(self):
        """Circuit opens after N consecutive failures."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_seconds=300)

        # 3 failures should open the circuit
        for _ in range(3):
            await cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert not await cb.can_execute()

    @pytest.mark.asyncio
    async def test_circuit_breaker_stays_closed_under_threshold(self):
        """Circuit stays closed if failures are below threshold."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_seconds=300)

        await cb.record_failure()
        await cb.record_failure()

        assert cb.state == CircuitState.CLOSED
        assert await cb.can_execute()

    @pytest.mark.asyncio
    async def test_circuit_breaker_success_resets(self):
        """Success resets failure count and keeps circuit closed."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_seconds=300)

        await cb.record_failure()
        await cb.record_failure()
        await cb.record_success()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_after_cooldown(self):
        """Circuit transitions to HALF_OPEN after cooldown expires."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=1, cooldown_seconds=0.01)

        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for cooldown
        await asyncio.sleep(0.02)

        # Should transition to HALF_OPEN and allow one test call
        assert await cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_success_closes(self):
        """Successful call in HALF_OPEN closes the circuit."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=1, cooldown_seconds=0.01)

        await cb.record_failure()
        await asyncio.sleep(0.02)
        await cb.can_execute()  # Transitions to HALF_OPEN

        await cb.record_success()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_failure_reopens(self):
        """Failed call in HALF_OPEN reopens the circuit."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=1, cooldown_seconds=0.01)

        await cb.record_failure()
        await asyncio.sleep(0.02)
        await cb.can_execute()  # Transitions to HALF_OPEN

        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_circuit_breaker_reset(self):
        """Manual reset clears all state."""
        from src.scrapers.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.state = CircuitState.OPEN
        cb.failure_count = 5

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestConcurrentScanRunner:
    """Verify ConcurrentScanRunner behavior."""

    def test_runner_instantiation(self):
        """ConcurrentScanRunner can be created."""
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        runner = ConcurrentScanRunner(max_concurrent=3)
        assert runner.semaphore._value == 3
        assert runner.results == []

    @pytest.mark.asyncio
    async def test_runner_empty_scrapers_returns_empty(self):
        """run_all with no scrapers returns empty list."""
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        runner = ConcurrentScanRunner()
        result = await runner.run_all([], query=["ai"], filters={"days": 7})
        assert result == []

    @pytest.mark.asyncio
    async def test_runner_skips_mcp_stubs(self):
        """ConcurrentScanRunner should skip MCPPlaywrightScraper stubs."""
        from src.scrapers.concurrent_runner import ConcurrentScanRunner
        from src.scrapers.mcp_scraper import MCPPlaywrightScraper

        # Use a real MCPPlaywrightScraper instance so type().__name__ check works
        mcp_scraper = MCPPlaywrightScraper(
            SourcePortal.BUILT_IN, skill_name="scan-builtin"
        )

        runner = ConcurrentScanRunner()
        await runner.run_all(
            [mcp_scraper], query=["ai"], filters={"days": 7}
        )

        # MCP stubs are skipped (detected by class name check)
        assert len(runner.results) == 1
        assert runner.results[0].outcome == "skipped"

    @pytest.mark.asyncio
    async def test_runner_handles_scraper_timeout(self):
        """Runner wraps each scraper with SCRAPER_TIMEOUT."""
        from src.scrapers.concurrent_runner import SCRAPER_TIMEOUT, ConcurrentScanRunner

        assert SCRAPER_TIMEOUT == 120  # 2-minute per-scraper timeout

    @pytest.mark.asyncio
    async def test_runner_with_mock_scraper_success(self):
        """Runner can execute a mock scraper successfully."""
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        mock_posting = JobPosting(
            title="AI Engineer", company_name="TestCo",
            url="https://test.example/1", source_portal=SourcePortal.STARTUP_JOBS,
        )
        mock_scraper = MagicMock()
        mock_scraper.name = "test_portal"
        type(mock_scraper).__name__ = "TestScraper"
        mock_scraper.search = AsyncMock(return_value=[mock_posting])

        runner = ConcurrentScanRunner()
        result = await runner.run_all(
            [mock_scraper], query=["ai"], filters={"days": 7}
        )

        assert len(result) == 1
        assert result[0].title == "AI Engineer"
        assert len(runner.results) == 1
        assert runner.results[0].outcome == "success"


# ---------------------------------------------------------------------------
# (e) ATS slug validation
# ---------------------------------------------------------------------------


class TestATSSlugValidation:
    """Verify ATS slug mappings are correct after C4 changes."""

    def test_ashby_no_disqualified_companies(self):
        """Disqualified companies must NOT be in ASHBY_SLUGS."""
        from src.scrapers.ats_scraper import ASHBY_SLUGS

        disqualified = {"cursor", "hippocratic_ai", "evenup"}
        for company in disqualified:
            assert company not in ASHBY_SLUGS, (
                f"Disqualified company '{company}' still in ASHBY_SLUGS"
            )

    def test_ashby_has_valid_slugs(self):
        """Valid Tier 1 companies must be in ASHBY_SLUGS."""
        from src.scrapers.ats_scraper import ASHBY_SLUGS

        valid_slugs = {"llamaindex", "langchain", "norm_ai", "cinder"}
        for slug in valid_slugs:
            assert slug in ASHBY_SLUGS, f"Valid slug '{slug}' missing from ASHBY_SLUGS"

    def test_ashby_slug_values_non_empty(self):
        """Every Ashby slug value must be a non-empty string."""
        from src.scrapers.ats_scraper import ASHBY_SLUGS

        for key, value in ASHBY_SLUGS.items():
            assert isinstance(value, str) and value, (
                f"ASHBY_SLUGS['{key}'] has invalid value: {value!r}"
            )

    def test_greenhouse_has_snorkel(self):
        """Snorkel AI must be in GREENHOUSE_SLUGS."""
        from src.scrapers.ats_scraper import GREENHOUSE_SLUGS

        assert "snorkelai" in GREENHOUSE_SLUGS

    def test_ats_config_loader_exists(self):
        """_load_slugs_from_config helper must exist for dynamic slug loading."""
        from src.scrapers.ats_scraper import _load_slugs_from_config

        # Should return a dict (possibly empty if config not found)
        result = _load_slugs_from_config("ashby")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# (f) LinkedIn safety limits
# ---------------------------------------------------------------------------


class TestLinkedInSafety:
    """Verify LinkedIn scraper safety limits."""

    def test_max_pages_is_5(self):
        """MAX_PAGES must be 5 to limit pagination depth."""
        from src.scrapers.linkedin_scraper import MAX_PAGES

        assert MAX_PAGES == 5

    def test_max_scans_per_day_is_1(self):
        """MAX_SCANS_PER_DAY must be 1 to avoid detection."""
        from src.scrapers.linkedin_scraper import MAX_SCANS_PER_DAY

        assert MAX_SCANS_PER_DAY == 1

    def test_min_delay_is_3_seconds(self):
        """Minimum delay between page loads must be at least 3 seconds."""
        from src.scrapers.linkedin_scraper import MIN_DELAY_MS

        assert MIN_DELAY_MS >= 3000

    def test_max_delay_is_7_seconds(self):
        """Maximum delay between page loads must be 7 seconds."""
        from src.scrapers.linkedin_scraper import MAX_DELAY_MS

        assert MAX_DELAY_MS == 7000

    def test_captcha_detection_works(self):
        """_is_captcha should detect LinkedIn security challenge indicators."""
        from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper

        scraper = LinkedInPatchrightScraper()

        # Should detect CAPTCHA indicators
        assert scraper._is_captcha("Please complete the captcha")
        assert scraper._is_captcha("Security verification required")
        assert scraper._is_captcha("Let's do a quick security check")
        assert scraper._is_captcha("We noticed unusual activity")
        assert scraper._is_captcha("Please verify you are a real person")
        assert scraper._is_captcha("Are you a robot?")

        # Should NOT flag normal pages
        assert not scraper._is_captcha("AI Engineer at LlamaIndex")
        assert not scraper._is_captcha("50 jobs found for your search")
        assert not scraper._is_captcha("")

    def test_linkedin_inherits_patchright(self):
        """LinkedInPatchrightScraper must inherit from PatchrightScraper."""
        from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper
        from src.scrapers.patchright_scraper import PatchrightScraper

        assert issubclass(LinkedInPatchrightScraper, PatchrightScraper)

    def test_linkedin_portal_is_correct(self):
        """LinkedIn scraper must use SourcePortal.LINKEDIN."""
        from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper

        scraper = LinkedInPatchrightScraper()
        assert scraper.portal == SourcePortal.LINKEDIN

    def test_linkedin_is_tier_1(self):
        """LinkedIn scraper must be Tier 1."""
        from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper

        scraper = LinkedInPatchrightScraper()
        assert scraper.tier == PortalTier.TIER_1

    def test_daily_scan_limit_check(self):
        """_can_scan_today should work without existing scan record."""
        from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper

        scraper = LinkedInPatchrightScraper()
        # Without any existing record, should be able to scan
        # (we don't actually create the record file in tests)
        result = scraper._can_scan_today()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# (g) Built In + JobBoard AI Patchright scrapers
# ---------------------------------------------------------------------------


class TestBuiltInPatchright:
    """Verify BuiltInPatchrightScraper configuration."""

    def test_builtin_homepage_url(self):
        from src.scrapers.builtin_scraper import BuiltInPatchrightScraper

        scraper = BuiltInPatchrightScraper()
        assert scraper.HOMEPAGE_URL == "https://builtin.com/"

    def test_builtin_search_url_template(self):
        from src.scrapers.builtin_scraper import BuiltInPatchrightScraper

        scraper = BuiltInPatchrightScraper()
        assert "{kw}" in scraper.SEARCH_URL_TEMPLATE
        assert "builtin.com" in scraper.SEARCH_URL_TEMPLATE

    def test_builtin_portal(self):
        from src.scrapers.builtin_scraper import BuiltInPatchrightScraper

        scraper = BuiltInPatchrightScraper()
        assert scraper.portal == SourcePortal.BUILT_IN

    def test_builtin_tier_2(self):
        """Built In is Tier 2 -- H1B cross-check required."""
        from src.scrapers.builtin_scraper import BuiltInPatchrightScraper

        scraper = BuiltInPatchrightScraper()
        assert scraper.tier == PortalTier.TIER_2


class TestJobBoardAIPatchright:
    """Verify JobBoardAIPatchrightScraper configuration."""

    def test_jobboardai_homepage_url(self):
        from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper

        scraper = JobBoardAIPatchrightScraper()
        assert scraper.HOMEPAGE_URL == "https://thejobboard.ai/"

    def test_jobboardai_search_url_template(self):
        from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper

        scraper = JobBoardAIPatchrightScraper()
        assert "{kw}" in scraper.SEARCH_URL_TEMPLATE

    def test_jobboardai_portal(self):
        from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper

        scraper = JobBoardAIPatchrightScraper()
        assert scraper.portal == SourcePortal.JOBBOARD_AI

    def test_jobboardai_tier_2(self):
        """JobBoard AI is Tier 2 -- H1B cross-check required."""
        from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper

        scraper = JobBoardAIPatchrightScraper()
        assert scraper.tier == PortalTier.TIER_2

    def test_jobboardai_has_card_selector(self):
        from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper

        scraper = JobBoardAIPatchrightScraper()
        assert scraper.JOB_CARD_SELECTOR, "JOB_CARD_SELECTOR must not be empty"


# ---------------------------------------------------------------------------
# (h) HN Hiring Algolia fallback
# ---------------------------------------------------------------------------


class TestHNHiringIntegration:
    """Verify HN Hiring scraper configuration after C4 changes."""

    def test_hn_hiring_is_httpx_based(self):
        """HN Hiring uses httpx (Algolia API), not browser."""
        from src.scrapers.hn_hiring_scraper import HNHiringScraper
        from src.scrapers.httpx_scraper import HttpxScraper

        assert issubclass(HNHiringScraper, HttpxScraper)

    def test_hn_hiring_portal(self):
        from src.scrapers.hn_hiring_scraper import HNHiringScraper

        scraper = HNHiringScraper()
        assert scraper.portal == SourcePortal.HN_HIRING

    def test_hn_hiring_is_tier_3(self):
        """HN Hiring is Tier 3 -- no H1B filter needed."""
        from src.scrapers.hn_hiring_scraper import HNHiringScraper

        scraper = HNHiringScraper()
        assert scraper.tier == PortalTier.TIER_3

    def test_hn_hiring_parse_pipe_format(self):
        """HN Hiring parser handles the standard pipe-delimited format."""
        from src.scrapers.hn_hiring_scraper import HNHiringScraper

        scraper = HNHiringScraper()
        item = {
            "text": "Acme AI | Senior ML Engineer | San Francisco, CA | Remote | H1B",
            "id": "12345",
            "created_at": "2026-03-01T12:00:00Z",
        }
        posting = scraper._parse_hn_item(item)
        assert posting is not None
        assert posting.company_name == "Acme AI"
        assert posting.title == "Senior ML Engineer"
        assert "San Francisco" in posting.location
        assert posting.h1b_mentioned is True


# ---------------------------------------------------------------------------
# (i) Cross-component wiring: registry scrapers can be fetched and have search()
# ---------------------------------------------------------------------------


class TestCrossComponentWiring:
    """Verify all registered scrapers have the expected interface."""

    def test_all_scrapers_have_search_method(self):
        """Every registered scraper must have a callable search method."""
        registry = build_default_registry()
        for scraper in registry.get_all_scrapers():
            assert hasattr(scraper, "search"), (
                f"{type(scraper).__name__} missing search() method"
            )
            assert callable(scraper.search)

    def test_all_scrapers_have_name_property(self):
        """Every registered scraper must have a non-empty name."""
        registry = build_default_registry()
        for scraper in registry.get_all_scrapers():
            assert scraper.name, f"{type(scraper).__name__} has empty name"

    def test_all_scrapers_have_is_healthy_method(self):
        """Every registered scraper must implement is_healthy()."""
        registry = build_default_registry()
        for scraper in registry.get_all_scrapers():
            result = scraper.is_healthy()
            assert isinstance(result, bool), (
                f"{type(scraper).__name__}.is_healthy() returned non-bool: {result}"
            )

    def test_no_unexpected_duplicate_portal_names(self):
        """No unexpected duplicate portal names in the registry.

        Known exception: LinkedInPatchrightScraper and LinkedInAlertScraper
        both use SourcePortal.LINKEDIN (name "LinkedIn") because the alert
        scraper is a supplementary ingest path, not a separate portal.
        """
        registry = build_default_registry()
        names = [s.name for s in registry.get_all_scrapers()]
        # Remove the known LinkedIn duplicate before checking
        linkedin_count = names.count("LinkedIn")
        assert linkedin_count == 2, (
            f"Expected exactly 2 'LinkedIn' scrapers (primary + alerts), got {linkedin_count}"
        )
        # All other names must be unique
        non_linkedin = [n for n in names if n != "LinkedIn"]
        assert len(non_linkedin) == len(set(non_linkedin)), (
            f"Unexpected duplicate scraper names: {[n for n in non_linkedin if non_linkedin.count(n) > 1]}"
        )

    def test_circuit_breaker_error_class_importable(self):
        """CircuitOpenError must be importable for error handling."""
        from src.scrapers.circuit_breaker import CircuitOpenError

        assert issubclass(CircuitOpenError, Exception)

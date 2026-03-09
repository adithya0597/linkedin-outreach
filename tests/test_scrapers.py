from __future__ import annotations

import asyncio
import time

import pytest

from src.config.enums import PortalTier, SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.deduplicator import Deduplicator
from src.scrapers.rate_limiter import RateLimiter
from src.scrapers.registry import PortalRegistry, build_default_registry


# --- RateLimiter tests ---


@pytest.mark.asyncio
async def test_rate_limiter_allows_first_request():
    limiter = RateLimiter(default_tokens_per_second=10.0)
    start = time.monotonic()
    await limiter.acquire("test_portal")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, "First request should be immediate"


@pytest.mark.asyncio
async def test_rate_limiter_throttles():
    limiter = RateLimiter(default_tokens_per_second=2.0)
    limiter.configure("slow", tokens_per_second=2.0)

    # Consume initial tokens
    await limiter.acquire("slow")
    await limiter.acquire("slow")

    start = time.monotonic()
    await limiter.acquire("slow")
    elapsed = time.monotonic() - start

    # Should have waited ~0.5s for a new token at 2/s
    assert elapsed >= 0.3, f"Should throttle after burst; waited {elapsed:.3f}s"


# --- Deduplicator tests ---


def test_deduplicator_exact_match():
    dedup = Deduplicator()
    is_dup, match = dedup.is_duplicate("LlamaIndex", ["LlamaIndex", "Cursor"])
    assert is_dup is True
    assert match == "LlamaIndex"


def test_deduplicator_fuzzy_match():
    dedup = Deduplicator()
    is_dup, match = dedup.is_duplicate("Llama Index", ["LlamaIndex", "Cursor"])
    assert is_dup is True
    assert match == "LlamaIndex"


def test_deduplicator_no_match():
    dedup = Deduplicator()
    is_dup, match = dedup.is_duplicate("Hippocratic AI", ["LlamaIndex", "Cursor"])
    assert is_dup is False
    assert match is None


def test_deduplicator_case_insensitive():
    dedup = Deduplicator()
    is_dup, match = dedup.is_duplicate("llamaindex", ["LlamaIndex"])
    assert is_dup is True


def test_deduplicator_empty_lists():
    dedup = Deduplicator()
    is_dup, match = dedup.is_duplicate("Cursor", [])
    assert is_dup is False
    assert match is None


# --- Registry tests ---


def test_registry_register_and_get():
    from src.scrapers.mcp_scraper import MCPPlaywrightScraper

    registry = PortalRegistry()
    scraper = MCPPlaywrightScraper(SourcePortal.LINKEDIN, skill_name="scan-linkedin")
    registry.register("linkedin", scraper)

    retrieved = registry.get_scraper("linkedin")
    assert retrieved is scraper
    assert retrieved.portal == SourcePortal.LINKEDIN


def test_registry_get_missing_raises():
    registry = PortalRegistry()
    with pytest.raises(KeyError):
        registry.get_scraper("nonexistent")


def test_registry_get_all():
    registry = build_default_registry()
    all_scrapers = registry.get_all_scrapers()
    assert len(all_scrapers) == 18  # 4-tier architecture: S(4) + A(6) + B(4) + C(2) + D(2)


def test_registry_get_by_tier():
    registry = build_default_registry()

    tier_1 = registry.get_scrapers_by_tier(1)
    assert len(tier_1) == 2  # linkedin (MCP), linkedin_alerts (Gmail)

    tier_3 = registry.get_scrapers_by_tier(3)
    assert len(tier_3) == 6  # wellfound, yc, startup_jobs, hiring_cafe, top_startups, hn_hiring

    tier_2 = registry.get_scrapers_by_tier(2)
    assert len(tier_2) == 10  # ashby, greenhouse, lever, wttj, ai_jobs, builtin, jobboard_ai, jobright, trueup, jobspy


def test_registry_correct_scraper_type():
    registry = build_default_registry()

    from src.scrapers.httpx_scraper import HttpxScraper
    from src.scrapers.mcp_scraper import MCPPlaywrightScraper

    linkedin = registry.get_scraper("linkedin")
    assert isinstance(linkedin, MCPPlaywrightScraper)

    startup_jobs = registry.get_scraper("startup_jobs")
    assert isinstance(startup_jobs, HttpxScraper)

    yc = registry.get_scraper("yc")
    assert isinstance(yc, HttpxScraper)  # AlgoliaBaseScraper extends HttpxScraper


# --- H1B filter tests ---


def test_h1b_filter_tier3_auto_passes():
    """Tier 3 (startup portals) should auto-pass all postings."""
    from src.scrapers.wellfound_nextdata import WellfoundNextDataScraper

    scraper = WellfoundNextDataScraper()
    assert scraper.tier == PortalTier.TIER_3

    posting = JobPosting(
        company_name="SomeStartup",
        h1b_text="no",  # Even "no" should pass on Tier 3
    )
    assert scraper.apply_h1b_filter(posting) is True


def test_h1b_filter_tier2_rejects_explicit_no():
    """Tier 2 portals should reject postings that explicitly won't sponsor."""
    from src.scrapers.httpx_scraper import AIJobsScraper

    scraper = AIJobsScraper()
    assert scraper.tier == PortalTier.TIER_2

    posting_no = JobPosting(company_name="NoSponsor", h1b_text="no")
    assert scraper.apply_h1b_filter(posting_no) is False

    posting_explicit = JobPosting(company_name="NoSponsor", h1b_text="will not sponsor")
    assert scraper.apply_h1b_filter(posting_explicit) is False


def test_h1b_filter_tier2_passes_unknown():
    """Tier 2 portals should pass postings with unknown H1B status."""
    from src.scrapers.httpx_scraper import AIJobsScraper

    scraper = AIJobsScraper()
    posting = JobPosting(company_name="MaybeSponsor", h1b_text="")
    assert scraper.apply_h1b_filter(posting) is True


def test_h1b_filter_tier1_rejects_explicit_no():
    """Tier 1 (LinkedIn) should also reject explicit no."""
    from src.scrapers.mcp_scraper import MCPPlaywrightScraper

    scraper = MCPPlaywrightScraper(SourcePortal.LINKEDIN, skill_name="scan-linkedin")
    assert scraper.tier == PortalTier.TIER_1

    posting = JobPosting(company_name="BigCo", h1b_text="Explicit No")
    assert scraper.apply_h1b_filter(posting) is False


# --- Scraper health check ---


def test_healthy_scrapers_exclude_unhealthy():
    """Healthy scrapers should not include unhealthy portals (e.g. uninstalled deps)."""
    registry = build_default_registry()
    healthy = registry.get_healthy_scrapers()
    healthy_names = {s.name for s in healthy}

    # After 4-tier migration, most scrapers are healthy (MCP, Patchright, Algolia replacements)
    # Only JobSpy may be unhealthy if python-jobspy is not installed
    assert "Ashby" in healthy_names
    assert "Greenhouse" in healthy_names
    assert "Wellfound" in healthy_names
    assert "AI Jobs" in healthy_names
    # Total healthy count: 17 (all except JobSpy if not installed) or 18 if installed
    assert len(healthy) >= 17

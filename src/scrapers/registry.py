from __future__ import annotations

from src.config.enums import PortalTier, SourcePortal
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.rate_limiter import RateLimiter


class PortalRegistry:
    """Maps portal names to scraper instances."""

    def __init__(self) -> None:
        self._scrapers: dict[str, BaseScraper] = {}

    def register(self, portal: str, scraper: BaseScraper) -> None:
        """Register a scraper instance for a portal name."""
        self._scrapers[portal] = scraper

    def get_scraper(self, portal: str) -> BaseScraper:
        """Get scraper by portal name. Raises KeyError if not registered."""
        if portal not in self._scrapers:
            raise KeyError(f"No scraper registered for portal: {portal}")
        return self._scrapers[portal]

    def get_all_scrapers(self) -> list[BaseScraper]:
        """Return all registered scraper instances."""
        return list(self._scrapers.values())

    def get_scrapers_by_tier(self, tier: int) -> list[BaseScraper]:
        """Return scrapers whose portal matches the given tier number."""
        portal_tier = PortalTier(tier)
        return [s for s in self._scrapers.values() if s.tier == portal_tier]

    def get_healthy_scrapers(self, health_monitor=None) -> list[BaseScraper]:
        """Return only scrapers that report healthy status.

        If a HealthMonitor is provided, uses data-driven health checks
        based on scan history instead of per-scraper is_healthy() stubs.
        """
        if health_monitor is not None:
            healthy = []
            for name, scraper in self._scrapers.items():
                portal_health = health_monitor.check_portal(name)
                if portal_health.is_healthy:
                    healthy.append(scraper)
            return healthy
        return [s for s in self._scrapers.values() if s.is_healthy()]


def build_default_registry() -> PortalRegistry:
    """Create a registry with all portal scrapers pre-registered.

    Four-tier architecture:
      Tier S — Zero Risk (APIs): Ashby, Greenhouse, Hiring Cafe
      Tier A — Low Risk (httpx): Wellfound (__NEXT_DATA__), YC (Algolia),
               WTTJ (Algolia), startup.jobs, Top Startups, AI Jobs
      Tier B — Patchright: LinkedIn (primary), Built In, JobBoard AI
      Tier C — Medium Risk (Patchright): Jobright, TrueUp
      Tier D — New Sources: JobSpy, HN Hiring
    """
    from src.scrapers.ats_scraper import AshbyScraper, GreenhouseScraper
    from src.scrapers.hn_hiring_scraper import HNHiringScraper
    from src.scrapers.homepage_first_scraper import (
        HiringCafeHomepageFirstScraper,
        StartupJobsHomepageFirstScraper,
        WellfoundHomepageFirstScraper,
        WTTJHomepageFirstScraper,
        YCHomepageFirstScraper,
    )
    from src.scrapers.httpx_scraper import (
        AIJobsScraper,
        TopStartupsScraper,
    )
    from src.scrapers.jobspy_scraper import JobSpyScraper
    from src.scrapers.linkedin_email_ingest import LinkedInAlertScraper
    from src.scrapers.linkedin_scraper import LinkedInPatchrightScraper
    from src.scrapers.builtin_scraper import BuiltInPatchrightScraper
    from src.scrapers.jobboardai_scraper import JobBoardAIPatchrightScraper
    from src.scrapers.patchright_scraper import (
        JobrightPatchrightScraper,
        TrueUpPatchrightScraper,
    )

    # Shared rate limiter with per-portal rates
    rl = RateLimiter(default_tokens_per_second=1.0)
    rl.configure("LinkedIn", 0.15)                  # ~1 req / 7s (strict anti-bot safety)
    rl.configure("Wellfound", 0.3)                 # browser-based homepage-first
    rl.configure("Jobright AI", 0.5)               # Patchright stealth
    rl.configure("TrueUp", 0.5)                    # Patchright stealth
    rl.configure("Hiring Cafe", 0.3)               # browser-based homepage-first
    rl.configure("Work at a Startup (YC)", 0.3)    # browser-based homepage-first
    rl.configure("Welcome to the Jungle", 0.3)     # browser-based homepage-first
    rl.configure("startup.jobs", 0.3)              # browser-based homepage-first
    rl.configure("Built In", 0.3)                   # browser-based, Fastly + HUMAN Security
    rl.configure("JobBoard AI", 0.5)                 # browser-based
    rl.configure("Ashby", 2.0)                     # ATS API
    rl.configure("Greenhouse", 2.0)                # ATS API
    registry = PortalRegistry()

    scrapers: list[tuple[str, BaseScraper]] = [
        # ── Tier S: Zero Risk (APIs) ──────────────────────────────
        ("ashby", AshbyScraper(rate_limiter=rl)),
        ("greenhouse", GreenhouseScraper(rate_limiter=rl)),
        # ── Tier A: Low Risk (httpx, no browser) ─────────────────
        ("top_startups", TopStartupsScraper(rate_limiter=rl)),
        ("ai_jobs", AIJobsScraper(rate_limiter=rl)),
        # ── Tier A+: Homepage-first (Patchright browser) ─────────
        ("wellfound", WellfoundHomepageFirstScraper(rate_limiter=rl)),
        ("yc", YCHomepageFirstScraper(rate_limiter=rl)),
        ("wttj", WTTJHomepageFirstScraper(rate_limiter=rl)),
        ("startup_jobs", StartupJobsHomepageFirstScraper(rate_limiter=rl)),
        ("hiring_cafe", HiringCafeHomepageFirstScraper(rate_limiter=rl)),
        # ── Tier B: Patchright stealth (LinkedIn, logged-in Chrome) ─
        ("linkedin", LinkedInPatchrightScraper(rate_limiter=rl)),
        ("linkedin_alerts", LinkedInAlertScraper(rate_limiter=rl)),
        ("builtin", BuiltInPatchrightScraper(rate_limiter=rl)),
        ("jobboard_ai", JobBoardAIPatchrightScraper(rate_limiter=rl)),
        # ── Tier C: Medium Risk (Patchright stealth browser) ─────
        ("jobright", JobrightPatchrightScraper(rate_limiter=rl)),
        ("trueup", TrueUpPatchrightScraper(rate_limiter=rl)),
        # ── Tier D: New Sources ───────────────────────────────────
        ("jobspy", JobSpyScraper(rate_limiter=rl)),
        ("hn_hiring", HNHiringScraper(rate_limiter=rl)),
    ]

    for name, scraper in scrapers:
        registry.register(name, scraper)

    return registry

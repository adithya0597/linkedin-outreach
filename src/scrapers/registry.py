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
    """Create a registry with all portal scrapers pre-registered."""
    from src.scrapers.apify_scraper import (
        BuiltInScraper,
        TrueUpScraper,
        WTTJScraper,
        YCScraper,
    )
    from src.scrapers.httpx_scraper import (
        AIJobsScraper,
        JobBoardAIScraper,
        StartupJobsScraper,
        TopStartupsScraper,
    )
    from src.scrapers.playwright_scraper import (
        HiringCafeScraper,
        JobrightScraper,
        LinkedInScraper,
        WellfoundScraper,
    )

    # Shared rate limiter with per-portal rates
    rl = RateLimiter(default_tokens_per_second=1.0)
    rl.configure("LinkedIn", 0.2)           # 1 req / 5s (anti-bot)
    rl.configure("Wellfound", 0.5)          # Playwright portals
    rl.configure("Jobright AI", 0.5)
    rl.configure("Hiring Cafe", 0.5)
    rl.configure("Work at a Startup (YC)", 1.0)  # Apify
    rl.configure("TrueUp", 1.0)
    rl.configure("Built In", 1.0)
    rl.configure("Welcome to the Jungle", 1.0)

    registry = PortalRegistry()

    scrapers: list[tuple[str, BaseScraper]] = [
        # Playwright scrapers
        ("linkedin", LinkedInScraper(rate_limiter=rl)),
        ("wellfound", WellfoundScraper(rate_limiter=rl)),
        ("jobright", JobrightScraper(rate_limiter=rl)),
        ("hiring_cafe", HiringCafeScraper(rate_limiter=rl)),
        # httpx scrapers
        ("startup_jobs", StartupJobsScraper(rate_limiter=rl)),
        ("top_startups", TopStartupsScraper(rate_limiter=rl)),
        ("ai_jobs", AIJobsScraper(rate_limiter=rl)),
        ("jobboard_ai", JobBoardAIScraper(rate_limiter=rl)),
        # Apify scrapers
        ("yc", YCScraper(rate_limiter=rl)),
        ("builtin", BuiltInScraper(rate_limiter=rl)),
        ("wttj", WTTJScraper(rate_limiter=rl)),
        ("trueup", TrueUpScraper(rate_limiter=rl)),
    ]

    for name, scraper in scrapers:
        registry.register(name, scraper)

    return registry

from __future__ import annotations

from abc import ABC, abstractmethod

from src.config.enums import H1BStatus, PortalTier, SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.rate_limiter import RateLimiter


class BaseScraper(ABC):
    """Abstract base class for all portal scrapers."""

    def __init__(self, portal: SourcePortal, rate_limiter: RateLimiter | None = None) -> None:
        self._portal = portal
        self._rate_limiter = rate_limiter

    @property
    def name(self) -> str:
        return self._portal.value

    @property
    def portal(self) -> SourcePortal:
        return self._portal

    @property
    def tier(self) -> PortalTier:
        return self._portal.tier

    @abstractmethod
    async def search(self, keywords: list[str]) -> list[JobPosting]:
        """Search portal for job postings matching keywords."""

    @abstractmethod
    async def get_posting_details(self, url: str) -> JobPosting:
        """Fetch full details for a single job posting."""

    def is_healthy(self) -> bool:
        """Return True if the scraper is operational."""
        return True

    async def _throttle(self) -> None:
        """Acquire a rate-limiter token for this portal (no-op if no limiter)."""
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire(self.name)

    def apply_h1b_filter(self, posting: JobPosting) -> bool:
        """Check whether a posting passes H1B filtering for this portal's tier.

        Returns True if the posting should be KEPT (passes filter).
        - Tier 3 portals: auto-pass (no H1B filter)
        - Tier 1/2 portals: pass only if H1B is confirmed, likely, or unknown
          (explicit "no" is filtered out)
        """
        if self.tier == PortalTier.TIER_3:
            return True

        # For Tier 1 and Tier 2, reject postings that explicitly won't sponsor
        if posting.h1b_text.lower() in ("no", "explicit no", "will not sponsor"):
            return False

        return True

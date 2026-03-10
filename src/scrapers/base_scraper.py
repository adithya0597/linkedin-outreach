from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from src.config.enums import PortalTier, SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.rate_limiter import RateLimiter
from src.scrapers.retry import scraper_retry


@dataclass
class ScrapeResult:
    """Result of a single scraper run."""

    entries: list = field(default_factory=list)  # list[JobPosting]
    outcome: str = "success"  # "success" | "no_results" | "error" | "timeout" | "skipped"
    error_message: str = ""
    status_code: int | None = None
    duration_seconds: float = 0.0


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
    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        """Search portal for job postings matching keywords.

        Args:
            keywords: Search terms to query.
            days: Only include postings from the last N days.
        """

    async def get_posting_details(self, url: str) -> JobPosting:
        """Fetch full details for a single job posting.

        Default implementation returns a minimal JobPosting with only the URL
        and source portal. Subclasses that can fetch richer details from the
        posting page should override this method.
        """
        return JobPosting(url=url, source_portal=self._portal)

    def is_healthy(self) -> bool:
        """Return True if the scraper is operational."""
        return True

    async def close(self) -> None:  # noqa: B027
        """Clean up scraper resources. Override in subclasses if needed."""
        pass

    async def _throttle(self) -> None:
        """Acquire a rate-limiter token for this portal (no-op if no limiter)."""
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire(self.name)

    @staticmethod
    def _post_filter_by_date(postings: list[JobPosting], days: int) -> list[JobPosting]:
        """Filter postings to only those discovered within the last N days."""
        cutoff = datetime.now() - timedelta(days=days)
        return [p for p in postings if p.discovered_date >= cutoff]

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
        return posting.h1b_text.lower() not in ("no", "explicit no", "will not sponsor")

    async def _fetch_with_retry(self, url: str, **kwargs) -> httpx.Response:
        """Fetch URL with retry logic. Opt-in helper for subclasses."""

        @scraper_retry
        async def _do_fetch() -> httpx.Response:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, **kwargs)
                response.raise_for_status()
                return response

        return await _do_fetch()

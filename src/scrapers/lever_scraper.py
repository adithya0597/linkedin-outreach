"""Lever ATS API scraper.

Lever provides a free, unauthenticated JSON API for public job boards.
Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json

Tier S — Zero Risk: Public API, no authentication, structured JSON.
"""

# DEPRECATED: LeverScraper removed from default registry (2026-03-10).
# Lever ATS jobs are now discovered via direct ATS API scraper.
# This file is kept for reference. Do not import in new code.

from __future__ import annotations

from datetime import datetime

import httpx
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.ats_scraper import _matches_keywords, _parse_h1b_from_description, _parse_salary_from_description
from src.scrapers.httpx_scraper import HttpxScraper
from src.scrapers.rate_limiter import RateLimiter

# Company slugs for Lever job boards we want to monitor
LEVER_SLUGS: dict[str, str] = {
    # Add company slugs as they're discovered
    # Format: "internal_key": "lever-company-slug"
    # Example: "openai": "openai"
}


class LeverScraper(HttpxScraper):
    """Lever ATS API scraper.

    Endpoint: GET https://api.lever.co/v0/postings/{slug}?mode=json
    Returns JSON array of postings. Each posting has:
    text (title), categories.location, categories.department,
    categories.team, descriptionPlain, hostedUrl, createdAt.

    Post-fetch keyword filter on title/department for AI/ML relevance.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.MANUAL, rate_limiter=rate_limiter)
        # Override portal name for display
        self._portal_name = "Lever"

    @property
    def name(self) -> str:
        return self._portal_name

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        if not LEVER_SLUGS:
            logger.info("LeverScraper: No company slugs configured")
            return results

        for slug_key, slug in LEVER_SLUGS.items():
            await self._throttle()
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"Lever API request failed for slug '{slug_key}': {e}")
                continue

            try:
                jobs = response.json()
            except Exception as e:
                logger.warning(f"Lever returned non-JSON for slug '{slug_key}': {e}")
                continue

            if not isinstance(jobs, list):
                continue

            for job in jobs:
                title = job.get("text", "")
                if not title:
                    continue

                categories = job.get("categories", {})
                department = categories.get("department", "")
                team = categories.get("team", "")

                # Post-fetch keyword filter
                if not _matches_keywords(title, f"{department} {team}", keywords):
                    continue

                location = categories.get("location", "")
                commitment = categories.get("commitment", "")

                description = job.get("descriptionPlain", "")
                job_url = job.get("hostedUrl", "")

                # Parse H1B and salary from description
                h1b_mentioned, h1b_text = _parse_h1b_from_description(description)
                salary_range, salary_min, salary_max = _parse_salary_from_description(description)

                # Parse created date
                posted_date = None
                created_at = job.get("createdAt")
                if created_at:
                    try:
                        # Lever uses millisecond timestamps
                        posted_date = datetime.fromtimestamp(created_at / 1000)
                    except (ValueError, TypeError, OSError):
                        pass

                # Work model from commitment or location
                work_model = ""
                if commitment:
                    work_model = commitment.lower()
                if "remote" in location.lower():
                    work_model = "remote"

                company_name = slug_key.replace("_", " ").title()

                posting = JobPosting(
                    title=title,
                    company_name=company_name,
                    location=location,
                    url=job_url,
                    description=description[:500] if description else "",
                    work_model=work_model,
                    salary_range=salary_range,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    source_portal=SourcePortal.MANUAL,  # Will be updated when LEVER enum is added
                    h1b_mentioned=h1b_mentioned,
                    h1b_text=h1b_text,
                    posted_date=posted_date,
                )
                if self.apply_h1b_filter(posting):
                    results.append(posting)

        logger.info(f"LeverScraper found {len(results)} postings")
        return results


"""Built In job portal scraper using Patchright stealth browser.

Replaces the MCP stub. Uses homepage-first pattern to establish session.
Built In has Fastly + HUMAN Security (difficulty: 5/10).

Tier 2 -- H1B cross-check required.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.homepage_first_scraper import HomepageFirstScraper
from src.scrapers.rate_limiter import RateLimiter


class BuiltInPatchrightScraper(HomepageFirstScraper):
    """Built In job scraper using homepage-first Patchright.

    Built In has Fastly CDN + HUMAN Security bot protection.
    Homepage-first approach establishes real browser session to bypass.
    """

    HOMEPAGE_URL = "https://builtin.com/"
    SEARCH_URL_TEMPLATE = "https://builtin.com/jobs?search={kw}"
    JOB_CARD_SELECTOR = "[data-id], .job-card, article, a[href*='/job/'], [role='listitem']"

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.BUILT_IN, rate_limiter=rate_limiter)

    async def _parse_card(self, card, page) -> JobPosting | None:
        try:
            title_el = await card.query_selector(
                "h2, h3, [data-testid*='title'], [role='heading'], a[href*='/job/']"
            )
            company_el = await card.query_selector(
                "[data-testid*='company'], .company-name, h4, span[class*='company']"
            )
            location_el = await card.query_selector(
                "[data-testid*='location'], .job-location, span[class*='location']"
            )

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            if not title or len(title) < 3:
                return None

            # Get URL
            link = await card.query_selector("a[href*='/job/'], a[href*='/jobs/']")
            href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://builtin.com{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.BUILT_IN,
                discovered_date=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"Built In card parse error: {e}")
            return None

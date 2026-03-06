from __future__ import annotations

import asyncio
from datetime import datetime

from apify_client import ApifyClient
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.rate_limiter import RateLimiter


class ApifyScraper(BaseScraper):
    """Base class for scrapers using the Apify cloud platform."""

    def __init__(self, portal: SourcePortal, actor_id: str = "", rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(portal, rate_limiter=rate_limiter)
        self._actor_id = actor_id
        self._client: ApifyClient | None = None

    def _get_client(self) -> ApifyClient:
        if self._client is None:
            self._client = ApifyClient()
        return self._client

    async def _run_actor(self, run_input: dict) -> list[dict]:
        """Run an Apify actor and return the dataset items."""
        client = self._get_client()
        try:
            run = await asyncio.to_thread(
                client.actor(self._actor_id).call,
                run_input=run_input,
            )
            items = await asyncio.to_thread(
                lambda: client.dataset(run["defaultDatasetId"]).list_items().items
            )
            return items
        except Exception as e:
            logger.error(f"{self.name} Apify run failed: {e}")
            return []


class YCScraper(ApifyScraper):
    """Work at a Startup (YC) scraper (Tier 3 -- startup portal).

    Uses Apify web-scraper actor to crawl workatastartup.com listings.
    Tier 3 = no H1B filter needed.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.YC, actor_id="apify/web-scraper", rate_limiter=rate_limiter)

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        await self._throttle()

        query = " ".join(keywords)
        run_input = {
            "startUrls": [
                {"url": f"https://www.workatastartup.com/companies?query={query}&demographic=any&hasEquity=any&hasSalary=any&industry=any&interviewProcess=any&jobType=any&layout=list-compact&sortBy=created_desc&tab=any&usVisaOnly=any"}
            ],
            "pageFunction": """async function pageFunction(context) {
                const { request, log, jQuery } = context;
                const $ = jQuery;
                const results = [];
                $('[class*="company"]').each(function() {
                    const el = $(this);
                    results.push({
                        company: el.find('[class*="name"]').text().trim(),
                        title: el.find('[class*="role"], [class*="title"]').text().trim(),
                        url: el.find('a').attr('href') || '',
                        location: el.find('[class*="location"]').text().trim(),
                    });
                });
                return results;
            }""",
            "maxPagesPerCrawl": 3,
            "maxConcurrency": 1,
        }

        items = await self._run_actor(run_input)

        results = []
        for item in items:
            if not item.get("company") and not item.get("title"):
                continue
            url = item.get("url", "")
            if url and not url.startswith("http"):
                url = f"https://www.workatastartup.com{url}"
            posting = JobPosting(
                company_name=item.get("company", ""),
                title=item.get("title", ""),
                url=url,
                source_portal=SourcePortal.YC,
                location=item.get("location", ""),
                discovered_date=datetime.now(),
            )
            # Tier 3 -- apply_h1b_filter auto-passes
            if self.apply_h1b_filter(posting):
                results.append(posting)

        logger.info(f"YCScraper found {len(results)} postings for keywords={keywords}")
        return results

    async def get_posting_details(self, url: str) -> JobPosting:
        await self._throttle()

        run_input = {
            "startUrls": [{"url": url}],
            "pageFunction": """async function pageFunction(context) {
                const { request, jQuery } = context;
                const $ = jQuery;
                return {
                    company: $('[class*="company-name"]').text().trim(),
                    title: $('h1, [class*="title"]').first().text().trim(),
                    url: request.url,
                    location: $('[class*="location"]').text().trim(),
                    description: $('[class*="description"], [class*="job-detail"]').text().trim(),
                };
            }""",
            "maxPagesPerCrawl": 1,
        }

        items = await self._run_actor(run_input)
        if not items:
            return JobPosting(url=url, source_portal=SourcePortal.YC)

        item = items[0]
        return JobPosting(
            company_name=item.get("company", ""),
            title=item.get("title", ""),
            url=item.get("url", url),
            source_portal=SourcePortal.YC,
            location=item.get("location", ""),
            description=item.get("description", ""),
            discovered_date=datetime.now(),
        )


class BuiltInScraper(ApifyScraper):
    """Built In scraper (Tier 2 -- H1B cross-check required).

    DEMOTED: Zero startups found in prior scans. is_healthy() returns False.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.BUILT_IN, actor_id="apify/web-scraper", rate_limiter=rate_limiter)

    def is_healthy(self) -> bool:
        return False

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        logger.warning("BuiltIn scraper demoted — zero startup matches in prior scans")
        return []

    async def get_posting_details(self, url: str) -> JobPosting:
        logger.warning("BuiltIn scraper demoted — returning minimal posting")
        return JobPosting(url=url, source_portal=SourcePortal.BUILT_IN)


class WTTJScraper(ApifyScraper):
    """Welcome to the Jungle scraper (Tier 2 -- H1B cross-check required).

    DOWN: Portal returning 500 errors. is_healthy() returns False.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.WTTJ, actor_id="apify/web-scraper", rate_limiter=rate_limiter)

    def is_healthy(self) -> bool:
        return False

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        logger.warning("WTTJ scraper is DOWN — portal returning 500 errors")
        return []

    async def get_posting_details(self, url: str) -> JobPosting:
        logger.warning("WTTJ scraper is DOWN — returning minimal posting")
        return JobPosting(url=url, source_portal=SourcePortal.WTTJ)


class TrueUpScraper(ApifyScraper):
    """TrueUp scraper (Tier 2 -- H1B cross-check required).

    Uses Apify web-scraper actor to crawl trueup.io listings.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.TRUEUP, actor_id="apify/web-scraper", rate_limiter=rate_limiter)

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        await self._throttle()

        query = "+".join(keywords)
        run_input = {
            "startUrls": [
                {"url": f"https://www.trueup.io/jobs?query={query}"}
            ],
            "pageFunction": """async function pageFunction(context) {
                const { request, log, jQuery } = context;
                const $ = jQuery;
                const results = [];
                $('[class*="job-card"], [class*="JobCard"], tr[class*="job"]').each(function() {
                    const el = $(this);
                    results.push({
                        company: el.find('[class*="company"]').text().trim(),
                        title: el.find('[class*="title"], a').first().text().trim(),
                        url: el.find('a').attr('href') || '',
                        location: el.find('[class*="location"]').text().trim(),
                        salary: el.find('[class*="salary"], [class*="compensation"]').text().trim(),
                    });
                });
                return results;
            }""",
            "maxPagesPerCrawl": 3,
            "maxConcurrency": 1,
        }

        items = await self._run_actor(run_input)

        results = []
        for item in items:
            if not item.get("company") and not item.get("title"):
                continue
            url = item.get("url", "")
            if url and not url.startswith("http"):
                url = f"https://www.trueup.io{url}"
            posting = JobPosting(
                company_name=item.get("company", ""),
                title=item.get("title", ""),
                url=url,
                source_portal=SourcePortal.TRUEUP,
                location=item.get("location", ""),
                salary_range=item.get("salary", ""),
                discovered_date=datetime.now(),
            )
            # Tier 2 -- apply H1B filter
            if self.apply_h1b_filter(posting):
                results.append(posting)

        logger.info(f"TrueUpScraper found {len(results)} postings for keywords={keywords}")
        return results

    async def get_posting_details(self, url: str) -> JobPosting:
        await self._throttle()

        run_input = {
            "startUrls": [{"url": url}],
            "pageFunction": """async function pageFunction(context) {
                const { request, jQuery } = context;
                const $ = jQuery;
                return {
                    company: $('[class*="company-name"], [class*="employer"]').text().trim(),
                    title: $('h1, [class*="job-title"]').first().text().trim(),
                    url: request.url,
                    location: $('[class*="location"]').text().trim(),
                    description: $('[class*="description"], [class*="job-detail"]').text().trim(),
                    salary: $('[class*="salary"], [class*="compensation"]').text().trim(),
                };
            }""",
            "maxPagesPerCrawl": 1,
        }

        items = await self._run_actor(run_input)
        if not items:
            return JobPosting(url=url, source_portal=SourcePortal.TRUEUP)

        item = items[0]
        return JobPosting(
            company_name=item.get("company", ""),
            title=item.get("title", ""),
            url=item.get("url", url),
            source_portal=SourcePortal.TRUEUP,
            location=item.get("location", ""),
            description=item.get("description", ""),
            salary_range=item.get("salary", ""),
            discovered_date=datetime.now(),
        )

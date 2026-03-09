"""Algolia API-based scrapers for YC and Welcome to the Jungle.

Both portals use Algolia as their search backend. We query the Algolia
search API directly with the public search-only API keys embedded in
their page source. This returns structured JSON with full-text search,
faceted filtering, and pagination — far richer than HTML parsing.

Tier A — Low Risk: No browser needed, just httpx POST requests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.httpx_scraper import HttpxScraper
from src.scrapers.rate_limiter import RateLimiter


class AlgoliaBaseScraper(HttpxScraper):
    """Base class for Algolia-powered scrapers.

    Subclasses must set:
        _app_id: Algolia Application ID
        _api_key: Algolia public search-only API key
        _index_name: Algolia index to query
    """

    _app_id: str = ""
    _api_key: str = ""
    _index_name: str = ""

    async def _algolia_search(
        self,
        query: str,
        filters: str = "",
        hits_per_page: int = 50,
        page: int = 0,
    ) -> dict:
        """Execute an Algolia search query.

        Returns the raw Algolia response dict with keys:
        hits, nbHits, page, nbPages, hitsPerPage, etc.
        """
        client = await self._get_client()

        url = f"https://{self._app_id}-dsn.algolia.net/1/indexes/{self._index_name}/query"
        headers = {
            "X-Algolia-Application-Id": self._app_id,
            "X-Algolia-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

        body = {
            "query": query,
            "hitsPerPage": hits_per_page,
            "page": page,
        }
        if filters:
            body["filters"] = filters

        try:
            await self._throttle()
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.warning(f"Algolia search failed for {self.name}: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.warning(f"Algolia returned non-JSON for {self.name}: {e}")
            return {}

    async def _algolia_search_all(
        self,
        query: str,
        filters: str = "",
        max_pages: int = 3,
    ) -> list[dict]:
        """Search Algolia with pagination, returning all hits."""
        all_hits: list[dict] = []

        for page in range(max_pages):
            result = await self._algolia_search(query, filters=filters, page=page)
            hits = result.get("hits", [])
            all_hits.extend(hits)

            nb_pages = result.get("nbPages", 0)
            if page + 1 >= nb_pages:
                break

        return all_hits


class YCAlgoliaScraper(AlgoliaBaseScraper):
    """Work at a Startup (YC) scraper via Algolia API.

    Tier 3 — startup portal (no H1B filter needed).

    YC's Work at a Startup uses Algolia for job search.
    App ID and API key are public search-only credentials
    extracted from the page source.
    """

    # Public search-only credentials from workatastartup.com page source
    _app_id = "45BWZJ1SGC"
    _api_key = "MjBjYjRiMzY0NzdhZWY0NjExY2NhZjYxMGIxYjc2MTAwNWFkNTkwNTc4NjgxYjU0YzFhYTY2ZGQ5OGY5NDMxZnJlc3RyaWN0SW5kaWNlcz0lNUIlMjJZQ0NvbXBhbnlfcHJvZHVjdGlvbiUyMiUyQyUyMllDQ29tcGFueV9CeV9MYXVuY2hfRGF0ZV9wcm9kdWN0aW9uJTIyJTVEJnRhZ0ZpbHRlcnM9JTVCJTIyeWNkY19wdWJsaWMlMjIlNUQmYW5hbHl0aWNzVGFncz0lNUIlMjJ5Y2RjJTIyJTVE"
    _index_name = "YCCompany_production"

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.YC, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        seen_urls: set[str] = set()

        for kw in keywords:
            # Algolia search with keyword
            hits = await self._algolia_search_all(
                query=kw,
                max_pages=2,
            )

            for hit in hits:
                postings = self._parse_yc_hit(hit, kw)
                for p in postings:
                    if p.url and p.url not in seen_urls:
                        seen_urls.add(p.url)
                        if self.apply_h1b_filter(p):
                            results.append(p)

        results = self._post_filter_by_date(results, days)
        logger.info(f"YCAlgoliaScraper found {len(results)} postings")
        return results

    def _parse_yc_hit(self, hit: dict, keyword: str) -> list[JobPosting]:
        """Parse a YC Algolia hit (company) into job postings.

        Each hit is a company with nested job listings.
        """
        postings: list[JobPosting] = []
        company_name = hit.get("name", "")
        batch = hit.get("batch", "")

        # Check if company is hiring
        if not hit.get("highlight_black", "") and not hit.get("jobs", []):
            # Try to extract from top_company_jobs or similar keys
            pass

        # YC Algolia stores jobs under the company hit
        jobs = hit.get("jobs", [])
        if not jobs and isinstance(hit.get("highlight_black"), str):
            # Sometimes the job title is in highlight_black
            jobs = [{"title": hit.get("highlight_black", ""), "url": hit.get("website", "")}]

        for job in jobs:
            if isinstance(job, str):
                # Sometimes jobs is a list of titles
                title = job
                job_url = ""
            elif isinstance(job, dict):
                title = job.get("title", "") or job.get("role", "")
                job_url = job.get("url", "") or job.get("job_url", "")
            else:
                continue

            if not title:
                continue

            # Build URL
            company_slug = hit.get("slug", "")
            if not job_url and company_slug:
                job_url = f"https://www.workatastartup.com/companies/{company_slug}"

            location = ""
            loc_list = hit.get("all_locations", []) or hit.get("regions", [])
            if isinstance(loc_list, list):
                location = ", ".join(str(l) for l in loc_list[:3] if l)

            # Remote info
            work_model = ""
            if hit.get("is_remote", False):
                work_model = "remote"

            posting = JobPosting(
                title=title.strip(),
                company_name=company_name.strip(),
                location=location,
                url=job_url,
                work_model=work_model,
                source_portal=SourcePortal.YC,
                discovered_date=datetime.now(),
            )
            postings.append(posting)

        # If no jobs found but the hit itself looks relevant
        if not postings and company_name:
            one_liner = hit.get("one_liner", "")
            if any(kw.lower() in (one_liner + " " + company_name).lower() for kw in [keyword]):
                company_slug = hit.get("slug", "")
                url = f"https://www.workatastartup.com/companies/{company_slug}" if company_slug else ""
                postings.append(JobPosting(
                    title=f"Engineering at {company_name}",
                    company_name=company_name,
                    url=url,
                    source_portal=SourcePortal.YC,
                    discovered_date=datetime.now(),
                ))

        return postings


class WTTJAlgoliaScraper(AlgoliaBaseScraper):
    """Welcome to the Jungle scraper via Algolia/WelcomeKit API.

    Tier 2 — H1B cross-check required.

    WTTJ literally built the algoliax Elixir library. Their job search
    is powered by Algolia. The API keys are public search-only credentials.
    """

    # Public search-only credentials from welcometothejungle.com page source
    _app_id = "0VETEIO1GR"
    _api_key = "01onal23e552e4e5d9c52b1b4a3906c6d"
    _index_name = "wttj_jobs_production"

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.WTTJ, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        seen_urls: set[str] = set()

        for kw in keywords:
            # Filter for US-based jobs
            filters = "office.country_code:US"

            hits = await self._algolia_search_all(
                query=kw,
                filters=filters,
                max_pages=2,
            )

            for hit in hits:
                posting = self._parse_wttj_hit(hit)
                if posting and posting.url and posting.url not in seen_urls:
                    seen_urls.add(posting.url)
                    if self.apply_h1b_filter(posting):
                        results.append(posting)

        results = self._post_filter_by_date(results, days)
        logger.info(f"WTTJAlgoliaScraper found {len(results)} postings")
        return results

    def _parse_wttj_hit(self, hit: dict) -> JobPosting | None:
        """Parse a WTTJ Algolia hit into a JobPosting."""
        title = hit.get("name", "")
        if not title:
            return None

        # Company info
        company = hit.get("company", {})
        if isinstance(company, dict):
            company_name = company.get("name", "")
        else:
            company_name = str(company) if company else ""

        # Location
        office = hit.get("office", {})
        location = ""
        if isinstance(office, dict):
            city = office.get("city", "")
            state = office.get("state", "")
            country = office.get("country_code", "")
            parts = [p for p in [city, state, country] if p]
            location = ", ".join(parts)

        # URL
        slug = hit.get("slug", "") or hit.get("reference", "")
        company_slug = ""
        if isinstance(company, dict):
            company_slug = company.get("slug", "")

        job_url = ""
        if slug and company_slug:
            job_url = f"https://www.welcometothejungle.com/en/companies/{company_slug}/jobs/{slug}"
        elif slug:
            job_url = f"https://www.welcometothejungle.com/en/jobs/{slug}"

        # Salary
        salary_range = ""
        sal_min = hit.get("salary_min")
        sal_max = hit.get("salary_max")
        salary_currency = hit.get("salary_currency", "USD")
        if sal_min and sal_max:
            if salary_currency == "USD":
                salary_range = f"${int(sal_min)//1000}k-${int(sal_max)//1000}k/yr"
            else:
                salary_range = f"{sal_min}-{sal_max} {salary_currency}"

        # Work model
        work_model = ""
        remote = hit.get("remote", "")
        if remote and str(remote).lower() in ("full", "true", "fulltime"):
            work_model = "remote"
        elif remote and str(remote).lower() in ("partial", "hybrid", "flex"):
            work_model = "hybrid"

        contract_type = hit.get("contract_type", "")

        # Published date
        posted_date = None
        published = hit.get("published_at", "") or hit.get("created_at", "")
        if published:
            try:
                posted_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return JobPosting(
            title=title.strip(),
            company_name=company_name.strip(),
            location=location.strip(),
            url=job_url,
            salary_range=salary_range,
            salary_min=int(sal_min) if sal_min else None,
            salary_max=int(sal_max) if sal_max else None,
            work_model=work_model or contract_type.lower() if contract_type else "",
            source_portal=SourcePortal.WTTJ,
            posted_date=posted_date,
            discovered_date=datetime.now(),
        )

    async def get_posting_details(self, url: str) -> JobPosting:
        """Fetch details via page __NEXT_DATA__ or return minimal."""
        await self._throttle()
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            title_el = soup.select_one("h1, [class*='title']")
            desc_el = soup.select_one("[class*='description'], [class*='content']")

            return JobPosting(
                title=title_el.get_text(strip=True) if title_el else "",
                url=url,
                description=desc_el.get_text(strip=True)[:500] if desc_el else "",
                source_portal=SourcePortal.WTTJ,
            )
        except httpx.HTTPError:
            return JobPosting(url=url, source_portal=SourcePortal.WTTJ)

"""Wellfound (AngelList) scraper using __NEXT_DATA__ JSON parsing.

Wellfound is a Next.js app. All job listing data is embedded in
<script id="__NEXT_DATA__"> tags on server-rendered pages. This approach:
- Uses httpx only (no browser needed)
- Bypasses Cloudflare entirely (no JS execution)
- Gets structured JSON with full job details
- Replaces the broken PlaywrightScraper that used fabricated CSS selectors

The __NEXT_DATA__ JSON contains Apollo GraphQL cache with all page data.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.httpx_scraper import HttpxScraper
from src.scrapers.rate_limiter import RateLimiter


class WellfoundNextDataScraper(HttpxScraper):
    """Wellfound scraper using __NEXT_DATA__ JSON extraction.

    Tier 3 — startup portal (no H1B filter needed).
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.WELLFOUND, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()
        seen_urls: set[str] = set()

        for kw in keywords:
            await self._throttle()
            # Wellfound role search URL pattern
            url = f"https://wellfound.com/role/l/software-engineer/{quote_plus(kw.lower().replace(' ', '-'))}"

            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"Wellfound request failed for '{kw}': {e}")
                continue

            postings = self._parse_next_data(response.text, kw)
            for p in postings:
                if p.url and p.url not in seen_urls:
                    seen_urls.add(p.url)
                    if self.apply_h1b_filter(p):
                        results.append(p)

        logger.info(f"WellfoundNextDataScraper found {len(results)} postings")
        return results

    def _parse_next_data(self, html: str, keyword: str) -> list[JobPosting]:
        """Extract job data from __NEXT_DATA__ script tag."""
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")

        if not script or not script.string:
            logger.debug("No __NEXT_DATA__ found on Wellfound page")
            # Fallback: try to find inline JSON in other script tags
            return self._parse_fallback(soup)

        try:
            data = json.loads(script.string)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse __NEXT_DATA__ JSON: {e}")
            return []

        return self._extract_jobs_from_next_data(data)

    def _extract_jobs_from_next_data(self, data: dict) -> list[JobPosting]:
        """Navigate the __NEXT_DATA__ JSON structure to extract job listings.

        The structure varies but generally follows:
        props.pageProps.{some_key} containing job/startup data,
        or an Apollo GraphQL cache in props.pageProps.__APOLLO_STATE__
        """
        postings: list[JobPosting] = []

        props = data.get("props", {})
        page_props = props.get("pageProps", {})

        # Strategy 1: Apollo GraphQL cache
        apollo_state = page_props.get("__APOLLO_STATE__", {})
        if apollo_state:
            postings.extend(self._parse_apollo_state(apollo_state))
            if postings:
                return postings

        # Strategy 2: Direct job listings in pageProps
        # Look for common keys that contain job data
        for key in ("listings", "jobs", "startupResults", "results", "jobListings"):
            items = page_props.get(key, [])
            if isinstance(items, list) and items:
                for item in items:
                    posting = self._item_to_posting(item)
                    if posting:
                        postings.append(posting)
                if postings:
                    return postings

        # Strategy 3: Recursive search for job-like objects
        postings = self._recursive_find_jobs(page_props)

        return postings

    def _parse_apollo_state(self, apollo_state: dict) -> list[JobPosting]:
        """Parse Apollo GraphQL cache for job/startup data.

        Apollo cache keys look like:
        - "StartupResult:12345" for company cards
        - "JobListing:67890" for individual jobs
        - "Startup:12345" for company details
        """
        postings: list[JobPosting] = []

        # Collect startups and job listings from Apollo cache
        startups: dict[str, dict] = {}
        job_listings: list[dict] = []

        for key, value in apollo_state.items():
            if not isinstance(value, dict):
                continue

            typename = value.get("__typename", "")

            if typename in ("Startup", "StartupResult"):
                startups[key] = value
                # Also store by numeric ID for fallback lookup
                startup_id = key.split(":")[-1] if ":" in key else key
                startups[startup_id] = value
            elif typename in ("JobListing", "Job", "JobPosting"):
                job_listings.append(value)

        # Convert job listings to postings
        for job in job_listings:
            title = job.get("title", "") or job.get("name", "")
            if not title:
                continue

            # Resolve company from startup reference
            company_name = ""
            company_ref = job.get("startup", {})
            if isinstance(company_ref, dict):
                ref_id = company_ref.get("__ref", "")
                if ref_id and ref_id in startups:
                    company_name = startups[ref_id].get("name", "")
                else:
                    company_name = company_ref.get("name", "")
            elif isinstance(company_ref, str):
                company_name = company_ref

            # Extract location
            location = ""
            loc_data = job.get("locationNames", [])
            if isinstance(loc_data, list):
                location = ", ".join(str(l) for l in loc_data if l)
            elif isinstance(loc_data, str):
                location = loc_data
            if not location:
                location = job.get("location", "")

            # Build URL
            slug = job.get("slug", "") or job.get("id", "")
            job_url = f"https://wellfound.com/jobs/{slug}" if slug else ""
            if not job_url:
                ext_url = job.get("externalUrl", "") or job.get("url", "")
                if ext_url:
                    job_url = ext_url

            # Salary
            salary_range = ""
            sal_min = job.get("compensation", {}).get("min", None) if isinstance(job.get("compensation"), dict) else None
            sal_max = job.get("compensation", {}).get("max", None) if isinstance(job.get("compensation"), dict) else None
            if sal_min and sal_max:
                salary_range = f"${int(sal_min)//1000}k-${int(sal_max)//1000}k/yr"

            # Work model
            work_model = ""
            remote = job.get("remote", False)
            if remote:
                work_model = "remote"
            elif location:
                work_model = "onsite"

            posting = JobPosting(
                title=title.strip(),
                company_name=company_name.strip(),
                location=location.strip(),
                url=job_url,
                salary_range=salary_range,
                work_model=work_model,
                source_portal=SourcePortal.WELLFOUND,
                discovered_date=datetime.now(),
            )
            postings.append(posting)

        # If no job listings found but we have startups, extract from startups
        if not postings and startups:
            for startup_data in startups.values():
                jobs = startup_data.get("jobs", [])
                if isinstance(jobs, list):
                    for job in jobs:
                        if isinstance(job, dict):
                            posting = self._item_to_posting(job)
                            if posting:
                                posting.company_name = startup_data.get("name", "")
                                postings.append(posting)

        return postings

    def _item_to_posting(self, item: dict) -> JobPosting | None:
        """Convert a generic job item dict to a JobPosting."""
        if not isinstance(item, dict):
            return None

        title = item.get("title", "") or item.get("name", "") or item.get("jobTitle", "")
        if not title:
            return None

        company = item.get("company_name", "") or item.get("companyName", "") or item.get("startup", "")
        if isinstance(company, dict):
            company = company.get("name", "")

        location = item.get("location", "") or item.get("locationNames", "")
        if isinstance(location, list):
            location = ", ".join(str(l) for l in location if l)

        url = item.get("url", "") or item.get("externalUrl", "") or item.get("slug", "")
        if url and not url.startswith("http"):
            url = f"https://wellfound.com/jobs/{url}"

        salary = item.get("salary_range", "") or item.get("compensation", "")
        if isinstance(salary, dict):
            sal_min = salary.get("min")
            sal_max = salary.get("max")
            salary = f"${int(sal_min)//1000}k-${int(sal_max)//1000}k/yr" if sal_min and sal_max else ""

        work_model = ""
        if item.get("remote"):
            work_model = "remote"

        return JobPosting(
            title=title.strip(),
            company_name=str(company).strip() if company else "",
            location=str(location).strip() if location else "",
            url=url,
            salary_range=str(salary) if salary else "",
            work_model=work_model,
            source_portal=SourcePortal.WELLFOUND,
            discovered_date=datetime.now(),
        )

    def _recursive_find_jobs(self, data: dict | list, depth: int = 0) -> list[JobPosting]:
        """Recursively search for job-like objects in nested data."""
        if depth > 5:
            return []

        postings: list[JobPosting] = []

        if isinstance(data, dict):
            # Check if this dict looks like a job
            if "title" in data and any(k in data for k in ("company", "startup", "companyName", "company_name")):
                posting = self._item_to_posting(data)
                if posting:
                    postings.append(posting)
            else:
                for value in data.values():
                    if isinstance(value, (dict, list)):
                        postings.extend(self._recursive_find_jobs(value, depth + 1))
        elif isinstance(data, list):
            for item in data[:50]:  # Limit to prevent infinite recursion
                if isinstance(item, (dict, list)):
                    postings.extend(self._recursive_find_jobs(item, depth + 1))

        return postings

    def _parse_fallback(self, soup: BeautifulSoup) -> list[JobPosting]:
        """Fallback HTML parsing if __NEXT_DATA__ is not available."""
        postings: list[JobPosting] = []

        # Look for job cards using structural selectors
        for link in soup.select("a[href*='/jobs/']"):
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or len(title) < 5:
                continue

            if href and not href.startswith("http"):
                href = f"https://wellfound.com{href}"

            postings.append(JobPosting(
                title=title,
                url=href,
                source_portal=SourcePortal.WELLFOUND,
                discovered_date=datetime.now(),
            ))

        return postings

    async def get_posting_details(self, url: str) -> JobPosting:
        """Fetch details for a single Wellfound job posting."""
        await self._throttle()
        client = await self._get_client()

        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return JobPosting(url=url, source_portal=SourcePortal.WELLFOUND)

        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")

        if script and script.string:
            try:
                data = json.loads(script.string)
                page_props = data.get("props", {}).get("pageProps", {})

                # Try to find job details in Apollo state or direct props
                apollo = page_props.get("__APOLLO_STATE__", {})
                for key, value in apollo.items():
                    if isinstance(value, dict) and value.get("__typename") in ("JobListing", "Job"):
                        posting = self._item_to_posting(value)
                        if posting:
                            posting.url = url
                            return posting

                # Direct props
                job_data = page_props.get("job", page_props.get("listing", {}))
                if job_data:
                    posting = self._item_to_posting(job_data)
                    if posting:
                        posting.url = url
                        return posting
            except json.JSONDecodeError:
                pass

        # Fallback: basic HTML parsing
        title_el = soup.select_one("h1")
        desc_el = soup.select_one("[class*='description'], [class*='content']")

        return JobPosting(
            title=title_el.get_text(strip=True) if title_el else "",
            url=url,
            description=desc_el.get_text(strip=True)[:500] if desc_el else "",
            source_portal=SourcePortal.WELLFOUND,
        )

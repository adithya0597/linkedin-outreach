from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.rate_limiter import RateLimiter


class HttpxScraper(BaseScraper):
    """Base class for scrapers using httpx + BeautifulSoup."""

    def __init__(self, portal: SourcePortal, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(portal, rate_limiter=rate_limiter)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class StartupJobsScraper(HttpxScraper):
    """startup.jobs scraper (Tier 3 -- startup portal)."""

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.STARTUP_JOBS, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        for kw in keywords:
            await self._throttle()
            url = f"https://startup.jobs/?q={quote_plus(kw)}"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"startup.jobs request failed for '{kw}': {e}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            for card in soup.select(".job-card"):
                title_el = card.select_one(".job-title a, .job-title")
                company_el = card.select_one(".company-name")
                location_el = card.select_one(".location")
                salary_el = card.select_one(".salary")

                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                href = ""
                link = card.select_one("a[href]")
                if link and link.get("href"):
                    href = link["href"]
                    if not href.startswith("http"):
                        href = f"https://startup.jobs{href}"

                posting = JobPosting(
                    title=title,
                    company_name=company_el.get_text(strip=True) if company_el else "",
                    location=location_el.get_text(strip=True) if location_el else "",
                    url=href,
                    salary_range=salary_el.get_text(strip=True) if salary_el else "",
                    source_portal=SourcePortal.STARTUP_JOBS,
                )
                if self.apply_h1b_filter(posting):
                    results.append(posting)

        logger.info(f"StartupJobsScraper found {len(results)} postings")
        return results

    async def get_posting_details(self, url: str) -> JobPosting:
        await self._throttle()
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return JobPosting(url=url, source_portal=SourcePortal.STARTUP_JOBS)

        soup = BeautifulSoup(response.text, "html.parser")
        title_el = soup.select_one("h1")
        company_el = soup.select_one(".company-name")
        desc_el = soup.select_one(".job-description, .description")
        location_el = soup.select_one(".location")

        return JobPosting(
            title=title_el.get_text(strip=True) if title_el else "",
            company_name=company_el.get_text(strip=True) if company_el else "",
            url=url,
            description=desc_el.get_text(strip=True) if desc_el else "",
            location=location_el.get_text(strip=True) if location_el else "",
            source_portal=SourcePortal.STARTUP_JOBS,
        )


class TopStartupsScraper(HttpxScraper):
    """Top Startups scraper (Tier 3 -- startup portal).

    Uses https://topstartups.io/jobs/?q=<kw> — server-rendered cards inside
    ``div.col-12.infinite-item`` with ``h5#job-title``, ``h7`` for company/location,
    and external apply links (Greenhouse, Lever, etc.).
    """

    _healthy = True

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.TOP_STARTUPS, rate_limiter=rate_limiter)

    def is_healthy(self) -> bool:
        return self._healthy

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        for kw in keywords:
            await self._throttle()
            url = f"https://topstartups.io/jobs/?q={quote_plus(kw)}"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"topstartups.io request failed for '{kw}': {e}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select("div.infinite-item")

            if not cards:
                # Fallback: the page may have returned a 404 or be JS-rendered
                if not soup.select_one("body") or "404" in (getattr(soup.title, "string", "") or ""):
                    self._healthy = False
                    logger.warning("topstartups.io returned empty/404 — marking unhealthy")
                continue

            for card in cards:
                title_el = card.select_one("h5#job-title")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                # Company is the first h7 inside the first startup-website-link
                company_el = card.select_one("a#startup-website-link h7")
                company = company_el.get_text(strip=True) if company_el else ""

                # Location is in an h7 that contains a map-marker icon
                location = ""
                for h7 in card.find_all("h7"):
                    icon = h7.find("i", class_=lambda c: c and "map-marker" in c)
                    if icon:
                        location = h7.get_text(strip=True)
                        break

                # Apply link is external (Greenhouse, Lever, etc.)
                href = ""
                apply_btn = card.select_one("a#apply-button")
                if apply_btn and apply_btn.get("href"):
                    href = apply_btn["href"]

                # Badges for metadata
                badges = [b.get_text(strip=True) for b in card.select("span.badge")]
                work_model = ""
                for badge in badges:
                    if badge.lower() in ("remote", "hybrid", "on-site", "onsite"):
                        work_model = badge
                        break

                posting = JobPosting(
                    title=title,
                    company_name=company,
                    location=location,
                    url=href,
                    work_model=work_model,
                    source_portal=SourcePortal.TOP_STARTUPS,
                )
                if self.apply_h1b_filter(posting):
                    results.append(posting)

        logger.info(f"TopStartupsScraper found {len(results)} postings")
        return results

    async def get_posting_details(self, url: str) -> JobPosting:
        """Fetch detail from the external apply link (Greenhouse/Lever/etc.)."""
        await self._throttle()
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return JobPosting(url=url, source_portal=SourcePortal.TOP_STARTUPS)

        soup = BeautifulSoup(response.text, "html.parser")
        title_el = soup.select_one("h1")
        desc_el = soup.select_one(
            ".job-description, .description, #content, .posting-page"
        )
        location_el = soup.select_one(".location, .job-location")

        return JobPosting(
            title=title_el.get_text(strip=True) if title_el else "",
            url=url,
            description=desc_el.get_text(strip=True) if desc_el else "",
            location=location_el.get_text(strip=True) if location_el else "",
            source_portal=SourcePortal.TOP_STARTUPS,
        )


class AIJobsScraper(HttpxScraper):
    """AI Jobs scraper (Tier 2 -- H1B cross-check required).

    Cards are ``a.jobcardStyle1`` with ``div.tw-text-lg.tw-font-medium`` for title,
    ``span.tw-card-title`` for company, ``span.tw-location`` for location.
    Detail page uses ``.post-main-title2`` and ``.job-description-container``.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.AI_JOBS, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        for kw in keywords:
            await self._throttle()
            url = f"https://aijobs.ai/jobs?q={quote_plus(kw)}&location=United+States"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"aijobs.ai request failed for '{kw}': {e}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            for card in soup.select("a.jobcardStyle1[href*='/job/']"):
                title_el = card.select_one("div.tw-text-lg.tw-font-medium")
                company_el = card.select_one("span.tw-card-title")
                location_el = card.select_one("span.tw-location")

                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                href = card.get("href", "")
                if href and not href.startswith("http"):
                    href = f"https://aijobs.ai{href}"

                # Salary text (e.g. "Salary: from $190,000")
                salary = ""
                for span in card.select("span.tw-text-sm"):
                    text = span.get_text(strip=True)
                    if "$" in text or "salary" in text.lower():
                        salary = text.replace("Salary:", "").strip()
                        break

                posting = JobPosting(
                    title=title,
                    company_name=company_el.get_text(strip=True) if company_el else "",
                    location=location_el.get_text(strip=True) if location_el else "",
                    url=href,
                    salary_range=salary,
                    source_portal=SourcePortal.AI_JOBS,
                )
                if self.apply_h1b_filter(posting):
                    results.append(posting)

        logger.info(f"AIJobsScraper found {len(results)} postings")
        return results

    async def get_posting_details(self, url: str) -> JobPosting:
        await self._throttle()
        client = await self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return JobPosting(url=url, source_portal=SourcePortal.AI_JOBS)

        soup = BeautifulSoup(response.text, "html.parser")

        title_el = soup.select_one(".post-main-title2")
        desc_el = soup.select_one(".job-description-container")
        location_el = soup.select_one("span.tw-location")

        # Company from the detail page title box
        company = ""
        for a_tag in soup.select(".job-details-title-box a[href*='/company/']"):
            for span in a_tag.find_all("span"):
                text = span.get_text(strip=True)
                if text and text != "at":
                    company = text
                    break
            if company:
                break

        return JobPosting(
            title=title_el.get_text(strip=True) if title_el else "",
            company_name=company,
            url=url,
            description=desc_el.get_text(strip=True) if desc_el else "",
            location=location_el.get_text(strip=True) if location_el else "",
            source_portal=SourcePortal.AI_JOBS,
        )


class HiringCafeHttpxScraper(HttpxScraper):
    """Hiring Cafe scraper (Tier 3 -- startup portal).

    Uses the Hiring Cafe JSON API directly — no HTML parsing needed.
    API endpoint: GET https://hiring.cafe/api/search-jobs
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.HIRING_CAFE, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        for kw in keywords:
            await self._throttle()
            url = (
                f"https://hiring.cafe/api/search-jobs"
                f"?searchQuery={quote_plus(kw)}"
                f"&countryCode=US"
                f"&limit=50"
                f"&dateFetchedPastNDays={days}"
            )
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"hiring.cafe API request failed for '{kw}': {e}")
                continue

            try:
                data = response.json()
            except Exception as e:
                logger.warning(f"hiring.cafe returned non-JSON response for '{kw}': {e}")
                continue

            for item in data.get("results", []):
                job_info = item.get("job_information", {})
                processed = item.get("v5_processed_job_data", {})
                company_data = item.get("enriched_company_data", {})

                title = job_info.get("title", "")
                if not title:
                    continue

                company_name = processed.get("company_name", "") or company_data.get("name", "")
                location = processed.get("formatted_workplace_location", "")
                work_model = processed.get("workplace_type", "")

                # Build salary string from yearly min/max compensation
                salary_range = ""
                sal_min = processed.get("yearly_min_compensation")
                sal_max = processed.get("yearly_max_compensation")
                if sal_min and sal_max:
                    salary_range = f"${sal_min // 1000}k-${sal_max // 1000}k/yr"
                elif sal_min:
                    salary_range = f"${sal_min // 1000}k/yr"
                elif sal_max:
                    salary_range = f"${sal_max // 1000}k/yr"

                # URL: prefer apply_url, fallback to requisition_id
                apply_url = item.get("apply_url", "")
                requisition_id = item.get("requisition_id", "")
                if apply_url:
                    job_url = apply_url
                elif requisition_id:
                    job_url = f"https://hiring.cafe/viewjob/{requisition_id}"
                else:
                    job_url = ""

                # H1B visa info from API
                h1b_mentioned = False
                h1b_text = ""
                visa_sponsorship = processed.get("visa_sponsorship")
                if visa_sponsorship is not None:
                    h1b_mentioned = True
                    h1b_text = "yes" if visa_sponsorship else "no"

                # Parse posted date
                posted_date = None
                pub_date_str = processed.get("estimated_publish_date", "")
                if pub_date_str:
                    try:
                        posted_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

                posting = JobPosting(
                    title=title,
                    company_name=company_name,
                    location=location,
                    url=job_url,
                    salary_range=salary_range,
                    salary_min=sal_min,
                    salary_max=sal_max,
                    work_model=work_model.lower() if work_model else "",
                    source_portal=SourcePortal.HIRING_CAFE,
                    h1b_mentioned=h1b_mentioned,
                    h1b_text=h1b_text,
                    posted_date=posted_date,
                )
                if self.apply_h1b_filter(posting):
                    results.append(posting)

        logger.info(f"HiringCafeHttpxScraper found {len(results)} postings")
        return results

    async def get_posting_details(self, url: str) -> JobPosting:
        """Fetch details for a single posting via requisition ID lookup or return minimal."""
        # Try to extract requisition_id from URL
        match = re.search(r"/viewjob/([^/?]+)", url)
        if match:
            req_id = match.group(1)
            await self._throttle()
            client = await self._get_client()
            try:
                api_url = f"https://hiring.cafe/api/search-jobs?requisitionId={req_id}"
                response = await client.get(api_url)
                response.raise_for_status()
                data = response.json()
                items = data.get("results", [])
                if items:
                    item = items[0]
                    job_info = item.get("job_information", {})
                    processed = item.get("v5_processed_job_data", {})
                    company_data = item.get("enriched_company_data", {})
                    return JobPosting(
                        title=job_info.get("title", ""),
                        company_name=processed.get("company_name", "") or company_data.get("name", ""),
                        location=processed.get("formatted_workplace_location", ""),
                        url=url,
                        source_portal=SourcePortal.HIRING_CAFE,
                    )
            except httpx.HTTPError:
                pass
        return JobPosting(url=url, source_portal=SourcePortal.HIRING_CAFE)


class YCHttpxScraper(HttpxScraper):
    """Work at a Startup (YC) scraper (Tier 3 -- startup portal).

    Scrapes the server-rendered HTML at https://www.workatastartup.com/jobs
    using httpx + BeautifulSoup. Tier 3 = no H1B filter.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.YC, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        await self._throttle()
        url = "https://www.workatastartup.com/jobs"
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"workatastartup.com request failed: {e}")
            return results

        soup = BeautifulSoup(response.text, "html.parser")

        # Find all company links (links to /companies/slug but NOT to /jobs/)
        company_links = soup.select('a[href*="/companies/"]')

        # Group elements by their parent container
        # Each job card has: company link, job title link (ycombinator.com), details <p>, apply link
        processed_job_urls: set[str] = set()

        # Find all job title links (ycombinator.com/companies/.../jobs/...)
        job_links = soup.select('a[href*="ycombinator.com/companies/"][href*="/jobs/"]')

        for job_link in job_links:
            job_title = job_link.get_text(strip=True)
            job_url = job_link.get("href", "")
            if not job_title or not job_url or job_url in processed_job_urls:
                continue
            processed_job_urls.add(job_url)

            # Walk up to find the card container, then find sibling elements
            card = job_link
            for _ in range(5):
                parent = card.parent
                if parent is None:
                    break
                card = parent
                # Check if this container has a company link
                co_link = card.find("a", href=re.compile(r"/companies/[^/]+$"))
                if co_link:
                    break

            # Parse company name from the company link text
            company_name = ""
            co_link = card.find("a", href=re.compile(r"/companies/[^/]+$"))
            if co_link:
                co_text = co_link.get_text(strip=True)
                # Strip batch tag like "(W21)" and description after bullet
                co_text = re.sub(r"\((?:W|S|IK)\d{2}\)", "", co_text)
                if "\u2022" in co_text:
                    co_text = co_text.split("\u2022")[0]
                company_name = co_text.strip()

            # Parse location from <p> tag near the job link
            location = ""
            details_p = job_link.find_next("p")
            if details_p:
                details_text = details_p.get_text(strip=True)
                # Strip employment type prefix (fulltime, intern, contract, parttime)
                details_text = re.sub(
                    r"^(fulltime|full-time|part-time|parttime|intern|contract)\s*",
                    "",
                    details_text,
                    flags=re.IGNORECASE,
                )
                # Strip trailing role type (e.g., "Full stack", "Backend", "Frontend")
                location = details_text.strip()

            posting = JobPosting(
                title=job_title,
                company_name=company_name,
                location=location,
                url=job_url,
                source_portal=SourcePortal.YC,
                discovered_date=datetime.now(),
            )
            if self.apply_h1b_filter(posting):
                results.append(posting)

        # YC doesn't have keyword search — post-filter by date
        results = self._post_filter_by_date(results, days)

        logger.info(f"YCHttpxScraper found {len(results)} postings")
        return results


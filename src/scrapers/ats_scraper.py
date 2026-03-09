"""ATS API scrapers for Ashby and Greenhouse job boards.

These scrapers hit structured JSON APIs directly — no HTML parsing needed
for the main job listing. Follows the HiringCafeHttpxScraper pattern.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.httpx_scraper import HttpxScraper
from src.scrapers.rate_limiter import RateLimiter


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_H1B_KEYWORDS = [
    "h1b", "h-1b", "h1-b",
    "visa sponsor", "visa sponsorship",
    "work authorization", "work permit",
    "employment eligibility",
    "immigration sponsor",
    "ead", "opt", "cpt",
]

_AI_KEYWORDS = [
    "ai", "ml", "machine learning", "deep learning",
    "llm", "nlp", "natural language", "computer vision",
    "data scientist", "data science",
    "genai", "generative ai", "gen ai",
    "neural", "transformer", "rag",
    "founding engineer",
]


def _parse_h1b_from_description(text: str) -> tuple[bool, str]:
    """Search for H1B / visa sponsorship keywords in job description text.

    Returns:
        (h1b_mentioned, h1b_text) — the first matching line or empty string.
    """
    if not text:
        return False, ""

    text_lower = text.lower()
    for keyword in _H1B_KEYWORDS:
        if keyword in text_lower:
            # Find the line containing the keyword
            for line in text.split("\n"):
                if keyword in line.lower():
                    return True, line.strip()
            return True, ""

    return False, ""


def _parse_salary_from_description(text: str) -> tuple[str, int | None, int | None]:
    """Extract salary range from description text via regex.

    Returns:
        (salary_range_str, salary_min, salary_max)
    """
    if not text:
        return "", None, None

    # Match patterns like "$150,000 - $200,000", "$150k-$200k", "$150K - $200K/yr"
    patterns = [
        # $150,000 - $200,000  (with optional /yr, /year, per year)
        r"\$\s*([\d,]+)\s*(?:[-–—to]+)\s*\$\s*([\d,]+)\s*(?:/?\s*(?:yr|year|annually|per\s+year))?",
        # $150k - $200k
        r"\$\s*(\d+)\s*[kK]\s*(?:[-–—to]+)\s*\$\s*(\d+)\s*[kK]",
        # $150,000+ or $150k+
        r"\$\s*([\d,]+)\s*\+",
        r"\$\s*(\d+)\s*[kK]\s*\+",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                # Range pattern
                raw_min = groups[0].replace(",", "")
                raw_max = groups[1].replace(",", "")
                sal_min = int(raw_min)
                sal_max = int(raw_max)
                # Normalize k values (e.g., 150 -> 150000)
                if sal_min < 1000:
                    sal_min *= 1000
                if sal_max < 1000:
                    sal_max *= 1000
                sal_str = f"${sal_min // 1000}k-${sal_max // 1000}k/yr"
                return sal_str, sal_min, sal_max
            elif len(groups) == 1:
                # Single value with +
                raw = groups[0].replace(",", "")
                sal_min = int(raw)
                if sal_min < 1000:
                    sal_min *= 1000
                sal_str = f"${sal_min // 1000}k+/yr"
                return sal_str, sal_min, None

    return "", None, None


def _matches_keywords(title: str, department: str, keywords: list[str] | None = None) -> bool:
    """Check if a job title or department matches AI/ML keywords.

    If no keywords list is provided, uses the default _AI_KEYWORDS.
    """
    if keywords is None:
        keywords = _AI_KEYWORDS

    combined = f"{title} {department}".lower()
    return any(kw in combined for kw in keywords)


def _strip_html(html: str) -> str:
    """Strip HTML tags using BeautifulSoup and return plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


# ---------------------------------------------------------------------------
# Company slug mappings
# ---------------------------------------------------------------------------

ASHBY_SLUGS: dict[str, str] = {
    "llamaindex": "llamaindex",
    "cursor": "cursor",
    "hippocratic_ai": "Hippocratic%20AI",
    "langchain": "langchain",
    "norm_ai": "norm-ai",
    "cinder": "cinder",
    "evenup": "evenup",
}

GREENHOUSE_SLUGS: dict[str, str] = {
    "snorkelai": "snorkelai",
}


# ---------------------------------------------------------------------------
# Ashby Scraper
# ---------------------------------------------------------------------------


class AshbyScraper(HttpxScraper):
    """Ashby ATS API scraper.

    Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{slug}
    Returns JSON with ``jobs`` array. Each job has:
    title, location, departmentName, employmentType, descriptionPlain,
    publishedAt, jobUrl.

    Post-fetch keyword filter on title/department for AI/ML relevance.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.ASHBY, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        for slug_key, slug in ASHBY_SLUGS.items():
            await self._throttle()
            url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"Ashby API request failed for slug '{slug_key}': {e}")
                continue

            try:
                data = response.json()
            except Exception as e:
                logger.warning(f"Ashby returned non-JSON for slug '{slug_key}': {e}")
                continue

            jobs = data.get("jobs", [])
            for job in jobs:
                title = job.get("title", "")
                if not title:
                    continue

                department = job.get("departmentName", "")

                # Post-fetch keyword filter for AI/ML relevance
                if not _matches_keywords(title, department, keywords):
                    continue

                location = job.get("location", "")
                if isinstance(location, dict):
                    location = location.get("name", "")

                description = job.get("descriptionPlain", "")
                job_url = job.get("jobUrl", "")
                employment_type = job.get("employmentType", "")

                # Parse H1B and salary from description
                h1b_mentioned, h1b_text = _parse_h1b_from_description(description)
                salary_range, salary_min, salary_max = _parse_salary_from_description(description)

                # Parse posted date
                posted_date = None
                published_at = job.get("publishedAt", "")
                if published_at:
                    try:
                        posted_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

                # Derive company name from slug key
                company_name = slug_key.replace("_", " ").title()

                posting = JobPosting(
                    title=title,
                    company_name=company_name,
                    location=location,
                    url=job_url,
                    description=description[:500] if description else "",
                    work_model=employment_type.lower() if employment_type else "",
                    salary_range=salary_range,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    source_portal=SourcePortal.ASHBY,
                    h1b_mentioned=h1b_mentioned,
                    h1b_text=h1b_text,
                    posted_date=posted_date,
                )
                if self.apply_h1b_filter(posting):
                    results.append(posting)

        logger.info(f"AshbyScraper found {len(results)} postings")
        return results


# ---------------------------------------------------------------------------
# Greenhouse Scraper
# ---------------------------------------------------------------------------


class GreenhouseScraper(HttpxScraper):
    """Greenhouse Boards API scraper.

    Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    Returns JSON with ``jobs`` array. Each job has:
    title, location.name, content (HTML), absolute_url, updated_at.

    HTML content is stripped via BeautifulSoup for description parsing.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.GREENHOUSE, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()

        for slug_key, slug in GREENHOUSE_SLUGS.items():
            await self._throttle()
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"Greenhouse API request failed for slug '{slug_key}': {e}")
                continue

            try:
                data = response.json()
            except Exception as e:
                logger.warning(f"Greenhouse returned non-JSON for slug '{slug_key}': {e}")
                continue

            jobs = data.get("jobs", [])
            for job in jobs:
                title = job.get("title", "")
                if not title:
                    continue

                # Post-fetch keyword filter for AI/ML relevance
                department_data = job.get("departments", [])
                department = ""
                if department_data and isinstance(department_data, list):
                    department = department_data[0].get("name", "") if department_data[0] else ""

                if not _matches_keywords(title, department, keywords):
                    continue

                # Location
                location_data = job.get("location", {})
                location = ""
                if isinstance(location_data, dict):
                    location = location_data.get("name", "")
                elif isinstance(location_data, str):
                    location = location_data

                # Content — strip HTML to get plain text
                content_html = job.get("content", "")
                description = _strip_html(content_html)

                job_url = job.get("absolute_url", "")

                # Parse H1B and salary from stripped content
                h1b_mentioned, h1b_text = _parse_h1b_from_description(description)
                salary_range, salary_min, salary_max = _parse_salary_from_description(description)

                # Parse updated_at as posted date
                posted_date = None
                updated_at = job.get("updated_at", "")
                if updated_at:
                    try:
                        posted_date = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

                # Derive company name from slug key
                company_name = slug_key.replace("_", " ").title()

                posting = JobPosting(
                    title=title,
                    company_name=company_name,
                    location=location,
                    url=job_url,
                    description=description[:500] if description else "",
                    salary_range=salary_range,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    source_portal=SourcePortal.GREENHOUSE,
                    h1b_mentioned=h1b_mentioned,
                    h1b_text=h1b_text,
                    posted_date=posted_date,
                )
                if self.apply_h1b_filter(posting):
                    results.append(posting)

        logger.info(f"GreenhouseScraper found {len(results)} postings")
        return results


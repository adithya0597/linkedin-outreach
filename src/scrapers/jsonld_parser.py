"""Schema.org JobPosting JSON-LD extractor.

Extracts structured job posting data from Schema.org JSON-LD markup
embedded in career pages. Many ATS platforms (Workday, iCIMS, Lever,
Greenhouse) include JSON-LD structured data that can be parsed without
any HTML scraping.

Tier D — Zero Risk: Reads structured data that sites intentionally expose.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting


def extract_jsonld_jobs(html: str, source_url: str = "") -> list[JobPosting]:
    """Extract JobPosting JSON-LD from HTML content.

    Finds all <script type="application/ld+json"> tags and extracts
    Schema.org JobPosting objects.

    Args:
        html: Raw HTML content of a career/job page.
        source_url: URL of the page (for fallback URL construction).

    Returns:
        List of JobPosting objects extracted from JSON-LD.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    postings: list[JobPosting] = []

    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue

        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue

        # Handle single object or array
        items = data if isinstance(data, list) else [data]

        for item in items:
            if not isinstance(item, dict):
                continue

            # Check if it's a JobPosting or contains JobPosting items
            schema_type = item.get("@type", "")

            if schema_type == "JobPosting":
                posting = _parse_job_posting(item, source_url)
                if posting:
                    postings.append(posting)

            elif schema_type in ("ItemList", "CollectionPage"):
                # List of job postings
                for list_item in item.get("itemListElement", []):
                    if isinstance(list_item, dict):
                        job_item = list_item.get("item", list_item)
                        if isinstance(job_item, dict) and job_item.get("@type") == "JobPosting":
                            posting = _parse_job_posting(job_item, source_url)
                            if posting:
                                postings.append(posting)

            elif "@graph" in item:
                # JSON-LD graph format
                for graph_item in item["@graph"]:
                    if isinstance(graph_item, dict) and graph_item.get("@type") == "JobPosting":
                        posting = _parse_job_posting(graph_item, source_url)
                        if posting:
                            postings.append(posting)

    logger.debug(f"Extracted {len(postings)} JobPosting(s) from JSON-LD in {source_url}")
    return postings


def _parse_job_posting(data: dict, source_url: str) -> JobPosting | None:
    """Parse a Schema.org JobPosting object into our JobPosting dataclass."""
    title = data.get("title", "")
    if not title:
        return None

    # Company
    company_name = ""
    hiring_org = data.get("hiringOrganization", {})
    if isinstance(hiring_org, dict):
        company_name = hiring_org.get("name", "")
    elif isinstance(hiring_org, str):
        company_name = hiring_org

    # Location
    location = ""
    job_location = data.get("jobLocation", {})
    if isinstance(job_location, dict):
        address = job_location.get("address", {})
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality", ""),
                address.get("addressRegion", ""),
                address.get("addressCountry", ""),
            ]
            location = ", ".join(p for p in parts if p)
        elif isinstance(address, str):
            location = address
    elif isinstance(job_location, list):
        # Multiple locations
        locations = []
        for loc in job_location[:3]:
            if isinstance(loc, dict):
                addr = loc.get("address", {})
                if isinstance(addr, dict):
                    city = addr.get("addressLocality", "")
                    state = addr.get("addressRegion", "")
                    if city:
                        locations.append(f"{city}, {state}" if state else city)
        location = " | ".join(locations)

    # URL
    job_url = data.get("url", "") or data.get("sameAs", "") or source_url

    # Salary
    salary_range = ""
    salary_min = None
    salary_max = None
    base_salary = data.get("baseSalary", {})
    if isinstance(base_salary, dict):
        value = base_salary.get("value", {})
        currency = base_salary.get("currency", "USD")
        if isinstance(value, dict):
            sal_min = value.get("minValue")
            sal_max = value.get("maxValue")
            if sal_min and sal_max:
                salary_min = int(float(sal_min))
                salary_max = int(float(sal_max))
                if currency == "USD":
                    salary_range = f"${salary_min // 1000}k-${salary_max // 1000}k/yr"
                else:
                    salary_range = f"{sal_min}-{sal_max} {currency}"
        elif isinstance(value, (int, float)):
            salary_min = int(value)
            if currency == "USD":
                salary_range = f"${salary_min // 1000}k/yr"

    # Work model
    work_model = ""
    job_location_type = data.get("jobLocationType", "")
    if job_location_type:
        if "remote" in str(job_location_type).lower():
            work_model = "remote"
    employment_type = data.get("employmentType", "")
    if isinstance(employment_type, list):
        employment_type = employment_type[0] if employment_type else ""

    # Description
    description = data.get("description", "")
    if description:
        # Strip HTML from description
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()[:500]

    # H1B check in description
    h1b_mentioned = False
    h1b_text = ""
    if description:
        desc_lower = description.lower()
        for term in ("h1b", "h-1b", "visa sponsor", "visa sponsorship"):
            if term in desc_lower:
                h1b_mentioned = True
                for line in description.split("."):
                    if term in line.lower():
                        h1b_text = line.strip()
                        break
                break

    # Posted date
    posted_date = None
    date_posted = data.get("datePosted", "")
    if date_posted:
        try:
            posted_date = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    return JobPosting(
        title=title.strip(),
        company_name=company_name.strip(),
        location=location.strip(),
        url=job_url,
        description=description,
        salary_range=salary_range,
        salary_min=salary_min,
        salary_max=salary_max,
        work_model=work_model,
        source_portal=SourcePortal.MANUAL,
        h1b_mentioned=h1b_mentioned,
        h1b_text=h1b_text,
        posted_date=posted_date,
        discovered_date=datetime.now(),
    )


async def fetch_and_extract_jsonld(
    url: str,
    client: httpx.AsyncClient | None = None,
) -> list[JobPosting]:
    """Fetch a URL and extract JSON-LD JobPosting data.

    Args:
        url: Career page or job listing URL.
        client: Optional httpx client (creates one if not provided).

    Returns:
        List of JobPosting objects found in the page's JSON-LD.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
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

    try:
        response = await client.get(url)
        response.raise_for_status()
        return extract_jsonld_jobs(response.text, source_url=url)
    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch {url} for JSON-LD extraction: {e}")
        return []
    finally:
        if own_client:
            await client.aclose()

"""Parser for LinkedIn Job Alert email HTML content.

LinkedIn sends job alert emails from jobs-noreply@linkedin.com with
HTML content containing job cards. Each card has:
- Job title (link to LinkedIn job page)
- Company name
- Location
- Sometimes salary info
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from loguru import logger


@dataclass
class AlertJob:
    """A single job extracted from a LinkedIn alert email."""
    title: str = ""
    company_name: str = ""
    location: str = ""
    url: str = ""
    salary_range: str = ""


def parse_linkedin_alert_html(html_content: str) -> list[AlertJob]:
    """Parse a LinkedIn Job Alert email's HTML and extract job listings.

    LinkedIn alert emails contain job cards in a table-based layout.
    Each job card has a link to the job posting, company name, and location.
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    jobs: list[AlertJob] = []

    # LinkedIn alert emails use various structures:
    # 1. Links containing "/jobs/view/" in href
    # 2. Table cells with job info

    # Strategy: find all links to LinkedIn job pages
    job_links = soup.find_all("a", href=re.compile(r"linkedin\.com/(?:comm/)?jobs/view/\d+"))

    seen_urls: set[str] = set()

    for link in job_links:
        href = link.get("href", "")
        # Clean tracking params — extract the core job URL
        clean_url = _clean_linkedin_url(href)
        if not clean_url or clean_url in seen_urls:
            continue
        seen_urls.add(clean_url)

        # The link text is usually the job title
        title = link.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        # Walk up to the containing table cell or div to find company/location
        container = _find_job_container(link)
        company = ""
        location = ""
        salary = ""

        if container:
            # Look for text elements near the job title
            texts = _extract_nearby_text(container, title)
            if len(texts) >= 1:
                company = texts[0]
            if len(texts) >= 2:
                location = texts[1]

            # Check for salary info
            salary_match = re.search(r"\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?(?:\s*/\s*(?:yr|year|hr|hour))?", container.get_text())
            if salary_match:
                salary = salary_match.group(0)

        jobs.append(AlertJob(
            title=title,
            company_name=company,
            location=location,
            url=clean_url,
            salary_range=salary,
        ))

    logger.info(f"Parsed {len(jobs)} jobs from LinkedIn alert email")
    return jobs


def _clean_linkedin_url(url: str) -> str:
    """Extract clean LinkedIn job URL from tracked email link."""
    # LinkedIn wraps URLs in tracking redirects
    # Extract the actual job URL
    match = re.search(r"(https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/\d+)", url)
    if match:
        base = match.group(1)
        # Normalize: remove /comm/ prefix if present
        base = base.replace("/comm/jobs/", "/jobs/")
        return base
    return ""


def _find_job_container(element) -> object | None:
    """Walk up the DOM to find the containing cell/div for a job card."""
    current = element
    for _ in range(8):
        parent = current.parent
        if parent is None:
            break
        # Stop at table cells, divs with multiple children, or tr elements
        if parent.name in ("td", "tr") and len(list(parent.children)) > 2:
            return parent
        if parent.name == "div" and len(list(parent.children)) > 2:
            return parent
        current = parent
    return current.parent


def _extract_nearby_text(container, exclude_title: str) -> list[str]:
    """Extract text elements from a container, excluding the job title."""
    texts: list[str] = []

    # Get all text-bearing elements
    for el in container.find_all(["span", "p", "td", "a", "div"]):
        text = el.get_text(strip=True)
        if not text or text == exclude_title:
            continue
        # Skip very short or very long text
        if len(text) < 2 or len(text) > 100:
            continue
        # Skip if it's just a URL or button text
        if text.lower() in ("view job", "apply", "see more", "similar jobs"):
            continue
        # Skip duplicates
        if text not in texts:
            texts.append(text)

    return texts[:3]  # Return at most company, location, one extra


def parse_alert_subject(subject: str) -> dict[str, str]:
    """Parse the email subject line for metadata.

    LinkedIn subjects look like:
    - "3 new jobs for AI Engineer in United States"
    - "AI Engineer: 5 new jobs"
    """
    result: dict[str, str] = {}

    # "N new jobs for KEYWORD in LOCATION"
    match = re.match(r"(\d+)\s+new\s+jobs?\s+for\s+(.+?)\s+in\s+(.+)", subject, re.IGNORECASE)
    if match:
        result["count"] = match.group(1)
        result["keyword"] = match.group(2)
        result["location"] = match.group(3)
        return result

    # "KEYWORD: N new jobs"
    match = re.match(r"(.+?):\s*(\d+)\s+new\s+jobs?", subject, re.IGNORECASE)
    if match:
        result["keyword"] = match.group(1)
        result["count"] = match.group(2)
        return result

    return result

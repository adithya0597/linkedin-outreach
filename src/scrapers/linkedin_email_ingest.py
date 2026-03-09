"""LinkedIn Job Alert email ingest scraper.

Supplementary LinkedIn strategy: parses LinkedIn Job Alert emails
via Gmail MCP to catch jobs between active MCP Playwright scans.
Zero detection risk — just reading email.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from src.config.enums import SourcePortal
from src.integrations.gmail_alert_parser import AlertJob, parse_linkedin_alert_html
from src.models.job_posting import JobPosting
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.rate_limiter import RateLimiter


class LinkedInAlertScraper(BaseScraper):
    """Scraper that ingests LinkedIn Job Alert emails via Gmail.

    This is the SUPPLEMENTARY LinkedIn strategy. It parses emails from
    jobs-noreply@linkedin.com to extract job postings passively.

    The PRIMARY LinkedIn strategy is the MCP Playwright skill.

    Usage:
        Results come from pre-fetched email data (passed via inject_emails)
        or from a JSON file of parsed alerts, since this scraper cannot
        directly call Gmail MCP tools during async execution.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        # Uses LINKEDIN portal (not a separate enum) since these are LinkedIn jobs
        super().__init__(SourcePortal.LINKEDIN, rate_limiter=rate_limiter)
        self._email_htmls: list[str] = []

    def is_healthy(self) -> bool:
        """Always healthy — zero ban risk."""
        return True

    def inject_emails(self, email_htmls: list[str]) -> None:
        """Pre-load email HTML content for processing.

        In practice, the CLI or daily scanner fetches emails via Gmail MCP
        and passes the HTML content here before calling search().
        """
        self._email_htmls = email_htmls

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        """Parse injected LinkedIn alert emails into JobPostings.

        Args:
            keywords: Not used for email parsing (emails are pre-filtered by LinkedIn).
            days: Not used (email recency is handled by Gmail query).
        """
        if not self._email_htmls:
            logger.info("LinkedInAlertScraper: No emails injected — skipping")
            return []

        all_jobs: list[AlertJob] = []
        for html in self._email_htmls:
            jobs = parse_linkedin_alert_html(html)
            all_jobs.extend(jobs)

        # Deduplicate by URL
        seen: set[str] = set()
        unique_jobs: list[AlertJob] = []
        for job in all_jobs:
            if job.url and job.url not in seen:
                seen.add(job.url)
                unique_jobs.append(job)

        # Convert to JobPostings
        postings: list[JobPosting] = []
        for job in unique_jobs:
            posting = JobPosting(
                title=job.title,
                company_name=job.company_name,
                location=job.location,
                url=job.url,
                salary_range=job.salary_range,
                source_portal=SourcePortal.LINKEDIN,
                discovered_date=datetime.now(),
            )
            if self.apply_h1b_filter(posting):
                postings.append(posting)

        logger.info(f"LinkedInAlertScraper parsed {len(postings)} postings from {len(self._email_htmls)} emails")
        # Clear injected emails after processing
        self._email_htmls = []
        return postings


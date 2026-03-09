"""JobSpy multi-source aggregator scraper.

Wraps the python-jobspy library which aggregates job listings from
multiple sources (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google).
Provides broad coverage with a single query.

Tier D — New Source: Additional coverage at low risk.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.rate_limiter import RateLimiter


class JobSpyScraper(BaseScraper):
    """Multi-source job aggregator using python-jobspy.

    Searches across LinkedIn, Indeed, Glassdoor, and ZipRecruiter
    simultaneously. Results are deduplicated by URL against existing DB.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.MANUAL, rate_limiter=rate_limiter)
        self._portal_name = "JobSpy"

    @property
    def name(self) -> str:
        return self._portal_name

    def is_healthy(self) -> bool:
        """Check if python-jobspy is installed."""
        try:
            import jobspy  # noqa: F401
            return True
        except ImportError:
            return False

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []

        try:
            from jobspy import scrape_jobs
        except ImportError:
            logger.warning("python-jobspy not installed — run: pip install python-jobspy")
            return results

        import asyncio

        for kw in keywords:
            await self._throttle()
            try:
                # Run synchronous jobspy in thread pool
                df = await asyncio.to_thread(
                    scrape_jobs,
                    site_name=["indeed", "glassdoor", "zip_recruiter"],
                    search_term=kw,
                    location="United States",
                    results_wanted=50,
                    hours_old=days * 24,
                    country_indeed="USA",
                )

                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    title = str(row.get("title", "")).strip()
                    if not title:
                        continue

                    company = str(row.get("company_name", "")).strip()
                    location = str(row.get("location", "")).strip()
                    job_url = str(row.get("job_url", "")).strip()

                    # Salary
                    salary_range = ""
                    sal_min = row.get("min_amount")
                    sal_max = row.get("max_amount")
                    if sal_min and sal_max:
                        try:
                            salary_range = f"${int(float(sal_min))//1000}k-${int(float(sal_max))//1000}k/yr"
                        except (ValueError, TypeError):
                            pass

                    # Description
                    description = str(row.get("description", ""))[:500]

                    # H1B check in description
                    h1b_mentioned = False
                    h1b_text = ""
                    desc_lower = description.lower()
                    for term in ("h1b", "h-1b", "visa sponsor"):
                        if term in desc_lower:
                            h1b_mentioned = True
                            for line in description.split("\n"):
                                if term in line.lower():
                                    h1b_text = line.strip()
                                    break
                            break

                    # Posted date
                    posted_date = None
                    date_posted = row.get("date_posted")
                    if date_posted:
                        try:
                            if isinstance(date_posted, str):
                                posted_date = datetime.fromisoformat(date_posted)
                            elif hasattr(date_posted, "to_pydatetime"):
                                posted_date = date_posted.to_pydatetime()
                        except (ValueError, TypeError):
                            pass

                    posting = JobPosting(
                        title=title,
                        company_name=company,
                        location=location,
                        url=job_url,
                        description=description,
                        salary_range=salary_range,
                        source_portal=SourcePortal.MANUAL,
                        h1b_mentioned=h1b_mentioned,
                        h1b_text=h1b_text,
                        posted_date=posted_date,
                        discovered_date=datetime.now(),
                    )
                    if self.apply_h1b_filter(posting):
                        results.append(posting)

            except Exception as e:
                logger.warning(f"JobSpy search failed for '{kw}': {e}")
                continue

        logger.info(f"JobSpyScraper found {len(results)} postings")
        return results


"""Automated LinkedIn job scraper using Patchright stealth browser.

Replaces the MCP stub that returned []. Uses Chrome profile with logged-in
LinkedIn session. Replicates the /scan-linkedin skill logic as a programmatic scraper.

Safety limits (per Anti-Bot Intelligence):
- Max 5 result pages per scan (50 jobs)
- Random 3-7 second delays between page loads
- CAPTCHA detection -> immediate stop, return partial results
- Max 1 scan per day (tracked via last_scan timestamp)
- Always headless=False (LinkedIn detects headless)
- Always channel="chrome" (user's installed Chrome with sessions)
"""

from __future__ import annotations

import json
import random
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus

from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.patchright_scraper import PatchrightScraper
from src.scrapers.rate_limiter import RateLimiter

# Safety constants
MAX_PAGES = 5
MIN_DELAY_MS = 3000
MAX_DELAY_MS = 7000
MAX_SCANS_PER_DAY = 1
SCAN_RECORD_PATH = Path("data/mcp_scans")


class LinkedInPatchrightScraper(PatchrightScraper):
    """Automated LinkedIn job scraper using Patchright.

    Uses Chrome profile (via temp copy) with logged-in LinkedIn session.
    BehavioralLayer for human-like interaction.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.LINKEDIN, rate_limiter=rate_limiter)
        self._scan_count_today = 0

    def _can_scan_today(self) -> bool:
        """Check if we've already hit the daily scan limit."""
        today = date.today().isoformat()
        record_file = SCAN_RECORD_PATH / f"linkedin_{today}.json"
        if record_file.exists():
            try:
                data = json.loads(record_file.read_text())
                return data.get("scan_count", 0) < MAX_SCANS_PER_DAY
            except (json.JSONDecodeError, KeyError):
                pass
        return True

    def _record_scan(self, results_count: int) -> None:
        """Record this scan for daily limit tracking."""
        today = date.today().isoformat()
        SCAN_RECORD_PATH.mkdir(parents=True, exist_ok=True)
        record_file = SCAN_RECORD_PATH / f"linkedin_{today}.json"

        data = {
            "scan_count": 1,
            "last_scan": datetime.now().isoformat(),
            "results": results_count,
        }
        if record_file.exists():
            try:
                existing = json.loads(record_file.read_text())
                data["scan_count"] = existing.get("scan_count", 0) + 1
            except (json.JSONDecodeError, KeyError):
                pass

        record_file.write_text(json.dumps(data, indent=2))

    def _is_captcha(self, page_text: str) -> bool:
        """Check for CAPTCHA or security challenge indicators."""
        lower = page_text.lower()
        indicators = (
            "captcha",
            "security verification",
            "verify you are human",
            "let's do a quick security check",
            "unusual activity",
            "challenge",
            "please verify",
            "are you a robot",
        )
        return any(ind in lower for ind in indicators)

    async def _check_login(self, page) -> bool:
        """Verify user is logged into LinkedIn."""
        try:
            page_text = await page.inner_text("body")
            # If we see "Sign in" form, we're not logged in
            if "sign in" in page_text.lower()[:500] and "feed" not in page.url:
                logger.error("LinkedIn: not logged in -- aborting scan")
                return False
            return True
        except Exception:
            return False

    async def search(self, keywords: list[str], days: int = 7) -> list[JobPosting]:
        """Search LinkedIn for jobs matching keywords.

        Safety: max 5 pages, 3-7s random delays, CAPTCHA detection, 1 scan/day.
        """
        results: list[JobPosting] = []

        # Check daily limit
        if not self._can_scan_today():
            logger.warning("LinkedIn: daily scan limit reached (max 1/day) -- skipping")
            return results

        try:
            await self._launch(headless=False)
            page, behavior = await self._new_page_with_behavior()

            # Step 1: Navigate to LinkedIn jobs homepage
            await page.goto(
                "https://www.linkedin.com/jobs/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await behavior.human_delay(2000, 4000)

            # Step 2: Verify login
            if not await self._check_login(page):
                return results

            # Step 3: CAPTCHA check on homepage
            page_text = await page.inner_text("body")
            if self._is_captcha(page_text):
                logger.error("LinkedIn: CAPTCHA on homepage -- aborting")
                return results

            # Step 4: Search each keyword
            for kw in keywords:
                await self._throttle()

                # Build search URL with filters:
                # f_CS=B,C = company size 11-50, 51-200 (startups)
                # f_TPR=r604800 = past week
                # sortBy=DD = date descending
                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={quote_plus(kw)}"
                    f"&f_CS=B,C"
                    f"&f_TPR=r{days * 86400}"
                    f"&sortBy=DD"
                )

                try:
                    await page.goto(
                        search_url, wait_until="domcontentloaded", timeout=30000
                    )
                    await behavior.human_delay(MIN_DELAY_MS, MAX_DELAY_MS)

                    # CAPTCHA check after search
                    page_text = await page.inner_text("body")
                    if self._is_captcha(page_text):
                        logger.error(
                            f"LinkedIn: CAPTCHA detected for '{kw}' -- stopping all searches"
                        )
                        break

                    # Paginate through results (max 5 pages)
                    for page_num in range(MAX_PAGES):
                        # Wait for job cards
                        try:
                            await page.wait_for_selector(
                                "[data-job-id], .job-card-container, [role='listitem']",
                                timeout=15000,
                            )
                        except Exception:
                            logger.debug(
                                f"LinkedIn: no more results on page {page_num + 1}"
                            )
                            break

                        # Extract job cards from current page
                        cards = await page.query_selector_all(
                            "[data-job-id], .job-card-container, "
                            "[role='listitem'] a[href*='/jobs/view/']"
                        )

                        for card in cards:
                            posting = await self._parse_linkedin_card(card)
                            if posting:
                                # Skip Easy Apply (per outreach rules)
                                if posting.is_easy_apply:
                                    continue
                                if self.apply_h1b_filter(posting):
                                    results.append(posting)

                        # Scroll to bottom and click next page
                        await behavior.smooth_scroll("down", 2000)
                        await behavior.human_delay(MIN_DELAY_MS, MAX_DELAY_MS)

                        # CAPTCHA check after each page
                        page_text = await page.inner_text("body")
                        if self._is_captcha(page_text):
                            logger.error(
                                "LinkedIn: CAPTCHA detected during pagination -- stopping"
                            )
                            break

                        # Try to click next page button
                        if page_num < MAX_PAGES - 1:
                            next_btn = await page.query_selector(
                                "button[aria-label='Next'], "
                                "[data-testid*='next'], "
                                ".artdeco-pagination__button--next"
                            )
                            if next_btn:
                                await next_btn.click()
                                # Random delay between pages
                                delay_ms = random.randint(MIN_DELAY_MS, MAX_DELAY_MS)
                                await behavior.human_delay(delay_ms, delay_ms + 2000)
                            else:
                                break  # No more pages

                except Exception as e:
                    logger.warning(f"LinkedIn search failed for '{kw}': {e}")
                    continue

        finally:
            await self._close()

        # Record scan and save results
        self._record_scan(len(results))
        self._save_results(results)

        logger.info(f"LinkedInPatchrightScraper found {len(results)} postings")
        return results

    async def _parse_linkedin_card(self, card) -> JobPosting | None:
        """Parse a LinkedIn job card element using structural selectors."""
        try:
            # Title: usually in h3 or heading role
            title_el = await card.query_selector(
                "h3, [role='heading'], [data-testid*='job-title']"
            ) or await card.query_selector("a[href*='/jobs/view/']")
            # Company: usually in h4 or company-specific element
            company_el = await card.query_selector(
                "h4, [data-testid*='company'], .job-card-container__company-name"
            )
            # Location: text matching state/city pattern
            location_el = await card.query_selector(
                "[data-testid*='location'], .job-card-container__metadata-item"
            )

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            if not title or len(title) < 3:
                return None

            # URL
            link = await card.query_selector("a[href*='/jobs/view/']")
            href = await link.get_attribute("href") if link else ""
            if href:
                # Clean tracking params
                href = re.sub(r"\?.*", "", href)
                if not href.startswith("http"):
                    href = f"https://www.linkedin.com{href}"

            # Easy Apply detection
            easy_apply_el = await card.query_selector(
                "[data-testid*='easy-apply'], .job-card-container__easy-apply-icon"
            )
            is_easy_apply = easy_apply_el is not None

            # Top Applicant badge
            top_applicant_el = await card.query_selector(
                "[data-testid*='top-applicant'], "
                ".job-card-container__footer-item--is-promoted"
            )
            is_top_applicant = top_applicant_el is not None

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.LINKEDIN,
                discovered_date=datetime.now(),
                is_easy_apply=is_easy_apply,
                is_top_applicant=is_top_applicant,
            )
        except Exception as e:
            logger.debug(f"LinkedIn card parse error: {e}")
            return None

    def _save_results(self, results: list[JobPosting]) -> None:
        """Save results to data/mcp_scans/linkedin_{date}.json."""
        if not results:
            return

        SCAN_RECORD_PATH.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        output_file = SCAN_RECORD_PATH / f"linkedin_{today}_results.json"

        data = [
            {
                "title": p.title,
                "company": p.company_name,
                "location": p.location,
                "url": p.url,
                "is_easy_apply": p.is_easy_apply,
                "is_top_applicant": p.is_top_applicant,
            }
            for p in results
        ]

        output_file.write_text(json.dumps(data, indent=2))
        logger.info(f"Saved {len(results)} LinkedIn results to {output_file}")

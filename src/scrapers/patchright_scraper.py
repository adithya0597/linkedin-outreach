"""Patchright-based stealth scrapers for bot-protected portals.

Patchright is a drop-in Playwright replacement that patches the CDP
Runtime.enable leak — the primary detection signal for Cloudflare
and DataDome. Combined with BehavioralLayer for human-like interaction.

Tier C — Medium Risk: Used only for portals with moderate anti-bot
protection (Jobright 4/10, TrueUp 4/10).
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from urllib.parse import quote_plus

from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.behavioral_mimicry import BehavioralLayer
from src.scrapers.rate_limiter import RateLimiter


class PatchrightScraper(BaseScraper):
    """Base class for stealth browser scrapers using Patchright.

    Patchright patches CDP Runtime.enable leak that Cloudflare/DataDome detect.
    Uses BehavioralLayer for human-like mouse/scroll/typing patterns.
    Uses structural selectors (data-testid, ARIA roles) not CSS classnames.
    """

    def __init__(self, portal: SourcePortal, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(portal, rate_limiter=rate_limiter)
        self._browser = None
        self._context = None
        self._pw = None

    async def _launch(self, headless: bool = False):
        """Launch Patchright browser with stealth settings.

        Falls back to regular Playwright if Patchright is not installed.
        """
        try:
            from patchright.async_api import async_playwright
            logger.debug("Using Patchright (stealth mode)")
        except ImportError:
            logger.warning("Patchright not installed, falling back to Playwright (less stealth)")
            from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/Chicago",
        )
        return self._context

    async def _close(self):
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    async def _new_page_with_behavior(self):
        """Create a new page with BehavioralLayer attached."""
        if not self._context:
            await self._launch()
        page = await self._context.new_page()
        behavior = BehavioralLayer(page)
        return page, behavior


class JobrightPatchrightScraper(PatchrightScraper):
    """Jobright AI scraper using Patchright stealth browser.

    Tier C — Medium Risk (Jobright difficulty: 4/10).
    Uses data-testid attributes for reliable element targeting.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.JOBRIGHT, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []

        try:
            ctx = await self._launch()
            page, behavior = await self._new_page_with_behavior()

            for kw in keywords:
                await self._throttle()
                url = f"https://jobright.ai/jobs?searchKeyword={quote_plus(kw)}&location=United+States"

                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    await behavior.human_delay(2000, 4000)

                    # Wait for job cards to load (use structural selectors)
                    try:
                        await page.wait_for_selector(
                            "[data-testid*='job'], [role='listitem'], .job-card, article",
                            timeout=15000,
                        )
                    except Exception:
                        logger.warning(f"Jobright: no job cards found for '{kw}'")
                        continue

                    # Scroll to load more results
                    await behavior.smooth_scroll("down", 800)
                    await behavior.human_delay(1000, 2000)

                    # Extract job cards
                    cards = await page.query_selector_all(
                        "[data-testid*='job'], [role='listitem'] a[href*='/jobs/'], article a[href*='/jobs/']"
                    )

                    for card in cards:
                        posting = await self._parse_card(card, page)
                        if posting and self.apply_h1b_filter(posting):
                            results.append(posting)

                except Exception as e:
                    logger.warning(f"Jobright search failed for '{kw}': {e}")
                    # Check for CAPTCHA/challenge
                    page_text = await page.inner_text("body")
                    if any(w in page_text.lower() for w in ("captcha", "verify", "challenge", "blocked")):
                        logger.error("Jobright: CAPTCHA/challenge detected — stopping scan")
                        break
                    continue

        finally:
            await self._close()

        logger.info(f"JobrightPatchrightScraper found {len(results)} postings")
        return results

    async def _parse_card(self, card, page) -> JobPosting | None:
        """Parse a Jobright job card element."""
        try:
            # Try structural selectors first
            title_el = (
                await card.query_selector("[data-testid*='title'], h3, h2")
                or await card.query_selector("a[href*='/jobs/']")
            )
            company_el = await card.query_selector(
                "[data-testid*='company'], [class*='company'], span:nth-child(2)"
            )
            location_el = await card.query_selector(
                "[data-testid*='location'], [class*='location']"
            )

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            if not title:
                return None

            # Get URL
            link = await card.query_selector("a[href*='/jobs/']")
            href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://jobright.ai{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.JOBRIGHT,
                discovered_date=datetime.now(),
            )
        except Exception:
            return None


class TrueUpPatchrightScraper(PatchrightScraper):
    """TrueUp scraper using Patchright stealth browser.

    Tier C — Medium Risk (TrueUp difficulty: 4/10).
    Previously blocked by 403 from cloud IPs. Local browser bypasses this.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.TRUEUP, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []

        try:
            ctx = await self._launch()
            page, behavior = await self._new_page_with_behavior()

            for kw in keywords:
                await self._throttle()
                url = f"https://www.trueup.io/jobs?title={quote_plus(kw)}&location=United+States"

                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    await behavior.human_delay(2000, 4000)

                    # Wait for content
                    try:
                        await page.wait_for_selector(
                            "[data-testid*='job'], a[href*='/job/'], tr[class*='job'], .job-row",
                            timeout=15000,
                        )
                    except Exception:
                        logger.warning(f"TrueUp: no job cards found for '{kw}'")
                        # Check for block page
                        page_text = await page.inner_text("body")
                        if "403" in page_text or "blocked" in page_text.lower():
                            logger.error("TrueUp: blocked (403) — stopping scan")
                            break
                        continue

                    await behavior.smooth_scroll("down", 600)
                    await behavior.human_delay(1000, 2000)

                    # Extract job rows
                    cards = await page.query_selector_all(
                        "a[href*='/job/'], tr[class*='job'], [data-testid*='job']"
                    )

                    for card in cards:
                        posting = await self._parse_card(card)
                        if posting and self.apply_h1b_filter(posting):
                            results.append(posting)

                except Exception as e:
                    logger.warning(f"TrueUp search failed for '{kw}': {e}")
                    continue

        finally:
            await self._close()

        logger.info(f"TrueUpPatchrightScraper found {len(results)} postings")
        return results

    async def _parse_card(self, card) -> JobPosting | None:
        """Parse a TrueUp job card/row element."""
        try:
            title_el = await card.query_selector("h3, h2, [class*='title'], td:first-child")
            company_el = await card.query_selector("[class*='company'], td:nth-child(2)")
            location_el = await card.query_selector("[class*='location'], td:nth-child(3)")
            salary_el = await card.query_selector("[class*='salary'], [class*='compensation']")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""
            salary = await salary_el.inner_text() if salary_el else ""

            if not title:
                # Try getting text from the card itself
                title = await card.inner_text()
                if not title or len(title) > 200:
                    return None

            # Get URL
            href = await card.get_attribute("href")
            if not href:
                link = await card.query_selector("a[href*='/job/']")
                href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://www.trueup.io{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href or "",
                salary_range=salary.strip(),
                source_portal=SourcePortal.TRUEUP,
                discovered_date=datetime.now(),
            )
        except Exception:
            return None


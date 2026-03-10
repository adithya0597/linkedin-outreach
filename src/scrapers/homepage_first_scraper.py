"""Homepage-first Playwright scrapers for 403-blocked portals.

Strategy: Navigate to portal homepage first to establish real browser session
(cookies, referrer chain, TLS fingerprint), then navigate to search URL.
This bypasses bot detection that blocks direct URL hits.

Uses PatchrightScraper base for Chrome profile + BehavioralLayer.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus

from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.behavioral_mimicry import BehavioralLayer
from src.scrapers.patchright_scraper import PatchrightScraper
from src.scrapers.rate_limiter import RateLimiter


class HomepageFirstScraper(PatchrightScraper):
    """Base class for scrapers that establish session via homepage visit first.

    Subclasses must set:
        HOMEPAGE_URL: str -- portal homepage URL
        SEARCH_URL_TEMPLATE: str -- search URL with {kw} placeholder
        JOB_CARD_SELECTOR: str -- CSS selector for job cards
    """

    HOMEPAGE_URL: str = ""
    SEARCH_URL_TEMPLATE: str = ""
    JOB_CARD_SELECTOR: str = ""

    def __init__(self, portal: SourcePortal, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(portal, rate_limiter=rate_limiter)

    async def _establish_session(self, page, behavior: BehavioralLayer) -> bool:
        """Navigate to homepage to establish browser session.

        Returns True if session established successfully, False if blocked.
        """
        try:
            await page.goto(self.HOMEPAGE_URL, wait_until="domcontentloaded", timeout=30000)
            await behavior.human_delay(2000, 4000)

            # Check for CAPTCHA/block indicators
            page_text = await page.inner_text("body")
            if self._is_blocked(page_text):
                logger.error(f"{self.name}: blocked on homepage -- stopping")
                return False

            return True
        except Exception as e:
            logger.warning(f"{self.name}: failed to load homepage: {e}")
            return False

    def _is_blocked(self, page_text: str) -> bool:
        """Check if page shows CAPTCHA or block indicators."""
        lower = page_text.lower()
        blocked_indicators = (
            "captcha",
            "verify you are human",
            "access denied",
            "403 forbidden",
            "blocked",
            "please complete the security check",
            "challenge",
            "just a moment",
            "checking your browser",
        )
        return any(indicator in lower for indicator in blocked_indicators)

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        """Homepage-first search flow: homepage -> delay -> search -> extract."""
        results: list[JobPosting] = []

        try:
            await self._launch()
            page, behavior = await self._new_page_with_behavior()

            # Step 1: Establish session via homepage
            if not await self._establish_session(page, behavior):
                return results

            # Step 2: Search for each keyword
            for kw in keywords:
                await self._throttle()
                search_url = self.SEARCH_URL_TEMPLATE.format(kw=quote_plus(kw))

                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    await behavior.human_delay(2000, 4000)

                    # Check for block on search page
                    page_text = await page.inner_text("body")
                    if self._is_blocked(page_text):
                        logger.error(f"{self.name}: blocked on search page for '{kw}' -- stopping")
                        break

                    # Wait for job cards
                    try:
                        await page.wait_for_selector(self.JOB_CARD_SELECTOR, timeout=15000)
                    except Exception:
                        logger.warning(f"{self.name}: no job cards found for '{kw}'")
                        continue

                    # Scroll to load more results
                    await behavior.smooth_scroll("down", 800)
                    await behavior.human_delay(1000, 2000)

                    # Extract job cards
                    cards = await page.query_selector_all(self.JOB_CARD_SELECTOR)
                    for card in cards:
                        posting = await self._parse_card(card, page)
                        if posting and self.apply_h1b_filter(posting):
                            results.append(posting)

                except Exception as e:
                    logger.warning(f"{self.name}: search failed for '{kw}': {e}")
                    # Check for CAPTCHA on error
                    try:
                        page_text = await page.inner_text("body")
                        if self._is_blocked(page_text):
                            logger.error(f"{self.name}: CAPTCHA detected -- stopping scan")
                            break
                    except Exception:
                        pass
                    continue

        finally:
            await self._close()

        logger.info(f"{type(self).__name__} found {len(results)} postings")
        return results

    async def _parse_card(self, card, page) -> JobPosting | None:
        """Parse a job card element. Subclasses should override."""
        raise NotImplementedError("Subclasses must implement _parse_card")


# ---------------------------------------------------------------------------
# Concrete portal scrapers
# ---------------------------------------------------------------------------


class WellfoundHomepageFirstScraper(HomepageFirstScraper):
    """Wellfound scraper using homepage-first strategy."""

    HOMEPAGE_URL = "https://wellfound.com/"
    SEARCH_URL_TEMPLATE = "https://wellfound.com/role/l/software-engineer/{kw}"
    JOB_CARD_SELECTOR = (
        "[data-testid*='startup'], .styles_component__startup, "
        "[role='listitem'], a[href*='/jobs/']"
    )

    def __init__(self, rate_limiter=None):
        super().__init__(SourcePortal.WELLFOUND, rate_limiter=rate_limiter)

    async def _parse_card(self, card, page):
        try:
            title_el = await card.query_selector(
                "h3, h2, [data-testid*='title'], a[href*='/jobs/']"
            )
            company_el = await card.query_selector(
                "a[href*='/companies/'], [data-testid*='company'], h4"
            )
            location_el = await card.query_selector(
                "[data-testid*='location'], span:has-text('Remote'), span:has-text(',')"
            )

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            if not title or len(title) < 3:
                return None

            link = await card.query_selector("a[href*='/jobs/']")
            href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://wellfound.com{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.WELLFOUND,
                discovered_date=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"Wellfound card parse error: {e}")
            return None


class StartupJobsHomepageFirstScraper(HomepageFirstScraper):
    """startup.jobs scraper using homepage-first strategy."""

    HOMEPAGE_URL = "https://startup.jobs/"
    SEARCH_URL_TEMPLATE = "https://startup.jobs/?q={kw}"
    JOB_CARD_SELECTOR = ".job-card, article, [data-testid*='job'], a[href*='/job/']"

    def __init__(self, rate_limiter=None):
        super().__init__(SourcePortal.STARTUP_JOBS, rate_limiter=rate_limiter)

    async def _parse_card(self, card, page):
        try:
            title_el = await card.query_selector(
                "h3, h2, .job-title, [data-testid*='title']"
            )
            company_el = await card.query_selector(
                ".company-name, [data-testid*='company'], h4"
            )
            location_el = await card.query_selector(
                ".location, [data-testid*='location']"
            )

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            if not title:
                return None

            link = await card.query_selector("a[href]")
            href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://startup.jobs{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.STARTUP_JOBS,
                discovered_date=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"startup.jobs card parse error: {e}")
            return None


class HiringCafeHomepageFirstScraper(HomepageFirstScraper):
    """Hiring Cafe scraper using homepage-first strategy."""

    HOMEPAGE_URL = "https://hiring.cafe/"
    SEARCH_URL_TEMPLATE = "https://hiring.cafe/jobs?search={kw}&country=US"
    JOB_CARD_SELECTOR = (
        "[data-testid*='job'], .job-listing, article, a[href*='/viewjob/']"
    )

    def __init__(self, rate_limiter=None):
        super().__init__(SourcePortal.HIRING_CAFE, rate_limiter=rate_limiter)

    async def _parse_card(self, card, page):
        try:
            title_el = await card.query_selector("h3, h2, [data-testid*='title']")
            company_el = await card.query_selector(
                "[data-testid*='company'], h4, span"
            )
            location_el = await card.query_selector("[data-testid*='location']")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            if not title:
                return None

            link = await card.query_selector(
                "a[href*='/viewjob/'], a[href*='/job']"
            )
            href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://hiring.cafe{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.HIRING_CAFE,
                discovered_date=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"Hiring Cafe card parse error: {e}")
            return None


class YCHomepageFirstScraper(HomepageFirstScraper):
    """Work at a Startup (YC) scraper using homepage-first strategy."""

    HOMEPAGE_URL = "https://www.workatastartup.com/"
    SEARCH_URL_TEMPLATE = "https://www.workatastartup.com/companies?query={kw}"
    JOB_CARD_SELECTOR = (
        "[data-testid*='company'], [role='listitem'], "
        "a[href*='/companies/'], .company-card"
    )

    def __init__(self, rate_limiter=None):
        super().__init__(SourcePortal.YC, rate_limiter=rate_limiter)

    async def _parse_card(self, card, page):
        try:
            title_el = await card.query_selector(
                "h3, h2, [data-testid*='title'], [role='heading']"
            )
            company_el = await card.query_selector(
                "a[href*='/companies/'], [data-testid*='company'], h4"
            )
            location_el = await card.query_selector(
                "[data-testid*='location'], span"
            )

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            # YC cards often show company name as main heading
            if not title and company:
                title = f"Engineering at {company}"
            if not title:
                return None

            link = await card.query_selector("a[href*='/companies/']")
            href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://www.workatastartup.com{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.YC,
                discovered_date=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"YC card parse error: {e}")
            return None


class WTTJHomepageFirstScraper(HomepageFirstScraper):
    """Welcome to the Jungle scraper using homepage-first strategy."""

    HOMEPAGE_URL = "https://www.welcometothejungle.com/"
    SEARCH_URL_TEMPLATE = (
        "https://www.welcometothejungle.com/en/jobs?query={kw}"
        "&region=North%20America"
    )
    JOB_CARD_SELECTOR = (
        "[data-testid*='job'], article, a[href*='/jobs/'], [role='listitem']"
    )

    def __init__(self, rate_limiter=None):
        super().__init__(SourcePortal.WTTJ, rate_limiter=rate_limiter)

    async def _parse_card(self, card, page):
        try:
            title_el = await card.query_selector(
                "h3, h2, [data-testid*='title'], [role='heading']"
            )
            company_el = await card.query_selector(
                "[data-testid*='company'], h4, span"
            )
            location_el = await card.query_selector("[data-testid*='location']")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""

            if not title:
                return None

            link = await card.query_selector("a[href*='/jobs/']")
            href = await link.get_attribute("href") if link else ""
            if href and not href.startswith("http"):
                href = f"https://www.welcometothejungle.com{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=href,
                source_portal=SourcePortal.WTTJ,
                discovered_date=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"WTTJ card parse error: {e}")
            return None

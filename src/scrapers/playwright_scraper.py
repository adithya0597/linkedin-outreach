from __future__ import annotations

import asyncio
import random
from urllib.parse import quote_plus

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.rate_limiter import RateLimiter

CHROME_USER_DATA_DIR = "/Users/adithya/Library/Application Support/Google/Chrome"

# Class-level lock to prevent concurrent Chrome profile access
_chrome_profile_lock = asyncio.Lock()


class PlaywrightScraper(BaseScraper):
    """Base class for scrapers that use Playwright with the user's Chrome profile."""

    def __init__(self, portal: SourcePortal, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(portal, rate_limiter=rate_limiter)
        self._browser = None
        self._context = None

    async def _launch(self):
        """Launch Playwright with the user's Chrome profile."""
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        self._context = await pw.chromium.launch_persistent_context(
            user_data_dir=CHROME_USER_DATA_DIR,
            channel="chrome",
            headless=False,
        )
        return self._context

    async def _close(self):
        if self._context:
            await self._context.close()
            self._context = None


class JobrightScraper(PlaywrightScraper):
    """Jobright AI scraper (Tier 2 -- H1B cross-check required)."""

    MAX_PAGES = 3

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.JOBRIGHT, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        results: list[JobPosting] = []
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                for kw in keywords:
                    await self._throttle()
                    url = f"https://jobright.ai/jobs?q={quote_plus(kw)}"
                    await page.goto(url)
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(2000)

                    for page_num in range(self.MAX_PAGES):
                        cards = await page.query_selector_all(".job-card")
                        for card in cards:
                            posting = await self._parse_jobright_card(card)
                            if posting and self.apply_h1b_filter(posting):
                                results.append(posting)

                        next_btn = await page.query_selector("button.next-page")
                        if next_btn and page_num < self.MAX_PAGES - 1:
                            await self._throttle()
                            await next_btn.click()
                            await page.wait_for_load_state("networkidle")
                            await page.wait_for_timeout(2000)
                        else:
                            break
            finally:
                await self._close()
        return results

    async def _parse_jobright_card(self, card) -> JobPosting | None:
        try:
            title_el = await card.query_selector(".job-title")
            company_el = await card.query_selector(".company-name")
            location_el = await card.query_selector(".job-location")
            link_el = await card.query_selector("a[href]")
            salary_el = await card.query_selector(".salary")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""
            href = await link_el.get_attribute("href") if link_el else ""
            salary = await salary_el.inner_text() if salary_el else ""

            if not title:
                return None

            job_url = href if href.startswith("http") else f"https://jobright.ai{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=job_url,
                salary_range=salary.strip(),
                source_portal=SourcePortal.JOBRIGHT,
            )
        except Exception:
            return None

    async def get_posting_details(self, url: str) -> JobPosting:
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await self._throttle()
                await page.goto(url)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)

                title_el = await page.query_selector("h1.job-title, h1")
                company_el = await page.query_selector(".company-name")
                desc_el = await page.query_selector(".job-description")
                location_el = await page.query_selector(".job-location")

                title = await title_el.inner_text() if title_el else ""
                company = await company_el.inner_text() if company_el else ""
                description = await desc_el.inner_text() if desc_el else ""
                location = await location_el.inner_text() if location_el else ""

                requirements = self._extract_list_section(description, "requirements")
                tech_stack = self._extract_list_section(description, "tech stack")

                return JobPosting(
                    title=title.strip(),
                    company_name=company.strip(),
                    url=url,
                    description=description.strip(),
                    location=location.strip(),
                    requirements=requirements,
                    tech_stack=tech_stack,
                    source_portal=SourcePortal.JOBRIGHT,
                )
            finally:
                await self._close()

    @staticmethod
    def _extract_list_section(text: str, section_name: str) -> list[str]:
        """Extract bullet items from a named section in description text."""
        lines = text.split("\n")
        in_section = False
        items: list[str] = []
        for line in lines:
            stripped = line.strip().lower()
            if section_name.lower() in stripped and (":" in stripped or stripped.endswith(section_name.lower())):
                in_section = True
                continue
            if in_section:
                if line.strip().startswith(("-", "•", "*")):
                    items.append(line.strip().lstrip("-•* ").strip())
                elif line.strip() == "":
                    if items:
                        break
                else:
                    break
        return items


class HiringCafeScraper(PlaywrightScraper):
    """Hiring Cafe scraper (Tier 3 -- startup portal)."""

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.HIRING_CAFE, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        results: list[JobPosting] = []
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                for kw in keywords:
                    await self._throttle()
                    url = f"https://hiring.cafe/jobs?q={quote_plus(kw)}"
                    await page.goto(url)
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(2000)

                    cards = await page.query_selector_all(".job-card")
                    for card in cards:
                        posting = await self._parse_hiring_cafe_card(card)
                        if posting:
                            results.append(posting)
            finally:
                await self._close()
        return results

    async def _parse_hiring_cafe_card(self, card) -> JobPosting | None:
        try:
            title_el = await card.query_selector(".job-title")
            company_el = await card.query_selector(".company-name")
            location_el = await card.query_selector(".job-location")
            link_el = await card.query_selector("a[href]")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""
            href = await link_el.get_attribute("href") if link_el else ""

            if not title:
                return None

            job_url = href if href.startswith("http") else f"https://hiring.cafe{href}"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=job_url,
                source_portal=SourcePortal.HIRING_CAFE,
            )
        except Exception:
            return None

    async def get_posting_details(self, url: str) -> JobPosting:
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await self._throttle()
                await page.goto(url)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)

                title_el = await page.query_selector("h1.job-title, h1")
                company_el = await page.query_selector(".company-name")
                desc_el = await page.query_selector(".job-description")
                location_el = await page.query_selector(".job-location")

                title = await title_el.inner_text() if title_el else ""
                company = await company_el.inner_text() if company_el else ""
                description = await desc_el.inner_text() if desc_el else ""
                location = await location_el.inner_text() if location_el else ""

                return JobPosting(
                    title=title.strip(),
                    company_name=company.strip(),
                    url=url,
                    description=description.strip(),
                    location=location.strip(),
                    source_portal=SourcePortal.HIRING_CAFE,
                )
            finally:
                await self._close()


class WellfoundScraper(PlaywrightScraper):
    """Wellfound (AngelList) scraper (Tier 3 -- startup portal)."""

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.WELLFOUND, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        results: list[JobPosting] = []
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                for kw in keywords:
                    await self._throttle()
                    url = f"https://wellfound.com/role/ai-engineer?q={quote_plus(kw)}"
                    await page.goto(url)
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(2000)

                    cards = await page.query_selector_all(".job-card")
                    for card in cards:
                        posting = await self._parse_wellfound_card(card)
                        if posting:
                            results.append(posting)
            finally:
                await self._close()
        return results

    async def _parse_wellfound_card(self, card) -> JobPosting | None:
        try:
            title_el = await card.query_selector(".job-title")
            company_el = await card.query_selector(".company-name")
            location_el = await card.query_selector(".job-location")
            link_el = await card.query_selector("a[href]")
            salary_el = await card.query_selector(".salary")
            funding_el = await card.query_selector(".funding")
            size_el = await card.query_selector(".company-size")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""
            href = await link_el.get_attribute("href") if link_el else ""
            salary = await salary_el.inner_text() if salary_el else ""

            if not title:
                return None

            job_url = href if href.startswith("http") else f"https://wellfound.com{href}"

            # Determine work model from location text
            work_model = ""
            loc_lower = location.lower()
            if "remote" in loc_lower:
                work_model = "remote"
            elif "hybrid" in loc_lower:
                work_model = "hybrid"
            elif location:
                work_model = "onsite"

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=job_url,
                salary_range=salary.strip(),
                work_model=work_model,
                source_portal=SourcePortal.WELLFOUND,
            )
        except Exception:
            return None

    async def get_posting_details(self, url: str) -> JobPosting:
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await self._throttle()
                await page.goto(url)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)

                title_el = await page.query_selector("h1.job-title, h1")
                company_el = await page.query_selector(".company-name")
                desc_el = await page.query_selector(".job-description")
                location_el = await page.query_selector(".job-location")
                salary_el = await page.query_selector(".salary")

                title = await title_el.inner_text() if title_el else ""
                company = await company_el.inner_text() if company_el else ""
                description = await desc_el.inner_text() if desc_el else ""
                location = await location_el.inner_text() if location_el else ""
                salary = await salary_el.inner_text() if salary_el else ""

                return JobPosting(
                    title=title.strip(),
                    company_name=company.strip(),
                    url=url,
                    description=description.strip(),
                    location=location.strip(),
                    salary_range=salary.strip(),
                    source_portal=SourcePortal.WELLFOUND,
                )
            finally:
                await self._close()


class LinkedInScraper(PlaywrightScraper):
    """LinkedIn job scraper (Tier 1 -- requires Premium login)."""

    MAX_PAGES = 5

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.LINKEDIN, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str]) -> list[JobPosting]:
        results: list[JobPosting] = []
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                for kw in keywords:
                    await self._throttle()
                    url = (
                        f"https://www.linkedin.com/jobs/search/"
                        f"?keywords={quote_plus(kw)}&f_TPR=r604800&sortBy=DD"
                    )
                    await page.goto(url)
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(random.randint(2000, 5000))

                    for page_num in range(self.MAX_PAGES):
                        cards = await page.query_selector_all(".job-card-container")
                        for card in cards:
                            posting = await self._parse_linkedin_card(card)
                            if posting is None:
                                continue
                            # Skip Easy Apply per outreach rules
                            if posting.is_easy_apply:
                                continue
                            if self.apply_h1b_filter(posting):
                                results.append(posting)

                        next_btn = await page.query_selector("button[aria-label='Next']")
                        if next_btn and page_num < self.MAX_PAGES - 1:
                            await self._throttle()
                            await next_btn.click()
                            await page.wait_for_load_state("networkidle")
                            await page.wait_for_timeout(random.randint(2000, 5000))
                        else:
                            break
            finally:
                await self._close()
        return results

    async def _parse_linkedin_card(self, card) -> JobPosting | None:
        try:
            title_el = await card.query_selector(".job-title")
            company_el = await card.query_selector(".company-name")
            location_el = await card.query_selector(".job-location")
            link_el = await card.query_selector("a[href]")

            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            location = await location_el.inner_text() if location_el else ""
            href = await link_el.get_attribute("href") if link_el else ""

            if not title:
                return None

            job_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"

            # Check for Easy Apply badge
            easy_apply_el = await card.query_selector(".easy-apply-badge")
            is_easy_apply = easy_apply_el is not None

            # Check for Top Applicant badge
            top_applicant_el = await card.query_selector(".top-applicant-badge")
            is_top_applicant = top_applicant_el is not None

            return JobPosting(
                title=title.strip(),
                company_name=company.strip(),
                location=location.strip(),
                url=job_url,
                source_portal=SourcePortal.LINKEDIN,
                is_easy_apply=is_easy_apply,
                is_top_applicant=is_top_applicant,
            )
        except Exception:
            return None

    async def get_posting_details(self, url: str) -> JobPosting:
        async with _chrome_profile_lock:
            ctx = await self._launch()
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await self._throttle()
                await page.goto(url)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(random.randint(2000, 5000))

                title_el = await page.query_selector("h1.job-title, h1")
                company_el = await page.query_selector(".company-name")
                desc_el = await page.query_selector(".job-description, .description")
                location_el = await page.query_selector(".job-location")

                title = await title_el.inner_text() if title_el else ""
                company = await company_el.inner_text() if company_el else ""
                description = await desc_el.inner_text() if desc_el else ""
                location = await location_el.inner_text() if location_el else ""

                # Check for H1B mentions in description
                h1b_mentioned = False
                h1b_text = ""
                desc_lower = description.lower()
                if "h1b" in desc_lower or "h-1b" in desc_lower or "visa sponsor" in desc_lower:
                    h1b_mentioned = True
                    for line in description.split("\n"):
                        if any(term in line.lower() for term in ("h1b", "h-1b", "visa sponsor")):
                            h1b_text = line.strip()
                            break

                return JobPosting(
                    title=title.strip(),
                    company_name=company.strip(),
                    url=url,
                    description=description.strip(),
                    location=location.strip(),
                    source_portal=SourcePortal.LINKEDIN,
                    h1b_mentioned=h1b_mentioned,
                    h1b_text=h1b_text,
                )
            finally:
                await self._close()

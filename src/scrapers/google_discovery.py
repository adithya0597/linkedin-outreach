"""Google Search-based ATS company discovery using Patchright.

Uses stealth Chrome browser to search Google with site: dorks,
extract ATS slugs from result URLs, and discover new companies
using Ashby/Greenhouse/Lever.
"""

from __future__ import annotations

import asyncio
import random
import re
import sys
from dataclasses import dataclass, field

from loguru import logger

from src.scrapers.patchright_scraper import PatchrightScraper
from src.config.enums import SourcePortal
from src.scrapers.rate_limiter import RateLimiter


# Regex patterns to extract company slugs from ATS URLs
_SLUG_PATTERNS: dict[str, re.Pattern] = {
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([^/?\s#]+)"),
    "greenhouse": re.compile(
        r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?.*?for=)?([^/&?\s#]+)"
    ),
    "lever": re.compile(r"jobs\.lever\.co/([^/?\s#]+)"),
}

# Google search templates — one per ATS platform
# {kw} is inserted raw (already formatted with quotes/operators by the keyword)
_SEARCH_QUERIES: dict[str, list[str]] = {
    "ashby": [
        "site:jobs.ashbyhq.com {kw}",
    ],
    "greenhouse": [
        "site:boards.greenhouse.io {kw}",
        "site:job-boards.greenhouse.io {kw}",
    ],
    "lever": [
        "site:jobs.lever.co {kw}",
    ],
}

# Tier 1 — Google discovery search queries (OR-consolidated)
#
# Uses Google OR operators to maximize slug discovery per query.
# Validated by 4 research agents: AI industry analyst, Google SEO expert,
# ATS formatting specialist, and AI startup founder/CTO.
#
# 8 queries × 2 platforms (Ashby + Greenhouse) = 16 Google requests per run.
# Well within CAPTCHA threshold (~40 queries/session).
DEFAULT_KEYWORDS = [
    # Q1: Core AI titles (highest volume — the #1 search)
    '("AI Engineer" OR "Applied AI Engineer" OR "LLM Engineer" OR "AI/ML Engineer")',
    # Q2: Software Engineer + AI qualifiers (Anthropic-style postings)
    '"Software Engineer" (AI OR LLM OR "AI Agents")',
    # Q3: Backend / Full Stack + AI
    '("Backend Engineer" OR "Full Stack Engineer" OR "Full-Stack Engineer") AI',
    # Q4: Startup-signal roles (every hit = early-stage company)
    '("Founding Engineer" OR "Founding AI Engineer") AI',
    # Q5: Platform & infrastructure (matches infra-focused AI roles)
    '("AI Platform Engineer" OR "AI Infrastructure Engineer" OR "ML Engineer" LLM)',
    # Q6: Deployment & customer-facing (800% growth in 2026)
    '("Forward Deployed Engineer" OR "Deployed Engineer" OR "AI Solutions Engineer")',
    # Q7: Agent-era + prestige titles (emerging 2026)
    '("Agent Engineer" OR "Member of Technical Staff" OR "Generative AI Engineer")',
    # Q8: Product / applied variants
    '("Product Engineer" AI OR "Applied ML Engineer" OR "Software Engineer" agentic)',
]

# Tier 2 — Post-fetch profile match keywords (precise, for scoring fit)
# Matched against job descriptions after fetching from ATS APIs.
# Each keyword maps to a skill/tool on the user's resume.
# Skills removed from Tier 1 search (LangChain, RAG) are captured here instead.
PROFILE_MATCH_KEYWORDS = [
    # AI/ML frameworks (resume core)
    "langchain", "langgraph", "dspy", "langfuse",
    # RAG & knowledge graph (key differentiators)
    "rag", "graph rag", "retrieval-augmented", "neo4j", "knowledge graph",
    # Vector/embedding infra
    "vector", "embedding", "milvus",
    # Agentic systems
    "agentic", "ai agent", "tool use", "agent framework",
    # Backend stack (resume match)
    "fastapi", "python", "java", "spring boot",
    # Infrastructure
    "aws", "docker", "kubernetes",
    # Code intelligence (unique differentiator)
    "compiler", "ast", "tree-sitter",
    # Observability & data
    "observability", "cdc", "data pipeline",
]


@dataclass
class DiscoveryResult:
    """Result of a discovery scan."""

    platform: str
    slugs_found: set[str] = field(default_factory=set)
    new_slugs: set[str] = field(default_factory=set)
    queries_run: int = 0
    errors: list[str] = field(default_factory=list)


class GoogleATSDiscovery(PatchrightScraper):
    """Discover new ATS company slugs via Google site: searches."""

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.MANUAL, rate_limiter=rate_limiter)

    async def search(self, keywords: list[str], days: int = 30) -> list:
        """Not used — discovery uses discover() instead."""
        return []

    async def discover(
        self,
        platforms: list[str] | None = None,
        keywords: list[str] | None = None,
        max_pages: int = 2,
        existing_slugs: dict[str, set[str]] | None = None,
    ) -> list[DiscoveryResult]:
        """Search Google for ATS job board URLs and extract company slugs.

        Args:
            platforms: Which ATS platforms to search ("ashby", "greenhouse", "lever").
                       Defaults to all three.
            keywords: Role keywords to search for. Defaults to DEFAULT_KEYWORDS.
            max_pages: Max Google result pages to scan per query (1 page = ~10 results).
            existing_slugs: Dict of platform -> set of already-known slugs for dedup.

        Returns:
            List of DiscoveryResult per platform.
        """
        platforms = platforms or ["ashby", "greenhouse"]
        keywords = keywords or DEFAULT_KEYWORDS
        existing_slugs = existing_slugs or {}
        results: list[DiscoveryResult] = []

        try:
            # headless=False required — Google blocks headless browsers aggressively
            await self._launch(headless=False)
            page, behavior = await self._new_page_with_behavior()

            # Warm up session — navigate to Google homepage first
            await page.goto("https://www.google.com", wait_until="domcontentloaded")
            await self._handle_consent(page)
            await asyncio.sleep(2)

            # If Google shows /sorry/ page on homepage, wait for manual CAPTCHA solve
            if "/sorry/" in page.url:
                await self._wait_for_captcha_solve(page)

            captcha_count = 0

            for platform in platforms:
                result = DiscoveryResult(platform=platform)
                query_templates = _SEARCH_QUERIES.get(platform, [])
                slug_pattern = _SLUG_PATTERNS.get(platform)

                if not slug_pattern:
                    result.errors.append(f"No slug pattern for platform: {platform}")
                    results.append(result)
                    continue

                for template in query_templates:
                    for kw in keywords:
                        # Early abort — if 2+ consecutive CAPTCHAs, IP is flagged
                        if captcha_count >= 2:
                            msg = "IP flagged by Google — aborting remaining queries. Wait 30-60 min."
                            logger.warning(msg)
                            result.errors.append(msg)
                            break

                        query = template.format(kw=kw)
                        try:
                            slugs = await self._search_google(
                                page, behavior, query, slug_pattern, max_pages
                            )
                            result.slugs_found.update(slugs)
                            result.queries_run += 1
                            captcha_count = 0  # Reset on success
                        except RuntimeError as e:
                            if "CAPTCHA" in str(e):
                                captcha_count += 1
                            logger.warning(f"Google search failed for '{query}': {e}")
                            result.errors.append(f"{query}: {e}")
                        except Exception as e:
                            logger.warning(f"Google search failed for '{query}': {e}")
                            result.errors.append(f"{query}: {e}")

                        # Human-like delay between searches
                        await asyncio.sleep(3 + (hash(kw) % 4))

                    if captcha_count >= 2:
                        break

                # Compute new slugs
                known = existing_slugs.get(platform, set())
                result.new_slugs = result.slugs_found - known

                results.append(result)
                logger.info(
                    f"Discovery [{platform}]: {len(result.slugs_found)} total, "
                    f"{len(result.new_slugs)} new slugs"
                )

        finally:
            await self._close()

        return results

    async def _wait_for_captcha_solve(self, page, timeout: int = 120) -> bool:
        """Wait for user to manually solve Google CAPTCHA in the browser window.

        Returns True if CAPTCHA was solved, False if timed out.
        """
        logger.info(
            f"Google CAPTCHA — solve it in the browser window (timeout: {timeout}s)"
        )
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(3)
            elapsed += 3
            url = page.url
            # Still on the /sorry/ page — keep waiting
            if "/sorry/" in url:
                continue
            # Redirected away from /sorry/ — CAPTCHA was solved
            logger.info(f"CAPTCHA solved — page now at: {url}")
            await asyncio.sleep(1)
            return True
        logger.warning(f"CAPTCHA not solved within {timeout}s")
        return False

    async def _handle_consent(self, page) -> None:
        """Dismiss Google consent/cookie dialog if present."""
        try:
            # Google consent page has various "Accept" / "Accept all" buttons
            for selector in [
                'button:has-text("Accept all")',
                'button:has-text("Accept")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                '#L2AGLb',  # Common Google consent button ID
            ]:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    await btn.click()
                    await asyncio.sleep(1.5)
                    logger.debug("Dismissed Google consent dialog")
                    return
        except Exception:
            pass  # No consent dialog — continue normally

    async def _search_google(
        self,
        page,
        behavior,
        query: str,
        slug_pattern: re.Pattern,
        max_pages: int,
    ) -> set[str]:
        """Run a single Google search by typing into the search box like a human."""
        slugs: set[str] = set()

        # Type query into Google search box (page should already be on google.com)
        search_box = page.locator('textarea[name="q"], input[name="q"]').first
        if await search_box.count() == 0:
            # Navigate to Google if not already there
            await page.goto("https://www.google.com", wait_until="domcontentloaded")
            await self._handle_consent(page)
            await asyncio.sleep(1)
            search_box = page.locator('textarea[name="q"], input[name="q"]').first

        # Clear any previous query and type the new one like a human
        await search_box.click()
        await asyncio.sleep(0.2)
        # Select all + delete to clear previous search
        if sys.platform == "darwin":
            await page.keyboard.press("Meta+a")
        else:
            await page.keyboard.press("Control+a")
        await asyncio.sleep(0.2)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.3)

        # Type query character by character with human-like delays
        for char in query:
            delay = random.uniform(0.04, 0.12)
            if random.random() < 0.05:
                delay += random.uniform(0.2, 0.5)  # Occasional thinking pause
            await page.keyboard.type(char, delay=int(delay * 1000))

        await asyncio.sleep(0.5 + (hash(query) % 10) / 10)  # Pause before pressing Enter
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await asyncio.sleep(2)

        # Check for CAPTCHA / sorry page redirect — let user solve it manually
        if "/sorry/" in page.url or _is_captcha(await page.inner_text("body")):
            logger.info("CAPTCHA detected — waiting for manual solve in browser window...")
            solved = await self._wait_for_captcha_solve(page)
            if not solved:
                raise RuntimeError("Google CAPTCHA detected — user did not solve within timeout")

            # After CAPTCHA solve, re-navigate to Google and re-type query
            await page.goto("https://www.google.com", wait_until="domcontentloaded")
            await asyncio.sleep(1)
            search_box = page.locator('textarea[name="q"], input[name="q"]').first
            await search_box.click()
            await asyncio.sleep(0.3)
            for char in query:
                delay = random.uniform(0.04, 0.12)
                await page.keyboard.type(char, delay=int(delay * 1000))
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(2)

            # If still blocked after solving, abort
            if "/sorry/" in page.url:
                raise RuntimeError("Google CAPTCHA detected — still blocked after solve")

        for page_num in range(max_pages):
            # Extract all links from search results
            links = await page.evaluate("""() => {
                const anchors = document.querySelectorAll('a[href]');
                return Array.from(anchors).map(a => a.href);
            }""")

            for link in links:
                match = slug_pattern.search(link)
                if match:
                    slug = match.group(1).lower()
                    # Skip Google's own tracking URLs and common non-company slugs
                    if slug not in _SKIP_SLUGS and len(slug) > 1:
                        slugs.add(slug)

            # Try next page if available
            if page_num < max_pages - 1:
                next_btn = page.locator('a[aria-label="Next"]')
                if await next_btn.count() > 0:
                    await behavior.smooth_scroll("down", 500)
                    await next_btn.click()
                    await asyncio.sleep(2)
                else:
                    break

        logger.debug(f"Google '{query}': found {len(slugs)} slugs")
        return slugs


# Slugs to skip (Google artifacts, non-company pages)
_SKIP_SLUGS = {
    "embed", "api", "v1", "boards", "jobs", "search",
    "posting-api", "job-board", "www", "support",
}


def _url_encode(text: str) -> str:
    """URL-encode a search query."""
    from urllib.parse import quote_plus
    return quote_plus(text)


def _is_captcha(text: str) -> bool:
    """Check if Google returned a real CAPTCHA block (not just a consent page)."""
    lower = text.lower()
    captcha_indicators = [
        "unusual traffic",
        "automated requests",
        "not a robot",
        "captcha",
        "systems have detected unusual traffic",
    ]
    return any(i in lower for i in captcha_indicators)


def get_existing_slugs() -> dict[str, set[str]]:
    """Load existing ATS slugs from config and database."""
    from src.scrapers.ats_scraper import (
        ASHBY_SLUGS,
        GREENHOUSE_SLUGS,
        _load_slugs_from_config,
        _load_greenhouse_slugs_from_db,
    )

    ashby_config = _load_slugs_from_config("ashby")
    greenhouse_config = _load_slugs_from_config("greenhouse")
    greenhouse_db = _load_greenhouse_slugs_from_db()

    return {
        "ashby": set(ASHBY_SLUGS.values()) | set(ashby_config.values()),
        "greenhouse": (
            set(GREENHOUSE_SLUGS.values())
            | set(greenhouse_config.values())
            | set(greenhouse_db.values())
        ),
        "lever": set(),
    }

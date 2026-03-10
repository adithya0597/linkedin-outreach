"""Hacker News Who Is Hiring scraper.

Parses the monthly "Ask HN: Who is hiring?" threads via hnhiring.com API
which provides structured JSON of HN hiring posts.

Tier D — New Source: 58K+ startup jobs, zero risk (public API).
"""

from __future__ import annotations

import contextlib
import re
from datetime import datetime

import httpx
from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.httpx_scraper import HttpxScraper
from src.scrapers.rate_limiter import RateLimiter


class HNHiringScraper(HttpxScraper):
    """Hacker News Who Is Hiring thread scraper via hnhiring.com.

    Uses hnhiring.com/technologies/<keyword>.json for structured data.
    Each result has company, title, location, remote status, and URL.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        super().__init__(SourcePortal.HN_HIRING, rate_limiter=rate_limiter)
        self._portal_name = "HN Hiring"

    @property
    def name(self) -> str:
        return self._portal_name

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        results: list[JobPosting] = []
        client = await self._get_client()
        seen_urls: set[str] = set()

        for kw in keywords:
            await self._throttle()
            # Go directly to HN Algolia API (hnhiring.com is dead)
            algolia_results = await self._search_hn_algolia(client, kw, days)
            for p in algolia_results:
                if p.url and p.url not in seen_urls:
                    seen_urls.add(p.url)
                    if self.apply_h1b_filter(p):
                        results.append(p)

        logger.info(f"HNHiringScraper found {len(results)} postings")
        return results

    def _parse_hn_item(self, item: dict) -> JobPosting | None:
        """Parse a single HN hiring post into a JobPosting."""
        if not isinstance(item, dict):
            return None

        # HN hiring posts typically start with "Company | Role | Location"
        text = item.get("text", "") or item.get("title", "") or item.get("comment", "")
        if not text:
            return None

        # Parse the standard HN hiring format: "Company | Role | Location | ..."
        parts = [p.strip() for p in text.split("|")]

        company = parts[0] if len(parts) > 0 else ""
        title = parts[1] if len(parts) > 1 else ""
        location = parts[2] if len(parts) > 2 else ""

        # If no clear title, try to extract from text
        if not title and company:
            title = f"Engineering at {company}"

        if not title:
            return None

        # Clean HTML tags
        company = re.sub(r"<[^>]+>", "", company).strip()
        title = re.sub(r"<[^>]+>", "", title).strip()
        location = re.sub(r"<[^>]+>", "", location).strip()

        # URL: use item URL or construct HN link
        job_url = item.get("url", "")
        if not job_url:
            item_id = item.get("id", "") or item.get("objectID", "")
            if item_id:
                job_url = f"https://news.ycombinator.com/item?id={item_id}"

        # Check for remote
        work_model = ""
        full_text = text.lower()
        if "remote" in full_text:
            work_model = "remote"
        elif "onsite" in full_text or "on-site" in full_text:
            work_model = "onsite"
        elif "hybrid" in full_text:
            work_model = "hybrid"

        # H1B check
        h1b_mentioned = any(t in full_text for t in ("h1b", "h-1b", "visa sponsor"))
        h1b_text = ""
        if h1b_mentioned:
            for part in parts:
                if any(t in part.lower() for t in ("h1b", "h-1b", "visa")):
                    h1b_text = part.strip()
                    break

        # Posted date
        posted_date = None
        created = item.get("created_at", "") or item.get("date", "")
        if created:
            with contextlib.suppress(ValueError, TypeError):
                posted_date = datetime.fromisoformat(created.replace("Z", "+00:00"))

        return JobPosting(
            title=title[:200],
            company_name=company[:100],
            location=location[:100],
            url=job_url,
            work_model=work_model,
            source_portal=SourcePortal.HN_HIRING,
            h1b_mentioned=h1b_mentioned,
            h1b_text=h1b_text,
            posted_date=posted_date,
            discovered_date=datetime.now(),
        )

    async def _search_hn_algolia(
        self, client: httpx.AsyncClient, keyword: str, days: int
    ) -> list[JobPosting]:
        """Fallback: search HN hiring threads via Algolia HN Search API."""
        results: list[JobPosting] = []

        # HN Search API (powered by Algolia)
        url = (
            f"https://hn.algolia.com/api/v1/search?"
            f"query={keyword}&tags=comment,ask_hn"
            f"&numericFilters=created_at_i>{int((datetime.now().timestamp()) - days * 86400)}"
        )

        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as e:
            logger.warning(f"HN Algolia fallback failed for '{keyword}': {e}")
            return results

        # Algolia returns {"hits": [...]}, but handle list responses gracefully
        if isinstance(data, list):
            hits = data
        else:
            hits = data.get("hits", [])

        for hit in hits[:30]:
            # Check if this is from a "Who is hiring" thread
            story_title = hit.get("story_title", "")
            if "hiring" not in story_title.lower():
                continue

            comment_text = hit.get("comment_text", "")
            if not comment_text:
                continue

            posting = self._parse_hn_item({
                "text": comment_text,
                "id": hit.get("objectID", ""),
                "created_at": hit.get("created_at", ""),
            })
            if posting:
                results.append(posting)

        return results


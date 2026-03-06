"""H1B verification system — 3-source waterfall with tier-aware auto-pass."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import httpx

from src.config.enums import H1BStatus, PortalTier, SourcePortal
from src.db.orm import CompanyORM, H1BORM
from src.models.h1b import H1BRecord

logger = logging.getLogger(__name__)


class FrogHireClient:
    """Scrapes froghire.ai/company for H1B sponsorship data using Playwright."""

    BASE_URL = "https://www.froghire.ai"
    SOURCE_NAME = "Frog Hire"

    def __init__(self, rate_limit_per_minute: int = 10):
        self._semaphore = asyncio.Semaphore(rate_limit_per_minute)
        self._delay = 60.0 / rate_limit_per_minute

    async def search(self, company_name: str) -> H1BRecord | None:
        """Search FrogHire for H1B sponsorship data.

        Uses Playwright to render JS-heavy pages. Returns None if no data found.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("playwright not installed, skipping FrogHire")
            return None

        url = f"{self.BASE_URL}/company?search={quote_plus(company_name)}"
        logger.info("FrogHire: searching %s", company_name)

        async with self._semaphore:
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=15000)

                    # Wait for results to load
                    await page.wait_for_timeout(2000)
                    content = await page.content()
                    await browser.close()

                return self._parse_result(company_name, content)
            except Exception as e:
                logger.error("FrogHire error for %s: %s", company_name, e)
                return None
            finally:
                await asyncio.sleep(self._delay)

    def _parse_result(self, company_name: str, html: str) -> H1BRecord | None:
        """Parse FrogHire HTML response for H1B data."""
        # Check for "no results" indicators
        if "No companies found" in html or "0 results" in html:
            return None

        record = H1BRecord(
            company_name=company_name,
            source=self.SOURCE_NAME,
            verified_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=30),
        )

        # Extract H1B status
        if re.search(r"H-?1B\s*(?:Sponsor|Visa|Yes|✓|✅)", html, re.IGNORECASE):
            record.status = H1BStatus.CONFIRMED
        elif re.search(r"H-?1B.*(?:No|✗|❌|Not Found)", html, re.IGNORECASE):
            record.status = H1BStatus.EXPLICIT_NO
        else:
            record.status = H1BStatus.UNKNOWN

        # Extract PERM
        if re.search(r"PERM\s*(?:Yes|✓|✅|Filed|Approved)", html, re.IGNORECASE):
            record.has_perm = True

        # Extract E-Verify
        if re.search(r"E-?Verify\s*(?:Yes|✓|✅|Enrolled|Participant)", html, re.IGNORECASE):
            record.has_everify = True

        # Extract employee count
        emp_match = re.search(r"(?:Employees?|Size)[:\s]*([0-9,]+(?:\s*[-–]\s*[0-9,]+)?)", html, re.IGNORECASE)
        if emp_match:
            record.employee_count_on_source = emp_match.group(1).strip()

        # Extract LCA count
        lca_match = re.search(r"(?:LCA|Labor Condition)[:\s]*([0-9,]+)", html, re.IGNORECASE)
        if lca_match:
            record.lca_count = int(lca_match.group(1).replace(",", ""))

        # Extract fiscal year
        fy_match = re.search(r"(?:FY|Fiscal Year)\s*(\d{4})", html, re.IGNORECASE)
        if fy_match:
            record.lca_fiscal_year = fy_match.group(1)

        # Extract ranking
        rank_match = re.search(r"#[\d,]+", html)
        if rank_match:
            record.ranking = rank_match.group(0)

        record.raw_data = html[:2000]  # Store first 2KB for debugging

        # Only return if we actually found meaningful data
        if record.status != H1BStatus.UNKNOWN or record.lca_count or record.has_perm:
            return record
        return None


class H1BGraderClient:
    """Queries h1bgrader.com for H1B approval data using httpx."""

    BASE_URL = "https://h1bgrader.com"
    SOURCE_NAME = "H1BGrader"

    def __init__(self, rate_limit_per_minute: int = 15):
        self._semaphore = asyncio.Semaphore(rate_limit_per_minute)
        self._delay = 60.0 / rate_limit_per_minute

    async def search(self, company_name: str) -> H1BRecord | None:
        """Search H1BGrader for H1B approval statistics."""
        url = f"{self.BASE_URL}/search/{quote_plus(company_name)}"
        logger.info("H1BGrader: searching %s", company_name)

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(
                    timeout=15.0,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; OutreachBot/1.0)"},
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return self._parse_result(company_name, response.text)
            except Exception as e:
                logger.error("H1BGrader error for %s: %s", company_name, e)
                return None
            finally:
                await asyncio.sleep(self._delay)

    def _parse_result(self, company_name: str, html: str) -> H1BRecord | None:
        """Parse H1BGrader HTML for approval rate and LCA data."""
        if "No results found" in html or "did not find" in html.lower():
            return None

        record = H1BRecord(
            company_name=company_name,
            source=self.SOURCE_NAME,
            verified_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=30),
        )

        # Extract approval rate
        rate_match = re.search(
            r"(?:Approval|Certification)\s*Rate[:\s]*([\d.]+)\s*%", html, re.IGNORECASE
        )
        if rate_match:
            record.approval_rate = float(rate_match.group(1))

        # Extract LCA count
        lca_match = re.search(r"(?:LCA|Cases?|Petitions?)[:\s]*([0-9,]+)", html, re.IGNORECASE)
        if lca_match:
            record.lca_count = int(lca_match.group(1).replace(",", ""))

        # Determine status from data
        if record.approval_rate is not None or record.lca_count:
            record.status = H1BStatus.CONFIRMED
        else:
            return None

        record.raw_data = html[:2000]
        return record


class MyVisaJobsClient:
    """Queries myvisajobs.com for H1B visa sponsor data using httpx."""

    BASE_URL = "https://www.myvisajobs.com"
    SOURCE_NAME = "MyVisaJobs"

    def __init__(self, rate_limit_per_minute: int = 15):
        self._semaphore = asyncio.Semaphore(rate_limit_per_minute)
        self._delay = 60.0 / rate_limit_per_minute

    async def search(self, company_name: str) -> H1BRecord | None:
        """Search MyVisaJobs for H1B sponsor information."""
        url = f"{self.BASE_URL}/Search_Visa_Sponsor.aspx?co={quote_plus(company_name)}"
        logger.info("MyVisaJobs: searching %s", company_name)

        async with self._semaphore:
            try:
                async with httpx.AsyncClient(
                    timeout=15.0,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; OutreachBot/1.0)"},
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return self._parse_result(company_name, response.text)
            except Exception as e:
                logger.error("MyVisaJobs error for %s: %s", company_name, e)
                return None
            finally:
                await asyncio.sleep(self._delay)

    def _parse_result(self, company_name: str, html: str) -> H1BRecord | None:
        """Parse MyVisaJobs HTML for LCA and approval data."""
        if "No matching records" in html or "0 Records" in html:
            return None

        record = H1BRecord(
            company_name=company_name,
            source=self.SOURCE_NAME,
            verified_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=30),
        )

        # Extract LCA count
        lca_match = re.search(r"(?:LCA|Applications?)[:\s]*([0-9,]+)", html, re.IGNORECASE)
        if lca_match:
            record.lca_count = int(lca_match.group(1).replace(",", ""))

        # Extract approval rate
        rate_match = re.search(
            r"(?:Approval|Certified)\s*(?:Rate)?[:\s]*([\d.]+)\s*%", html, re.IGNORECASE
        )
        if rate_match:
            record.approval_rate = float(rate_match.group(1))

        # Determine status
        if record.lca_count or record.approval_rate is not None:
            record.status = H1BStatus.CONFIRMED
        else:
            return None

        record.raw_data = html[:2000]
        return record


def _resolve_portal_tier(company: CompanyORM) -> PortalTier:
    """Determine the PortalTier for a company based on its source_portal field."""
    for sp in SourcePortal:
        if sp.value == company.source_portal:
            return sp.tier
    return PortalTier.TIER_2  # Default to Tier 2 (requires verification)


class H1BVerifier:
    """Orchestrates the 3-source waterfall H1B verification.

    - Tier 3 companies get auto-pass (no HTTP requests).
    - Tier 1/2 companies go through FrogHire -> H1BGrader -> MyVisaJobs waterfall.
    """

    def __init__(
        self,
        froghire: FrogHireClient | None = None,
        h1bgrader: H1BGraderClient | None = None,
        myvisajobs: MyVisaJobsClient | None = None,
    ):
        self.froghire = froghire or FrogHireClient()
        self.h1bgrader = h1bgrader or H1BGraderClient()
        self.myvisajobs = myvisajobs or MyVisaJobsClient()

    async def verify(self, company: CompanyORM) -> H1BRecord:
        """Verify H1B sponsorship for a single company.

        Tier 3: auto-pass with NOT_APPLICABLE.
        Tier 1/2: waterfall through 3 sources.
        """
        tier = _resolve_portal_tier(company)

        # Tier 3 auto-pass — no HTTP requests
        if tier == PortalTier.TIER_3:
            logger.info("Tier 3 auto-pass for %s (portal: %s)", company.name, company.source_portal)
            return H1BRecord(
                company_name=company.name,
                company_id=company.id,
                status=H1BStatus.NOT_APPLICABLE,
                source="auto_pass",
                verified_at=datetime.now(),
            )

        # Waterfall: FrogHire -> H1BGrader -> MyVisaJobs
        sources = [
            ("Frog Hire", self.froghire),
            ("H1BGrader", self.h1bgrader),
            ("MyVisaJobs", self.myvisajobs),
        ]

        for source_name, client in sources:
            logger.info("Trying %s for %s", source_name, company.name)
            record = await client.search(company.name)
            if record is not None:
                record.company_id = company.id
                logger.info(
                    "%s: found data for %s — status=%s",
                    source_name, company.name, record.status.value,
                )
                return record

        # All sources exhausted — return UNKNOWN
        logger.warning("No H1B data found for %s across all 3 sources", company.name)
        return H1BRecord(
            company_name=company.name,
            company_id=company.id,
            status=H1BStatus.UNKNOWN,
            source="waterfall_exhausted",
            verified_at=datetime.now(),
        )

    async def batch_verify(
        self,
        companies: list[CompanyORM],
        session=None,
        concurrency: int = 3,
    ) -> list[H1BRecord]:
        """Verify H1B status for a batch of companies.

        Args:
            companies: List of CompanyORM records to verify.
            session: Optional SQLAlchemy session to persist results.
            concurrency: Max concurrent verifications (rate limiting).

        Returns:
            List of H1BRecord results.
        """
        semaphore = asyncio.Semaphore(concurrency)
        results: list[H1BRecord] = []

        async def _verify_one(company: CompanyORM) -> H1BRecord:
            async with semaphore:
                return await self.verify(company)

        tasks = [_verify_one(c) for c in companies]
        results = await asyncio.gather(*tasks)

        # Persist results if session provided
        if session is not None:
            for record, company in zip(results, companies):
                # Save H1BORM record
                h1b_orm = H1BORM(
                    company_id=company.id,
                    company_name=record.company_name,
                    status=record.status.value,
                    source=record.source,
                    lca_count=record.lca_count,
                    lca_fiscal_year=record.lca_fiscal_year,
                    has_perm=record.has_perm,
                    has_everify=record.has_everify,
                    employee_count_on_source=record.employee_count_on_source,
                    ranking=record.ranking,
                    approval_rate=record.approval_rate,
                    raw_data=record.raw_data,
                    verified_at=record.verified_at,
                )
                session.add(h1b_orm)

                # Update CompanyORM h1b fields
                company.h1b_status = record.status.value
                company.h1b_source = record.source
                details_parts = []
                if record.lca_count:
                    details_parts.append(f"LCA: {record.lca_count}")
                if record.has_perm:
                    details_parts.append("PERM: Yes")
                if record.has_everify:
                    details_parts.append("E-Verify: Yes")
                if record.approval_rate is not None:
                    details_parts.append(f"Approval: {record.approval_rate}%")
                company.h1b_details = " | ".join(details_parts) if details_parts else ""

            session.commit()
            logger.info("Persisted %d H1B records to DB", len(results))

        return list(results)

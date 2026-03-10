"""H1B verification system — 3-source parallel consensus with tier-aware filtering."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import httpx

from src.config.enums import H1BStatus, PortalTier, SourcePortal
from src.db.orm import H1BORM, CompanyORM
from src.models.h1b import H1BRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared regex patterns for H1B status extraction
# ---------------------------------------------------------------------------

# Negative phrases that negate an H1B match — used as lookahead
_NEGATIVE_PHRASES = (
    r"denied|not\s+sponsor|no\s+sponsor|doesn['']t\s+sponsor|"
    r"does\s+not\s+sponsor|unable\s+to\s+sponsor|cannot\s+sponsor|"
    r"can['']t\s+sponsor|will\s+not\s+sponsor|won['']t\s+sponsor|"
    r"no\s+longer\s+sponsor"
)

# Positive H1B pattern — requires NO negative context following/preceding the match
_H1B_POSITIVE_PATTERN = re.compile(
    r"(?!.*(?:" + _NEGATIVE_PHRASES + r"))"  # negative lookahead over full match region
    r"H-?1B\s*(?:Sponsor|Visa|Yes|✓|✅)",
    re.IGNORECASE,
)

# Also match "Sponsors H1B" pattern (verb form)
_SPONSORS_H1B_PATTERN = re.compile(
    r"(?<!not\s)(?<!no\s)(?<!doesn['']t\s)(?<!cannot\s)(?<!unable\sto\s)"
    r"Sponsors?\s+H-?1B",
    re.IGNORECASE,
)

# Explicit negative pattern
_H1B_NEGATIVE_PATTERN = re.compile(
    r"H-?1B.*?(?:No|✗|❌|Not Found|Denied)", re.IGNORECASE
)

# Denial/negative context pattern — if H1B is mentioned alongside these words
_H1B_DENIAL_CONTEXT = re.compile(
    r"(?:" + _NEGATIVE_PHRASES + r").*H-?1B|H-?1B.*?(?:" + _NEGATIVE_PHRASES + r")",
    re.IGNORECASE,
)


def classify_h1b_text(html: str) -> H1BStatus:
    """Classify H1B status from raw HTML/text using hardened regex.

    Checks for denial context FIRST to avoid false positives, then checks
    for positive signals.

    Returns:
        H1BStatus.CONFIRMED — positive H1B sponsorship signal found
        H1BStatus.EXPLICIT_NO — explicit denial found
        H1BStatus.UNKNOWN — no signal either way
    """
    # Step 1: Check for explicit denial context FIRST
    if _H1B_DENIAL_CONTEXT.search(html):
        return H1BStatus.EXPLICIT_NO
    if _H1B_NEGATIVE_PATTERN.search(html):
        return H1BStatus.EXPLICIT_NO

    # Step 2: Check for positive signals (with negative lookahead baked in)
    if _H1B_POSITIVE_PATTERN.search(html):
        return H1BStatus.CONFIRMED
    if _SPONSORS_H1B_PATTERN.search(html):
        return H1BStatus.CONFIRMED

    return H1BStatus.UNKNOWN


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
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TESTING") == "1":
            raise RuntimeError(
                "Real browser launch blocked during testing! "
                "Mock the browser launch or use @pytest.mark.live"
            )

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
                    browser = await p.chromium.launch(headless=True, channel="chrome")
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)

                    # Wait for JS to render results
                    await page.wait_for_timeout(4000)
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

        # Extract H1B status using shared classifier
        record.status = classify_h1b_text(html)

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
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
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
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
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
            raw_val = lca_match.group(1).replace(",", "").strip()
            if raw_val.isdigit():
                record.lca_count = int(raw_val)

        # Extract approval rate
        rate_match = re.search(
            r"(?:Approval|Certified)\s*(?:Rate)?[:\s]*([\d.]+)\s*%", html, re.IGNORECASE
        )
        if rate_match:
            with contextlib.suppress(ValueError):
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


def _build_consensus(
    results: list[H1BRecord | None],
    source_labels: list[str],
) -> tuple[H1BStatus, str, list[dict]]:
    """Build consensus from parallel source results.

    Args:
        results: List of H1BRecord or None from each source.
        source_labels: Corresponding source names.

    Returns:
        (consensus_status, consensus_source_string, disagreement_details)

    Voting rules:
        - 2/3 or 3/3 agree on a non-UNKNOWN status -> that status wins
        - All sources return None -> UNKNOWN
        - No majority -> UNKNOWN + disagreement details logged
    """
    votes: list[tuple[str, H1BStatus]] = []
    details: list[dict] = []

    for label, record in zip(source_labels, results, strict=False):
        if record is None:
            votes.append((label, H1BStatus.UNKNOWN))
            details.append({"source": label, "status": "no_data", "record": None})
        else:
            votes.append((label, record.status))
            details.append({"source": label, "status": record.status.value, "record": record})

    # Count non-UNKNOWN statuses
    status_counts: Counter[H1BStatus] = Counter()
    for _, status in votes:
        if status != H1BStatus.UNKNOWN:
            status_counts[status] += 1

    # Check for consensus (2/3 or more agree)
    if status_counts:
        winner, count = status_counts.most_common(1)[0]
        if count >= 2:
            sources_agreeing = [label for label, s in votes if s == winner]
            return winner, f"consensus({','.join(sources_agreeing)})", details
        elif count == 1 and len(status_counts) == 1:
            # Only one source returned data, the others had no data
            source_label = next(label for label, s in votes if s == winner)
            return winner, f"single({source_label})", details

    # Check for disagreement (multiple non-UNKNOWN statuses that don't agree)
    disagreements = []
    if len(status_counts) > 1:
        for label, status in votes:
            if status != H1BStatus.UNKNOWN:
                disagreements.append({"source": label, "status": status.value})

    if disagreements:
        logger.warning(
            "H1B source disagreement: %s",
            json.dumps(disagreements, default=str),
        )

    # No consensus — return UNKNOWN
    return H1BStatus.UNKNOWN, "no_consensus", details


class H1BVerifier:
    """Orchestrates 3-source parallel H1B verification with consensus voting.

    - Tier 3 companies get auto-pass (no HTTP requests).
    - Tier 1/2 companies query all 3 sources in parallel, then vote.
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
        Tier 1/2: parallel query of 3 sources + consensus voting.
        """
        tier = _resolve_portal_tier(company)

        # Tier 3 auto-pass -- no HTTP requests
        if tier == PortalTier.TIER_3:
            logger.info("Tier 3 auto-pass for %s (portal: %s)", company.name, company.source_portal)
            return H1BRecord(
                company_name=company.name,
                company_id=company.id,
                status=H1BStatus.NOT_APPLICABLE,
                source="auto_pass",
                verified_at=datetime.now(),
            )

        # Parallel: query all 3 sources concurrently
        source_labels = ["Frog Hire", "H1BGrader", "MyVisaJobs"]
        raw_results = await asyncio.gather(
            self.froghire.search(company.name),
            self.h1bgrader.search(company.name),
            self.myvisajobs.search(company.name),
            return_exceptions=True,
        )

        # Convert exceptions to None
        results: list[H1BRecord | None] = []
        for i, r in enumerate(raw_results):
            if isinstance(r, BaseException):
                logger.error(
                    "%s raised exception for %s: %s",
                    source_labels[i], company.name, r,
                )
                results.append(None)
            else:
                results.append(r)

        # Build consensus from results
        consensus_status, consensus_source, details = _build_consensus(results, source_labels)

        # Pick the best record for metadata (prefer the one matching consensus)
        best_record: H1BRecord | None = None
        for d in details:
            if d["record"] is not None and d.get("status") == consensus_status.value:
                best_record = d["record"]
                break
        # Fallback: any non-None record
        if best_record is None:
            for d in details:
                if d["record"] is not None:
                    best_record = d["record"]
                    break

        if best_record is not None:
            best_record.company_id = company.id
            best_record.status = consensus_status
            best_record.source = consensus_source
            logger.info(
                "H1B consensus for %s: status=%s source=%s",
                company.name, consensus_status.value, consensus_source,
            )
            return best_record

        # All sources returned None
        logger.warning("No H1B data found for %s across all 3 sources", company.name)
        return H1BRecord(
            company_name=company.name,
            company_id=company.id,
            status=H1BStatus.UNKNOWN,
            source="all_sources_empty",
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
            for record, company in zip(results, companies, strict=False):
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

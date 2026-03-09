"""MCP Playwright -> SQLite bridge.

Converts JSON results saved by MCP Playwright skills into JobPosting
objects and persists them via the existing persist_scan_results() pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting


def load_mcp_results(json_path: str | Path) -> list[dict]:
    """Load MCP scan results from a JSON file.

    Expected format: list of dicts with keys:
    title, company_name, location, url, salary_range, work_model,
    h1b_mentioned, h1b_text, is_easy_apply, is_top_applicant, posted_date
    """
    path = Path(json_path)
    if not path.exists():
        logger.warning(f"MCP results file not found: {path}")
        return []

    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("results", data.get("jobs", [data]))
        if not isinstance(data, list):
            logger.warning(f"MCP results file has unexpected format: {path}")
            return []
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load MCP results from {path}: {e}")
        return []


def mcp_results_to_postings(
    results: list[dict],
    portal: SourcePortal,
) -> list[JobPosting]:
    """Convert raw MCP result dicts to JobPosting objects."""
    postings: list[JobPosting] = []
    for item in results:
        title = item.get("title", "").strip()
        if not title:
            continue

        posted_date = None
        pd_str = item.get("posted_date", "")
        if pd_str:
            try:
                posted_date = datetime.fromisoformat(pd_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        posting = JobPosting(
            title=title,
            company_name=item.get("company_name", "").strip(),
            location=item.get("location", "").strip(),
            url=item.get("url", "").strip(),
            salary_range=item.get("salary_range", ""),
            work_model=item.get("work_model", ""),
            source_portal=portal,
            h1b_mentioned=bool(item.get("h1b_mentioned", False)),
            h1b_text=item.get("h1b_text", ""),
            is_easy_apply=bool(item.get("is_easy_apply", False)),
            is_top_applicant=bool(item.get("is_top_applicant", False)),
            posted_date=posted_date,
        )
        postings.append(posting)

    return postings


def persist_mcp_results(
    portal_name: str,
    json_path: str | Path,
    portal: SourcePortal | None = None,
) -> tuple[int, int, int]:
    """Load MCP results from JSON and persist to SQLite.

    Args:
        portal_name: Portal key for scan audit (e.g., "linkedin", "wellfound")
        json_path: Path to the JSON results file
        portal: SourcePortal enum value. If None, inferred from portal_name.

    Returns:
        (total_found, new_inserted, new_companies)
    """
    from src.db.database import get_engine, get_session, init_db
    from src.scrapers.persistence import persist_scan_results

    # Infer portal from name if not provided
    if portal is None:
        portal_map = {
            "linkedin": SourcePortal.LINKEDIN,
            "wellfound": SourcePortal.WELLFOUND,
            "jobright": SourcePortal.JOBRIGHT,
            "trueup": SourcePortal.TRUEUP,
            "builtin": SourcePortal.BUILT_IN,
            "wttj": SourcePortal.WTTJ,
            "jobboard_ai": SourcePortal.JOBBOARD_AI,
        }
        portal = portal_map.get(portal_name, SourcePortal.MANUAL)

    raw = load_mcp_results(json_path)
    postings = mcp_results_to_postings(raw, portal)

    if not postings:
        logger.info(f"No results to persist for {portal_name} from {json_path}")
        return 0, 0, 0

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    try:
        result = persist_scan_results(session, portal_name, postings, scan_type="mcp")
        logger.info(f"MCP bridge persisted {result[1]} new postings for {portal_name}")
        return result
    finally:
        session.close()


def get_existing_urls(portal_name: str | None = None) -> set[str]:
    """Get all existing job posting URLs from the database.

    Args:
        portal_name: If provided, only return URLs from this portal.
    """
    from src.db.database import get_engine, get_session, init_db
    from src.db.orm import JobPostingORM

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    try:
        query = session.query(JobPostingORM.url).filter(JobPostingORM.url != "")
        if portal_name:
            query = query.filter(JobPostingORM.source_portal == portal_name)
        return {row[0] for row in query.all()}
    finally:
        session.close()


def get_last_scan_date(portal_name: str) -> datetime | None:
    """Get the most recent scan completion date for a portal."""
    from src.db.database import get_engine, get_session, init_db
    from src.db.orm import ScanORM

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    try:
        scan = (
            session.query(ScanORM)
            .filter(ScanORM.portal == portal_name)
            .order_by(ScanORM.completed_at.desc())
            .first()
        )
        return scan.completed_at if scan else None
    finally:
        session.close()

"""Persistence helpers for scan results."""

from __future__ import annotations

import json
import re
import string
from datetime import datetime

from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, JobPostingORM, ScanORM
from src.models.job_posting import JobPosting


def _normalize(text: str | None) -> str:
    """Normalize text for composite key and cache key comparison.

    Lowercase, strip whitespace, remove punctuation, collapse spaces.
    Returns empty string for None/empty input.
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = text.translate(str.maketrans("", "", string.punctuation))
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text


def posting_to_orm(posting: JobPosting) -> JobPostingORM:
    """Convert a JobPosting dataclass to an ORM model."""
    return JobPostingORM(
        company_name=posting.company_name,
        title=posting.title,
        url=posting.url,
        source_portal=posting.source_portal.value,
        location=posting.location,
        work_model=posting.work_model,
        salary_min=posting.salary_min,
        salary_max=posting.salary_max,
        salary_range=posting.salary_range,
        description=posting.description,
        requirements=json.dumps(posting.requirements),
        preferred=json.dumps(posting.preferred),
        tech_stack=json.dumps(posting.tech_stack),
        posted_date=posting.posted_date,
        discovered_date=posting.discovered_date,
        is_active=posting.is_active,
        h1b_mentioned=posting.h1b_mentioned,
        h1b_text=posting.h1b_text,
        is_easy_apply=posting.is_easy_apply,
        is_top_applicant=posting.is_top_applicant,
    )


def _get_or_create_company(
    session: Session,
    company_name: str,
    portal_name: str,
    role_url: str = "",
    role: str = "",
) -> CompanyORM | None:
    """Find existing company or create skeleton. Case-insensitive match.

    Backfills ``role_url`` and ``role`` on existing companies when they are
    currently empty and the incoming posting supplies a value.
    """
    if not company_name or not company_name.strip():
        return None
    existing = session.query(CompanyORM).filter(
        CompanyORM.name.ilike(company_name.strip())
    ).first()
    if existing:
        if not existing.role_url and role_url:
            existing.role_url = role_url
        if not existing.role and role:
            existing.role = role
        return existing
    company = CompanyORM(
        name=company_name.strip(),
        data_completeness=20.0,
        tier="Tier 5 - RESCAN",
        is_ai_native=True,
        source_portal=portal_name,
        stage="To apply",
        role_url=role_url,
        role=role,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    session.add(company)
    session.flush()
    return company


def persist_scan_results(
    session: Session,
    portal_name: str,
    postings: list[JobPosting],
    scan_type: str = "full",
    duration: float = 0.0,
    errors: str = "",
) -> tuple[int, int, int]:
    """Persist scan results, dedup by URL + composite key. Returns (total_found, new_inserted, new_companies)."""
    # Get existing URLs for dedup
    existing_urls = {
        row[0]
        for row in session.query(JobPostingORM.url)
        .filter(JobPostingORM.url != "")
        .all()
    }

    # Build composite key set from existing DB records for secondary dedup
    existing_composites: set[tuple[str, str]] = set()
    for row in session.query(JobPostingORM.company_name, JobPostingORM.title).all():
        if row[0] and row[1]:
            existing_composites.add((_normalize(row[0]), _normalize(row[1])))

    # Track intra-batch composites to avoid duplicates within a single scan
    batch_composites: set[tuple[str, str]] = set()

    # Preload existing company names for tracking new creations
    existing_company_names = {
        _normalize(row[0]) for row in session.query(CompanyORM.name).all() if row[0]
    }
    new_companies = 0
    company_cache: dict[str, CompanyORM | None] = {}

    new_count = 0
    for posting in postings:
        # Primary dedup: URL
        if posting.url and posting.url in existing_urls:
            continue

        # Secondary dedup: composite key (normalized company_name, normalized title)
        # When either field is empty/None, skip composite dedup — rely on URL-only
        norm_company = _normalize(posting.company_name)
        norm_title = _normalize(posting.title)
        if norm_company and norm_title:
            comp_key = (norm_company, norm_title)
            if comp_key in existing_composites or comp_key in batch_composites:
                continue
            batch_composites.add(comp_key)

        orm = posting_to_orm(posting)

        # Link posting to company (get or create)
        company_key = _normalize(posting.company_name)
        if company_key:
            if company_key not in company_cache:
                was_known = company_key in existing_company_names
                company = _get_or_create_company(
                    session, posting.company_name, portal_name,
                    role_url=posting.url, role=posting.title,
                )
                company_cache[company_key] = company
                if company and not was_known:
                    new_companies += 1
                    existing_company_names.add(company_key)
            else:
                company = company_cache[company_key]
            if company:
                orm.company_id = company.id

        session.add(orm)
        existing_urls.add(posting.url)
        new_count += 1

    # Create scan audit record
    scan = ScanORM(
        portal=portal_name,
        scan_type=scan_type,
        started_at=datetime.now(),
        completed_at=datetime.now(),
        companies_found=len(postings),
        new_companies=new_count,
        errors=errors,
        is_healthy=not bool(errors),
        duration_seconds=duration,
    )
    session.add(scan)
    session.commit()

    return len(postings), new_count, new_companies

"""Persistence helpers for scan results."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from src.db.orm import JobPostingORM, ScanORM
from src.models.job_posting import JobPosting


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


def persist_scan_results(
    session: Session,
    portal_name: str,
    postings: list[JobPosting],
    scan_type: str = "full",
    duration: float = 0.0,
    errors: str = "",
) -> tuple[int, int]:
    """Persist scan results, dedup by URL. Returns (total_found, new_inserted)."""
    # Get existing URLs for dedup
    existing_urls = {
        row[0]
        for row in session.query(JobPostingORM.url)
        .filter(JobPostingORM.url != "")
        .all()
    }

    new_count = 0
    for posting in postings:
        if posting.url and posting.url in existing_urls:
            continue
        orm = posting_to_orm(posting)
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

    return len(postings), new_count

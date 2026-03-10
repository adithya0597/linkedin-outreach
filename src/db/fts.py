"""FTS5 full-text search for job postings."""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def create_fts5_table(engine: Engine) -> None:
    """Create FTS5 virtual table for job posting search."""
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS job_postings_fts "
            "USING fts5(title, description, company_name, content='job_postings', content_rowid='id')"
        ))
        conn.commit()
    logger.info("FTS5 table 'job_postings_fts' created/verified")


def rebuild_fts_index(engine: Engine) -> None:
    """Rebuild FTS5 index from existing job_postings data."""
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO job_postings_fts(job_postings_fts) VALUES('rebuild')"
        ))
        conn.commit()
    logger.info("FTS5 index rebuilt")


def fts_search(session: Session, query: str, limit: int = 50):
    """Search job postings using FTS5 full-text search.

    Returns list of matching job posting rows with relevance ranking.
    """
    from src.db.orm import JobPostingORM

    results = session.execute(text(
        "SELECT rowid, rank FROM job_postings_fts WHERE job_postings_fts MATCH :query "
        "ORDER BY rank LIMIT :limit"
    ), {"query": query, "limit": limit}).fetchall()

    if not results:
        return []

    row_ids = [r[0] for r in results]
    postings = session.query(JobPostingORM).filter(
        JobPostingORM.id.in_(row_ids)
    ).all()

    # Preserve FTS rank ordering
    id_to_posting = {p.id: p for p in postings}
    return [id_to_posting[rid] for rid in row_ids if rid in id_to_posting]

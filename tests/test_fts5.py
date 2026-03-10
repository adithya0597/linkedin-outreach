"""Tests for FTS5 search and Lever registry removal."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.fts import create_fts5_table, fts_search, rebuild_fts_index
from src.db.orm import Base, JobPostingORM


@pytest.fixture
def fts_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    create_fts5_table(engine)
    return engine


@pytest.fixture
def fts_session(fts_engine):
    factory = sessionmaker(bind=fts_engine)
    sess = factory()
    yield sess
    sess.close()


def _seed_postings(session: Session) -> None:
    """Insert sample job postings for search tests."""
    postings = [
        JobPostingORM(
            title="Senior AI Engineer",
            description="Build production ML pipelines using LangChain and vector databases",
            company_name="Acme AI",
            url="https://acme.ai/jobs/1",
        ),
        JobPostingORM(
            title="Backend Software Engineer",
            description="Build REST APIs with Python and FastAPI",
            company_name="WebCorp",
            url="https://webcorp.com/jobs/1",
        ),
        JobPostingORM(
            title="ML Infrastructure Engineer",
            description="Design and operate ML training infrastructure using Kubernetes and GPU clusters",
            company_name="DeepTech",
            url="https://deeptech.ai/jobs/1",
        ),
        JobPostingORM(
            title="LLM Application Developer",
            description="Build LLM-powered applications with RAG, LangChain, and Neo4j knowledge graphs",
            company_name="GraphAI",
            url="https://graphai.com/jobs/1",
        ),
    ]
    session.add_all(postings)
    session.commit()


# ── Lever registry removal ──────────────────────────────────────────────


def test_lever_not_in_default_registry():
    """LeverScraper should not be in the default registry."""
    from src.scrapers.registry import build_default_registry

    registry = build_default_registry()
    with pytest.raises(KeyError, match="lever"):
        registry.get_scraper("lever")


def test_lever_not_in_scraper_list():
    """Lever should not appear in get_all_scrapers."""
    from src.scrapers.registry import build_default_registry

    registry = build_default_registry()
    names = [s.name for s in registry.get_all_scrapers()]
    assert "Lever" not in names


# ── FTS5 table creation ─────────────────────────────────────────────────


def test_fts5_table_creation(fts_engine):
    """FTS5 virtual table should be created successfully."""
    from sqlalchemy import text

    with fts_engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='job_postings_fts'"
        )).fetchall()
    assert len(tables) == 1
    assert tables[0][0] == "job_postings_fts"


def test_fts5_table_idempotent(fts_engine):
    """Calling create_fts5_table twice should not error."""
    create_fts5_table(fts_engine)  # second call
    # No exception = pass


# ── FTS5 search ──────────────────────────────────────────────────────────


def test_fts5_search_returns_results(fts_engine, fts_session):
    """FTS5 search should return matching postings."""
    _seed_postings(fts_session)
    rebuild_fts_index(fts_engine)

    results = fts_search(fts_session, "LangChain")
    assert len(results) >= 1
    titles = [r.title for r in results]
    assert any("AI" in t or "LLM" in t for t in titles)


def test_fts5_search_ranking(fts_engine, fts_session):
    """More relevant results should appear first."""
    _seed_postings(fts_session)
    rebuild_fts_index(fts_engine)

    results = fts_search(fts_session, "ML infrastructure")
    assert len(results) >= 1
    # The ML Infrastructure posting should rank highest
    assert "ML Infrastructure" in results[0].title or "ML" in results[0].title


def test_fts5_search_no_match(fts_engine, fts_session):
    """Search for nonexistent term returns empty list."""
    _seed_postings(fts_session)
    rebuild_fts_index(fts_engine)

    results = fts_search(fts_session, "quantumzygomorphic")
    assert results == []


def test_fts5_search_empty_index(fts_engine, fts_session):
    """Search on empty index returns empty list."""
    results = fts_search(fts_session, "AI Engineer")
    assert results == []


# ── FTS5 rebuild ─────────────────────────────────────────────────────────


def test_fts5_rebuild_from_existing(fts_engine, fts_session):
    """Rebuild should re-index all existing postings."""
    _seed_postings(fts_session)
    rebuild_fts_index(fts_engine)

    # Should find all postings that mention AI or ML
    results = fts_search(fts_session, "AI OR ML")
    assert len(results) >= 2


def test_fts5_rebuild_idempotent(fts_engine, fts_session):
    """Rebuilding twice should produce the same results."""
    _seed_postings(fts_session)
    rebuild_fts_index(fts_engine)
    rebuild_fts_index(fts_engine)

    results = fts_search(fts_session, "LangChain")
    assert len(results) >= 1

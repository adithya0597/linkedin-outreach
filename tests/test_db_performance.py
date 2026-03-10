"""Tests for composite DB indexes and SQLite PRAGMAs."""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.db.database import get_engine, init_db
from src.db.orm import Base


# ---------------------------------------------------------------------------
# Index tests
# ---------------------------------------------------------------------------


def test_company_indexes():
    """CompanyORM has composite indexes on (is_disqualified, stage) and (source_portal, tier)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("companies")
    index_names = {idx["name"] for idx in indexes}
    assert "ix_company_disqualified_stage" in index_names
    assert "ix_company_source_tier" in index_names


def test_company_disqualified_stage_columns():
    """ix_company_disqualified_stage covers (is_disqualified, stage)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("companies")
    idx = next(i for i in indexes if i["name"] == "ix_company_disqualified_stage")
    assert idx["column_names"] == ["is_disqualified", "stage"]


def test_company_source_tier_columns():
    """ix_company_source_tier covers (source_portal, tier)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("companies")
    idx = next(i for i in indexes if i["name"] == "ix_company_source_tier")
    assert idx["column_names"] == ["source_portal", "tier"]


def test_contact_indexes():
    """ContactORM has composite index on (company_id, contact_score)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("contacts")
    index_names = {idx["name"] for idx in indexes}
    assert "ix_contact_company_score" in index_names


def test_contact_company_score_columns():
    """ix_contact_company_score covers (company_id, contact_score)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("contacts")
    idx = next(i for i in indexes if i["name"] == "ix_contact_company_score")
    assert idx["column_names"] == ["company_id", "contact_score"]


def test_job_posting_indexes():
    """JobPostingORM has composite index on (source_portal, company_id) and UniqueConstraint on url."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("job_postings")
    index_names = {idx["name"] for idx in indexes}
    assert "ix_posting_portal_company" in index_names


def test_job_posting_portal_company_columns():
    """ix_posting_portal_company covers (source_portal, company_id)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("job_postings")
    idx = next(i for i in indexes if i["name"] == "ix_posting_portal_company")
    assert idx["column_names"] == ["source_portal", "company_id"]


def test_job_posting_unique_constraint_preserved():
    """UniqueConstraint on url is still present."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    uniques = inspector.get_unique_constraints("job_postings")
    constraint_names = {u["name"] for u in uniques}
    assert "uq_postings_url" in constraint_names


def test_scan_indexes():
    """ScanORM has composite index on (portal, started_at)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("scans")
    index_names = {idx["name"] for idx in indexes}
    assert "ix_scan_portal_started" in index_names


def test_scan_portal_started_columns():
    """ix_scan_portal_started covers (portal, started_at)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    indexes = inspector.get_indexes("scans")
    idx = next(i for i in indexes if i["name"] == "ix_scan_portal_started")
    assert idx["column_names"] == ["portal", "started_at"]


def test_create_all_with_indexes_succeeds():
    """Creating all tables (including indexes) completes without error."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "companies" in tables
    assert "contacts" in tables
    assert "job_postings" in tables
    assert "scans" in tables


# ---------------------------------------------------------------------------
# PRAGMA tests
# ---------------------------------------------------------------------------


def test_pragma_journal_mode(tmp_path):
    """WAL journal mode is set on connect."""
    engine = get_engine(str(tmp_path / "test.db"))
    init_db(engine)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert result == "wal"


def test_pragma_foreign_keys(tmp_path):
    """Foreign keys are enabled on connect."""
    engine = get_engine(str(tmp_path / "test.db"))
    init_db(engine)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1


def test_pragma_synchronous(tmp_path):
    """Synchronous mode is set to NORMAL (1)."""
    engine = get_engine(str(tmp_path / "test.db"))
    init_db(engine)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA synchronous")).scalar()
        assert result == 1  # NORMAL = 1


def test_pragma_cache_size(tmp_path):
    """Cache size is set to -10000 (10MB)."""
    engine = get_engine(str(tmp_path / "test.db"))
    init_db(engine)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA cache_size")).scalar()
        assert result == -10000


def test_pragma_busy_timeout(tmp_path):
    """Busy timeout is set to 5000ms."""
    engine = get_engine(str(tmp_path / "test.db"))
    init_db(engine)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA busy_timeout")).scalar()
        assert result == 5000


def test_pragma_temp_store(tmp_path):
    """Temp store is set to MEMORY (2)."""
    engine = get_engine(str(tmp_path / "test.db"))
    init_db(engine)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA temp_store")).scalar()
        assert result == 2  # MEMORY = 2

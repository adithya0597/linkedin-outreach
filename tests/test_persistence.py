"""Tests for persistence dedup logic and ORM constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.config.enums import SourcePortal
from src.db.orm import Base, CompanyORM, JobPostingORM
from src.models.job_posting import JobPosting
from src.scrapers.persistence import _normalize, persist_scan_results

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """In-memory SQLite engine with all tables created."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    """Database session scoped to one test."""
    factory = sessionmaker(bind=engine)
    sess = factory()
    yield sess
    sess.close()


def _make_posting(
    company_name: str = "TestCo",
    title: str = "AI Engineer",
    url: str = "https://example.com/job/1",
    portal: SourcePortal = SourcePortal.STARTUP_JOBS,
) -> JobPosting:
    """Helper to build a JobPosting with overridable fields."""
    return JobPosting(
        company_name=company_name,
        title=title,
        url=url,
        source_portal=portal,
    )


# ---------------------------------------------------------------------------
# 1. Empty-field dedup: falls back to URL-only when company_name or title empty
# ---------------------------------------------------------------------------


class TestEmptyFieldDedup:
    """When company_name or title is empty/None, composite key dedup is skipped
    and only URL dedup protects against duplicates."""

    def test_empty_company_name_different_urls_both_inserted(self, session: Session):
        """Two postings with empty company_name but different URLs should both
        be inserted (composite dedup is skipped)."""
        postings = [
            _make_posting(company_name="", title="AI Engineer", url="https://a.com/1"),
            _make_posting(company_name="", title="AI Engineer", url="https://a.com/2"),
        ]
        _total, new, _ = persist_scan_results(session, "test", postings)
        assert new == 2

    def test_none_company_name_different_urls_both_inserted(self, session: Session):
        """None company_name also skips composite dedup."""
        postings = [
            _make_posting(company_name=None, title="AI Engineer", url="https://a.com/1"),
            _make_posting(company_name=None, title="AI Engineer", url="https://a.com/2"),
        ]
        _total, new, _ = persist_scan_results(session, "test", postings)
        assert new == 2

    def test_empty_title_different_urls_both_inserted(self, session: Session):
        """Empty title skips composite dedup — URL is the only guard."""
        postings = [
            _make_posting(company_name="Acme", title="", url="https://a.com/1"),
            _make_posting(company_name="Acme", title="", url="https://a.com/2"),
        ]
        _total, new, _ = persist_scan_results(session, "test", postings)
        assert new == 2

    def test_none_title_different_urls_both_inserted(self, session: Session):
        """None title skips composite dedup."""
        postings = [
            _make_posting(company_name="Acme", title=None, url="https://a.com/1"),
            _make_posting(company_name="Acme", title=None, url="https://a.com/2"),
        ]
        _total, new, _ = persist_scan_results(session, "test", postings)
        assert new == 2

    def test_both_fields_empty_same_url_deduped(self, session: Session):
        """When both fields are empty, URL dedup still catches duplicates."""
        postings = [
            _make_posting(company_name="", title="", url="https://a.com/same"),
            _make_posting(company_name="", title="", url="https://a.com/same"),
        ]
        _total, new, _ = persist_scan_results(session, "test", postings)
        assert new == 1

    def test_empty_fields_deduped_against_existing_by_url(self, session: Session):
        """Postings with empty fields that match an existing URL are still deduped."""
        # First batch: insert one
        persist_scan_results(
            session,
            "test",
            [_make_posting(company_name="", title="", url="https://a.com/x")],
        )
        # Second batch: same URL should be deduped
        _, new, _ = persist_scan_results(
            session,
            "test",
            [_make_posting(company_name="", title="", url="https://a.com/x")],
        )
        assert new == 0


# ---------------------------------------------------------------------------
# 2. Case sensitivity: "Acme Corp" vs "acme corp" vs " ACME CORP " should
#    hit the same composite key and the same company cache entry
# ---------------------------------------------------------------------------


class TestCaseSensitivity:
    """Company name normalization must be case-insensitive and whitespace-tolerant."""

    def test_normalize_basic_cases(self):
        assert _normalize("Acme Corp") == "acme corp"
        assert _normalize("acme corp") == "acme corp"
        assert _normalize(" ACME CORP ") == "acme corp"

    def test_normalize_strips_punctuation(self):
        assert _normalize("Acme, Corp.") == "acme corp"

    def test_normalize_collapses_whitespace(self):
        assert _normalize("Acme   Corp") == "acme corp"

    def test_normalize_none_returns_empty(self):
        assert _normalize(None) == ""

    def test_normalize_empty_returns_empty(self):
        assert _normalize("") == ""

    def test_composite_dedup_case_insensitive_within_batch(self, session: Session):
        """Two postings with same company/title but different casing should
        be deduped within a single batch (second one dropped)."""
        postings = [
            _make_posting(company_name="Acme Corp", title="AI Engineer", url="https://a.com/1"),
            _make_posting(company_name="acme corp", title="ai engineer", url="https://a.com/2"),
        ]
        _, new, _ = persist_scan_results(session, "test", postings)
        assert new == 1

    def test_composite_dedup_case_insensitive_across_batches(self, session: Session):
        """Second batch posting with same normalized company/title as existing
        DB record should be deduped."""
        persist_scan_results(
            session,
            "test",
            [_make_posting(company_name="Acme Corp", title="AI Engineer", url="https://a.com/1")],
        )
        _, new, _ = persist_scan_results(
            session,
            "test",
            [_make_posting(company_name=" ACME CORP ", title="  AI ENGINEER  ", url="https://a.com/2")],
        )
        assert new == 0

    def test_composite_dedup_whitespace_variations(self, session: Session):
        """Extra whitespace in company_name or title should still dedup."""
        postings = [
            _make_posting(company_name="Acme Corp", title="AI Engineer", url="https://a.com/1"),
            _make_posting(company_name="  Acme  Corp  ", title="  AI  Engineer  ", url="https://a.com/2"),
        ]
        _, new, _ = persist_scan_results(session, "test", postings)
        assert new == 1

    def test_company_cache_case_insensitive(self, session: Session):
        """'Acme Corp', 'acme corp', and ' ACME CORP ' should all resolve
        to the same company in the DB (only one CompanyORM created)."""
        postings = [
            _make_posting(company_name="Acme Corp", title="Role A", url="https://a.com/1"),
            _make_posting(company_name="acme corp", title="Role B", url="https://a.com/2"),
            _make_posting(company_name=" ACME CORP ", title="Role C", url="https://a.com/3"),
        ]
        _, new, new_companies = persist_scan_results(session, "test", postings)
        # All three have unique titles so they pass composite dedup,
        # but they should map to ONE company
        assert new == 3
        assert new_companies == 1
        companies = session.query(CompanyORM).all()
        assert len(companies) == 1


# ---------------------------------------------------------------------------
# 3. URL uniqueness constraint at DB level
# ---------------------------------------------------------------------------


class TestURLUniquenessConstraint:
    """The UniqueConstraint on job_postings.url should prevent duplicate URLs
    at the database level as a safety net."""

    def test_duplicate_url_raises_integrity_error(self, session: Session):
        """Inserting two ORM objects with the same non-empty URL should raise
        IntegrityError when the session is flushed."""
        p1 = JobPostingORM(url="https://example.com/job/1", company_name="A", title="T1")
        p2 = JobPostingORM(url="https://example.com/job/1", company_name="B", title="T2")
        session.add(p1)
        session.flush()
        session.add(p2)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_different_urls_no_conflict(self, session: Session):
        """Distinct URLs should not conflict."""
        p1 = JobPostingORM(url="https://example.com/job/1", company_name="A", title="T1")
        p2 = JobPostingORM(url="https://example.com/job/2", company_name="A", title="T1")
        session.add_all([p1, p2])
        session.flush()  # Should not raise
        assert session.query(JobPostingORM).count() == 2

    def test_persist_scan_dedup_prevents_constraint_violation(self, session: Session):
        """persist_scan_results should dedup in-memory so the constraint is
        never hit during normal operation."""
        postings = [
            _make_posting(company_name="A", title="T1", url="https://a.com/1"),
            _make_posting(company_name="B", title="T2", url="https://a.com/1"),
        ]
        _, new, _ = persist_scan_results(session, "test", postings)
        assert new == 1


# ---------------------------------------------------------------------------
# 4. Regression / integration tests
# ---------------------------------------------------------------------------


class TestPersistScanResultsIntegration:
    """End-to-end tests for the full persist_scan_results flow."""

    def test_basic_insert(self, session: Session):
        """Three unique postings should all be inserted."""
        postings = [
            _make_posting(company_name="A", title="T1", url="https://a.com/1"),
            _make_posting(company_name="B", title="T2", url="https://b.com/1"),
            _make_posting(company_name="C", title="T3", url="https://c.com/1"),
        ]
        total, new, new_co = persist_scan_results(session, "test", postings)
        assert total == 3
        assert new == 3
        assert new_co == 3

    def test_scan_record_created(self, session: Session):
        """A ScanORM audit record should be created for every call."""
        from src.db.orm import ScanORM

        persist_scan_results(session, "test_portal", [])
        scans = session.query(ScanORM).all()
        assert len(scans) == 1
        assert scans[0].portal == "test_portal"

    def test_url_dedup_across_batches(self, session: Session):
        """A URL seen in batch 1 should be deduped in batch 2."""
        batch1 = [_make_posting(company_name="A", title="T1", url="https://a.com/1")]
        batch2 = [_make_posting(company_name="A", title="T1", url="https://a.com/1")]
        persist_scan_results(session, "test", batch1)
        _, new, _ = persist_scan_results(session, "test", batch2)
        assert new == 0

    def test_company_not_duplicated_across_batches(self, session: Session):
        """Same company appearing in two batches should only create one CompanyORM."""
        batch1 = [_make_posting(company_name="Acme", title="Role A", url="https://a.com/1")]
        batch2 = [_make_posting(company_name="Acme", title="Role B", url="https://a.com/2")]
        _, _, co1 = persist_scan_results(session, "test", batch1)
        _, _, co2 = persist_scan_results(session, "test", batch2)
        assert co1 == 1
        assert co2 == 0
        assert session.query(CompanyORM).count() == 1

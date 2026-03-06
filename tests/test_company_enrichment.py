"""Tests for company auto-creation from job postings."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.enums import SourcePortal
from src.db.orm import Base, CompanyORM, JobPostingORM
from src.models.job_posting import JobPosting
from src.scrapers.persistence import _get_or_create_company, persist_scan_results


@pytest.fixture
def enrichment_engine():
    """In-memory SQLite engine for enrichment tests."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def enrichment_session(enrichment_engine):
    """Database session for enrichment tests."""
    factory = sessionmaker(bind=enrichment_engine)
    sess = factory()
    yield sess
    sess.close()


# ── _get_or_create_company tests ──────────────────────────────────────


class TestGetOrCreateCompany:
    def test_creates_skeleton_with_correct_defaults(self, enrichment_session: Session):
        """New company should be created with skeleton defaults."""
        company = _get_or_create_company(enrichment_session, "Acme AI", "startup.jobs")

        assert company is not None
        assert company.id is not None
        assert company.name == "Acme AI"
        assert company.data_completeness == 20.0
        assert company.tier == "Tier 5 - RESCAN"
        assert company.is_ai_native is True
        assert company.source_portal == "startup.jobs"
        assert company.stage == "To apply"
        assert isinstance(company.created_at, datetime)
        assert isinstance(company.updated_at, datetime)

    def test_returns_existing_company_case_insensitive(self, enrichment_session: Session):
        """Should find existing company regardless of case."""
        # Create the company first
        first = _get_or_create_company(enrichment_session, "Acme AI", "startup.jobs")
        enrichment_session.flush()

        # Look it up with different case
        second = _get_or_create_company(enrichment_session, "acme ai", "jobright")
        third = _get_or_create_company(enrichment_session, "ACME AI", "linkedin")

        assert first.id == second.id
        assert first.id == third.id

        # Only one company should exist
        count = enrichment_session.query(CompanyORM).count()
        assert count == 1

    def test_returns_none_for_empty_name(self, enrichment_session: Session):
        """Empty or whitespace-only names should return None."""
        assert _get_or_create_company(enrichment_session, "", "startup.jobs") is None
        assert _get_or_create_company(enrichment_session, "   ", "startup.jobs") is None
        assert _get_or_create_company(enrichment_session, None, "startup.jobs") is None


# ── persist_scan_results tests ────────────────────────────────────────


class TestPersistScanResultsCompanyEnrichment:
    def test_creates_companies_for_new_postings(self, enrichment_session: Session):
        """Persisting postings should auto-create CompanyORM for new company names."""
        postings = [
            JobPosting(
                company_name="AlphaAI",
                title="AI Engineer",
                url="https://example.com/alpha-1",
                source_portal=SourcePortal.STARTUP_JOBS,
            ),
            JobPosting(
                company_name="BetaML",
                title="ML Engineer",
                url="https://example.com/beta-1",
                source_portal=SourcePortal.HIRING_CAFE,
            ),
        ]
        found, new, new_co = persist_scan_results(
            enrichment_session, "startup.jobs", postings
        )

        assert new_co == 2
        assert enrichment_session.query(CompanyORM).count() == 2

        alpha = enrichment_session.query(CompanyORM).filter(
            CompanyORM.name == "AlphaAI"
        ).first()
        assert alpha is not None
        assert alpha.tier == "Tier 5 - RESCAN"

    def test_links_postings_to_companies(self, enrichment_session: Session):
        """Job postings should have company_id set to the matching company."""
        postings = [
            JobPosting(
                company_name="GammaAI",
                title="Backend Engineer",
                url="https://example.com/gamma-1",
                source_portal=SourcePortal.JOBRIGHT,
            ),
        ]
        persist_scan_results(enrichment_session, "jobright", postings)

        posting_orm = enrichment_session.query(JobPostingORM).filter(
            JobPostingORM.url == "https://example.com/gamma-1"
        ).first()
        company_orm = enrichment_session.query(CompanyORM).filter(
            CompanyORM.name == "GammaAI"
        ).first()

        assert posting_orm is not None
        assert company_orm is not None
        assert posting_orm.company_id == company_orm.id

    def test_no_duplicate_companies_from_same_name(self, enrichment_session: Session):
        """Multiple postings from the same company should create only one CompanyORM."""
        postings = [
            JobPosting(
                company_name="DeltaAI",
                title="AI Engineer",
                url="https://example.com/delta-1",
                source_portal=SourcePortal.STARTUP_JOBS,
            ),
            JobPosting(
                company_name="DeltaAI",
                title="ML Engineer",
                url="https://example.com/delta-2",
                source_portal=SourcePortal.STARTUP_JOBS,
            ),
            JobPosting(
                company_name="deltaai",
                title="Data Engineer",
                url="https://example.com/delta-3",
                source_portal=SourcePortal.STARTUP_JOBS,
            ),
        ]
        found, new, new_co = persist_scan_results(
            enrichment_session, "startup.jobs", postings
        )

        assert new_co == 1
        assert enrichment_session.query(CompanyORM).count() == 1

        # All three postings should link to the same company
        posting_orms = enrichment_session.query(JobPostingORM).all()
        company_ids = {p.company_id for p in posting_orms}
        assert len(company_ids) == 1

    def test_links_to_existing_company(self, enrichment_session: Session):
        """If a company already exists in the DB, postings should link to it."""
        # Pre-create company
        existing = CompanyORM(
            name="ExistingCorp",
            tier="Tier 2 - STRONG",
            data_completeness=80.0,
            source_portal="Manual",
        )
        enrichment_session.add(existing)
        enrichment_session.commit()
        existing_id = existing.id

        postings = [
            JobPosting(
                company_name="ExistingCorp",
                title="AI Engineer",
                url="https://example.com/existing-1",
                source_portal=SourcePortal.WELLFOUND,
            ),
        ]
        found, new, new_co = persist_scan_results(
            enrichment_session, "wellfound", postings
        )

        assert new_co == 0  # No new companies
        posting_orm = enrichment_session.query(JobPostingORM).first()
        assert posting_orm.company_id == existing_id

        # Existing company should not be overwritten
        company = enrichment_session.query(CompanyORM).filter(
            CompanyORM.name == "ExistingCorp"
        ).first()
        assert company.tier == "Tier 2 - STRONG"
        assert company.data_completeness == 80.0

    def test_returns_three_tuple_with_new_companies_count(
        self, enrichment_session: Session
    ):
        """persist_scan_results should return (total_found, new_postings, new_companies)."""
        postings = [
            JobPosting(
                company_name="EpsilonAI",
                title="Engineer",
                url="https://example.com/eps-1",
                source_portal=SourcePortal.AI_JOBS,
            ),
            JobPosting(
                company_name="EpsilonAI",
                title="Senior Engineer",
                url="https://example.com/eps-2",
                source_portal=SourcePortal.AI_JOBS,
            ),
            JobPosting(
                company_name="ZetaML",
                title="ML Engineer",
                url="https://example.com/zeta-1",
                source_portal=SourcePortal.AI_JOBS,
            ),
        ]

        result = persist_scan_results(enrichment_session, "aijobs", postings)

        assert isinstance(result, tuple)
        assert len(result) == 3
        total_found, new_postings, new_companies = result
        assert total_found == 3
        assert new_postings == 3
        assert new_companies == 2  # EpsilonAI + ZetaML

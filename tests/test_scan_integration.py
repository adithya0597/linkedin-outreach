"""Tests for scan integration: persistence, CLI wiring, and pipeline scan_all."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.enums import SourcePortal
from src.db.orm import CompanyORM, JobPostingORM, ScanORM
from src.models.job_posting import JobPosting
from src.scrapers.persistence import persist_scan_results, posting_to_orm


# ---------------------------------------------------------------------------
# posting_to_orm
# ---------------------------------------------------------------------------


class TestPostingToORM:
    def test_converts_basic_fields(self):
        posting = JobPosting(
            company_name="Acme",
            title="AI Eng",
            url="https://x.com/1",
            source_portal=SourcePortal.STARTUP_JOBS,
        )
        orm = posting_to_orm(posting)
        assert orm.company_name == "Acme"
        assert orm.title == "AI Eng"
        assert orm.url == "https://x.com/1"
        assert orm.source_portal == "startup.jobs"

    def test_serializes_lists_to_json(self):
        posting = JobPosting(
            requirements=["Python", "LangChain"],
            preferred=["Neo4j"],
            tech_stack=["FastAPI", "AWS"],
            source_portal=SourcePortal.MANUAL,
        )
        orm = posting_to_orm(posting)
        assert '"Python"' in orm.requirements
        assert '"Neo4j"' in orm.preferred
        assert '"FastAPI"' in orm.tech_stack

    def test_preserves_booleans(self):
        posting = JobPosting(
            h1b_mentioned=True,
            is_easy_apply=True,
            is_top_applicant=False,
            source_portal=SourcePortal.LINKEDIN,
        )
        orm = posting_to_orm(posting)
        assert orm.h1b_mentioned is True
        assert orm.is_easy_apply is True
        assert orm.is_top_applicant is False


# ---------------------------------------------------------------------------
# persist_scan_results
# ---------------------------------------------------------------------------


class TestPersistScanResults:
    def test_inserts_new_postings(self, session):
        postings = [
            JobPosting(
                url="https://x.com/1",
                company_name="Test Co",
                source_portal=SourcePortal.STARTUP_JOBS,
            )
        ]
        found, new, new_co = persist_scan_results(session, "startup.jobs", postings)
        assert found == 1
        assert new == 1
        assert session.query(JobPostingORM).count() == 1

    def test_dedup_by_url(self, session):
        postings = [
            JobPosting(
                url="https://x.com/1",
                source_portal=SourcePortal.STARTUP_JOBS,
            )
        ]
        persist_scan_results(session, "test", postings)
        # Second call with same URL
        found, new, new_co = persist_scan_results(session, "test", postings)
        assert found == 1
        assert new == 0
        assert session.query(JobPostingORM).count() == 1

    def test_creates_scan_record(self, session):
        persist_scan_results(session, "test_portal", [], duration=1.5)
        scan = session.query(ScanORM).first()
        assert scan is not None
        assert scan.portal == "test_portal"
        assert scan.duration_seconds == 1.5
        assert scan.companies_found == 0
        assert scan.new_companies == 0

    def test_scan_record_counts(self, session):
        postings = [
            JobPosting(url="https://a.com/1", source_portal=SourcePortal.AI_JOBS),
            JobPosting(url="https://a.com/2", source_portal=SourcePortal.AI_JOBS),
        ]
        persist_scan_results(session, "AI Jobs", postings)
        scan = session.query(ScanORM).first()
        assert scan.companies_found == 2
        assert scan.new_companies == 2

    def test_empty_url_not_deduped(self, session):
        """Postings with empty URLs should always be inserted."""
        postings = [
            JobPosting(url="", source_portal=SourcePortal.MANUAL),
            JobPosting(url="", source_portal=SourcePortal.MANUAL),
        ]
        found, new, new_co = persist_scan_results(session, "test", postings)
        assert new == 2

    def test_error_recorded_in_scan(self, session):
        persist_scan_results(session, "broken_portal", [], errors="Connection timeout")
        scan = session.query(ScanORM).first()
        assert scan.errors == "Connection timeout"
        assert scan.is_healthy is False

    def test_mixed_new_and_existing(self, session):
        persist_scan_results(
            session,
            "p1",
            [JobPosting(url="https://x.com/existing", source_portal=SourcePortal.MANUAL)],
        )
        postings = [
            JobPosting(url="https://x.com/existing", source_portal=SourcePortal.MANUAL),
            JobPosting(url="https://x.com/new", source_portal=SourcePortal.MANUAL),
        ]
        found, new, new_co = persist_scan_results(session, "p1", postings)
        assert found == 2
        assert new == 1

    def test_new_company_gets_role_url_from_posting(self, session):
        """New companies should get role_url and role from the first posting."""
        postings = [
            JobPosting(
                company_name="FreshCo",
                title="AI Engineer",
                url="https://freshco.com/jobs/1",
                source_portal=SourcePortal.STARTUP_JOBS,
            )
        ]
        persist_scan_results(session, "startup.jobs", postings)
        company = session.query(CompanyORM).filter_by(name="FreshCo").first()
        assert company is not None
        assert company.role_url == "https://freshco.com/jobs/1"
        assert company.role == "AI Engineer"

    def test_existing_company_backfills_empty_role_url(self, session):
        """Existing company with no role_url gets backfilled from new posting."""
        # Pre-create company with no URL
        company = CompanyORM(name="OldCo", stage="To apply", role_url="", role="")
        session.add(company)
        session.flush()

        postings = [
            JobPosting(
                company_name="OldCo",
                title="ML Eng",
                url="https://oldco.com/jobs/ml",
                source_portal=SourcePortal.STARTUP_JOBS,
            )
        ]
        persist_scan_results(session, "startup.jobs", postings)

        session.refresh(company)
        assert company.role_url == "https://oldco.com/jobs/ml"
        assert company.role == "ML Eng"

    def test_existing_company_with_role_url_not_overwritten(self, session):
        """Existing company WITH role_url should NOT be overwritten."""
        company = CompanyORM(
            name="StableCo",
            stage="To apply",
            role_url="https://stableco.com/original",
            role="Original Role",
        )
        session.add(company)
        session.flush()

        postings = [
            JobPosting(
                company_name="StableCo",
                title="New Role",
                url="https://stableco.com/new-posting",
                source_portal=SourcePortal.STARTUP_JOBS,
            )
        ]
        persist_scan_results(session, "startup.jobs", postings)

        session.refresh(company)
        assert company.role_url == "https://stableco.com/original"
        assert company.role == "Original Role"


# ---------------------------------------------------------------------------
# Pipeline.scan_all
# ---------------------------------------------------------------------------


class TestPipelineScanAll:
    @pytest.mark.asyncio
    async def test_scan_all_persists_results(self, session):
        from src.pipeline.orchestrator import Pipeline

        mock_scraper = MagicMock()
        mock_scraper.name = "test_portal"
        mock_scraper.is_healthy.return_value = True
        mock_scraper.search = AsyncMock(
            return_value=[
                JobPosting(
                    url="https://x.com/pipe1",
                    source_portal=SourcePortal.MANUAL,
                )
            ]
        )

        mock_registry = MagicMock()
        mock_registry.get_all_scrapers.return_value = [mock_scraper]

        pipeline = Pipeline(session)
        with patch(
            "src.scrapers.registry.build_default_registry",
            return_value=mock_registry,
        ):
            result = await pipeline.scan_all()

        assert result["total_found"] == 1
        assert result["total_new"] == 1
        assert session.query(JobPostingORM).count() == 1

    @pytest.mark.asyncio
    async def test_scan_all_skips_unhealthy(self, session):
        from src.pipeline.orchestrator import Pipeline

        mock_scraper = MagicMock()
        mock_scraper.name = "down_portal"
        mock_scraper.is_healthy.return_value = False

        mock_registry = MagicMock()
        mock_registry.get_all_scrapers.return_value = [mock_scraper]

        pipeline = Pipeline(session)
        with patch(
            "src.scrapers.registry.build_default_registry",
            return_value=mock_registry,
        ):
            result = await pipeline.scan_all()

        assert result["total_found"] == 0
        assert result["total_new"] == 0

    @pytest.mark.asyncio
    async def test_scan_all_handles_errors(self, session):
        from src.pipeline.orchestrator import Pipeline

        mock_scraper = MagicMock()
        mock_scraper.name = "error_portal"
        mock_scraper.is_healthy.return_value = True
        mock_scraper.search = AsyncMock(side_effect=RuntimeError("Connection failed"))

        mock_registry = MagicMock()
        mock_registry.get_all_scrapers.return_value = [mock_scraper]

        pipeline = Pipeline(session)
        with patch(
            "src.scrapers.registry.build_default_registry",
            return_value=mock_registry,
        ):
            result = await pipeline.scan_all()

        assert result["total_found"] == 0

    @pytest.mark.asyncio
    async def test_scan_all_filters_by_portal(self, session):
        from src.pipeline.orchestrator import Pipeline

        mock_scraper = MagicMock()
        mock_scraper.name = "selected_portal"
        mock_scraper.is_healthy.return_value = True
        mock_scraper.search = AsyncMock(return_value=[])

        mock_registry = MagicMock()
        mock_registry.get_scraper.return_value = mock_scraper

        pipeline = Pipeline(session)
        with patch(
            "src.scrapers.registry.build_default_registry",
            return_value=mock_registry,
        ):
            await pipeline.scan_all(portals=["selected_portal"])

        mock_registry.get_scraper.assert_called_once_with("selected_portal")

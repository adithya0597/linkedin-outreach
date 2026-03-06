"""Tests for stale posting archive system."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, JobPostingORM
from src.validators.quality_gates import QualityAuditor


@pytest.fixture
def archive_session():
    """Session with job postings at various ages."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    company = CompanyORM(name="TestCo", data_completeness=80.0)
    session.add(company)
    session.flush()

    now = datetime.now()

    fresh = JobPostingORM(
        company_id=company.id,
        company_name="TestCo",
        title="AI Engineer",
        discovered_date=now - timedelta(days=5),
        is_active=True,
    )
    stale = JobPostingORM(
        company_id=company.id,
        company_name="TestCo",
        title="ML Engineer",
        discovered_date=now - timedelta(days=45),
        is_active=True,
    )
    archived = JobPostingORM(
        company_id=company.id,
        company_name="TestCo",
        title="Data Scientist",
        discovered_date=now - timedelta(days=60),
        is_active=False,
    )

    session.add_all([fresh, stale, archived])
    session.commit()

    yield session
    session.close()


class TestArchiveStalePostings:
    def test_archives_only_stale_active(self, archive_session):
        """Default 30 days: only 45-day posting archived, fresh stays active,
        already-archived stays inactive."""
        auditor = QualityAuditor(archive_session)
        count = auditor.archive_stale_postings()

        assert count == 1

        postings = archive_session.query(JobPostingORM).all()
        by_title = {p.title: p for p in postings}

        # Fresh posting (5 days) stays active
        assert by_title["AI Engineer"].is_active is True
        # Stale posting (45 days) was archived
        assert by_title["ML Engineer"].is_active is False
        # Already-archived posting stays inactive
        assert by_title["Data Scientist"].is_active is False

    def test_custom_max_days(self, archive_session):
        """max_days=3: both 5d and 45d get archived."""
        auditor = QualityAuditor(archive_session)
        count = auditor.archive_stale_postings(max_days=3)

        assert count == 2

        active = archive_session.query(JobPostingORM).filter(
            JobPostingORM.is_active == True  # noqa: E712
        ).count()
        assert active == 0

    def test_no_stale_postings(self):
        """Session with only fresh postings returns 0."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        company = CompanyORM(name="FreshCo", data_completeness=90.0)
        session.add(company)
        session.flush()

        fresh = JobPostingORM(
            company_id=company.id,
            company_name="FreshCo",
            title="Engineer",
            discovered_date=datetime.now() - timedelta(days=1),
            is_active=True,
        )
        session.add(fresh)
        session.commit()

        auditor = QualityAuditor(session)
        count = auditor.archive_stale_postings()
        assert count == 0

        session.close()

    def test_returns_correct_count(self, archive_session):
        """Return value matches actual archived count."""
        auditor = QualityAuditor(archive_session)
        count = auditor.archive_stale_postings()

        # Only the 45-day active posting should be archived
        assert count == 1

        # Verify by querying: 1 active (fresh), 2 inactive (stale + already-archived)
        inactive = archive_session.query(JobPostingORM).filter(
            JobPostingORM.is_active == False  # noqa: E712
        ).count()
        assert inactive == 2


class TestCheckStaleDataWithPostings:
    def test_includes_stale_postings_in_report(self, archive_session):
        """check_stale_data() reports stale active postings."""
        auditor = QualityAuditor(archive_session)
        issues = auditor.check_stale_data(max_days=30)

        posting_issues = [i for i in issues if "active job postings" in i]
        assert len(posting_issues) == 1
        assert "1 active job postings older than 30 days" in posting_issues[0]

    def test_no_stale_postings_no_extra_issue(self):
        """Fresh postings don't generate extra issue."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        company = CompanyORM(
            name="FreshCo",
            data_completeness=90.0,
            updated_at=datetime.now(),
        )
        session.add(company)
        session.flush()

        fresh = JobPostingORM(
            company_id=company.id,
            company_name="FreshCo",
            title="Engineer",
            discovered_date=datetime.now() - timedelta(days=1),
            is_active=True,
        )
        session.add(fresh)
        session.commit()

        auditor = QualityAuditor(session)
        issues = auditor.check_stale_data(max_days=30)

        posting_issues = [i for i in issues if "active job postings" in i]
        assert len(posting_issues) == 0

        session.close()


class TestSchedulerArchiveJob:
    def test_scheduler_registers_archive_job(self):
        """Mock APScheduler to verify add_job is called with weekly_archive id."""
        mock_scheduler_cls = MagicMock()
        mock_scheduler_instance = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler_instance
        # Make start() raise KeyboardInterrupt to exit the blocking loop
        mock_scheduler_instance.start.side_effect = KeyboardInterrupt

        mock_cron_trigger = MagicMock()

        with patch.dict("sys.modules", {}):
            with patch(
                "apscheduler.schedulers.blocking.BlockingScheduler",
                mock_scheduler_cls,
            ), patch(
                "apscheduler.triggers.cron.CronTrigger",
                mock_cron_trigger,
            ):
                from src.pipeline.scheduler import ScanScheduler

                sched = ScanScheduler.__new__(ScanScheduler)
                sched.config = {
                    "schedules": {
                        "full_scan": {"cron": "0 8 * * *"},
                        "afternoon_rescan": {"cron": "0 14 * * *"},
                    }
                }
                sched.start()

        # Verify 4 add_job calls: full_scan, afternoon_rescan, weekly_archive, followup_alerts
        assert mock_scheduler_instance.add_job.call_count == 4

        # Third call should be weekly_archive
        third_call = mock_scheduler_instance.add_job.call_args_list[2]
        assert third_call.kwargs.get("id") or third_call[1].get("id") == "weekly_archive"
        # Check via keyword args
        call_kwargs = third_call.kwargs if third_call.kwargs else third_call[1]
        assert call_kwargs["id"] == "weekly_archive"
        assert call_kwargs["name"] == "Weekly Stale Posting Archive"

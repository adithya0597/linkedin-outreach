"""Coverage boost tests — quality_gates, scoring_engine, and new CLI commands.

Targets:
  - src/validators/quality_gates.py lines 20-96, 110, 143-183
  - src/validators/scoring_engine.py lines 45-169
  - src/cli/main.py lines 507-619 (archive, portal-scores, health)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from src.cli.main import app
from src.db.orm import Base, CompanyORM, JobPostingORM
from src.models.company import ScoreBreakdown
from src.validators.quality_gates import QualityAuditor
from src.validators.scoring_engine import FitScoringEngine

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qa_session():
    """Session seeded with companies for quality gate testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Skeleton record (data_completeness < 40)
    session.add(CompanyORM(
        name="SkeletonCo",
        description="",
        hq_location="",
        employees=None,
        funding_stage="Unknown",
        data_completeness=15.0,
        is_disqualified=False,
        updated_at=datetime.now(),
    ))

    # Normal company
    session.add(CompanyORM(
        name="HealthyCo",
        description="AI-powered healthcare platform",
        hq_location="San Francisco, CA",
        employees=50,
        funding_stage="Series A",
        data_completeness=90.0,
        is_disqualified=False,
        h1b_status="Confirmed",
        fit_score=85.0,
        is_ai_native=True,
        updated_at=datetime.now(),
    ))

    # Criteria violator: Series D funding
    session.add(CompanyORM(
        name="BigFundingCo",
        description="Over-funded startup",
        hq_location="NYC",
        employees=200,
        funding_stage="Series D",
        data_completeness=80.0,
        is_disqualified=False,
        h1b_status="Unknown",
        updated_at=datetime.now(),
    ))

    # Criteria violator: >1000 employees
    session.add(CompanyORM(
        name="BigCorpCo",
        description="Too many employees",
        hq_location="Seattle, WA",
        employees=1500,
        funding_stage="Series B",
        data_completeness=70.0,
        is_disqualified=False,
        h1b_status="Unknown",
        updated_at=datetime.now(),
    ))

    # Criteria violator: Explicit No H1B
    session.add(CompanyORM(
        name="NoVisaCo",
        description="Does not sponsor",
        hq_location="Austin, TX",
        employees=100,
        funding_stage="Series A",
        data_completeness=75.0,
        is_disqualified=False,
        h1b_status="Explicit No",
        h1b_details="Company policy: no visa sponsorship",
        updated_at=datetime.now(),
    ))

    # Near-duplicate names for fuzzy matching
    session.add(CompanyORM(
        name="Acme AI Inc",
        description="AI platform",
        data_completeness=60.0,
        is_disqualified=False,
        updated_at=datetime.now(),
    ))
    session.add(CompanyORM(
        name="Acme AI Inc.",
        description="AI platform copy",
        data_completeness=60.0,
        is_disqualified=False,
        updated_at=datetime.now(),
    ))

    # Companies with identical fit scores (anomaly detection)
    for i in range(4):
        session.add(CompanyORM(
            name=f"CloneCo_{i}",
            description=f"Clone company {i}",
            data_completeness=50.0,
            is_disqualified=False,
            fit_score=77.0,
            updated_at=datetime.now(),
        ))

    # Stale company (old updated_at)
    session.add(CompanyORM(
        name="StaleCo",
        description="Not updated recently",
        data_completeness=60.0,
        is_disqualified=False,
        updated_at=datetime.now() - timedelta(days=60),
    ))

    session.commit()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Quality Gates Tests
# ---------------------------------------------------------------------------


class TestCheckCompleteness:
    def test_finds_skeleton_records(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_completeness()
        assert any("SkeletonCo" in i for i in issues)
        assert any("SKELETON" in i for i in issues)

    def test_healthy_company_not_flagged(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_completeness()
        assert not any("HealthyCo" in i for i in issues)


class TestCheckDuplicates:
    def test_finds_fuzzy_duplicates(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_duplicates()
        assert any("DUPLICATE" in i for i in issues)
        assert any("Acme AI" in i for i in issues)

    def test_unrelated_names_not_flagged(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_duplicates()
        # SkeletonCo and HealthyCo should NOT be flagged as duplicates
        dupe_names = " ".join(issues)
        assert not ("SkeletonCo" in dupe_names and "HealthyCo" in dupe_names)


class TestCheckCriteriaViolations:
    def test_finds_invalid_funding(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_criteria_violations()
        assert any("BigFundingCo" in i and "Series D" in i for i in issues)

    def test_finds_employee_violation(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_criteria_violations()
        assert any("BigCorpCo" in i and "1500" in i for i in issues)

    def test_finds_h1b_explicit_no(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_criteria_violations()
        assert any("NoVisaCo" in i and "H1B" in i for i in issues)

    def test_healthy_company_passes(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_criteria_violations()
        assert not any("HealthyCo" in i for i in issues)


class TestCheckScoreAnomalies:
    def test_finds_identical_scores(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_score_anomalies()
        assert any("ANOMALY" in i for i in issues)
        assert any("77" in i for i in issues)

    def test_unique_scores_not_flagged(self, qa_session):
        """HealthyCo (score=85) is unique, so it should not appear in anomalies."""
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_score_anomalies()
        assert not any("HealthyCo" in i for i in issues)


class TestCheckStaleData:
    def test_finds_stale_companies(self, qa_session):
        auditor = QualityAuditor(qa_session)
        issues = auditor.check_stale_data(max_days=30)
        assert any("STALE" in i and "companies" in i for i in issues)


class TestFullAudit:
    def test_returns_formatted_report(self, qa_session):
        auditor = QualityAuditor(qa_session)
        report = auditor.full_audit()
        assert "DATA QUALITY AUDIT" in report
        assert "Total companies:" in report
        assert "Total issues:" in report
        assert "Completeness" in report
        assert "Duplicates" in report
        assert "Criteria Violations" in report
        assert "Score Anomalies" in report
        assert "Stale Data" in report

    def test_report_includes_issues(self, qa_session):
        auditor = QualityAuditor(qa_session)
        report = auditor.full_audit()
        # Should have at least some issues from our seeded data
        assert "SKELETON" in report or "DUPLICATE" in report or "CRITERIA" in report


class TestEnforceGate:
    def test_fails_with_zero_threshold(self, qa_session):
        auditor = QualityAuditor(qa_session)
        passed, report = auditor.enforce_gate(threshold=0)
        # We have criteria violations, so threshold=0 should fail
        assert passed is False
        assert "DATA QUALITY AUDIT" in report

    def test_passes_with_high_threshold(self, qa_session):
        auditor = QualityAuditor(qa_session)
        passed, report = auditor.enforce_gate(threshold=100)
        assert passed is True

    def test_returns_report(self, qa_session):
        auditor = QualityAuditor(qa_session)
        _, report = auditor.enforce_gate(threshold=0)
        assert isinstance(report, str)
        assert len(report) > 50


# ---------------------------------------------------------------------------
# Scoring Engine Tests
# ---------------------------------------------------------------------------


class TestScoringEngineDetailed:
    def setup_method(self):
        self.engine = FitScoringEngine()

    def test_h1b_confirmed_scores_15(self):
        company = CompanyORM(name="Test", h1b_status="Confirmed")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.h1b_score == 15

    def test_h1b_likely_scores_8(self):
        company = CompanyORM(name="Test", h1b_status="Likely")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.h1b_score == 8

    def test_h1b_unknown_scores_3(self):
        company = CompanyORM(name="Test", h1b_status="Unknown")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.h1b_score == 3

    def test_h1b_explicit_no_scores_0(self):
        company = CompanyORM(name="Test", h1b_status="Explicit No")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.h1b_score == 0

    def test_h1b_na_scores_12(self):
        company = CompanyORM(name="Test", h1b_status="N/A")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.h1b_score == 12

    def test_employees_under_1000_scores_4(self):
        company = CompanyORM(name="Test", employees=500)
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.criteria_score >= 4

    def test_employees_none_scores_half(self):
        company = CompanyORM(name="Test", employees=None)
        breakdown = self.engine.score_deterministic(company)
        # employees_under_1000 * 0.5 = 4 * 0.5 = 2
        assert breakdown.criteria_score >= 2.0

    def test_valid_funding_stage_adds_points(self):
        company = CompanyORM(name="Test", funding_stage="Series B", employees=100)
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.criteria_score >= 8  # employees_under_1000 + valid_funding

    def test_us_hq_adds_points(self):
        company = CompanyORM(name="Test", hq_location="San Francisco, CA", employees=100, funding_stage="Series A")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.criteria_score >= 11  # employees + funding + us_hq

    def test_ai_native_adds_points(self):
        company = CompanyORM(
            name="Test",
            hq_location="San Francisco, CA",
            employees=100,
            funding_stage="Series A",
            is_ai_native=True,
        )
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.criteria_score == 15  # Max criteria

    def test_tech_overlap_with_keywords(self):
        company = CompanyORM(
            name="Test",
            description="We use python langchain neo4j rag llm fastapi",
        )
        breakdown = self.engine.score_deterministic(company)
        # 6 keywords * 1.5 = 9, capped at 10
        assert breakdown.tech_overlap_score >= 9.0

    def test_tech_overlap_capped_at_max(self):
        company = CompanyORM(
            name="Test",
            description="python langchain neo4j milvus fastapi aws java rag llm nlp knowledge graph vector kafka docker kubernetes",
        )
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.tech_overlap_score == 10

    def test_tech_overlap_no_match(self):
        company = CompanyORM(
            name="Test",
            description="We make traditional pottery with no technology",
        )
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.tech_overlap_score == 0

    def test_salary_full_overlap(self):
        # Range 150K-280K target. Need >50% overlap for full_overlap=10.
        # $150,000 - $280,000 has ratio = 1.0 => full overlap
        company = CompanyORM(name="Test", salary_range="$150,000 - $280,000")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.salary_score == 10

    def test_salary_partial_overlap(self):
        company = CompanyORM(name="Test", salary_range="$100K - $160K")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.salary_score == 6

    def test_salary_out_of_range(self):
        company = CompanyORM(name="Test", salary_range="$40,000 - $60,000")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.salary_score == 2

    def test_salary_no_data(self):
        company = CompanyORM(name="Test", salary_range="")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.salary_score == 5  # Benefit of doubt

    def test_salary_none(self):
        company = CompanyORM(name="Test", salary_range=None)
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.salary_score == 5

    def test_salary_single_number_only(self):
        """Salary with only one number (e.g. '$150K') should get no_data score."""
        company = CompanyORM(name="Test", salary_range="$150K")
        breakdown = self.engine.score_deterministic(company)
        assert breakdown.salary_score == 5  # no_data

    def test_salary_in_thousands(self):
        """Salary in K format like '150K - 280K' should be normalized."""
        company = CompanyORM(name="Test", salary_range="$150K - $280K")
        breakdown = self.engine.score_deterministic(company)
        # 150K-280K maps to 150000-280000 after normalization, full overlap
        assert breakdown.salary_score == 10

    def test_score_includes_deterministic_only_by_default(self):
        company = CompanyORM(name="Test", h1b_status="Confirmed")
        breakdown = self.engine.score(company)
        assert breakdown.profile_jd_similarity == 0.0
        assert breakdown.domain_company_similarity == 0.0

    def test_score_with_semantic_false(self):
        company = CompanyORM(name="Test", h1b_status="Confirmed")
        breakdown = self.engine.score(company, include_semantic=False)
        assert breakdown.semantic_total == 0.0

    def test_score_with_semantic_import_error(self):
        """When sentence-transformers is not installed, embedding scores are skipped but domain match still runs."""
        company = CompanyORM(
            name="Test",
            h1b_status="Confirmed",
            description="AI platform using LLMs",
        )
        with patch.dict("sys.modules", {"src.validators.embeddings": None}):
            # This should not raise, just skip embedding-based semantic scoring
            breakdown = self.engine.score(company, include_semantic=True)
            assert breakdown.profile_jd_similarity == 0.0
            assert breakdown.domain_company_similarity == 0.0

    def test_batch_score_sorted_descending(self):
        companies = [
            CompanyORM(name="Low", h1b_status="Explicit No"),
            CompanyORM(name="High", h1b_status="Confirmed", employees=50,
                       funding_stage="Series A", hq_location="SF", is_ai_native=True),
        ]
        results = self.engine.batch_score(companies)
        assert len(results) == 2
        assert results[0][0].name == "High"
        assert results[1][0].name == "Low"
        assert results[0][1].total >= results[1][1].total


# ---------------------------------------------------------------------------
# CLI Tests — archive, portal-scores, health commands
# ---------------------------------------------------------------------------


class TestArchiveCommand:
    def test_dry_run_shows_count(self):
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.db.database.init_db"),
        ):
            mock_q = MagicMock()
            mock_q.filter.return_value.count.return_value = 7
            mock_session.return_value.query.return_value = mock_q

            result = runner.invoke(app, ["archive", "--dry-run"])
            assert result.exit_code == 0
            assert "7" in result.output
            assert "dry run" in result.output

    def test_archive_executes(self):
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.validators.quality_gates.QualityAuditor") as mock_auditor,
        ):
            mock_auditor.return_value.archive_stale_postings.return_value = 5
            result = runner.invoke(app, ["archive"])
            assert result.exit_code == 0
            assert "Archived 5" in result.output

    def test_archive_custom_max_days(self):
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.validators.quality_gates.QualityAuditor") as mock_auditor,
        ):
            mock_auditor.return_value.archive_stale_postings.return_value = 2
            result = runner.invoke(app, ["archive", "--max-days", "14"])
            assert result.exit_code == 0
            mock_auditor.return_value.archive_stale_postings.assert_called_once_with(max_days=14)


class TestPortalScoresCommand:
    def test_scores_displayed(self):
        mock_score = MagicMock()
        mock_score.portal = "jobright"
        mock_score.velocity_score = 2
        mock_score.afternoon_delta_score = 1
        mock_score.conversion_score = 2
        mock_score.total = 5
        mock_score.recommendation = "promote"

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.validators.portal_scorer.PortalScorer") as mock_scorer_cls,
        ):
            mock_scorer_cls.return_value.score_all.return_value = [mock_score]
            result = runner.invoke(app, ["portal-scores"])
            assert result.exit_code == 0
            assert "jobright" in result.output
            assert "PROMOTE" in result.output

    def test_empty_scores(self):
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.validators.portal_scorer.PortalScorer") as mock_scorer_cls,
        ):
            mock_scorer_cls.return_value.score_all.return_value = []
            result = runner.invoke(app, ["portal-scores"])
            assert result.exit_code == 0
            assert "No scan data" in result.output

    def test_demote_recommendation(self):
        mock_score = MagicMock()
        mock_score.portal = "builtin"
        mock_score.velocity_score = 0
        mock_score.afternoon_delta_score = 0
        mock_score.conversion_score = 0
        mock_score.total = 0
        mock_score.recommendation = "demote"

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.validators.portal_scorer.PortalScorer") as mock_scorer_cls,
        ):
            mock_scorer_cls.return_value.score_all.return_value = [mock_score]
            result = runner.invoke(app, ["portal-scores"])
            assert result.exit_code == 0
            assert "DEMOTE" in result.output


class TestHealthCommand:
    def test_health_displayed(self):
        mock_health = MagicMock()
        mock_health.portal = "jobright"
        mock_health.consecutive_failures = 0
        mock_health.is_healthy = True
        mock_health.last_success = datetime(2026, 3, 5, 8, 0, 0)
        mock_health.last_failure = None
        mock_health.alert_triggered = False

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.pipeline.health_monitor.HealthMonitor") as mock_monitor_cls,
        ):
            mock_monitor_cls.return_value.check_all.return_value = [mock_health]
            result = runner.invoke(app, ["health"])
            assert result.exit_code == 0
            assert "jobright" in result.output
            assert "Healthy" in result.output

    def test_health_empty(self):
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.pipeline.health_monitor.HealthMonitor") as mock_monitor_cls,
        ):
            mock_monitor_cls.return_value.check_all.return_value = []
            result = runner.invoke(app, ["health"])
            assert result.exit_code == 0
            assert "No scan data" in result.output

    def test_health_with_alerts(self):
        healthy = MagicMock()
        healthy.portal = "jobright"
        healthy.consecutive_failures = 0
        healthy.is_healthy = True
        healthy.last_success = datetime(2026, 3, 5, 8, 0, 0)
        healthy.last_failure = None
        healthy.alert_triggered = False

        unhealthy = MagicMock()
        unhealthy.portal = "builtin"
        unhealthy.consecutive_failures = 5
        unhealthy.is_healthy = False
        unhealthy.last_success = datetime(2026, 3, 1, 8, 0, 0)
        unhealthy.last_failure = datetime(2026, 3, 5, 14, 0, 0)
        unhealthy.alert_triggered = True

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.pipeline.health_monitor.HealthMonitor") as mock_monitor_cls,
        ):
            mock_monitor_cls.return_value.check_all.return_value = [healthy, unhealthy]
            result = runner.invoke(app, ["health"])
            assert result.exit_code == 0
            assert "UNHEALTHY" in result.output
            assert "need attention" in result.output

    def test_health_unhealthy_with_none_dates(self):
        """Portal with no last_success or last_failure (None dates)."""
        mock_health = MagicMock()
        mock_health.portal = "new_portal"
        mock_health.consecutive_failures = 0
        mock_health.is_healthy = True
        mock_health.last_success = None
        mock_health.last_failure = None
        mock_health.alert_triggered = False

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.pipeline.health_monitor.HealthMonitor") as mock_monitor_cls,
        ):
            mock_monitor_cls.return_value.check_all.return_value = [mock_health]
            result = runner.invoke(app, ["health"])
            assert result.exit_code == 0
            assert "N/A" in result.output

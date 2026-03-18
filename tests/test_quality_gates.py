"""Tests for field completeness, configurable staleness, and quality gate logic."""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.config.enums import FundingStage, H1BStatus
from src.models.company import Company, CompletenessResult
from src.pipeline.quality_gates import (
    QualityReport,
    get_quality_report,
    is_outreach_ready,
    is_stale,
    load_stale_thresholds,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture()
def empty_company() -> Company:
    """A Company with every field at its default (empty) value."""
    return Company()


@pytest.fixture()
def full_company() -> Company:
    """A Company with all 15 completeness fields populated."""
    return Company(
        name="Acme AI",
        website="https://acme.ai",
        linkedin_url="https://linkedin.com/company/acme",
        employees_range="50-100",
        funding_stage=FundingStage.SERIES_A,
        funding_amount="$10M",
        hiring_manager="Jane Doe",
        role_url="https://acme.ai/jobs/1",
        h1b_status=H1BStatus.CONFIRMED,
        salary_range="$150k-$200k",
        tech_stack=["Python", "LangChain"],
        differentiators=["RAG pipeline", "Agent infra"],
        ai_nativity="AI-native",
        headquarters_city="San Francisco",
        headquarters_state="CA",
    )


@pytest.fixture()
def partial_company() -> Company:
    """A Company with 9 of 15 fields filled (0.6 score exactly)."""
    return Company(
        name="Half Inc",
        website="https://half.io",
        linkedin_url="https://linkedin.com/company/half",
        employees_range="10-50",
        funding_stage=FundingStage.SEED,
        funding_amount="$2M",
        hiring_manager="John Smith",
        role_url="https://half.io/careers/42",
        h1b_status=H1BStatus.LIKELY,
        # These 6 are intentionally left empty:
        # salary_range, tech_stack, differentiators,
        # ai_nativity, headquarters_city, headquarters_state
    )


@pytest.fixture()
def tmp_portals_yaml(tmp_path: Path) -> Path:
    """Create a minimal portals.yaml in a temp dir and return its path."""
    content = textwrap.dedent("""\
        default_stale_after_days: 30
        portals:
          ashby:
            name: "Ashby"
            stale_after_days: 14
          linkedin:
            name: "LinkedIn"
            stale_after_days: 7
          wellfound:
            name: "Wellfound"
            # no stale_after_days -> inherits default 30
    """)
    p = tmp_path / "portals.yaml"
    p.write_text(content)
    return p


# =========================================================================
# 1. Completeness Calculation
# =========================================================================


class TestCalculateCompleteness:
    """Tests for Company.calculate_completeness()."""

    def test_all_fields_empty(self, empty_company: Company) -> None:
        result = empty_company.calculate_completeness()
        assert isinstance(result, CompletenessResult)
        assert result.score == 0.0
        assert len(result.missing_fields) == 15

    def test_all_fields_filled(self, full_company: Company) -> None:
        result = full_company.calculate_completeness()
        assert result.score == 1.0
        assert result.missing_fields == []

    def test_partial_fields(self, partial_company: Company) -> None:
        result = partial_company.calculate_completeness()
        assert result.score == pytest.approx(9 / 15, abs=0.001)
        assert len(result.missing_fields) == 6
        # The six missing ones
        for expected_missing in [
            "salary_range",
            "tech_stack",
            "differentiators",
            "ai_nativity",
            "headquarters_city",
            "headquarters_state",
        ]:
            assert expected_missing in result.missing_fields

    def test_score_is_between_0_and_1(self) -> None:
        for n_filled in range(16):
            c = Company()
            # Fill n fields in order
            fields_to_fill = [
                ("name", "X"),
                ("website", "https://x.com"),
                ("linkedin_url", "https://linkedin.com/company/x"),
                ("employees_range", "10-50"),
                ("funding_stage", FundingStage.SERIES_B),
                ("funding_amount", "$5M"),
                ("hiring_manager", "Person"),
                ("role_url", "https://x.com/j/1"),
                ("h1b_status", H1BStatus.CONFIRMED),
                ("salary_range", "$100k"),
                ("tech_stack", ["Python"]),
                ("differentiators", ["fast"]),
                ("ai_nativity", "AI-native"),
                ("headquarters_city", "NYC"),
                ("headquarters_state", "NY"),
            ]
            for fname, val in fields_to_fill[:n_filled]:
                setattr(c, fname, val)
            result = c.calculate_completeness()
            assert 0.0 <= result.score <= 1.0

    def test_data_completeness_backward_compat(self, full_company: Company) -> None:
        """data_completeness (0-100 scale) is still set for backward compat."""
        full_company.calculate_completeness()
        assert full_company.data_completeness == 100.0

    def test_data_completeness_empty(self, empty_company: Company) -> None:
        empty_company.calculate_completeness()
        assert empty_company.data_completeness == 0.0

    def test_whitespace_only_treated_as_empty(self) -> None:
        c = Company(name="   ", website="  \t  ")
        result = c.calculate_completeness()
        assert "name" in result.missing_fields
        assert "website" in result.missing_fields

    def test_empty_list_treated_as_empty(self) -> None:
        c = Company(tech_stack=[], differentiators=[])
        result = c.calculate_completeness()
        assert "tech_stack" in result.missing_fields
        assert "differentiators" in result.missing_fields

    def test_funding_stage_unknown_treated_as_empty(self) -> None:
        c = Company(funding_stage=FundingStage.UNKNOWN)
        result = c.calculate_completeness()
        assert "funding_stage" in result.missing_fields

    def test_h1b_unknown_treated_as_empty(self) -> None:
        c = Company(h1b_status=H1BStatus.UNKNOWN)
        result = c.calculate_completeness()
        assert "h1b_status" in result.missing_fields

    def test_h1b_explicit_no_still_counted_as_present(self) -> None:
        """EXPLICIT_NO is a valid known status, not 'missing'."""
        c = Company(h1b_status=H1BStatus.EXPLICIT_NO)
        result = c.calculate_completeness()
        assert "h1b_status" not in result.missing_fields

    def test_result_is_namedtuple(self, full_company: Company) -> None:
        result = full_company.calculate_completeness()
        score, missing = result
        assert score == 1.0
        assert missing == []

    def test_exactly_15_completeness_fields(self) -> None:
        c = Company()
        assert len(c.COMPLETENESS_FIELDS) == 15


# =========================================================================
# 2. Configurable Stale Thresholds
# =========================================================================


class TestStaleThresholds:
    """Tests for load_stale_thresholds and is_stale."""

    def test_load_from_yaml(self, tmp_portals_yaml: Path) -> None:
        thresholds = load_stale_thresholds(tmp_portals_yaml)
        assert thresholds["ashby"] == 14
        assert thresholds["linkedin"] == 7
        assert thresholds["wellfound"] == 30  # inherits default

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        thresholds = load_stale_thresholds(tmp_path / "nonexistent.yaml")
        assert thresholds == {}

    def test_is_stale_within_threshold(self, tmp_portals_yaml: Path) -> None:
        now = datetime(2026, 3, 10, 12, 0)
        recent = now - timedelta(days=5)
        assert not is_stale("ashby", recent, now=now, config_path=tmp_portals_yaml)

    def test_is_stale_beyond_threshold(self, tmp_portals_yaml: Path) -> None:
        now = datetime(2026, 3, 10, 12, 0)
        old = now - timedelta(days=15)
        assert is_stale("ashby", old, now=now, config_path=tmp_portals_yaml)

    def test_is_stale_exactly_at_threshold(self, tmp_portals_yaml: Path) -> None:
        now = datetime(2026, 3, 10, 12, 0)
        boundary = now - timedelta(days=14)
        # timedelta(days=14) == timedelta(days=14), NOT greater — so not stale
        assert not is_stale("ashby", boundary, now=now, config_path=tmp_portals_yaml)

    def test_is_stale_unknown_portal_uses_default(self, tmp_portals_yaml: Path) -> None:
        now = datetime(2026, 3, 10, 12, 0)
        old = now - timedelta(days=31)
        assert is_stale("unknown_portal", old, now=now, config_path=tmp_portals_yaml)

    def test_is_stale_unknown_portal_within_default(self, tmp_portals_yaml: Path) -> None:
        now = datetime(2026, 3, 10, 12, 0)
        recent = now - timedelta(days=20)
        assert not is_stale("unknown_portal", recent, now=now, config_path=tmp_portals_yaml)

    def test_custom_default_in_yaml(self, tmp_path: Path) -> None:
        content = textwrap.dedent("""\
            default_stale_after_days: 60
            portals:
              foo:
                name: "Foo"
        """)
        p = tmp_path / "portals.yaml"
        p.write_text(content)
        thresholds = load_stale_thresholds(p)
        assert thresholds["foo"] == 60

    def test_linkedin_short_staleness(self, tmp_portals_yaml: Path) -> None:
        now = datetime(2026, 3, 10, 12, 0)
        eight_days_ago = now - timedelta(days=8)
        assert is_stale("linkedin", eight_days_ago, now=now, config_path=tmp_portals_yaml)

    def test_linkedin_not_stale(self, tmp_portals_yaml: Path) -> None:
        now = datetime(2026, 3, 10, 12, 0)
        five_days_ago = now - timedelta(days=5)
        assert not is_stale("linkedin", five_days_ago, now=now, config_path=tmp_portals_yaml)


# =========================================================================
# 3. Outreach Readiness Gate
# =========================================================================


class TestIsOutreachReady:
    """Tests for is_outreach_ready()."""

    def test_fully_qualified(self, full_company: Company) -> None:
        assert is_outreach_ready(full_company) is True

    def test_empty_company_not_ready(self, empty_company: Company) -> None:
        assert is_outreach_ready(empty_company) is False

    def test_h1b_denied_blocks(self, full_company: Company) -> None:
        full_company.h1b_status = H1BStatus.EXPLICIT_NO
        assert is_outreach_ready(full_company) is False

    def test_no_hiring_manager_blocks(self, full_company: Company) -> None:
        full_company.hiring_manager = ""
        assert is_outreach_ready(full_company) is False

    def test_whitespace_hiring_manager_blocks(self, full_company: Company) -> None:
        full_company.hiring_manager = "   "
        assert is_outreach_ready(full_company) is False

    def test_low_completeness_blocks(self) -> None:
        # Only 5/15 fields => 0.333 < 0.6
        c = Company(
            name="LowData Co",
            website="https://low.com",
            linkedin_url="https://linkedin.com/company/low",
            employees_range="5-10",
            funding_stage=FundingStage.SEED,
            hiring_manager="Person",
            h1b_status=H1BStatus.CONFIRMED,
        )
        # 7/15 ~ 0.467 — still under 0.6
        assert is_outreach_ready(c) is False

    def test_exactly_0_6_passes(self, partial_company: Company) -> None:
        # partial_company has 9/15 = 0.6
        assert is_outreach_ready(partial_company) is True

    def test_h1b_unknown_still_passes(self, partial_company: Company) -> None:
        """Unknown H1B is NOT denied — should not block outreach."""
        partial_company.h1b_status = H1BStatus.UNKNOWN
        # But now h1b_status counts as empty, so completeness drops to 8/15 = 0.533
        assert is_outreach_ready(partial_company) is False

    def test_h1b_likely_passes(self, full_company: Company) -> None:
        full_company.h1b_status = H1BStatus.LIKELY
        assert is_outreach_ready(full_company) is True

    def test_h1b_not_applicable_passes(self, full_company: Company) -> None:
        full_company.h1b_status = H1BStatus.NOT_APPLICABLE
        assert is_outreach_ready(full_company) is True


# =========================================================================
# 4. Quality Report
# =========================================================================


class TestGetQualityReport:
    """Tests for get_quality_report()."""

    def test_empty_list(self) -> None:
        report = get_quality_report([])
        assert report.total_companies == 0
        assert report.avg_completeness == 0.0
        assert report.bucket_0_25 == 0

    def test_single_full_company(self, full_company: Company) -> None:
        report = get_quality_report([full_company])
        assert report.total_companies == 1
        assert report.avg_completeness == 1.0
        assert report.bucket_75_100 == 1
        assert report.most_common_missing == []

    def test_single_empty_company(self, empty_company: Company) -> None:
        report = get_quality_report([empty_company])
        assert report.total_companies == 1
        assert report.avg_completeness == 0.0
        assert report.bucket_0_25 == 1
        assert len(report.most_common_missing) == 15

    def test_mixed_companies(
        self,
        full_company: Company,
        empty_company: Company,
        partial_company: Company,
    ) -> None:
        report = get_quality_report([full_company, empty_company, partial_company])
        assert report.total_companies == 3
        # avg: (1.0 + 0.0 + 0.6) / 3 = 0.5333
        assert 0.53 < report.avg_completeness < 0.54
        # full -> 75-100 bucket, empty -> 0-25, partial (0.6=60%) -> 50-75
        assert report.bucket_75_100 == 1
        assert report.bucket_0_25 == 1
        assert report.bucket_50_75 == 1
        assert report.bucket_25_50 == 0

    def test_most_common_missing_sorted(self, empty_company: Company, full_company: Company) -> None:
        report = get_quality_report([empty_company, full_company])
        # For the 2-company set, each of the 15 fields is missing in the empty one
        # So all 15 fields are equally common (count=1 each)
        assert len(report.most_common_missing) == 15
        # All counts should be 1
        for _field, count in report.most_common_missing:
            assert count == 1

    def test_report_type(self) -> None:
        report = get_quality_report([])
        assert isinstance(report, QualityReport)

    def test_buckets_sum_to_total(
        self,
        full_company: Company,
        empty_company: Company,
        partial_company: Company,
    ) -> None:
        companies = [full_company, empty_company, partial_company]
        report = get_quality_report(companies)
        total = (
            report.bucket_0_25
            + report.bucket_25_50
            + report.bucket_50_75
            + report.bucket_75_100
        )
        assert total == report.total_companies

    def test_all_same_completeness(self) -> None:
        """All companies identical -> single bucket, uniform average."""
        companies = [
            Company(
                name="Clone",
                website="https://clone.com",
                hiring_manager="HM",
            )
            for _ in range(5)
        ]
        report = get_quality_report(companies)
        assert report.total_companies == 5
        # 3/15 = 0.2 => all in 0-25% bucket
        assert report.bucket_0_25 == 5

    def test_most_common_missing_order(self) -> None:
        """Field missing from MORE companies appears first."""
        c1 = Company(name="A")  # missing: website + 13 others
        c2 = Company(name="B", website="https://b.com")  # missing: 13 others (not website)
        report = get_quality_report([c1, c2])
        missing_names = [f for f, _ in report.most_common_missing]
        # "website" is missing only in c1, so it's at count=1
        # All other 13 fields are missing in both, so count=2
        top_fields = [f for f, count in report.most_common_missing if count == 2]
        bottom_fields = [f for f, count in report.most_common_missing if count == 1]
        assert "website" in bottom_fields
        assert "name" not in missing_names  # both have name
        assert len(top_fields) == 13


# =========================================================================
# 5. CLI completeness-report command
# =========================================================================


class TestCompletenessReportCLI:
    """Tests for the completeness-report CLI command."""

    def test_completeness_report_renders(self, full_company, empty_company, partial_company, tmp_path, monkeypatch):
        """The completeness-report command renders without errors."""
        from unittest.mock import MagicMock, patch

        from typer.testing import CliRunner

        from src.cli.system_commands import app

        runner = CliRunner()

        # Mock the db_session to return our test companies as ORM-like objects
        mock_orm_rows = []
        for c in [full_company, empty_company, partial_company]:
            orm = MagicMock()
            orm.id = c.id
            orm.name = c.name
            orm.description = c.description
            orm.hq_location = c.hq_location
            orm.employees = c.employees
            orm.employees_range = c.employees_range
            orm.funding_stage = c.funding_stage.value if hasattr(c.funding_stage, "value") else str(c.funding_stage)
            orm.funding_amount = c.funding_amount
            orm.total_raised = c.total_raised
            orm.valuation = c.valuation
            orm.founded_year = c.founded_year
            orm.website = c.website
            orm.careers_url = c.careers_url
            orm.linkedin_url = c.linkedin_url
            orm.is_ai_native = c.is_ai_native
            orm.ai_product_description = c.ai_product_description
            orm.tier = c.tier.value if hasattr(c.tier, "value") else str(c.tier)
            orm.source_portal = c.source_portal.value if hasattr(c.source_portal, "value") else str(c.source_portal)
            orm.h1b_status = c.h1b_status.value if hasattr(c.h1b_status, "value") else str(c.h1b_status)
            orm.h1b_source = c.h1b_source
            orm.h1b_details = c.h1b_details
            orm.fit_score = c.fit_score
            orm.stage = c.stage.value if hasattr(c.stage, "value") else str(c.stage)
            orm.validation_result = c.validation_result.value if c.validation_result and hasattr(c.validation_result, "value") else None
            orm.validation_notes = c.validation_notes
            orm.differentiators = "|".join(c.differentiators) if c.differentiators else ""
            orm.role = c.role
            orm.role_url = c.role_url
            orm.salary_range = c.salary_range
            orm.notes = c.notes
            orm.hiring_manager = c.hiring_manager
            orm.hiring_manager_linkedin = c.hiring_manager_linkedin
            orm.why_fit = c.why_fit
            orm.best_stats = c.best_stats
            orm.action = c.action
            orm.is_disqualified = c.is_disqualified
            orm.disqualification_reason = c.disqualification_reason
            orm.needs_review = c.needs_review
            orm.data_completeness = c.data_completeness
            mock_orm_rows.append(orm)

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = mock_orm_rows
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("src.cli._db.db_session", return_value=mock_session):
            result = runner.invoke(app, ["completeness-report"])

        assert result.exit_code == 0
        assert "Completeness Summary" in result.output
        assert "Distribution" in result.output
        assert "Top 10 Missing Fields" in result.output

    def test_completeness_report_min_score_flag(self, full_company, empty_company, tmp_path, monkeypatch):
        """The --min-score flag filters companies below the threshold."""
        from unittest.mock import MagicMock, patch

        from typer.testing import CliRunner

        from src.cli.system_commands import app

        runner = CliRunner()

        # Create ORM mocks
        mock_orm_rows = []
        for c in [full_company, empty_company]:
            orm = MagicMock()
            orm.id = c.id
            orm.name = c.name
            orm.description = c.description
            orm.hq_location = c.hq_location
            orm.employees = c.employees
            orm.employees_range = c.employees_range
            orm.funding_stage = c.funding_stage.value if hasattr(c.funding_stage, "value") else str(c.funding_stage)
            orm.funding_amount = c.funding_amount
            orm.total_raised = c.total_raised
            orm.valuation = c.valuation
            orm.founded_year = c.founded_year
            orm.website = c.website
            orm.careers_url = c.careers_url
            orm.linkedin_url = c.linkedin_url
            orm.is_ai_native = c.is_ai_native
            orm.ai_product_description = c.ai_product_description
            orm.tier = c.tier.value if hasattr(c.tier, "value") else str(c.tier)
            orm.source_portal = c.source_portal.value if hasattr(c.source_portal, "value") else str(c.source_portal)
            orm.h1b_status = c.h1b_status.value if hasattr(c.h1b_status, "value") else str(c.h1b_status)
            orm.h1b_source = c.h1b_source
            orm.h1b_details = c.h1b_details
            orm.fit_score = c.fit_score
            orm.stage = c.stage.value if hasattr(c.stage, "value") else str(c.stage)
            orm.validation_result = c.validation_result.value if c.validation_result and hasattr(c.validation_result, "value") else None
            orm.validation_notes = c.validation_notes
            orm.differentiators = "|".join(c.differentiators) if c.differentiators else ""
            orm.role = c.role
            orm.role_url = c.role_url
            orm.salary_range = c.salary_range
            orm.notes = c.notes
            orm.hiring_manager = c.hiring_manager
            orm.hiring_manager_linkedin = c.hiring_manager_linkedin
            orm.why_fit = c.why_fit
            orm.best_stats = c.best_stats
            orm.action = c.action
            orm.is_disqualified = c.is_disqualified
            orm.disqualification_reason = c.disqualification_reason
            orm.needs_review = c.needs_review
            orm.data_completeness = c.data_completeness
            mock_orm_rows.append(orm)

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = mock_orm_rows
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("src.cli._db.db_session", return_value=mock_session):
            result = runner.invoke(app, ["completeness-report", "--min-score", "0.5"])

        assert result.exit_code == 0
        # The empty company (0% completeness) should appear in the "below threshold" table
        assert "Below" in result.output or "below" in result.output

    def test_orm_to_company_conversion(self):
        """_orm_to_company correctly converts mock ORM to Company dataclass."""
        from unittest.mock import MagicMock

        from src.cli.system_commands import _orm_to_company
        from src.config.enums import FundingStage, H1BStatus

        orm = MagicMock()
        orm.id = 42
        orm.name = "TestCo"
        orm.description = "An AI company"
        orm.hq_location = "SF"
        orm.employees = 50
        orm.employees_range = "10-100"
        orm.funding_stage = "Series A"
        orm.funding_amount = "$10M"
        orm.total_raised = "$15M"
        orm.valuation = "$100M"
        orm.founded_year = 2022
        orm.website = "https://testco.ai"
        orm.careers_url = "https://testco.ai/careers"
        orm.linkedin_url = "https://linkedin.com/company/testco"
        orm.is_ai_native = True
        orm.ai_product_description = "AI platform"
        orm.tier = "Tier 5 - RESCAN"
        orm.source_portal = "Manual"
        orm.h1b_status = "Confirmed"
        orm.h1b_source = "froghire"
        orm.h1b_details = "5 LCAs"
        orm.fit_score = 72.5
        orm.stage = "To apply"
        orm.validation_result = None
        orm.validation_notes = ""
        orm.differentiators = "RAG|Agents"
        orm.role = "AI Engineer"
        orm.role_url = "https://testco.ai/jobs/1"
        orm.salary_range = "$150k-$200k"
        orm.notes = ""
        orm.hiring_manager = "Jane Doe"
        orm.hiring_manager_linkedin = "https://linkedin.com/in/janedoe"
        orm.why_fit = "Strong fit"
        orm.best_stats = ""
        orm.action = ""
        orm.is_disqualified = False
        orm.disqualification_reason = ""
        orm.needs_review = False
        orm.data_completeness = 80.0

        company = _orm_to_company(orm)

        assert company.id == 42
        assert company.name == "TestCo"
        assert company.funding_stage == FundingStage.SERIES_A
        assert company.h1b_status == H1BStatus.CONFIRMED
        assert company.differentiators == ["RAG", "Agents"]
        assert company.hiring_manager == "Jane Doe"
        # Verify completeness calculation works on the converted object
        result = company.calculate_completeness()
        assert 0.0 <= result.score <= 1.0

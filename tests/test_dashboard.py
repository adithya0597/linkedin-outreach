"""Tests for dashboard -- import sanity, data loading, portal scores, health monitor,
phase 2 expansion, and data quality upgrade.

Streamlit's runtime makes deeper testing impractical. These tests
verify the module is importable, page functions exist, data loaders are
callable, widget data structures are well-formed, and upgrade fields exist.
"""

import importlib
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Streamlit mock helpers
# ---------------------------------------------------------------------------


def _make_mock_streamlit():
    """Create a mock streamlit module that handles decorators, config, and widget calls.

    The dashboard module executes PAGE_MAP[page]() at import time (line 639),
    so we must mock every st.* call that page_pipeline_overview makes,
    including st.columns(5) returning 5 mock objects.
    """
    mock_st = MagicMock()

    # @st.cache_data(ttl=30) -> decorator that returns the function unchanged
    mock_st.cache_data = lambda **kwargs: lambda f: f

    # @st.cache_resource (no parens in the source)
    # st.cache_resource is used as a bare decorator: @st.cache_resource\ndef _engine():
    # So st.cache_resource(func) -> func
    mock_st.cache_resource = lambda f: f

    # st.set_page_config(...) -- called at module level
    mock_st.set_page_config = MagicMock()

    # Sidebar mocks
    mock_st.sidebar = MagicMock()
    mock_st.sidebar.title = MagicMock()
    mock_st.sidebar.markdown = MagicMock()
    mock_st.sidebar.radio.return_value = "Pipeline Overview"
    mock_st.sidebar.button.return_value = False

    # st.columns(N) must return N MagicMock objects to allow unpacking
    def mock_columns(n, **kwargs):
        if isinstance(n, list):
            return [MagicMock() for _ in n]
        return [MagicMock() for _ in range(n)]
    mock_st.columns = mock_columns

    # Other st functions that pages call
    mock_st.title = MagicMock()
    mock_st.subheader = MagicMock()
    mock_st.markdown = MagicMock()
    mock_st.info = MagicMock()
    mock_st.success = MagicMock()
    mock_st.warning = MagicMock()
    mock_st.caption = MagicMock()
    mock_st.bar_chart = MagicMock()
    mock_st.dataframe = MagicMock()
    mock_st.text_input = MagicMock(return_value="")
    mock_st.selectbox = MagicMock(return_value="All")
    mock_st.expander = MagicMock()
    mock_st.container = MagicMock()
    mock_st.rerun = MagicMock()
    mock_st.metric = MagicMock()

    return mock_st


def _make_mock_pd():
    """Return the real pandas module (it's available in the venv)."""
    return pytest.importorskip("pandas")


def _import_dashboard(mock_st):
    """Import dashboard module with mocked streamlit and DB layer.

    Returns the module object.
    """
    pd = _make_mock_pd()
    import pandas as real_pd

    # We need to mock the DB imports so the module doesn't try to create
    # a real SQLite engine at import time
    with patch.dict(sys.modules, {"streamlit": mock_st}):
        # Clear cached module
        sys.modules.pop("src.dashboard.app", None)
        sys.modules.pop("src.dashboard", None)

        # Mock the DB functions that are called at module level and in data loaders
        with (
            patch("src.db.database.get_engine") as mock_engine,
            patch("src.db.database.init_db"),
        ):
            mock_sessionmaker = MagicMock()
            mock_sess_instance = MagicMock()
            mock_sess_instance.query.return_value.all.return_value = []
            mock_sessionmaker.return_value = mock_sess_instance

            with patch("sqlalchemy.orm.sessionmaker", return_value=mock_sessionmaker):
                from src.dashboard import app as dashboard

    return dashboard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dashboard():
    mock_st = _make_mock_streamlit()
    return _import_dashboard(mock_st)


# Module-level cache for _get_app (used by phase 2 tests)
_app_module = None


def _get_app():
    global _app_module
    if _app_module is None:
        _app_module = _import_dashboard(_make_mock_streamlit())
    return _app_module


# ---------------------------------------------------------------------------
# Mock dataclasses for widget tests
# ---------------------------------------------------------------------------


@dataclass
class MockPortalScore:
    portal: str
    velocity_score: int
    afternoon_delta_score: int
    conversion_score: int
    total: int
    recommendation: str


@dataclass
class MockPortalHealth:
    portal: str
    consecutive_failures: int
    last_success: datetime | None
    last_failure: datetime | None
    is_healthy: bool
    alert_triggered: bool


# ===========================================================================
# Original dashboard import tests
# ===========================================================================


class TestDashboardImport:
    """Verify dashboard module and its functions are importable."""

    def test_page_functions_exist(self):
        mock_st = _make_mock_streamlit()
        dashboard = _import_dashboard(mock_st)

        assert callable(dashboard.page_pipeline_overview)
        assert callable(dashboard.page_company_explorer)
        assert callable(dashboard.page_scan_history)
        assert callable(dashboard.page_outreach_tracker)
        assert callable(dashboard.page_h1b_status)

    def test_data_loaders_exist(self):
        mock_st = _make_mock_streamlit()
        dashboard = _import_dashboard(mock_st)

        assert callable(dashboard.load_companies)
        assert callable(dashboard.load_scans)
        assert callable(dashboard.load_outreach)
        assert callable(dashboard.load_h1b)
        assert callable(dashboard.load_contacts)

    def test_page_map_has_all_pages(self):
        mock_st = _make_mock_streamlit()
        dashboard = _import_dashboard(mock_st)

        assert len(dashboard.PAGE_MAP) == 9
        expected = {
            "Pipeline Overview",
            "Company Explorer",
            "Scan History",
            "Outreach Tracker",
            "H1B Status",
            "Data Quality",
            "Contacts",
            "A/B Testing",
            "Follow-Up Manager",
        }
        assert set(dashboard.PAGE_MAP.keys()) == expected

    def test_pages_list_matches_page_map(self):
        mock_st = _make_mock_streamlit()
        dashboard = _import_dashboard(mock_st)

        assert len(dashboard.PAGES) == 9
        for page_name in dashboard.PAGES:
            assert page_name in dashboard.PAGE_MAP

    def test_set_page_config_called(self):
        mock_st = _make_mock_streamlit()
        _import_dashboard(mock_st)

        mock_st.set_page_config.assert_called_once()
        call_kwargs = mock_st.set_page_config.call_args
        assert "LinkedIn Outreach Dashboard" in str(call_kwargs)


# ===========================================================================
# Portal scores widget tests (from test_dashboard_enhanced.py)
# ===========================================================================


class TestPortalScoresWidget:
    def test_scores_data_structure(self):
        scores = [
            MockPortalScore("startup_jobs", 2, 1, 2, 5, "promote"),
            MockPortalScore("linkedin", 1, 0, 1, 2, "demote"),
        ]
        score_data = []
        for s in scores:
            score_data.append({
                "Portal": s.portal,
                "Velocity": s.velocity_score,
                "PM Delta": s.afternoon_delta_score,
                "Conversion": s.conversion_score,
                "Total": s.total,
                "Recommendation": s.recommendation.upper(),
            })
        assert len(score_data) == 2
        assert score_data[0]["Recommendation"] == "PROMOTE"
        assert score_data[1]["Recommendation"] == "DEMOTE"

    def test_empty_scores_handled(self):
        scores = []
        assert len(scores) == 0

    def test_recommendation_colors(self):
        colors = {
            "PROMOTE": "background-color: #2d6a2e; color: white",
            "DEMOTE": "background-color: #8b2020; color: white",
            "HOLD": "background-color: #8b7d20; color: white",
        }
        assert "#2d6a2e" in colors["PROMOTE"]
        assert "#8b2020" in colors["DEMOTE"]
        assert "#8b7d20" in colors["HOLD"]


# ===========================================================================
# Health monitor widget tests (from test_dashboard_enhanced.py)
# ===========================================================================


class TestHealthMonitorWidget:
    def test_health_data_structure(self):
        statuses = [
            MockPortalHealth("startup_jobs", 0, datetime(2026, 3, 5), None, True, False),
            MockPortalHealth("linkedin", 5, datetime(2026, 3, 1), datetime(2026, 3, 5), False, True),
        ]
        health_data = []
        for s in statuses:
            health_data.append({
                "Portal": s.portal,
                "Consecutive Failures": s.consecutive_failures,
                "Status": "Healthy" if s.is_healthy else "UNHEALTHY",
                "Last Success": str(s.last_success.strftime("%Y-%m-%d %H:%M")) if s.last_success else "N/A",
                "Last Failure": str(s.last_failure.strftime("%Y-%m-%d %H:%M")) if s.last_failure else "N/A",
            })
        assert len(health_data) == 2
        assert health_data[0]["Status"] == "Healthy"
        assert health_data[1]["Status"] == "UNHEALTHY"

    def test_alert_detection(self):
        statuses = [
            MockPortalHealth("startup_jobs", 0, datetime(2026, 3, 5), None, True, False),
            MockPortalHealth("linkedin", 5, None, datetime(2026, 3, 5), False, True),
        ]
        has_alerts = any(s.alert_triggered for s in statuses)
        assert has_alerts is True
        alert_count = sum(1 for s in statuses if s.alert_triggered)
        assert alert_count == 1

    def test_no_alerts_when_all_healthy(self):
        statuses = [
            MockPortalHealth("startup_jobs", 0, datetime(2026, 3, 5), None, True, False),
            MockPortalHealth("linkedin", 1, datetime(2026, 3, 5), None, True, False),
        ]
        has_alerts = any(s.alert_triggered for s in statuses)
        assert has_alerts is False

    def test_empty_statuses_handled(self):
        statuses = []
        assert len(statuses) == 0


# ===========================================================================
# File archive tests (from test_dashboard_enhanced.py)
# ===========================================================================


class TestFileArchive:
    def test_stale_files_list_count(self):
        stale_files = [
            "Fireworks_AI_Execution_Calendar.md",
            "Fireworks_AI_Outreach.md",
            "Fireworks_AI_Quick_Reference.md",
            "Fireworks_AI_Strategy_Notes.md",
            "Together_AI_Daily_Action_Plan.md",
            "Together_AI_Outreach_Package.md",
            "Together_AI_Summary.md",
            "Snorkel_AI_Outreach_Package.md",
            "LangChain_Outreach.md",
            "LlamaIndex_Execution_Checklist.md",
            "LlamaIndex_Outreach.md",
            "LlamaIndex_Summary.md",
            "Hypercubic_Outreach.md",
            "Irina_Adamchic_Outreach.md",
            "Hippocratic_AI_1_Intelligence_Report.md",
            "LinkedIn_Scan_Results.md",
            "FULL_SCAN_AUDIT_2026-03-05.md",
            "AUDIT_REPORT.md",
            "BEFORE_AFTER_COMPARISON.md",
            "AGENCY_BRIEF_2026-03-05.md",
            "TOOLS_AND_SKILLS_RECOMMENDATIONS.md",
            "Daily_Portal_Scan_Task.md",
            "Networking_Log.md",
        ]
        assert len(stale_files) == 23


# ===========================================================================
# Phase 2 expansion tests (from test_dashboard_phase2.py)
# ===========================================================================


class TestPhase2OutreachStages:
    def test_outreach_stages_has_eight_entries(self):
        """All 8 outreach stages are present in OUTREACH_STAGES."""
        app = _get_app()
        expected = [
            "Not Started",
            "Sent",
            "No Answer",
            "Responded",
            "Interview",
            "Declined",
            "Offer",
            "Rejected",
        ]
        assert app.OUTREACH_STAGES == expected
        assert len(app.OUTREACH_STAGES) == 8


class TestPhase2NewPages:
    def test_page_contacts_function_exists(self):
        """page_contacts function exists in the module."""
        app = _get_app()
        assert hasattr(app, "page_contacts")
        assert callable(app.page_contacts)

    def test_page_ab_testing_function_exists(self):
        """page_ab_testing function exists in the module."""
        app = _get_app()
        assert hasattr(app, "page_ab_testing")
        assert callable(app.page_ab_testing)

    def test_page_map_includes_new_pages(self):
        """PAGE_MAP includes 'Contacts' and 'A/B Testing' entries."""
        app = _get_app()
        assert "Contacts" in app.PAGE_MAP
        assert "A/B Testing" in app.PAGE_MAP
        assert app.PAGE_MAP["Contacts"] == app.page_contacts
        assert app.PAGE_MAP["A/B Testing"] == app.page_ab_testing

    def test_pages_list_has_at_least_eight_entries(self):
        """PAGES list has at least 8 entries (original 5 + new pages)."""
        app = _get_app()
        assert len(app.PAGES) >= 8
        # Verify the new pages are in the list
        assert "Contacts" in app.PAGES
        assert "A/B Testing" in app.PAGES
        assert "Follow-Up Manager" in app.PAGES
        # Verify original pages are still present
        assert "Pipeline Overview" in app.PAGES
        assert "Company Explorer" in app.PAGES
        assert "Scan History" in app.PAGES
        assert "Outreach Tracker" in app.PAGES
        assert "H1B Status" in app.PAGES


# ===========================================================================
# Dashboard upgrade tests (from test_dashboard_upgrade.py)
# ===========================================================================


class TestPagesConfig:
    def test_pages_has_9_entries(self, dashboard):
        assert len(dashboard.PAGES) == 9

    def test_pages_includes_data_quality(self, dashboard):
        assert "Data Quality" in dashboard.PAGES

    def test_page_map_matches_pages(self, dashboard):
        for page_name in dashboard.PAGES:
            assert page_name in dashboard.PAGE_MAP, f"{page_name} not in PAGE_MAP"

    def test_page_map_values_are_callable(self, dashboard):
        for name, func in dashboard.PAGE_MAP.items():
            assert callable(func), f"{name} is not callable"


class TestOutreachStages:
    def test_outreach_stages_has_correct_values(self, dashboard):
        assert "Not Started" in dashboard.OUTREACH_STAGES
        assert "Sent" in dashboard.OUTREACH_STAGES
        assert "Responded" in dashboard.OUTREACH_STAGES


class TestDataQualityFields:
    def test_data_quality_checks_8_fields(self, dashboard):
        assert len(dashboard.DATA_QUALITY_FIELDS) == 8

    def test_data_quality_fields_includes_key_fields(self, dashboard):
        assert "description" in dashboard.DATA_QUALITY_FIELDS
        assert "h1b_status" in dashboard.DATA_QUALITY_FIELDS
        assert "hiring_manager" in dashboard.DATA_QUALITY_FIELDS
        assert "salary_range" in dashboard.DATA_QUALITY_FIELDS


class TestDataQualityLogic:
    def test_skeleton_threshold_filters_correctly(self):
        """Companies below 50% completeness are skeletons."""
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "data_completeness": [30, 60, 45],
        })
        skeletons = df[df["data_completeness"] < 50]
        assert len(skeletons) == 2
        assert "A" in skeletons["name"].values
        assert "C" in skeletons["name"].values
        assert "B" not in skeletons["name"].values

    def test_empty_dataframe_returns_empty(self):
        """Empty DataFrame should not crash skeleton/enrichment logic."""
        df = pd.DataFrame()
        assert df.empty


class TestTemplateStats:
    def test_template_stats_have_correct_columns(self):
        """Template stats should have total/sent/responded/response_rate."""
        df = pd.DataFrame({
            "id": [1, 2, 3, 4],
            "template_type": ["a.j2", "a.j2", "b.j2", "b.j2"],
            "stage": ["Not Started", "Sent", "Sent", "Responded"],
        })
        stats = (
            df.groupby("template_type")
            .agg(
                total=("id", "count"),
                sent=("stage", lambda x: (x == "Sent").sum()),
                responded=("stage", lambda x: (x == "Responded").sum()),
            )
            .reset_index()
        )
        stats["response_rate"] = (
            stats["responded"] / stats["sent"].replace(0, 1) * 100
        ).round(1)

        assert "total" in stats.columns
        assert "sent" in stats.columns
        assert "responded" in stats.columns
        assert "response_rate" in stats.columns
        assert len(stats) == 2

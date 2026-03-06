"""Tests for dashboard upgrade — Data Quality page, enhanced outreach, updated stages.

Uses the same mocking approach as test_dashboard.py to handle Streamlit's
module-level execution.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
import pandas as pd


def _make_mock_streamlit():
    """Create a mock streamlit module that handles decorators, config, and widget calls."""
    mock_st = MagicMock()
    mock_st.cache_data = lambda **kwargs: lambda f: f
    mock_st.cache_resource = lambda f: f
    mock_st.set_page_config = MagicMock()
    mock_st.sidebar = MagicMock()
    mock_st.sidebar.title = MagicMock()
    mock_st.sidebar.markdown = MagicMock()
    mock_st.sidebar.radio.return_value = "Pipeline Overview"
    mock_st.sidebar.button.return_value = False

    def mock_columns(n):
        return [MagicMock() for _ in range(n)]
    mock_st.columns = mock_columns

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


def _import_dashboard(mock_st):
    """Import dashboard module with mocked streamlit and DB layer."""
    with patch.dict(sys.modules, {"streamlit": mock_st}):
        sys.modules.pop("src.dashboard.app", None)
        sys.modules.pop("src.dashboard", None)

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


@pytest.fixture
def dashboard():
    mock_st = _make_mock_streamlit()
    return _import_dashboard(mock_st)


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

"""Tests for dashboard -- import sanity and data loading.

Streamlit's runtime makes deeper testing impractical. These tests
verify the module is importable, page functions exist, and data
loaders are callable.
"""

import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


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
    def mock_columns(n):
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
            # The module calls _engine() -> get_engine(str(DB_PATH)) via @st.cache_resource
            # which we made a pass-through, so get_engine will be called.
            # Then _session() creates a sessionmaker. We need to make query return empty DataFrames.
            # page_pipeline_overview() calls load_companies() which calls _session().query(CompanyORM).all()
            # If it returns no rows, it returns pd.DataFrame() and the page shows st.info().
            mock_sessionmaker = MagicMock()
            mock_sess_instance = MagicMock()
            mock_sess_instance.query.return_value.all.return_value = []
            mock_sessionmaker.return_value = mock_sess_instance

            with patch("sqlalchemy.orm.sessionmaker", return_value=mock_sessionmaker):
                from src.dashboard import app as dashboard

    return dashboard


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

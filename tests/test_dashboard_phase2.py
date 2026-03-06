"""Dashboard Phase 2 expansion tests.

Validates: expanded outreach stages, new page functions, updated navigation.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_streamlit_mock():
    """Build a comprehensive Streamlit mock that handles all widget calls."""
    mock_st = MagicMock()

    # Make columns() return the correct number of mock column objects
    def _mock_columns(n, **kwargs):
        if isinstance(n, list):
            return [MagicMock() for _ in n]
        return [MagicMock() for _ in range(n)]

    mock_st.columns = _mock_columns

    # Decorators that pass through
    mock_st.cache_resource = lambda f=None: (lambda fn: fn) if f is None else f
    mock_st.cache_data = lambda ttl=None: (lambda fn: fn)

    # Sidebar
    mock_st.sidebar = MagicMock()
    mock_st.sidebar.radio = MagicMock(return_value="Pipeline Overview")
    mock_st.sidebar.button = MagicMock(return_value=False)

    return mock_st


def _load_app_module():
    """Import the dashboard app module without running Streamlit or touching the DB."""
    mock_st = _build_streamlit_mock()
    sys.modules["streamlit"] = mock_st

    # Patch the data loaders to return empty DataFrames so page functions exit early
    empty_df = pd.DataFrame()

    with patch.dict(sys.modules, {"streamlit": mock_st}):
        # If already imported, remove it so we can re-import cleanly
        if "src.dashboard.app" in sys.modules:
            del sys.modules["src.dashboard.app"]

        # Patch the ORM and database imports to avoid DB connection
        mock_db = MagicMock()
        mock_db.get_engine = MagicMock()
        mock_db.init_db = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "src.db.database": mock_db,
            },
        ):
            import src.dashboard.app as app_module

    return app_module


# Cache the module so we only load once
_app_module = None


def _get_app():
    global _app_module
    if _app_module is None:
        _app_module = _load_app_module()
    return _app_module


def test_outreach_stages_has_eight_entries():
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


def test_page_contacts_function_exists():
    """page_contacts function exists in the module."""
    app = _get_app()
    assert hasattr(app, "page_contacts")
    assert callable(app.page_contacts)


def test_page_ab_testing_function_exists():
    """page_ab_testing function exists in the module."""
    app = _get_app()
    assert hasattr(app, "page_ab_testing")
    assert callable(app.page_ab_testing)


def test_page_map_includes_new_pages():
    """PAGE_MAP includes 'Contacts' and 'A/B Testing' entries."""
    app = _get_app()
    assert "Contacts" in app.PAGE_MAP
    assert "A/B Testing" in app.PAGE_MAP
    assert app.PAGE_MAP["Contacts"] == app.page_contacts
    assert app.PAGE_MAP["A/B Testing"] == app.page_ab_testing


def test_pages_list_has_at_least_eight_entries():
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

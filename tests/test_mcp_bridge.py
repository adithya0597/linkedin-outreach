"""Tests for MCP Playwright -> SQLite bridge (src/scrapers/mcp_bridge.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.mcp_bridge import (
    load_mcp_results,
    mcp_results_to_postings,
    persist_mcp_results,
)

# ---------------------------------------------------------------------------
# load_mcp_results
# ---------------------------------------------------------------------------


class TestLoadMCPResults:
    def test_load_mcp_results_valid_json(self, tmp_path: Path):
        """Create a temp JSON file, load it, verify list is returned."""
        data = [
            {"title": "AI Engineer", "company_name": "Acme Corp", "url": "https://example.com/1"},
            {"title": "ML Engineer", "company_name": "Beta Inc", "url": "https://example.com/2"},
        ]
        json_file = tmp_path / "results.json"
        json_file.write_text(json.dumps(data))

        results = load_mcp_results(str(json_file))

        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0]["title"] == "AI Engineer"
        assert results[1]["company_name"] == "Beta Inc"

    def test_load_mcp_results_dict_with_results_key(self, tmp_path: Path):
        """JSON file with dict containing 'results' key should unwrap."""
        data = {"results": [{"title": "Data Scientist"}]}
        json_file = tmp_path / "results.json"
        json_file.write_text(json.dumps(data))

        results = load_mcp_results(str(json_file))

        assert len(results) == 1
        assert results[0]["title"] == "Data Scientist"

    def test_load_mcp_results_dict_with_jobs_key(self, tmp_path: Path):
        """JSON file with dict containing 'jobs' key should unwrap."""
        data = {"jobs": [{"title": "Backend Engineer"}]}
        json_file = tmp_path / "results.json"
        json_file.write_text(json.dumps(data))

        results = load_mcp_results(str(json_file))

        assert len(results) == 1
        assert results[0]["title"] == "Backend Engineer"

    def test_load_mcp_results_missing_file(self):
        """Non-existent path should return empty list."""
        results = load_mcp_results("/nonexistent/path/missing.json")

        assert results == []

    def test_load_mcp_results_invalid_json(self, tmp_path: Path):
        """Malformed JSON should return empty list."""
        json_file = tmp_path / "bad.json"
        json_file.write_text("{this is not valid json")

        results = load_mcp_results(str(json_file))

        assert results == []


# ---------------------------------------------------------------------------
# mcp_results_to_postings
# ---------------------------------------------------------------------------


class TestMCPResultsToPostings:
    def test_mcp_results_to_postings(self):
        """Convert dicts to JobPosting objects."""
        raw = [
            {
                "title": "AI Engineer",
                "company_name": "LlamaIndex",
                "location": "San Francisco, CA",
                "url": "https://jobs.ashbyhq.com/llamaindex/ai-eng",
                "salary_range": "$150k-$200k",
                "h1b_mentioned": True,
                "h1b_text": "H1B sponsorship available",
                "work_model": "remote",
                "posted_date": "2026-03-01T00:00:00Z",
            },
            {
                "title": "ML Platform Engineer",
                "company_name": "Snorkel AI",
                "url": "https://boards.greenhouse.io/snorkelai/12345",
            },
        ]

        postings = mcp_results_to_postings(raw, SourcePortal.LINKEDIN)

        assert len(postings) == 2
        assert isinstance(postings[0], JobPosting)
        assert postings[0].title == "AI Engineer"
        assert postings[0].company_name == "LlamaIndex"
        assert postings[0].source_portal == SourcePortal.LINKEDIN
        assert postings[0].h1b_mentioned is True
        assert postings[0].work_model == "remote"
        assert postings[0].posted_date is not None

        assert postings[1].title == "ML Platform Engineer"
        assert postings[1].company_name == "Snorkel AI"
        assert postings[1].h1b_mentioned is False  # default

    def test_mcp_results_to_postings_skips_empty_title(self):
        """Items without a title (or blank title) should be skipped."""
        raw = [
            {"title": "", "company_name": "NoTitle Corp"},
            {"company_name": "MissingTitle Inc"},  # no title key at all
            {"title": "   ", "company_name": "WhitespaceOnly"},
            {"title": "Valid Job", "company_name": "Good Corp"},
        ]

        postings = mcp_results_to_postings(raw, SourcePortal.WELLFOUND)

        assert len(postings) == 1
        assert postings[0].title == "Valid Job"

    def test_mcp_results_to_postings_invalid_date(self):
        """Invalid posted_date should not crash, just leave it None."""
        raw = [{"title": "AI Engineer", "posted_date": "not-a-date"}]

        postings = mcp_results_to_postings(raw, SourcePortal.MANUAL)

        assert len(postings) == 1
        assert postings[0].posted_date is None


# ---------------------------------------------------------------------------
# persist_mcp_results (integration)
# ---------------------------------------------------------------------------


class TestPersistMCPResults:
    def test_persist_mcp_results_integration(self, tmp_path: Path):
        """Mock DB, verify persist_scan_results is called with correct args."""
        data = [
            {"title": "AI Engineer", "company_name": "TestCo", "url": "https://example.com/1"},
        ]
        json_file = tmp_path / "results.json"
        json_file.write_text(json.dumps(data))

        mock_session = MagicMock()
        mock_engine = MagicMock()

        with (
            patch("src.db.database.get_engine", return_value=mock_engine),
            patch("src.db.database.init_db"),
            patch("src.db.database.get_session", return_value=mock_session),
            patch("src.scrapers.persistence.persist_scan_results", return_value=(1, 1, 1)) as mock_persist,
        ):
            total, new, _companies = persist_mcp_results("linkedin", str(json_file))

        mock_persist.assert_called_once()
        call_args = mock_persist.call_args
        assert call_args[0][0] is mock_session
        assert call_args[0][1] == "linkedin"
        assert len(call_args[0][2]) == 1
        assert call_args[0][2][0].title == "AI Engineer"
        assert total == 1
        assert new == 1

    def test_persist_mcp_results_empty_file(self, tmp_path: Path):
        """Empty results file should return (0, 0, 0) without touching DB."""
        json_file = tmp_path / "empty.json"
        json_file.write_text("[]")

        result = persist_mcp_results("linkedin", str(json_file))

        assert result == (0, 0, 0)

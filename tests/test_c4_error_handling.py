"""Tests for C4: ScrapeResult dataclass, ConcurrentScanRunner wrapping, scan summary formatting."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.scrapers.base_scraper import ScrapeResult


# ---------------------------------------------------------------------------
# 1. ScrapeResult dataclass creation
# ---------------------------------------------------------------------------


class TestScrapeResultCreation:
    """Test ScrapeResult instantiation with different outcomes."""

    def test_default_values(self):
        sr = ScrapeResult()
        assert sr.entries == []
        assert sr.outcome == "success"
        assert sr.error_message == ""
        assert sr.status_code is None
        assert sr.duration_seconds == 0.0

    def test_success_with_entries(self):
        entries = [{"title": "AI Engineer"}]
        sr = ScrapeResult(entries=entries, outcome="success", duration_seconds=2.5)
        assert sr.entries == entries
        assert sr.outcome == "success"
        assert sr.duration_seconds == 2.5

    def test_no_results_outcome(self):
        sr = ScrapeResult(outcome="no_results", duration_seconds=1.2)
        assert sr.entries == []
        assert sr.outcome == "no_results"
        assert sr.error_message == ""

    def test_error_outcome(self):
        sr = ScrapeResult(
            outcome="error",
            error_message="Connection refused",
            duration_seconds=0.3,
        )
        assert sr.outcome == "error"
        assert sr.error_message == "Connection refused"
        assert sr.entries == []

    def test_timeout_outcome(self):
        sr = ScrapeResult(
            outcome="timeout",
            error_message="Timeout (120s)",
            duration_seconds=120.0,
        )
        assert sr.outcome == "timeout"
        assert sr.duration_seconds == 120.0

    def test_skipped_outcome(self):
        sr = ScrapeResult(
            outcome="skipped",
            error_message="Circuit breaker open",
        )
        assert sr.outcome == "skipped"
        assert sr.error_message == "Circuit breaker open"

    def test_status_code_field(self):
        sr = ScrapeResult(outcome="error", status_code=429, error_message="Rate limited")
        assert sr.status_code == 429

    def test_entries_list_independence(self):
        """Each ScrapeResult should have its own entries list."""
        sr1 = ScrapeResult()
        sr2 = ScrapeResult()
        sr1.entries.append("x")
        assert sr2.entries == []


# ---------------------------------------------------------------------------
# 2. ConcurrentScanRunner wrapping results into ScrapeResult
# ---------------------------------------------------------------------------


def _make_mock_scraper(name: str, results=None, error=None):
    """Create a mock scraper for testing."""
    mock = MagicMock()
    mock.name = name
    mock.portal_name = name
    if error:
        mock.search = AsyncMock(side_effect=error)
    else:
        mock.search = AsyncMock(return_value=results or [])
    return mock


class TestConcurrentScanRunner:
    """Test that ConcurrentScanRunner wraps scraper outcomes into ScrapeResult."""

    @pytest.mark.asyncio
    async def test_success_with_results(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        entries = [MagicMock(spec=["title"])]
        scraper = _make_mock_scraper("test_portal", results=entries)

        runner = ConcurrentScanRunner(max_concurrent=2)
        await runner.run_all([scraper], query=["AI Engineer"], filters={"days": 30})

        assert len(runner.results) == 1
        result = runner.results[0]
        assert isinstance(result, ScrapeResult)
        assert result.outcome == "success"
        assert result.entries == entries
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_success_empty_results(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        scraper = _make_mock_scraper("empty_portal", results=[])

        runner = ConcurrentScanRunner(max_concurrent=2)
        await runner.run_all([scraper], query=["AI Engineer"], filters={"days": 30})

        assert len(runner.results) == 1
        result = runner.results[0]
        assert result.outcome == "no_results"
        assert result.entries == []

    @pytest.mark.asyncio
    async def test_error_outcome(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        scraper = _make_mock_scraper(
            "broken_portal", error=RuntimeError("Connection refused")
        )

        runner = ConcurrentScanRunner(max_concurrent=2)
        await runner.run_all([scraper], query=["AI Engineer"], filters={"days": 30})

        assert len(runner.results) == 1
        result = runner.results[0]
        assert result.outcome == "error"
        assert "Connection refused" in result.error_message
        assert result.entries == []

    @pytest.mark.asyncio
    async def test_timeout_outcome(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner, SCRAPER_TIMEOUT

        async def slow_search(*args, **kwargs):
            await asyncio.sleep(999)  # Will be cancelled by timeout
            return []

        scraper = _make_mock_scraper("slow_portal")
        scraper.search = slow_search

        # Use a very short timeout for testing
        import src.scrapers.concurrent_runner as runner_mod
        original_timeout = runner_mod.SCRAPER_TIMEOUT
        runner_mod.SCRAPER_TIMEOUT = 0.1  # 100ms timeout

        try:
            runner = ConcurrentScanRunner(max_concurrent=2)
            await runner.run_all([scraper], query=["AI Engineer"], filters={"days": 30})

            assert len(runner.results) == 1
            result = runner.results[0]
            assert result.outcome == "timeout"
            assert "Timeout" in result.error_message
        finally:
            runner_mod.SCRAPER_TIMEOUT = original_timeout

    @pytest.mark.asyncio
    async def test_circuit_breaker_skipped(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        scraper = _make_mock_scraper("cb_portal")

        runner = ConcurrentScanRunner(max_concurrent=2)
        # Force circuit breaker open
        breaker = runner._get_breaker("cb_portal")
        # Trip the breaker by recording enough failures
        for _ in range(5):
            await breaker.record_failure()

        await runner.run_all([scraper], query=["AI Engineer"], filters={"days": 30})

        assert len(runner.results) == 1
        result = runner.results[0]
        assert result.outcome == "skipped"
        assert "Circuit breaker" in result.error_message

    @pytest.mark.asyncio
    async def test_multiple_scrapers_mixed_outcomes(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        entries = [MagicMock(spec=["title"])]
        s_ok = _make_mock_scraper("ok_portal", results=entries)
        s_empty = _make_mock_scraper("empty_portal", results=[])
        s_err = _make_mock_scraper("err_portal", error=ValueError("bad data"))

        runner = ConcurrentScanRunner(max_concurrent=5)
        await runner.run_all(
            [s_ok, s_empty, s_err], query=["AI Engineer"], filters={"days": 30}
        )

        assert len(runner.results) == 3
        outcomes = {r.outcome for r in runner.results}
        assert "success" in outcomes
        assert "no_results" in outcomes
        assert "error" in outcomes

    @pytest.mark.asyncio
    async def test_empty_scraper_list(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        runner = ConcurrentScanRunner()
        result = await runner.run_all([], query=["AI Engineer"], filters={})
        assert result == []
        assert runner.results == []

    @pytest.mark.asyncio
    async def test_persist_fn_called_for_success(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        entries = [MagicMock(spec=["title"])]
        scraper = _make_mock_scraper("persist_portal", results=entries)
        persist_fn = MagicMock()

        runner = ConcurrentScanRunner(max_concurrent=2)
        await runner.run_all(
            [scraper], query=["AI Engineer"], filters={"days": 30},
            persist_fn=persist_fn,
        )

        persist_fn.assert_called_once_with("persist_portal", entries)

    @pytest.mark.asyncio
    async def test_persist_fn_not_called_for_error(self):
        from src.scrapers.concurrent_runner import ConcurrentScanRunner

        scraper = _make_mock_scraper(
            "err_portal", error=RuntimeError("fail")
        )
        persist_fn = MagicMock()

        runner = ConcurrentScanRunner(max_concurrent=2)
        await runner.run_all(
            [scraper], query=["AI Engineer"], filters={"days": 30},
            persist_fn=persist_fn,
        )

        persist_fn.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Scan summary formatting
# ---------------------------------------------------------------------------


class TestScanSummaryFormatting:
    """Test the _format_outcome helper and outcome style mapping."""

    def test_format_outcome_success(self):
        from src.cli.scan_commands import _format_outcome

        result = _format_outcome("success")
        assert "Found" in result
        assert "green" in result

    def test_format_outcome_no_results(self):
        from src.cli.scan_commands import _format_outcome

        result = _format_outcome("no_results")
        assert "No Results" in result
        assert "yellow" in result

    def test_format_outcome_error(self):
        from src.cli.scan_commands import _format_outcome

        result = _format_outcome("error")
        assert "Error" in result
        assert "red" in result

    def test_format_outcome_timeout(self):
        from src.cli.scan_commands import _format_outcome

        result = _format_outcome("timeout")
        assert "Timeout" in result
        assert "red" in result

    def test_format_outcome_skipped(self):
        from src.cli.scan_commands import _format_outcome

        result = _format_outcome("skipped")
        assert "Skipped" in result
        assert "yellow" in result

    def test_format_outcome_unknown_passthrough(self):
        from src.cli.scan_commands import _format_outcome

        result = _format_outcome("unknown_state")
        assert result == "unknown_state"

    def test_outcome_styles_all_defined(self):
        from src.cli.scan_commands import _OUTCOME_STYLES

        expected = {"success", "no_results", "error", "timeout", "skipped"}
        assert set(_OUTCOME_STYLES.keys()) == expected


# ---------------------------------------------------------------------------
# 4. ScrapeResult used end-to-end in scan summary rendering
# ---------------------------------------------------------------------------


class TestScrapeResultInScanSummary:
    """Verify that ScrapeResult outcomes drive scan summary display logic."""

    def test_success_outcome_maps_to_found_display(self):
        """A success ScrapeResult should show 'Found X' in the summary."""
        sr = ScrapeResult(
            entries=[MagicMock()], outcome="success", duration_seconds=1.0,
        )
        assert sr.outcome == "success"
        assert len(sr.entries) == 1
        assert sr.error_message == ""

    def test_no_results_vs_error_distinguishable(self):
        """no_results and error must be clearly different outcomes."""
        sr_empty = ScrapeResult(outcome="no_results", duration_seconds=0.5)
        sr_error = ScrapeResult(
            outcome="error", error_message="500 Internal Server Error",
            duration_seconds=0.5,
        )
        assert sr_empty.outcome != sr_error.outcome
        assert sr_empty.error_message == ""
        assert sr_error.error_message != ""

    def test_timeout_includes_duration(self):
        sr = ScrapeResult(
            outcome="timeout",
            error_message="Timeout (120s)",
            duration_seconds=120.0,
        )
        assert sr.duration_seconds == 120.0
        assert "120" in sr.error_message

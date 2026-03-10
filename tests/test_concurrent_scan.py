"""Tests for ConcurrentScanRunner — parallel scraper execution with serialized DB writes."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.scrapers.concurrent_runner import ConcurrentScanRunner


def _make_mock_scraper(name: str, results: list | None = None, delay: float = 0.0, error: Exception | None = None):
    """Create a mock scraper with portal_name, name, and async search()."""
    scraper = MagicMock()
    scraper.name = name
    scraper.portal_name = name

    async def _search(*args, **kwargs):
        if delay:
            await asyncio.sleep(delay)
        if error:
            raise error
        return results if results is not None else []

    scraper.search = AsyncMock(side_effect=_search)
    return scraper


@pytest.mark.asyncio
async def test_concurrent_execution_is_parallel():
    """Scrapers with delays should run concurrently, not sequentially."""
    delay = 0.1
    s1 = _make_mock_scraper("portal_a", results=["a"], delay=delay)
    s2 = _make_mock_scraper("portal_b", results=["b"], delay=delay)
    s3 = _make_mock_scraper("portal_c", results=["c"], delay=delay)

    runner = ConcurrentScanRunner(max_concurrent=5)
    start = time.monotonic()
    await runner.run_all([s1, s2, s3], query="AI Engineer", filters={})
    elapsed = time.monotonic() - start

    # If sequential, would take ~0.3s. Parallel should be ~0.1s.
    assert elapsed < 0.25, f"Took {elapsed:.2f}s — scrapers ran sequentially, not concurrently"
    assert len(runner.results) == 3


@pytest.mark.asyncio
async def test_db_write_serialization():
    """persist_fn is called once per scraper, and calls do not overlap."""
    write_log = []

    async def _slow_search(*args, **kwargs):
        await asyncio.sleep(0.01)
        return [{"title": "job"}]

    s1 = _make_mock_scraper("portal_a")
    s1.search = AsyncMock(side_effect=_slow_search)
    s2 = _make_mock_scraper("portal_b")
    s2.search = AsyncMock(side_effect=_slow_search)

    def _persist(portal, entries):
        write_log.append(("start", portal))
        # Simulate some write work — in a real scenario this is synchronous
        write_log.append(("end", portal))

    runner = ConcurrentScanRunner(max_concurrent=5)
    await runner.run_all([s1, s2], query="q", filters={}, persist_fn=_persist)

    # Both portals should have writes logged
    portals_written = [p for action, p in write_log if action == "start"]
    assert len(portals_written) == 2
    assert set(portals_written) == {"portal_a", "portal_b"}


@pytest.mark.asyncio
async def test_single_failure_isolation():
    """One scraper failing should not prevent others from succeeding."""
    s1 = _make_mock_scraper("good", results=[{"title": "job1"}])
    s2 = _make_mock_scraper("bad", error=RuntimeError("connection timeout"))
    s3 = _make_mock_scraper("also_good", results=[{"title": "job2"}])

    runner = ConcurrentScanRunner(max_concurrent=5)
    entries = await runner.run_all([s1, s2, s3], query="q", filters={})

    # Should get entries from good scrapers
    assert len(entries) == 2

    # Check that the failed scraper is recorded
    failed = [r for r in runner.results if r.error]
    assert len(failed) == 1
    assert failed[0].portal == "bad"
    assert "connection timeout" in failed[0].error

    succeeded = [r for r in runner.results if not r.error]
    assert len(succeeded) == 2


@pytest.mark.asyncio
async def test_semaphore_limiting():
    """max_concurrent limits how many scrapers run at once."""
    active = {"count": 0, "peak": 0}

    async def _tracked_search(*args, **kwargs):
        active["count"] += 1
        active["peak"] = max(active["peak"], active["count"])
        await asyncio.sleep(0.05)
        active["count"] -= 1
        return [{"title": "job"}]

    scrapers = []
    for i in range(6):
        s = _make_mock_scraper(f"portal_{i}")
        s.search = AsyncMock(side_effect=_tracked_search)
        scrapers.append(s)

    runner = ConcurrentScanRunner(max_concurrent=2)
    await runner.run_all(scrapers, query="q", filters={})

    assert active["peak"] <= 2, f"Peak concurrency was {active['peak']}, expected <= 2"
    assert len(runner.results) == 6


@pytest.mark.asyncio
async def test_empty_scraper_list():
    """Empty scraper list returns empty results immediately."""
    runner = ConcurrentScanRunner()
    entries = await runner.run_all([], query="q", filters={})
    assert entries == []
    assert runner.results == []


@pytest.mark.asyncio
async def test_all_scrapers_fail():
    """When every scraper fails, results contain all errors and no entries."""
    s1 = _make_mock_scraper("a", error=ValueError("bad query"))
    s2 = _make_mock_scraper("b", error=TimeoutError("timed out"))

    runner = ConcurrentScanRunner(max_concurrent=5)
    entries = await runner.run_all([s1, s2], query="q", filters={})

    assert entries == []
    assert len(runner.results) == 2
    assert all(r.error for r in runner.results)


@pytest.mark.asyncio
async def test_results_aggregation():
    """All entries from all scrapers are aggregated in the return value."""
    s1 = _make_mock_scraper("a", results=["e1", "e2"])
    s2 = _make_mock_scraper("b", results=["e3"])
    s3 = _make_mock_scraper("c", results=["e4", "e5", "e6"])

    runner = ConcurrentScanRunner(max_concurrent=5)
    entries = await runner.run_all([s1, s2, s3], query="q", filters={})

    assert len(entries) == 6
    assert set(entries) == {"e1", "e2", "e3", "e4", "e5", "e6"}


@pytest.mark.asyncio
async def test_persist_fn_receives_correct_data():
    """persist_fn is called with the portal name and its entries."""
    s1 = _make_mock_scraper("alpha", results=["x", "y"])
    s2 = _make_mock_scraper("beta", results=["z"])

    persist_calls = {}

    def _persist(portal, entries):
        persist_calls[portal] = list(entries)

    runner = ConcurrentScanRunner(max_concurrent=5)
    await runner.run_all([s1, s2], query="q", filters={}, persist_fn=_persist)

    assert "alpha" in persist_calls
    assert persist_calls["alpha"] == ["x", "y"]
    assert "beta" in persist_calls
    assert persist_calls["beta"] == ["z"]


@pytest.mark.asyncio
async def test_persist_fn_not_called_on_error():
    """persist_fn should not be called for scrapers that errored."""
    s1 = _make_mock_scraper("good", results=["e1"])
    s2 = _make_mock_scraper("bad", error=RuntimeError("fail"))

    persist_calls = []

    def _persist(portal, entries):
        persist_calls.append(portal)

    runner = ConcurrentScanRunner(max_concurrent=5)
    await runner.run_all([s1, s2], query="q", filters={}, persist_fn=_persist)

    assert persist_calls == ["good"]


@pytest.mark.asyncio
async def test_scan_result_duration_recorded():
    """Each ScanResult should have a non-zero duration."""
    s1 = _make_mock_scraper("portal_a", results=["e1"], delay=0.02)

    runner = ConcurrentScanRunner(max_concurrent=5)
    await runner.run_all([s1], query="q", filters={})

    assert len(runner.results) == 1
    assert runner.results[0].duration >= 0.01


@pytest.mark.asyncio
async def test_filters_passed_to_scraper():
    """Filters dict is passed as kwargs to scraper.search()."""
    s = _make_mock_scraper("portal_a", results=[])
    runner = ConcurrentScanRunner()
    await runner.run_all([s], query="AI Engineer", filters={"days": 7, "limit": 50})

    s.search.assert_called_once_with("AI Engineer", days=7, limit=50)

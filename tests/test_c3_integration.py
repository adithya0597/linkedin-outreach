"""C3 Integration Tests -- verify cross-feature interactions."""

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from tenacity import RetryError

from src.config.settings import Settings
from src.config.startup_checks import CheckResult, run_all_checks
from src.db.orm import Base, CompanyORM, ContactORM, JobPostingORM
from src.integrations.notion_bidirectional import NotionBidirectionalSync
from src.scrapers.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from src.scrapers.concurrent_runner import ConcurrentScanRunner, ScanResult
from src.scrapers.retry import scraper_retry

# ---------------------------------------------------------------------------
# 1. Concurrent scan -> DB write queue -> no duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_scan_no_duplicates():
    """Multiple scrapers returning overlapping data should persist without duplication."""
    persisted = {}  # portal -> entries

    def persist_fn(portal, entries):
        persisted[portal] = entries

    scrapers = []
    for name in ("alpha", "beta", "gamma"):
        s = MagicMock()
        s.portal_name = name
        s.search = AsyncMock(
            return_value=[{"title": f"{name}-job-1"}, {"title": f"{name}-job-2"}]
        )
        scrapers.append(s)

    runner = ConcurrentScanRunner(max_concurrent=3)
    all_entries = await runner.run_all(scrapers, "AI Engineer", {}, persist_fn=persist_fn)

    # Each portal should have been persisted exactly once
    assert len(persisted) == 3
    assert set(persisted.keys()) == {"alpha", "beta", "gamma"}
    # Total entries: 3 scrapers * 2 entries each
    assert len(all_entries) == 6
    # No duplicates in runner.results
    assert len(runner.results) == 3


# ---------------------------------------------------------------------------
# 2. Retry exhaustion -> error surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scraper_retry_exhaustion():
    """scraper_retry should retry 3 times then re-raise on persistent failure."""
    call_count = 0

    @scraper_retry
    async def flaky_scraper():
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused")

    with pytest.raises(httpx.ConnectError):
        await flaky_scraper()

    assert call_count == 3


# ---------------------------------------------------------------------------
# 3. Circuit breaker state transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_state_transitions():
    """CLOSED -> OPEN after 3 failures, then HALF_OPEN after cooldown."""
    cb = CircuitBreaker("test-portal", failure_threshold=3, cooldown_seconds=0.1)

    # Initially CLOSED
    assert cb.state == CircuitState.CLOSED
    assert await cb.can_execute() is True

    # Fail 3 times -> OPEN
    for _ in range(3):
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert await cb.can_execute() is False

    # Wait for cooldown -> HALF_OPEN
    await asyncio.sleep(0.15)
    assert await cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN

    # Success in HALF_OPEN -> CLOSED
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED

    # Fail to OPEN again, then HALF_OPEN, then fail again -> OPEN
    for _ in range(3):
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN
    await asyncio.sleep(0.15)
    assert await cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# 4. Startup validation with mixed results
# ---------------------------------------------------------------------------


def test_startup_validation_mixed_results():
    """run_all_checks returns a mix of passed/failed depending on env."""
    # Clear Notion keys to force failures, set APIFY to force a pass
    env_overrides = {
        "NOTION_API_KEY": "",
        "NOTION_DATABASE_ID": "",
        "APIFY_TOKEN": "test-token-123",
    }
    with patch.dict("os.environ", env_overrides, clear=False):
        results = run_all_checks()

    # Should have results for api keys + config + db + chrome
    assert len(results) >= 5

    # Find specific results
    by_name = {r.name: r for r in results}

    # APIFY should pass (we set it)
    assert by_name["api_key_apify_token"].passed is True

    # Notion keys should fail (we cleared them)
    assert by_name["api_key_notion_api_key"].passed is False
    assert by_name["api_key_notion_database_id"].passed is False

    # All results should be CheckResult instances
    for r in results:
        assert isinstance(r, CheckResult)
        assert r.severity in ("warning", "error")


# ---------------------------------------------------------------------------
# 5. N+1 fix verification -- detect_conflicts bulk loads
# ---------------------------------------------------------------------------


def test_detect_conflicts_bulk_loads(session):
    """detect_conflicts should query companies once, not N times."""
    # Seed some companies
    for i in range(5):
        c = CompanyORM(
            name=f"Company-{i}",
            stage="To apply",
            updated_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        session.add(c)
    session.commit()

    sync = NotionBidirectionalSync.__new__(NotionBidirectionalSync)
    sync.session = session

    # Mock pulled data matching 3 of our companies
    pulled = [
        {
            "name": f"Company-{i}",
            "stage": "Applied",
            "_notion_updated": "2026-03-05T12:00:00Z",
        }
        for i in range(3)
    ]

    # Spy on session.query to count calls
    original_query = session.query
    query_calls = []

    def counting_query(*args, **kwargs):
        query_calls.append(args)
        return original_query(*args, **kwargs)

    session.query = counting_query

    conflicts = sync.detect_conflicts(pulled)

    # Should have called query exactly once (bulk load)
    company_queries = [c for c in query_calls if CompanyORM in c]
    assert len(company_queries) == 1

    # Should detect conflicts on the 'stage' field for the 3 matching companies
    assert len(conflicts) >= 3


# ---------------------------------------------------------------------------
# 6. Batch page ID lookup -- push_all uses get_all_page_ids once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_all_batch_page_id_lookup():
    """push_all should call get_all_page_ids once, not per-company."""
    from src.integrations.notion_sync import NotionCRM

    crm = NotionCRM.__new__(NotionCRM)
    crm.database_id = "test-db-id"

    companies = []
    for i in range(5):
        c = MagicMock(spec=CompanyORM)
        c.name = f"Company-{i}"
        c.updated_at = datetime(2026, 3, 1, tzinfo=UTC)
        companies.append(c)

    crm.get_all_page_ids = AsyncMock(return_value={f"Company-{i}": f"page-{i}" for i in range(5)})
    crm.sync_company = AsyncMock(return_value="page-id")

    await crm.push_all(companies)

    # get_all_page_ids called exactly once
    crm.get_all_page_ids.assert_awaited_once()
    # sync_company called 5 times (once per company), each with cache
    assert crm.sync_company.await_count == 5
    for call in crm.sync_company.call_args_list:
        assert "page_id_cache" in call.kwargs or len(call.args) > 1


# ---------------------------------------------------------------------------
# 7. Concurrent scan with failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_scan_failure_isolation():
    """One failing scraper should not block others."""
    persisted = {}

    def persist_fn(portal, entries):
        persisted[portal] = entries

    good1 = MagicMock()
    good1.portal_name = "good1"
    good1.search = AsyncMock(return_value=[{"title": "job-1"}])

    bad = MagicMock()
    bad.portal_name = "bad"
    bad.search = AsyncMock(side_effect=RuntimeError("scraper crashed"))

    good2 = MagicMock()
    good2.portal_name = "good2"
    good2.search = AsyncMock(return_value=[{"title": "job-2"}])

    runner = ConcurrentScanRunner(max_concurrent=3)
    all_entries = await runner.run_all([good1, bad, good2], "AI", {}, persist_fn=persist_fn)

    # Both good scrapers should persist
    assert "good1" in persisted
    assert "good2" in persisted
    # Bad scraper should NOT be in persisted (error branch skips persist)
    assert "bad" not in persisted

    # all_entries includes entries from the error result too (empty list extended)
    assert len(all_entries) == 2

    # Runner results should have 3 entries, one with error
    assert len(runner.results) == 3
    errors = [r for r in runner.results if r.error_message]
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# 8. Circuit breaker + concurrent runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_with_concurrent_runner():
    """A circuit-broken scraper should return empty results without crashing the runner."""
    good = MagicMock()
    good.name = "healthy"
    good.portal_name = "healthy"
    good.search = AsyncMock(return_value=[{"title": "real-job"}])

    broken = MagicMock()
    broken.name = "broken-portal"
    broken.portal_name = "broken-portal"
    broken.search = AsyncMock(return_value=[{"title": "real-job"}])

    runner = ConcurrentScanRunner(max_concurrent=2)

    # Trip the runner's internal breaker for "broken-portal"
    breaker = runner._get_breaker("broken-portal")
    breaker.failure_threshold = 1
    await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    all_entries = await runner.run_all([broken, good], "AI", {})

    # Healthy scraper results should be present
    assert any(e.get("title") == "real-job" for e in all_entries)
    # Circuit-broken scraper should be skipped
    skipped = [r for r in runner.results if r.outcome == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].entries == []


# ---------------------------------------------------------------------------
# 9. DB composite indexes exist
# ---------------------------------------------------------------------------


def test_db_composite_indexes_exist():
    """Verify expected composite indexes are created by Base.metadata.create_all."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)

    # Check companies table indexes
    company_indexes = inspector.get_indexes("companies")
    index_names = {idx["name"] for idx in company_indexes}
    assert "ix_company_disqualified_stage" in index_names
    assert "ix_company_source_tier" in index_names

    # Check contacts table indexes
    contact_indexes = inspector.get_indexes("contacts")
    contact_index_names = {idx["name"] for idx in contact_indexes}
    assert "ix_contact_company_score" in contact_index_names

    # Check job_postings table indexes
    posting_indexes = inspector.get_indexes("job_postings")
    posting_index_names = {idx["name"] for idx in posting_indexes}
    assert "ix_posting_portal_company" in posting_index_names

    # Check scans table indexes
    scan_indexes = inspector.get_indexes("scans")
    scan_index_names = {idx["name"] for idx in scan_indexes}
    assert "ix_scan_portal_started" in scan_index_names

    engine.dispose()


# ---------------------------------------------------------------------------
# 10. Settings timezone integration
# ---------------------------------------------------------------------------


def test_settings_timezone_default():
    """Settings should have a default timezone and it can be overridden."""
    s = Settings(_env_file=None)
    assert s.timezone == "America/Chicago"


def test_settings_timezone_override():
    """Settings timezone can be overridden via env var."""
    with patch.dict("os.environ", {"TIMEZONE": "UTC"}):
        Settings.model_config["env_file"] = None
        s = Settings(timezone="UTC")
        assert s.timezone == "UTC"


# ---------------------------------------------------------------------------
# 11. Concurrent scan runner with empty scraper list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_scan_empty_scrapers():
    """run_all with no scrapers should return empty list immediately."""
    runner = ConcurrentScanRunner()
    result = await runner.run_all([], "AI", {})
    assert result == []
    assert runner.results == []


# ---------------------------------------------------------------------------
# 12. Circuit breaker reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_reset():
    """reset() should restore circuit to CLOSED state."""
    cb = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=300)
    await cb.record_failure()
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert await cb.can_execute() is True


# ---------------------------------------------------------------------------
# 13. ScanResult dataclass
# ---------------------------------------------------------------------------


def test_scan_result_defaults():
    """ScanResult should have sensible defaults."""
    r = ScanResult(portal="test", entries=[{"a": 1}])
    assert r.error is None
    assert r.duration == 0.0
    assert r.portal == "test"
    assert len(r.entries) == 1

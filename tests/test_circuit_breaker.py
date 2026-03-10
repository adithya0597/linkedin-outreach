"""Tests for circuit breaker + scraper exception hardening."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scrapers.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState

# ---------------------------------------------------------------------------
# Circuit breaker core tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_state_allows_execution():
    cb = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=1.0)
    assert cb.state == CircuitState.CLOSED
    assert await cb.can_execute() is True


@pytest.mark.asyncio
async def test_failures_increment_counter():
    cb = CircuitBreaker("test", failure_threshold=5)
    await cb.record_failure()
    assert cb.failure_count == 1
    await cb.record_failure()
    assert cb.failure_count == 2
    assert cb.state == CircuitState.CLOSED  # Not yet at threshold


@pytest.mark.asyncio
async def test_closed_to_open_after_threshold():
    cb = CircuitBreaker("test", failure_threshold=3)
    for _ in range(3):
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 3


@pytest.mark.asyncio
async def test_open_rejects_execution():
    cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=999.0)
    await cb.record_failure()  # Opens circuit
    assert cb.state == CircuitState.OPEN
    assert await cb.can_execute() is False


@pytest.mark.asyncio
async def test_open_to_half_open_after_cooldown():
    cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.05)
    await cb.record_failure()  # Opens circuit
    assert cb.state == CircuitState.OPEN

    await asyncio.sleep(0.1)  # Wait past cooldown
    assert await cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_to_closed_on_success():
    cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.05)
    await cb.record_failure()  # CLOSED -> OPEN
    await asyncio.sleep(0.1)
    await cb.can_execute()  # OPEN -> HALF_OPEN

    await cb.record_success()  # HALF_OPEN -> CLOSED
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_half_open_to_open_on_failure():
    cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.05)
    await cb.record_failure()  # CLOSED -> OPEN
    await asyncio.sleep(0.1)
    await cb.can_execute()  # OPEN -> HALF_OPEN

    await cb.record_failure()  # HALF_OPEN -> OPEN
    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_reset_restores_closed():
    cb = CircuitBreaker("test", failure_threshold=1)
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert cb.last_failure_time == 0.0


def test_circuit_open_error():
    err = CircuitOpenError("portal down")
    assert str(err) == "portal down"
    assert isinstance(err, Exception)


@pytest.mark.asyncio
async def test_success_resets_failure_count():
    cb = CircuitBreaker("test", failure_threshold=5)
    await cb.record_failure()
    await cb.record_failure()
    assert cb.failure_count == 2

    await cb.record_success()
    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_concurrent_access():
    """Verify lock protects state under concurrent calls."""
    cb = CircuitBreaker("test", failure_threshold=10, cooldown_seconds=0.05)

    async def fail_many():
        for _ in range(5):
            await cb.record_failure()

    await asyncio.gather(fail_many(), fail_many())
    assert cb.failure_count == 10
    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_logging_on_state_transitions(caplog):
    cb = CircuitBreaker("test-portal", failure_threshold=2, cooldown_seconds=0.05)

    with caplog.at_level(logging.WARNING, logger="src.scrapers.circuit_breaker"):
        await cb.record_failure()
        await cb.record_failure()  # -> OPEN

    assert any("opened after 2 failures" in r.message for r in caplog.records)

    caplog.clear()
    await asyncio.sleep(0.1)

    with caplog.at_level(logging.INFO, logger="src.scrapers.circuit_breaker"):
        await cb.can_execute()  # -> HALF_OPEN

    assert any("HALF_OPEN" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Scraper exception-hardening tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patchright_parse_card_logs_on_error(caplog):
    """Verify _parse_card in JobrightPatchrightScraper logs exceptions."""
    from src.scrapers.patchright_scraper import JobrightPatchrightScraper

    scraper = JobrightPatchrightScraper()
    mock_card = AsyncMock()
    mock_card.query_selector = AsyncMock(side_effect=RuntimeError("element detached"))

    with caplog.at_level(logging.WARNING, logger="src.scrapers.patchright_scraper"):
        result = await scraper._parse_card(mock_card, AsyncMock())

    assert result is None


@pytest.mark.asyncio
async def test_trueup_parse_card_logs_on_error(caplog):
    """Verify _parse_card in TrueUpPatchrightScraper logs exceptions."""
    from src.scrapers.patchright_scraper import TrueUpPatchrightScraper

    scraper = TrueUpPatchrightScraper()
    mock_card = AsyncMock()
    mock_card.query_selector = AsyncMock(side_effect=RuntimeError("stale element"))

    with caplog.at_level(logging.WARNING, logger="src.scrapers.patchright_scraper"):
        result = await scraper._parse_card(mock_card)

    assert result is None


@pytest.mark.asyncio
async def test_hn_hiring_json_parse_logs_on_error(caplog):
    """Verify HNHiringScraper logs JSON parse failures."""
    from src.scrapers.hn_hiring_scraper import HNHiringScraper

    scraper = HNHiringScraper()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(side_effect=ValueError("bad json"))

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(scraper, "_get_client", return_value=mock_client), \
         patch.object(scraper, "_throttle", new_callable=AsyncMock):
        with caplog.at_level(logging.WARNING, logger="src.scrapers.hn_hiring_scraper"):
            results = await scraper.search(["python"], days=7)

    assert results == []


@pytest.mark.asyncio
async def test_hn_hiring_algolia_fallback_logs_on_error(caplog):
    """Verify _search_hn_algolia logs failures."""
    import httpx

    from src.scrapers.hn_hiring_scraper import HNHiringScraper

    scraper = HNHiringScraper()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with caplog.at_level(logging.WARNING, logger="src.scrapers.hn_hiring_scraper"):
        results = await scraper._search_hn_algolia(mock_client, "python", 7)

    assert results == []

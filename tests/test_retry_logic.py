"""Tests for retry decorators and BaseScraper._fetch_with_retry."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from tenacity import RetryError

from src.scrapers.retry import _is_retryable_status, notion_retry, scraper_retry


# ---------------------------------------------------------------------------
# scraper_retry
# ---------------------------------------------------------------------------

class TestScraperRetry:
    """Tests for the scraper_retry decorator."""

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        call_count = 0

        @scraper_retry
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("connection refused")
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exhaustion_raises_original(self):
        @scraper_retry
        async def always_fails():
            raise httpx.ConnectError("connection refused")

        with pytest.raises(httpx.ConnectError, match="connection refused"):
            await always_fails()

    @pytest.mark.asyncio
    async def test_non_retryable_skips_retry(self):
        call_count = 0

        @scraper_retry
        async def bad_value():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await bad_value()
        assert call_count == 1  # no retry attempted

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        call_count = 0

        @scraper_retry
        async def timeout_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("timed out")
            return "recovered"

        result = await timeout_then_ok()
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_os_error(self):
        call_count = 0

        @scraper_retry
        async def os_error_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("network unreachable")
            return "ok"

        result = await os_error_then_ok()
        assert result == "ok"
        assert call_count == 2


# ---------------------------------------------------------------------------
# notion_retry
# ---------------------------------------------------------------------------

class TestNotionRetry:
    """Tests for the notion_retry decorator."""

    def _make_status_error(self, status_code: int) -> httpx.HTTPStatusError:
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        request = MagicMock(spec=httpx.Request)
        return httpx.HTTPStatusError(
            f"{status_code} error", request=request, response=response
        )

    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        call_count = 0

        @notion_retry
        async def rate_limited():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise self._make_status_error(429)
            return "ok"

        result = await rate_limited()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_502(self):
        call_count = 0

        @notion_retry
        async def bad_gateway():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise self._make_status_error(502)
            return "ok"

        result = await bad_gateway()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_skips_404(self):
        call_count = 0

        @notion_retry
        async def not_found():
            nonlocal call_count
            call_count += 1
            raise self._make_status_error(404)

        with pytest.raises(httpx.HTTPStatusError):
            await not_found()
        assert call_count == 1  # no retry on 404

    @pytest.mark.asyncio
    async def test_skips_400(self):
        call_count = 0

        @notion_retry
        async def bad_request():
            nonlocal call_count
            call_count += 1
            raise self._make_status_error(400)

        with pytest.raises(httpx.HTTPStatusError):
            await bad_request()
        assert call_count == 1


# ---------------------------------------------------------------------------
# _is_retryable_status helper
# ---------------------------------------------------------------------------

class TestIsRetryableStatus:
    def _make_status_error(self, code: int) -> httpx.HTTPStatusError:
        response = MagicMock(spec=httpx.Response)
        response.status_code = code
        request = MagicMock(spec=httpx.Request)
        return httpx.HTTPStatusError(f"{code}", request=request, response=response)

    def test_429_is_retryable(self):
        assert _is_retryable_status(self._make_status_error(429)) is True

    def test_502_is_retryable(self):
        assert _is_retryable_status(self._make_status_error(502)) is True

    def test_503_is_retryable(self):
        assert _is_retryable_status(self._make_status_error(503)) is True

    def test_404_not_retryable(self):
        assert _is_retryable_status(self._make_status_error(404)) is False

    def test_non_http_error_not_retryable(self):
        assert _is_retryable_status(ValueError("nope")) is False


# ---------------------------------------------------------------------------
# BaseScraper._fetch_with_retry
# ---------------------------------------------------------------------------

class TestFetchWithRetry:
    """Tests for the opt-in _fetch_with_retry helper on BaseScraper."""

    @pytest.mark.asyncio
    async def test_fetch_with_retry_success(self):
        from src.config.enums import SourcePortal
        from src.scrapers.base_scraper import BaseScraper

        # Create a concrete subclass
        class DummyScraper(BaseScraper):
            async def search(self, keywords, days=30):
                return []

        scraper = DummyScraper(portal=SourcePortal.ASHBY)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.scrapers.base_scraper.httpx.AsyncClient", return_value=mock_client):
            result = await scraper._fetch_with_retry("https://example.com")

        assert result == mock_response
        mock_client.get.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_with_retry_retries_on_error(self):
        from src.config.enums import SourcePortal
        from src.scrapers.base_scraper import BaseScraper

        class DummyScraper(BaseScraper):
            async def search(self, keywords, days=30):
                return []

        scraper = DummyScraper(portal=SourcePortal.ASHBY)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            httpx.ConnectError("refused"),
            mock_response,
        ]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.scrapers.base_scraper.httpx.AsyncClient", return_value=mock_client):
            result = await scraper._fetch_with_retry("https://example.com")

        assert result == mock_response
        assert mock_client.get.call_count == 2

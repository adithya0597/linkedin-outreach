"""Reusable retry decorators for scrapers and API clients."""

import logging

import httpx
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

__all__ = ["RetryError", "notion_retry", "scraper_retry"]

# Retry on transient HTTP / network errors
scraper_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(
        (httpx.HTTPError, TimeoutError, ConnectionError, OSError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


def _is_retryable_status(exc: BaseException) -> bool:
    """Return True for Notion-style retryable HTTP status codes (429/502/503)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 502, 503)
    return False


# Retry on Notion API rate limits and server errors only
notion_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception(_is_retryable_status),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)

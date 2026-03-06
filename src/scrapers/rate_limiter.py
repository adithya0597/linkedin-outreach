from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter — one bucket per portal."""

    def __init__(self, default_tokens_per_second: float = 1.0) -> None:
        self._default_rate = default_tokens_per_second
        self._rates: dict[str, float] = {}
        self._tokens: dict[str, float] = {}
        self._last_refill: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def configure(self, portal: str, tokens_per_second: float) -> None:
        """Set a custom rate for a specific portal."""
        self._rates[portal] = tokens_per_second

    def _get_rate(self, portal: str) -> float:
        return self._rates.get(portal, self._default_rate)

    def _refill(self, portal: str) -> None:
        now = time.monotonic()
        rate = self._get_rate(portal)
        last = self._last_refill.get(portal, now)
        elapsed = now - last

        current = self._tokens.get(portal, rate)
        self._tokens[portal] = min(rate, current + elapsed * rate)
        self._last_refill[portal] = now

    async def acquire(self, portal: str) -> None:
        """Wait until a token is available for the given portal."""
        async with self._lock:
            self._refill(portal)

            if self._tokens[portal] >= 1.0:
                self._tokens[portal] -= 1.0
                return

            # Calculate wait time for next token
            rate = self._get_rate(portal)
            deficit = 1.0 - self._tokens[portal]
            wait_seconds = deficit / rate

        await asyncio.sleep(wait_seconds)

        async with self._lock:
            self._refill(portal)
            self._tokens[portal] -= 1.0

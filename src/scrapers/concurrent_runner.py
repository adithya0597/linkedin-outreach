"""Concurrent scan runner with serialized DB writes, timeouts, and circuit breakers."""

import asyncio
import logging
from dataclasses import dataclass

from src.scrapers.base_scraper import ScrapeResult
from src.scrapers.circuit_breaker import CircuitBreaker


@dataclass
class ScanResult:
    """Legacy result type for backward compatibility with C3 tests."""
    portal: str
    entries: list
    error: str | None = None
    duration: float = 0.0

logger = logging.getLogger(__name__)

# Per-scraper timeout (seconds)
SCRAPER_TIMEOUT = 120


class ConcurrentScanRunner:
    """Run multiple scrapers concurrently with circuit breakers and timeouts."""

    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.results_queue: asyncio.Queue = asyncio.Queue()
        self.results: list[ScrapeResult] = []
        self._breakers: dict[str, CircuitBreaker] = {}

    def _get_breaker(self, portal: str) -> CircuitBreaker:
        """Get or create a circuit breaker for a portal."""
        if portal not in self._breakers:
            self._breakers[portal] = CircuitBreaker(
                name=portal, failure_threshold=3, cooldown_seconds=300
            )
        return self._breakers[portal]

    async def _run_single(self, scraper, query, filters: dict) -> ScrapeResult:
        """Run a single scraper with semaphore, timeout, and circuit breaker."""
        async with self.semaphore:
            portal = getattr(scraper, "portal_name", getattr(scraper, "name", str(scraper)))
            breaker = self._get_breaker(portal)
            loop = asyncio.get_event_loop()
            start = loop.time()

            # Check circuit breaker
            if not await breaker.can_execute():
                duration = loop.time() - start
                result = ScrapeResult(
                    entries=[],
                    error_message="Circuit breaker open",
                    duration_seconds=duration,
                    outcome="skipped",
                )
                await self.results_queue.put((portal, result))
                return result

            # Check if this is an MCP stub (returns [] by design)
            scraper_class = type(scraper).__name__
            if hasattr(scraper, "_scraper"):
                scraper_class = type(scraper._scraper).__name__
            if scraper_class == "MCPPlaywrightScraper":
                duration = loop.time() - start
                result = ScrapeResult(
                    entries=[],
                    duration_seconds=duration,
                    outcome="skipped",
                    error_message="MCP stub — use /scan-* skill instead",
                )
                logger.info(f"{portal} is an MCP stub — use /scan-* skill instead")
                await self.results_queue.put((portal, result))
                return result

            try:
                # Apply per-scraper timeout
                async with asyncio.timeout(SCRAPER_TIMEOUT):
                    entries = await scraper.search(query, **filters)

                duration = loop.time() - start
                await breaker.record_success()

                outcome = "success" if entries else "no_results"
                result = ScrapeResult(
                    entries=entries or [],
                    duration_seconds=duration,
                    outcome=outcome,
                )
            except TimeoutError:
                duration = loop.time() - start
                await breaker.record_failure()
                logger.error(f"Scraper {portal} timed out after {SCRAPER_TIMEOUT}s")
                result = ScrapeResult(
                    entries=[],
                    error_message=f"Timeout ({SCRAPER_TIMEOUT}s)",
                    duration_seconds=duration,
                    outcome="timeout",
                )
            except Exception as e:
                duration = loop.time() - start
                await breaker.record_failure()
                logger.error(f"Scraper {portal} failed: {e}")
                result = ScrapeResult(
                    entries=[],
                    error_message=str(e),
                    duration_seconds=duration,
                    outcome="error",
                )
            finally:
                # Resource cleanup - close scraper if possible
                close_fn = getattr(scraper, "close", None)
                if close_fn is None:
                    # Check wrapped scraper
                    inner = getattr(scraper, "_scraper", None)
                    if inner:
                        close_fn = getattr(inner, "close", None)
                if close_fn and callable(close_fn):
                    try:
                        if asyncio.iscoroutinefunction(close_fn):
                            await close_fn()
                        else:
                            close_fn()
                    except Exception:
                        pass

            await self.results_queue.put((portal, result))
            return result

    async def _db_writer(self, persist_fn, total_scrapers: int):
        """Single consumer that serializes DB writes from the queue."""
        processed = 0
        all_entries = []
        while processed < total_scrapers:
            portal, result = await self.results_queue.get()
            self.results.append(result)
            if result.entries and result.outcome == "success":
                try:
                    persist_fn(portal, result.entries)
                except Exception as e:
                    logger.error(f"DB write failed for {portal}: {e}")
            all_entries.extend(result.entries)
            processed += 1
            self.results_queue.task_done()
        return all_entries

    async def _drain_queue(self, total_scrapers: int):
        """Drain the results queue without persisting."""
        processed = 0
        while processed < total_scrapers:
            _portal, result = await self.results_queue.get()
            self.results.append(result)
            processed += 1
            self.results_queue.task_done()

    async def run_all(self, scrapers: list, query, filters: dict, persist_fn=None):
        """Run all scrapers concurrently with serialized DB writes."""
        self.results = []

        if not scrapers:
            return []

        if persist_fn:
            consumer_task = asyncio.create_task(
                self._db_writer(persist_fn, len(scrapers))
            )
        else:
            consumer_task = asyncio.create_task(
                self._drain_queue(len(scrapers))
            )

        tasks = []
        for scraper in scrapers:
            tasks.append(asyncio.create_task(self._run_single(scraper, query, filters)))

        await asyncio.gather(*tasks, return_exceptions=True)

        if persist_fn:
            return await consumer_task

        await consumer_task
        return [e for r in self.results for e in r.entries]

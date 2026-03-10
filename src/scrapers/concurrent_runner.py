"""Concurrent scan runner with serialized DB writes."""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    portal: str
    entries: list
    error: str | None = None
    duration: float = 0.0


class ConcurrentScanRunner:
    """Run multiple scrapers concurrently with a single DB-write consumer."""

    def __init__(self, max_concurrent: int = 5):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.results_queue: asyncio.Queue = asyncio.Queue()
        self.results: list[ScanResult] = []

    async def _run_single(self, scraper, query, filters: dict):
        """Run a single scraper with semaphore limiting and error isolation."""
        async with self.semaphore:
            portal = getattr(scraper, "portal_name", getattr(scraper, "name", str(scraper)))
            loop = asyncio.get_event_loop()
            start = loop.time()
            try:
                entries = await scraper.search(query, **filters)
                duration = loop.time() - start
                result = ScanResult(portal=portal, entries=entries or [], duration=duration)
            except Exception as e:
                duration = loop.time() - start
                logger.error(f"Scraper {portal} failed: {e}")
                result = ScanResult(portal=portal, entries=[], error=str(e), duration=duration)
            await self.results_queue.put(result)
            return result

    async def _db_writer(self, persist_fn, total_scrapers: int):
        """Single consumer that serializes DB writes from the queue."""
        processed = 0
        all_entries = []
        while processed < total_scrapers:
            result = await self.results_queue.get()
            self.results.append(result)
            if result.entries and not result.error:
                try:
                    persist_fn(result.portal, result.entries)
                except Exception as e:
                    logger.error(f"DB write failed for {result.portal}: {e}")
            all_entries.extend(result.entries)
            processed += 1
            self.results_queue.task_done()
        return all_entries

    async def _drain_queue(self, total_scrapers: int):
        """Drain the results queue without persisting (no persist_fn case)."""
        processed = 0
        while processed < total_scrapers:
            result = await self.results_queue.get()
            self.results.append(result)
            processed += 1
            self.results_queue.task_done()

    async def run_all(self, scrapers: list, query, filters: dict, persist_fn=None):
        """Run all scrapers concurrently with serialized DB writes."""
        self.results = []

        if not scrapers:
            return []

        # Start queue consumer (DB writer or simple drain)
        if persist_fn:
            consumer_task = asyncio.create_task(
                self._db_writer(persist_fn, len(scrapers))
            )
        else:
            consumer_task = asyncio.create_task(
                self._drain_queue(len(scrapers))
            )

        # Start all scrapers concurrently
        tasks = []
        for scraper in scrapers:
            tasks.append(asyncio.create_task(self._run_single(scraper, query, filters)))

        # Wait for all scrapers to finish
        await asyncio.gather(*tasks, return_exceptions=True)

        # Wait for consumer to drain
        if persist_fn:
            return await consumer_task

        await consumer_task
        return [e for r in self.results for e in r.entries]

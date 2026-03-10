"""Bidirectional sync with conflict detection and resolution for Notion CRM."""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM
from src.integrations.notion_incremental import NotionSyncState
from src.integrations.notion_sync import NotionCRM, NotionSchemas

# Default lock file location
_SYNC_LOCK_DIR = Path.home() / ".cache" / "lineked-outreach"
_SYNC_LOCK_PATH = _SYNC_LOCK_DIR / "sync.lock"


class SyncLockError(Exception):
    """Raised when the sync lock cannot be acquired within the timeout."""


@contextmanager
def _sync_lock(lock_path: Path | None = None, timeout: float = 30.0):
    """Acquire an exclusive file lock for the sync pipeline.

    Uses ``fcntl.flock(LOCK_EX | LOCK_NB)`` with a polling loop so that
    a descriptive ``SyncLockError`` is raised when the timeout elapses
    instead of silently proceeding.

    The lock is **always** released in the ``finally`` block, even when
    the caller raises an exception.
    """
    if lock_path is None:
        lock_path = _SYNC_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                logger.debug("Sync lock acquired: {}", lock_path)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise SyncLockError(
                        f"Could not acquire sync lock at {lock_path} "
                        f"within {timeout}s — another sync process may be running."
                    )
                time.sleep(0.1)
        yield fd
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


class ConflictStrategy(str, Enum):
    LOCAL_WINS = "LOCAL_WINS"
    NOTION_WINS = "NOTION_WINS"
    NEWEST_WINS = "NEWEST_WINS"


# Derived from NotionSchemas._FIELD_MAP, excluding identity/timestamp fields.
_NON_SYNC_ORM_FIELDS = {"name", "created_at", "updated_at"}
_SYNC_FIELDS = [
    orm_field
    for orm_field, _ in NotionSchemas._FIELD_MAP.values()
    if orm_field not in _NON_SYNC_ORM_FIELDS
]


class NotionBidirectionalSync:
    """Pull from Notion, detect field-level conflicts against local DB, and merge.

    Also pushes locally-modified records back to Notion.
    """

    def __init__(
        self,
        api_key: str,
        database_id: str,
        session: Session,
        sync_state_path: str = "data/notion_sync_state.json",
    ):
        self.notion = NotionCRM(api_key=api_key, database_id=database_id)
        self.session = session
        self.sync_state = NotionSyncState(state_path=sync_state_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def pull_updates(self) -> list[dict]:
        """Fetch all records from Notion via NotionCRM.pull_all()."""
        logger.info("Pulling all records from Notion")
        records = await self.notion.pull_all()
        logger.info("Pulled {} records from Notion", len(records))
        return records

    async def pull_incremental(self) -> list[dict]:
        """Pull only records changed since last sync. Falls back to full pull."""
        last_sync = self.sync_state.get_last_sync()
        if last_sync is None:
            logger.info("No previous sync state; falling back to full pull")
            return await self.pull_updates()

        logger.info("Incremental pull: fetching pages edited after {}", last_sync)
        pages = await self.notion.pull_since(last_sync)
        logger.info("Incremental pull returned {} pages", len(pages))
        return pages

    def detect_conflicts(self, pulled: list[dict]) -> list[dict]:
        """Compare pulled Notion records against local CompanyORM rows.

        A conflict exists when both sides changed the same field since
        the last sync (i.e., both local and Notion have non-matching values
        AND both were updated after their previous common state).

        Returns a list of per-field conflict dicts.
        """
        conflicts: list[dict] = []

        # Bulk-load all local companies into a dict for O(1) lookups
        all_companies = {c.name: c for c in self.session.query(CompanyORM).all()}

        for record in pulled:
            company_name = record.get("name")
            if not company_name:
                continue

            local: CompanyORM | None = all_companies.get(company_name)
            if local is None:
                # New company from Notion -- no conflict possible
                continue

            notion_updated = _parse_dt(record.get("_notion_updated"))
            local_updated = local.updated_at

            # Only flag a conflict when BOTH sides were modified
            if notion_updated is None or local_updated is None:
                continue

            for field in _SYNC_FIELDS:
                local_value = getattr(local, field, None)
                notion_value = record.get(field)

                # Only compare if Notion actually provides this field
                if field not in record:
                    continue

                local_norm = _normalise(local_value)
                notion_norm = _normalise(notion_value)

                if local_norm != notion_norm:
                    conflicts.append(
                        {
                            "company_name": company_name,
                            "field": field,
                            "local_value": local_value,
                            "notion_value": notion_value,
                            "local_updated": local_updated.isoformat()
                            if local_updated
                            else None,
                            "notion_updated": notion_updated.isoformat()
                            if notion_updated
                            else None,
                        }
                    )

        logger.info("Detected {} field-level conflicts", len(conflicts))
        return conflicts

    def merge(
        self,
        conflicts: list[dict],
        strategy: str = ConflictStrategy.NEWEST_WINS,
    ) -> dict:
        """Apply a merge strategy to resolve conflicts and update local DB.

        Returns summary stats.
        """
        strategy = ConflictStrategy(strategy)
        stats = {
            "merged": 0,
            "local_kept": 0,
            "notion_kept": 0,
            "fields_updated": {},
        }

        # Group conflicts by company for batch update
        by_company: dict[str, list[dict]] = {}
        for c in conflicts:
            by_company.setdefault(c["company_name"], []).append(c)

        # Bulk-load companies involved in conflicts for O(1) lookups
        company_names = list(by_company.keys())
        company_map = {
            c.name: c
            for c in self.session.query(CompanyORM)
            .filter(CompanyORM.name.in_(company_names))
            .all()
        }

        for company_name, field_conflicts in by_company.items():
            local: CompanyORM | None = company_map.get(company_name)
            if local is None:
                continue

            for c in field_conflicts:
                winner = _pick_winner(c, strategy)
                if winner == "notion":
                    setattr(local, c["field"], c["notion_value"])
                    stats["notion_kept"] += 1
                    stats["fields_updated"].setdefault(company_name, []).append(
                        c["field"]
                    )
                else:
                    stats["local_kept"] += 1
                stats["merged"] += 1

        self.session.commit()
        logger.info("Merge complete: {}", stats)
        return stats

    async def push_updates(self, dry_run: bool = False) -> dict:
        """Push locally-modified records to Notion.

        Only pushes records where last_synced_at is None or < updated_at.
        After a successful push, stamps last_synced_at = now.
        """
        all_companies = self.session.query(CompanyORM).all()

        # Filter to dirty records (never synced, or updated since last sync)
        dirty = []
        skipped = 0
        for c in all_companies:
            if c.last_synced_at is not None and c.updated_at is not None:
                if c.last_synced_at >= c.updated_at:
                    skipped += 1
                    continue
            dirty.append(c)

        if dry_run:
            logger.info(
                "push_updates dry_run: {} records would be pushed", len(dirty)
            )
            return {
                "pushed": len(dirty),
                "push_errors": [],
                "skipped": skipped,
            }

        # Push dirty records
        push_errors: list[str] = []
        pushed = 0
        for company in dirty:
            try:
                await self.notion.sync_company(company)
                company.last_synced_at = datetime.now()
                pushed += 1
            except Exception as e:
                push_errors.append(f"{company.name}: {e}")

        self.session.commit()

        logger.info(
            "push_updates complete: pushed={}, errors={}, skipped={}",
            pushed,
            len(push_errors),
            skipped,
        )
        return {"pushed": pushed, "push_errors": push_errors, "skipped": skipped}

    async def full_sync(
        self,
        strategy: str = ConflictStrategy.NEWEST_WINS,
        dry_run: bool = False,
        lock_timeout: float = 30.0,
    ) -> dict:
        """End-to-end sync pipeline: pull -> detect conflicts -> merge -> push.

        Uses incremental pull when a previous sync timestamp is available.
        Uses parallel push via push_all_parallel.

        When *dry_run* is True, conflicts are detected but NOT merged,
        and push counts records but does not actually push.

        An exclusive file lock is held for the entire pipeline to prevent
        concurrent sync processes from interleaving.  If the lock cannot
        be acquired within *lock_timeout* seconds (default 30), a
        ``SyncLockError`` is raised.
        """
        with _sync_lock(timeout=lock_timeout):
            # Use incremental pull if we have sync state, otherwise full pull
            last_sync = self.sync_state.get_last_sync()
            if last_sync is not None:
                logger.info("Using incremental pull (since {})", last_sync)
                pulled = await self.pull_incremental()
            else:
                pulled = await self.pull_updates()

            # Upsert new companies that don't exist locally
            new_count = self._upsert_new_companies(pulled, dry_run=dry_run)

            conflicts = self.detect_conflicts(pulled)

            merge_result: dict = {}
            if not dry_run and conflicts:
                merge_result = self.merge(conflicts, strategy=strategy)

            # Push locally-modified records to Notion (uses parallel push)
            push_result = await self.push_updates(dry_run=dry_run)

            # Update sync state after successful sync
            if not dry_run:
                self.sync_state.update_last_sync()

            return {
                "pulled": len(pulled),
                "new_companies": new_count,
                "conflicts_found": len(conflicts),
                "merged": merge_result.get("merged", 0),
                "strategy_used": strategy,
                "dry_run": dry_run,
                "pushed": push_result["pushed"],
                "push_errors": push_result["push_errors"],
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert_new_companies(
        self, pulled: list[dict], dry_run: bool = False
    ) -> int:
        """Create local CompanyORM rows for Notion records not yet in DB."""
        # Bulk-load existing names for O(1) lookups
        existing_names = {
            row[0] for row in self.session.query(CompanyORM.name).all()
        }

        created = 0
        for record in pulled:
            company_name = record.get("name")
            if not company_name:
                continue

            if company_name in existing_names:
                continue

            if dry_run:
                created += 1
                continue

            new_company = CompanyORM(name=company_name)
            for field in _SYNC_FIELDS:
                value = record.get(field)
                if value is not None:
                    setattr(new_company, field, value)
            self.session.add(new_company)
            existing_names.add(company_name)
            created += 1

        if not dry_run:
            self.session.commit()
        logger.info("Upserted {} new companies from Notion", created)
        return created


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _parse_dt(value) -> datetime | None:
    """Parse an ISO datetime string (Notion format) or return a datetime as-is."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        # Notion uses ISO 8601 e.g. "2026-03-05T12:34:56.000Z"
        cleaned = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def _normalise(value) -> str:
    """Normalise a value to a comparable string."""
    if value is None:
        return ""
    return str(value).strip()


def _to_utc(dt: datetime) -> datetime:
    """Normalise a datetime to UTC-aware for consistent comparison."""
    from datetime import timezone

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pick_winner(conflict: dict, strategy: ConflictStrategy) -> str:
    """Return 'local' or 'notion' based on strategy."""
    if strategy == ConflictStrategy.LOCAL_WINS:
        return "local"
    if strategy == ConflictStrategy.NOTION_WINS:
        return "notion"

    # NEWEST_WINS -- compare timestamps in UTC
    local_dt = _parse_dt(conflict.get("local_updated"))
    notion_dt = _parse_dt(conflict.get("notion_updated"))

    if local_dt and notion_dt:
        local_utc = _to_utc(local_dt)
        notion_utc = _to_utc(notion_dt)
        return "local" if local_utc >= notion_utc else "notion"
    if local_dt:
        return "local"
    if notion_dt:
        return "notion"
    return "local"  # default tie-break

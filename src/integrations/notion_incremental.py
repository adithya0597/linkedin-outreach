"""Notion incremental sync -- track last sync time, pull only changed pages."""

from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path

from loguru import logger


class NotionSyncState:
    """Manage sync state (last sync timestamp) in a JSON file.

    All reads and writes use ``fcntl.flock()`` to prevent concurrent
    corruption when multiple processes sync simultaneously.
    """

    def __init__(self, state_path: str = "data/notion_sync_state.json"):
        self._path = Path(state_path)

    def get_last_sync(self) -> str | None:
        """Get ISO timestamp of last sync, or None if never synced."""
        if not self._path.exists():
            return None
        try:
            return self._locked_read().get("last_sync")
        except (json.JSONDecodeError, OSError):
            return None

    def update_last_sync(self, timestamp: str | None = None) -> None:
        """Update last sync timestamp. Defaults to now."""
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        self._path.parent.mkdir(parents=True, exist_ok=True)

        self._locked_write(timestamp)
        logger.info(f"Sync state updated: {timestamp}")

    def reset(self) -> None:
        """Reset sync state (delete the file)."""
        if self._path.exists():
            self._path.unlink()
            logger.info("Sync state reset")

    def get_status(self) -> dict:
        """Get full sync status info."""
        last = self.get_last_sync()
        return {
            "last_sync": last,
            "state_file": str(self._path),
            "has_synced": last is not None,
        }

    # ------------------------------------------------------------------
    # File-locked I/O helpers
    # ------------------------------------------------------------------

    def _locked_read(self) -> dict:
        """Read the JSON state file under a shared (read) lock."""
        with open(self._path) as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _locked_write(self, timestamp: str) -> None:
        """Read-modify-write the JSON state file under an exclusive lock.

        Opens the file in ``r+`` mode (or creates it) and holds
        ``LOCK_EX`` for the entire read-modify-write cycle.
        """
        # Ensure file exists so we can open in r+ mode
        if not self._path.exists():
            self._path.write_text("{}")

        with open(self._path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                try:
                    data = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    data = {}
                data["last_sync"] = timestamp
                data["updated_at"] = datetime.now().isoformat()
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

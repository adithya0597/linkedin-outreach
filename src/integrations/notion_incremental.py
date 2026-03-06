"""Notion incremental sync -- track last sync time, pull only changed pages."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger


class NotionSyncState:
    """Manage sync state (last sync timestamp) in a JSON file."""

    def __init__(self, state_path: str = "data/notion_sync_state.json"):
        self._path = Path(state_path)

    def get_last_sync(self) -> str | None:
        """Get ISO timestamp of last sync, or None if never synced."""
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            return data.get("last_sync")
        except (json.JSONDecodeError, OSError):
            return None

    def update_last_sync(self, timestamp: str | None = None) -> None:
        """Update last sync timestamp. Defaults to now."""
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        self._path.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {}

        data["last_sync"] = timestamp
        data["updated_at"] = datetime.now().isoformat()
        self._path.write_text(json.dumps(data, indent=2))
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

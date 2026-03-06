"""Tests for NotionSyncState -- incremental sync state management."""

import json

import pytest

from src.integrations.notion_incremental import NotionSyncState


class TestNotionSyncState:
    """Verify sync state persistence via JSON file."""

    def test_get_last_sync_no_file(self, tmp_path):
        """get_last_sync returns None when state file does not exist."""
        state = NotionSyncState(state_path=str(tmp_path / "nonexistent.json"))
        assert state.get_last_sync() is None

    def test_update_last_sync_creates_file(self, tmp_path):
        """update_last_sync creates the JSON file and stores a timestamp."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))

        state.update_last_sync()

        assert path.exists()
        data = json.loads(path.read_text())
        assert "last_sync" in data
        assert data["last_sync"] is not None
        assert "updated_at" in data

    def test_get_last_sync_after_update(self, tmp_path):
        """get_last_sync returns the timestamp written by update_last_sync."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))

        state.update_last_sync()
        result = state.get_last_sync()

        assert result is not None
        assert isinstance(result, str)
        # Should be an ISO-ish timestamp
        assert "T" in result or "-" in result

    def test_update_last_sync_explicit_timestamp(self, tmp_path):
        """update_last_sync with an explicit timestamp stores that exact value."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))
        explicit = "2026-03-05T12:00:00"

        state.update_last_sync(timestamp=explicit)
        result = state.get_last_sync()

        assert result == explicit

    def test_reset_removes_file(self, tmp_path):
        """reset deletes the state file and get_last_sync returns None."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))

        state.update_last_sync("2026-03-05T12:00:00")
        assert path.exists()

        state.reset()
        assert not path.exists()
        assert state.get_last_sync() is None

    def test_get_status_returns_correct_dict(self, tmp_path):
        """get_status returns a dict with last_sync, state_file, has_synced."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))

        # Before any sync
        status = state.get_status()
        assert status["last_sync"] is None
        assert status["state_file"] == str(path)
        assert status["has_synced"] is False

        # After sync
        state.update_last_sync("2026-03-05T12:00:00")
        status = state.get_status()
        assert status["last_sync"] == "2026-03-05T12:00:00"
        assert status["has_synced"] is True

    def test_handles_corrupt_json_gracefully(self, tmp_path):
        """get_last_sync returns None when file contains invalid JSON."""
        path = tmp_path / "state.json"
        path.write_text("{not valid json!!!}")
        state = NotionSyncState(state_path=str(path))

        result = state.get_last_sync()
        assert result is None

    def test_update_preserves_existing_data(self, tmp_path):
        """update_last_sync preserves other keys in the JSON file."""
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"custom_key": "custom_value"}))
        state = NotionSyncState(state_path=str(path))

        state.update_last_sync("2026-03-05T15:00:00")

        data = json.loads(path.read_text())
        assert data["custom_key"] == "custom_value"
        assert data["last_sync"] == "2026-03-05T15:00:00"

    def test_reset_when_no_file_is_noop(self, tmp_path):
        """reset on nonexistent file does not raise."""
        state = NotionSyncState(state_path=str(tmp_path / "missing.json"))
        state.reset()  # should not raise

    def test_creates_parent_directories(self, tmp_path):
        """update_last_sync creates intermediate directories as needed."""
        path = tmp_path / "nested" / "dir" / "state.json"
        state = NotionSyncState(state_path=str(path))

        state.update_last_sync("2026-01-01T00:00:00")

        assert path.exists()
        assert state.get_last_sync() == "2026-01-01T00:00:00"

"""Tests for Calendar MCP bridge."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from src.integrations.calendar_bridge import CalendarBridge


@pytest.fixture
def bridge():
    return CalendarBridge()


class TestCreateFollowupEvent:
    def test_returns_gcal_compatible_dict(self, bridge):
        event = bridge.create_followup_event("Acme AI", "Jane Doe")

        assert "summary" in event
        assert "description" in event
        assert "start" in event
        assert "end" in event
        assert "metadata" in event
        assert event["summary"] == "Follow-up: Acme AI (Jane Doe)"
        assert "Jane Doe" in event["description"]
        assert "Acme AI" in event["description"]
        assert event["start"]["timeZone"] == "America/Chicago"
        assert event["end"]["timeZone"] == "America/Chicago"
        assert event["metadata"]["company"] == "Acme AI"
        assert event["metadata"]["contact"] == "Jane Doe"
        assert event["metadata"]["source"] == "positive_response"

    def test_skips_weekends(self, bridge):
        # Find a Thursday so that +1 day = Friday, +2 = Saturday, +3 = Sunday
        # We need to test that if the target lands on a weekend, it moves to Monday
        # Use a fixed datetime: pick a Friday
        with patch("src.integrations.calendar_bridge.datetime") as mock_dt:
            # Friday March 6, 2026 is actually a Friday
            friday = datetime(2026, 3, 6, 12, 0, 0)
            mock_dt.now.return_value = friday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            # days_out=1 -> Saturday -> should skip to Monday
            event = bridge.create_followup_event("TestCo", "Bob", days_out=1)
            start_dt = datetime.fromisoformat(event["start"]["dateTime"])
            # Saturday should be skipped to Monday
            assert start_dt.weekday() == 0  # Monday
            assert start_dt.day == 9  # March 9, 2026

    def test_event_times_correct(self, bridge):
        with patch("src.integrations.calendar_bridge.datetime") as mock_dt:
            wednesday = datetime(2026, 3, 4, 15, 30, 0)
            mock_dt.now.return_value = wednesday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            event = bridge.create_followup_event("TestCo", "Alice", days_out=1)
            start_dt = datetime.fromisoformat(event["start"]["dateTime"])
            end_dt = datetime.fromisoformat(event["end"]["dateTime"])

            # Should be 10:00 AM start
            assert start_dt.hour == 10
            assert start_dt.minute == 0
            assert start_dt.second == 0

            # Should be 30 minutes later (10:30 AM)
            assert end_dt.hour == 10
            assert end_dt.minute == 30
            assert (end_dt - start_dt).total_seconds() == 1800


class TestCreateFromPositive:
    def test_includes_response_text(self, bridge):
        response = "Thanks for reaching out! Let's schedule a call next week."
        event = bridge.create_from_positive("Acme AI", "Jane Doe", response)

        assert "Response excerpt:" in event["description"]
        assert "schedule a call" in event["description"]

    def test_truncates_long_response(self, bridge):
        long_response = "A" * 500
        event = bridge.create_from_positive("TestCo", "Bob", long_response)

        # Should truncate to 200 chars
        excerpt_part = event["description"].split("Response excerpt: ")[1]
        assert len(excerpt_part) == 200


class TestSavePendingEvents:
    def test_creates_file(self, bridge, tmp_path):
        path = str(tmp_path / "events.json")
        events = [bridge.create_followup_event("Acme AI", "Jane")]

        count = bridge.save_pending_events(events, path=path)
        assert count == 1

        saved = json.loads((tmp_path / "events.json").read_text())
        assert len(saved) == 1
        assert saved[0]["summary"] == "Follow-up: Acme AI (Jane)"

    def test_appends_to_existing(self, bridge, tmp_path):
        path = str(tmp_path / "events.json")
        existing = [{"summary": "Old event"}]
        (tmp_path / "events.json").write_text(json.dumps(existing))

        new_events = [bridge.create_followup_event("NewCo", "Bob")]
        count = bridge.save_pending_events(new_events, path=path)
        assert count == 1

        all_events = json.loads((tmp_path / "events.json").read_text())
        assert len(all_events) == 2
        assert all_events[0]["summary"] == "Old event"
        assert "NewCo" in all_events[1]["summary"]


class TestLoadPendingEvents:
    def test_empty_when_no_file(self, bridge, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        result = bridge.load_pending_events(path=path)
        assert result == []

    def test_reads_saved_events(self, bridge, tmp_path):
        path = str(tmp_path / "events.json")
        data = [{"summary": "Follow-up: TestCo (Alice)"}]
        (tmp_path / "events.json").write_text(json.dumps(data))

        result = bridge.load_pending_events(path=path)
        assert len(result) == 1
        assert result[0]["summary"] == "Follow-up: TestCo (Alice)"

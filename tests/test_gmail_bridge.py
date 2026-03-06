"""Tests for Gmail MCP bridge."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.integrations.gmail_bridge import GmailBridge


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def bridge(mock_session):
    with patch("src.integrations.gmail_bridge.EmailOutreach") as MockEmail:
        instance = MockEmail.return_value
        instance.batch_prepare_emails.return_value = {
            "drafts": [],
            "skipped_no_email": 0,
            "total_stale": 0,
        }
        b = GmailBridge(mock_session)
        b._email = instance
        yield b


class TestPrepareDrafts:
    def test_returns_only_contacts_with_emails(self, bridge):
        bridge._email.batch_prepare_emails.return_value = {
            "drafts": [
                {"to": "alice@example.com", "subject": "Hi", "body": "Hello", "company": "Acme", "contact": "Alice"},
                {"to": None, "subject": "Hi", "body": "Hello", "company": "Beta", "contact": "Bob"},
                {"to": "", "subject": "Hi", "body": "Hello", "company": "Gamma", "contact": "Carol"},
            ],
            "skipped_no_email": 2,
            "total_stale": 3,
        }

        drafts = bridge.prepare_drafts()
        assert len(drafts) == 1
        assert drafts[0]["to"] == "alice@example.com"

    def test_returns_correct_gmail_format(self, bridge):
        bridge._email.batch_prepare_emails.return_value = {
            "drafts": [
                {
                    "to": "cto@startup.io",
                    "subject": "Re: AI Engineer opportunity at StartupCo",
                    "body": "Hi there,\n\nFollowing up.",
                    "company": "StartupCo",
                    "contact": "Jane Doe",
                },
            ],
            "skipped_no_email": 0,
            "total_stale": 1,
        }

        drafts = bridge.prepare_drafts()
        assert len(drafts) == 1
        d = drafts[0]
        assert d["to"] == "cto@startup.io"
        assert d["subject"] == "Re: AI Engineer opportunity at StartupCo"
        assert "Following up" in d["body"]
        assert d["metadata"]["company"] == "StartupCo"
        assert d["metadata"]["contact"] == "Jane Doe"
        assert d["metadata"]["source"] == "linkedin_followup"
        assert "prepared_at" in d["metadata"]

    def test_no_stale_returns_empty_list(self, bridge):
        bridge._email.batch_prepare_emails.return_value = {
            "drafts": [],
            "skipped_no_email": 0,
            "total_stale": 0,
        }

        drafts = bridge.prepare_drafts()
        assert drafts == []


class TestSaveDrafts:
    def test_creates_file_and_returns_count(self, bridge, tmp_path):
        path = str(tmp_path / "drafts.json")
        drafts = [
            {"to": "a@b.com", "subject": "Hi", "body": "Hello", "metadata": {}},
            {"to": "c@d.com", "subject": "Hey", "body": "World", "metadata": {}},
        ]

        count = bridge.save_drafts(drafts, path=path)
        assert count == 2
        saved = json.loads((tmp_path / "drafts.json").read_text())
        assert len(saved) == 2

    def test_appends_to_existing_file(self, bridge, tmp_path):
        path = str(tmp_path / "drafts.json")
        existing = [{"to": "old@example.com", "subject": "Old", "body": "Existing", "metadata": {}}]
        (tmp_path / "drafts.json").write_text(json.dumps(existing))

        new_drafts = [{"to": "new@example.com", "subject": "New", "body": "Fresh", "metadata": {}}]
        count = bridge.save_drafts(new_drafts, path=path)
        assert count == 1

        all_drafts = json.loads((tmp_path / "drafts.json").read_text())
        assert len(all_drafts) == 2
        assert all_drafts[0]["to"] == "old@example.com"
        assert all_drafts[1]["to"] == "new@example.com"


class TestLoadPendingDrafts:
    def test_returns_empty_when_no_file(self, bridge, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        result = bridge.load_pending_drafts(path=path)
        assert result == []

    def test_reads_saved_drafts(self, bridge, tmp_path):
        path = str(tmp_path / "drafts.json")
        data = [
            {"to": "x@y.com", "subject": "Test", "body": "Body", "metadata": {"company": "TestCo"}},
        ]
        (tmp_path / "drafts.json").write_text(json.dumps(data))

        result = bridge.load_pending_drafts(path=path)
        assert len(result) == 1
        assert result[0]["to"] == "x@y.com"
        assert result[0]["metadata"]["company"] == "TestCo"


class TestClearDrafts:
    def test_empties_file_and_returns_count(self, bridge, tmp_path):
        path = str(tmp_path / "drafts.json")
        data = [
            {"to": "a@b.com", "subject": "A", "body": "B", "metadata": {}},
            {"to": "c@d.com", "subject": "C", "body": "D", "metadata": {}},
        ]
        (tmp_path / "drafts.json").write_text(json.dumps(data))

        count = bridge.clear_drafts(path=path)
        assert count == 2

        remaining = json.loads((tmp_path / "drafts.json").read_text())
        assert remaining == []

    def test_returns_zero_when_no_file(self, bridge, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        count = bridge.clear_drafts(path=path)
        assert count == 0

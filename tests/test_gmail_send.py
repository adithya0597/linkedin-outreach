"""Tests for Gmail send flow CLI commands."""
import pytest
from unittest.mock import patch, MagicMock


def test_gmail_send_dry_run_displays_drafts():
    """gmail-send --dry-run displays drafts without send instructions."""
    from typer.testing import CliRunner
    from src.cli.main import app

    runner = CliRunner()
    mock_drafts = [{"to": "a@b.com", "subject": "Hello", "company": "TestCo", "body": "Test body"}]
    with patch("src.cli.main.gmail_send_cmd.__wrapped__", None, create=True):
        pass
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session, \
         patch("src.integrations.gmail_bridge.GmailBridge.load_pending_drafts", return_value=mock_drafts):
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["gmail-send", "--dry-run"])
        assert "TestCo" in result.output
        assert "gmail_create_draft" not in result.output


def test_gmail_send_shows_instructions():
    """gmail-send without --dry-run shows MCP instructions."""
    from typer.testing import CliRunner
    from src.cli.main import app

    runner = CliRunner()
    mock_drafts = [{"to": "a@b.com", "subject": "Hello", "company": "TestCo", "body": "Test body"}]
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session, \
         patch("src.integrations.gmail_bridge.GmailBridge.load_pending_drafts", return_value=mock_drafts):
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["gmail-send"])
        assert "gmail_create_draft" in result.output


def test_gmail_send_no_drafts():
    """gmail-send shows warning when no drafts pending."""
    from typer.testing import CliRunner
    from src.cli.main import app

    runner = CliRunner()
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session, \
         patch("src.integrations.gmail_bridge.GmailBridge.load_pending_drafts", return_value=[]):
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["gmail-send"])
        assert "No pending" in result.output


def test_gmail_mark_sent_requires_flag():
    """gmail-mark-sent without --all or --company shows error."""
    from typer.testing import CliRunner
    from src.cli.main import app

    runner = CliRunner()
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session:
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["gmail-mark-sent"])
        assert "Specify" in result.output

"""Tests for LinkedIn queue CLI commands."""
from unittest.mock import MagicMock, patch


def test_linkedin_queue_displays_messages():
    """linkedin-queue shows copy-paste formatted messages."""
    from typer.testing import CliRunner

    from src.cli.main import app

    runner = CliRunner()
    mock_queue = [
        {
            "company_name": "TestCo",
            "contact_name": "John",
            "linkedin_actions": {"profile_url": "https://linkedin.com/in/john"},
            "content": "Hello John",
            "template_type": "connection",
            "char_count": 10,
            "fit_score": 85,
            "ab_variant": None,
        }
    ]
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session, \
         patch("src.outreach.send_queue.SendQueueManager.generate_daily_queue", return_value=mock_queue), \
         patch("src.outreach.send_queue.SendQueueManager.get_rate_limit_status", return_value={"sent_this_week": 3, "limit": 100}):
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["linkedin-queue"])
        assert "Copy below" in result.output
        assert "TestCo" in result.output


def test_linkedin_queue_empty():
    """linkedin-queue shows message when queue is empty."""
    from typer.testing import CliRunner

    from src.cli.main import app

    runner = CliRunner()
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session, \
         patch("src.outreach.send_queue.SendQueueManager.generate_daily_queue", return_value=[]), \
         patch("src.outreach.send_queue.SendQueueManager.get_rate_limit_status", return_value={"sent_this_week": 0, "limit": 100}):
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["linkedin-queue"])
        assert "No messages" in result.output


def test_linkedin_status_shows_counts():
    """linkedin-status shows outreach counts by stage."""
    from typer.testing import CliRunner

    from src.cli.main import app

    runner = CliRunner()
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session, \
         patch("src.outreach.send_queue.SendQueueManager.get_outreach_status_summary", return_value={"Sent": 10, "Responded": 3, "Not Started": 5}):
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["linkedin-status"])
        assert "Sent" in result.output
        assert "30.0%" in result.output


def test_linkedin_status_empty():
    """linkedin-status shows message when no records."""
    from typer.testing import CliRunner

    from src.cli.main import app

    runner = CliRunner()
    with patch("src.db.database.get_engine"), \
         patch("src.db.database.init_db"), \
         patch("src.db.database.get_session") as mock_get_session, \
         patch("src.outreach.send_queue.SendQueueManager.get_outreach_status_summary", return_value={}):
        mock_get_session.return_value = MagicMock()
        result = runner.invoke(app, ["linkedin-status"])
        assert "No outreach" in result.output

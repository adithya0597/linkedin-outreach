"""Tests for ResponseMonitor class."""

from datetime import datetime
from unittest.mock import MagicMock, patch


class TestResponseMonitor:
    def _make_monitor(self):
        """Create a ResponseMonitor with a mock session."""
        from src.integrations.gmail_bridge import ResponseMonitor

        session = MagicMock()
        return ResponseMonitor(session), session

    def test_pending_checks_returns_sent_with_email(self):
        monitor, session = self._make_monitor()

        # Mock outreach record
        outreach = MagicMock()
        outreach.company_name = "TestCo"
        outreach.contact_name = "John Doe"
        outreach.contact_id = None
        outreach.stage = "Sent"
        outreach.sent_at = datetime(2026, 3, 1)
        outreach.created_at = datetime(2026, 3, 1)

        # Mock contact with email
        contact = MagicMock()
        contact.name = "John Doe"
        contact.email = "john@testco.com"

        # Configure session queries:
        # First call: query(OutreachORM).filter(...).all() -> [outreach]
        # Second call: query(ContactORM).filter(...).first() -> contact
        MagicMock()

        call_count = [0]

        def query_side_effect(*args):
            call_count[0] += 1
            q = MagicMock()
            if call_count[0] == 1:
                # OutreachORM query
                q.filter.return_value.all.return_value = [outreach]
            else:
                # ContactORM query
                q.filter.return_value.first.return_value = contact
            return q

        session.query.side_effect = query_side_effect

        checks = monitor.get_pending_checks()
        assert len(checks) == 1
        assert checks[0]["email"] == "john@testco.com"
        assert checks[0]["search_query"] is not None
        assert "from:john@testco.com" in checks[0]["search_query"]

    def test_pending_checks_no_email(self):
        monitor, session = self._make_monitor()

        outreach = MagicMock()
        outreach.company_name = "NoEmailCo"
        outreach.contact_name = "Jane"
        outreach.contact_id = None
        outreach.sent_at = datetime(2026, 3, 1)
        outreach.created_at = datetime(2026, 3, 1)

        contact = MagicMock()
        contact.name = "Jane"
        contact.email = None

        call_count = [0]

        def query_side_effect(*args):
            call_count[0] += 1
            q = MagicMock()
            if call_count[0] == 1:
                q.filter.return_value.all.return_value = [outreach]
            else:
                q.filter.return_value.first.return_value = contact
            return q

        session.query.side_effect = query_side_effect

        checks = monitor.get_pending_checks()
        assert len(checks) == 1
        assert checks[0]["email"] is None
        assert checks[0]["search_query"] is None

    def test_pending_checks_empty_when_no_sent(self):
        monitor, session = self._make_monitor()

        mock_q = MagicMock()
        mock_q.filter.return_value.all.return_value = []
        session.query.return_value = mock_q

        checks = monitor.get_pending_checks()
        assert checks == []

    def test_search_query_format_correct(self):
        monitor, session = self._make_monitor()

        outreach = MagicMock()
        outreach.company_name = "FmtCo"
        outreach.contact_name = "Bob"
        outreach.contact_id = None
        outreach.sent_at = datetime(2026, 2, 15)
        outreach.created_at = datetime(2026, 2, 15)

        contact = MagicMock()
        contact.name = "Bob"
        contact.email = "bob@fmt.com"

        call_count = [0]

        def query_side_effect(*args):
            call_count[0] += 1
            q = MagicMock()
            if call_count[0] == 1:
                q.filter.return_value.all.return_value = [outreach]
            else:
                q.filter.return_value.first.return_value = contact
            return q

        session.query.side_effect = query_side_effect

        checks = monitor.get_pending_checks()
        assert checks[0]["search_query"] == "from:bob@fmt.com after:2026/02/15"

    def test_process_response_delegates_to_tracker(self):
        monitor, _session = self._make_monitor()

        with patch("src.outreach.response_tracker.ResponseTracker") as MockTracker:
            mock_instance = MockTracker.return_value
            mock_instance.log_response.return_value = {"classification": "interested"}

            result = monitor.process_response("TestCo", "I'd love to chat!")

            mock_instance.log_response.assert_called_once_with("TestCo", "I'd love to chat!")
            assert result["classification"] == "interested"

    def test_check_summary_counts(self):
        monitor, _session = self._make_monitor()

        # Mock get_pending_checks to return controlled data
        with patch.object(
            monitor,
            "get_pending_checks",
            return_value=[
                {
                    "company": "Co1",
                    "contact": "A",
                    "email": "a@co1.com",
                    "sent_date": "2026-03-01",
                    "days_waiting": 5,
                    "search_query": "from:a@co1.com after:2026/03/01",
                },
                {
                    "company": "Co2",
                    "contact": "B",
                    "email": None,
                    "sent_date": "2026-02-20",
                    "days_waiting": 14,
                    "search_query": None,
                },
            ],
        ):
            summary = monitor.get_check_summary()
            assert summary["total_sent"] == 2
            assert summary["with_email"] == 1
            assert summary["without_email"] == 1
            assert summary["oldest_waiting_days"] == 14

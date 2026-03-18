"""Tests for warm-up CLI commands."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.cli.warmup_commands import app
from src.db.orm import CompanyORM, WarmUpSequenceORM

runner = CliRunner()

# Patch targets — functions are imported inside command bodies via
# `from src.db.database import ...`, so we patch at the source module.
_DB_PREFIX = "src.db.database"
_TRACKER_CLASS = "src.outreach.warmup_tracker.WarmUpTracker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(companies=None, sequences=None):
    """Create a mock session with query support."""
    session = MagicMock()
    companies = companies or []
    sequences = sequences or []

    def _query_side_effect(model):
        mock_q = MagicMock()

        if model is CompanyORM:

            def _filter_fn(*args, **kwargs):
                mock_filtered = MagicMock()
                mock_filtered.first.return_value = (
                    companies[0] if companies else None
                )
                mock_filtered.all.return_value = companies
                mock_filtered.filter.return_value = mock_filtered
                return mock_filtered

            mock_q.filter.side_effect = _filter_fn
            mock_q.first.return_value = companies[0] if companies else None
        elif model is WarmUpSequenceORM:

            def _filter_fn(*args, **kwargs):
                mock_filtered = MagicMock()
                mock_filtered.first.return_value = (
                    sequences[0] if sequences else None
                )
                mock_filtered.all.return_value = sequences
                mock_filtered.filter.return_value = mock_filtered
                return mock_filtered

            mock_q.filter.side_effect = _filter_fn
            mock_q.all.return_value = sequences
        else:
            mock_q.filter.return_value = mock_q
            mock_q.first.return_value = None
            mock_q.all.return_value = []

        return mock_q

    session.query.side_effect = _query_side_effect
    return session


def _make_company(name="TestAI", company_id=1):
    """Create a mock CompanyORM."""
    comp = MagicMock(spec=CompanyORM)
    comp.id = company_id
    comp.name = name
    return comp


def _make_sequence(company_id=1, contact_name="Alice", state="PENDING"):
    """Create a mock WarmUpSequenceORM."""
    seq = MagicMock(spec=WarmUpSequenceORM)
    seq.company_id = company_id
    seq.contact_name = contact_name
    seq.state = state
    return seq


def _patch_db(mock_session):
    """Return a context manager that patches get_engine, init_db, get_session."""
    engine_patch = patch(f"{_DB_PREFIX}.get_engine", return_value=MagicMock())
    init_patch = patch(f"{_DB_PREFIX}.init_db")
    session_patch = patch(f"{_DB_PREFIX}.get_session", return_value=mock_session)
    # Stack all three
    from contextlib import ExitStack

    stack = ExitStack()

    class _DBPatch:
        def __enter__(self):
            stack.__enter__()
            stack.enter_context(engine_patch)
            stack.enter_context(init_patch)
            stack.enter_context(session_patch)
            return self

        def __exit__(self, *args):
            stack.__exit__(*args)

    return _DBPatch()


# ---------------------------------------------------------------------------
# warmup-status tests
# ---------------------------------------------------------------------------


class TestWarmupStatus:
    """Tests for the warmup-status command."""

    def test_status_no_company_no_sequences(self):
        """Show empty state when no sequences exist."""
        session = _make_mock_session()

        with _patch_db(session):
            result = runner.invoke(app, ["warmup-status"])
            assert result.exit_code == 0
            assert "No warm-up sequences found" in result.output

    def test_status_all_sequences(self):
        """Show all sequences when no company filter given."""
        comp = _make_company()
        seq = _make_sequence(company_id=1, contact_name="Alice", state="WARMING")
        session = _make_mock_session(companies=[comp], sequences=[seq])

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.get_status.return_value = {
                "company_id": 1,
                "contact_name": "Alice",
                "state": "WARMING",
                "completed_actions": ["PROFILE_VIEW"],
                "remaining_actions": ["LIKE_POST"],
                "action_count": 1,
                "is_ready": False,
            }

            result = runner.invoke(app, ["warmup-status"])
            assert result.exit_code == 0
            assert "Alice" in result.output

    def test_status_company_not_found(self):
        """Error when company not found."""
        session = _make_mock_session(companies=[])

        with _patch_db(session):
            result = runner.invoke(app, ["warmup-status", "NonExistent"])
            assert result.exit_code == 1
            assert "not found" in result.output

    def test_status_company_with_sequences(self):
        """Show sequences for a specific company."""
        comp = _make_company(name="Snorkel AI")
        seq = _make_sequence(company_id=1, contact_name="Jane", state="READY")
        session = _make_mock_session(companies=[comp], sequences=[seq])

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.get_status.return_value = {
                "company_id": 1,
                "contact_name": "Jane",
                "state": "READY",
                "completed_actions": ["PROFILE_VIEW", "LIKE_POST"],
                "remaining_actions": [],
                "action_count": 2,
                "is_ready": True,
            }

            result = runner.invoke(app, ["warmup-status", "Snorkel"])
            assert result.exit_code == 0
            assert "Jane" in result.output
            assert "READY" in result.output

    def test_status_company_no_sequences(self):
        """Show message when company exists but has no warmup sequences."""
        comp = _make_company(name="Snorkel AI")
        session = _make_mock_session(companies=[comp], sequences=[])

        with _patch_db(session):
            result = runner.invoke(app, ["warmup-status", "Snorkel"])
            assert result.exit_code == 0
            assert "No warm-up sequences found" in result.output


# ---------------------------------------------------------------------------
# warmup-next tests
# ---------------------------------------------------------------------------


class TestWarmupNext:
    """Tests for the warmup-next command."""

    def test_next_no_actions(self):
        """Show empty state when no actions needed."""
        session = MagicMock()

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.get_daily_actions.return_value = []
            tracker.get_ready_contacts.return_value = []

            result = runner.invoke(app, ["warmup-next"])
            assert result.exit_code == 0
            assert "No warm-up actions needed" in result.output

    def test_next_with_actions(self):
        """Show recommended actions."""
        session = MagicMock()

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.get_daily_actions.return_value = [
                {
                    "company_id": 1,
                    "company_name": "Snorkel AI",
                    "contact_name": "Jane Smith",
                    "current_state": "PENDING",
                    "recommended_action": "PROFILE_VIEW",
                    "reason": "First warm-up touch -- view their profile",
                },
            ]
            tracker.get_ready_contacts.return_value = []

            result = runner.invoke(app, ["warmup-next"])
            assert result.exit_code == 0
            assert "Snorkel AI" in result.output
            assert "Jane Smith" in result.output
            assert "PROFILE_VIEW" in result.output

    def test_next_with_limit(self):
        """Limit number of actions shown."""
        session = MagicMock()

        actions = [
            {
                "company_id": i,
                "company_name": f"Company{i}",
                "contact_name": f"Contact{i}",
                "current_state": "PENDING",
                "recommended_action": "PROFILE_VIEW",
                "reason": "First touch",
            }
            for i in range(5)
        ]

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.get_daily_actions.return_value = actions
            tracker.get_ready_contacts.return_value = []

            result = runner.invoke(app, ["warmup-next", "--limit", "2"])
            assert result.exit_code == 0
            assert "Company0" in result.output
            assert "Company1" in result.output
            # Company2 should not be in output (limit=2)
            assert "Company2" not in result.output

    def test_next_shows_ready_count(self):
        """Show ready contacts count at the end."""
        session = MagicMock()

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.get_daily_actions.return_value = []
            tracker.get_ready_contacts.return_value = [
                {"company_name": "A", "contact_name": "X"},
                {"company_name": "B", "contact_name": "Y"},
            ]

            result = runner.invoke(app, ["warmup-next"])
            assert result.exit_code == 0
            assert "2 contact(s) ready for outreach" in result.output


# ---------------------------------------------------------------------------
# warmup-record tests
# ---------------------------------------------------------------------------


class TestWarmupRecord:
    """Tests for the warmup-record command."""

    def test_record_success(self):
        """Record an action successfully."""
        comp = _make_company(name="Snorkel AI")
        session = _make_mock_session(companies=[comp])

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.record_action.return_value = MagicMock()
            tracker.get_status.return_value = {
                "company_id": 1,
                "contact_name": "Jane",
                "state": "WARMING",
                "completed_actions": ["PROFILE_VIEW"],
                "remaining_actions": ["LIKE_POST"],
                "action_count": 1,
                "is_ready": False,
            }

            result = runner.invoke(
                app, ["warmup-record", "Snorkel", "Jane", "profile_view"]
            )
            assert result.exit_code == 0
            assert "Recorded PROFILE_VIEW" in result.output
            assert "WARMING" in result.output

    def test_record_invalid_action(self):
        """Reject invalid action type."""
        result = runner.invoke(
            app, ["warmup-record", "Snorkel", "Jane", "invalid_action"]
        )
        assert result.exit_code == 1
        assert "Invalid action" in result.output

    def test_record_company_not_found(self):
        """Error when company not found."""
        session = _make_mock_session(companies=[])

        with _patch_db(session):
            result = runner.invoke(
                app, ["warmup-record", "NonExistent", "Jane", "profile_view"]
            )
            assert result.exit_code == 1
            assert "not found" in result.output

    def test_record_with_notes(self):
        """Record an action with notes."""
        comp = _make_company(name="LangChain")
        session = _make_mock_session(companies=[comp])

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.record_action.return_value = MagicMock()
            tracker.get_status.return_value = {
                "company_id": 1,
                "contact_name": "Alice",
                "state": "WARMING",
                "completed_actions": ["LIKE_POST"],
                "remaining_actions": ["PROFILE_VIEW"],
                "action_count": 1,
                "is_ready": False,
            }

            result = runner.invoke(
                app,
                [
                    "warmup-record",
                    "LangChain",
                    "Alice",
                    "like_post",
                    "--notes",
                    "Liked their RAG post",
                ],
            )
            assert result.exit_code == 0
            assert "Recorded LIKE_POST" in result.output
            tracker.record_action.assert_called_once()
            # Verify notes were passed
            call_args = tracker.record_action.call_args
            assert call_args[0][3] == "Liked their RAG post"

    def test_record_shows_ready_when_complete(self):
        """Show READY message when all warm-up actions complete."""
        comp = _make_company(name="Norm AI")
        session = _make_mock_session(companies=[comp])

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.record_action.return_value = MagicMock()
            tracker.get_status.return_value = {
                "company_id": 1,
                "contact_name": "Bob",
                "state": "READY",
                "completed_actions": ["PROFILE_VIEW", "LIKE_POST"],
                "remaining_actions": [],
                "action_count": 2,
                "is_ready": True,
            }

            result = runner.invoke(
                app, ["warmup-record", "Norm", "Bob", "like_post"]
            )
            assert result.exit_code == 0
            assert "READY for outreach" in result.output

    def test_record_sent_sequence_error(self):
        """Error when trying to record action on SENT sequence."""
        from src.outreach.warmup_tracker import InvalidWarmUpTransitionError

        comp = _make_company(name="Cinder")
        session = _make_mock_session(companies=[comp])

        with _patch_db(session), patch(_TRACKER_CLASS) as MockTracker:
            tracker = MockTracker.return_value
            tracker.record_action.side_effect = InvalidWarmUpTransitionError(
                "Cannot record actions -- sequence already in SENT state."
            )

            result = runner.invoke(
                app, ["warmup-record", "Cinder", "Charlie", "profile_view"]
            )
            assert result.exit_code == 1
            assert "Cannot record action" in result.output

    def test_record_case_insensitive_action(self):
        """Action type should be case-insensitive."""
        from src.outreach.warmup_tracker import WarmUpAction

        assert WarmUpAction("PROFILE_VIEW") == WarmUpAction.PROFILE_VIEW
        assert WarmUpAction("LIKE_POST") == WarmUpAction.LIKE_POST
        assert WarmUpAction("COMMENT") == WarmUpAction.COMMENT
        assert WarmUpAction("CONNECT") == WarmUpAction.CONNECT
        assert WarmUpAction("MESSAGE") == WarmUpAction.MESSAGE


# ---------------------------------------------------------------------------
# Command registration test
# ---------------------------------------------------------------------------


class TestWarmupRegistration:
    """Tests for warmup commands registration in main CLI."""

    def test_commands_registered(self):
        """Verify all warmup commands are in the app."""
        command_names = [
            cmd.name or cmd.callback.__name__.replace("_", "-")
            for cmd in app.registered_commands
        ]
        assert "warmup-status" in command_names
        assert "warmup-next" in command_names
        assert "warmup-record" in command_names

    def test_main_app_includes_warmup(self):
        """Verify warmup commands registered in main CLI app."""
        from src.cli.main import app as main_app

        command_names = set()
        for cmd in main_app.registered_commands:
            name = cmd.name or cmd.callback.__name__.replace("_", "-")
            command_names.add(name)

        assert "warmup-status" in command_names
        assert "warmup-next" in command_names
        assert "warmup-record" in command_names

"""Tests for consolidated outreach CLI commands.

Tests both new consolidated commands and backward-compatible hidden aliases.
"""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


# ===========================================================================
# 1. draft command (consolidated: draft + draft-all)
# ===========================================================================


class TestDraftCommand:
    """Tests for the consolidated `draft` command."""

    def test_list_templates(self):
        """--list should print available templates."""
        with patch("src.outreach.template_engine.OutreachTemplateEngine") as mock_cls:
            mock_cls.return_value.list_templates.return_value = [
                "connection_request_a.j2",
                "inmail_intro.j2",
            ]
            result = runner.invoke(app, ["draft", "--list"])
            assert result.exit_code == 0
            assert "connection_request_a.j2" in result.output
            assert "inmail_intro.j2" in result.output

    def test_draft_missing_args(self):
        """draft without company AND contact should exit with code 1."""
        with patch("src.outreach.template_engine.OutreachTemplateEngine"):
            result = runner.invoke(app, ["draft"])
            assert result.exit_code == 1
            assert "required" in result.output.lower()

    def test_draft_renders_template(self):
        """draft with company + contact should render and display template."""
        mock_company = MagicMock()
        mock_company.name = "LlamaIndex"
        mock_company.role = "AI Engineer"
        mock_company.differentiators = "RAG, Graph"

        with (
            patch("src.outreach.template_engine.OutreachTemplateEngine") as mock_tmpl_cls,
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = mock_company
            mock_tmpl_cls.return_value.render.return_value = (
                "Hi Simon, I noticed LlamaIndex...",
                True,
                120,
            )

            result = runner.invoke(app, ["draft", "LlamaIndex", "Simon"])
            assert result.exit_code == 0
            assert "VALID" in result.output
            assert "120" in result.output

    def test_draft_shows_next_step_hint(self):
        """draft should show 'Next:' hint after rendering."""
        mock_company = MagicMock()
        mock_company.name = "TestCo"
        mock_company.role = "AI Engineer"
        mock_company.differentiators = "RAG"

        with (
            patch("src.outreach.template_engine.OutreachTemplateEngine") as mock_tmpl_cls,
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = mock_company
            mock_tmpl_cls.return_value.render.return_value = ("Hello", True, 5)

            result = runner.invoke(app, ["draft", "TestCo", "John"])
            assert result.exit_code == 0
            assert "outreach send" in result.output

    def test_draft_all_flag(self):
        """draft --all should invoke batch drafting."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.batch_engine.BatchOutreachEngine") as mock_batch_cls,
        ):
            mock_batch_cls.return_value.draft_all.return_value = {
                "drafted": 5,
                "skipped": 2,
                "over_limit": 1,
                "errors": [],
            }

            result = runner.invoke(app, ["draft", "--all"])
            assert result.exit_code == 0
            assert "Batch Draft" in result.output
            assert "5" in result.output

    def test_draft_all_dry_run(self):
        """draft --all --dry-run should show count without creating."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.db.database.init_db"),
        ):
            mock_query = MagicMock()
            mock_query.count.return_value = 10
            mock_query.filter.return_value = mock_query
            mock_session.return_value.query.return_value.filter.return_value = mock_query

            result = runner.invoke(app, ["draft", "--all", "--dry-run"])
            assert result.exit_code == 0
            assert "Dry run" in result.output
            assert "10" in result.output

    def test_draft_all_hidden_alias(self):
        """draft-all (old command name) should still work as hidden alias."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.batch_engine.BatchOutreachEngine") as mock_batch_cls,
        ):
            mock_batch_cls.return_value.draft_all.return_value = {
                "drafted": 3,
                "skipped": 0,
                "over_limit": 0,
                "errors": [],
            }

            result = runner.invoke(app, ["draft-all"])
            assert result.exit_code == 0
            assert "Batch Draft" in result.output


# ===========================================================================
# 2. sequence command (consolidated: outreach-sequence + auto-followup)
# ===========================================================================


class TestSequenceCommand:
    """Tests for the consolidated `sequence` command."""

    def test_sequence_builds(self):
        """sequence COMPANY CONTACT should build a 14-day sequence."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.batch_engine.BatchOutreachEngine") as mock_batch_cls,
        ):
            mock_batch_cls.return_value.build_sequence.return_value = [
                {"step": "1", "date": "2026-03-10", "day": "Tue",
                 "template": "connection_request_a.j2", "char_count": 120, "is_valid": True},
            ]

            result = runner.invoke(app, ["sequence", "LlamaIndex", "Simon"])
            assert result.exit_code == 0
            assert "Outreach Sequence" in result.output

    def test_sequence_missing_args(self):
        """sequence without company/contact and without --auto-draft should error."""
        result = runner.invoke(app, ["sequence"])
        assert result.exit_code == 1
        assert "required" in result.output.lower()

    def test_sequence_auto_draft(self):
        """sequence --auto-draft should create follow-up drafts."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.followup_manager.FollowUpManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.auto_draft_followups.return_value = {
                "drafted": 3,
                "skipped_duplicates": 1,
                "errors": [],
            }
            mock_mgr_cls.return_value.queue_followups.return_value = []

            result = runner.invoke(app, ["sequence", "--auto-draft"])
            assert result.exit_code == 0
            assert "Auto Follow-Up" in result.output
            assert "3" in result.output

    def test_outreach_sequence_hidden_alias(self):
        """outreach-sequence (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.batch_engine.BatchOutreachEngine") as mock_batch_cls,
        ):
            mock_batch_cls.return_value.build_sequence.return_value = [
                {"step": "1", "date": "2026-03-10", "day": "Tue",
                 "template": "t.j2", "char_count": 100, "is_valid": True},
            ]

            result = runner.invoke(app, ["outreach-sequence", "TestCo", "John"])
            assert result.exit_code == 0
            assert "Outreach Sequence" in result.output

    def test_auto_followup_hidden_alias(self):
        """auto-followup (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.followup_manager.FollowUpManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.auto_draft_followups.return_value = {
                "drafted": 0,
                "skipped_duplicates": 0,
                "errors": [],
            }
            mock_mgr_cls.return_value.queue_followups.return_value = []

            result = runner.invoke(app, ["auto-followup"])
            assert result.exit_code == 0
            assert "Auto Follow-Up" in result.output


# ===========================================================================
# 3. followups command (renamed from outreach-followups)
# ===========================================================================


class TestFollowupsCommand:
    """Tests for the `followups` command."""

    def test_followups_no_overdue(self):
        """followups should show green message when no overdue items."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.followup_manager.FollowUpManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.generate_daily_alert.return_value = {
                "overdue": [],
                "total_active_sequences": 0,
            }
            mock_mgr_cls.return_value.get_pending_followups.return_value = []

            result = runner.invoke(app, ["followups"])
            assert result.exit_code == 0
            assert "No overdue" in result.output

    def test_outreach_followups_hidden_alias(self):
        """outreach-followups (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.followup_manager.FollowUpManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.generate_daily_alert.return_value = {
                "overdue": [],
                "total_active_sequences": 0,
            }
            mock_mgr_cls.return_value.get_pending_followups.return_value = []

            result = runner.invoke(app, ["outreach-followups"])
            assert result.exit_code == 0
            assert "No overdue" in result.output


# ===========================================================================
# 4. send command (consolidated: send-queue + outreach-mark-sent)
# ===========================================================================


class TestSendCommand:
    """Tests for the consolidated `send` command."""

    def test_send_queue_shows_rate_limit(self):
        """send (no args) should show send queue and rate limit."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.send_queue.SendQueueManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.get_rate_limit_status.return_value = {
                "sent_this_week": 5,
                "limit": 100,
                "remaining": 95,
                "resets_on": "2026-03-17",
            }
            mock_mgr_cls.return_value.generate_daily_queue.return_value = []

            result = runner.invoke(app, ["send"])
            assert result.exit_code == 0
            assert "Weekly Rate Limit" in result.output
            assert "95" in result.output

    def test_send_mark(self):
        """send COMPANY STEP --mark should mark as sent."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.sequence_tracker.SequenceTracker") as mock_tracker_cls,
        ):
            mock_record = MagicMock()
            mock_record.stage = "Sent"
            mock_record.sent_at = "2026-03-10T09:00:00"
            mock_tracker_cls.return_value.mark_sent.return_value = mock_record

            result = runner.invoke(app, ["send", "LlamaIndex", "connection_request", "--mark"])
            assert result.exit_code == 0
            assert "Marked sent" in result.output
            assert "LlamaIndex" in result.output

    def test_send_shows_next_hint(self):
        """send should show 'Next: outreach status' hint."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.send_queue.SendQueueManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.get_rate_limit_status.return_value = {
                "sent_this_week": 0, "limit": 100, "remaining": 100, "resets_on": "2026-03-17",
            }
            mock_mgr_cls.return_value.generate_daily_queue.return_value = []

            result = runner.invoke(app, ["send"])
            assert result.exit_code == 0
            assert "outreach status" in result.output

    def test_send_queue_hidden_alias(self):
        """send-queue (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.send_queue.SendQueueManager") as mock_mgr_cls,
        ):
            mock_mgr_cls.return_value.get_rate_limit_status.return_value = {
                "sent_this_week": 0, "limit": 100, "remaining": 100, "resets_on": "2026-03-17",
            }
            mock_mgr_cls.return_value.generate_daily_queue.return_value = []

            result = runner.invoke(app, ["send-queue"])
            assert result.exit_code == 0
            assert "Weekly Rate Limit" in result.output

    def test_outreach_mark_sent_hidden_alias(self):
        """outreach-mark-sent (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.sequence_tracker.SequenceTracker") as mock_tracker_cls,
        ):
            mock_record = MagicMock()
            mock_record.stage = "Sent"
            mock_record.sent_at = "2026-03-10T09:00:00"
            mock_tracker_cls.return_value.mark_sent.return_value = mock_record

            result = runner.invoke(app, ["outreach-mark-sent", "TestCo", "connection_request"])
            assert result.exit_code == 0
            assert "Marked sent" in result.output


# ===========================================================================
# 5. respond command (consolidated: log-response, classify-response,
#    classify-llm, outreach-mark-responded)
# ===========================================================================


class TestRespondCommand:
    """Tests for the consolidated `respond` command."""

    def test_respond_logs_response(self):
        """respond COMPANY --text should log a response."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.response_tracker.ResponseTracker") as mock_tracker_cls,
        ):
            mock_tracker_cls.return_value.log_response.return_value = {
                "classification": "POSITIVE",
                "next_action": "Schedule call",
                "response_time_days": 2,
            }
            mock_tracker_cls.return_value.get_response_summary.return_value = {
                "total_responses": 1,
                "by_classification": {"POSITIVE": 1},
            }

            result = runner.invoke(app, ["respond", "LlamaIndex", "--text", "Great to connect!"])
            assert result.exit_code == 0
            assert "Response logged" in result.output
            assert "POSITIVE" in result.output

    def test_respond_classify_only(self):
        """respond --classify-only should classify without logging."""
        with patch("src.outreach.response_tracker.ResponseTracker") as mock_cls:
            mock_cls.classify_response.return_value = "POSITIVE"
            with patch("src.outreach.response_tracker._NEXT_ACTIONS", {"POSITIVE": "Follow up"}):
                result = runner.invoke(app, ["respond", "--classify-only", "Thanks for connecting!"])
                assert result.exit_code == 0
                assert "Classification" in result.output

    def test_respond_mark_responded(self):
        """respond COMPANY --mark-responded should mark as responded."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.sequence_tracker.SequenceTracker") as mock_tracker_cls,
        ):
            mock_record = MagicMock()
            mock_record.stage = "Responded"
            mock_record.response_at = "2026-03-10T10:00:00"
            mock_tracker_cls.return_value.mark_responded.return_value = mock_record

            result = runner.invoke(app, ["respond", "LlamaIndex", "--mark-responded"])
            assert result.exit_code == 0
            assert "Marked responded" in result.output

    def test_respond_missing_company(self):
        """respond without company and without --classify-only should error."""
        result = runner.invoke(app, ["respond"])
        assert result.exit_code == 1

    def test_log_response_hidden_alias(self):
        """log-response (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.response_tracker.ResponseTracker") as mock_tracker_cls,
        ):
            mock_tracker_cls.return_value.log_response.return_value = {
                "classification": "NEUTRAL",
                "next_action": "Wait",
                "response_time_days": None,
            }
            mock_tracker_cls.return_value.get_response_summary.return_value = {
                "total_responses": 1,
                "by_classification": {"NEUTRAL": 1},
            }

            result = runner.invoke(app, ["log-response", "TestCo", "--text", "Ok"])
            assert result.exit_code == 0
            assert "Response logged" in result.output

    def test_classify_response_hidden_alias(self):
        """classify-response (old name) should still work."""
        with patch("src.outreach.response_tracker.ResponseTracker") as mock_cls:
            mock_cls.classify_response.return_value = "AUTO_REPLY"
            with patch("src.outreach.response_tracker._NEXT_ACTIONS", {"AUTO_REPLY": "Ignore"}):
                result = runner.invoke(app, ["classify-response", "I am out of office"])
                assert result.exit_code == 0
                assert "Classification" in result.output

    def test_outreach_mark_responded_hidden_alias(self):
        """outreach-mark-responded (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.sequence_tracker.SequenceTracker") as mock_tracker_cls,
        ):
            mock_record = MagicMock()
            mock_record.stage = "Responded"
            mock_record.response_at = "2026-03-10T10:00:00"
            mock_tracker_cls.return_value.mark_responded.return_value = mock_record

            result = runner.invoke(app, ["outreach-mark-responded", "TestCo"])
            assert result.exit_code == 0
            assert "Marked responded" in result.output


# ===========================================================================
# 6. transition command (renamed from outreach-transition)
# ===========================================================================


class TestTransitionCommand:
    """Tests for the `transition` command."""

    def test_transition_succeeds(self):
        """transition COMPANY STAGE should transition the outreach stage."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.state_machine.OutreachStateMachine") as mock_sm_cls,
        ):
            mock_record = MagicMock()
            mock_sm_cls.return_value.transition.return_value = mock_record
            mock_sm_cls.return_value.get_audit_trail.return_value = [{"entry": 1}]

            result = runner.invoke(app, ["transition", "LlamaIndex", "Sent"])
            assert result.exit_code == 0
            assert "Transitioned" in result.output

    def test_transition_check_only(self):
        """transition --check-only should only validate."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.state_machine.OutreachStateMachine") as mock_sm_cls,
        ):
            mock_sm_cls.return_value.can_transition.return_value = True
            mock_sm_cls.return_value.get_available_transitions.return_value = ["Sent", "Declined"]

            result = runner.invoke(app, ["transition", "LlamaIndex", "Sent", "--check-only"])
            assert result.exit_code == 0
            assert "VALID" in result.output

    def test_outreach_transition_hidden_alias(self):
        """outreach-transition (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.state_machine.OutreachStateMachine") as mock_sm_cls,
        ):
            mock_sm_cls.return_value.transition.return_value = MagicMock()
            mock_sm_cls.return_value.get_audit_trail.return_value = []

            result = runner.invoke(app, ["outreach-transition", "TestCo", "Sent"])
            assert result.exit_code == 0
            assert "Transitioned" in result.output


# ===========================================================================
# 7. status command (consolidated: outreach-audit-trail + kickoff-tier1)
# ===========================================================================


class TestStatusCommand:
    """Tests for the consolidated `status` command."""

    def test_status_audit_trail(self):
        """status COMPANY should show audit trail."""
        mock_outreach = MagicMock()
        mock_outreach.company_name = "LlamaIndex"
        mock_outreach.stage = "Sent"
        mock_outreach.contact_name = "Simon"
        mock_outreach.template_type = "connection_request"
        mock_outreach.audit_trail = ""

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.db.database.init_db"),
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = mock_outreach

            result = runner.invoke(app, ["status", "LlamaIndex"])
            assert result.exit_code == 0
            assert "LlamaIndex" in result.output
            assert "Sent" in result.output

    def test_status_kickoff(self):
        """status --kickoff should run Tier 1 kickoff."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.kickoff.Tier1Kickoff") as mock_kickoff_cls,
        ):
            mock_kickoff_cls.return_value.run.return_value = {
                "companies": ["LlamaIndex", "LangChain"],
                "drafted": 2,
                "sequences_built": 2,
                "errors": [],
                "report": "All good!",
            }

            result = runner.invoke(app, ["status", "--kickoff"])
            assert result.exit_code == 0
            assert "Tier 1 Kickoff" in result.output
            assert "2" in result.output

    def test_status_missing_company(self):
        """status without company or --kickoff should error."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1

    def test_outreach_audit_trail_hidden_alias(self):
        """outreach-audit-trail (old name) should still work."""
        mock_outreach = MagicMock()
        mock_outreach.company_name = "TestCo"
        mock_outreach.stage = "Drafted"
        mock_outreach.contact_name = None
        mock_outreach.template_type = None
        mock_outreach.audit_trail = ""

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.db.database.init_db"),
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = mock_outreach

            result = runner.invoke(app, ["outreach-audit-trail", "TestCo"])
            assert result.exit_code == 0
            assert "TestCo" in result.output

    def test_kickoff_tier1_hidden_alias(self):
        """kickoff-tier1 (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.kickoff.Tier1Kickoff") as mock_kickoff_cls,
        ):
            mock_kickoff_cls.return_value.run.return_value = {
                "companies": [],
                "drafted": 0,
                "sequences_built": 0,
                "errors": [],
                "report": "",
            }

            result = runner.invoke(app, ["kickoff-tier1"])
            assert result.exit_code == 0
            assert "Tier 1 Kickoff" in result.output


# ===========================================================================
# 8. templates command (consolidated: template-stats + ab-test + template-export)
# ===========================================================================


class TestTemplatesCommand:
    """Tests for the consolidated `templates` command."""

    def test_templates_shows_stats(self):
        """templates (no flags) should show template performance."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.template_analytics.TemplateAnalytics") as mock_analytics_cls,
        ):
            mock_analytics_cls.return_value.get_template_stats.return_value = [
                {
                    "template": "connection_request_a",
                    "total_drafted": 10,
                    "total_sent": 5,
                    "total_responded": 2,
                    "response_rate": 40,
                    "avg_char_count": 150,
                },
            ]

            result = runner.invoke(app, ["templates"])
            assert result.exit_code == 0
            assert "Template Performance" in result.output
            assert "connection_request_a" in result.output

    def test_templates_ab_create(self):
        """templates --ab-create should create an A/B experiment."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.ab_testing.ABTestManager") as mock_ab_cls,
        ):
            mock_ab_cls.return_value.create_experiment.return_value = {
                "experiment_id": 1,
                "variants": ["a", "b"],
            }

            result = runner.invoke(app, [
                "templates", "--ab-create", "test_exp",
                "--ab-variants", "a,b",
            ])
            assert result.exit_code == 0
            assert "Created experiment" in result.output
            assert "test_exp" in result.output

    def test_templates_ab_list(self):
        """templates --ab-list should list experiments."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.ab_testing.ABTestManager") as mock_ab_cls,
        ):
            mock_ab_cls.return_value.list_experiments.return_value = []

            result = runner.invoke(app, ["templates", "--ab-list"])
            assert result.exit_code == 0
            assert "No experiments" in result.output

    def test_template_stats_hidden_alias(self):
        """template-stats (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.template_analytics.TemplateAnalytics") as mock_analytics_cls,
        ):
            mock_analytics_cls.return_value.get_template_stats.return_value = []

            result = runner.invoke(app, ["template-stats"])
            assert result.exit_code == 0

    def test_ab_test_hidden_alias(self):
        """ab-test (old name) should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.ab_testing.ABTestManager") as mock_ab_cls,
        ):
            mock_ab_cls.return_value.list_experiments.return_value = []

            result = runner.invoke(app, ["ab-test", "--list"])
            assert result.exit_code == 0

    def test_template_export_hidden_alias(self):
        """template-export (old name) should still work."""
        with (
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.outreach.template_analytics.TemplateAnalytics") as mock_analytics_cls,
        ):
            mock_analytics_cls.return_value.export_csv.return_value = 5

            result = runner.invoke(app, ["template-export", "/tmp/test.csv"])
            assert result.exit_code == 0
            assert "Exported" in result.output


# ===========================================================================
# 9. email-fallback command (unchanged)
# ===========================================================================


class TestEmailFallbackCommand:
    """Tests for the `email-fallback` command."""

    def test_email_fallback_no_stale(self):
        """email-fallback with no stale connections should show green message."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.integrations.email_outreach.EmailOutreach") as mock_email_cls,
        ):
            mock_email_cls.return_value.find_stale_connections.return_value = []

            result = runner.invoke(app, ["email-fallback"])
            assert result.exit_code == 0
            assert "No stale" in result.output

    def test_email_fallback_status(self):
        """email-fallback --status should show email outreach status."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.integrations.email_outreach.EmailOutreach") as mock_email_cls,
        ):
            mock_email_cls.return_value.get_email_status.return_value = {
                "total_stale": 5,
                "with_email": 3,
                "without_email": 2,
                "drafts_prepared": 1,
            }

            result = runner.invoke(app, ["email-fallback", "--status"])
            assert result.exit_code == 0
            assert "Email Outreach Status" in result.output


# ===========================================================================
# 10. schedule command (renamed from schedule-interview)
# ===========================================================================


class TestScheduleCommand:
    """Tests for the `schedule` command."""

    def test_schedule_creates_event(self):
        """schedule COMPANY CONTACT should create calendar event."""
        with patch("src.integrations.calendar_bridge.CalendarBridge") as mock_bridge_cls:
            mock_bridge_cls.return_value.create_followup_event.return_value = {
                "summary": "Follow up: LlamaIndex - Simon",
                "start": {"dateTime": "2026-03-13T10:00:00"},
                "end": {"dateTime": "2026-03-13T10:30:00"},
                "description": "Follow up on outreach",
            }

            result = runner.invoke(app, ["schedule", "LlamaIndex", "Simon"])
            assert result.exit_code == 0
            assert "Calendar event prepared" in result.output
            assert "LlamaIndex" in result.output

    def test_schedule_interview_hidden_alias(self):
        """schedule-interview (old name) should still work."""
        with patch("src.integrations.calendar_bridge.CalendarBridge") as mock_bridge_cls:
            mock_bridge_cls.return_value.create_followup_event.return_value = {
                "summary": "Follow up: TestCo - Jane",
                "start": {"dateTime": "2026-03-13T10:00:00"},
                "end": {"dateTime": "2026-03-13T10:30:00"},
                "description": "Follow up",
            }

            result = runner.invoke(app, ["schedule-interview", "TestCo", "Jane"])
            assert result.exit_code == 0
            assert "Calendar event prepared" in result.output


# ===========================================================================
# 11. Hidden alias completeness — verify all old names are registered
# ===========================================================================


class TestAllHiddenAliases:
    """Verify that all old command names are registered as hidden aliases."""

    def test_all_old_names_exist_in_app(self):
        """All 9 deprecated command names should be registered in the app."""
        from src.cli.outreach_commands import app as outreach_app

        registered_names = {
            cmd.name or cmd.callback.__name__.replace("_", "-")
            for cmd in outreach_app.registered_commands
        }

        old_names = [
            "draft-all",
            "outreach-sequence",
            "auto-followup",
            "outreach-followups",
            "send-queue",
            "outreach-mark-sent",
            "outreach-mark-responded",
            "log-response",
            "classify-response",
            "classify-llm",
            "outreach-transition",
            "outreach-audit-trail",
            "kickoff-tier1",
            "template-stats",
            "ab-test",
            "template-export",
            "schedule-interview",
        ]

        for name in old_names:
            assert name in registered_names, f"Missing hidden alias: {name}"

    def test_new_primary_commands_exist(self):
        """All 10 new primary command names should be registered."""
        from src.cli.outreach_commands import app as outreach_app

        registered_names = {
            cmd.name or cmd.callback.__name__.replace("_", "-")
            for cmd in outreach_app.registered_commands
        }

        new_names = [
            "draft",
            "sequence",
            "followups",
            "send",
            "respond",
            "transition",
            "status",
            "templates",
            "email-fallback",
            "schedule",
        ]

        for name in new_names:
            assert name in registered_names, f"Missing primary command: {name}"

    def test_command_count(self):
        """Should have 10 primary + 17 hidden = 27 total registered commands."""
        from src.cli.outreach_commands import app as outreach_app

        total = len(outreach_app.registered_commands)
        # 10 primary + 17 hidden aliases = 27
        assert total == 27, f"Expected 27 commands, got {total}"

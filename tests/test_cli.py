"""Tests for CLI commands -- typer.testing.CliRunner + mock patching.

Since CLI commands use lazy imports inside function bodies, we patch
at the source module level (e.g., src.scrapers.registry) rather than
at src.cli.main.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


# ===================================================================
# 1. scan command
# ===================================================================


class TestScanCommand:
    """Tests for the `scan` CLI command."""

    def test_dry_run_shows_portal_table(self):
        """--dry-run should show a Rich table of portal statuses."""
        with patch("src.scrapers.registry.build_default_registry") as mock_reg:
            mock_scraper = MagicMock()
            mock_scraper.name = "test_portal"
            mock_scraper.is_healthy.return_value = True
            mock_scraper.tier.value = 1
            type(mock_scraper).__bases__ = (MagicMock,)
            mock_reg.return_value.get_all_scrapers.return_value = [mock_scraper]

            result = runner.invoke(app, ["scan", "--dry-run"])
            assert result.exit_code == 0
            assert "test_portal" in result.output

    def test_unknown_portal_prints_error(self):
        """Specifying an unknown portal should print error message."""
        with patch("src.scrapers.registry.build_default_registry") as mock_reg:
            mock_reg.return_value.get_scraper.side_effect = KeyError("nope")
            mock_all = MagicMock()
            mock_all.name = "real_portal"
            mock_reg.return_value.get_all_scrapers.return_value = [mock_all]

            result = runner.invoke(app, ["scan", "--portal", "fake_portal"])
            assert result.exit_code == 0
            assert "Unknown portal" in result.output
            assert "real_portal" in result.output

    def test_tier_filter(self):
        """--tier 2 should call get_scrapers_by_tier(2)."""
        with patch("src.scrapers.registry.build_default_registry") as mock_reg:
            mock_reg.return_value.get_scrapers_by_tier.return_value = []

            result = runner.invoke(app, ["scan", "--dry-run", "--tier", "2"])
            assert result.exit_code == 0
            mock_reg.return_value.get_scrapers_by_tier.assert_called_once_with(2)

    def test_full_scan_runs(self):
        """Full scan should run async _run_scans and persist results."""
        with (
            patch("src.scrapers.registry.build_default_registry") as mock_reg,
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.db.database.init_db"),
            patch("src.scrapers.persistence.persist_scan_results", return_value=(5, 3, 2)),
            patch("builtins.open", MagicMock()),
            patch("yaml.safe_load", return_value={
                "portals": {"test": {"name": "test_portal", "search_keywords": ["AI"]}}
            }),
        ):
            mock_scraper = MagicMock()
            mock_scraper.name = "test_portal"
            mock_scraper.is_healthy.return_value = True
            mock_scraper.tier.value = 1
            mock_scraper.search = AsyncMock(return_value=[])
            mock_reg.return_value.get_all_scrapers.return_value = [mock_scraper]

            result = runner.invoke(app, ["scan"])
            assert result.exit_code == 0


# ===================================================================
# 2. validate command
# ===================================================================


class TestValidateCommand:
    """Tests for the `validate` CLI command."""

    def test_validate_prints_result(self):
        """validate should call CompanyValidator.validate_by_name and print result."""
        with patch("src.validators.company_validator.CompanyValidator") as mock_cls:
            mock_cls.return_value.validate_by_name.return_value = "PASS: LlamaIndex"
            result = runner.invoke(app, ["validate", "LlamaIndex"])
            assert result.exit_code == 0
            assert "PASS" in result.output
            mock_cls.return_value.validate_by_name.assert_called_once_with("LlamaIndex")

    def test_validate_not_found(self):
        """validate should handle company not found gracefully."""
        with patch("src.validators.company_validator.CompanyValidator") as mock_cls:
            mock_cls.return_value.validate_by_name.return_value = "Company 'FakeComp' not found"
            result = runner.invoke(app, ["validate", "FakeComp"])
            assert result.exit_code == 0
            assert "not found" in result.output


# ===================================================================
# 3. score command
# ===================================================================


class TestScoreCommand:
    """Tests for the `score` CLI command."""

    def test_score_company_found(self):
        """score should display a breakdown table when company is found."""
        mock_company = MagicMock()
        mock_company.name = "LlamaIndex"

        breakdown = MagicMock()
        breakdown.h1b_score = 15
        breakdown.criteria_score = 12
        breakdown.tech_overlap_score = 8
        breakdown.salary_score = 7
        breakdown.deterministic_total = 42
        breakdown.total = 42

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.validators.scoring_engine.FitScoringEngine") as mock_scorer_cls,
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = mock_company
            mock_scorer_cls.return_value.score.return_value = breakdown

            result = runner.invoke(app, ["score", "LlamaIndex"])
            assert result.exit_code == 0
            assert "LlamaIndex" in result.output

    def test_score_company_not_found(self):
        """score should print error when company not in DB."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = None

            result = runner.invoke(app, ["score", "NonExistent"])
            assert result.exit_code == 0
            assert "not found" in result.output

    def test_score_with_semantic(self):
        """--semantic flag should pass include_semantic=True to the scorer."""
        mock_company = MagicMock()
        mock_company.name = "Cursor"

        breakdown = MagicMock()
        breakdown.h1b_score = 15
        breakdown.criteria_score = 10
        breakdown.tech_overlap_score = 8
        breakdown.salary_score = 7
        breakdown.deterministic_total = 40
        breakdown.profile_jd_similarity = 20
        breakdown.domain_company_similarity = 18
        breakdown.semantic_total = 38
        breakdown.total = 78

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.validators.scoring_engine.FitScoringEngine") as mock_scorer_cls,
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = mock_company
            mock_scorer_cls.return_value.score.return_value = breakdown

            result = runner.invoke(app, ["score", "Cursor", "--semantic"])
            assert result.exit_code == 0
            mock_scorer_cls.return_value.score.assert_called_once_with(
                mock_company, include_semantic=True
            )


# ===================================================================
# 4. h1b command
# ===================================================================


class TestH1BCommand:
    """Tests for the `h1b` CLI command."""

    def test_h1b_single_company_found(self):
        """h1b for a single company should display status table."""
        mock_company = MagicMock()
        mock_company.name = "LlamaIndex"

        mock_record = MagicMock()
        mock_record.status.value = "Confirmed"
        mock_record.source = "Frog Hire"
        mock_record.lca_count = 5
        mock_record.approval_rate = 95.0
        mock_record.has_perm = True
        mock_record.has_everify = True

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.validators.h1b_verifier.H1BVerifier"),
            patch("asyncio.run", return_value=mock_record),
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = mock_company

            result = runner.invoke(app, ["h1b", "LlamaIndex"])
            assert result.exit_code == 0
            assert "LlamaIndex" in result.output

    def test_h1b_company_not_found(self):
        """h1b should print error for unknown company."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.validators.h1b_verifier.H1BVerifier"),
        ):
            mock_session.return_value.query.return_value.filter.return_value.first.return_value = None

            result = runner.invoke(app, ["h1b", "NonExistent"])
            assert result.exit_code == 0
            assert "not found" in result.output

    def test_h1b_batch_mode(self):
        """--batch should query unverified companies and batch verify."""
        mock_companies = [MagicMock(), MagicMock()]

        mock_record = MagicMock()
        mock_record.company_name = "Co1"
        mock_record.status.value = "Confirmed"
        mock_record.source = "Frog Hire"

        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("src.validators.h1b_verifier.H1BVerifier"),
            patch("asyncio.run", return_value=[mock_record]),
        ):
            mock_session.return_value.query.return_value.filter.return_value.all.return_value = mock_companies

            result = runner.invoke(app, ["h1b", "ignored", "--batch"])
            assert result.exit_code == 0
            assert "Batch verifying" in result.output


# ===================================================================
# 5. draft command
# ===================================================================


class TestDraftCommand:
    """Tests for the `draft` CLI command."""

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


# ===================================================================
# 6. sync-notion command
# ===================================================================


class TestSyncNotionCommand:
    """Tests for the `sync-notion` CLI command."""

    def test_missing_api_key(self):
        """sync-notion without NOTION_API_KEY should print error."""
        with (
            patch("os.getenv", return_value=""),
            patch("src.integrations.notion_sync.NotionCRM"),
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
        ):
            result = runner.invoke(app, ["sync-notion"])
            assert result.exit_code == 0
            assert "NOTION_API_KEY" in result.output

    def test_push_direction(self):
        """sync-notion --direction push should push companies to Notion."""
        with (
            patch("os.getenv", side_effect=lambda k, d="": "test-key" if k == "NOTION_API_KEY" else d),
            patch("src.integrations.notion_sync.NotionCRM"),
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session,
            patch("asyncio.run", return_value=["page_1", "page_2"]),
        ):
            mock_session.return_value.query.return_value.filter.return_value.all.return_value = [
                MagicMock(), MagicMock()
            ]

            result = runner.invoke(app, ["sync-notion", "--direction", "push"])
            assert result.exit_code == 0
            assert "Pushed" in result.output

    def test_pull_direction(self):
        """sync-notion --direction pull should pull records from Notion."""
        with (
            patch("os.getenv", side_effect=lambda k, d="": "test-key" if k == "NOTION_API_KEY" else d),
            patch("src.integrations.notion_sync.NotionCRM"),
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("asyncio.run", return_value=[
                {"name": "Company A", "tier": "Tier 1"},
                {"name": "Company B", "tier": "Tier 2"},
            ]),
        ):
            result = runner.invoke(app, ["sync-notion", "--direction", "pull"])
            assert result.exit_code == 0
            assert "Pulled" in result.output


# ===================================================================
# 7. audit command
# ===================================================================


class TestAuditCommand:
    """Tests for the `audit` CLI command."""

    def test_audit_runs(self):
        """audit should create QualityAuditor and print full_audit report."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.validators.quality_gates.QualityAuditor") as mock_auditor_cls,
        ):
            mock_auditor_cls.return_value.full_audit.return_value = "=== DATA QUALITY AUDIT ===\nTotal: 100"
            result = runner.invoke(app, ["audit"])
            assert result.exit_code == 0
            assert "AUDIT" in result.output
            mock_auditor_cls.return_value.full_audit.assert_called_once()

    def test_audit_empty_db(self):
        """audit on empty database should still work."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.validators.quality_gates.QualityAuditor") as mock_auditor_cls,
        ):
            mock_auditor_cls.return_value.full_audit.return_value = "Total companies: 0\nTotal issues: 0"
            result = runner.invoke(app, ["audit"])
            assert result.exit_code == 0
            assert "0" in result.output


# ===================================================================
# 8. dashboard command
# ===================================================================


class TestDashboardCommand:
    """Tests for the `dashboard` CLI command."""

    def test_dashboard_launches_streamlit(self):
        """dashboard should call subprocess.run with streamlit run."""
        with patch("subprocess.run") as mock_run:
            result = runner.invoke(app, ["dashboard"])
            assert result.exit_code == 0
            assert "Launching dashboard" in result.output
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "streamlit" in call_args[2]
            assert "run" in call_args[3]


# ===================================================================
# 9. seed command
# ===================================================================


class TestSeedCommand:
    """Tests for the `seed` CLI command."""

    def test_seed_default_args(self):
        """seed with defaults should call seed_database and display audit report."""
        with patch("src.db.seed.seed_database") as mock_seed:
            mock_seed.return_value = {
                "total_parsed": 100,
                "inserted": 95,
                "disqualified": ["Harvey AI"],
                "borderline": ["Cursor"],
                "skeleton_records": ["10a Labs"],
                "tier_mismatches": [],
            }
            result = runner.invoke(app, ["seed"])
            assert result.exit_code == 0
            assert "100" in result.output
            assert "95" in result.output
            mock_seed.assert_called_once_with("Startup_Target_List.md", "data/outreach.db")

    def test_seed_custom_args(self):
        """seed with custom --target-list and --db-path."""
        with patch("src.db.seed.seed_database") as mock_seed:
            mock_seed.return_value = {
                "total_parsed": 50,
                "inserted": 48,
                "disqualified": [],
                "borderline": [],
                "skeleton_records": [],
                "tier_mismatches": [],
            }
            result = runner.invoke(
                app, ["seed", "--target-list", "custom.md", "--db-path", "custom.db"]
            )
            assert result.exit_code == 0
            mock_seed.assert_called_once_with("custom.md", "custom.db")

    def test_seed_shows_disqualified(self):
        """seed should display disqualified companies in output."""
        with patch("src.db.seed.seed_database") as mock_seed:
            mock_seed.return_value = {
                "total_parsed": 10,
                "inserted": 8,
                "disqualified": ["BadCo1", "BadCo2"],
                "borderline": [],
                "skeleton_records": [],
                "tier_mismatches": [],
            }
            result = runner.invoke(app, ["seed"])
            assert result.exit_code == 0
            assert "Disqualified" in result.output


# ===================================================================
# 10. stats command
# ===================================================================


class TestStatsCommand:
    """Tests for the `stats` CLI command."""

    def test_stats_displays_metrics(self):
        """stats should show total, disqualified, needs_review, avg_completeness."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session") as mock_session_fn,
        ):
            mock_sess = mock_session_fn.return_value

            scalar_results = [100, 5, 10, 75.5]
            call_count = {"n": 0}

            def query_side_effect(*args):
                mock_q = MagicMock()
                idx = call_count["n"]
                call_count["n"] += 1

                if idx < 4:
                    mock_q.scalar.return_value = scalar_results[idx]
                    mock_q.filter.return_value = mock_q
                else:
                    # Tier breakdown query
                    mock_q.group_by.return_value.all.return_value = [
                        ("Tier 1 - HIGH", 12),
                        ("Tier 2 - STRONG", 25),
                    ]
                return mock_q

            mock_sess.query.side_effect = query_side_effect

            result = runner.invoke(app, ["stats"])
            assert result.exit_code == 0
            assert "Database Statistics" in result.output


# ===================================================================
# 11. run-pipeline command
# ===================================================================


class TestRunPipelineCommand:
    """Tests for the `run-pipeline` CLI command."""

    def test_pipeline_default_run(self):
        """run-pipeline with no flags should run validate + score, skip h1b."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.pipeline.orchestrator.Pipeline") as mock_pipeline_cls,
        ):
            mock_pipeline_cls.return_value.run.return_value = {
                "validation": {"passed": 80, "failed": 5, "borderline": 10},
                "scoring": {
                    "scored": 80,
                    "top_10": [
                        ("LlamaIndex", 92, "Tier 1"),
                        ("Cursor", 90, "Tier 1"),
                    ],
                },
            }
            result = runner.invoke(app, ["run-pipeline"])
            assert result.exit_code == 0
            assert "Validation" in result.output
            mock_pipeline_cls.return_value.run.assert_called_once_with(
                validate=True, score=True, verify_h1b=False, include_semantic=False,
            )

    def test_pipeline_skip_flags(self):
        """--skip-validate --skip-score should pass validate=False, score=False."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.pipeline.orchestrator.Pipeline") as mock_pipeline_cls,
        ):
            mock_pipeline_cls.return_value.run.return_value = {}
            result = runner.invoke(app, ["run-pipeline", "--skip-validate", "--skip-score"])
            assert result.exit_code == 0
            mock_pipeline_cls.return_value.run.assert_called_once_with(
                validate=False, score=False, verify_h1b=False, include_semantic=False,
            )

    def test_pipeline_with_h1b_and_semantic(self):
        """--h1b --semantic should pass verify_h1b=True, include_semantic=True."""
        with (
            patch("src.db.database.get_engine"),
            patch("src.db.database.get_session"),
            patch("src.pipeline.orchestrator.Pipeline") as mock_pipeline_cls,
        ):
            mock_pipeline_cls.return_value.run.return_value = {
                "h1b": {"verified": 50, "confirmed": 30, "explicit_no": 5, "unknown": 15},
            }
            result = runner.invoke(app, ["run-pipeline", "--h1b", "--semantic"])
            assert result.exit_code == 0
            assert "H1B Verification" in result.output
            mock_pipeline_cls.return_value.run.assert_called_once_with(
                validate=True, score=True, verify_h1b=True, include_semantic=True,
            )


# ===================================================================
# 12. No-args help
# ===================================================================


class TestAppHelp:
    """Tests for top-level app behavior."""

    def test_no_args_shows_help(self):
        """Calling app with no args should show help (no_args_is_help=True).

        Typer returns exit_code=0 for no_args_is_help=True on some versions.
        """
        result = runner.invoke(app, [])
        # no_args_is_help may return 0 or 2 depending on typer/click version
        assert result.exit_code in (0, 2)
        assert "Usage" in result.output or "scan" in result.output

    def test_help_flag(self):
        """--help should show all available commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "scan" in result.output
        assert "validate" in result.output
        assert "score" in result.output
        assert "seed" in result.output

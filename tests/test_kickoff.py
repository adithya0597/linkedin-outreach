"""Tests for Tier 1 kickoff workflow — get_ready_companies, run, generate_send_report."""

from unittest.mock import patch

import pytest

from src.db.orm import CompanyORM, ContactORM, OutreachORM
from src.outreach.kickoff import Tier1Kickoff


@pytest.fixture
def tier1_company(session):
    company = CompanyORM(
        name="AlphaCorp",
        description="AI startup",
        tier="Tier 1 - HIGH",
        h1b_status="Confirmed",
        role="AI Engineer",
        fit_score=90.0,
        is_disqualified=False,
        differentiators="graph,rag",
        linkedin_url="https://linkedin.com/company/alphacorp",
    )
    session.add(company)
    session.flush()
    return company


@pytest.fixture
def tier1_contact(session, tier1_company):
    contact = ContactORM(
        name="Alice CTO",
        title="CTO",
        company_id=tier1_company.id,
        company_name="AlphaCorp",
        contact_score=9.0,
    )
    session.add(contact)
    session.flush()
    return contact


@pytest.fixture
def disqualified_company(session):
    company = CompanyORM(
        name="BadCorp",
        tier="Tier 1 - HIGH",
        is_disqualified=True,
        disqualification_reason="Staffing firm",
        differentiators="",
    )
    session.add(company)
    session.flush()
    return company


@pytest.fixture
def tier2_company(session):
    company = CompanyORM(
        name="MidCorp",
        tier="Tier 2 - STRONG",
        fit_score=80.0,
        is_disqualified=False,
        differentiators="infrastructure",
    )
    session.add(company)
    session.flush()
    return company


def _mock_render(template_name, context, message_type="follow_up"):
    text = f"Hi from {template_name}"
    return text, True, len(text)


class TestGetReadyCompanies:
    def test_returns_tier1_not_disqualified(self, session, tier1_company):
        """get_ready_companies returns Tier 1, non-disqualified companies."""
        kickoff = Tier1Kickoff(session)
        ready = kickoff.get_ready_companies()
        assert len(ready) == 1
        assert ready[0]["company"].name == "AlphaCorp"

    def test_skips_existing_outreach(self, session, tier1_company):
        """Companies with existing OutreachORM records are skipped."""
        outreach = OutreachORM(
            company_id=tier1_company.id,
            company_name="AlphaCorp",
            stage="Not Started",
            sequence_step="connection_request",
        )
        session.add(outreach)
        session.flush()

        kickoff = Tier1Kickoff(session)
        ready = kickoff.get_ready_companies()
        assert len(ready) == 0

    def test_skips_disqualified(self, session, tier1_company, disqualified_company):
        """Disqualified companies are excluded."""
        kickoff = Tier1Kickoff(session)
        ready = kickoff.get_ready_companies()
        names = [r["company"].name for r in ready]
        assert "BadCorp" not in names
        assert "AlphaCorp" in names

    def test_skips_non_tier1(self, session, tier1_company, tier2_company):
        """Non-Tier 1 companies are excluded."""
        kickoff = Tier1Kickoff(session)
        ready = kickoff.get_ready_companies()
        names = [r["company"].name for r in ready]
        assert "MidCorp" not in names

    def test_includes_contact(self, session, tier1_company, tier1_contact):
        """Ready list includes the best contact for each company."""
        kickoff = Tier1Kickoff(session)
        ready = kickoff.get_ready_companies()
        assert ready[0]["contact"].name == "Alice CTO"

    def test_no_contact_returns_none(self, session, tier1_company):
        """Company without contacts gets contact=None."""
        kickoff = Tier1Kickoff(session)
        ready = kickoff.get_ready_companies()
        assert ready[0]["contact"] is None


class TestRun:
    @patch("src.outreach.template_engine.OutreachTemplateEngine.render")
    def test_dry_run_no_records(self, mock_render, session, tier1_company, tier1_contact):
        """dry_run=True returns companies without creating OutreachORM records."""
        mock_render.return_value = ("Hello test", True, 10)
        kickoff = Tier1Kickoff(session)
        result = kickoff.run(dry_run=True)

        assert "AlphaCorp" in result["companies"]
        assert result["drafted"] == 0
        assert "(DRY RUN)" in result["report"]
        # No outreach records created
        count = session.query(OutreachORM).count()
        assert count == 0

    @patch("src.outreach.template_engine.SequenceBuilder.build_sequence")
    @patch("src.outreach.template_engine.OutreachTemplateEngine.render")
    def test_run_creates_drafts(self, mock_render, mock_seq, session, tier1_company, tier1_contact):
        """run() creates outreach drafts for Tier 1 companies."""
        mock_render.return_value = ("Hi there", True, 8)
        mock_seq.return_value = [
            {"step": "pre_engagement", "date": "2026-03-06", "day": "Day 0"},
            {"step": "connection_request", "date": "2026-03-07", "day": "Day 1"},
        ]
        kickoff = Tier1Kickoff(session)
        result = kickoff.run()

        assert result["drafted"] >= 1
        count = session.query(OutreachORM).count()
        assert count >= 1

    @patch("src.outreach.template_engine.SequenceBuilder.build_sequence")
    @patch("src.outreach.template_engine.OutreachTemplateEngine.render")
    def test_run_builds_sequences(self, mock_render, mock_seq, session, tier1_company, tier1_contact):
        """run() builds sequences when contact exists."""
        mock_render.return_value = ("Hi there", True, 8)
        mock_seq.return_value = [
            {"step": "pre_engagement", "date": "2026-03-06", "day": "Day 0"},
            {"step": "connection_request", "date": "2026-03-07", "day": "Day 1"},
        ]
        kickoff = Tier1Kickoff(session)
        result = kickoff.run()

        assert result["sequences_built"] == 1

    @patch("src.outreach.template_engine.OutreachTemplateEngine.render")
    def test_run_handles_no_contact(self, mock_render, session, tier1_company):
        """run() handles company without contact gracefully (no sequence built)."""
        mock_render.return_value = ("Hi there", True, 8)
        kickoff = Tier1Kickoff(session)
        result = kickoff.run()

        assert result["drafted"] >= 1
        assert result["sequences_built"] == 0
        assert len(result["errors"]) == 0


class TestGenerateSendReport:
    def test_produces_markdown_table(self, session, tier1_company, tier1_contact):
        """Report includes a markdown table with company rows."""
        kickoff = Tier1Kickoff(session)
        report = kickoff.generate_send_report()

        assert "# Tier 1 Kickoff Report" in report
        assert "| # | Company |" in report
        assert "AlphaCorp" in report
        assert "Alice CTO" in report

    def test_dry_run_label(self, session, tier1_company):
        """Dry run report includes (DRY RUN) label."""
        kickoff = Tier1Kickoff(session)
        ready = kickoff.get_ready_companies()
        report = kickoff.generate_send_report(ready, dry_run=True)
        assert "(DRY RUN)" in report

    def test_empty_report(self, session):
        """Report with no companies shows appropriate message."""
        kickoff = Tier1Kickoff(session)
        report = kickoff.generate_send_report([])
        assert "No Tier 1 companies ready for outreach" in report

    def test_fit_score_in_report(self, session, tier1_company):
        """Fit score appears in report table."""
        kickoff = Tier1Kickoff(session)
        report = kickoff.generate_send_report()
        assert "90" in report

    def test_total_ready_count(self, session, tier1_company):
        """Report footer includes total ready count."""
        kickoff = Tier1Kickoff(session)
        report = kickoff.generate_send_report()
        assert "**Total ready:** 1" in report

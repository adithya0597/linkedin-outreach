"""Tests for company validator and scoring engine."""

import pytest

from src.validators.company_validator import CompanyValidator, ValidationResult
from src.validators.scoring_engine import FitScoringEngine
from src.db.orm import CompanyORM


class TestCompanyValidator:
    def setup_method(self):
        self.validator = CompanyValidator()

    def test_llamaindex_passes(self, sample_valid_company):
        """LlamaIndex should PASS — Series A, <50 employees, AI-native."""
        report = self.validator.validate(sample_valid_company)
        assert report.result == ValidationResult.PASS
        assert all(c.passed for c in report.checks)

    def test_harvey_ai_fails(self, sample_failing_company):
        """Harvey AI should FAIL — Series F violates funding criteria."""
        report = self.validator.validate(sample_failing_company)
        assert report.result == ValidationResult.FAIL
        funding_check = [c for c in report.checks if "Seed" in c.name][0]
        assert not funding_check.passed

    def test_borderline_company(self, sample_borderline_company):
        """Acme AI should be BORDERLINE — Series D but named exception."""
        report = self.validator.validate(sample_borderline_company)
        assert report.result == ValidationResult.BORDERLINE

    def test_tier3_h1b_autopass(self, sample_tier3_company):
        """Tier 3 company should auto-pass H1B check."""
        report = self.validator.validate(sample_tier3_company)
        h1b_check = [c for c in report.checks if "H1B" in c.name][0]
        assert h1b_check.passed
        assert "auto-pass" in h1b_check.evidence.lower() or "n/a" in h1b_check.evidence.lower()


class TestScoringEngine:
    def setup_method(self):
        self.engine = FitScoringEngine()

    def test_deterministic_scoring(self, sample_valid_company):
        """LlamaIndex should get a high deterministic score."""
        breakdown = self.engine.score_deterministic(sample_valid_company)
        assert breakdown.h1b_score == 15  # Confirmed
        assert breakdown.criteria_score > 10  # All criteria pass
        assert breakdown.deterministic_total > 25

    def test_different_companies_different_scores(
        self, sample_valid_company, sample_failing_company
    ):
        """Two different companies must not have identical breakdowns."""
        b1 = self.engine.score_deterministic(sample_valid_company)
        b2 = self.engine.score_deterministic(sample_failing_company)
        # At minimum, criteria scores should differ (valid vs invalid funding)
        assert b1.criteria_score != b2.criteria_score or b1.h1b_score != b2.h1b_score

    def test_same_input_same_output(self, sample_valid_company):
        """Same company scored twice must produce identical results."""
        b1 = self.engine.score_deterministic(sample_valid_company)
        b2 = self.engine.score_deterministic(sample_valid_company)
        assert b1.total == b2.total
        assert b1.h1b_score == b2.h1b_score
        assert b1.criteria_score == b2.criteria_score

    def test_kumo_scores_higher_than_runway(self):
        """Kumo (graph ML, strong fit) should score higher than Runway (Series E, weak fit)."""
        kumo = CompanyORM(
            name="Kumo",
            description="AI/ML on graph data — predictive analytics on relational data",
            hq_location="USA",
            employees=50,
            funding_stage="Series A",
            is_ai_native=True,
            h1b_status="Unknown",
            source_portal="Top Startups",
            why_fit="Graph-based ML directly overlaps with Graph RAG + Neo4j expertise",
        )
        runway = CompanyORM(
            name="Runway",
            description="AI video generation and editing",
            hq_location="New York, NY",
            employees=400,
            funding_stage="Series E",
            is_ai_native=True,
            h1b_status="Unknown",
            source_portal="Manual",
            why_fit="ML infrastructure + production systems at scale",
        )
        kumo_score = self.engine.score_deterministic(kumo)
        runway_score = self.engine.score_deterministic(runway)
        # Kumo should score higher due to valid funding + tech overlap keywords
        assert kumo_score.deterministic_total > runway_score.deterministic_total


class TestCharCounter:
    def test_connection_request_within_limit(self):
        from src.outreach.template_engine import CharCounter

        text = "Hi John, I'm an AI Engineer. Would love to connect."
        valid, count, limit = CharCounter.validate(text, "connection_request")
        assert valid
        assert count < 300
        assert limit == 300

    def test_connection_request_over_limit(self):
        from src.outreach.template_engine import CharCounter

        text = "x" * 301
        valid, count, limit = CharCounter.validate(text, "connection_request")
        assert not valid
        assert count == 301

    def test_follow_up_no_limit(self):
        from src.outreach.template_engine import CharCounter

        text = "x" * 5000
        valid, count, limit = CharCounter.validate(text, "follow_up")
        assert valid
        assert limit is None


class TestSequenceBuilder:
    def test_14_day_sequence(self):
        from src.outreach.template_engine import SequenceBuilder

        builder = SequenceBuilder()
        sequence = builder.build_sequence("2026-03-10", "John Doe", "Acme AI")
        assert len(sequence) == 5  # 5 touch points
        # All dates should be Tue or Thu
        for step in sequence:
            assert step["day"] in ("Tuesday", "Thursday"), (
                f"{step['step']} on {step['date']} is {step['day']}, expected Tue/Thu"
            )

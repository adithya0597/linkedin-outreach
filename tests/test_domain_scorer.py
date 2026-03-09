"""Tests for domain match scoring and scoring engine integration."""

from __future__ import annotations

import pytest

from src.db.orm import CompanyORM
from src.validators.domain_scorer import DomainMatchScorer


@pytest.fixture
def scorer():
    return DomainMatchScorer()


@pytest.fixture
def tier1_company(session):
    c = CompanyORM(name="Kumo AI", description="Graph ML platform")
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def graph_company(session):
    c = CompanyORM(
        name="GraphCo",
        description="Building graph-based RAG and knowledge graph systems with Neo4j",
        ai_product_description="Semantic search and retrieval augmented generation",
        role="AI Engineer",
    )
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def healthcare_company(session):
    c = CompanyORM(
        name="MedTechCo",
        description="AI platform for clinical decision support and patient outcomes",
        ai_product_description="Medical imaging and health data analysis",
        role="ML Engineer",
    )
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def agentic_company(session):
    c = CompanyORM(
        name="AgentCo",
        description="Building autonomous agent workflows for enterprise automation",
        ai_product_description="Agentic AI orchestration platform",
        role="AI Engineer",
    )
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def empty_company(session):
    c = CompanyORM(name="EmptyCo")
    session.add(c)
    session.flush()
    return c


# --- DomainMatchScorer tests ---


class TestDomainMatchScorer:
    def test_tier1_override_gets_full_weight(self, scorer, tier1_company):
        """Kumo AI (graph_rag, weight 1.0) should get score 10.0."""
        score, domain = scorer.score_domain_match(tier1_company)
        assert domain == "graph_rag"
        assert score == 10.0

    def test_tier1_healthcare_override(self, scorer, session):
        """Hippocratic AI (healthcare, weight 0.9) should get score 9.0."""
        c = CompanyORM(name="Hippocratic AI", description="Healthcare AI")
        session.add(c)
        session.flush()
        score, domain = scorer.score_domain_match(c)
        assert domain == "healthcare"
        assert score == 9.0

    def test_tier1_agentic_override(self, scorer, session):
        """Cinder (agentic_ai, weight 0.85) should get score 8.5."""
        c = CompanyORM(name="Cinder", description="Safety AI")
        session.add(c)
        session.flush()
        score, domain = scorer.score_domain_match(c)
        assert domain == "agentic_ai"
        assert score == 8.5

    def test_healthcare_company_scores_high(self, scorer, healthcare_company):
        """Company with healthcare keywords should match healthcare domain."""
        score, domain = scorer.score_domain_match(healthcare_company)
        assert domain == "healthcare"
        assert score > 0.0

    def test_agentic_company_scores(self, scorer, agentic_company):
        """Company with agent/autonomous keywords should match agentic_ai."""
        score, domain = scorer.score_domain_match(agentic_company)
        assert domain == "agentic_ai"
        assert score > 0.0

    def test_unknown_company_gets_default(self, scorer, session):
        """Company with no matching keywords gets default score (3.0)."""
        c = CompanyORM(name="RandomCo", description="We sell office supplies online")
        session.add(c)
        session.flush()
        score, domain = scorer.score_domain_match(c)
        assert domain == "ml_infrastructure"
        assert score == 3.0  # DEFAULT_WEIGHT (0.3) * MAX_POINTS (10.0)

    def test_keyword_density_calculation(self, scorer, graph_company):
        """Direct test of _count_keyword_density for graph_rag domain."""
        density = scorer._count_keyword_density(graph_company, "graph_rag")
        # graph_rag keywords: graph, rag, retrieval, knowledge graph, neo4j, vector, embedding, semantic search
        # GraphCo has: graph, rag, knowledge graph, neo4j, retrieval, semantic search, embedding = 7/8
        assert density > 0.5
        assert density <= 1.0

    def test_keyword_density_zero_for_unrelated(self, scorer, session):
        """Company with no matching keywords returns density 0."""
        c = CompanyORM(name="UnrelatedCo", description="Selling shoes")
        session.add(c)
        session.flush()
        density = scorer._count_keyword_density(c, "graph_rag")
        assert density == 0.0

    def test_batch_sorted_by_score(self, scorer, tier1_company, graph_company, empty_company):
        """batch_score returns results sorted by score descending."""
        results = scorer.batch_score([empty_company, tier1_company, graph_company])
        scores = [s for _, s, _ in results]
        assert scores == sorted(scores, reverse=True)
        # Tier 1 override (Kumo AI = 10.0) should be first
        assert results[0][0].name == "Kumo AI"

    def test_empty_description_handled(self, scorer, empty_company):
        """Company with empty fields doesn't crash."""
        score, domain = scorer.score_domain_match(empty_company)
        assert score == 3.0
        assert domain == "ml_infrastructure"


# --- FitScoringEngine integration tests ---


class TestScoringEngineWithDomainMatch:
    @pytest.fixture
    def scoring_engine(self):
        from src.validators.scoring_engine import FitScoringEngine
        return FitScoringEngine()

    def test_includes_bonus_when_semantic(self, scoring_engine, tier1_company):
        """score(include_semantic=True) includes domain_match_bonus."""
        breakdown = scoring_engine.score(tier1_company, include_semantic=True)
        assert breakdown.domain_match_bonus == 10.0

    def test_excludes_bonus_when_not_semantic(self, scoring_engine, tier1_company):
        """score(include_semantic=False) has domain_match_bonus=0."""
        breakdown = scoring_engine.score(tier1_company, include_semantic=False)
        assert breakdown.domain_match_bonus == 0.0

    def test_batch_score_semantic_method(self, scoring_engine, tier1_company, empty_company):
        """batch_score_semantic returns sorted results with domain match."""
        results = scoring_engine.batch_score_semantic([empty_company, tier1_company])
        assert len(results) == 2
        # Kumo AI should rank higher
        assert results[0][0].name == "Kumo AI"
        assert results[0][1].domain_match_bonus == 10.0

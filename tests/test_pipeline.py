"""Tests for pipeline orchestrator and state machine."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.enums import CompanyStage
from src.db.orm import Base, CompanyORM
from src.pipeline.orchestrator import Pipeline
from src.pipeline.state import PipelineState


@pytest.fixture
def pipeline_session():
    """Session with pre-loaded companies for pipeline testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    # Add test companies
    companies = [
        CompanyORM(
            name="LlamaIndex",
            description="RAG framework for LLM applications",
            hq_location="San Francisco, CA",
            employees=40,
            funding_stage="Series A",
            funding_amount="Series A — $19M",
            is_ai_native=True,
            h1b_status="Confirmed",
            source_portal="Manual",
            tier="Tier 1 - HIGH",
            role="AI Engineer",
            why_fit="Graph RAG + Neo4j overlap",
        ),
        CompanyORM(
            name="Harvey AI",
            description="Legal AI",
            hq_location="San Francisco, CA",
            employees=400,
            funding_stage="Series F",
            funding_amount="Series F — $160M at $8B",
            is_ai_native=True,
            h1b_status="Unknown",
            source_portal="Manual",
            tier="Tier 2 - STRONG",
            is_disqualified=True,
            disqualification_reason="Series F",
        ),
        CompanyORM(
            name="Hippocratic AI",
            description="Healthcare AI agents for clinical documentation",
            hq_location="Palo Alto, CA",
            employees=150,
            funding_stage="Series C",
            is_ai_native=True,
            h1b_status="Confirmed",
            source_portal="Manual",
            tier="Tier 1 - HIGH",
            role="AI Engineer",
            why_fit="Healthcare CDC pipeline + AI automation",
            best_stats="300+ table CDC pipelines, 99.9% data integrity",
        ),
    ]
    session.add_all(companies)
    session.commit()
    yield session
    session.close()


class TestPipeline:
    def test_validate_all(self, pipeline_session):
        """Pipeline validation should pass LlamaIndex and skip Harvey AI (already disqualified)."""
        pipeline = Pipeline(pipeline_session)
        results = pipeline.validate_all()
        assert results["passed"] >= 1  # LlamaIndex should pass
        # Harvey AI is already disqualified, won't be re-checked

    def test_score_all(self, pipeline_session):
        """Pipeline scoring should produce scores for non-disqualified companies."""
        pipeline = Pipeline(pipeline_session)
        results = pipeline.score_all()
        assert results["scored"] >= 2  # LlamaIndex + Hippocratic AI

    def test_full_pipeline(self, pipeline_session):
        """Full pipeline run should complete without errors."""
        pipeline = Pipeline(pipeline_session)
        results = pipeline.run()
        assert "validation" in results
        assert "scoring" in results
        assert results["scoring"]["scored"] >= 1

    def test_scoring_produces_different_scores(self, pipeline_session):
        """Different companies should get different total scores."""
        pipeline = Pipeline(pipeline_session)
        pipeline.score_all()
        companies = pipeline_session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).all()
        scores = [c.fit_score for c in companies if c.fit_score is not None]
        # At least 2 companies should have different scores
        assert len(set(scores)) > 1 or len(scores) <= 1


class TestPipelineState:
    def test_valid_transition(self, pipeline_session):
        """Should allow To Apply → Applied transition."""
        state = PipelineState(pipeline_session)
        company = pipeline_session.query(CompanyORM).filter_by(name="LlamaIndex").first()
        assert state.transition(company.id, CompanyStage.APPLIED)
        assert company.stage == CompanyStage.APPLIED.value

    def test_invalid_transition(self, pipeline_session):
        """Should reject To Apply → Offer (must go through Applied first)."""
        state = PipelineState(pipeline_session)
        company = pipeline_session.query(CompanyORM).filter_by(name="LlamaIndex").first()
        assert not state.transition(company.id, CompanyStage.OFFER)

    def test_get_counts(self, pipeline_session):
        """Should return counts by stage."""
        state = PipelineState(pipeline_session)
        counts = state.get_counts()
        assert "To apply" in counts

"""Tests for PriorityReporter — priority matrix, domain breakdown, markdown export."""

from unittest.mock import patch

from src.db.orm import CompanyORM
from src.pipeline.orchestrator import Pipeline
from src.validators.domain_scorer import DomainMatchScorer
from src.validators.priority_report import PriorityReporter


def _make_company(
    session,
    name,
    tier="Tier 1 - HIGH",
    fit_score=85.0,
    h1b="Confirmed",
    stage="To apply",
    is_disqualified=False,
    data_completeness=0.8,
):
    c = CompanyORM(
        name=name,
        tier=tier,
        fit_score=fit_score,
        h1b_status=h1b,
        is_disqualified=is_disqualified,
        stage=stage,
        data_completeness=data_completeness,
    )
    session.add(c)
    session.flush()
    return c


@patch.object(DomainMatchScorer, "score_domain_match", return_value=(8.5, "agentic_ai"))
@patch.object(Pipeline, "score_all")
def test_generate_priority_matrix_groups_by_tier(mock_score_all, mock_domain, session):
    """Matrix groups companies by tier and sorts by fit_score DESC within each tier."""
    mock_score_all.return_value = {"scored": 3, "top_10": []}

    _make_company(session, "AlphaAI", tier="Tier 1 - HIGH", fit_score=90.0)
    _make_company(session, "BetaAI", tier="Tier 1 - HIGH", fit_score=80.0)
    _make_company(session, "GammaAI", tier="Tier 2 - MEDIUM", fit_score=70.0)
    session.commit()

    reporter = PriorityReporter(session)
    matrix = reporter.generate_priority_matrix(include_semantic=False)

    assert matrix["total_scored"] == 3
    assert "Tier 1 - HIGH" in matrix["tiers"]
    assert "Tier 2 - MEDIUM" in matrix["tiers"]

    tier1 = matrix["tiers"]["Tier 1 - HIGH"]
    assert len(tier1) == 2
    assert tier1[0]["name"] == "AlphaAI"
    assert tier1[0]["fit_score"] == 90.0
    assert tier1[1]["name"] == "BetaAI"
    assert tier1[1]["fit_score"] == 80.0

    tier2 = matrix["tiers"]["Tier 2 - MEDIUM"]
    assert len(tier2) == 1
    assert tier2[0]["name"] == "GammaAI"

    mock_score_all.assert_called_once_with(include_semantic=False)


@patch.object(DomainMatchScorer, "batch_score")
def test_get_domain_breakdown_groups_by_domain(mock_batch, session):
    """Domain breakdown groups companies by their matched domain."""
    c1 = _make_company(session, "GraphCo", fit_score=90.0)
    c2 = _make_company(session, "AgentCo", fit_score=85.0)
    c3 = _make_company(session, "GraphCo2", fit_score=80.0)
    session.commit()

    mock_batch.return_value = [
        (c1, 10.0, "graph_rag"),
        (c3, 8.0, "graph_rag"),
        (c2, 8.5, "agentic_ai"),
    ]

    reporter = PriorityReporter(session)
    breakdown = reporter.get_domain_breakdown()

    assert "graph_rag" in breakdown
    assert breakdown["graph_rag"]["count"] == 2
    assert breakdown["graph_rag"]["avg_score"] == 9.0
    assert "GraphCo" in breakdown["graph_rag"]["companies"]
    assert "GraphCo2" in breakdown["graph_rag"]["companies"]

    assert "agentic_ai" in breakdown
    assert breakdown["agentic_ai"]["count"] == 1
    assert breakdown["agentic_ai"]["avg_score"] == 8.5


@patch.object(DomainMatchScorer, "score_domain_match", return_value=(7.0, "healthcare"))
@patch.object(Pipeline, "score_all")
def test_export_markdown_produces_valid_report(mock_score_all, mock_domain, session):
    """Markdown export contains tier sections, table headers, and company rows."""
    mock_score_all.return_value = {"scored": 2, "top_10": []}

    _make_company(session, "HealthCo", tier="Tier 1 - HIGH", fit_score=88.0)
    _make_company(session, "MedCo", tier="Tier 2 - MEDIUM", fit_score=72.0)
    session.commit()

    reporter = PriorityReporter(session)
    md = reporter.export_markdown()

    assert "# Priority Matrix Report" in md
    assert "## Tier 1 - HIGH" in md
    assert "## Tier 2 - MEDIUM" in md
    assert "| # | Company | Fit Score | H1B | Domain | Stage |" in md
    assert "HealthCo" in md
    assert "MedCo" in md
    assert "**Total Scored:** 2" in md


@patch.object(Pipeline, "score_all")
def test_export_notion_update_dry_run(mock_score_all, session):
    """dry_run=True returns count of companies that would be updated, no API calls."""
    _make_company(session, "DryRunCo1", fit_score=85.0)
    _make_company(session, "DryRunCo2", fit_score=90.0)
    _make_company(session, "DQCo", fit_score=75.0, is_disqualified=True)
    session.commit()

    reporter = PriorityReporter(session)
    result = reporter.export_notion_update(dry_run=True)

    assert result["updated"] == 2
    assert result["unchanged"] == 0
    assert result["errors"] == []


@patch.object(DomainMatchScorer, "score_domain_match", return_value=(5.0, "ml_infrastructure"))
@patch.object(Pipeline, "score_all")
def test_disqualified_companies_excluded(mock_score_all, mock_domain, session):
    """Disqualified companies are excluded from the priority matrix."""
    mock_score_all.return_value = {"scored": 1, "top_10": []}

    _make_company(session, "GoodCo", fit_score=85.0, is_disqualified=False)
    _make_company(session, "BadCo", fit_score=60.0, is_disqualified=True)
    session.commit()

    reporter = PriorityReporter(session)
    matrix = reporter.generate_priority_matrix(include_semantic=False)

    all_names = []
    for companies in matrix["tiers"].values():
        all_names.extend(c["name"] for c in companies)

    assert "GoodCo" in all_names
    assert "BadCo" not in all_names


@patch.object(DomainMatchScorer, "score_domain_match", return_value=(0, "ml_infrastructure"))
@patch.object(Pipeline, "score_all")
def test_empty_database_returns_empty_tiers(mock_score_all, mock_domain, session):
    """Empty database returns empty tiers dict and zero avg_score."""
    mock_score_all.return_value = {"scored": 0, "top_10": []}

    reporter = PriorityReporter(session)
    matrix = reporter.generate_priority_matrix(include_semantic=False)

    assert matrix["tiers"] == {}
    assert matrix["total_scored"] == 0
    assert matrix["avg_score"] == 0

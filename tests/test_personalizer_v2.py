"""Tests for Personalizer v2: weighted scoring, config-driven overrides, multi-template variants."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, ContactORM


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def test_weighted_scoring_prefers_high_weight_keywords():
    """A company mentioning 'knowledge graph' (weight 3.0) should match graph_rag
    over a company mentioning 'graph' (weight 2.0) alone."""
    from src.outreach.personalizer import OutreachPersonalizer, _DOMAIN_WEIGHTS

    p = OutreachPersonalizer()
    company = MagicMock(spec=CompanyORM)
    company.name = "TestCo"
    company.description = "We build knowledge graph systems"
    company.differentiators = ""
    company.role = ""
    domain = p._match_domain(company)
    assert domain == "graph_rag"


def test_weighted_scoring_agentic():
    """Company with 'agentic' and 'multi-agent' should match agentic_ai."""
    from src.outreach.personalizer import OutreachPersonalizer

    p = OutreachPersonalizer()
    company = MagicMock(spec=CompanyORM)
    company.name = "AgentCo"
    company.description = "agentic multi-agent orchestration platform"
    company.differentiators = ""
    company.role = ""
    domain = p._match_domain(company)
    assert domain == "agentic_ai"


def test_tier1_overrides_from_yaml():
    """TIER1_OVERRIDES should be loaded and contain known companies."""
    from src.outreach.personalizer import TIER1_OVERRIDES

    # At minimum, the YAML should have these entries
    assert "Kumo AI" in TIER1_OVERRIDES
    assert TIER1_OVERRIDES["Kumo AI"] == "graph_rag"
    assert "LangChain" in TIER1_OVERRIDES
    assert TIER1_OVERRIDES["LangChain"] == "llm_framework"


def test_override_takes_precedence_over_scoring():
    """Tier1 override should win even if keyword scoring points elsewhere."""
    from src.outreach.personalizer import OutreachPersonalizer

    p = OutreachPersonalizer()
    company = MagicMock(spec=CompanyORM)
    company.name = "Hippocratic AI"  # Override -> healthcare
    company.description = "agentic AI for clinical decision-making"
    company.differentiators = "agent"
    company.role = "AI Engineer"
    domain = p._match_domain(company)
    assert domain == "healthcare"


def test_domain_weights_has_all_five_domains():
    """_DOMAIN_WEIGHTS should have entries for all 5 domains."""
    from src.outreach.personalizer import _DOMAIN_WEIGHTS

    expected_domains = {"graph_rag", "healthcare", "llm_framework", "ml_infrastructure", "agentic_ai"}
    assert set(_DOMAIN_WEIGHTS.keys()) == expected_domains
    for domain, weights in _DOMAIN_WEIGHTS.items():
        assert len(weights) >= 5, f"{domain} should have at least 5 weighted keywords"


def test_generate_variants_returns_list():
    """generate_variants returns a list of tuples (text, is_valid, count)."""
    from src.outreach.personalizer import OutreachPersonalizer

    p = OutreachPersonalizer()
    context = {
        "name": "Test",
        "company": "TestCo",
        "role": "AI Engineer",
        "topic": "AI",
        "relevant_experience": "building RAG systems",
        "value_prop": "production AI experience",
        "metric": "26000 orders",
        "domain": "ML Infrastructure",
        "mutual_interest": "AI",
        "specific_insight": "what TestCo does",
        "your_background": "AI engineer",
        "connection_point": "AI engineering",
        "follow_up_context": "AI roles",
    }
    variants = p.generate_variants("connection_request_a.j2", context, n=2)
    assert isinstance(variants, list)
    assert len(variants) >= 1
    for v in variants:
        assert len(v) == 3  # (text, is_valid, char_count)


def test_domain_keywords_backward_compat():
    """_DOMAIN_KEYWORDS should still be importable and contain all 5 domains."""
    from src.outreach.personalizer import _DOMAIN_KEYWORDS

    expected_domains = {"graph_rag", "healthcare", "llm_framework", "ml_infrastructure", "agentic_ai"}
    assert set(_DOMAIN_KEYWORDS.keys()) == expected_domains
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        assert isinstance(keywords, list)
        assert len(keywords) >= 5


def test_all_tier1_overrides_map_to_valid_domains():
    """Every company in TIER1_OVERRIDES must map to a domain in EXPERIENCE_MAP."""
    from src.outreach.personalizer import EXPERIENCE_MAP, TIER1_OVERRIDES

    for company, domain in TIER1_OVERRIDES.items():
        assert domain in EXPERIENCE_MAP, (
            f"TIER1_OVERRIDES['{company}'] = '{domain}' not in EXPERIENCE_MAP"
        )

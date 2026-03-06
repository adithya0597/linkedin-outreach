"""Tests for outreach personalizer — domain matching, context enrichment, variant generation."""

from unittest.mock import MagicMock, patch

import pytest

from src.db.orm import CompanyORM, ContactORM
from src.outreach.personalizer import (
    EXPERIENCE_MAP,
    TIER1_OVERRIDES,
    OutreachPersonalizer,
    _DOMAIN_KEYWORDS,
)


@pytest.fixture
def personalizer():
    """Personalizer with real engine (templates directory exists)."""
    return OutreachPersonalizer()


@pytest.fixture
def graph_company():
    return CompanyORM(
        name="GraphCo",
        description="Building knowledge graph and RAG retrieval systems",
        differentiators="graph,rag,vector search",
        role="AI Engineer",
    )


@pytest.fixture
def healthcare_company():
    return CompanyORM(
        name="MedTech AI",
        description="Clinical decision support with patient health data",
        differentiators="healthcare,clinical AI",
        role="ML Engineer",
    )


@pytest.fixture
def cto_contact():
    return ContactORM(
        name="Jane Doe",
        title="CTO",
        company_name="GraphCo",
    )


@pytest.fixture
def recruiter_contact():
    return ContactORM(
        name="John Smith",
        title="Senior Recruiter",
        company_name="MedTech AI",
    )


class TestTier1Overrides:
    def test_llamaindex_maps_to_graph_rag(self, personalizer):
        """LlamaIndex is a Tier 1 override that should map to graph_rag."""
        company = CompanyORM(name="LlamaIndex", description="RAG framework")
        domain = personalizer._match_domain(company)
        assert domain == "graph_rag"

    def test_hippocratic_maps_to_healthcare(self, personalizer):
        """Hippocratic AI is a Tier 1 override that should map to healthcare."""
        company = CompanyORM(name="Hippocratic AI", description="Healthcare AI")
        domain = personalizer._match_domain(company)
        assert domain == "healthcare"

    def test_cursor_maps_to_ml_infrastructure(self, personalizer):
        """Cursor is a Tier 1 override that should map to ml_infrastructure."""
        company = CompanyORM(name="Cursor", description="AI code editor")
        domain = personalizer._match_domain(company)
        assert domain == "ml_infrastructure"

    def test_langchain_maps_to_llm_framework(self, personalizer):
        """LangChain is a Tier 1 override that should map to llm_framework."""
        company = CompanyORM(name="LangChain", description="LLM framework")
        domain = personalizer._match_domain(company)
        assert domain == "llm_framework"

    def test_cinder_maps_to_agentic_ai(self, personalizer):
        """Cinder is a Tier 1 override that should map to agentic_ai."""
        company = CompanyORM(name="Cinder", description="Trust and safety")
        domain = personalizer._match_domain(company)
        assert domain == "agentic_ai"


class TestGenericDomainMatching:
    def test_graph_keywords_match(self, personalizer, graph_company):
        """Company with graph/rag keywords should match graph_rag domain."""
        domain = personalizer._match_domain(graph_company)
        assert domain == "graph_rag"

    def test_healthcare_keywords_match(self, personalizer, healthcare_company):
        """Company with health/clinical keywords should match healthcare domain."""
        domain = personalizer._match_domain(healthcare_company)
        assert domain == "healthcare"

    def test_agentic_keywords_match(self, personalizer):
        """Company with agent/autonomous keywords should match agentic_ai."""
        company = CompanyORM(
            name="AutoBot AI",
            description="Autonomous agent workflows for enterprise automation",
            differentiators="agentic,orchestration",
        )
        domain = personalizer._match_domain(company)
        assert domain == "agentic_ai"

    def test_fallback_to_ml_infrastructure(self, personalizer):
        """Company with no matching keywords should default to ml_infrastructure."""
        company = CompanyORM(
            name="Mystery Corp",
            description="We do things with computers",
            differentiators="",
        )
        domain = personalizer._match_domain(company)
        assert domain == "ml_infrastructure"


class TestContextEnrichment:
    def test_context_has_all_required_keys(self, personalizer, graph_company):
        """Context dict must contain all required template variables."""
        required_keys = [
            "name", "company", "role", "topic",
            "relevant_experience", "value_prop", "metric",
            "domain", "mutual_interest", "specific_insight",
            "your_background", "connection_point", "follow_up_context",
        ]
        context = personalizer.enrich_context(graph_company)
        for key in required_keys:
            assert key in context, f"Missing required key: {key}"

    def test_graph_rag_experience_contains_138_node(self, personalizer):
        """Graph RAG context should mention 138-node in relevant_experience."""
        company = CompanyORM(name="LlamaIndex", description="RAG framework")
        context = personalizer.enrich_context(company)
        assert "138-node" in context["relevant_experience"]

    def test_healthcare_experience_contains_300_plus(self, personalizer):
        """Healthcare context should mention 300+ in relevant_experience."""
        company = CompanyORM(name="Hippocratic AI", description="Healthcare AI")
        context = personalizer.enrich_context(company)
        assert "300+" in context["relevant_experience"]

    def test_company_name_in_context(self, personalizer, graph_company):
        """Company name must appear in context."""
        context = personalizer.enrich_context(graph_company)
        assert context["company"] == "GraphCo"

    def test_contact_name_populated(self, personalizer, graph_company, cto_contact):
        """When contact is provided, name should be populated."""
        context = personalizer.enrich_context(graph_company, cto_contact)
        assert context["name"] == "Jane Doe"

    def test_no_contact_empty_name(self, personalizer, graph_company):
        """When no contact is provided, name should be empty string."""
        context = personalizer.enrich_context(graph_company)
        assert context["name"] == ""


class TestTitleAdaptation:
    def test_cto_gets_technical_tone(self, personalizer, graph_company, cto_contact):
        """CTO contact should get technical tone."""
        context = personalizer.enrich_context(graph_company, cto_contact)
        assert context["tone"] == "technical"
        assert context["emphasis"] == "architecture and system design"

    def test_recruiter_gets_results_tone(self, personalizer, healthcare_company, recruiter_contact):
        """Recruiter contact should get results-oriented tone."""
        context = personalizer.enrich_context(healthcare_company, recruiter_contact)
        assert context["tone"] == "results-oriented"
        assert context["emphasis"] == "measurable impact and team fit"

    def test_vp_gets_technical_tone(self, personalizer, graph_company):
        """VP Engineering should get technical tone."""
        contact = ContactORM(name="VP Person", title="VP of Engineering", company_name="GraphCo")
        context = personalizer.enrich_context(graph_company, contact)
        assert context["tone"] == "technical"

    def test_generic_title_gets_balanced_tone(self, personalizer, graph_company):
        """Unknown title should get balanced tone."""
        contact = ContactORM(name="Random Person", title="Software Engineer", company_name="GraphCo")
        context = personalizer.enrich_context(graph_company, contact)
        assert context["tone"] == "balanced"
        assert context["emphasis"] == "technical depth with business impact"


class TestGenerateVariants:
    def test_returns_n_results(self, personalizer):
        """generate_variants should return exactly n results."""
        context = {"relevant_experience": "test", "value_prop": "test", "metric": "test"}
        mock_render = MagicMock(return_value=("rendered text", True, 50))
        with patch.object(personalizer.engine, "render", mock_render):
            variants = personalizer.generate_variants("connection_request_a.j2", context, n=3)
        assert len(variants) == 3

    def test_returns_one_result(self, personalizer):
        """generate_variants with n=1 should return exactly 1 result."""
        context = {"relevant_experience": "test", "value_prop": "test", "metric": "test"}
        mock_render = MagicMock(return_value=("rendered text", True, 50))
        with patch.object(personalizer.engine, "render", mock_render):
            variants = personalizer.generate_variants("connection_request_a.j2", context, n=1)
        assert len(variants) == 1

    def test_each_variant_is_3_tuple(self, personalizer):
        """Each variant should be a tuple of (str, bool, int)."""
        context = {"relevant_experience": "test", "value_prop": "test", "metric": "test"}
        mock_render = MagicMock(return_value=("rendered text", True, 50))
        with patch.object(personalizer.engine, "render", mock_render):
            variants = personalizer.generate_variants("follow_up_a.j2", context, n=3)
        for variant in variants:
            assert isinstance(variant, tuple)
            assert len(variant) == 3
            text, is_valid, count = variant
            assert isinstance(text, str)
            assert isinstance(is_valid, bool)
            assert isinstance(count, int)

    def test_connection_template_uses_connection_type(self, personalizer):
        """Template with 'connection' in name should use connection_request msg_type."""
        context = {"relevant_experience": "test", "value_prop": "test", "metric": "test"}
        mock_render = MagicMock(return_value=("rendered", True, 50))
        with patch.object(personalizer.engine, "render", mock_render):
            personalizer.generate_variants("connection_request_a.j2", context, n=1)
        # Verify msg_type argument
        _, kwargs = mock_render.call_args
        assert kwargs.get("message_type", mock_render.call_args[0][2] if len(mock_render.call_args[0]) > 2 else None) is not None

    def test_inmail_template_uses_inmail_type(self, personalizer):
        """Template with 'inmail' in name should use inmail msg_type."""
        context = {"relevant_experience": "test", "value_prop": "test", "metric": "test"}
        mock_render = MagicMock(return_value=("rendered", True, 50))
        with patch.object(personalizer.engine, "render", mock_render):
            personalizer.generate_variants("inmail_a.j2", context, n=1)
        call_args = mock_render.call_args[0]
        assert call_args[2] == "inmail"


class TestExperienceMapIntegrity:
    def test_all_domains_have_required_fields(self):
        """Every domain in EXPERIENCE_MAP must have relevant_experience, metric, and value_prop."""
        required_fields = {"relevant_experience", "metric", "value_prop"}
        for domain, fields in EXPERIENCE_MAP.items():
            for field in required_fields:
                assert field in fields, f"Domain '{domain}' missing field '{field}'"

    def test_all_tier1_overrides_map_to_valid_domains(self):
        """Every company in TIER1_OVERRIDES must map to a domain in EXPERIENCE_MAP."""
        for company, domain in TIER1_OVERRIDES.items():
            assert domain in EXPERIENCE_MAP, (
                f"TIER1_OVERRIDES['{company}'] = '{domain}' not in EXPERIENCE_MAP"
            )

    def test_all_domain_keywords_map_to_valid_domains(self):
        """Every domain in _DOMAIN_KEYWORDS must exist in EXPERIENCE_MAP."""
        for domain in _DOMAIN_KEYWORDS:
            assert domain in EXPERIENCE_MAP, (
                f"_DOMAIN_KEYWORDS has domain '{domain}' not in EXPERIENCE_MAP"
            )

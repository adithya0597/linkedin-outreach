"""Rule-based outreach personalization — maps company attributes to Adithya's experience."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.db.orm import CompanyORM, ContactORM
from src.outreach.template_engine import OutreachTemplateEngine


EXPERIENCE_MAP: dict[str, dict[str, str]] = {
    "graph_rag": {
        "relevant_experience": "building a 138-node semantic knowledge graph with Neo4j powering production RAG pipelines",
        "metric": "138-node semantic graph with 90% automated code translation",
        "value_prop": "I've built graph-based RAG systems that connect structured knowledge to LLM reasoning",
    },
    "healthcare": {
        "relevant_experience": "building CDC data pipelines across 300+ tables with 99.9% data integrity in healthcare",
        "metric": "300+ table healthcare CDC pipelines at 99.9% integrity",
        "value_prop": "I bring production healthcare data engineering experience with strict compliance requirements",
    },
    "llm_framework": {
        "relevant_experience": "building production LLM applications with LangChain, including RAG and agentic workflows",
        "metric": "production LangChain RAG systems serving real users",
        "value_prop": "I've shipped LLM-powered features from prototype to production using the frameworks you're building",
    },
    "ml_infrastructure": {
        "relevant_experience": "automating code translation across 27 microservices with 90% automation rate",
        "metric": "90% automated code translation across 27 microservices",
        "value_prop": "I build ML infrastructure that scales — from model serving to automated code generation",
    },
    "agentic_ai": {
        "relevant_experience": "building agentic AI pipelines that processed 26,000+ orders autonomously",
        "metric": "26,000+ orders processed via agentic AI pipeline",
        "value_prop": "I've built autonomous AI systems that handle real-world transactions at scale",
    },
}


def _load_overrides() -> dict[str, str]:
    """Load tier1 domain overrides from YAML config, falling back to empty dict."""
    path = Path(__file__).parent.parent.parent / "config" / "domain_overrides.yaml"
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("tier1_overrides", {})
    return {}


TIER1_OVERRIDES: dict[str, str] = _load_overrides()


_DOMAIN_WEIGHTS: dict[str, dict[str, float]] = {
    "graph_rag": {
        "knowledge graph": 3.0,
        "neo4j": 3.0,
        "graph": 2.0,
        "rag": 2.0,
        "retrieval": 1.5,
        "vector": 1.5,
        "embedding": 1.5,
        "semantic search": 2.0,
        "graph neural": 2.5,
        "gnn": 2.5,
    },
    "healthcare": {
        "health": 2.0,
        "medical": 2.0,
        "clinical": 2.5,
        "patient": 2.0,
        "pharma": 2.0,
        "biotech": 1.5,
        "care": 1.0,
        "hipaa": 3.0,
        "ehr": 2.5,
        "fhir": 2.5,
    },
    "llm_framework": {
        "langchain": 3.0,
        "llm framework": 3.0,
        "llm tool": 2.0,
        "prompt": 1.5,
        "chain": 1.0,
        "agent framework": 2.5,
        "llamaindex": 3.0,
        "model serving": 2.0,
    },
    "ml_infrastructure": {
        "infrastructure": 2.0,
        "mlops": 3.0,
        "model serving": 2.5,
        "deployment": 1.5,
        "pipeline": 1.5,
        "translation": 1.0,
        "compiler": 2.0,
        "code generation": 2.0,
        "kubernetes": 1.5,
        "gpu": 1.5,
    },
    "agentic_ai": {
        "agent": 2.0,
        "autonomous": 2.5,
        "agentic": 3.0,
        "workflow automation": 2.5,
        "orchestration": 2.0,
        "multi-agent": 3.0,
        "tool use": 2.0,
    },
}

# Backward-compatible alias: flat keyword lists derived from _DOMAIN_WEIGHTS keys.
# Used by src.validators.domain_scorer and existing tests.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    domain: list(weights.keys()) for domain, weights in _DOMAIN_WEIGHTS.items()
}


class OutreachPersonalizer:
    """Maps company attributes to Adithya's experience for personalized outreach."""

    def __init__(self):
        self.engine = OutreachTemplateEngine()

    def _match_domain(self, company: CompanyORM) -> str:
        """Match company to best experience domain via weighted keyword scoring."""
        if company.name in TIER1_OVERRIDES:
            return TIER1_OVERRIDES[company.name]

        text = f"{company.description or ''} {company.differentiators or ''} {company.role or ''}".lower()
        best_domain = "ml_infrastructure"
        best_score = 0.0
        for domain, weights in _DOMAIN_WEIGHTS.items():
            score = sum(w for kw, w in weights.items() if kw in text)
            if score > best_score:
                best_score = score
                best_domain = domain
        return best_domain

    def _adapt_for_title(self, context: dict, title: str) -> dict:
        """Adjust messaging based on contact's title."""
        title_lower = title.lower()
        if any(t in title_lower for t in ["cto", "vp", "head", "director", "founder"]):
            context["tone"] = "technical"
            context["emphasis"] = "architecture and system design"
        elif any(t in title_lower for t in ["recruiter", "talent", "hr"]):
            context["tone"] = "results-oriented"
            context["emphasis"] = "measurable impact and team fit"
        else:
            context["tone"] = "balanced"
            context["emphasis"] = "technical depth with business impact"
        return context

    def enrich_context(self, company: CompanyORM, contact: ContactORM | None = None) -> dict:
        """Build full template variable dict with personalized context."""
        domain = self._match_domain(company)
        exp = EXPERIENCE_MAP[domain]
        context = {
            "name": contact.name if contact else "",
            "company": company.name,
            "role": company.role or "AI Engineer",
            "topic": company.differentiators.split(",")[0].strip() if company.differentiators else "AI engineering",
            "relevant_experience": exp["relevant_experience"],
            "value_prop": exp["value_prop"],
            "metric": exp["metric"],
            "domain": domain.replace("_", " ").title(),
            "mutual_interest": company.differentiators or "AI/ML",
            "specific_insight": f"what {company.name} is building in AI",
            "your_background": "AI engineer with production experience in LangChain, Neo4j, and RAG systems",
            "connection_point": f"AI engineering and {domain.replace('_', ' ')}",
            "follow_up_context": f"connecting about {company.role or 'AI engineering'} opportunities",
        }
        if contact:
            context = self._adapt_for_title(context, contact.title)
        return context

    def generate_variants(self, template_name: str, context: dict, n: int = 3) -> list[tuple[str, bool, int]]:
        """Generate n message variants using different templates.
        Returns list of (rendered_text, is_within_limit, char_count).
        """
        # Determine message type
        if "connection" in template_name:
            msg_type = "connection_request"
        elif "inmail" in template_name:
            msg_type = "inmail"
        elif "pre_engagement" in template_name:
            msg_type = "pre_engagement"
        else:
            msg_type = "follow_up"

        # Build list of template candidates for this message type
        suffixes = ["a", "b", "c"]
        candidates = [f"{msg_type}_{s}.j2" for s in suffixes[:n]]

        variants = []
        for tmpl in candidates:
            try:
                rendered, is_valid, count = self.engine.render(tmpl, context, msg_type)
                variants.append((rendered, is_valid, count))
            except Exception:
                # Template may not exist; skip it
                pass

        # If we got fewer than n, fill with field-swap fallback on original template
        while len(variants) < n:
            ctx = context.copy()
            ctx["relevant_experience"] = context.get("value_prop", context.get("relevant_experience", ""))
            try:
                rendered, is_valid, count = self.engine.render(template_name, ctx, msg_type)
                variants.append((rendered, is_valid, count))
            except Exception:
                # If even fallback fails, append a placeholder
                variants.append(("", False, 0))
            break  # Only one fallback

        return variants[:n]

    def generate_multi_template_variants(
        self,
        template_names: list[str],
        context: dict,
        message_type: str = "connection_request",
    ) -> list[tuple[str, bool, int, str]]:
        """Render same context through DIFFERENT templates.

        Returns list of (text, is_valid, char_count, template_used).
        """
        variants = []
        for tmpl in template_names:
            rendered, is_valid, count = self.engine.render(tmpl, context, message_type)
            variants.append((rendered, is_valid, count, tmpl))
        return variants

    def get_best_template_for_contact(
        self, contact: "ContactORM", message_type: str = "connection_request"
    ) -> str:
        """Select best template based on contact's title/role."""
        title = (contact.title or "").lower() if contact else ""
        if message_type == "connection_request":
            if any(t in title for t in ["cto", "vp", "head", "director", "founder"]):
                return "connection_request_a.j2"  # technical angle
            elif any(t in title for t in ["recruiter", "talent", "hr"]):
                return "connection_request_b.j2"  # metrics angle
            return "connection_request_c.j2"  # balanced
        elif message_type == "follow_up":
            return "follow_up_a.j2"
        elif message_type == "inmail":
            return "inmail_a.j2"
        return f"{message_type}_a.j2"

"""Domain match scoring — bonus points for companies matching candidate's experience domains."""

from __future__ import annotations

from loguru import logger

from src.db.orm import CompanyORM
from src.outreach.personalizer import _DOMAIN_KEYWORDS, TIER1_OVERRIDES


class DomainMatchScorer:
    """Scores companies based on domain match to candidate's experience."""

    DOMAIN_WEIGHTS: dict[str, float] = {
        "graph_rag": 1.0,
        "healthcare": 0.9,
        "agentic_ai": 0.85,
        "llm_framework": 0.8,
        "ml_infrastructure": 0.6,
    }

    MAX_POINTS: float = 10.0
    DEFAULT_WEIGHT: float = 0.3

    def _count_keyword_density(self, company: CompanyORM, domain: str) -> float:
        """Calculate ratio of matched keywords in company text fields.

        Returns float between 0.0 and 1.0.
        """
        keywords = _DOMAIN_KEYWORDS.get(domain, [])
        if not keywords:
            return 0.0

        text = " ".join([
            company.description or "",
            company.ai_product_description or "",
            company.why_fit or "",
            company.role or "",
            company.differentiators or "",
        ]).lower()

        if not text.strip():
            return 0.0

        matches = sum(1 for kw in keywords if kw.lower() in text)
        return matches / len(keywords)

    def score_domain_match(self, company: CompanyORM) -> tuple[float, str]:
        """Score how well a company matches candidate's experience domains.

        Checks TIER1_OVERRIDES first, then falls back to keyword density matching.

        Args:
            company: The company to score.

        Returns:
            Tuple of (score 0-10, matched_domain_name).
        """
        # Check Tier 1 overrides first — these get full weight
        if company.name in TIER1_OVERRIDES:
            domain = TIER1_OVERRIDES[company.name]
            weight = self.DOMAIN_WEIGHTS.get(domain, self.DEFAULT_WEIGHT)
            score = round(weight * self.MAX_POINTS, 2)
            logger.debug(f"Domain match (Tier 1 override): {company.name} -> {domain} = {score}")
            return score, domain

        # Find best domain via keyword density
        best_domain = "ml_infrastructure"
        best_score = 0.0

        for domain in self.DOMAIN_WEIGHTS:
            density = self._count_keyword_density(company, domain)
            weight = self.DOMAIN_WEIGHTS[domain]
            candidate_score = density * weight * self.MAX_POINTS

            if candidate_score > best_score:
                best_score = candidate_score
                best_domain = domain

        # If no keywords matched, use default weight with ml_infrastructure
        if best_score == 0.0:
            best_score = round(self.DEFAULT_WEIGHT * self.MAX_POINTS, 2)
            best_domain = "ml_infrastructure"
        else:
            best_score = round(best_score, 2)

        logger.debug(f"Domain match: {company.name} -> {best_domain} = {best_score}")
        return best_score, best_domain

    def batch_score(
        self, companies: list[CompanyORM]
    ) -> list[tuple[CompanyORM, float, str]]:
        """Score all companies and return sorted by score desc.

        Returns list of (company, score, domain).
        """
        results = []
        for company in companies:
            score, domain = self.score_domain_match(company)
            results.append((company, score, domain))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

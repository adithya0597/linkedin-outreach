"""Hybrid fit scoring engine — deterministic 50pts + semantic 50pts."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.db.orm import CompanyORM
from src.models.company import ScoreBreakdown


class FitScoringEngine:
    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "scoring_weights.yaml"
            )
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self._embedder = None
        self._profile_embedding = None
        self._domain_scorer = None

    def score_deterministic(self, company: CompanyORM) -> ScoreBreakdown:
        """Calculate deterministic half of fit score (50pts max)."""
        breakdown = ScoreBreakdown()

        # H1B scoring (0-15)
        h1b_config = self.config["h1b_scoring"]
        h1b_map = {
            "Confirmed": h1b_config["confirmed"],
            "Likely": h1b_config["likely"],
            "Unknown": h1b_config["unknown"],
            "Explicit No": h1b_config["explicit_no"],
            "N/A": h1b_config["not_applicable"],
        }
        breakdown.h1b_score = h1b_map.get(company.h1b_status, h1b_config["unknown"])

        # Criteria scoring (0-15)
        criteria_config = self.config["criteria_scoring"]
        if company.employees and company.employees < 1000:
            breakdown.criteria_score += criteria_config["employees_under_1000"]
        elif not company.employees:
            breakdown.criteria_score += criteria_config["employees_under_1000"] * 0.5

        valid_stages = {"Pre-Seed", "Seed", "Series A", "Series B", "Series C"}
        if company.funding_stage in valid_stages:
            breakdown.criteria_score += criteria_config["valid_funding_stage"]

        if company.hq_location:
            hq_lower = company.hq_location.lower()
            us_markers = [
                "ca", "ny", "tx", "wa", "sf", "nyc", "usa", "united states",
                "san francisco", "new york", "seattle", "remote", "palo alto",
            ]
            if any(m in hq_lower for m in us_markers):
                breakdown.criteria_score += criteria_config["us_hq"]

        if company.is_ai_native:
            breakdown.criteria_score += criteria_config["ai_native"]

        # Tech overlap scoring (0-10)
        tech_config = self.config["tech_overlap_scoring"]
        candidate_keywords = tech_config["candidate_tech_keywords"]
        company_text = " ".join([
            company.description or "",
            company.role or "",
            company.why_fit or "",
            company.best_stats or "",
            company.ai_product_description or "",
        ]).lower()

        matches = sum(1 for kw in candidate_keywords if kw.lower() in company_text)
        breakdown.tech_overlap_score = min(
            matches * tech_config["points_per_match"],
            tech_config["max_points"],
        )

        # Salary scoring (0-10)
        salary_config = self.config["salary_scoring"]
        if company.salary_range:
            salary_text = company.salary_range.replace("$", "").replace(",", "").replace("K", "000")
            import re
            nums = re.findall(r"\d+", salary_text)
            if len(nums) >= 2:
                sal_min, sal_max = int(nums[0]), int(nums[1])
                # Normalize if in thousands
                if sal_min < 1000:
                    sal_min *= 1000
                    sal_max *= 1000
                target_min = salary_config["candidate_target_min"]
                target_max = salary_config["candidate_target_max"]
                if sal_min <= target_max and sal_max >= target_min:
                    overlap = min(sal_max, target_max) - max(sal_min, target_min)
                    total_range = target_max - target_min
                    ratio = overlap / total_range if total_range > 0 else 0
                    if ratio > 0.5:
                        breakdown.salary_score = salary_config["full_overlap"]
                    else:
                        breakdown.salary_score = salary_config["partial_overlap"]
                else:
                    breakdown.salary_score = salary_config["out_of_range"]
            else:
                breakdown.salary_score = salary_config["no_data"]
        else:
            breakdown.salary_score = salary_config["no_data"]

        return breakdown

    def score(self, company: CompanyORM, include_semantic: bool = False) -> ScoreBreakdown:
        """Calculate full hybrid score. Semantic scoring requires model loading."""
        breakdown = self.score_deterministic(company)

        if include_semantic:
            breakdown = self._add_semantic_scores(breakdown, company)
            breakdown.domain_match_bonus = self._score_domain_match(company)

        return breakdown

    def _score_domain_match(self, company: CompanyORM) -> float:
        """Calculate domain match bonus score (0-10)."""
        if self._domain_scorer is None:
            from src.validators.domain_scorer import DomainMatchScorer
            self._domain_scorer = DomainMatchScorer()
        score, _domain = self._domain_scorer.score_domain_match(company)
        return score

    def _add_semantic_scores(
        self, breakdown: ScoreBreakdown, company: CompanyORM
    ) -> ScoreBreakdown:
        """Add semantic embedding scores (requires sentence-transformers)."""
        try:
            from src.validators.embeddings import EmbeddingManager

            if self._embedder is None:
                model_name = self.config["semantic_scoring"]["model"]
                self._embedder = EmbeddingManager(model_name)

            if self._profile_embedding is None:
                profile_text = self.config["semantic_scoring"]["candidate_profile_text"]
                self._profile_embedding = self._embedder.embed(profile_text)

            # Profile-to-JD similarity (0-25)
            jd_text = " ".join([
                company.description or "",
                company.role or "",
                company.why_fit or "",
            ])
            if jd_text.strip():
                jd_embedding = self._embedder.embed(jd_text)
                sim = self._embedder.cosine_similarity(self._profile_embedding, jd_embedding)
                max_pts = self.config["semantic_scoring"]["profile_jd_max"]
                breakdown.profile_jd_similarity = round(sim * max_pts, 2)

            # Domain-to-company similarity (0-25)
            domain_text = self.config["semantic_scoring"]["candidate_domain_keywords"]
            company_desc = company.ai_product_description or company.description or ""
            if company_desc.strip():
                domain_embedding = self._embedder.embed(domain_text)
                desc_embedding = self._embedder.embed(company_desc)
                sim = self._embedder.cosine_similarity(domain_embedding, desc_embedding)
                max_pts = self.config["semantic_scoring"]["domain_company_max"]
                breakdown.domain_company_similarity = round(sim * max_pts, 2)

        except ImportError:
            pass  # Semantic scoring unavailable — deterministic only

        return breakdown

    def batch_score(
        self, companies: list[CompanyORM], include_semantic: bool = False
    ) -> list[tuple[CompanyORM, ScoreBreakdown]]:
        """Score all companies and return sorted by total score."""
        results = [(c, self.score(c, include_semantic)) for c in companies]
        results.sort(key=lambda x: x[1].total, reverse=True)
        return results

    def batch_score_semantic(
        self, companies: list[CompanyORM]
    ) -> list[tuple[CompanyORM, ScoreBreakdown]]:
        """Score all companies with semantic scoring and domain match, sorted by total desc."""
        results = [(c, self.score(c, include_semantic=True)) for c in companies]
        results.sort(key=lambda x: x[1].total, reverse=True)
        return results

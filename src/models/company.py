from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.config.enums import (
    CompanyStage,
    FundingStage,
    H1BStatus,
    SourcePortal,
    Tier,
    ValidationResult,
)


@dataclass
class ScoreBreakdown:
    h1b_score: float = 0.0  # 0-15
    criteria_score: float = 0.0  # 0-15
    tech_overlap_score: float = 0.0  # 0-10
    salary_score: float = 0.0  # 0-10
    profile_jd_similarity: float = 0.0  # 0-25
    domain_company_similarity: float = 0.0  # 0-25
    domain_match_bonus: float = 0.0  # 0-10

    @property
    def deterministic_total(self) -> float:
        return self.h1b_score + self.criteria_score + self.tech_overlap_score + self.salary_score

    @property
    def semantic_total(self) -> float:
        return self.profile_jd_similarity + self.domain_company_similarity + self.domain_match_bonus

    @property
    def total(self) -> float:
        return self.deterministic_total + self.semantic_total


@dataclass
class Company:
    id: int | None = None
    name: str = ""
    description: str = ""
    hq_location: str = ""
    employees: int | None = None
    employees_range: str = ""
    funding_stage: FundingStage = FundingStage.UNKNOWN
    funding_amount: str = ""
    total_raised: str = ""
    valuation: str = ""
    founded_year: int | None = None
    website: str = ""
    careers_url: str = ""
    linkedin_url: str = ""
    is_ai_native: bool = False
    ai_product_description: str = ""
    tier: Tier = Tier.TIER_5
    source_portal: SourcePortal = SourcePortal.MANUAL
    h1b_status: H1BStatus = H1BStatus.UNKNOWN
    h1b_source: str = ""
    h1b_details: str = ""
    fit_score: float | None = None
    score_breakdown: ScoreBreakdown | None = None
    stage: CompanyStage = CompanyStage.TO_APPLY
    validation_result: ValidationResult | None = None
    validation_notes: str = ""
    differentiators: list[str] = field(default_factory=list)
    role: str = ""
    role_url: str = ""
    salary_range: str = ""
    notes: str = ""
    hiring_manager: str = ""
    hiring_manager_linkedin: str = ""
    why_fit: str = ""
    best_stats: str = ""
    action: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    is_disqualified: bool = False
    disqualification_reason: str = ""
    needs_review: bool = False
    data_completeness: float = 0.0  # 0-100%

    def calculate_completeness(self) -> float:
        """Calculate what % of important fields are populated."""
        important_fields = [
            self.name,
            self.description,
            self.hq_location,
            self.employees or self.employees_range,
            self.funding_stage != FundingStage.UNKNOWN,
            self.is_ai_native,
            self.tier,
            self.source_portal,
            self.role,
        ]
        filled = sum(1 for f in important_fields if f)
        self.data_completeness = round(filled / len(important_fields) * 100, 1)
        return self.data_completeness

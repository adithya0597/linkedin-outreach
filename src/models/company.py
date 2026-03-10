from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple

from src.config.enums import (
    CompanyStage,
    FundingStage,
    H1BStatus,
    SourcePortal,
    Tier,
    ValidationResult,
)


class CompletenessResult(NamedTuple):
    """Result of a field-completeness calculation."""
    score: float  # 0.0 - 1.0
    missing_fields: list[str]


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
    tech_stack: list[str] = field(default_factory=list)
    ai_nativity: str = ""  # e.g. "AI-native", "AI-enabled", "Not AI"
    headquarters_city: str = ""
    headquarters_state: str = ""

    # -- 15-field completeness ------------------------------------------------

    COMPLETENESS_FIELDS: list[str] = field(
        default=None, init=False, repr=False,
    )

    def __post_init__(self) -> None:
        # Immutable ordered list used by calculate_completeness
        object.__setattr__(self, "COMPLETENESS_FIELDS", [
            "name",
            "website",
            "linkedin_url",
            "employees_range",
            "funding_stage",
            "funding_amount",
            "hiring_manager",
            "role_url",
            "h1b_status",
            "salary_range",
            "tech_stack",
            "differentiators",
            "ai_nativity",
            "headquarters_city",
            "headquarters_state",
        ])

    def _is_field_present(self, field_name: str) -> bool:
        """Return True if the field has a meaningful (non-default/non-empty) value."""
        value = getattr(self, field_name)
        # Check enums BEFORE str — FundingStage/H1BStatus inherit from str
        if isinstance(value, FundingStage):
            return value != FundingStage.UNKNOWN
        if isinstance(value, H1BStatus):
            return value != H1BStatus.UNKNOWN
        if isinstance(value, list):
            return len(value) > 0
        if isinstance(value, str):
            return bool(value.strip())
        return bool(value)

    def calculate_completeness(self) -> CompletenessResult:
        """Calculate what fraction of the 15 important fields are populated.

        Returns a CompletenessResult with:
        - score: 0.0 to 1.0
        - missing_fields: list of field names that are empty/default
        Also updates self.data_completeness (0-100 scale) for backward compat.
        """
        missing: list[str] = []
        filled = 0
        for fname in self.COMPLETENESS_FIELDS:
            if self._is_field_present(fname):
                filled += 1
            else:
                missing.append(fname)
        total = len(self.COMPLETENESS_FIELDS)
        score = round(filled / total, 4) if total else 0.0
        self.data_completeness = round(score * 100, 1)
        return CompletenessResult(score=score, missing_fields=missing)

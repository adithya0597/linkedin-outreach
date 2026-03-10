"""Pipeline state machine — tracks company progression through stages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.config.enums import CompanyStage
from src.db.orm import CompanyORM

# Valid state transitions
TRANSITIONS = {
    CompanyStage.TO_APPLY: [CompanyStage.APPLIED, CompanyStage.DISQUALIFIED],
    CompanyStage.APPLIED: [CompanyStage.NO_ANSWER, CompanyStage.OFFER, CompanyStage.REJECTED],
    CompanyStage.NO_ANSWER: [CompanyStage.APPLIED, CompanyStage.REJECTED],  # Can re-apply
    CompanyStage.OFFER: [],  # Terminal
    CompanyStage.REJECTED: [],  # Terminal
    CompanyStage.DISQUALIFIED: [],  # Terminal
}


class PipelineState:
    def __init__(self, session: Session):
        self.session = session

    def transition(self, company_id: int, new_stage: CompanyStage) -> bool:
        """Attempt to transition a company to a new stage. Returns success."""
        company = self.session.get(CompanyORM, company_id)
        if not company:
            return False

        current = CompanyStage(company.stage)
        allowed = TRANSITIONS.get(current, [])

        if new_stage not in allowed:
            return False

        company.stage = new_stage.value
        company.updated_at = datetime.now()
        self.session.commit()
        return True

    def get_counts(self) -> dict[str, int]:
        """Get count of companies in each stage."""
        from sqlalchemy import func

        results = self.session.query(
            CompanyORM.stage, func.count(CompanyORM.id)
        ).group_by(CompanyORM.stage).all()
        return {stage: count for stage, count in results}

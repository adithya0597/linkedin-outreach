"""Sequence tracking -- mark-sent, mark-responded, sequence status."""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, OutreachORM
from src.outreach.constants import STEP_INDEX as STEP_ORDER
from src.outreach.constants import STEP_ORDER as ALL_STEPS


class SequenceTracker:
    """Track outreach sequence progress -- mark sent, responded, get status."""

    def __init__(self, session: Session):
        self.session = session

    def mark_sent(
        self,
        company_name: str,
        step: str,
        contact_name: str | None = None,
    ) -> OutreachORM | None:
        """Mark an outreach step as sent.

        Finds existing draft matching company+step, updates to Sent.
        If no draft exists, creates one.

        Returns OutreachORM record, or None if company not found.
        """
        company = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.name == company_name)
            .first()
        )
        if not company:
            logger.warning(f"Company not found: {company_name}")
            return None

        # Find existing draft for this step
        record = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.company_name == company_name,
                OutreachORM.sequence_step == step,
                OutreachORM.stage == "Not Started",
            )
            .first()
        )

        if record:
            record.stage = "Sent"
            record.sent_at = datetime.now()
            if contact_name:
                record.contact_name = contact_name
        else:
            # Create new record
            record = OutreachORM(
                company_id=company.id,
                company_name=company_name,
                contact_name=contact_name or "",
                stage="Sent",
                sent_at=datetime.now(),
                sequence_step=step,
            )
            self.session.add(record)

        self.session.commit()
        logger.info(f"Marked sent: {company_name} / {step}")
        return record

    def mark_responded(
        self,
        company_name: str,
        response_text: str = "",
    ) -> OutreachORM | None:
        """Mark the most recent sent outreach as responded.

        Returns updated OutreachORM, or None if no sent record found.
        """
        record = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.company_name == company_name,
                OutreachORM.stage == "Sent",
            )
            .order_by(OutreachORM.sent_at.desc())
            .first()
        )

        if not record:
            logger.warning(f"No sent outreach found for: {company_name}")
            return None

        record.stage = "Responded"
        record.response_at = datetime.now()
        record.response_text = response_text
        self.session.commit()
        logger.info(f"Marked responded: {company_name}")
        return record

    def get_sequence_status(self, company_name: str) -> dict:
        """Get full sequence status for a company.

        Returns dict with company, contact, current_step, steps_completed,
        steps_remaining, next_due, total_sent, has_response.
        """
        records = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.company_name == company_name)
            .order_by(OutreachORM.created_at)
            .all()
        )

        if not records:
            return {
                "company": company_name,
                "contact": "",
                "current_step": None,
                "steps_completed": [],
                "steps_remaining": ALL_STEPS.copy(),
                "next_due": None,
                "total_sent": 0,
                "has_response": False,
            }

        # Analyze records
        completed_steps = []
        has_response = False
        total_sent = 0
        contact = records[0].contact_name
        current_step = None

        for record in records:
            if record.stage in ("Sent", "Responded"):
                if record.sequence_step and record.sequence_step not in completed_steps:
                    completed_steps.append(record.sequence_step)
                total_sent += 1
                current_step = record.sequence_step
            if record.stage == "Responded":
                has_response = True

        remaining = [s for s in ALL_STEPS if s not in completed_steps]

        return {
            "company": company_name,
            "contact": contact,
            "current_step": current_step,
            "steps_completed": completed_steps,
            "steps_remaining": remaining,
            "next_due": remaining[0] if remaining else None,
            "total_sent": total_sent,
            "has_response": has_response,
        }

    def get_all_active_sequences(self) -> list[dict]:
        """Get all companies with at least one Sent record and incomplete sequences.

        Returns list of sequence status dicts.
        """
        # Get distinct company names with at least one Sent
        sent_companies = (
            self.session.query(OutreachORM.company_name)
            .filter(OutreachORM.stage.in_(["Sent", "Responded"]))
            .distinct()
            .all()
        )

        active = []
        for (company_name,) in sent_companies:
            status = self.get_sequence_status(company_name)
            if status["steps_remaining"]:  # Not all steps done
                active.append(status)

        return active

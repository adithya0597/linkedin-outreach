from __future__ import annotations

import json
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import OutreachORM

# Valid state transitions: current_state -> set of allowed next states
VALID_TRANSITIONS: dict[str, set[str]] = {
    "Not Started": {"Sent"},
    "Sent": {"Responded", "No Answer"},
    "No Answer": {"Sent"},
    "Responded": {"Interview", "Declined"},
    "Interview": {"Offer", "Rejected"},
}

MAX_RESEND_CYCLES = 3


class InvalidTransitionError(Exception):
    """Raised when attempting an invalid state transition."""

    pass


class OutreachStateMachine:
    """Manages outreach stage transitions with validation and audit trail.

    Audit trail entries are stored as newline-separated JSON objects in the
    OutreachORM.audit_trail field (a dedicated Text column for append-log
    storage).
    """

    # The ORM field used to store the audit trail JSON log.
    _audit_field = "audit_trail"

    def __init__(self, session: Session) -> None:
        self.session = session

    def _get_outreach_record(self, company_name: str) -> OutreachORM:
        """Look up the outreach record by company name.

        Raises ValueError if no record found.
        """
        record = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.company_name == company_name)
            .first()
        )
        if record is None:
            raise ValueError(f"Company not found: {company_name}")
        return record

    def can_transition(self, company_name: str, new_stage: str) -> bool:
        """Check whether a transition is valid without executing it."""
        record = self._get_outreach_record(company_name)
        current = record.stage
        allowed = VALID_TRANSITIONS.get(current, set())
        return new_stage in allowed

    def get_available_transitions(self, company_name: str) -> list[str]:
        """Return valid next states for the company's current stage."""
        record = self._get_outreach_record(company_name)
        current = record.stage
        return sorted(VALID_TRANSITIONS.get(current, set()))

    def _count_resend_cycles(self, record: OutreachORM) -> int:
        """Count how many No Answer -> Sent cycles exist in the audit trail."""
        raw = getattr(record, self._audit_field) or ""
        if not raw.strip():
            return 0

        count = 0
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("from_stage") == "No Answer" and entry.get("to_stage") == "Sent":
                    count += 1
            except json.JSONDecodeError:
                continue
        return count

    def transition(
        self,
        company_name: str,
        new_stage: str,
        metadata: dict | None = None,
    ) -> OutreachORM:
        """Execute a stage transition with validation and audit logging.

        Raises InvalidTransitionError if the transition is not allowed.
        Raises ValueError if the company is not found.
        """
        record = self._get_outreach_record(company_name)
        current = record.stage
        allowed = VALID_TRANSITIONS.get(current, set())

        if new_stage not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from '{current}' to '{new_stage}'. "
                f"Allowed: {sorted(allowed) if allowed else 'none (terminal state)'}"
            )

        # Circuit breaker: prevent infinite No Answer -> Sent loops
        if current == "No Answer" and new_stage == "Sent":
            cycles = self._count_resend_cycles(record)
            if cycles >= MAX_RESEND_CYCLES:
                raise InvalidTransitionError(
                    f"Circuit breaker: {cycles} resend cycles reached "
                    f"(max {MAX_RESEND_CYCLES}). Consider a different approach for '{company_name}'."
                )

        # Build audit entry
        audit_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "from_stage": current,
            "to_stage": new_stage,
            "metadata": metadata or {},
        }

        # Append to audit trail (newline-separated JSON objects)
        existing = getattr(record, self._audit_field) or ""
        separator = "\n" if existing else ""
        setattr(
            record,
            self._audit_field,
            existing + separator + json.dumps(audit_entry),
        )

        # Update stage
        record.stage = new_stage

        # Update timestamps based on transition
        if new_stage == "Sent":
            record.sent_at = datetime.now(UTC)
        elif new_stage in ("Responded", "Interview", "Declined", "Offer", "Rejected"):
            record.response_at = datetime.now(UTC)

        self.session.commit()
        logger.info(
            "Transitioned '{}': '{}' -> '{}'",
            company_name,
            current,
            new_stage,
        )
        return record

    def get_audit_trail(self, company_name: str) -> list[dict]:
        """Return the audit trail as a list of dicts.

        Each entry has: timestamp, from_stage, to_stage, metadata.
        """
        record = self._get_outreach_record(company_name)
        raw = getattr(record, self._audit_field) or ""
        if not raw.strip():
            return []

        trail: list[dict] = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line:
                trail.append(json.loads(line))
        return trail

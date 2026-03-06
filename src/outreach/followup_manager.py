"""Follow-up scheduling and overdue detection for outreach sequences."""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, OutreachORM


class FollowUpManager:
    """Manages follow-up scheduling, overdue detection, and daily alerts."""

    SEQUENCE_GAPS: dict[str, int] = {
        "connection_request->follow_up": 3,
        "follow_up->deeper_engagement": 5,
        "deeper_engagement->final_touch": 5,
    }

    STEP_ORDER: list[str] = [
        "pre_engagement",
        "connection_request",
        "follow_up",
        "deeper_engagement",
        "final_touch",
    ]

    def __init__(self, session: Session):
        self.session = session

    def _get_next_step(self, current_step: str) -> str | None:
        """Get the next step in the sequence after current_step."""
        try:
            idx = self.STEP_ORDER.index(current_step)
            if idx + 1 < len(self.STEP_ORDER):
                return self.STEP_ORDER[idx + 1]
        except ValueError:
            pass
        return None

    def _get_gap_days(self, current_step: str, next_step: str) -> int:
        """Get the expected gap in days between two steps."""
        key = f"{current_step}->{next_step}"
        return self.SEQUENCE_GAPS.get(key, 3)  # default 3 days

    def get_overdue_followups(self, grace_days: int = 2) -> list[dict]:
        """Find outreach records where the next follow-up is overdue.

        Args:
            grace_days: Extra days of grace before marking as overdue.

        Returns:
            List of dicts with company_name, contact_name, last_step, next_step,
            days_overdue, suggested_template.
        """
        now = datetime.now()

        # Get all "Sent" records
        sent_records = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.stage == "Sent",
                OutreachORM.sent_at.isnot(None),
            )
            .all()
        )

        overdue = []
        for record in sent_records:
            current_step = record.sequence_step or ""
            next_step = self._get_next_step(current_step)

            if next_step is None:
                continue  # Last step in sequence, no follow-up needed

            # Check if next step already exists
            next_exists = (
                self.session.query(OutreachORM)
                .filter(
                    OutreachORM.company_name == record.company_name,
                    OutreachORM.sequence_step == next_step,
                    OutreachORM.stage.in_(["Sent", "Responded"]),
                )
                .first()
            )
            if next_exists:
                continue

            gap_days = self._get_gap_days(current_step, next_step)
            due_date = record.sent_at + timedelta(days=gap_days + grace_days)

            if now > due_date:
                days_overdue = (now - due_date).days
                overdue.append({
                    "company_name": record.company_name,
                    "contact_name": record.contact_name,
                    "last_step": current_step,
                    "next_step": next_step,
                    "days_overdue": days_overdue,
                    "suggested_template": self.suggest_next_template(
                        record.company_name, current_step
                    ),
                })

        return sorted(overdue, key=lambda x: x["days_overdue"], reverse=True)

    def get_pending_followups(self, days_ahead: int = 3) -> list[dict]:
        """Get follow-ups due within the next N days.

        Args:
            days_ahead: How many days ahead to look.

        Returns:
            List of dicts with company_name, contact_name, step, due_date.
        """
        now = datetime.now()
        window_end = now + timedelta(days=days_ahead)

        sent_records = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.stage == "Sent",
                OutreachORM.sent_at.isnot(None),
            )
            .all()
        )

        pending = []
        for record in sent_records:
            current_step = record.sequence_step or ""
            next_step = self._get_next_step(current_step)

            if next_step is None:
                continue

            # Check if next step already exists
            next_exists = (
                self.session.query(OutreachORM)
                .filter(
                    OutreachORM.company_name == record.company_name,
                    OutreachORM.sequence_step == next_step,
                    OutreachORM.stage.in_(["Sent", "Responded"]),
                )
                .first()
            )
            if next_exists:
                continue

            gap_days = self._get_gap_days(current_step, next_step)
            due_date = record.sent_at + timedelta(days=gap_days)

            if now <= due_date <= window_end:
                pending.append({
                    "company_name": record.company_name,
                    "contact_name": record.contact_name,
                    "step": next_step,
                    "due_date": due_date.strftime("%Y-%m-%d"),
                })

        return pending

    def generate_daily_alert(self) -> dict:
        """Generate a daily alert summarizing follow-up status.

        Returns:
            Dict with overdue, due_today, due_this_week, total_active_sequences.
        """
        overdue = self.get_overdue_followups()
        today_followups = self.get_pending_followups(days_ahead=1)
        week_followups = self.get_pending_followups(days_ahead=7)

        # Count active sequences (companies with at least one Sent)
        active = (
            self.session.query(OutreachORM.company_name)
            .filter(OutreachORM.stage == "Sent")
            .distinct()
            .count()
        )

        return {
            "overdue": overdue,
            "due_today": today_followups,
            "due_this_week": week_followups,
            "total_active_sequences": active,
        }

    def suggest_next_template(self, company_name: str, current_step: str) -> str:
        """Suggest the next template based on current step.

        Args:
            company_name: Company name (for potential future personalization).
            current_step: The current step name.

        Returns:
            Template filename suggestion.
        """
        template_map = {
            "pre_engagement": "connection_request_a.j2",
            "connection_request": "follow_up_a.j2",
            "follow_up": "follow_up_b.j2",
            "deeper_engagement": "inmail_a.j2",
        }
        return template_map.get(current_step, "follow_up_a.j2")

    # ------------------------------------------------------------------
    # Follow-up automation: draft creation and send-queue integration
    # ------------------------------------------------------------------

    def auto_draft_followups(self, max_drafts: int = 10) -> dict:
        """Create draft OutreachORM records for overdue follow-ups.

        For each overdue item returned by ``generate_daily_alert()['overdue']``,
        a new OutreachORM record is created with stage="Not Started" and the
        template_type derived from the overdue item's suggested_template.

        Deduplication: if a draft (stage="Not Started") already exists for the
        same company_name + next sequence_step, it is skipped.

        Args:
            max_drafts: Maximum number of drafts to create in one call.

        Returns:
            Dict with keys ``drafted`` (int), ``skipped_duplicates`` (int),
            ``errors`` (list of str).
        """
        alert = self.generate_daily_alert()
        overdue_items = alert["overdue"]

        drafted = 0
        skipped_duplicates = 0
        errors: list[str] = []

        for item in overdue_items:
            if drafted >= max_drafts:
                break

            company_name = item["company_name"]
            next_step = item["next_step"]

            # Dedup: check if a draft already exists for this company + step
            existing_draft = (
                self.session.query(OutreachORM)
                .filter(
                    OutreachORM.company_name == company_name,
                    OutreachORM.sequence_step == next_step,
                    OutreachORM.stage == "Not Started",
                )
                .first()
            )
            if existing_draft:
                skipped_duplicates += 1
                continue

            try:
                # Resolve company_id if possible
                company = (
                    self.session.query(CompanyORM)
                    .filter(CompanyORM.name == company_name)
                    .first()
                )

                draft = OutreachORM(
                    company_id=company.id if company else None,
                    company_name=company_name,
                    contact_name=item.get("contact_name", ""),
                    stage="Not Started",
                    sequence_step=next_step,
                    template_type=item.get("suggested_template", "follow_up_a.j2"),
                )
                self.session.add(draft)
                self.session.flush()
                drafted += 1
                logger.info(
                    "Drafted follow-up for {} step={}",
                    company_name,
                    next_step,
                )
            except Exception as exc:
                errors.append(f"{company_name}: {exc}")
                logger.error(
                    "Failed to draft follow-up for {}: {}", company_name, exc
                )

        if drafted:
            self.session.commit()

        return {
            "drafted": drafted,
            "skipped_duplicates": skipped_duplicates,
            "errors": errors,
        }

    def queue_followups(self) -> list[dict]:
        """Return follow-up drafts ready for the send queue.

        Queries OutreachORM for records where stage="Not Started" and
        sequence_step corresponds to a follow-up (i.e. not the first step
        in the sequence — sequence_step index > 0 in STEP_ORDER, which
        means sequence_step != "pre_engagement").

        Returns:
            List of dicts with keys: company_name, contact_name,
            template_type, sequence_step, content.
        """
        # Follow-up steps are everything after the first step in STEP_ORDER
        first_step = self.STEP_ORDER[0] if self.STEP_ORDER else ""

        drafts = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.stage == "Not Started",
                OutreachORM.sequence_step != first_step,
                OutreachORM.sequence_step != "",
            )
            .all()
        )

        result = []
        for draft in drafts:
            # Only include if sequence_step is actually in STEP_ORDER at index > 0
            if draft.sequence_step in self.STEP_ORDER:
                idx = self.STEP_ORDER.index(draft.sequence_step)
                if idx < 1:
                    continue
            # If step is not in STEP_ORDER but is non-empty and not first_step,
            # still include it (defensive for custom steps)

            result.append({
                "company_name": draft.company_name,
                "contact_name": draft.contact_name,
                "template_type": draft.template_type,
                "sequence_step": draft.sequence_step,
                "content": draft.content,
            })

        return result

"""Gmail MCP bridge — format email drafts for gmail_create_draft consumption."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.integrations.email_outreach import EmailOutreach


class GmailBridge:
    """Format email drafts into Gmail MCP-ready dicts and persist to JSON."""

    def __init__(self, session: Session):
        self.session = session
        self._email = EmailOutreach(session)

    def prepare_drafts(self, threshold_days: int = 14) -> list[dict]:
        """Prepare all stale connection drafts in gmail_create_draft format.

        Returns list of {to, subject, body, metadata} dicts.
        Only includes contacts with email addresses.
        """
        result = self._email.batch_prepare_emails(threshold_days=threshold_days)
        drafts = []
        for draft in result["drafts"]:
            if not draft.get("to"):
                continue
            gmail_draft = {
                "to": draft["to"],
                "subject": draft["subject"],
                "body": draft["body"],
                "metadata": {
                    "company": draft.get("company", ""),
                    "contact": draft.get("contact", ""),
                    "prepared_at": datetime.now().isoformat(),
                    "source": "linkedin_followup",
                },
            }
            drafts.append(gmail_draft)

        logger.info(f"Prepared {len(drafts)} Gmail drafts (from {result['total_stale']} stale)")
        return drafts

    def save_drafts(self, drafts: list[dict], path: str = "data/gmail_drafts.json") -> int:
        """Persist drafts to JSON for MCP consumption."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        existing = []
        if p.exists():
            try:
                existing = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.extend(drafts)
        p.write_text(json.dumps(existing, indent=2, default=str))
        logger.info(f"Saved {len(drafts)} drafts to {path} (total: {len(existing)})")
        return len(drafts)

    def load_pending_drafts(self, path: str = "data/gmail_drafts.json") -> list[dict]:
        """Load pending drafts from JSON file."""
        p = Path(path)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def clear_drafts(self, path: str = "data/gmail_drafts.json") -> int:
        """Clear all pending drafts. Returns count cleared."""
        p = Path(path)
        if not p.exists():
            return 0
        drafts = self.load_pending_drafts(path)
        count = len(drafts)
        p.write_text("[]")
        return count

    def mark_drafts_sent(self, companies: list[str] | None = None) -> int:
        """Mark OutreachORM records as 'Draft Created' for companies with pending Gmail drafts."""
        from src.db.orm import OutreachORM

        query = self.session.query(OutreachORM).filter(OutreachORM.stage == "Not Started")
        if companies:
            query = query.filter(OutreachORM.company_name.in_(companies))
        records = query.all()
        for r in records:
            r.stage = "Draft Created"
            r.sent_at = datetime.now()
        self.session.commit()
        return len(records)


class ResponseMonitor:
    """Generate Gmail search queries for sent outreach and process responses."""

    def __init__(self, session: Session):
        self.session = session

    def get_pending_checks(self) -> list[dict]:
        """Query OutreachORM for stage='Sent', join ContactORM for emails.

        Returns list of dicts with: company, contact, email, sent_date,
        days_waiting, search_query.
        search_query format: 'from:<email> after:<YYYY/MM/DD>'
        """
        from src.db.orm import ContactORM, OutreachORM

        results = []
        outreach_records = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.stage == "Sent")
            .all()
        )
        for rec in outreach_records:
            # Try to find contact email via contact_id first, then company_name
            contact = None
            if rec.contact_id:
                contact = (
                    self.session.query(ContactORM)
                    .filter(ContactORM.id == rec.contact_id)
                    .first()
                )
            if not contact and rec.company_name:
                contact = (
                    self.session.query(ContactORM)
                    .filter(ContactORM.company_name == rec.company_name)
                    .first()
                )

            email = getattr(contact, "email", None) if contact else None
            # Treat empty string as no email
            if not email:
                email = None

            contact_name = (
                getattr(contact, "name", None) or rec.contact_name or "Unknown"
            )

            sent_date = rec.sent_at or rec.created_at
            days_waiting = (
                (datetime.now() - sent_date).days if sent_date else 0
            )

            search_query = None
            if email and sent_date:
                date_str = sent_date.strftime("%Y/%m/%d")
                search_query = f"from:{email} after:{date_str}"

            results.append(
                {
                    "company": rec.company_name,
                    "contact": contact_name,
                    "email": email,
                    "sent_date": (
                        str(sent_date.date()) if sent_date else "N/A"
                    ),
                    "days_waiting": days_waiting,
                    "search_query": search_query,
                }
            )
        return results

    def get_check_summary(self) -> dict:
        """Return summary counts for pending checks."""
        checks = self.get_pending_checks()
        with_email = sum(1 for c in checks if c["email"])
        without_email = sum(1 for c in checks if not c["email"])
        max_days = max((c["days_waiting"] for c in checks), default=0)
        return {
            "total_sent": len(checks),
            "with_email": with_email,
            "without_email": without_email,
            "oldest_waiting_days": max_days,
        }

    def process_response(self, company_name: str, response_text: str) -> dict:
        """Classify + log a response via ResponseTracker."""
        from src.outreach.response_tracker import ResponseTracker

        tracker = ResponseTracker(self.session)
        result = tracker.log_response(company_name, response_text)
        return result

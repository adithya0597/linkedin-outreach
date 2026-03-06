"""Email outreach fallback — find stale LinkedIn connections and prepare email drafts."""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, ContactORM, OutreachORM

STALE_THRESHOLD_DAYS = 14


class EmailOutreach:
    """Prepare email drafts for stale LinkedIn connection requests."""

    def __init__(self, session: Session):
        self.session = session
        self._drafts_prepared = 0

    def find_stale_connections(
        self, threshold_days: int = STALE_THRESHOLD_DAYS
    ) -> list[dict]:
        """Find connection requests that were sent but never got a response.

        Returns outreach records where stage='Sent', sequence_step='connection_request',
        and sent_at is older than threshold_days, with no subsequent 'Responded' record
        for the same company.
        """
        cutoff = datetime.now() - timedelta(days=threshold_days)

        # Get all sent connection requests older than threshold
        sent_records = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.stage == "Sent",
                OutreachORM.sequence_step == "connection_request",
                OutreachORM.sent_at <= cutoff,
                OutreachORM.sent_at.isnot(None),
            )
            .all()
        )

        # Get companies that have a Responded record (exclude them)
        responded_companies = {
            r.company_name
            for r in self.session.query(OutreachORM.company_name)
            .filter(OutreachORM.stage == "Responded")
            .all()
        }

        stale = []
        for record in sent_records:
            if record.company_name in responded_companies:
                continue

            days_since = (datetime.now() - record.sent_at).days

            contact = (
                self.session.query(ContactORM)
                .filter(
                    ContactORM.company_name == record.company_name,
                    ContactORM.name == record.contact_name,
                )
                .first()
            )
            contact_email = contact.email if contact and contact.email else None

            stale.append(
                {
                    "company_name": record.company_name,
                    "contact_name": record.contact_name,
                    "sent_at": record.sent_at,
                    "days_since_sent": days_since,
                    "contact_email": contact_email,
                }
            )

        logger.info(f"Found {len(stale)} stale connections (threshold={threshold_days}d)")
        return stale

    def generate_email_draft(self, company_name: str, contact_name: str) -> dict:
        """Generate an email draft for a stale connection.

        Uses CompanyORM and ContactORM context to build a value-first email
        referencing the LinkedIn connection attempt.
        """
        company = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.name == company_name)
            .first()
        )
        contact = (
            self.session.query(ContactORM)
            .filter(
                ContactORM.company_name == company_name,
                ContactORM.name == contact_name,
            )
            .first()
        )

        role = company.role if company and company.role else "AI Engineer"
        ai_desc = (
            company.ai_product_description
            if company and company.ai_product_description
            else ""
        )
        contact_title = contact.title if contact and contact.title else ""

        # Build body
        body_lines = [
            f"Hi {contact_name.split()[0] if contact_name else 'there'},",
            "",
            "I recently sent a connection request on LinkedIn — wanted to follow up here.",
        ]

        if ai_desc:
            body_lines.append(
                f"I've been following {company_name}'s work in {ai_desc[:80]} "
                "and see strong alignment with my background in AI engineering."
            )

        body_lines.extend(
            [
                "",
                "I build production AI systems — semantic graphs, agentic pipelines, "
                "and large-scale data infrastructure. Would love to explore how my "
                f"experience could contribute to {company_name}.",
                "",
                "Happy to share specifics if there's interest.",
                "",
                "Best,",
                "Bala Adithya Malaraju",
            ]
        )

        subject = f"Re: {role} opportunity at {company_name}"

        contact_email = contact.email if contact and contact.email else None
        draft = {
            "to": contact_email,
            "subject": subject,
            "body": "\n".join(body_lines),
            "company": company_name,
            "contact": contact_name,
        }

        logger.debug(f"Generated email draft for {contact_name} at {company_name}")
        return draft

    def batch_prepare_emails(
        self, threshold_days: int = STALE_THRESHOLD_DAYS
    ) -> dict:
        """Find all stale connections and generate email drafts.

        Returns summary with drafts list, skipped count (no email), and total stale.
        """
        stale = self.find_stale_connections(threshold_days=threshold_days)
        drafts = []
        skipped_no_email = 0

        for entry in stale:
            draft = self.generate_email_draft(
                entry["company_name"], entry["contact_name"]
            )
            # Skip contacts with no email on file
            if entry["contact_email"] is None:
                skipped_no_email += 1
            drafts.append(draft)

        self._drafts_prepared = len(drafts)

        logger.info(
            f"Batch prepared {len(drafts)} drafts, "
            f"{skipped_no_email} without email, {len(stale)} total stale"
        )

        return {
            "drafts": drafts,
            "skipped_no_email": skipped_no_email,
            "total_stale": len(stale),
        }

    def get_email_status(self) -> dict:
        """Return current email outreach status summary."""
        stale = self.find_stale_connections()
        with_email = sum(1 for s in stale if s["contact_email"] is not None)
        without_email = sum(1 for s in stale if s["contact_email"] is None)

        return {
            "total_stale": len(stale),
            "with_email": with_email,
            "without_email": without_email,
            "drafts_prepared": self._drafts_prepared,
        }

    @staticmethod
    def to_gmail_format(draft: dict) -> dict:
        """Convert an email draft dict to gmail_create_draft MCP format.

        Takes a draft dict with {to, subject, body, company, contact} and
        returns {to, subject, body, metadata} suitable for gmail_create_draft.
        """
        return {
            "to": draft.get("to"),
            "subject": draft.get("subject", ""),
            "body": draft.get("body", ""),
            "metadata": {
                "company": draft.get("company", ""),
                "contact": draft.get("contact", ""),
                "prepared_at": datetime.now().isoformat(),
                "source": "linkedin_followup",
            },
        }

    def prepare_gmail_drafts(
        self, threshold_days: int = STALE_THRESHOLD_DAYS
    ) -> list[dict]:
        """Batch prepare emails and convert to gmail_create_draft format.

        Calls batch_prepare_emails, filters out drafts without 'to' address,
        and converts each to Gmail MCP format.
        """
        result = self.batch_prepare_emails(threshold_days=threshold_days)
        gmail_drafts = []
        for draft in result["drafts"]:
            if not draft.get("to"):
                continue
            gmail_drafts.append(self.to_gmail_format(draft))

        logger.info(
            f"Prepared {len(gmail_drafts)} Gmail-format drafts "
            f"(from {result['total_stale']} stale)"
        )
        return gmail_drafts

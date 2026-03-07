"""Daily send queue — prioritized action list with LinkedIn rate limiting."""

from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy.orm import Session

from sqlalchemy import func

from src.db.orm import CompanyORM, ContactORM, OutreachORM

WEEKLY_SEND_LIMIT = 100
DEFAULT_DAILY_MAX = 20


class SendQueueManager:
    """Generate prioritized daily action list from existing drafts."""

    def __init__(self, session: Session):
        self.session = session

    def get_rate_limit_status(self) -> dict:
        """Get current weekly rate limit status.

        Returns dict with sent_this_week, limit, remaining, resets_on.
        """
        now = datetime.now()
        # Monday 00:00 of current week
        monday = now - timedelta(days=now.weekday())
        week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)

        sent_count = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.stage == "Sent",
                OutreachORM.sent_at >= week_start,
            )
            .count()
        )

        # Next Monday
        next_monday = week_start + timedelta(weeks=1)

        return {
            "sent_this_week": sent_count,
            "limit": WEEKLY_SEND_LIMIT,
            "remaining": max(0, WEEKLY_SEND_LIMIT - sent_count),
            "resets_on": next_monday.strftime("%Y-%m-%d"),
        }

    def get_linkedin_actions(self, company_name: str) -> dict:
        """Get LinkedIn action URLs for a company.

        Returns dict with profile_url, connect_url, message_url, careers_url.
        """
        company = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.name == company_name)
            .first()
        )

        contact = None
        if company:
            contact = (
                self.session.query(ContactORM)
                .filter(ContactORM.company_id == company.id)
                .order_by(ContactORM.contact_score.desc())
                .first()
            )

        return {
            "profile_url": contact.linkedin_url if contact and contact.linkedin_url else None,
            "connect_url": None,  # Would need profile URL transform
            "message_url": None,
            "careers_url": company.careers_url if company and company.careers_url else None,
        }

    def generate_daily_queue(self, max_sends: int = DEFAULT_DAILY_MAX, ab_manager=None) -> list[dict]:
        """Generate prioritized daily send queue.

        Queries OutreachORM stage="Not Started" joined to CompanyORM,
        sorted by fit_score DESC, capped by min(max_sends, remaining_this_week).

        If ab_manager is provided, assigns A/B test variants to each queue item.

        Returns list of dicts with company_name, contact_name, template_type,
        content, char_count, fit_score, linkedin_actions, ab_variant.
        """
        rate_status = self.get_rate_limit_status()
        effective_limit = min(max_sends, rate_status["remaining"])

        if effective_limit <= 0:
            logger.warning("Weekly send limit reached — no sends available")
            return []

        # Query Not Started outreach records joined with company for fit_score
        records = (
            self.session.query(OutreachORM, CompanyORM.fit_score)
            .join(CompanyORM, OutreachORM.company_id == CompanyORM.id)
            .filter(
                OutreachORM.stage == "Not Started",
                CompanyORM.is_disqualified == False,  # noqa: E712
            )
            .order_by(CompanyORM.fit_score.desc().nullslast())
            .limit(effective_limit)
            .all()
        )

        queue = []
        for outreach, fit_score in records:
            actions = self.get_linkedin_actions(outreach.company_name)
            item = {
                "company_name": outreach.company_name,
                "contact_name": outreach.contact_name,
                "template_type": outreach.template_type,
                "content": outreach.content,
                "char_count": outreach.character_count,
                "fit_score": fit_score or 0,
                "linkedin_actions": actions,
                "ab_variant": None,
            }

            if ab_manager:
                experiment = ab_manager.get_active_experiment()
                if experiment:
                    variant = ab_manager.assign_variant(experiment["name"], outreach.company_name)
                    item["ab_variant"] = variant
                    item["template_type"] = variant

            queue.append(item)

        logger.info(
            f"Daily queue: {len(queue)} items "
            f"(limit: {effective_limit}, weekly remaining: {rate_status['remaining']})"
        )
        return queue

    def get_outreach_status_summary(self) -> dict:
        """Return outreach counts by stage."""
        rows = (
            self.session.query(OutreachORM.stage, func.count())
            .group_by(OutreachORM.stage)
            .all()
        )
        return {stage: count for stage, count in rows}

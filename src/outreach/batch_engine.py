"""Batch outreach drafting engine — drafts for all qualifying companies at once."""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, ContactORM, OutreachORM
from src.outreach.personalizer import OutreachPersonalizer
from src.outreach.template_engine import OutreachTemplateEngine, SequenceBuilder


class BatchOutreachEngine:
    """Batch draft outreach messages for qualifying companies."""

    # Template selection by contact role
    _ROLE_TEMPLATE_MAP = {
        "technical": "connection_request_a.j2",   # CTO, VP, Founder
        "metrics": "connection_request_b.j2",     # Recruiter, Talent
        "balanced": "connection_request_c.j2",    # Default
    }

    # Template rotation order for avoiding duplicates
    _CONNECTION_TEMPLATES = [
        "connection_request_a.j2",
        "connection_request_b.j2",
        "connection_request_c.j2",
    ]

    _FOLLOW_UP_TEMPLATES = ["follow_up_a.j2", "follow_up_b.j2"]

    _SEQUENCE_TEMPLATE_MAP = {
        "pre_engagement": "pre_engagement_a.j2",
        "connection_request": "connection_request_a.j2",
        "follow_up": "follow_up_a.j2",
        "deeper_engagement": "follow_up_b.j2",
        "final_touch": "inmail_a.j2",
    }

    def __init__(self, session: Session):
        self.session = session
        self.personalizer = OutreachPersonalizer()
        self.engine = OutreachTemplateEngine()
        self.sequence_builder = SequenceBuilder()

    def _get_primary_contact(self, company: CompanyORM) -> ContactORM | None:
        """Get primary contact for a company (highest score)."""
        return (
            self.session.query(ContactORM)
            .filter(ContactORM.company_id == company.id)
            .order_by(ContactORM.contact_score.desc())
            .first()
        )

    def _select_template(
        self, message_type: str, contact: ContactORM | None, existing_templates: list[str]
    ) -> str:
        """Select template, rotating to avoid duplicates. Picks role-appropriate template first."""
        if message_type == "connection_request":
            pool = self._CONNECTION_TEMPLATES
            # Pick role-based first if no existing
            if contact and not existing_templates:
                title = (contact.title or "").lower()
                if any(t in title for t in ["cto", "vp", "head", "director", "founder"]):
                    return self._ROLE_TEMPLATE_MAP["technical"]
                elif any(t in title for t in ["recruiter", "talent", "hr"]):
                    return self._ROLE_TEMPLATE_MAP["metrics"]
                return self._ROLE_TEMPLATE_MAP["balanced"]
        elif message_type == "follow_up":
            pool = self._FOLLOW_UP_TEMPLATES
        else:
            return f"{message_type}_a.j2"

        # Rotate: pick first template not already used
        for tmpl in pool:
            if tmpl not in existing_templates:
                return tmpl
        # All used — cycle back to first
        return pool[0]

    def draft_for_company(
        self,
        company: CompanyORM,
        contact: ContactORM | None = None,
        template_types: list[str] | None = None,
    ) -> list[OutreachORM]:
        """Draft outreach messages for a single company.

        Returns list of created OutreachORM records.
        """
        if contact is None:
            contact = self._get_primary_contact(company)

        context = self.personalizer.enrich_context(company, contact)
        types = template_types or ["connection_request"]

        drafts = []
        for msg_type in types:
            # Check existing drafts for this company+type to avoid duplicates
            existing = (
                self.session.query(OutreachORM.template_type)
                .filter(
                    OutreachORM.company_id == company.id,
                    OutreachORM.template_type.like(f"{msg_type}%"),
                )
                .all()
            )
            existing_templates = [e[0] for e in existing]

            template_name = self._select_template(msg_type, contact, existing_templates)

            # Determine char limit
            if "connection" in msg_type:
                char_limit = 300
                engine_type = "connection_request"
            elif "inmail" in msg_type:
                char_limit = 400
                engine_type = "inmail"
            elif "pre_engagement" in msg_type:
                char_limit = 280
                engine_type = "pre_engagement"
            else:
                char_limit = 0  # no limit for follow-ups
                engine_type = "follow_up"

            rendered, is_valid, char_count = self.engine.render(
                template_name, context, engine_type
            )

            record = OutreachORM(
                company_id=company.id,
                company_name=company.name,
                contact_name=contact.name if contact else "",
                contact_id=contact.id if contact else None,
                template_type=template_name,
                content=rendered,
                character_count=char_count,
                char_limit=char_limit if char_limit > 0 else 0,
                is_within_limit=is_valid,
                stage="Not Started",
                sequence_step=msg_type,
            )
            self.session.add(record)
            drafts.append(record)

        self.session.flush()
        return drafts

    def draft_all(
        self,
        tier: str | None = None,
        limit: int | None = None,
        template_types: list[str] | None = None,
    ) -> dict:
        """Batch draft outreach for qualifying companies.

        Returns dict with counts: {drafted, skipped, over_limit, errors}.
        """
        query = self.session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        )
        if tier:
            query = query.filter(CompanyORM.tier == tier)

        query = query.order_by(CompanyORM.fit_score.desc().nullslast())
        if limit:
            query = query.limit(limit)

        companies = query.all()

        results = {"drafted": 0, "skipped": 0, "over_limit": 0, "errors": []}

        for company in companies:
            try:
                contact = self._get_primary_contact(company)
                drafts = self.draft_for_company(company, contact, template_types)

                for draft in drafts:
                    if draft.is_within_limit:
                        results["drafted"] += 1
                    else:
                        results["over_limit"] += 1

                if not drafts:
                    results["skipped"] += 1

            except Exception as e:
                results["errors"].append(f"{company.name}: {e}")
                logger.error(f"Draft failed for {company.name}: {e}")

        self.session.commit()
        logger.info(
            f"Batch draft complete: {results['drafted']} drafted, "
            f"{results['skipped']} skipped, {results['over_limit']} over limit, "
            f"{len(results['errors'])} errors"
        )
        return results

    def build_sequence(
        self,
        company_name: str,
        contact_name: str,
        start_date: str | None = None,
    ) -> list[dict]:
        """Build a 14-day outreach sequence with template recommendations.

        Creates OutreachORM records for each touch point.
        Returns list of sequence step dicts.
        """
        if start_date is None:
            start_date = datetime.now().strftime("%Y-%m-%d")

        company = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.name == company_name)
            .first()
        )
        if not company:
            logger.warning(f"Company not found: {company_name}")
            return []

        contact = (
            self.session.query(ContactORM)
            .filter(
                ContactORM.company_id == company.id,
                ContactORM.name == contact_name,
            )
            .first()
        )

        sequence = self.sequence_builder.build_sequence(
            start_date, contact_name, company_name
        )

        # Enrich with template recommendations and create ORM records
        context = self.personalizer.enrich_context(company, contact)

        for step in sequence:
            step_name = step["step"]
            template = self._SEQUENCE_TEMPLATE_MAP.get(step_name, f"{step_name}_a.j2")
            step["template"] = template

            # Render the template
            if "connection" in step_name:
                engine_type = "connection_request"
                char_limit = 300
            elif "inmail" in step_name or "final" in step_name:
                engine_type = "inmail"
                char_limit = 400
            elif "pre_engagement" in step_name:
                engine_type = "pre_engagement"
                char_limit = 280
            else:
                engine_type = "follow_up"
                char_limit = 0

            try:
                rendered, is_valid, char_count = self.engine.render(
                    template, context, engine_type
                )
            except Exception as e:
                logger.warning(f"Render failed for template {template} in sequence: {e}")
                rendered = ""
                is_valid = True
                char_count = 0

            step["content_preview"] = rendered[:100] + "..." if len(rendered) > 100 else rendered
            step["char_count"] = char_count
            step["is_valid"] = is_valid

            # Create OutreachORM record
            record = OutreachORM(
                company_id=company.id,
                company_name=company_name,
                contact_name=contact_name,
                contact_id=contact.id if contact else None,
                template_type=template,
                content=rendered,
                character_count=char_count,
                char_limit=char_limit if char_limit > 0 else 0,
                is_within_limit=is_valid,
                stage="Not Started",
                sequence_step=step_name,
            )
            self.session.add(record)

        self.session.commit()
        return sequence

"""Response tracking -- classify responses, recommend next actions, build funnels.

v2: Score-based classification replaces first-match-wins to fix order dependency bugs.
v3: Optional LLM-powered classification with confidence scores (falls back to keyword).
"""

from __future__ import annotations

import json
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, OutreachORM
from src.outreach.llm_classifier import get_classifier
from src.outreach.sequence_tracker import SequenceTracker

# Response classifications
POSITIVE = "POSITIVE"
NEUTRAL = "NEUTRAL"
NEGATIVE = "NEGATIVE"
REFERRAL = "REFERRAL"
AUTO_REPLY = "AUTO_REPLY"

ALL_CLASSIFICATIONS = [POSITIVE, NEUTRAL, NEGATIVE, REFERRAL, AUTO_REPLY]

# ---------------------------------------------------------------------------
# v2 keyword lists (expanded from v1's 5 POSITIVE keywords)
# ---------------------------------------------------------------------------

_AUTO_REPLY_KEYWORDS: list[str] = [
    "out of office", "auto-reply", "automatic reply", "ooo",
]

_POSITIVE_KEYWORDS: list[str] = [
    "interview", "schedule a call", "love to chat", "meet",
    "exciting", "interested", "tell me more", "sounds great",
    "let's connect", "would love to", "happy to chat", "reach out",
    "send me", "looking forward", "great fit", "let's talk",
]

_NEGATIVE_KEYWORDS: list[str] = [
    "not hiring", "no positions", "not a fit", "unfortunately",
    "not able", "not hiring", "filled the position",
    "no longer available", "moved on",
]

_REFERRAL_KEYWORDS: list[str] = [
    "check with", "refer", "try reaching", "connect you with",
    "talk to", "forward your info",
]

# Negative override words -- when present alongside positive keywords,
# force classification to NEGATIVE (e.g., "unfortunately we love to chat").
_NEGATIVE_OVERRIDES: list[str] = [
    "unfortunately", "regret", "unable", "sorry to",
]

# Recommended next actions per classification
_NEXT_ACTIONS: dict[str, str] = {
    POSITIVE: "Schedule call",
    REFERRAL: "Contact referred person",
    NEGATIVE: "Archive and move on",
    NEUTRAL: "Send follow-up",
    AUTO_REPLY: "Wait and retry",
}


def _count_keyword_matches(text: str, keywords: list[str]) -> int:
    """Count how many keywords from *keywords* appear in *text*."""
    lower = text.lower()
    return sum(1 for kw in keywords if kw in lower)


def _auto_classify(text: str) -> str:
    """Classify response text using score-based keyword matching.

    Algorithm (v2):
    1. AUTO_REPLY is checked first -- any match is definitive.
    2. Count matches per category (positive, negative, referral).
    3. If positive keywords match AND a negative override word is present,
       classify as NEGATIVE (conservative).
    4. Highest count wins. On tie, prefer NEGATIVE (conservative).
    5. If no keywords match at all, return NEUTRAL.
    """
    if not text or not text.strip():
        return NEUTRAL

    lower = text.lower()

    # Step 1: AUTO_REPLY always wins
    for kw in _AUTO_REPLY_KEYWORDS:
        if kw in lower:
            return AUTO_REPLY

    # Step 2: Count matches per category
    positive_count = _count_keyword_matches(text, _POSITIVE_KEYWORDS)
    negative_count = _count_keyword_matches(text, _NEGATIVE_KEYWORDS)
    referral_count = _count_keyword_matches(text, _REFERRAL_KEYWORDS)
    override_count = _count_keyword_matches(text, _NEGATIVE_OVERRIDES)

    # Step 3: Negative override handling
    # 3a: If positive keywords matched AND a negative override word is present,
    #     force NEGATIVE (the core bug fix).
    if positive_count > 0 and override_count > 0:
        return NEGATIVE
    # 3b: Override words also count as negative signals on their own.
    #     This handles "sorry to say we're unable to move forward" where
    #     no explicit negative keywords match but the tone is clearly negative.
    negative_count += override_count

    # Step 4: Highest count wins; ties go to NEGATIVE (conservative)
    if positive_count == 0 and negative_count == 0 and referral_count == 0:
        return NEUTRAL

    # Build scored list: (count, priority, classification)
    # Lower priority number = preferred on tie.  NEGATIVE=0 wins ties.
    scored = [
        (negative_count, 0, NEGATIVE),
        (referral_count, 1, REFERRAL),
        (positive_count, 2, POSITIVE),
    ]
    # Sort descending by count, then ascending by priority (for ties)
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored[0][2]


class ResponseTracker:
    """Track and classify outreach responses, recommend next actions."""

    def __init__(self, session: Session):
        self.session = session
        self._seq = SequenceTracker(session)

    # Expose classify_response as a public method for direct use
    @staticmethod
    def classify_response(text: str) -> str:
        """Classify a response text string. Public API for the v2 classifier."""
        return _auto_classify(text)

    @staticmethod
    def classify_response_llm(text: str, company_context: str = "") -> dict:
        """Classify using LLM if available, falling back to keyword classifier.

        Returns dict with:
            classification: str (POSITIVE, NEGATIVE, etc.)
            confidence: float | None (0.0-1.0 for LLM, None for keyword)
            source: str ("llm" or "keyword")
        """
        llm = get_classifier()
        if llm is not None:
            try:
                result = llm.classify(text, company_context=company_context)
                return {
                    "classification": result.classification,
                    "confidence": result.confidence,
                    "source": "llm",
                }
            except Exception as exc:
                logger.warning(f"LLM classifier failed, falling back to keyword: {exc}")

        # Fallback to keyword classifier
        return {
            "classification": _auto_classify(text),
            "confidence": None,
            "source": "keyword",
        }

    def log_response(
        self,
        company_name: str,
        response_text: str,
        classification: str | None = None,
    ) -> dict:
        """Log a response for a company.

        Calls SequenceTracker.mark_responded(), auto-classifies if classification
        not provided, stores classification in response_text as JSON.
        When no explicit classification is given, tries LLM first, then keyword.

        Returns dict with company, classification, next_action, response_time_days.
        """
        # Determine classification
        confidence: float | None = None
        source: str = "keyword"
        if classification:
            cls = classification
        else:
            result = self.classify_response_llm(response_text)
            cls = result["classification"]
            confidence = result["confidence"]
            source = result["source"]

        if cls not in ALL_CLASSIFICATIONS:
            logger.warning(f"Unknown classification '{cls}', defaulting to NEUTRAL")
            cls = NEUTRAL

        # Store as JSON in response_text (v3: includes confidence + source)
        response_payload = json.dumps({
            "text": response_text,
            "classification": cls,
            "confidence": confidence,
            "source": source,
        })

        # Use SequenceTracker to mark responded
        record = self._seq.mark_responded(company_name, response_payload)

        response_time_days: float | None = None
        if record and record.sent_at and record.response_at:
            delta = record.response_at - record.sent_at
            response_time_days = round(delta.total_seconds() / 86400, 1)

        if record:
            logger.info(f"Logged response for {company_name}: {cls}")
        else:
            logger.warning(f"No sent record found for {company_name}, response logged without record")

        return {
            "company": company_name,
            "classification": cls,
            "next_action": _NEXT_ACTIONS[cls],
            "response_time_days": response_time_days,
        }

    def _get_responded_records(self) -> list[OutreachORM]:
        """Get all outreach records with stage == Responded."""
        return (
            self.session.query(OutreachORM)
            .filter(OutreachORM.stage == "Responded")
            .all()
        )

    def _parse_classification(self, record: OutreachORM) -> str:
        """Extract classification from a responded record's response_text JSON."""
        if not record.response_text:
            return NEUTRAL
        try:
            data = json.loads(record.response_text)
            return data.get("classification", NEUTRAL)
        except (json.JSONDecodeError, TypeError):
            return NEUTRAL

    def get_response_summary(self) -> dict:
        """Get summary of all responses.

        Returns dict with total_responses, by_classification, avg_response_time_days,
        fastest_response, companies_responded.
        """
        records = self._get_responded_records()

        if not records:
            return {
                "total_responses": 0,
                "by_classification": {c: 0 for c in ALL_CLASSIFICATIONS},
                "avg_response_time_days": 0,
                "fastest_response": None,
                "companies_responded": [],
            }

        by_classification: dict[str, int] = {c: 0 for c in ALL_CLASSIFICATIONS}
        companies: list[str] = []
        response_times: list[float] = []

        for rec in records:
            cls = self._parse_classification(rec)
            by_classification[cls] = by_classification.get(cls, 0) + 1
            if rec.company_name and rec.company_name not in companies:
                companies.append(rec.company_name)
            if rec.sent_at and rec.response_at:
                days = (rec.response_at - rec.sent_at).total_seconds() / 86400
                response_times.append(round(days, 1))

        avg_time = round(sum(response_times) / len(response_times), 1) if response_times else 0
        fastest = min(response_times) if response_times else None

        return {
            "total_responses": len(records),
            "by_classification": by_classification,
            "avg_response_time_days": avg_time,
            "fastest_response": fastest,
            "companies_responded": companies,
        }

    def get_next_actions(self) -> list[dict]:
        """Get recommended next actions for each responded company.

        Returns list of dicts with company, classification, recommended_action.
        """
        records = self._get_responded_records()
        actions: list[dict] = []

        for rec in records:
            cls = self._parse_classification(rec)
            actions.append({
                "company": rec.company_name,
                "classification": cls,
                "recommended_action": _NEXT_ACTIONS[cls],
            })

        return actions

    def get_response_funnel(self) -> dict:
        """Get response funnel metrics.

        Returns dict with total_drafted, total_sent, total_responded,
        response_rate, by_tier.
        """
        total_drafted = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.stage == "Not Started")
            .count()
        )
        total_sent = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.stage == "Sent")
            .count()
        )
        total_responded = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.stage == "Responded")
            .count()
        )

        # response_rate = responded / (sent + responded) * 100
        sent_plus_responded = total_sent + total_responded
        response_rate = round((total_responded / sent_plus_responded) * 100, 1) if sent_plus_responded > 0 else 0

        # By-tier breakdown
        by_tier: dict[str, dict] = {}
        tier_records = (
            self.session.query(OutreachORM, CompanyORM.tier)
            .outerjoin(CompanyORM, OutreachORM.company_id == CompanyORM.id)
            .all()
        )

        for outreach_rec, tier in tier_records:
            tier_name = tier or "Unknown"
            if tier_name not in by_tier:
                by_tier[tier_name] = {"drafted": 0, "sent": 0, "responded": 0}
            if outreach_rec.stage == "Not Started":
                by_tier[tier_name]["drafted"] += 1
            elif outreach_rec.stage == "Sent":
                by_tier[tier_name]["sent"] += 1
            elif outreach_rec.stage == "Responded":
                by_tier[tier_name]["responded"] += 1

        return {
            "total_drafted": total_drafted,
            "total_sent": total_sent,
            "total_responded": total_responded,
            "response_rate": response_rate,
            "by_tier": by_tier,
        }

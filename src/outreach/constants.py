"""Shared constants for the outreach module."""

from __future__ import annotations

# Outreach sequence steps in canonical order
STEP_ORDER: list[str] = [
    "pre_engagement",
    "connection_request",
    "follow_up",
    "deeper_engagement",
    "final_touch",
]

# Derived index lookup: step name -> position
STEP_INDEX: dict[str, int] = {step: i for i, step in enumerate(STEP_ORDER)}

# Gap (in days) between consecutive sequence steps
SEQUENCE_GAPS: dict[str, int] = {
    "connection_request->follow_up": 3,
    "follow_up->deeper_engagement": 5,
    "deeper_engagement->final_touch": 5,
}

# Response classification labels
POSITIVE = "POSITIVE"
NEUTRAL = "NEUTRAL"
NEGATIVE = "NEGATIVE"
REFERRAL = "REFERRAL"
AUTO_REPLY = "AUTO_REPLY"

ALL_CLASSIFICATIONS: list[str] = [POSITIVE, NEUTRAL, NEGATIVE, REFERRAL, AUTO_REPLY]

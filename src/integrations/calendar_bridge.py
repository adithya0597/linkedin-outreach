"""Calendar MCP bridge — create follow-up event payloads from positive responses."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger


try:
    from src.config.settings import get_settings
    _tz = get_settings().timezone
except Exception:
    _tz = "America/Chicago"


class CalendarBridge:
    """Create gcal_create_event-compatible payloads."""

    def create_followup_event(
        self, company: str, contact: str, days_out: int = 3
    ) -> dict:
        """Return gcal_create_event-compatible payload. Skips weekends."""
        target = datetime.now() + timedelta(days=days_out)
        # Skip weekends
        while target.weekday() >= 5:  # 5=Sat, 6=Sun
            target += timedelta(days=1)

        start = target.replace(hour=10, minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=30)

        return {
            "summary": f"Follow-up: {company} ({contact})",
            "description": (
                f"Follow-up with {contact} at {company}.\n"
                f"Scheduled automatically after positive response."
            ),
            "start": {"dateTime": start.isoformat(), "timeZone": _tz},
            "end": {"dateTime": end.isoformat(), "timeZone": _tz},
            "metadata": {
                "company": company,
                "contact": contact,
                "created_at": datetime.now().isoformat(),
                "source": "positive_response",
            },
        }

    def create_from_positive(
        self, company: str, contact: str, response_text: str
    ) -> dict:
        """Create event from a positive response with context."""
        event = self.create_followup_event(company, contact)
        event["description"] += f"\n\nResponse excerpt: {response_text[:200]}"
        return event

    def save_pending_events(
        self, events: list[dict], path: str = "data/calendar_events.json"
    ) -> int:
        """Persist events to JSON for MCP consumption."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        existing = []
        if p.exists():
            try:
                existing = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.extend(events)
        p.write_text(json.dumps(existing, indent=2, default=str))
        logger.info(f"Saved {len(events)} events to {path}")
        return len(events)

    def load_pending_events(self, path: str = "data/calendar_events.json") -> list[dict]:
        """Load pending events from JSON file."""
        p = Path(path)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return []

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

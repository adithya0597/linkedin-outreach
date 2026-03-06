from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.config.enums import OutreachStage


@dataclass
class OutreachMessage:
    id: int | None = None
    company_name: str = ""
    contact_name: str = ""
    contact_id: int | None = None
    template_type: str = ""  # e.g., "connection_request", "follow_up", "inmail"
    template_version: str = ""  # e.g., "A", "B", "C"
    content: str = ""
    character_count: int = 0
    char_limit: int = 300
    is_within_limit: bool = True
    sent_at: datetime | None = None
    response_at: datetime | None = None
    response_text: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def validate_length(self) -> bool:
        self.character_count = len(self.content)
        self.is_within_limit = self.character_count <= self.char_limit
        return self.is_within_limit


@dataclass
class OutreachSequence:
    id: int | None = None
    company_name: str = ""
    contact_name: str = ""
    contact_id: int | None = None
    stage: OutreachStage = OutreachStage.NOT_STARTED
    messages: list[OutreachMessage] = field(default_factory=list)
    start_date: datetime | None = None
    next_touch_date: datetime | None = None
    touch_count: int = 0
    max_touches: int = 4
    days_since_last_action: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

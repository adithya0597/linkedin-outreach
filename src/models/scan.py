from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.config.enums import SourcePortal


@dataclass
class ScanRecord:
    id: int | None = None
    portal: SourcePortal = SourcePortal.MANUAL
    scan_type: str = "full"  # "full" or "rescan"
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    companies_found: int = 0
    new_companies: int = 0
    errors: list[str] = field(default_factory=list)
    is_healthy: bool = True
    duration_seconds: float = 0.0

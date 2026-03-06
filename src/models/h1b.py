from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.config.enums import H1BStatus


@dataclass
class H1BRecord:
    id: int | None = None
    company_name: str = ""
    company_id: int | None = None
    status: H1BStatus = H1BStatus.UNKNOWN
    source: str = ""  # "Frog Hire", "H1BGrader", "MyVisaJobs"
    lca_count: int | None = None
    lca_fiscal_year: str = ""
    has_perm: bool = False
    has_everify: bool = False
    employee_count_on_source: str = ""
    ranking: str = ""  # e.g., "#4,833"
    approval_rate: float | None = None
    raw_data: str = ""
    verified_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None

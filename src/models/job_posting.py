from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.config.enums import SourcePortal


@dataclass
class JobPosting:
    id: int | None = None
    company_name: str = ""
    company_id: int | None = None
    title: str = ""
    url: str = ""
    source_portal: SourcePortal = SourcePortal.MANUAL
    location: str = ""
    work_model: str = ""  # remote/hybrid/onsite
    salary_min: int | None = None
    salary_max: int | None = None
    salary_range: str = ""
    description: str = ""
    requirements: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    posted_date: datetime | None = None
    discovered_date: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    h1b_mentioned: bool = False
    h1b_text: str = ""
    is_easy_apply: bool = False
    is_top_applicant: bool = False
    embedding: list[float] | None = None

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Contact:
    id: int | None = None
    name: str = ""
    title: str = ""
    company_name: str = ""
    company_id: int | None = None
    linkedin_url: str = ""
    linkedin_degree: int | None = None  # 1, 2, 3+
    mutual_connections: list[str] = field(default_factory=list)
    followers: int | None = None
    location: str = ""
    is_open_profile: bool = False
    is_recruiter: bool = False
    recent_posts: list[str] = field(default_factory=list)
    communication_style: str = ""  # casual/formal/technical
    contact_score: float = 0.0  # deterministic ranking
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def calculate_score(self) -> float:
        """Deterministic contact ranking."""
        score = 0.0
        # Degree scoring
        if self.linkedin_degree == 1:
            score += 3
        elif self.linkedin_degree == 2:
            score += 2
        # Role scoring
        title_lower = self.title.lower()
        if any(t in title_lower for t in ["cto", "vp eng", "vp of eng", "head of eng"]):
            score += 2
        elif any(t in title_lower for t in ["recruiter", "talent", "hiring"]):
            score += 1
        # Followers
        if self.followers and self.followers > 1000:
            score += 1
        # Open profile
        if self.is_open_profile:
            score += 2
        # Recent posts (active = good)
        if len(self.recent_posts) > 0:
            score += 1
        self.contact_score = score
        return score

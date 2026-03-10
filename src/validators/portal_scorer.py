"""Portal scoring system — promotion/demotion based on scan performance metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.db.orm import ScanORM


@dataclass
class PortalScore:
    """Score breakdown for a single portal."""
    portal: str
    velocity_score: int  # 0, 1, or 2
    afternoon_delta_score: int  # 0, 1, or 2
    conversion_score: int  # 0, 1, or 2
    total: int  # sum of above (max 6)
    recommendation: str  # "promote", "demote", "hold"


class PortalScorer:
    """Scores portals based on scan performance metrics."""

    def __init__(self, session: Session, config_path: str | None = None):
        self.session = session
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "schedule.yaml"
            )
        with open(config_path) as f:
            config = yaml.safe_load(f)

        rules = config.get("promotion_rules", {})
        self.promote_threshold = rules.get("promote_threshold", 4)
        self.demote_threshold = rules.get("demote_threshold", 3)
        self.review_window_weeks = rules.get("review_window_weeks", 2)

    def _get_review_window_start(self) -> datetime:
        return datetime.now() - timedelta(weeks=self.review_window_weeks)

    def _get_scans(self, portal: str) -> list[ScanORM]:
        window_start = self._get_review_window_start()
        return self.session.query(ScanORM).filter(
            ScanORM.portal == portal,
            ScanORM.started_at >= window_start,
        ).order_by(ScanORM.started_at).all()

    def _score_velocity(self, scans: list[ScanORM]) -> int:
        if not scans:
            return 0
        total_found = sum(s.companies_found for s in scans)
        first = scans[0].started_at
        last = scans[-1].started_at
        days = max((last - first).days, 1)
        velocity = total_found / days
        if velocity >= 8:
            return 2
        elif velocity >= 3:
            return 1
        return 0

    def _score_afternoon_delta(self, scans: list[ScanORM]) -> int:
        if not scans:
            return 0
        am_found = 0
        pm_new = 0
        for scan in scans:
            hour = scan.started_at.hour if scan.started_at else 12
            if hour < 12:
                am_found += scan.companies_found
            else:
                pm_new += scan.new_companies
        if am_found == 0:
            return 0
        ratio = pm_new / am_found
        if ratio >= 0.4:
            return 2
        elif ratio >= 0.2:
            return 1
        return 0

    def _score_conversion(self, scans: list[ScanORM]) -> int:
        if not scans:
            return 0
        total_found = sum(s.companies_found for s in scans)
        total_new = sum(s.new_companies for s in scans)
        if total_found == 0:
            return 0
        ratio = total_new / total_found
        if ratio >= 0.3:
            return 2
        elif ratio >= 0.15:
            return 1
        return 0

    def score_portal(self, portal: str) -> PortalScore:
        scans = self._get_scans(portal)
        velocity = self._score_velocity(scans)
        delta = self._score_afternoon_delta(scans)
        conversion = self._score_conversion(scans)
        total = velocity + delta + conversion
        if total >= self.promote_threshold:
            recommendation = "promote"
        elif total < self.demote_threshold:
            recommendation = "demote"
        else:
            recommendation = "hold"
        return PortalScore(
            portal=portal,
            velocity_score=velocity,
            afternoon_delta_score=delta,
            conversion_score=conversion,
            total=total,
            recommendation=recommendation,
        )

    def score_all(self) -> list[PortalScore]:
        portals = self.session.query(ScanORM.portal).distinct().all()
        portal_names = [p[0] for p in portals]
        return [self.score_portal(name) for name in sorted(portal_names)]

    def get_promotion_candidates(self) -> list[PortalScore]:
        return [s for s in self.score_all() if s.recommendation == "promote"]

    def get_demotion_candidates(self) -> list[PortalScore]:
        return [s for s in self.score_all() if s.recommendation == "demote"]

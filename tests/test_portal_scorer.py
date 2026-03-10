"""Tests for portal scoring system."""
import tempfile
from datetime import datetime, timedelta

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, ScanORM
from src.validators.portal_scorer import PortalScorer


@pytest.fixture
def scorer_session():
    """Session with scan records for multiple portals."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    now = datetime.now()

    # High-velocity portal "jobright" — 10 AM + 10 PM scans over ~10 days
    for i in range(10):
        day_offset = i
        # AM scan
        session.add(ScanORM(
            portal="jobright",
            scan_type="full",
            started_at=now - timedelta(days=day_offset, hours=16),  # 8 AM
            companies_found=10,
            new_companies=4,
        ))
        # PM scan
        session.add(ScanORM(
            portal="jobright",
            scan_type="rescan",
            started_at=now - timedelta(days=day_offset, hours=10),  # 2 PM
            companies_found=5,
            new_companies=3,
        ))

    # Zero-result portal "builtin"
    for i in range(3):
        session.add(ScanORM(
            portal="builtin",
            scan_type="full",
            started_at=now - timedelta(days=i * 4, hours=16),
            companies_found=0,
            new_companies=0,
        ))

    # Moderate portal "linkedin"
    for i in range(5):
        session.add(ScanORM(
            portal="linkedin",
            scan_type="full",
            started_at=now - timedelta(days=i * 2, hours=16),
            companies_found=3,
            new_companies=1,
        ))

    session.commit()
    yield session
    session.close()


@pytest.fixture
def config_path():
    """Temporary config file with scoring thresholds."""
    config = {
        "promotion_rules": {
            "promote_threshold": 4,
            "demote_threshold": 3,
            "review_window_weeks": 2,
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        return f.name


def _make_session():
    """Helper to create a fresh in-memory session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


class TestPortalScoring:
    def test_high_velocity_scores_high(self, scorer_session, config_path):
        """Jobright (high velocity, good conversion, afternoon delta) should score >= 4."""
        scorer = PortalScorer(scorer_session, config_path)
        result = scorer.score_portal("jobright")
        assert result.total >= 4
        assert result.recommendation == "promote"

    def test_zero_listings_demoted(self, scorer_session, config_path):
        """Builtin (zero companies found) should get 'demote'."""
        scorer = PortalScorer(scorer_session, config_path)
        result = scorer.score_portal("builtin")
        assert result.recommendation == "demote"
        assert result.total < 3

    def test_unknown_portal_returns_zeros(self, scorer_session, config_path):
        """Scoring a portal with no scan records should return all 0s and 'demote'."""
        scorer = PortalScorer(scorer_session, config_path)
        result = scorer.score_portal("nonexistent")
        assert result.velocity_score == 0
        assert result.afternoon_delta_score == 0
        assert result.conversion_score == 0
        assert result.total == 0
        assert result.recommendation == "demote"

    def test_score_respects_review_window(self, scorer_session, config_path):
        """Scans older than the review window should be excluded."""
        now = datetime.now()
        # Add old scans for a new portal (60 days ago — well outside 2-week window)
        for i in range(5):
            scorer_session.add(ScanORM(
                portal="old_portal",
                scan_type="full",
                started_at=now - timedelta(days=60 + i),
                companies_found=20,
                new_companies=10,
            ))
        scorer_session.commit()

        scorer = PortalScorer(scorer_session, config_path)
        result = scorer.score_portal("old_portal")
        # All scans are outside the window, so no data to score
        assert result.velocity_score == 0
        assert result.afternoon_delta_score == 0
        assert result.conversion_score == 0
        assert result.total == 0

    def test_velocity_threshold_low(self, config_path):
        """Velocity of exactly 3/day should score 1."""
        session = _make_session()
        now = datetime.now()
        # 2 scans, 1 day apart, total 3 companies found => velocity = 3/1 = 3
        session.add(ScanORM(
            portal="test_v",
            scan_type="full",
            started_at=now - timedelta(days=1),
            companies_found=1,
            new_companies=0,
        ))
        session.add(ScanORM(
            portal="test_v",
            scan_type="full",
            started_at=now,
            companies_found=2,
            new_companies=0,
        ))
        session.commit()

        scorer = PortalScorer(session, config_path)
        result = scorer.score_portal("test_v")
        assert result.velocity_score == 1
        session.close()

    def test_velocity_threshold_high(self, config_path):
        """Velocity of 8+/day should score 2."""
        session = _make_session()
        now = datetime.now()
        # 2 scans, 1 day apart, total 10 companies => velocity = 10/1 = 10
        session.add(ScanORM(
            portal="test_vh",
            scan_type="full",
            started_at=now - timedelta(days=1),
            companies_found=5,
            new_companies=0,
        ))
        session.add(ScanORM(
            portal="test_vh",
            scan_type="full",
            started_at=now,
            companies_found=5,
            new_companies=0,
        ))
        session.commit()

        scorer = PortalScorer(session, config_path)
        result = scorer.score_portal("test_vh")
        assert result.velocity_score == 2
        session.close()

    def test_afternoon_delta_medium(self, config_path):
        """PM/AM ratio of ~0.25 should score 1."""
        session = _make_session()
        now = datetime.now()
        # AM scan: 8 AM, companies_found=20
        session.add(ScanORM(
            portal="test_pm",
            scan_type="full",
            started_at=now.replace(hour=8, minute=0, second=0),
            companies_found=20,
            new_companies=0,
        ))
        # PM scan: 2 PM, new_companies=5 => ratio = 5/20 = 0.25
        session.add(ScanORM(
            portal="test_pm",
            scan_type="rescan",
            started_at=now.replace(hour=14, minute=0, second=0),
            companies_found=5,
            new_companies=5,
        ))
        session.commit()

        scorer = PortalScorer(session, config_path)
        result = scorer.score_portal("test_pm")
        assert result.afternoon_delta_score == 1
        session.close()

    def test_afternoon_delta_high(self, config_path):
        """PM/AM ratio of ~0.5 should score 2."""
        session = _make_session()
        now = datetime.now()
        # AM scan: 8 AM, companies_found=10
        session.add(ScanORM(
            portal="test_ph",
            scan_type="full",
            started_at=now.replace(hour=8, minute=0, second=0),
            companies_found=10,
            new_companies=0,
        ))
        # PM scan: 2 PM, new_companies=5 => ratio = 5/10 = 0.5
        session.add(ScanORM(
            portal="test_ph",
            scan_type="rescan",
            started_at=now.replace(hour=14, minute=0, second=0),
            companies_found=5,
            new_companies=5,
        ))
        session.commit()

        scorer = PortalScorer(session, config_path)
        result = scorer.score_portal("test_ph")
        assert result.afternoon_delta_score == 2
        session.close()

    def test_conversion_medium(self, config_path):
        """Conversion ratio of 0.2 should score 1."""
        session = _make_session()
        now = datetime.now()
        # total_found=10, total_new=2 => ratio = 0.2
        session.add(ScanORM(
            portal="test_cm",
            scan_type="full",
            started_at=now,
            companies_found=10,
            new_companies=2,
        ))
        session.commit()

        scorer = PortalScorer(session, config_path)
        result = scorer.score_portal("test_cm")
        assert result.conversion_score == 1
        session.close()

    def test_conversion_high(self, config_path):
        """Conversion ratio of 0.35 should score 2."""
        session = _make_session()
        now = datetime.now()
        # total_found=20, total_new=7 => ratio = 0.35
        session.add(ScanORM(
            portal="test_ch",
            scan_type="full",
            started_at=now,
            companies_found=20,
            new_companies=7,
        ))
        session.commit()

        scorer = PortalScorer(session, config_path)
        result = scorer.score_portal("test_ch")
        assert result.conversion_score == 2
        session.close()


class TestPromotionDemotion:
    def test_promotion_candidates(self, scorer_session, config_path):
        """Jobright should appear in promotion candidates."""
        scorer = PortalScorer(scorer_session, config_path)
        candidates = scorer.get_promotion_candidates()
        portal_names = [c.portal for c in candidates]
        assert "jobright" in portal_names

    def test_demotion_candidates(self, scorer_session, config_path):
        """Builtin should appear in demotion candidates."""
        scorer = PortalScorer(scorer_session, config_path)
        candidates = scorer.get_demotion_candidates()
        portal_names = [c.portal for c in candidates]
        assert "builtin" in portal_names

    def test_score_all_returns_all_portals(self, scorer_session, config_path):
        """score_all should return scores for all 3 portals in the fixture."""
        scorer = PortalScorer(scorer_session, config_path)
        scores = scorer.score_all()
        portal_names = sorted([s.portal for s in scores])
        assert portal_names == ["builtin", "jobright", "linkedin"]
        assert len(scores) == 3

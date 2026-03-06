"""Integration tests — A/B test variants flow through the send queue."""

import json
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.ab_testing import ABTestManager
from src.outreach.send_queue import SendQueueManager


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def ab_config_path():
    """Temporary file for A/B experiment config."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump({"experiments": {}}, f)
        return f.name


def _seed_company_and_outreach(session, name, fit_score=80.0):
    """Create a company + outreach record for testing."""
    company = CompanyORM(
        name=name,
        fit_score=fit_score,
        tier="Tier 1 - HIGH",
        is_disqualified=False,
    )
    session.add(company)
    session.flush()

    outreach = OutreachORM(
        company_id=company.id,
        company_name=name,
        contact_name=f"Contact at {name}",
        stage="Not Started",
        template_type="connection_request_a.j2",
        content="Hello, I noticed your work...",
        character_count=30,
    )
    session.add(outreach)
    session.flush()
    return company, outreach


class TestABQueueIntegration:
    def test_queue_without_ab_manager_backward_compat(self, session):
        """Queue without ab_manager works unchanged — ab_variant is None."""
        _seed_company_and_outreach(session, "Acme AI", fit_score=90.0)
        session.commit()

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue()

        assert len(queue) == 1
        assert queue[0]["ab_variant"] is None
        assert queue[0]["template_type"] == "connection_request_a.j2"

    def test_queue_with_ab_manager_assigns_variants(self, session, ab_config_path):
        """Queue with ab_manager assigns variants from the active experiment."""
        _seed_company_and_outreach(session, "Alpha AI", fit_score=90.0)
        _seed_company_and_outreach(session, "Beta AI", fit_score=85.0)
        session.commit()

        ab = ABTestManager(session, config_path=ab_config_path)
        ab.create_experiment(
            "template_test",
            variants=["variant_a", "variant_b"],
            allocation="round_robin",
        )

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue(ab_manager=ab)

        assert len(queue) == 2
        # Both items should have a non-None ab_variant
        for item in queue:
            assert item["ab_variant"] is not None
            assert item["ab_variant"] in ("variant_a", "variant_b")
            # template_type should be overwritten to the variant
            assert item["template_type"] == item["ab_variant"]

    def test_variant_comes_from_experiment_variant_list(self, session, ab_config_path):
        """Assigned variant is always one of the experiment's defined variants."""
        for i in range(5):
            _seed_company_and_outreach(session, f"Co_{i}", fit_score=80.0 + i)
        session.commit()

        variants = ["short_template", "long_template", "casual_template"]
        ab = ABTestManager(session, config_path=ab_config_path)
        ab.create_experiment("style_test", variants=variants, allocation="round_robin")

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue(ab_manager=ab)

        assert len(queue) == 5
        for item in queue:
            assert item["ab_variant"] in variants

    def test_no_active_experiment_ab_variant_stays_none(self, session, ab_config_path):
        """When no active experiment exists, ab_variant stays None."""
        _seed_company_and_outreach(session, "Gamma AI", fit_score=88.0)
        session.commit()

        ab = ABTestManager(session, config_path=ab_config_path)
        # No experiment created — config has empty experiments dict

        mgr = SendQueueManager(session)
        queue = mgr.generate_daily_queue(ab_manager=ab)

        assert len(queue) == 1
        assert queue[0]["ab_variant"] is None
        # template_type should remain unchanged
        assert queue[0]["template_type"] == "connection_request_a.j2"

    def test_ab_variant_key_present_in_all_cases(self, session, ab_config_path):
        """Queue items always contain the 'ab_variant' key regardless of manager."""
        _seed_company_and_outreach(session, "Delta AI", fit_score=92.0)
        session.commit()

        # Case 1: no ab_manager
        mgr = SendQueueManager(session)
        queue_no_ab = mgr.generate_daily_queue()
        assert "ab_variant" in queue_no_ab[0]

        # Case 2: with ab_manager but no active experiment
        ab = ABTestManager(session, config_path=ab_config_path)
        queue_no_exp = mgr.generate_daily_queue(ab_manager=ab)
        assert "ab_variant" in queue_no_exp[0]

        # Case 3: with ab_manager and active experiment
        ab.create_experiment("test_exp", variants=["v1", "v2"])
        queue_with_exp = mgr.generate_daily_queue(ab_manager=ab)
        assert "ab_variant" in queue_with_exp[0]
        assert queue_with_exp[0]["ab_variant"] in ("v1", "v2")

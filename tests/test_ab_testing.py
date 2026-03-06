from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, OutreachORM
from src.outreach.ab_testing import ABTestManager


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "ab_experiments.json"
    path.write_text(json.dumps({"experiments": {}}))
    return path


@pytest.fixture
def manager(db_session, config_path):
    return ABTestManager(db_session, config_path=config_path)


class TestCreateExperiment:
    def test_create_returns_experiment_info(self, manager):
        result = manager.create_experiment("test_exp", ["template_a", "template_b"])
        assert result["name"] == "test_exp"
        assert result["variants"] == ["template_a", "template_b"]
        assert "experiment_id" in result
        assert "created_at" in result

    def test_create_persists_to_config(self, manager, config_path):
        manager.create_experiment("test_exp", ["a", "b"])
        data = json.loads(config_path.read_text())
        assert "test_exp" in data["experiments"]


class TestRoundRobin:
    def test_round_robin_alternates_variants(self, manager):
        manager.create_experiment("rr_test", ["a", "b"], allocation="round_robin")
        results = []
        for i in range(6):
            variant = manager.assign_variant("rr_test", f"company_{i}")
            results.append(variant)
        assert results == ["a", "b", "a", "b", "a", "b"]


class TestRandomAllocation:
    def test_random_assigns_all_variants(self, manager):
        manager.create_experiment("rand_test", ["x", "y", "z"], allocation="random")
        seen = set()
        for i in range(100):
            variant = manager.assign_variant("rand_test", f"company_{i}")
            seen.add(variant)
        assert seen == {"x", "y", "z"}


class TestExperimentResults:
    def test_results_calculates_response_rate(self, db_session, manager):
        manager.create_experiment("rate_test", ["tmpl_a", "tmpl_b"])

        # Assign companies and track which variant they get
        a_companies = []
        b_companies = []
        for i in range(6):
            variant = manager.assign_variant("rate_test", f"co_{i}")
            if variant == "tmpl_a":
                a_companies.append(f"co_{i}")
            else:
                b_companies.append(f"co_{i}")

        # Create outreach records for tmpl_a: 3 sent (1 responded)
        for idx, company in enumerate(a_companies[:3]):
            stage = "Responded" if idx == 0 else "Sent"
            db_session.add(OutreachORM(
                company_name=company, template_type="tmpl_a", stage=stage
            ))
        # Create outreach records for tmpl_b: 2 sent (2 responded)
        for company in b_companies[:2]:
            db_session.add(OutreachORM(
                company_name=company, template_type="tmpl_b", stage="Responded"
            ))
        db_session.commit()

        results = manager.get_experiment_results("rate_test")
        variants = {v["template"]: v for v in results["variants"]}

        assert variants["tmpl_a"]["sent"] == 3
        assert variants["tmpl_a"]["responded"] == 1
        assert abs(variants["tmpl_a"]["response_rate"] - 33.33) < 0.1

        assert variants["tmpl_b"]["sent"] == 2
        assert variants["tmpl_b"]["responded"] == 2
        assert variants["tmpl_b"]["response_rate"] == 100.0

    def test_winner_is_highest_response_rate(self, db_session, manager):
        manager.create_experiment("winner_test", ["good", "bad"])

        manager.assign_variant("winner_test", "co_good")
        manager.assign_variant("winner_test", "co_bad")

        db_session.add(OutreachORM(
            company_name="co_good", template_type="good", stage="Responded"
        ))
        db_session.add(OutreachORM(
            company_name="co_bad", template_type="bad", stage="Sent"
        ))
        db_session.commit()

        results = manager.get_experiment_results("winner_test")
        assert results["winner"] == "good"

    def test_significance_requires_min_10_sends(self, db_session, manager):
        manager.create_experiment("sig_test", ["a", "b"])

        # Only 2 sends per variant — not significant
        for i in range(2):
            manager.assign_variant("sig_test", f"co_a_{i}")
            manager.assign_variant("sig_test", f"co_b_{i}")
            db_session.add(OutreachORM(
                company_name=f"co_a_{i}", template_type="a", stage="Responded"
            ))
            db_session.add(OutreachORM(
                company_name=f"co_b_{i}", template_type="b", stage="Sent"
            ))
        db_session.commit()

        results = manager.get_experiment_results("sig_test")
        assert results["is_significant"] is False


class TestListExperiments:
    def test_list_returns_active_experiments(self, manager):
        manager.create_experiment("exp_1", ["a", "b"])
        manager.create_experiment("exp_2", ["x", "y", "z"], allocation="random")

        experiments = manager.list_experiments()
        assert len(experiments) == 2
        names = {e["name"] for e in experiments}
        assert names == {"exp_1", "exp_2"}
        assert all(e["status"] == "active" for e in experiments)


class TestDuplicateAssignment:
    def test_duplicate_company_returns_same_variant(self, manager):
        manager.create_experiment("dup_test", ["a", "b"], allocation="round_robin")

        first = manager.assign_variant("dup_test", "same_company")
        second = manager.assign_variant("dup_test", "same_company")
        assert first == second


class TestExperimentNotFound:
    def test_assign_variant_raises_key_error(self, manager):
        with pytest.raises(KeyError, match="not found"):
            manager.assign_variant("nonexistent", "any_company")

    def test_get_results_raises_key_error(self, manager):
        with pytest.raises(KeyError, match="not found"):
            manager.get_experiment_results("nonexistent")

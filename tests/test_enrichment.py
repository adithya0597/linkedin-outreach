"""Tests for company data enrichment pipeline."""


from src.db.orm import CompanyORM
from src.pipeline.enrichment import CompanyEnricher


def _make_company(session, name, description="", hq_location="", employees=None,
                  funding_stage="Unknown", data_completeness=0.0, is_disqualified=False, **kwargs):
    c = CompanyORM(
        name=name, description=description, hq_location=hq_location,
        employees=employees, funding_stage=funding_stage,
        data_completeness=data_completeness, is_disqualified=is_disqualified,
        **kwargs,
    )
    session.add(c)
    session.flush()
    return c


def test_enrich_extracts_location(session):
    """enrich_from_description extracts location from 'headquartered in San Francisco, CA'."""
    c = _make_company(session, "LocCo", description="AI startup headquartered in San Francisco, CA")
    enricher = CompanyEnricher(session)
    changes = enricher.enrich_from_description(c)
    assert changes["hq_location"] == "San Francisco, CA"
    assert c.hq_location == "San Francisco, CA"


def test_enrich_extracts_employee_count(session):
    """enrich_from_description extracts employee count from 'team of 150'."""
    c = _make_company(session, "TeamCo", description="A growing team of 150 building AI tools")
    enricher = CompanyEnricher(session)
    changes = enricher.enrich_from_description(c)
    assert changes["employees"] == 150
    assert c.employees == 150


def test_enrich_extracts_funding_stage(session):
    """enrich_from_description extracts funding stage from 'Series B'."""
    c = _make_company(session, "FundCo", description="Recently closed Series B to expand AI platform")
    enricher = CompanyEnricher(session)
    changes = enricher.enrich_from_description(c)
    assert changes["funding_stage"] == "Series B"
    assert c.funding_stage == "Series B"


def test_enrich_skips_populated_fields(session):
    """enrich_from_description does not overwrite already-populated fields."""
    c = _make_company(
        session, "PopCo",
        description="headquartered in Austin, TX with team of 200 after Series A",
        hq_location="New York, NY",
        employees=50,
        funding_stage="Seed",
    )
    enricher = CompanyEnricher(session)
    changes = enricher.enrich_from_description(c)
    # All fields already populated, so no changes
    assert changes == {}
    assert c.hq_location == "New York, NY"
    assert c.employees == 50
    assert c.funding_stage == "Seed"


def test_compute_all_completeness(session):
    """compute_all_completeness updates data_completeness for all companies."""
    # Company with several fields filled
    _make_company(
        session, "FullCo",
        description="AI platform",
        hq_location="SF, CA",
        employees=100,
        funding_stage="Series A",
        h1b_status="Confirmed",
        role="AI Engineer",
        hiring_manager="Jane Doe",
        salary_range="$150k-$200k",
        website="https://fullco.ai",
    )
    # Skeleton company
    _make_company(session, "EmptyCo")

    enricher = CompanyEnricher(session)
    result = enricher.compute_all_completeness()

    assert result["updated"] == 2

    full = session.query(CompanyORM).filter_by(name="FullCo").one()
    empty = session.query(CompanyORM).filter_by(name="EmptyCo").one()
    assert full.data_completeness == 100.0
    assert empty.data_completeness < 50.0


def test_get_skeleton_records(session):
    """get_skeleton_records returns only companies below threshold, not disqualified."""
    _make_company(session, "LowCo", data_completeness=20.0)
    _make_company(session, "HighCo", data_completeness=80.0)
    _make_company(session, "DQCo", data_completeness=10.0, is_disqualified=True)

    enricher = CompanyEnricher(session)
    skeletons = enricher.get_skeleton_records(threshold=50)

    names = [c.name for c in skeletons]
    assert "LowCo" in names
    assert "HighCo" not in names
    assert "DQCo" not in names


def test_batch_enrich(session):
    """batch_enrich processes skeleton records and returns fields_filled counts."""
    _make_company(
        session, "EnrichMe",
        description="headquartered in Austin, TX with team of 75 after Series A",
        data_completeness=20.0,
    )
    _make_company(
        session, "NoData",
        description="",
        data_completeness=10.0,
    )

    enricher = CompanyEnricher(session)
    result = enricher.batch_enrich(threshold=50)

    assert result["enriched"] == 1
    assert result["skipped"] == 1
    assert result["fields_filled"]["hq_location"] == 1
    assert result["fields_filled"]["employees"] == 1
    assert result["fields_filled"]["funding_stage"] == 1
    assert len(result["errors"]) == 0


def test_enrich_empty_description(session):
    """enrich_from_description with empty description returns {} without crashing."""
    c = _make_company(session, "BlankCo", description="")
    enricher = CompanyEnricher(session)
    changes = enricher.enrich_from_description(c)
    assert changes == {}

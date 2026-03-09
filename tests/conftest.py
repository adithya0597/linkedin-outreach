"""Shared test fixtures."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.enums import SourcePortal
from src.db.orm import Base, CompanyORM
from src.models.job_posting import JobPosting
from src.scrapers.rate_limiter import RateLimiter

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> str:
    """Load a test fixture file as string."""
    return (FIXTURES_DIR / filename).read_text()


def load_json_fixture(filename: str):
    """Load a JSON test fixture."""
    return json.loads((FIXTURES_DIR / filename).read_text())


@pytest.fixture
def engine():
    """In-memory SQLite engine for testing."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    """Database session for testing."""
    session_factory = sessionmaker(bind=engine)
    sess = session_factory()
    yield sess
    sess.close()


@pytest.fixture
def sample_valid_company() -> CompanyORM:
    """LlamaIndex — should PASS validation."""
    return CompanyORM(
        name="LlamaIndex",
        description="Data indexing and retrieval framework for RAG and LLM applications",
        hq_location="San Francisco, CA",
        employees=40,
        employees_range="30-50",
        funding_stage="Series A",
        funding_amount="Series A — $19M",
        is_ai_native=True,
        ai_product_description="RAG framework for LLM applications",
        tier="Tier 1 - HIGH",
        source_portal="Manual",
        h1b_status="Confirmed",
        h1b_details="Frog Hire: H1B+PERM+E-Verify",
        role="AI Engineer",
        why_fit="DIRECT match — Graph RAG + Neo4j + vector store work IS their product domain",
    )


@pytest.fixture
def sample_failing_company() -> CompanyORM:
    """Harvey AI — should FAIL validation (Series F)."""
    return CompanyORM(
        name="Harvey AI",
        description="Legal AI assistant for law firms — NLP + document understanding",
        hq_location="San Francisco, CA",
        employees=400,
        employees_range="300-500",
        funding_stage="Series F",
        funding_amount="Series F — $160M at $8B valuation",
        is_ai_native=True,
        tier="Tier 2 - STRONG",
        source_portal="Manual",
        h1b_status="Unknown",
        role="AI Engineer",
    )


@pytest.fixture
def sample_borderline_company() -> CompanyORM:
    """Acme AI — borderline (Series D but strong fit)."""
    return CompanyORM(
        name="Acme AI",
        description="AI-powered developer tools that automate programming tasks",
        hq_location="San Francisco, CA",
        employees=200,
        employees_range="100-300",
        funding_stage="Series D",
        funding_amount="Series D — $500M",
        is_ai_native=True,
        tier="Tier 2 - STRONG",
        source_portal="Manual",
        h1b_status="Confirmed",
        role="AI Engineer",
        why_fit="Code translation + AST parsing + compiler validation work maps to their core product",
    )


@pytest.fixture
def sample_skeleton_company() -> CompanyORM:
    """Skeleton entry with minimal data."""
    return CompanyORM(
        name="10a Labs",
        description="",
        hq_location="",
        employees=None,
        funding_stage="Unknown",
        source_portal="Hiring Cafe",
        tier="Tier 5 - RESCAN",
        data_completeness=20.0,
    )


@pytest.fixture
def sample_tier3_company() -> CompanyORM:
    """Company from Tier 3 portal — H1B auto-pass."""
    return CompanyORM(
        name="Floot",
        description="No-code AI app builder",
        hq_location="San Francisco, CA",
        employees=5,
        employees_range="<10",
        funding_stage="Seed",
        funding_amount="YC S25",
        is_ai_native=True,
        tier="Tier 3 - DECENT",
        source_portal="Work at a Startup (YC)",
        h1b_status="Unknown",
        role="Founding Full-Stack Engineer",
    )


@pytest.fixture
def fast_rate_limiter():
    """Rate limiter with no throttling for tests."""
    return RateLimiter(default_tokens_per_second=1000.0)


@pytest.fixture
def sample_job_posting():
    """Standard JobPosting for testing."""
    return JobPosting(
        company_name="TestCo AI",
        title="AI Engineer",
        url="https://example.com/jobs/ai-engineer",
        source_portal=SourcePortal.STARTUP_JOBS,
        location="San Francisco, CA",
        work_model="remote",
        salary_range="$150k - $200k",
        description="Build AI systems",
        tech_stack=["Python", "LangChain", "FastAPI"],
        is_active=True,
    )


@pytest.fixture
def sample_job_postings():
    """List of sample JobPostings across different portals."""
    return [
        JobPosting(
            company_name="Acme AI",
            title="AI Engineer",
            url="https://startup.jobs/1",
            source_portal=SourcePortal.STARTUP_JOBS,
            location="SF, CA",
        ),
        JobPosting(
            company_name="SmartAI",
            title="LLM Engineer",
            url="https://jobright.ai/1",
            source_portal=SourcePortal.JOBRIGHT,
            location="NY, NY",
        ),
        JobPosting(
            company_name="GraphCo",
            title="ML Engineer",
            url="https://hiring.cafe/1",
            source_portal=SourcePortal.HIRING_CAFE,
            location="Remote",
        ),
    ]


@pytest.fixture
def mock_registry():
    """Registry with mock scrapers that return fixture data."""
    from src.scrapers.registry import PortalRegistry

    registry = PortalRegistry()

    for portal_name, is_healthy in [
        ("startup_jobs", True),
        ("jobright", True),
        ("hiring_cafe", True),
        ("linkedin", True),
        ("yc", True),
        ("builtin", False),
        ("wttj", False),
    ]:
        mock = MagicMock()
        mock.name = portal_name
        mock.is_healthy.return_value = is_healthy
        mock.search = AsyncMock(
            return_value=[
                JobPosting(
                    company_name=f"Test-{portal_name}",
                    title="AI Engineer",
                    url=f"https://{portal_name}.example/1",
                    source_portal=SourcePortal.STARTUP_JOBS,
                )
            ]
            if is_healthy
            else []
        )
        registry.register(portal_name, mock)

    return registry

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class CompanyORM(Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index('ix_company_disqualified_stage', 'is_disqualified', 'stage'),
        Index('ix_company_source_tier', 'source_portal', 'tier'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, default="")
    hq_location = Column(String(255), default="")
    employees = Column(Integer, nullable=True)
    employees_range = Column(String(50), default="")
    funding_stage = Column(String(50), default="Unknown")
    funding_amount = Column(String(100), default="")
    total_raised = Column(String(100), default="")
    valuation = Column(String(100), default="")
    founded_year = Column(Integer, nullable=True)
    website = Column(String(500), default="")
    careers_url = Column(String(500), default="")
    linkedin_url = Column(String(500), default="")
    is_ai_native = Column(Boolean, default=False)
    ai_product_description = Column(Text, default="")
    tier = Column(String(50), default="Tier 5 - RESCAN")
    source_portal = Column(String(100), default="Manual")
    h1b_status = Column(String(50), default="Unknown")
    h1b_source = Column(String(100), default="")
    h1b_details = Column(Text, default="")
    fit_score = Column(Float, nullable=True)
    score_h1b = Column(Float, default=0.0)
    score_criteria = Column(Float, default=0.0)
    score_tech_overlap = Column(Float, default=0.0)
    score_salary = Column(Float, default=0.0)
    score_profile_jd = Column(Float, default=0.0)
    score_domain_company = Column(Float, default=0.0)
    score_domain_match = Column(Float, default=0.0)
    stage = Column(String(50), default="To apply")
    validation_result = Column(String(20), nullable=True)
    validation_notes = Column(Text, default="")
    differentiators = Column(Text, default="")  # pipe-separated (|)
    role = Column(String(255), default="")
    role_url = Column(String(500), default="")
    salary_range = Column(String(100), default="")
    notes = Column(Text, default="")
    hiring_manager = Column(String(255), default="")
    hiring_manager_linkedin = Column(String(500), default="")
    why_fit = Column(Text, default="")
    best_stats = Column(Text, default="")
    action = Column(Text, default="")
    is_disqualified = Column(Boolean, default=False)
    disqualification_reason = Column(Text, default="")
    needs_review = Column(Boolean, default=False)
    data_completeness = Column(Float, default=0.0)
    ats_platform = Column(String(50), default="")
    ats_slug = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_synced_at = Column(DateTime, nullable=True)

    # Relationships
    contacts = relationship("ContactORM", back_populates="company")
    job_postings = relationship("JobPostingORM", back_populates="company")
    h1b_records = relationship("H1BORM", back_populates="company")
    outreach_records = relationship("OutreachORM", back_populates="company")
    warmup_actions = relationship("WarmUpActionORM", back_populates="company")
    warmup_sequences = relationship("WarmUpSequenceORM", back_populates="company")


class ContactORM(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index('ix_contact_company_score', 'company_id', 'contact_score'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    title = Column(String(255), default="")
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    company_name = Column(String(255), default="")
    linkedin_url = Column(String(500), default="")
    linkedin_degree = Column(Integer, nullable=True)
    mutual_connections = Column(Text, default="")  # comma-separated
    followers = Column(Integer, nullable=True)
    location = Column(String(255), default="")
    email = Column(String(255), default="")
    is_open_profile = Column(Boolean, default=False)
    is_recruiter = Column(Boolean, default=False)
    recent_posts = Column(Text, default="")
    communication_style = Column(String(50), default="")
    contact_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    company = relationship("CompanyORM", back_populates="contacts")


class JobPostingORM(Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        Index('ix_posting_portal_company', 'source_portal', 'company_id'),
        UniqueConstraint("url", name="uq_postings_url"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    company_name = Column(String(255), default="")
    title = Column(String(255), default="")
    url = Column(String(500), default="")
    source_portal = Column(String(100), default="Manual")
    location = Column(String(255), default="")
    work_model = Column(String(50), default="")
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    salary_range = Column(String(100), default="")
    description = Column(Text, default="")
    requirements = Column(Text, default="")  # JSON list
    preferred = Column(Text, default="")  # JSON list
    tech_stack = Column(Text, default="")  # JSON list
    posted_date = Column(DateTime, nullable=True)
    discovered_date = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    h1b_mentioned = Column(Boolean, default=False)
    h1b_text = Column(String(500), default="")
    is_easy_apply = Column(Boolean, default=False)
    is_top_applicant = Column(Boolean, default=False)
    embedding_blob = Column(Text, nullable=True)  # JSON float list

    company = relationship("CompanyORM", back_populates="job_postings")


class H1BORM(Base):
    __tablename__ = "h1b_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    company_name = Column(String(255), default="")
    status = Column(String(50), default="Unknown")
    source = Column(String(100), default="")
    lca_count = Column(Integer, nullable=True)
    lca_fiscal_year = Column(String(10), default="")
    has_perm = Column(Boolean, default=False)
    has_everify = Column(Boolean, default=False)
    employee_count_on_source = Column(String(50), default="")
    ranking = Column(String(50), default="")
    approval_rate = Column(Float, nullable=True)
    raw_data = Column(Text, default="")
    verified_at = Column(DateTime, default=datetime.now)

    company = relationship("CompanyORM", back_populates="h1b_records")


class ScanORM(Base):
    __tablename__ = "scans"
    __table_args__ = (
        Index('ix_scan_portal_started', 'portal', 'started_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    portal = Column(String(100), default="Manual")
    scan_type = Column(String(20), default="full")
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    companies_found = Column(Integer, default=0)
    new_companies = Column(Integer, default=0)
    errors = Column(Text, default="")
    is_healthy = Column(Boolean, default=True)
    duration_seconds = Column(Float, default=0.0)


class OutreachORM(Base):
    __tablename__ = "outreach"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    company_name = Column(String(255), default="")
    contact_name = Column(String(255), default="")
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    template_type = Column(String(50), default="")
    template_version = Column(String(10), default="")
    content = Column(Text, default="")
    character_count = Column(Integer, default=0)
    char_limit = Column(Integer, default=300)
    is_within_limit = Column(Boolean, default=True)
    stage = Column(String(50), default="Not Started")
    sequence_step = Column(String(50), default="")
    sent_at = Column(DateTime, nullable=True)
    response_at = Column(DateTime, nullable=True)
    response_text = Column(Text, default="")
    audit_trail = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)

    company = relationship("CompanyORM", back_populates="outreach_records")


class WarmUpActionORM(Base):
    __tablename__ = "warmup_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    contact_name = Column(String(255), nullable=False)
    action_type = Column(String(50), nullable=False)  # WarmUpAction enum value
    performed_at = Column(DateTime, default=datetime.now)
    notes = Column(Text, default="")

    company = relationship("CompanyORM", back_populates="warmup_actions")


class WarmUpSequenceORM(Base):
    __tablename__ = "warmup_sequences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    contact_name = Column(String(255), nullable=False)
    state = Column(String(50), nullable=False, default="PENDING")  # WarmUpState enum value
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    company = relationship("CompanyORM", back_populates="warmup_sequences")

"""Initial 6-table schema.

Revision ID: 001
Revises:
Create Date: 2026-03-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- companies (no FK deps) ---
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("hq_location", sa.String(255), server_default=""),
        sa.Column("employees", sa.Integer, nullable=True),
        sa.Column("employees_range", sa.String(50), server_default=""),
        sa.Column("funding_stage", sa.String(50), server_default="Unknown"),
        sa.Column("funding_amount", sa.String(100), server_default=""),
        sa.Column("total_raised", sa.String(100), server_default=""),
        sa.Column("valuation", sa.String(100), server_default=""),
        sa.Column("founded_year", sa.Integer, nullable=True),
        sa.Column("website", sa.String(500), server_default=""),
        sa.Column("careers_url", sa.String(500), server_default=""),
        sa.Column("linkedin_url", sa.String(500), server_default=""),
        sa.Column("is_ai_native", sa.Boolean, server_default="0"),
        sa.Column("ai_product_description", sa.Text, server_default=""),
        sa.Column("tier", sa.String(50), server_default="Tier 5 - RESCAN"),
        sa.Column("source_portal", sa.String(100), server_default="Manual"),
        sa.Column("h1b_status", sa.String(50), server_default="Unknown"),
        sa.Column("h1b_source", sa.String(100), server_default=""),
        sa.Column("h1b_details", sa.Text, server_default=""),
        sa.Column("fit_score", sa.Float, nullable=True),
        sa.Column("score_h1b", sa.Float, server_default="0.0"),
        sa.Column("score_criteria", sa.Float, server_default="0.0"),
        sa.Column("score_tech_overlap", sa.Float, server_default="0.0"),
        sa.Column("score_salary", sa.Float, server_default="0.0"),
        sa.Column("score_profile_jd", sa.Float, server_default="0.0"),
        sa.Column("score_domain_company", sa.Float, server_default="0.0"),
        sa.Column("stage", sa.String(50), server_default="To apply"),
        sa.Column("validation_result", sa.String(20), nullable=True),
        sa.Column("validation_notes", sa.Text, server_default=""),
        sa.Column("differentiators", sa.Text, server_default=""),
        sa.Column("role", sa.String(255), server_default=""),
        sa.Column("role_url", sa.String(500), server_default=""),
        sa.Column("salary_range", sa.String(100), server_default=""),
        sa.Column("notes", sa.Text, server_default=""),
        sa.Column("hiring_manager", sa.String(255), server_default=""),
        sa.Column("hiring_manager_linkedin", sa.String(500), server_default=""),
        sa.Column("why_fit", sa.Text, server_default=""),
        sa.Column("best_stats", sa.Text, server_default=""),
        sa.Column("action", sa.Text, server_default=""),
        sa.Column("is_disqualified", sa.Boolean, server_default="0"),
        sa.Column("disqualification_reason", sa.Text, server_default=""),
        sa.Column("needs_review", sa.Boolean, server_default="0"),
        sa.Column("data_completeness", sa.Float, server_default="0.0"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_index("ix_companies_name", "companies", ["name"])

    # --- contacts (FK -> companies) ---
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), server_default=""),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("company_name", sa.String(255), server_default=""),
        sa.Column("linkedin_url", sa.String(500), server_default=""),
        sa.Column("linkedin_degree", sa.Integer, nullable=True),
        sa.Column("mutual_connections", sa.Text, server_default=""),
        sa.Column("followers", sa.Integer, nullable=True),
        sa.Column("location", sa.String(255), server_default=""),
        sa.Column("is_open_profile", sa.Boolean, server_default="0"),
        sa.Column("is_recruiter", sa.Boolean, server_default="0"),
        sa.Column("recent_posts", sa.Text, server_default=""),
        sa.Column("communication_style", sa.String(50), server_default=""),
        sa.Column("contact_score", sa.Float, server_default="0.0"),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    # --- job_postings (FK -> companies) ---
    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("company_name", sa.String(255), server_default=""),
        sa.Column("title", sa.String(255), server_default=""),
        sa.Column("url", sa.String(500), server_default=""),
        sa.Column("source_portal", sa.String(100), server_default="Manual"),
        sa.Column("location", sa.String(255), server_default=""),
        sa.Column("work_model", sa.String(50), server_default=""),
        sa.Column("salary_min", sa.Integer, nullable=True),
        sa.Column("salary_max", sa.Integer, nullable=True),
        sa.Column("salary_range", sa.String(100), server_default=""),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("requirements", sa.Text, server_default=""),
        sa.Column("preferred", sa.Text, server_default=""),
        sa.Column("tech_stack", sa.Text, server_default=""),
        sa.Column("posted_date", sa.DateTime, nullable=True),
        sa.Column("discovered_date", sa.DateTime),
        sa.Column("is_active", sa.Boolean, server_default="1"),
        sa.Column("h1b_mentioned", sa.Boolean, server_default="0"),
        sa.Column("h1b_text", sa.String(500), server_default=""),
        sa.Column("is_easy_apply", sa.Boolean, server_default="0"),
        sa.Column("is_top_applicant", sa.Boolean, server_default="0"),
        sa.Column("embedding_blob", sa.Text, nullable=True),
    )

    # --- h1b_records (FK -> companies) ---
    op.create_table(
        "h1b_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("company_name", sa.String(255), server_default=""),
        sa.Column("status", sa.String(50), server_default="Unknown"),
        sa.Column("source", sa.String(100), server_default=""),
        sa.Column("lca_count", sa.Integer, nullable=True),
        sa.Column("lca_fiscal_year", sa.String(10), server_default=""),
        sa.Column("has_perm", sa.Boolean, server_default="0"),
        sa.Column("has_everify", sa.Boolean, server_default="0"),
        sa.Column("employee_count_on_source", sa.String(50), server_default=""),
        sa.Column("ranking", sa.String(50), server_default=""),
        sa.Column("approval_rate", sa.Float, nullable=True),
        sa.Column("raw_data", sa.Text, server_default=""),
        sa.Column("verified_at", sa.DateTime),
    )

    # --- scans (no FK deps) ---
    op.create_table(
        "scans",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("portal", sa.String(100), server_default="Manual"),
        sa.Column("scan_type", sa.String(20), server_default="full"),
        sa.Column("started_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("companies_found", sa.Integer, server_default="0"),
        sa.Column("new_companies", sa.Integer, server_default="0"),
        sa.Column("errors", sa.Text, server_default=""),
        sa.Column("is_healthy", sa.Boolean, server_default="1"),
        sa.Column("duration_seconds", sa.Float, server_default="0.0"),
    )

    # --- outreach (FK -> companies, contacts) ---
    op.create_table(
        "outreach",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("company_name", sa.String(255), server_default=""),
        sa.Column("contact_name", sa.String(255), server_default=""),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("template_type", sa.String(50), server_default=""),
        sa.Column("template_version", sa.String(10), server_default=""),
        sa.Column("content", sa.Text, server_default=""),
        sa.Column("character_count", sa.Integer, server_default="0"),
        sa.Column("char_limit", sa.Integer, server_default="300"),
        sa.Column("is_within_limit", sa.Boolean, server_default="1"),
        sa.Column("stage", sa.String(50), server_default="Not Started"),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("response_at", sa.DateTime, nullable=True),
        sa.Column("response_text", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime),
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("outreach")
    op.drop_table("scans")
    op.drop_table("h1b_records")
    op.drop_table("job_postings")
    op.drop_table("contacts")
    op.drop_index("ix_companies_name", table_name="companies")
    op.drop_table("companies")

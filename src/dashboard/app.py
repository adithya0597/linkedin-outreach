"""LinkedIn Outreach Dashboard — Streamlit App.

Launch: streamlit run src/dashboard/app.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure project root is on sys.path so src.db imports work
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import func

from src.dashboard.themes import get_theme
from src.db.database import get_engine, init_db
from src.db.orm import CompanyORM, ContactORM, H1BORM, OutreachORM, ScanORM

theme = get_theme(os.getenv("DASHBOARD_THEME", "light"))

# ---------------------------------------------------------------------------
# Config & Session Setup
# ---------------------------------------------------------------------------

DB_PATH = PROJECT_ROOT / "data" / "outreach.db"

st.set_page_config(
    page_title="LinkedIn Outreach Dashboard",
    page_icon="briefcase",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def _engine():
    engine = get_engine(str(DB_PATH))
    init_db(engine)
    return engine


def _session():
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=_engine())()


# ---------------------------------------------------------------------------
# Helper: load tables as DataFrames
# ---------------------------------------------------------------------------


@st.cache_data(ttl=30)
def load_companies() -> pd.DataFrame:
    session = _session()
    try:
        rows = session.query(CompanyORM).all()
        if not rows:
            return pd.DataFrame()
        data = [
            {c.key: getattr(r, c.key) for c in CompanyORM.__table__.columns}
            for r in rows
        ]
        return pd.DataFrame(data)
    finally:
        session.close()


@st.cache_data(ttl=30)
def load_scans() -> pd.DataFrame:
    session = _session()
    try:
        rows = session.query(ScanORM).all()
        if not rows:
            return pd.DataFrame()
        data = [
            {c.key: getattr(r, c.key) for c in ScanORM.__table__.columns}
            for r in rows
        ]
        return pd.DataFrame(data)
    finally:
        session.close()


@st.cache_data(ttl=30)
def load_outreach() -> pd.DataFrame:
    session = _session()
    try:
        rows = session.query(OutreachORM).all()
        if not rows:
            return pd.DataFrame()
        data = [
            {c.key: getattr(r, c.key) for c in OutreachORM.__table__.columns}
            for r in rows
        ]
        return pd.DataFrame(data)
    finally:
        session.close()


@st.cache_data(ttl=30)
def load_h1b() -> pd.DataFrame:
    session = _session()
    try:
        rows = session.query(H1BORM).all()
        if not rows:
            return pd.DataFrame()
        data = [
            {c.key: getattr(r, c.key) for c in H1BORM.__table__.columns}
            for r in rows
        ]
        return pd.DataFrame(data)
    finally:
        session.close()


@st.cache_data(ttl=30)
def load_contacts() -> pd.DataFrame:
    session = _session()
    try:
        rows = session.query(ContactORM).all()
        if not rows:
            return pd.DataFrame()
        data = [
            {c.key: getattr(r, c.key) for c in ContactORM.__table__.columns}
            for r in rows
        ]
        return pd.DataFrame(data)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Sidebar Navigation
# ---------------------------------------------------------------------------

PAGES = [
    "Pipeline Overview",
    "Company Explorer",
    "Scan History",
    "Outreach Tracker",
    "H1B Status",
    "Data Quality",
    "Contacts",
    "A/B Testing",
    "Follow-Up Manager",
]

st.sidebar.title("LinkedIn Outreach")
st.sidebar.markdown("---")
page = st.sidebar.radio("Navigation", PAGES, index=0)
st.sidebar.markdown("---")
if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()


# ===================================================================
# PAGE 1 — Pipeline Overview
# ===================================================================

def page_pipeline_overview():
    st.title("Pipeline Overview")
    df = load_companies()

    if df.empty:
        st.info("No companies in the database yet. Run a portal scan to populate data.")
        return

    # --- KPI cards ---
    total = len(df)
    qualified = len(df[df["is_disqualified"] == False])  # noqa: E712
    disqualified = len(df[df["is_disqualified"] == True])  # noqa: E712
    applied = len(df[df["stage"] == "Applied"])
    avg_completeness = df["data_completeness"].mean() if "data_completeness" in df.columns else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Companies", total)
    k2.metric("Qualified", qualified)
    k3.metric("Disqualified", disqualified)
    k4.metric("Applied", applied)
    k5.metric("Avg Completeness", f"{avg_completeness:.0%}")

    st.markdown("---")

    col_left, col_right = st.columns(2)

    # --- Tier breakdown bar chart ---
    with col_left:
        st.subheader("Tier Breakdown")
        tier_counts = df["tier"].value_counts().sort_index()
        if not tier_counts.empty:
            st.bar_chart(tier_counts)
        else:
            st.caption("No tier data available.")

    # --- H1B status distribution ---
    with col_right:
        st.subheader("H1B Status Distribution")
        h1b_counts = df["h1b_status"].value_counts()
        if not h1b_counts.empty:
            # Use a horizontal bar chart as a clean alternative to pie
            chart_df = h1b_counts.reset_index()
            chart_df.columns = ["Status", "Count"]
            st.bar_chart(chart_df.set_index("Status"))
        else:
            st.caption("No H1B data available.")

    # --- Today's Actions ---
    st.markdown("---")
    st.subheader("Today's Actions")

    actions_df = df[df["needs_review"] == True]  # noqa: E712
    if not actions_df.empty:
        st.dataframe(
            actions_df[["name", "tier", "h1b_status", "stage", "notes"]].reset_index(drop=True),
            use_container_width=True,
        )
    else:
        # Show companies that are qualified but not yet applied
        pending = df[(df["is_disqualified"] == False) & (df["stage"] == "To apply")]  # noqa: E712
        if not pending.empty:
            st.caption(f"{len(pending)} companies ready to apply to:")
            st.dataframe(
                pending[["name", "tier", "h1b_status", "fit_score", "hiring_manager"]]
                .sort_values("fit_score", ascending=False)
                .head(10)
                .reset_index(drop=True),
                use_container_width=True,
            )
        else:
            st.success("All caught up — no pending actions.")


# ===================================================================
# PAGE 2 — Company Explorer
# ===================================================================

def page_company_explorer():
    st.title("Company Explorer")
    df = load_companies()

    if df.empty:
        st.info("No companies in the database yet.")
        return

    # --- Filters ---
    with st.expander("Filters", expanded=True):
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)

        with fc1:
            search = st.text_input("Search by name", "")
        with fc2:
            tiers = ["All"] + sorted(df["tier"].dropna().unique().tolist())
            sel_tier = st.selectbox("Tier", tiers)
        with fc3:
            h1b_opts = ["All"] + sorted(df["h1b_status"].dropna().unique().tolist())
            sel_h1b = st.selectbox("H1B Status", h1b_opts)
        with fc4:
            funding_opts = ["All"] + sorted(df["funding_stage"].dropna().unique().tolist())
            sel_funding = st.selectbox("Funding Stage", funding_opts)
        with fc5:
            val_opts = ["All"] + sorted(df["validation_result"].dropna().unique().tolist())
            sel_val = st.selectbox("Validation", val_opts)

    filtered = df.copy()
    if search:
        filtered = filtered[filtered["name"].str.contains(search, case=False, na=False)]
    if sel_tier != "All":
        filtered = filtered[filtered["tier"] == sel_tier]
    if sel_h1b != "All":
        filtered = filtered[filtered["h1b_status"] == sel_h1b]
    if sel_funding != "All":
        filtered = filtered[filtered["funding_stage"] == sel_funding]
    if sel_val != "All":
        filtered = filtered[filtered["validation_result"] == sel_val]

    st.caption(f"Showing {len(filtered)} of {len(df)} companies")

    # --- Color-coded table ---
    display_cols = [
        "name", "tier", "h1b_status", "fit_score", "stage",
        "validation_result", "funding_stage", "employees", "hiring_manager",
    ]
    display_cols = [c for c in display_cols if c in filtered.columns]
    display_df = filtered[display_cols].reset_index(drop=True)

    def _color_validation(val):
        if val == "PASS":
            return f"background-color: {theme.validation_pass}; color: white"
        elif val == "FAIL":
            return f"background-color: {theme.validation_fail}; color: white"
        elif val == "BORDERLINE":
            return "background-color: #8b7d20; color: white"
        return ""

    styled = display_df.style.map(
        _color_validation, subset=["validation_result"] if "validation_result" in display_df.columns else []
    )
    st.dataframe(styled, use_container_width=True, height=450)

    # --- Drill-down ---
    st.markdown("---")
    st.subheader("Company Detail")
    company_names = sorted(filtered["name"].dropna().unique().tolist())
    if company_names:
        selected = st.selectbox("Select a company", company_names)
        row = df[df["name"] == selected].iloc[0]

        d1, d2, d3 = st.columns(3)
        with d1:
            st.markdown(f"**Tier:** {row.get('tier', 'N/A')}")
            st.markdown(f"**H1B:** {row.get('h1b_status', 'Unknown')}")
            st.markdown(f"**Funding:** {row.get('funding_stage', 'Unknown')} {row.get('funding_amount', '')}")
            st.markdown(f"**Employees:** {row.get('employees', 'N/A')}")
            st.markdown(f"**Founded:** {row.get('founded_year', 'N/A')}")
        with d2:
            st.markdown(f"**Fit Score:** {row.get('fit_score', 'N/A')}")
            st.markdown(f"**Stage:** {row.get('stage', 'N/A')}")
            st.markdown(f"**Validation:** {row.get('validation_result', 'N/A')}")
            st.markdown(f"**Role:** {row.get('role', 'N/A')}")
            st.markdown(f"**Salary:** {row.get('salary_range', 'N/A')}")
        with d3:
            st.markdown(f"**Hiring Manager:** {row.get('hiring_manager', 'N/A')}")
            st.markdown(f"**Data Completeness:** {row.get('data_completeness', 0):.0%}")
            website = row.get("website", "")
            if website:
                st.markdown(f"**Website:** [{website}]({website})")
            careers = row.get("careers_url", "")
            if careers:
                st.markdown(f"**Careers:** [{careers}]({careers})")
            li = row.get("linkedin_url", "")
            if li:
                st.markdown(f"**LinkedIn:** [{li}]({li})")

        # Score breakdown
        score_cols = [c for c in df.columns if c.startswith("score_")]
        if score_cols:
            st.markdown("**Score Breakdown:**")
            scores = {c.replace("score_", "").replace("_", " ").title(): row.get(c, 0) for c in score_cols}
            score_df = pd.DataFrame(list(scores.items()), columns=["Component", "Score"])
            st.bar_chart(score_df.set_index("Component"))

        # Notes
        notes = row.get("notes", "")
        val_notes = row.get("validation_notes", "")
        why_fit = row.get("why_fit", "")
        if notes:
            st.markdown(f"**Notes:** {notes}")
        if val_notes:
            st.markdown(f"**Validation Notes:** {val_notes}")
        if why_fit:
            st.markdown(f"**Why Fit:** {why_fit}")
    else:
        st.caption("No companies match the current filters.")


# ===================================================================
# PAGE 3 — Scan History
# ===================================================================

def page_scan_history():
    st.title("Scan History")
    df = load_scans()

    if df.empty:
        st.info("No scan records yet. Run a portal scan to see history.")
        return

    # --- Scan table ---
    st.subheader("Scan Records")
    display_cols = [
        "id", "portal", "scan_type", "started_at", "completed_at",
        "companies_found", "new_companies", "duration_seconds", "is_healthy",
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[display_cols].sort_values("started_at", ascending=False).reset_index(drop=True),
        use_container_width=True,
    )

    st.markdown("---")
    col_left, col_right = st.columns(2)

    # --- Portal performance ---
    with col_left:
        st.subheader("Portal Performance")
        portal_stats = (
            df.groupby("portal")
            .agg(
                scans=("id", "count"),
                total_found=("companies_found", "sum"),
                total_new=("new_companies", "sum"),
                avg_duration=("duration_seconds", "mean"),
            )
            .sort_values("total_new", ascending=False)
        )
        st.dataframe(portal_stats, use_container_width=True)

    # --- Companies found per portal ---
    with col_right:
        st.subheader("Companies Found by Portal")
        if not portal_stats.empty:
            st.bar_chart(portal_stats["total_found"])

    # --- Health status ---
    st.markdown("---")
    st.subheader("Portal Health")
    latest_scans = df.sort_values("started_at").groupby("portal").last().reset_index()
    health_cols = ["portal", "started_at", "is_healthy", "errors"]
    health_cols = [c for c in health_cols if c in latest_scans.columns]

    for _, row in latest_scans[health_cols].iterrows():
        healthy = row.get("is_healthy", True)
        icon = "green" if healthy else "red"
        portal_name = row.get("portal", "Unknown")
        last_scan = row.get("started_at", "N/A")
        errors = row.get("errors", "")

        with st.container():
            c1, c2, c3 = st.columns([2, 3, 5])
            c1.markdown(f":{icon}_circle: **{portal_name}**")
            c2.caption(f"Last scan: {last_scan}")
            if errors:
                c3.caption(f"Errors: {errors}")


# ===================================================================
# PAGE 4 — Outreach Tracker
# ===================================================================

OUTREACH_STAGES = [
    "Not Started",
    "Sent",
    "No Answer",
    "Responded",
    "Interview",
    "Declined",
    "Offer",
    "Rejected",
]

DATA_QUALITY_FIELDS = [
    "description",
    "tier",
    "fit_score",
    "h1b_status",
    "stage",
    "salary_range",
    "hiring_manager",
    "role_url",
]


def page_outreach_tracker():
    st.title("Outreach Tracker")
    df = load_outreach()
    companies_df = load_companies()

    if df.empty and companies_df.empty:
        st.info("No outreach records yet.")
        return

    # --- Funnel from outreach records ---
    st.subheader("Pipeline Funnel")

    if not df.empty:
        stage_counts = df["stage"].value_counts()
        funnel_data = []
        for stage in OUTREACH_STAGES:
            funnel_data.append({"Stage": stage, "Count": stage_counts.get(stage, 0)})
        funnel_df = pd.DataFrame(funnel_data)
        st.bar_chart(funnel_df.set_index("Stage"))
    elif not companies_df.empty:
        # Fall back to company stages
        stage_map = {
            "To apply": "Not Started",
            "Applied": "Pre-Engaged",
            "No Answer": "Connected",
            "Offer": "Interview",
            "Rejected": "Not Started",
        }
        companies_df["outreach_stage"] = companies_df["stage"].map(stage_map).fillna("Not Started")
        stage_counts = companies_df["outreach_stage"].value_counts()
        funnel_data = []
        for stage in OUTREACH_STAGES:
            funnel_data.append({"Stage": stage, "Count": stage_counts.get(stage, 0)})
        funnel_df = pd.DataFrame(funnel_data)
        st.bar_chart(funnel_df.set_index("Stage"))

    st.markdown("---")

    # --- Active outreach sequences ---
    st.subheader("Active Outreach Sequences")

    if not df.empty:
        active = df[~df["stage"].isin(["Not Started"])].copy()
        if not active.empty:
            now = datetime.now()
            active["sent_at_dt"] = pd.to_datetime(active["sent_at"], errors="coerce")
            active["days_since"] = active["sent_at_dt"].apply(
                lambda x: (now - x).days if pd.notna(x) else None
            )
            display_cols = [
                "company_name", "contact_name", "stage", "template_type",
                "sent_at", "days_since",
            ]
            display_cols = [c for c in display_cols if c in active.columns]
            st.dataframe(
                active[display_cols].sort_values("sent_at", ascending=False).reset_index(drop=True),
                use_container_width=True,
            )
        else:
            st.caption("No active outreach sequences.")
    else:
        st.caption("No outreach records in the database.")

    # --- Follow-up alerts ---
    st.markdown("---")
    st.subheader("Follow-Up Alerts")

    if not df.empty:
        sent = df[df["sent_at"].notna()].copy()
        if not sent.empty:
            now = datetime.now()
            sent["sent_at_dt"] = pd.to_datetime(sent["sent_at"], errors="coerce")
            sent["days_since"] = sent["sent_at_dt"].apply(
                lambda x: (now - x).days if pd.notna(x) else None
            )
            overdue = sent[
                (sent["days_since"].notna())
                & (sent["days_since"] >= 3)
                & (sent["response_at"].isna())
            ]
            if not overdue.empty:
                st.warning(f"{len(overdue)} outreach message(s) need follow-up (3+ days, no response):")
                st.dataframe(
                    overdue[["company_name", "contact_name", "stage", "sent_at", "days_since"]]
                    .sort_values("days_since", ascending=False)
                    .reset_index(drop=True),
                    use_container_width=True,
                )
            else:
                st.success("No overdue follow-ups.")
        else:
            st.caption("No sent messages to track.")
    else:
        # Show companies with hiring managers but no outreach
        if not companies_df.empty:
            with_hm = companies_df[
                (companies_df["hiring_manager"].notna())
                & (companies_df["hiring_manager"] != "")
                & (companies_df["is_disqualified"] == False)  # noqa: E712
            ]
            if not with_hm.empty:
                st.caption(f"{len(with_hm)} qualified companies with hiring managers — ready for outreach:")
                st.dataframe(
                    with_hm[["name", "tier", "hiring_manager", "h1b_status", "fit_score"]]
                    .sort_values("fit_score", ascending=False)
                    .head(15)
                    .reset_index(drop=True),
                    use_container_width=True,
                )


# ===================================================================
# PAGE 5 — H1B Status
# ===================================================================

def page_h1b_status():
    st.title("H1B Sponsorship Status")
    companies_df = load_companies()
    h1b_df = load_h1b()

    if companies_df.empty:
        st.info("No companies in the database yet.")
        return

    # --- Status breakdown ---
    st.subheader("Status Breakdown")
    h1b_counts = companies_df["h1b_status"].value_counts()

    cols = st.columns(min(len(h1b_counts), 5))
    color_map = {
        "Confirmed": "green",
        "Likely": "blue",
        "Unknown": "orange",
        "Explicit No": "red",
        "N/A": "gray",
    }
    for i, (status, count) in enumerate(h1b_counts.items()):
        col_idx = i % len(cols)
        cols[col_idx].metric(status, count)

    st.bar_chart(h1b_counts)

    st.markdown("---")

    # --- Unverified queue ---
    st.subheader("Unverified Queue")
    unverified = companies_df[
        (companies_df["h1b_status"] == "Unknown")
        & (companies_df["is_disqualified"] == False)  # noqa: E712
    ]
    if not unverified.empty:
        st.warning(f"{len(unverified)} companies need H1B verification:")
        st.dataframe(
            unverified[["name", "tier", "fit_score", "website", "source_portal"]]
            .sort_values("fit_score", ascending=False)
            .reset_index(drop=True),
            use_container_width=True,
        )
    else:
        st.success("All companies have been verified.")

    st.markdown("---")

    # --- H1B records detail ---
    st.subheader("Verification Records")
    if not h1b_df.empty:
        display_cols = [
            "company_name", "status", "source", "lca_count",
            "lca_fiscal_year", "approval_rate", "has_perm", "verified_at",
        ]
        display_cols = [c for c in display_cols if c in h1b_df.columns]
        st.dataframe(
            h1b_df[display_cols].sort_values("company_name").reset_index(drop=True),
            use_container_width=True,
        )
    else:
        # Fall back to company-level H1B data
        h1b_info = companies_df[companies_df["h1b_status"] != "Unknown"]
        if not h1b_info.empty:
            st.dataframe(
                h1b_info[["name", "h1b_status", "h1b_source", "h1b_details"]]
                .sort_values("name")
                .reset_index(drop=True),
                use_container_width=True,
            )
        else:
            st.caption("No verification records yet.")


# ===================================================================
# PAGE 6 — Data Quality
# ===================================================================

def page_data_quality():
    """Data quality monitoring page."""
    st.title("Data Quality")
    df = load_companies()
    if df.empty:
        st.info("No companies to analyze.")
        return
    total = len(df)
    for field in DATA_QUALITY_FIELDS:
        if field in df.columns:
            filled = df[field].notna().sum()
            pct = (filled / total * 100) if total > 0 else 0
            st.markdown(f"**{field}**: {filled}/{total} ({pct:.0f}%)")


# ===================================================================
# PAGE 7 — Contacts
# ===================================================================

def page_contacts():
    """Contacts management page."""
    st.title("Contacts")
    df = load_contacts()
    if df.empty:
        st.info("No contacts found.")
        return
    st.dataframe(df)


# ===================================================================
# PAGE 8 — A/B Testing
# ===================================================================

def page_ab_testing():
    """A/B Testing analytics page."""
    st.title("A/B Testing")
    st.info("A/B testing analytics coming soon.")


# ===================================================================
# PAGE 9 — Follow-Up Manager
# ===================================================================

def page_followup_manager():
    """Follow-up management page."""
    st.title("Follow-Up Manager")
    st.info("Follow-up manager coming soon.")


# ===================================================================
# Router
# ===================================================================

PAGE_MAP = {
    "Pipeline Overview": page_pipeline_overview,
    "Company Explorer": page_company_explorer,
    "Scan History": page_scan_history,
    "Outreach Tracker": page_outreach_tracker,
    "H1B Status": page_h1b_status,
    "Data Quality": page_data_quality,
    "Contacts": page_contacts,
    "A/B Testing": page_ab_testing,
    "Follow-Up Manager": page_followup_manager,
}

PAGE_MAP[page]()

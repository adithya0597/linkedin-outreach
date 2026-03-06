"""LinkedIn Outreach CLI — Typer-based command interface."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="outreach",
    help="LinkedIn outreach automation — deterministic scoring, scraping, and CRM sync",
    no_args_is_help=True,
)
console = Console()


@app.command()
def scan(
    portal: str = typer.Option("all", help="Portal name or 'all'"),
    tier: int = typer.Option(0, help="Scan only this tier (1-3), 0 for all"),
    scan_type: str = typer.Option("full", help="'full' or 'rescan'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show portals without scanning"),
    keywords: str = typer.Option("", help="Comma-separated keywords (overrides portal config)"),
):
    """Scan job portals for new listings."""
    import asyncio
    import time

    import yaml

    from src.db.database import get_engine, get_session, init_db
    from src.scrapers.persistence import persist_scan_results
    from src.scrapers.registry import build_default_registry

    registry = build_default_registry()

    # Select scrapers
    if portal == "all" and tier > 0:
        scrapers = registry.get_scrapers_by_tier(tier)
    elif portal == "all":
        scrapers = registry.get_all_scrapers()
    else:
        try:
            scrapers = [registry.get_scraper(portal)]
        except KeyError:
            console.print(f"[red]Unknown portal: {portal}[/red]")
            console.print(f"Available: {', '.join(s.name for s in registry.get_all_scrapers())}")
            return

    # Dry run — just show portal status
    if dry_run:
        table = Table(title="Portal Scan Status")
        table.add_column("Portal", style="bold")
        table.add_column("Tier")
        table.add_column("Type")
        table.add_column("Status")
        for s in scrapers:
            healthy = "[green]Ready[/green]" if s.is_healthy() else "[red]Down[/red]"
            table.add_row(s.name, str(s.tier.value), type(s).__bases__[0].__name__, healthy)
        console.print(table)
        return

    # Load keywords
    portals_yaml = Path(__file__).parent.parent.parent / "config" / "portals.yaml"
    with open(portals_yaml) as f:
        portals_config = yaml.safe_load(f)

    # Build per-portal keyword map from config
    portal_keywords: dict[str, list[str]] = {}
    for key, cfg in portals_config.get("portals", {}).items():
        portal_keywords[cfg.get("name", key)] = cfg.get(
            "search_keywords", ["AI Engineer", "ML Engineer"]
        )

    # CLI override applies to all portals
    kw_override = [k.strip() for k in keywords.split(",")] if keywords else None

    # Run scan
    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    async def _run_scans() -> None:
        results_table = Table(title="Scan Results")
        results_table.add_column("Portal", style="bold")
        results_table.add_column("Found", justify="right")
        results_table.add_column("New", justify="right")
        results_table.add_column("Time", justify="right")
        results_table.add_column("Status")

        total_found = 0
        total_new = 0

        for s in scrapers:
            if not s.is_healthy():
                results_table.add_row(s.name, "-", "-", "-", "[red]Skipped (unhealthy)[/red]")
                continue

            portal_kws = kw_override or portal_keywords.get(s.name, ["AI Engineer", "ML Engineer"])

            start = time.time()
            try:
                postings = await s.search(portal_kws)
                elapsed = time.time() - start
                found, new = persist_scan_results(
                    session, s.name, postings, scan_type, elapsed
                )
                total_found += found
                total_new += new
                results_table.add_row(
                    s.name,
                    str(found),
                    f"[green]{new}[/green]",
                    f"{elapsed:.1f}s",
                    "[green]OK[/green]",
                )
            except Exception as e:
                elapsed = time.time() - start
                persist_scan_results(session, s.name, [], scan_type, elapsed, str(e))
                results_table.add_row(
                    s.name, "0", "0", f"{elapsed:.1f}s", f"[red]Error: {e}[/red]"
                )

        console.print(results_table)
        console.print(f"\n[bold]Total: {total_found} found, {total_new} new[/bold]")

    asyncio.run(_run_scans())
    session.close()


@app.command()
def validate(
    company: str = typer.Argument(help="Company name to validate"),
):
    """Validate a company against target criteria."""
    from src.validators.company_validator import CompanyValidator

    validator = CompanyValidator()
    result = validator.validate_by_name(company)
    console.print(result)


@app.command()
def score(
    company: str = typer.Argument(help="Company name to score"),
    semantic: bool = typer.Option(False, help="Include semantic embedding scores"),
):
    """Calculate deterministic fit score for a company."""
    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.validators.scoring_engine import FitScoringEngine

    engine = get_engine()
    session = get_session(engine)
    comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()
    if not comp:
        console.print(f"[red]Company '{company}' not found in database.[/red]")
        session.close()
        return

    scorer = FitScoringEngine()
    breakdown = scorer.score(comp, include_semantic=semantic)

    table = Table(title=f"Fit Score: {comp.name}")
    table.add_column("Component", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Max", justify="right")
    table.add_row("H1B Status", f"{breakdown.h1b_score}", "15")
    table.add_row("Company Criteria", f"{breakdown.criteria_score}", "15")
    table.add_row("Tech Overlap", f"{breakdown.tech_overlap_score}", "10")
    table.add_row("Salary Alignment", f"{breakdown.salary_score}", "10")
    table.add_row("[bold]Deterministic Total[/bold]", f"[bold]{breakdown.deterministic_total}[/bold]", "50")
    if semantic:
        table.add_row("Profile-JD Similarity", f"{breakdown.profile_jd_similarity}", "25")
        table.add_row("Domain-Company Similarity", f"{breakdown.domain_company_similarity}", "25")
        table.add_row("[bold]Semantic Total[/bold]", f"[bold]{breakdown.semantic_total}[/bold]", "50")
    table.add_row("[bold green]TOTAL[/bold green]", f"[bold green]{breakdown.total}[/bold green]", "100" if semantic else "50")
    console.print(table)
    session.close()


@app.command()
def h1b(
    company: str = typer.Argument(help="Company name to verify H1B status"),
    batch: bool = typer.Option(False, help="Verify all unverified companies"),
):
    """Verify H1B sponsorship status via 3-source waterfall."""
    import asyncio

    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.validators.h1b_verifier import H1BVerifier

    engine = get_engine()
    session = get_session(engine)
    verifier = H1BVerifier()

    if batch:
        companies = session.query(CompanyORM).filter(
            CompanyORM.h1b_status.in_(["Unknown", "", None]),
            CompanyORM.is_disqualified == False,  # noqa: E712
        ).all()
        console.print(f"[bold]Batch verifying {len(companies)} companies...[/bold]")
        results = asyncio.run(verifier.batch_verify(companies, session=session))
        table = Table(title="H1B Verification Results")
        table.add_column("Company", style="bold")
        table.add_column("Status")
        table.add_column("Source")
        for record in results:
            style = {"Confirmed": "green", "Explicit No": "red"}.get(record.status.value, "yellow")
            table.add_row(record.company_name, f"[{style}]{record.status.value}[/{style}]", record.source)
        console.print(table)
    else:
        comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()
        if not comp:
            console.print(f"[red]Company '{company}' not found in database.[/red]")
            session.close()
            return
        console.print(f"[bold]Verifying H1B for {comp.name}...[/bold]")
        record = asyncio.run(verifier.verify(comp))

        table = Table(title=f"H1B: {comp.name}")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        style = {"Confirmed": "green", "Explicit No": "red"}.get(record.status.value, "yellow")
        table.add_row("Status", f"[{style}]{record.status.value}[/{style}]")
        table.add_row("Source", record.source)
        if record.lca_count:
            table.add_row("LCA Count", str(record.lca_count))
        if record.approval_rate is not None:
            table.add_row("Approval Rate", f"{record.approval_rate}%")
        if record.has_perm:
            table.add_row("PERM", "Yes")
        if record.has_everify:
            table.add_row("E-Verify", "Yes")
        console.print(table)

    session.close()


@app.command()
def draft(
    company: str = typer.Argument(None, help="Company name"),
    contact: str = typer.Argument(None, help="Contact name"),
    template: str = typer.Option("connection_request_a.j2", help="Template file name"),
    list_templates: bool = typer.Option(False, "--list", help="List available templates"),
):
    """Draft outreach messages using Jinja2 templates."""
    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.outreach.template_engine import OutreachTemplateEngine

    engine_tmpl = OutreachTemplateEngine()

    if list_templates:
        console.print("[bold]Available templates:[/bold]")
        for t in engine_tmpl.list_templates():
            console.print(f"  {t}")
        return

    if not company or not contact:
        console.print("[red]Both COMPANY and CONTACT are required (or use --list).[/red]")
        raise typer.Exit(1)

    engine = get_engine()
    session = get_session(engine)
    comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()

    context = {
        # Template variables (match .j2 files)
        "name": contact,
        "company": comp.name if comp else company,
        "role": comp.role if comp else "AI Engineer",
        "topic": comp.differentiators.split(",")[0].strip() if comp and comp.differentiators else "AI engineering",
        "relevant_experience": "building production AI systems (semantic graphs, RAG pipelines)",
        "mutual_interest": comp.differentiators if comp else "AI/ML",
        "specific_insight": f"what {comp.name if comp else company} is building in AI",
        "your_background": "AI engineer with experience in LangChain, Neo4j, and production RAG systems",
        "value_prop": "138-node semantic graph powering 90% automated code translation",
        "connection_point": "AI engineering and production ML systems",
        "follow_up_context": f"connecting about {comp.role if comp and comp.role else 'AI engineering'} opportunities",
    }

    # Determine message_type from template name
    if "connection" in template:
        msg_type = "connection_request"
    elif "inmail" in template:
        msg_type = "inmail"
    elif "pre_engagement" in template:
        msg_type = "pre_engagement"
    else:
        msg_type = "follow_up"

    rendered, is_valid, char_count = engine_tmpl.render(template, context, msg_type)

    console.print(f"\n[bold]Template:[/bold] {template}")
    console.print(f"[bold]Type:[/bold] {msg_type}")
    status = "[green]VALID[/green]" if is_valid else "[red]OVER LIMIT[/red]"
    console.print(f"[bold]Chars:[/bold] {char_count} {status}")
    console.print(f"\n{'─' * 50}")
    console.print(rendered)
    console.print(f"{'─' * 50}")

    session.close()


@app.command(name="sync-notion")
def sync_notion(
    direction: str = typer.Option("push", help="'push', 'pull', or 'both'"),
):
    """Sync data with Notion CRM."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.integrations.notion_sync import NotionCRM

    api_key = os.getenv("NOTION_API_KEY", "")
    database_id = os.getenv("NOTION_DATABASE_ID", "0c412604-a409-47ab-8c04-29f112c2c683")

    if not api_key:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return

    crm = NotionCRM(api_key=api_key, database_id=database_id)
    engine = get_engine()
    session = get_session(engine)

    if direction in ("push", "both"):
        companies = session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).all()
        console.print(f"[bold]Pushing {len(companies)} companies to Notion...[/bold]")
        page_ids = asyncio.run(crm.push_all(companies))
        console.print(f"[green]Pushed {len(page_ids)} companies.[/green]")

    if direction in ("pull", "both"):
        console.print("[bold]Pulling from Notion...[/bold]")
        pages = asyncio.run(crm.pull_all())
        console.print(f"[green]Pulled {len(pages)} records from Notion.[/green]")
        for page in pages[:5]:
            console.print(f"  {page.get('name', '?')} — {page.get('tier', '?')}")
        if len(pages) > 5:
            console.print(f"  ... and {len(pages) - 5} more")

    session.close()


@app.command()
def audit():
    """Run data quality audit on all companies."""
    from src.db.database import get_engine, get_session
    from src.validators.quality_gates import QualityAuditor

    engine = get_engine()
    session = get_session(engine)
    auditor = QualityAuditor(session)
    report = auditor.full_audit()
    console.print(report)
    session.close()


@app.command()
def dashboard():
    """Launch Streamlit dashboard."""
    import subprocess
    import sys

    dashboard_path = Path(__file__).parent.parent / "dashboard" / "app.py"
    console.print(f"[bold]Launching dashboard...[/bold]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path)])


@app.command()
def seed(
    target_list: str = typer.Option(
        "Startup_Target_List.md",
        help="Path to Startup_Target_List.md",
    ),
    db_path: str = typer.Option("data/outreach.db", help="SQLite database path"),
):
    """Seed database from Startup_Target_List.md."""
    from src.db.seed import seed_database

    audit_report = seed_database(target_list, db_path)

    table = Table(title="Migration Audit Report")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Total Parsed", str(audit_report["total_parsed"]))
    table.add_row("Inserted", str(audit_report["inserted"]))
    table.add_row("Disqualified", str(len(audit_report["disqualified"])))
    table.add_row("Borderline", str(len(audit_report["borderline"])))
    table.add_row("Skeleton Records", str(len(audit_report["skeleton_records"])))
    table.add_row("Tier Mismatches", str(len(audit_report["tier_mismatches"])))
    console.print(table)

    if audit_report["disqualified"]:
        console.print("\n[red bold]Disqualified:[/red bold]")
        for d in audit_report["disqualified"]:
            console.print(f"  ❌ {d}")

    if audit_report["borderline"]:
        console.print("\n[yellow bold]Borderline:[/yellow bold]")
        for b in audit_report["borderline"]:
            console.print(f"  ⚠️ {b}")


@app.command()
def stats():
    """Show database statistics."""
    from sqlalchemy import func

    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM

    engine = get_engine()
    session = get_session(engine)

    total = session.query(func.count(CompanyORM.id)).scalar()
    disqualified = session.query(func.count(CompanyORM.id)).filter(
        CompanyORM.is_disqualified == True  # noqa: E712
    ).scalar()
    needs_review = session.query(func.count(CompanyORM.id)).filter(
        CompanyORM.needs_review == True  # noqa: E712
    ).scalar()
    avg_completeness = session.query(func.avg(CompanyORM.data_completeness)).scalar()

    table = Table(title="Database Statistics")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Total Companies", str(total))
    table.add_row("Disqualified", str(disqualified))
    table.add_row("Needs Review", str(needs_review))
    table.add_row("Avg Completeness", f"{avg_completeness:.1f}%" if avg_completeness else "N/A")

    # Tier breakdown
    tiers = session.query(
        CompanyORM.tier, func.count(CompanyORM.id)
    ).group_by(CompanyORM.tier).all()
    for tier_name, count in tiers:
        table.add_row(f"  {tier_name}", str(count))

    console.print(table)
    session.close()


@app.command(name="run-pipeline")
def run_pipeline(
    skip_validate: bool = typer.Option(False, help="Skip validation step"),
    skip_score: bool = typer.Option(False, help="Skip scoring step"),
    h1b_verify: bool = typer.Option(False, "--h1b", help="Run H1B verification step"),
    semantic: bool = typer.Option(False, help="Include semantic scoring"),
):
    """Run full pipeline: validate → h1b → score all companies."""
    from src.db.database import get_engine, get_session
    from src.pipeline.orchestrator import Pipeline

    engine = get_engine()
    session = get_session(engine)
    pipeline = Pipeline(session)
    results = pipeline.run(
        validate=not skip_validate,
        score=not skip_score,
        verify_h1b=h1b_verify,
        include_semantic=semantic,
    )

    if "validation" in results:
        v = results["validation"]
        console.print(
            f"\n[bold]Validation:[/bold] {v['passed']} passed, "
            f"{v['failed']} failed, {v['borderline']} borderline"
        )

    if "h1b" in results:
        h = results["h1b"]
        console.print(
            f"\n[bold]H1B Verification:[/bold] {h['verified']} checked — "
            f"[green]{h['confirmed']} confirmed[/green], "
            f"[red]{h['explicit_no']} no[/red], "
            f"[yellow]{h['unknown']} unknown[/yellow]"
        )

    if "scoring" in results:
        s = results["scoring"]
        console.print(f"\n[bold]Scored {s['scored']} companies. Top 10:[/bold]")
        table = Table()
        table.add_column("#", justify="right")
        table.add_column("Company", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Tier")
        for i, (name, score_val, tier) in enumerate(s["top_10"], 1):
            table.add_row(str(i), name, f"{score_val}", tier)
        console.print(table)

    session.close()


if __name__ == "__main__":
    app()

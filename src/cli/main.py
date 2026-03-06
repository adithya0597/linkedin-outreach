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
    smart: bool = typer.Option(False, "--smart", help="Auto-skip demoted portals via PortalScorer"),
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

    # Smart scan — filter out demoted portals
    if smart:
        from src.pipeline.smart_scan import SmartScanOrchestrator
        orchestrator = SmartScanOrchestrator(session)
        smart_list = orchestrator.get_smart_portal_list()
        scrapers = [s for s in scrapers if s.name in smart_list]
        console.print(f"[bold]Smart scan: using {len(scrapers)} portals (demoted excluded)[/bold]")

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
                found, new, new_co = persist_scan_results(
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
                persist_scan_results(session, s.name, [], scan_type, elapsed, errors=str(e))
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
    personalize: bool = typer.Option(False, "--personalize", help="Use domain-matched personalization"),
):
    """Draft outreach messages using Jinja2 templates."""
    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM, ContactORM
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

    if personalize and comp:
        from src.outreach.personalizer import OutreachPersonalizer

        personalizer = OutreachPersonalizer()
        contact_orm = session.query(ContactORM).filter(
            ContactORM.company_name.ilike(f"%{company}%"),
            ContactORM.name.ilike(f"%{contact}%"),
        ).first()
        context = personalizer.enrich_context(comp, contact_orm)
        if not context.get("name"):
            context["name"] = contact
    else:
        context = {
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
    if personalize:
        console.print(f"[bold]Domain:[/bold] {context.get('domain', 'N/A')}")
    status = "[green]VALID[/green]" if is_valid else "[red]OVER LIMIT[/red]"
    console.print(f"[bold]Chars:[/bold] {char_count} {status}")
    console.print(f"\n{'─' * 50}")
    console.print(rendered)
    console.print(f"{'─' * 50}")

    session.close()


@app.command(name="sync-notion")
def sync_notion(
    direction: str = typer.Option("push", help="'push', 'pull', or 'both'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show Notion properties without API calls"),
):
    """Sync data with Notion CRM."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.integrations.notion_sync import NotionCRM

    api_key = os.getenv("NOTION_API_KEY", "")
    database_id = os.getenv("NOTION_DATABASE_ID", "0c412604-a409-47ab-8c04-29f112c2c683")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return

    crm = NotionCRM(api_key=api_key or "dry-run", database_id=database_id)
    engine = get_engine()
    session = get_session(engine)

    if dry_run:
        companies = session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).limit(5).all()
        console.print(f"[bold]Dry run — showing Notion properties for {len(companies)} companies:[/bold]\n")
        for comp in companies:
            props = asyncio.run(crm.sync_company(comp, dry_run=True))
            console.print(f"[bold]{comp.name}[/bold]")
            for key, val in props.items():
                console.print(f"  {key}: {val}")
            console.print()
        session.close()
        return

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


@app.command()
def archive(
    max_days: int = typer.Option(30, help="Archive postings older than this many days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show count without archiving"),
):
    """Archive stale job postings (mark inactive)."""
    from src.db.database import get_engine, get_session, init_db
    from src.validators.quality_gates import QualityAuditor

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    auditor = QualityAuditor(session)

    if dry_run:
        from datetime import datetime, timedelta

        from src.db.orm import JobPostingORM

        cutoff = datetime.now() - timedelta(days=max_days)
        count = session.query(JobPostingORM).filter(
            JobPostingORM.discovered_date < cutoff,
            JobPostingORM.is_active == True,  # noqa: E712
        ).count()
        console.print(f"[bold]{count}[/bold] stale postings older than {max_days} days (dry run, not archived)")
    else:
        count = auditor.archive_stale_postings(max_days=max_days)
        console.print(f"[green]Archived {count} stale postings older than {max_days} days.[/green]")

    session.close()


@app.command(name="portal-scores")
def portal_scores():
    """Show portal performance scores and promotion/demotion recommendations."""
    from src.db.database import get_engine, get_session, init_db
    from src.validators.portal_scorer import PortalScorer

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    scorer = PortalScorer(session)
    scores = scorer.score_all()

    if not scores:
        console.print("[yellow]No scan data available. Run a portal scan first.[/yellow]")
        session.close()
        return

    table = Table(title="Portal Performance Scores")
    table.add_column("Portal", style="bold")
    table.add_column("Velocity", justify="right")
    table.add_column("PM Delta", justify="right")
    table.add_column("Conversion", justify="right")
    table.add_column("Total", justify="right", style="bold")
    table.add_column("Recommendation")

    for s in scores:
        rec_style = {"promote": "green", "demote": "red", "hold": "yellow"}.get(s.recommendation, "white")
        table.add_row(
            s.portal,
            str(s.velocity_score),
            str(s.afternoon_delta_score),
            str(s.conversion_score),
            str(s.total),
            f"[{rec_style}]{s.recommendation.upper()}[/{rec_style}]",
        )

    console.print(table)
    session.close()


@app.command()
def health():
    """Show portal health status based on scan failure history."""
    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.health_monitor import HealthMonitor

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    monitor = HealthMonitor(session)
    statuses = monitor.check_all()

    if not statuses:
        console.print("[yellow]No scan data available. Run a portal scan first.[/yellow]")
        session.close()
        return

    table = Table(title="Portal Health Status")
    table.add_column("Portal", style="bold")
    table.add_column("Consecutive Failures", justify="right")
    table.add_column("Status")
    table.add_column("Last Success")
    table.add_column("Last Failure")

    for s in statuses:
        status = "[green]Healthy[/green]" if s.is_healthy else "[red]UNHEALTHY[/red]"
        last_ok = str(s.last_success.strftime("%Y-%m-%d %H:%M")) if s.last_success else "N/A"
        last_fail = str(s.last_failure.strftime("%Y-%m-%d %H:%M")) if s.last_failure else "N/A"
        table.add_row(
            s.portal,
            str(s.consecutive_failures),
            status,
            last_ok,
            last_fail,
        )

    console.print(table)

    alerts = [s for s in statuses if s.alert_triggered]
    if alerts:
        console.print(f"\n[red bold]{len(alerts)} portal(s) need attention![/red bold]")

    session.close()


@app.command(name="enrich-h1b")
def enrich_h1b(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show matches without updating"),
):
    """Apply known H1B statuses from Frog Hire lookup to Unknown companies."""
    from src.db.database import get_engine, get_session, init_db
    from src.db.h1b_lookup import KNOWN_H1B_STATUSES, apply_known_statuses
    from src.db.orm import CompanyORM

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    if dry_run:
        unknown = session.query(CompanyORM).filter(
            CompanyORM.h1b_status == "Unknown"
        ).all()
        table = Table(title="H1B Enrichment Preview (dry run)")
        table.add_column("Company", style="bold")
        table.add_column("Current")
        table.add_column("Known Status")
        matches = 0
        for comp in unknown:
            for known_name, status in KNOWN_H1B_STATUSES.items():
                if comp.name.lower() == known_name.lower() and status != "Unknown":
                    table.add_row(comp.name, comp.h1b_status, f"[green]{status}[/green]")
                    matches += 1
                    break
        console.print(table)
        console.print(f"\n[bold]{matches} companies would be updated.[/bold]")
    else:
        count = apply_known_statuses(session)
        console.print(f"[green]Updated {count} companies with known H1B statuses.[/green]")

    session.close()


@app.command()
def contacts(
    company: str = typer.Argument(help="Company name to find contacts for"),
):
    """Generate LinkedIn search URLs for hiring contacts at a company."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)
    results = researcher.find_hiring_contacts(company)

    table = Table(title=f"LinkedIn Search URLs — {company}")
    table.add_column("Priority", justify="right")
    table.add_column("Title", style="bold")
    table.add_column("Search URL")

    for r in results:
        table.add_row(str(r["priority"]), r["title"], r["search_url"])

    console.print(table)
    session.close()


@app.command(name="record-contact")
def record_contact(
    company: str = typer.Argument(help="Company name"),
    name: str = typer.Argument(help="Contact name"),
    title: str = typer.Argument(help="Contact title (e.g. CTO, Recruiter)"),
    linkedin_url: str = typer.Option("", help="LinkedIn profile URL"),
    degree: int = typer.Option(None, help="LinkedIn connection degree (1, 2, or 3)"),
    open_profile: bool = typer.Option(False, help="Is an Open Profile (free InMail)"),
):
    """Record a contact for a target company."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)

    contact = researcher.record_contact(company, {
        "name": name,
        "title": title,
        "linkedin_url": linkedin_url,
        "linkedin_degree": degree,
        "is_open_profile": open_profile,
    })

    console.print(f"[green]Recorded:[/green] {contact.name} ({contact.title}) at {company}")
    console.print(f"  Score: {contact.contact_score}, Company ID: {contact.company_id or 'N/A'}")
    session.close()


@app.command(name="rank-contacts")
def rank_contacts(
    company: str = typer.Argument(help="Company name"),
):
    """Show ranked contacts for a company."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)
    ranked = researcher.rank_contacts(company)

    if not ranked:
        console.print(f"[yellow]No contacts found for {company}.[/yellow]")
        session.close()
        return

    table = Table(title=f"Contacts — {company}")
    table.add_column("#", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Title")
    table.add_column("Score", justify="right")
    table.add_column("Degree")
    table.add_column("Open Profile")

    for i, c in enumerate(ranked, 1):
        table.add_row(
            str(i), c.name, c.title, f"{c.contact_score}",
            str(c.linkedin_degree or "?"),
            "[green]Yes[/green]" if c.is_open_profile else "No",
        )

    console.print(table)
    session.close()


@app.command()
def viewers():
    """Show LinkedIn Premium 'Who Viewed Your Profile' URL and instructions."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)
    info = researcher.check_profile_viewers()

    console.print(f"\n[bold]Profile Viewers URL:[/bold] {info['viewers_url']}")
    console.print(f"\n[bold]Instructions:[/bold]\n{info['instructions']}")
    console.print("\n[bold]To record a viewer as a contact:[/bold]")
    console.print("  outreach record-contact <company> <name> <title> [--degree N] [--open-profile]")
    session.close()


@app.command(name="draft-all")
def draft_all(
    tier: str = typer.Option(None, help="Filter by tier (e.g. 'Tier 1 - HIGH')"),
    limit: int = typer.Option(None, help="Max companies to draft"),
    types: str = typer.Option("connection_request", help="Comma-separated message types"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show count without creating records"),
):
    """Batch draft outreach for all qualifying companies."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.batch_engine import BatchOutreachEngine

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    batch = BatchOutreachEngine(session)
    template_types = [t.strip() for t in types.split(",")]

    if dry_run:
        from src.db.orm import CompanyORM
        query = session.query(CompanyORM).filter(CompanyORM.is_disqualified == False)  # noqa: E712
        if tier:
            query = query.filter(CompanyORM.tier == tier)
        count = query.count()
        console.print(f"[bold]Dry run: would draft for {count} companies[/bold]")
        session.close()
        return

    results = batch.draft_all(tier=tier, limit=limit, template_types=template_types)

    table = Table(title="Batch Draft Results")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Drafted", f"[green]{results['drafted']}[/green]")
    table.add_row("Skipped", str(results["skipped"]))
    table.add_row("Over Limit", f"[yellow]{results['over_limit']}[/yellow]" if results["over_limit"] else "0")
    table.add_row("Errors", f"[red]{len(results['errors'])}[/red]" if results["errors"] else "0")
    console.print(table)

    if results["errors"]:
        for err in results["errors"]:
            console.print(f"  [red]{err}[/red]")

    session.close()


@app.command(name="outreach-sequence")
def outreach_sequence(
    company: str = typer.Argument(help="Company name"),
    contact: str = typer.Argument(help="Contact name"),
    start_date: str = typer.Option(None, help="Start date (YYYY-MM-DD), defaults to today"),
):
    """Build a 14-day outreach sequence with template recommendations."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.batch_engine import BatchOutreachEngine

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    batch = BatchOutreachEngine(session)
    sequence = batch.build_sequence(company, contact, start_date)

    if not sequence:
        console.print(f"[red]Company '{company}' not found in database.[/red]")
        session.close()
        return

    table = Table(title=f"Outreach Sequence: {company} -> {contact}")
    table.add_column("Step", style="bold")
    table.add_column("Date")
    table.add_column("Day")
    table.add_column("Template")
    table.add_column("Chars", justify="right")
    table.add_column("Valid")

    for step in sequence:
        valid_str = "[green]OK[/green]" if step.get("is_valid", True) else "[red]OVER[/red]"
        table.add_row(
            step["step"],
            step["date"],
            step["day"],
            step.get("template", ""),
            str(step.get("char_count", "")),
            valid_str,
        )

    console.print(table)
    session.close()


@app.command()
def rescan(
    smart: bool = typer.Option(True, help="Use smart portal selection (promoted + afternoon list)"),
    h1b: bool = typer.Option(True, "--h1b/--no-h1b", help="Run H1B enrichment after scan"),
    keywords: str = typer.Option("", help="Comma-separated keywords"),
):
    """Afternoon rescan of high-velocity portals with smart filtering."""
    import asyncio

    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.smart_scan import SmartScanOrchestrator

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    orchestrator = SmartScanOrchestrator(session)

    if smart:
        portals = orchestrator.get_rescan_portals()
        console.print(f"[bold]Smart rescan: {len(portals)} portals[/bold]")
        for p in portals:
            console.print(f"  {p}")
    else:
        portals = None

    kws = [k.strip() for k in keywords.split(",")] if keywords else None

    result = asyncio.run(orchestrator.run_smart_scan(
        portals=portals,
        keywords=kws,
        enrich_h1b=h1b,
        scan_type="rescan",
    ))

    scan = result["scan_results"]
    console.print(f"\n[bold]Results:[/bold] {scan.get('total_found', 0)} found, {scan.get('total_new', 0)} new")
    if result["h1b_enriched"]:
        console.print(f"[green]H1B enriched: {result['h1b_enriched']} companies[/green]")
    if result["skipped_portals"]:
        console.print(f"[yellow]Skipped (demoted): {', '.join(result['skipped_portals'])}[/yellow]")

    session.close()


@app.command(name="sync-contacts")
def sync_contacts(
    direction: str = typer.Option("push", help="'push', 'pull', or 'both'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show properties without API calls"),
):
    """Sync contacts with Notion CRM."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session, init_db
    from src.integrations.notion_contacts import NotionContactSync

    api_key = os.getenv("NOTION_API_KEY", "")
    contacts_db_id = os.getenv("NOTION_CONTACTS_DB_ID", "")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return
    if not contacts_db_id and not dry_run:
        console.print("[red]NOTION_CONTACTS_DB_ID not set in environment.[/red]")
        return

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    sync = NotionContactSync(
        api_key=api_key or "dry-run",
        contacts_database_id=contacts_db_id or "dry-run",
        session=session,
    )

    if direction in ("push", "both"):
        result = asyncio.run(sync.push_all_contacts(dry_run=dry_run))
        console.print(f"[green]Pushed: {result['pushed']}[/green], Skipped: {result['skipped']}")
        if result["errors"]:
            for err in result["errors"]:
                console.print(f"  [red]{err}[/red]")

    if direction in ("pull", "both"):
        contacts_list = asyncio.run(sync.pull_all_contacts())
        console.print(f"[green]Pulled {len(contacts_list)} contacts from Notion.[/green]")

    session.close()


@app.command(name="score-all")
def score_all(
    semantic: bool = typer.Option(False, help="Include semantic + domain match scoring"),
    limit: int = typer.Option(None, help="Limit to top N results displayed"),
):
    """Re-score all companies with optional domain match bonus."""
    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.orchestrator import Pipeline

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    pipeline = Pipeline(session)
    results = pipeline.score_all(include_semantic=semantic)

    console.print(f"[bold]Scored {results['scored']} companies[/bold]")

    top = results["top_10"]
    if limit:
        top = top[:limit]

    table = Table(title="Top Companies by Fit Score")
    table.add_column("#", justify="right")
    table.add_column("Company", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Tier")
    for i, (name, score_val, tier_val) in enumerate(top, 1):
        table.add_row(str(i), name, f"{score_val}", tier_val)
    console.print(table)

    session.close()


@app.command(name="outreach-followups")
def outreach_followups(
    days: int = typer.Option(7, help="Look-ahead window in days"),
    overdue_only: bool = typer.Option(False, "--overdue-only", help="Show only overdue follow-ups"),
):
    """Show overdue and upcoming outreach follow-ups."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.followup_manager import FollowUpManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    manager = FollowUpManager(session)
    alert = manager.generate_daily_alert()

    if alert["overdue"]:
        table = Table(title="Overdue Follow-ups")
        table.add_column("Company", style="bold")
        table.add_column("Contact")
        table.add_column("Last Step")
        table.add_column("Next Step")
        table.add_column("Days Overdue", justify="right", style="red")
        table.add_column("Suggested Template")
        for item in alert["overdue"]:
            table.add_row(
                item["company_name"], item["contact_name"],
                item["last_step"], item["next_step"],
                str(item["days_overdue"]), item["suggested_template"],
            )
        console.print(table)
    else:
        console.print("[green]No overdue follow-ups.[/green]")

    if not overdue_only:
        pending = manager.get_pending_followups(days_ahead=days)
        if pending:
            table = Table(title=f"Upcoming Follow-ups (next {days} days)")
            table.add_column("Company", style="bold")
            table.add_column("Contact")
            table.add_column("Step")
            table.add_column("Due Date")
            for item in pending:
                table.add_row(
                    item["company_name"], item["contact_name"],
                    item["step"], item["due_date"],
                )
            console.print(table)

    console.print(f"\n[bold]Active sequences: {alert['total_active_sequences']}[/bold]")
    session.close()


@app.command(name="outreach-mark-sent")
def outreach_mark_sent(
    company: str = typer.Argument(help="Company name"),
    step: str = typer.Argument(help="Sequence step (connection_request, follow_up, etc.)"),
    contact_name: str = typer.Option(None, help="Contact name (optional)"),
):
    """Mark an outreach step as sent."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.sequence_tracker import SequenceTracker

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    tracker = SequenceTracker(session)
    record = tracker.mark_sent(company, step, contact_name)

    if record:
        console.print(f"[green]Marked sent:[/green] {company} / {step}")
        console.print(f"  Stage: {record.stage}, Sent at: {record.sent_at}")
    else:
        console.print(f"[red]Company '{company}' not found in database.[/red]")

    session.close()


@app.command(name="outreach-mark-responded")
def outreach_mark_responded(
    company: str = typer.Argument(help="Company name"),
    response: str = typer.Option("", "--response", help="Response text"),
):
    """Mark outreach as responded."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.sequence_tracker import SequenceTracker

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    tracker = SequenceTracker(session)
    record = tracker.mark_responded(company, response)

    if record:
        console.print(f"[green]Marked responded:[/green] {company}")
        console.print(f"  Stage: {record.stage}, Responded at: {record.response_at}")
    else:
        console.print(f"[yellow]No sent outreach found for '{company}'.[/yellow]")

    session.close()


@app.command(name="kickoff-tier1")
def kickoff_tier1(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show ready companies without creating records"),
):
    """Run Tier 1 kickoff: draft → sequence → send report."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.kickoff import Tier1Kickoff

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    kickoff = Tier1Kickoff(session)
    result = kickoff.run(dry_run=dry_run)

    mode = " (DRY RUN)" if dry_run else ""
    console.print(f"\n[bold]Tier 1 Kickoff{mode}[/bold]")
    console.print(f"  Companies: {len(result['companies'])}")
    console.print(f"  Drafted: {result['drafted']}")
    console.print(f"  Sequences built: {result['sequences_built']}")

    if result["errors"]:
        console.print(f"\n[red]Errors ({len(result['errors'])}):[/red]")
        for err in result["errors"]:
            console.print(f"  {err}")

    if result["report"]:
        console.print(f"\n{result['report']}")

    session.close()


@app.command(name="send-queue")
def send_queue(
    limit: int = typer.Option(20, help="Max sends for today"),
    week_status: bool = typer.Option(False, "--week-status", help="Show weekly rate limit status only"),
):
    """Show daily prioritized send queue with rate limiting."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.send_queue import SendQueueManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    mgr = SendQueueManager(session)

    # Always show rate limit status
    status = mgr.get_rate_limit_status()
    console.print(f"\n[bold]Weekly Rate Limit:[/bold]")
    console.print(f"  Sent this week: {status['sent_this_week']} / {status['limit']}")
    console.print(f"  Remaining: {status['remaining']}")
    console.print(f"  Resets: {status['resets_on']}")

    if week_status:
        session.close()
        return

    queue = mgr.generate_daily_queue(max_sends=limit)

    if not queue:
        console.print("\n[yellow]No items in send queue (all sent or limit reached).[/yellow]")
        session.close()
        return

    table = Table(title=f"Daily Send Queue ({len(queue)} items)")
    table.add_column("#", justify="right")
    table.add_column("Company", style="bold")
    table.add_column("Contact")
    table.add_column("Template")
    table.add_column("Chars", justify="right")
    table.add_column("Fit", justify="right")

    for i, item in enumerate(queue, 1):
        table.add_row(
            str(i),
            item["company_name"],
            item["contact_name"],
            item["template_type"] or "",
            str(item["char_count"]),
            f"{item['fit_score']:.0f}",
        )

    console.print(table)
    session.close()


@app.command(name="sync-outreach")
def sync_outreach(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show sync plan without API calls"),
):
    """Push outreach stages to Notion CRM."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session, init_db
    from src.integrations.outreach_sync import OutreachNotionSync

    api_key = os.getenv("NOTION_API_KEY", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "0c412604-a409-47ab-8c04-29f112c2c683")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    sync = OutreachNotionSync(
        api_key=api_key or "dry-run",
        applications_db_id=db_id,
        session=session,
    )

    result = asyncio.run(sync.sync_all_outreach_stages(dry_run=dry_run))
    mode = " (DRY RUN)" if dry_run else ""

    console.print(f"\n[bold]Outreach → Notion Sync{mode}[/bold]")
    console.print(f"  Synced: [green]{result['synced']}[/green]")
    console.print(f"  Skipped: {result['skipped']}")
    if result["errors"]:
        console.print(f"  Errors: [red]{len(result['errors'])}[/red]")
        for err in result["errors"]:
            console.print(f"    {err}")

    console.print(f"\n  Stage counts: {result['stage_counts']}")
    session.close()


@app.command(name="priority-report")
def priority_report(
    semantic: bool = typer.Option(False, "--semantic", help="Include semantic scoring"),
    output: str = typer.Option(None, "--output", help="Export markdown to file"),
    notion: bool = typer.Option(False, "--notion", help="Update Notion fit scores"),
):
    """Generate priority matrix report grouped by tier."""
    from src.db.database import get_engine, get_session, init_db
    from src.validators.priority_report import PriorityReporter

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    reporter = PriorityReporter(session)

    if output:
        report = reporter.export_markdown(output)
        console.print(f"[green]Report exported to {output}[/green]")
        console.print(report)
    else:
        matrix = reporter.generate_priority_matrix(include_semantic=semantic)
        console.print(f"\n[bold]Priority Matrix[/bold]")
        console.print(f"  Total scored: {matrix['total_scored']}")
        console.print(f"  Average score: {matrix['avg_score']}")

        for tier_name, companies in sorted(matrix["tiers"].items()):
            console.print(f"\n[bold]{tier_name}[/bold] ({len(companies)} companies)")
            table = Table()
            table.add_column("#", justify="right")
            table.add_column("Company", style="bold")
            table.add_column("Fit Score", justify="right")
            table.add_column("H1B")
            table.add_column("Domain")
            table.add_column("Stage")
            for i, c in enumerate(companies, 1):
                table.add_row(
                    str(i), c["name"], f"{c['fit_score']:.0f}",
                    c["h1b_status"], c["domain"], c["stage"],
                )
            console.print(table)

    if notion:
        result = reporter.export_notion_update(dry_run=False)
        console.print(f"\n[bold]Notion Update:[/bold] {result['updated']} updated, {result['unchanged']} unchanged")
        if result["errors"]:
            for err in result["errors"]:
                console.print(f"  [red]{err}[/red]")

    session.close()


@app.command()
def enrich(
    company: str = typer.Option(None, "--company", help="Enrich a specific company"),
    batch: bool = typer.Option(False, "--batch", help="Batch enrich all skeleton records"),
    threshold: float = typer.Option(50, "--threshold", help="Completeness threshold for skeleton detection"),
):
    """Enrich company data by parsing text fields for structured information."""
    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.enrichment import CompanyEnricher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    enricher = CompanyEnricher(session)

    if company:
        from src.db.orm import CompanyORM

        comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()
        if not comp:
            console.print(f"[red]Company '{company}' not found.[/red]")
            session.close()
            return

        changes = enricher.enrich_from_description(comp)
        if changes:
            console.print(f"[green]Enriched {comp.name}:[/green]")
            for field, value in changes.items():
                console.print(f"  {field}: {value}")
            session.commit()
        else:
            console.print(f"[yellow]No new data found for {comp.name}.[/yellow]")
    elif batch:
        result = enricher.batch_enrich(threshold=threshold)

        table = Table(title="Batch Enrichment Results")
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")
        table.add_row("Enriched", f"[green]{result['enriched']}[/green]")
        table.add_row("Skipped", str(result["skipped"]))
        table.add_row("Errors", f"[red]{len(result['errors'])}[/red]" if result["errors"] else "0")
        console.print(table)

        console.print("\n[bold]Fields filled:[/bold]")
        for field, count in result["fields_filled"].items():
            console.print(f"  {field}: {count}")
    else:
        # Default: show skeleton records and completeness stats
        result = enricher.compute_all_completeness()
        console.print(f"[bold]Updated completeness for {result['updated']} companies[/bold]")
        console.print(f"Average completeness: {result['avg_completeness']}%")

        skeletons = enricher.get_skeleton_records(threshold=threshold)
        if skeletons:
            console.print(f"\n[yellow]{len(skeletons)} skeleton records (below {threshold}% completeness):[/yellow]")
            table = Table()
            table.add_column("Company", style="bold")
            table.add_column("Completeness", justify="right")
            table.add_column("Tier")
            for s in skeletons[:15]:
                table.add_row(s.name, f"{s.data_completeness:.0f}%", s.tier or "N/A")
            console.print(table)
        else:
            console.print(f"[green]No skeleton records below {threshold}%.[/green]")

    session.close()


@app.command(name="daily-run")
def daily_run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run (no Notion API calls)"),
    skip_scan: bool = typer.Option(False, "--skip-scan", help="Skip scan stage"),
    skip_enrich: bool = typer.Option(False, "--skip-enrich", help="Skip enrichment stage"),
):
    """Run full daily pipeline: scan → enrich → score → queue → followup → sync."""
    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.daily_orchestrator import DailyOrchestrator

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    orchestrator = DailyOrchestrator(session)
    results = orchestrator.run_full_day(
        dry_run=dry_run, skip_scan=skip_scan, skip_enrich=skip_enrich
    )

    summary = orchestrator.generate_daily_summary()
    console.print(summary)

    console.print(f"\n[bold]Total time: {results['total_time']}s[/bold]")
    session.close()


@app.command(name="outreach-audit-trail")
def outreach_audit_trail(
    company: str = typer.Argument(..., help="Company name (partial match)"),
):
    """Show the audit trail for a company's outreach record."""
    import json

    from src.db.database import get_engine, get_session, init_db
    from src.db.orm import OutreachORM

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    outreach = (
        session.query(OutreachORM)
        .filter(OutreachORM.company_name.ilike(f"%{company}%"))
        .first()
    )

    if not outreach:
        console.print(f"[red]No outreach record found for '{company}'[/red]")
        session.close()
        return

    console.print(f"[bold]{outreach.company_name}[/bold] — Stage: {outreach.stage}")
    console.print(f"Contact: {outreach.contact_name or 'N/A'}")
    console.print(f"Template: {outreach.template_type or 'N/A'}")
    console.print()

    trail = outreach.audit_trail or ""
    if not trail.strip():
        console.print("[yellow]No audit trail entries yet.[/yellow]")
    else:
        table = Table(title="Audit Trail")
        table.add_column("Timestamp", style="cyan")
        table.add_column("From", style="yellow")
        table.add_column("To", style="green")
        table.add_column("By")

        for line in trail.strip().split("\n"):
            try:
                entry = json.loads(line)
                table.add_row(
                    entry.get("timestamp", "?"),
                    entry.get("from", "?"),
                    entry.get("to", "?"),
                    entry.get("by", "?"),
                )
            except json.JSONDecodeError:
                table.add_row("?", "?", "?", line[:40])

        console.print(table)

    session.close()


@app.command(name="template-stats")
def template_stats(
    compare: bool = typer.Option(False, "--compare", help="Show connection request comparison"),
    trends: bool = typer.Option(False, "--trends", help="Show weekly trends"),
    export: str = typer.Option(None, "--export", help="Export full report to file"),
):
    """Show template performance analytics."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.template_analytics import TemplateAnalytics

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    analytics = TemplateAnalytics(session)

    if export:
        report = analytics.export_report()
        Path(export).write_text(report)
        console.print(f"[green]Report exported to {export}[/green]")
        session.close()
        return

    stats = analytics.get_template_stats()
    if stats:
        table = Table(title="Template Performance")
        table.add_column("Template", style="bold")
        table.add_column("Drafted", justify="right")
        table.add_column("Sent", justify="right")
        table.add_column("Responded", justify="right")
        table.add_column("Rate", justify="right")
        table.add_column("Avg Chars", justify="right")
        for s in stats:
            table.add_row(
                s["template"], str(s["total_drafted"]), str(s["total_sent"]),
                str(s["total_responded"]), f"{s['response_rate']}%",
                str(s["avg_char_count"]),
            )
        console.print(table)
    else:
        console.print("[yellow]No outreach data available.[/yellow]")

    if compare:
        comp = analytics.get_template_comparison()
        console.print(f"\n[bold]Best:[/bold] {comp['best_template']}")
        console.print(f"[bold]Worst:[/bold] {comp['worst_template']}")
        console.print(f"[bold]Recommendation:[/bold] {comp['recommendation']}")

    if trends:
        trend_data = analytics.get_weekly_trends()
        if trend_data:
            table = Table(title="Weekly Trends")
            table.add_column("Week", style="bold")
            table.add_column("Sent", justify="right")
            table.add_column("Responded", justify="right")
            table.add_column("Rate", justify="right")
            table.add_column("Top Template")
            for t in trend_data:
                table.add_row(
                    t["week_start"], str(t["total_sent"]), str(t["total_responded"]),
                    f"{t['rate']}%", t["top_template"] or "N/A",
                )
            console.print(table)

    session.close()


@app.command(name="promote-portals")
def promote_portals(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    log: bool = typer.Option(False, "--log", help="Show detailed change log"),
):
    """Auto-promote/demote portals in afternoon rescan schedule."""
    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.auto_promotion import PortalAutoPromoter

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    promoter = PortalAutoPromoter(session)
    evaluation = promoter.evaluate_promotions()
    changes = promoter.apply_changes(dry_run=dry_run)

    mode = " (DRY RUN)" if dry_run else ""
    console.print(f"\n[bold]Portal Auto-Promotion{mode}[/bold]")
    console.print(f"  Promotions: {len(evaluation['promotions'])}")
    console.print(f"  Demotions: {len(evaluation['demotions'])}")
    console.print(f"  Unchanged: {len(evaluation['unchanged'])}")

    if changes["added"]:
        console.print(f"\n[green]Added to rescan:[/green] {', '.join(changes['added'])}")
    if changes["removed"]:
        console.print(f"[red]Removed from rescan:[/red] {', '.join(changes['removed'])}")

    console.print(f"\n[bold]Current afternoon list:[/bold] {', '.join(changes['current_list'])}")

    if log:
        console.print(f"\n{promoter.get_change_log()}")

    session.close()


@app.command(name="outreach-transition")
def outreach_transition(
    company: str = typer.Argument(help="Company name"),
    stage: str = typer.Argument(help="New stage (Sent, Responded, No Answer, Interview, Declined)"),
    check_only: bool = typer.Option(False, "--check-only", help="Only check if transition is valid"),
):
    """Transition outreach stage with validation."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.state_machine import InvalidTransitionError, OutreachStateMachine

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    sm = OutreachStateMachine(session)

    try:
        if check_only:
            can = sm.can_transition(company, stage)
            available = sm.get_available_transitions(company)
            status = "[green]VALID[/green]" if can else "[red]INVALID[/red]"
            console.print(f"Transition to '{stage}': {status}")
            console.print(f"Available transitions: {', '.join(available)}")
        else:
            record = sm.transition(company, stage)
            console.print(f"[green]Transitioned {company} → {stage}[/green]")
            trail = sm.get_audit_trail(company)
            if trail:
                console.print(f"  Audit trail: {len(trail)} entries")
    except InvalidTransitionError as e:
        console.print(f"[red]Invalid transition:[/red] {e}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")

    session.close()


@app.command(name="log-response")
def log_response(
    company: str = typer.Argument(help="Company name"),
    text: str = typer.Option("", "--text", help="Response text"),
    classify: str = typer.Option(None, "--classify", help="Classification (POSITIVE, NEUTRAL, NEGATIVE, REFERRAL, AUTO_REPLY)"),
):
    """Log a LinkedIn response with classification."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.response_tracker import ResponseTracker

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    tracker = ResponseTracker(session)
    result = tracker.log_response(company, text, classification=classify)

    console.print(f"[green]Response logged for {company}[/green]")
    console.print(f"  Classification: {result['classification']}")
    console.print(f"  Next action: {result['next_action']}")
    if result["response_time_days"] is not None:
        console.print(f"  Response time: {result['response_time_days']} days")

    summary = tracker.get_response_summary()
    console.print(f"\n[bold]Total responses: {summary['total_responses']}[/bold]")
    for cls_name, count in summary["by_classification"].items():
        if count > 0:
            console.print(f"  {cls_name}: {count}")

    session.close()


@app.command(name="ab-test")
def ab_test(
    create: str = typer.Option(None, "--create", help="Create experiment with this name"),
    variants: str = typer.Option("connection_request_a,connection_request_b", "--variants", help="Comma-separated variant names"),
    results_name: str = typer.Option(None, "--results", help="Show results for experiment"),
    list_all: bool = typer.Option(False, "--list", help="List all experiments"),
):
    """Manage A/B template experiments."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.ab_testing import ABTestManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    manager = ABTestManager(session)

    if create:
        variant_list = [v.strip() for v in variants.split(",")]
        result = manager.create_experiment(create, variant_list)
        console.print(f"[green]Created experiment '{create}'[/green]")
        console.print(f"  ID: {result['experiment_id']}")
        console.print(f"  Variants: {result['variants']}")
    elif results_name:
        try:
            result = manager.get_experiment_results(results_name)
            table = Table(title=f"A/B Test: {results_name}")
            table.add_column("Variant", style="bold")
            table.add_column("Assigned", justify="right")
            table.add_column("Sent", justify="right")
            table.add_column("Responded", justify="right")
            table.add_column("Rate", justify="right")
            for v in result["variants"]:
                table.add_row(
                    v["template"], str(v["assigned"]), str(v["sent"]),
                    str(v["responded"]), f"{v['response_rate']}%",
                )
            console.print(table)
            console.print(f"Winner: {result['winner'] or 'N/A'}")
            console.print(f"Significant: {'Yes' if result['is_significant'] else 'No'}")
        except KeyError as e:
            console.print(f"[red]{e}[/red]")
    elif list_all:
        experiments = manager.list_experiments()
        if experiments:
            table = Table(title="A/B Experiments")
            table.add_column("Name", style="bold")
            table.add_column("Variants")
            table.add_column("Allocation")
            table.add_column("Assignments", justify="right")
            table.add_column("Status")
            for exp in experiments:
                table.add_row(
                    exp["name"], ", ".join(exp["variants"]),
                    exp["allocation"], str(exp["total_assignments"]),
                    exp["status"],
                )
            console.print(table)
        else:
            console.print("[yellow]No experiments created yet.[/yellow]")
    else:
        console.print("[yellow]Use --create, --results, or --list[/yellow]")

    session.close()


@app.command(name="email-fallback")
def email_fallback(
    threshold: int = typer.Option(14, "--threshold", help="Days before considering stale"),
    batch: bool = typer.Option(False, "--batch", help="Prepare email drafts for all stale connections"),
    status: bool = typer.Option(False, "--status", help="Show email outreach status"),
):
    """Email follow-ups for stale LinkedIn connections."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.email_outreach import EmailOutreach

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    email = EmailOutreach(session)

    if status:
        st = email.get_email_status()
        console.print(f"\n[bold]Email Outreach Status[/bold]")
        console.print(f"  Stale connections: {st['total_stale']}")
        console.print(f"  With email: {st['with_email']}")
        console.print(f"  Without email: {st['without_email']}")
        console.print(f"  Drafts prepared: {st['drafts_prepared']}")
    elif batch:
        result = email.batch_prepare_emails(threshold_days=threshold)
        console.print(f"\n[bold]Email Fallback — Batch Prepare[/bold]")
        console.print(f"  Total stale: {result['total_stale']}")
        console.print(f"  Drafts prepared: {len(result['drafts'])}")
        console.print(f"  Skipped (no email): {result['skipped_no_email']}")
        for draft in result["drafts"][:5]:
            console.print(f"\n  [bold]{draft['contact']} at {draft['company']}[/bold]")
            console.print(f"  Subject: {draft['subject']}")
    else:
        stale = email.find_stale_connections(threshold_days=threshold)
        if stale:
            table = Table(title=f"Stale Connections (>{threshold} days)")
            table.add_column("Company", style="bold")
            table.add_column("Contact")
            table.add_column("Days", justify="right")
            table.add_column("Email")
            for s in stale:
                table.add_row(
                    s["company_name"], s["contact_name"],
                    str(s["days_since_sent"]),
                    s["contact_email"] or "[yellow]N/A[/yellow]",
                )
            console.print(table)
        else:
            console.print(f"[green]No stale connections older than {threshold} days.[/green]")

    session.close()


@app.command(name="sync-notion-full")
def sync_notion_full(
    strategy: str = typer.Option("NEWEST_WINS", "--strategy", help="Conflict strategy: LOCAL_WINS, NOTION_WINS, NEWEST_WINS"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect conflicts without merging"),
):
    """Bidirectional Notion sync with conflict resolution."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session, init_db
    from src.integrations.notion_bidirectional import NotionBidirectionalSync

    api_key = os.getenv("NOTION_API_KEY", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "0c412604-a409-47ab-8c04-29f112c2c683")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    sync = NotionBidirectionalSync(
        api_key=api_key or "dry-run",
        database_id=db_id,
        session=session,
    )

    result = asyncio.run(sync.full_sync(strategy=strategy, dry_run=dry_run))

    mode = " (DRY RUN)" if dry_run else ""
    console.print(f"\n[bold]Bidirectional Notion Sync{mode}[/bold]")
    console.print(f"  Pulled: {result['pulled']}")
    console.print(f"  Conflicts found: {result['conflicts_found']}")
    console.print(f"  Merged: {result['merged']}")
    console.print(f"  Strategy: {result['strategy_used']}")
    pushed = result.get("pushed", 0)
    push_errors = result.get("push_errors", [])
    console.print(f"  Pushed to Notion: {pushed}")
    if push_errors:
        console.print(f"  [yellow]Push errors: {len(push_errors)}[/yellow]")
        for err in push_errors[:5]:
            console.print(f"    - {err}")

    session.close()


@app.command(name="auto-followup")
def auto_followup(
    max_drafts: int = typer.Option(10, "--max-drafts", help="Maximum drafts to create"),
):
    """Auto-create follow-up drafts for overdue outreach items."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.followup_manager import FollowUpManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    mgr = FollowUpManager(session)
    result = mgr.auto_draft_followups(max_drafts=max_drafts)

    console.print(f"\n[bold]Auto Follow-Up Drafts[/bold]")
    console.print(f"  Drafted: {result['drafted']}")
    console.print(f"  Skipped (duplicates): {result['skipped_duplicates']}")
    if result["errors"]:
        console.print(f"  [yellow]Errors: {len(result['errors'])}[/yellow]")
        for err in result["errors"]:
            console.print(f"    - {err}")

    # Also show queued follow-ups
    queued = mgr.queue_followups()
    if queued:
        console.print(f"\n  [cyan]{len(queued)} follow-up(s) ready for send queue:[/cyan]")
        for q in queued[:10]:
            console.print(f"    - {q['company_name']} ({q['sequence_step']})")

    session.close()


@app.command(name="classify-response")
def classify_response(
    text: str = typer.Argument(..., help="Response text to classify"),
):
    """Classify a response text using the v2 score-based classifier."""
    from src.outreach.response_tracker import ResponseTracker, _NEXT_ACTIONS

    classification = ResponseTracker.classify_response(text)
    next_action = _NEXT_ACTIONS.get(classification, "Unknown")

    console.print(f"\n[bold]Response Classification[/bold]")
    console.print(f"  Text: {text[:100]}{'...' if len(text) > 100 else ''}")
    console.print(f"  Classification: [bold]{classification}[/bold]")
    console.print(f"  Next action: {next_action}")


@app.command(name="portal-history")
def portal_history(
    limit: int = typer.Option(20, "--limit", help="Max entries to show"),
):
    """Show promotion/demotion history for portals."""
    from src.db.database import get_session, init_db
    from src.pipeline.auto_promotion import PortalAutoPromoter

    engine = init_db()
    session = get_session(engine)
    promoter = PortalAutoPromoter(session)
    history = promoter.get_change_history(limit=limit)

    if not history:
        console.print("[dim]No promotion history found.[/dim]")
        return

    table = Table(title=f"Portal Promotion History (last {limit})")
    table.add_column("Timestamp", style="dim")
    table.add_column("Action")
    table.add_column("Portal")
    table.add_column("Reason")

    for entry in history:
        action_color = {"promote": "green", "demote": "yellow", "force_demote": "red"}.get(entry["action"], "white")
        table.add_row(
            entry.get("timestamp", "")[:19],
            f"[{action_color}]{entry['action']}[/{action_color}]",
            entry.get("portal", ""),
            entry.get("reason", ""),
        )
    console.print(table)
    session.close()


@app.command(name="zero-yield")
def zero_yield(
    threshold: int = typer.Option(5, "--threshold", help="Minimum scans to check"),
):
    """Detect portals with zero new companies in recent scans."""
    from src.db.database import get_session, init_db
    from src.pipeline.health_monitor import HealthMonitor

    engine = init_db()
    session = get_session(engine)
    monitor = HealthMonitor(session)
    portals = monitor.detect_zero_yield(threshold=threshold)

    if not portals:
        console.print("[green]No zero-yield portals detected.[/green]")
    else:
        console.print(f"[yellow]Zero-yield portals (0 new in last {threshold} scans):[/yellow]")
        for p in portals:
            console.print(f"  - {p}")
    session.close()


@app.command(name="alerts")
def alerts_cmd():
    """Show actionable portal health alerts."""
    from src.db.database import get_session, init_db
    from src.pipeline.health_monitor import HealthMonitor

    engine = init_db()
    session = get_session(engine)
    monitor = HealthMonitor(session)
    alerts = monitor.get_actionable_alerts()

    if not alerts:
        console.print("[green]No actionable alerts.[/green]")
        session.close()
        return

    table = Table(title="Portal Health Alerts")
    table.add_column("Portal")
    table.add_column("Type")
    table.add_column("Severity")
    table.add_column("Action")
    table.add_column("Details", max_width=50)

    for a in alerts:
        sev_color = "red" if a["severity"] == "critical" else "yellow"
        table.add_row(
            a["portal"],
            a["alert_type"],
            f"[{sev_color}]{a['severity']}[/{sev_color}]",
            a["recommended_action"],
            a["details"],
        )
    console.print(table)
    session.close()


@app.command(name="domain-match")
def domain_match(
    company: str = typer.Argument(..., help="Company name to match domain"),
):
    """Show which experience domain best matches a company."""
    from src.db.database import get_session, init_db
    from src.outreach.personalizer import EXPERIENCE_MAP, OutreachPersonalizer

    engine = init_db()
    session = get_session(engine)
    personalizer = OutreachPersonalizer()

    from src.db.orm import CompanyORM
    company_orm = session.query(CompanyORM).filter(CompanyORM.name.ilike(company)).first()
    if not company_orm:
        console.print(f"[red]Company '{company}' not found in database.[/red]")
        session.close()
        return

    domain = personalizer._match_domain(company_orm)
    exp = EXPERIENCE_MAP[domain]
    console.print(f"\n[bold]{company_orm.name}[/bold] -> Domain: [cyan]{domain}[/cyan]")
    console.print(f"  Experience: {exp['relevant_experience']}")
    console.print(f"  Metric: {exp['metric']}")
    console.print(f"  Value prop: {exp['value_prop']}")
    session.close()


@app.command(name="template-export")
def template_export(
    file: str = typer.Argument(..., help="Output CSV file path"),
):
    """Export template analytics to CSV."""
    from src.db.database import get_session, init_db
    from src.outreach.template_analytics import TemplateAnalytics

    engine = init_db()
    session = get_session(engine)
    analytics = TemplateAnalytics(session)
    count = analytics.export_csv(file)
    console.print(f"[green]Exported {count} template stats to {file}[/green]")
    session.close()


@app.command(name="update-contact-score")
def update_contact_score(
    contact: str = typer.Argument(..., help="Contact name"),
    company: str = typer.Argument(..., help="Company name"),
    classification: str = typer.Argument(..., help="POSITIVE, NEGATIVE, NEUTRAL, REFERRAL, or AUTO_REPLY"),
):
    """Update a contact's score based on response classification."""
    from src.db.database import get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = init_db()
    session = get_session(engine)
    researcher = ContactResearcher(session)
    result = researcher.update_score_from_response(contact, company, classification.upper())

    if result:
        console.print(f"[green]Updated {contact} at {company}: score = {result.contact_score}[/green]")
    else:
        console.print(f"[red]Contact '{contact}' at '{company}' not found.[/red]")
    session.close()


@app.command(name="gmail-drafts")
def gmail_drafts(
    batch: bool = typer.Option(False, "--batch", help="Prepare all stale drafts"),
    list_drafts: bool = typer.Option(False, "--list", help="List pending drafts"),
    threshold: int = typer.Option(14, "--threshold", help="Days since last contact"),
):
    """Prepare Gmail drafts from stale outreach connections."""
    from src.integrations.gmail_bridge import GmailBridge
    from src.db.database import get_session, init_db

    if list_drafts:
        bridge = GmailBridge.__new__(GmailBridge)
        pending = bridge.load_pending_drafts()
        if not pending:
            console.print("[yellow]No pending drafts.[/yellow]")
            return
        table = Table(title=f"Pending Gmail Drafts ({len(pending)})")
        table.add_column("To", style="bold")
        table.add_column("Subject")
        table.add_column("Body Preview")
        for d in pending:
            body_preview = (d.get("body", "")[:60] + "...") if len(d.get("body", "")) > 60 else d.get("body", "")
            table.add_row(d.get("to", "—"), d.get("subject", "—"), body_preview)
        console.print(table)
        return

    engine = init_db()
    session = get_session(engine)
    bridge = GmailBridge(session)
    drafts = bridge.prepare_drafts(threshold_days=threshold)
    if not drafts:
        console.print("[yellow]No stale connections to draft.[/yellow]")
        session.close()
        return
    if batch:
        count = bridge.save_drafts(drafts)
        console.print(f"[green]Saved {count} drafts to data/gmail_drafts.json[/green]")
    else:
        console.print(f"[cyan]Found {len(drafts)} drafts. Use --batch to save.[/cyan]")
        for d in drafts[:5]:
            console.print(f"  • {d.get('to', '—')}: {d.get('subject', '—')}")
    session.close()


@app.command(name="enrich-emails")
def enrich_emails(
    company: str = typer.Option("", help="Enrich contacts for a specific company"),
    batch: bool = typer.Option(False, "--batch", help="Batch enrich all contacts"),
    limit: int = typer.Option(50, "--limit", help="Max contacts to enrich"),
):
    """Enrich contact emails via Hunter.io."""
    from src.integrations.email_enrichment import EmailEnricher
    from src.db.database import get_session, init_db

    engine = init_db()
    session = get_session(engine)
    enricher = EmailEnricher(session)

    if company:
        from src.db.orm import ContactORM
        contacts = session.query(ContactORM).filter(
            ContactORM.company_name.ilike(f"%{company}%"),
            (ContactORM.email.is_(None)) | (ContactORM.email == ""),
        ).all()
        if not contacts:
            console.print(f"[yellow]No contacts without email for '{company}'.[/yellow]")
            session.close()
            return
        for c in contacts:
            result = enricher.enrich_contact(c.contact_name, c.company_name)
            status = f"[green]{result}[/green]" if result else "[red]Not found[/red]"
            console.print(f"  {c.contact_name}: {status}")
    elif batch:
        results = enricher.batch_enrich(limit=limit)
        console.print(
            f"[green]Enriched: {results['enriched']}[/green] | "
            f"[red]Failed: {results['failed']}[/red] | "
            f"Skipped: {results['skipped']}"
        )
    else:
        console.print("[yellow]Use --company or --batch to enrich contacts.[/yellow]")
    session.close()


@app.command(name="classify-llm")
def classify_llm(
    text: str = typer.Argument(..., help="Response text to classify"),
    company: str = typer.Option("", "--company", help="Company context for better classification"),
):
    """Classify a response using LLM (falls back to keyword classifier)."""
    from src.outreach.llm_classifier import get_classifier

    classifier = get_classifier()
    if classifier:
        result = classifier.classify(text, company_context=company)
        console.print(f"[bold]Classification:[/bold] {result.classification}")
        console.print(f"[bold]Confidence:[/bold] {result.confidence:.0%}")
        console.print(f"[bold]Reasoning:[/bold] {result.reasoning}")
        console.print(f"[bold]Action:[/bold] {result.suggested_action}")
        console.print("[dim]Source: LLM (Claude)[/dim]")
    else:
        from src.outreach.response_tracker import ResponseTracker
        classification = ResponseTracker.classify_response(text)
        console.print(f"[bold]Classification:[/bold] {classification}")
        console.print("[dim]Source: keyword fallback (no ANTHROPIC_API_KEY)[/dim]")


@app.command(name="schedule-interview")
def schedule_interview(
    company: str = typer.Argument(..., help="Company name"),
    contact: str = typer.Argument(..., help="Contact name"),
    days_out: int = typer.Option(3, "--days-out", help="Days from now for follow-up"),
):
    """Create a calendar event payload for interview follow-up."""
    from src.integrations.calendar_bridge import CalendarBridge

    bridge = CalendarBridge()
    event = bridge.create_followup_event(company, contact, days_out=days_out)
    console.print(f"[green]Calendar event prepared:[/green]")
    console.print(f"  Summary: {event['summary']}")
    console.print(f"  Start: {event['start']['dateTime']}")
    console.print(f"  End: {event['end']['dateTime']}")
    console.print(f"  Description: {event.get('description', '')[:100]}")


@app.command(name="db-migrate")
def db_migrate(
    upgrade: bool = typer.Option(False, "--upgrade", help="Run pending migrations"),
    current: bool = typer.Option(False, "--current", help="Show current revision"),
    generate: str = typer.Option("", "--generate", help="Generate new migration with message"),
):
    """Manage Alembic database migrations."""
    import subprocess

    if current:
        result = subprocess.run(
            ["alembic", "current"], capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        console.print(result.stdout or result.stderr)
    elif upgrade:
        result = subprocess.run(
            ["alembic", "upgrade", "head"], capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        if result.returncode == 0:
            console.print("[green]Migration complete.[/green]")
        else:
            console.print(f"[red]Migration failed:[/red]\n{result.stderr}")
    elif generate:
        result = subprocess.run(
            ["alembic", "revision", "--autogenerate", "-m", generate],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        if result.returncode == 0:
            console.print(f"[green]Generated migration: {generate}[/green]")
        else:
            console.print(f"[red]Generation failed:[/red]\n{result.stderr}")
    else:
        console.print("[yellow]Use --upgrade, --current, or --generate MSG.[/yellow]")


@app.command(name="notion-incremental")
def notion_incremental(
    reset: bool = typer.Option(False, "--reset", help="Reset sync state"),
    status: bool = typer.Option(False, "--status", help="Show sync state"),
):
    """Manage incremental Notion sync."""
    from src.integrations.notion_incremental import NotionSyncState

    state = NotionSyncState()
    if reset:
        state.reset()
        console.print("[green]Notion sync state reset.[/green]")
    elif status:
        info = state.get_status()
        last = info.get("last_sync")
        if last:
            console.print(f"[bold]Last sync:[/bold] {last}")
        else:
            console.print("[yellow]No sync recorded yet.[/yellow]")
    else:
        console.print("[yellow]Use --reset or --status.[/yellow]")


@app.command(name="theme")
def theme_cmd(
    set_theme: str = typer.Option("", "--set", help="Set theme: light or dark"),
):
    """Switch dashboard theme."""
    import os

    if set_theme:
        if set_theme not in ("light", "dark"):
            console.print("[red]Theme must be 'light' or 'dark'.[/red]")
            return
        os.environ["DASHBOARD_THEME"] = set_theme
        console.print(f"[green]Dashboard theme set to '{set_theme}' for this session.[/green]")
        console.print("[dim]Set DASHBOARD_THEME env var for persistence.[/dim]")
    else:
        current = os.environ.get("DASHBOARD_THEME", "light")
        console.print(f"[bold]Current theme:[/bold] {current}")


if __name__ == "__main__":
    app()

"""Pipeline-related CLI commands: run-pipeline, daily-run, enrich, archive, promote-portals, seed."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command(name="run-pipeline")
def run_pipeline(
    skip_validate: bool = typer.Option(False, help="Skip validation step"),
    skip_score: bool = typer.Option(False, help="Skip scoring step"),
    h1b_verify: bool = typer.Option(False, "--h1b", help="Run H1B verification step"),
    semantic: bool = typer.Option(False, help="Include semantic scoring"),
):
    """Run full pipeline: validate -> h1b -> score all companies."""
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


@app.command(name="daily-run")
def daily_run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run (no Notion API calls)"),
    skip_scan: bool = typer.Option(False, "--skip-scan", help="Skip scan stage"),
    skip_enrich: bool = typer.Option(False, "--skip-enrich", help="Skip enrichment stage"),
):
    """Run full daily pipeline: scan -> enrich -> score -> queue -> followup -> sync."""
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
            console.print(f"  {d}")

    if audit_report["borderline"]:
        console.print("\n[yellow bold]Borderline:[/yellow bold]")
        for b in audit_report["borderline"]:
            console.print(f"  {b}")

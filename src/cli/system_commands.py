"""System-level CLI commands: audit, dashboard, stats, priority-report, completeness-report, db-migrate, theme, scheduler-start."""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer()
console = Console()


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
    console.print("[bold]Launching dashboard...[/bold]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path)])


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


def _orm_to_company(orm: "CompanyORM") -> "Company":
    """Convert a CompanyORM row to a Company dataclass for quality gate logic."""
    from src.config.enums import (
        CompanyStage,
        FundingStage,
        H1BStatus,
        SourcePortal,
        Tier,
        ValidationResult,
    )
    from src.models.company import Company

    def _safe_enum(enum_cls, value, default):
        try:
            return enum_cls(value)
        except (ValueError, KeyError):
            return default

    return Company(
        id=orm.id,
        name=orm.name or "",
        description=orm.description or "",
        hq_location=orm.hq_location or "",
        employees=orm.employees,
        employees_range=orm.employees_range or "",
        funding_stage=_safe_enum(FundingStage, orm.funding_stage, FundingStage.UNKNOWN),
        funding_amount=orm.funding_amount or "",
        total_raised=orm.total_raised or "",
        valuation=orm.valuation or "",
        founded_year=orm.founded_year,
        website=orm.website or "",
        careers_url=orm.careers_url or "",
        linkedin_url=orm.linkedin_url or "",
        is_ai_native=bool(orm.is_ai_native),
        ai_product_description=orm.ai_product_description or "",
        tier=_safe_enum(Tier, orm.tier, Tier.TIER_5),
        source_portal=_safe_enum(SourcePortal, orm.source_portal, SourcePortal.MANUAL),
        h1b_status=_safe_enum(H1BStatus, orm.h1b_status, H1BStatus.UNKNOWN),
        h1b_source=orm.h1b_source or "",
        h1b_details=orm.h1b_details or "",
        fit_score=orm.fit_score,
        stage=_safe_enum(CompanyStage, orm.stage, CompanyStage.TO_APPLY),
        validation_result=_safe_enum(ValidationResult, orm.validation_result, None) if orm.validation_result else None,
        validation_notes=orm.validation_notes or "",
        differentiators=[d.strip() for d in (orm.differentiators or "").split("|") if d.strip()],
        role=orm.role or "",
        role_url=orm.role_url or "",
        salary_range=orm.salary_range or "",
        notes=orm.notes or "",
        hiring_manager=orm.hiring_manager or "",
        hiring_manager_linkedin=orm.hiring_manager_linkedin or "",
        why_fit=orm.why_fit or "",
        best_stats=orm.best_stats or "",
        action=orm.action or "",
        is_disqualified=bool(orm.is_disqualified),
        disqualification_reason=orm.disqualification_reason or "",
        needs_review=bool(orm.needs_review),
        data_completeness=orm.data_completeness or 0.0,
    )


@app.command(name="completeness-report")
def completeness_report(
    min_score: float = typer.Option(0.0, "--min-score", help="Show only companies below this completeness threshold (0.0–1.0)"),
):
    """Show data completeness report across all companies."""
    from src.cli._db import db_session
    from src.db.orm import CompanyORM
    from src.pipeline.quality_gates import get_quality_report

    with db_session() as session:
        orm_rows = session.query(CompanyORM).all()
        companies = [_orm_to_company(row) for row in orm_rows]

        report = get_quality_report(companies)

        # -- Summary panel --
        summary = (
            f"[bold]Total Companies:[/bold] {report.total_companies}\n"
            f"[bold]Avg Completeness:[/bold] {report.avg_completeness:.1%}"
        )
        console.print(Panel(summary, title="Completeness Summary", border_style="green"))

        # -- Bucket table --
        bucket_table = Table(title="Completeness Distribution")
        bucket_table.add_column("Range", style="bold")
        bucket_table.add_column("Count", justify="right")
        bucket_table.add_row("0 - 25%", str(report.bucket_0_25))
        bucket_table.add_row("25 - 50%", str(report.bucket_25_50))
        bucket_table.add_row("50 - 75%", str(report.bucket_50_75))
        bucket_table.add_row("75 - 100%", str(report.bucket_75_100))
        console.print(bucket_table)

        # -- Top 10 missing fields --
        if report.most_common_missing:
            missing_table = Table(title="Top 10 Missing Fields")
            missing_table.add_column("#", justify="right")
            missing_table.add_column("Field", style="bold")
            missing_table.add_column("Missing In", justify="right")
            for i, (field_name, count) in enumerate(report.most_common_missing[:10], 1):
                missing_table.add_row(str(i), field_name, str(count))
            console.print(missing_table)

        # -- Optional: show companies below threshold --
        if min_score > 0.0:
            low_companies = []
            for c in companies:
                result = c.calculate_completeness()
                if result.score < min_score:
                    low_companies.append((c.name, result.score, result.missing_fields))
            if low_companies:
                low_table = Table(title=f"Companies Below {min_score:.0%} Completeness")
                low_table.add_column("#", justify="right")
                low_table.add_column("Company", style="bold")
                low_table.add_column("Score", justify="right")
                low_table.add_column("Missing Fields")
                for i, (name, score, missing) in enumerate(sorted(low_companies, key=lambda x: x[1]), 1):
                    low_table.add_row(
                        str(i),
                        name,
                        f"{score:.0%}",
                        ", ".join(missing[:5]) + ("..." if len(missing) > 5 else ""),
                    )
                console.print(low_table)
            else:
                console.print(f"[green]All companies meet the {min_score:.0%} threshold.[/green]")


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
        console.print("\n[bold]Priority Matrix[/bold]")
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


@app.command(name="scheduler-start")
def scheduler_start_cmd(
    daemon: bool = typer.Option(False, "--daemon", help="Run scheduler in background"),
    dry_run: bool = typer.Option(False, "--dry-run", help="List scheduled jobs and exit"),
):
    """Start the outreach scheduler or list scheduled jobs."""
    from src.pipeline.scheduler import ScanScheduler

    scheduler = ScanScheduler()

    if dry_run:
        console.print("\n[bold]Scheduled Jobs:[/bold]\n")
        jobs = scheduler.get_jobs()
        for job in jobs:
            console.print(f"  {job['name']}: {job['cron']} — {job['description']}")
        console.print(f"\n  Total: {len(jobs)} jobs")
        return

    if daemon:
        import os
        import subprocess
        import sys

        os.makedirs("data", exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.pipeline.scheduler"],
            stdout=open("data/scheduler.log", "a"),
            stderr=open("data/scheduler.log", "a"),
            start_new_session=True,
        )
        pid_path = "data/scheduler.pid"
        with open(pid_path, "w") as f:
            f.write(str(proc.pid))
        console.print(f"[green]Scheduler started in background (PID: {proc.pid})[/green]")
        console.print(f"  Log: data/scheduler.log | PID file: {pid_path}")
        return

    console.print("[bold]Starting scheduler in foreground (Ctrl+C to stop)...[/bold]")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped.[/yellow]")

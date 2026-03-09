"""System-level CLI commands: audit, dashboard, stats, priority-report, db-migrate, theme, scheduler-start."""

from pathlib import Path

import typer
from rich.console import Console
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
    console.print(f"[bold]Launching dashboard...[/bold]")
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

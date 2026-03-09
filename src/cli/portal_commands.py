"""Portal health and scoring CLI commands."""

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


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

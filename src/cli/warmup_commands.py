"""Warm-up sequence CLI commands for LinkedIn pre-engagement tracking."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command(name="warmup-status")
def warmup_status(
    company: str = typer.Argument(None, help="Company name (optional, shows all if omitted)"),
):
    """Show warm-up status for a company or all contacts."""
    from src.db.database import get_engine, get_session, init_db
    from src.db.orm import CompanyORM
    from src.outreach.warmup_tracker import WarmUpTracker

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    tracker = WarmUpTracker(session)

    if company:
        # Look up company by name (partial match)
        comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()
        if not comp:
            console.print(f"[red]Company '{company}' not found in database.[/red]")
            session.close()
            raise typer.Exit(1)

        # Get all warmup sequences for this company
        from src.db.orm import WarmUpSequenceORM

        sequences = (
            session.query(WarmUpSequenceORM)
            .filter(WarmUpSequenceORM.company_id == comp.id)
            .all()
        )

        if not sequences:
            console.print(
                Panel(
                    f"No warm-up sequences found for [bold]{comp.name}[/bold].",
                    title="Warm-Up Status",
                )
            )
            session.close()
            return

        table = Table(title=f"Warm-Up Status: {comp.name}")
        table.add_column("Contact", style="bold")
        table.add_column("State")
        table.add_column("Completed Actions")
        table.add_column("Remaining Actions")
        table.add_column("Action Count", justify="right")
        table.add_column("Ready?")

        for seq in sequences:
            status = tracker.get_status(comp.id, seq.contact_name)
            state_style = {
                "PENDING": "dim",
                "WARMING": "yellow",
                "READY": "green",
                "SENT": "blue",
            }.get(status["state"], "")
            ready_str = "[green]YES[/green]" if status["is_ready"] else "[dim]no[/dim]"

            table.add_row(
                status["contact_name"],
                f"[{state_style}]{status['state']}[/{state_style}]",
                ", ".join(status["completed_actions"]) or "-",
                ", ".join(status["remaining_actions"]) or "-",
                str(status["action_count"]),
                ready_str,
            )

        console.print(table)
    else:
        # Show all warmup sequences across all companies
        from src.db.orm import WarmUpSequenceORM

        sequences = session.query(WarmUpSequenceORM).all()

        if not sequences:
            console.print(
                Panel(
                    "No warm-up sequences found. Use [bold]warmup-record[/bold] to start tracking.",
                    title="Warm-Up Status",
                )
            )
            session.close()
            return

        table = Table(title="All Warm-Up Sequences")
        table.add_column("Company", style="bold")
        table.add_column("Contact")
        table.add_column("State")
        table.add_column("Actions Done", justify="right")

        for seq in sequences:
            comp = (
                session.query(CompanyORM)
                .filter(CompanyORM.id == seq.company_id)
                .first()
            )
            company_name = comp.name if comp else f"ID:{seq.company_id}"
            state_style = {
                "PENDING": "dim",
                "WARMING": "yellow",
                "READY": "green",
                "SENT": "blue",
            }.get(seq.state, "")

            status = tracker.get_status(seq.company_id, seq.contact_name)
            table.add_row(
                company_name,
                seq.contact_name,
                f"[{state_style}]{seq.state}[/{state_style}]",
                str(status["action_count"]),
            )

        console.print(table)

    session.close()


@app.command(name="warmup-next")
def warmup_next(
    limit: int = typer.Option(10, help="Max actions to show"),
):
    """Show recommended daily warm-up actions."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.warmup_tracker import WarmUpTracker

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    tracker = WarmUpTracker(session)
    actions = tracker.get_daily_actions()

    # Apply limit
    actions = actions[:limit]

    if not actions:
        console.print(
            Panel(
                "No warm-up actions needed today. All sequences are READY or SENT.",
                title="Daily Warm-Up Actions",
            )
        )
    else:
        table = Table(title=f"Recommended Warm-Up Actions (up to {limit})")
        table.add_column("Company", style="bold")
        table.add_column("Contact")
        table.add_column("Recommended Action", style="cyan")
        table.add_column("Notes")

        for action in actions:
            table.add_row(
                action["company_name"],
                action["contact_name"],
                action["recommended_action"],
                action["reason"],
            )

        console.print(table)

    # Show count of READY contacts
    ready = tracker.get_ready_contacts()
    if ready:
        console.print(
            f"\n[bold green]{len(ready)} contact(s) ready for outreach![/bold green]"
        )

    session.close()


@app.command(name="warmup-record")
def warmup_record(
    company: str = typer.Argument(..., help="Company name"),
    contact: str = typer.Argument(..., help="Contact name"),
    action: str = typer.Argument(
        ..., help="Action type: profile_view, like_post, comment, connect, message"
    ),
    notes: str = typer.Option(None, help="Optional notes"),
):
    """Record a warm-up action for a contact."""
    from src.db.database import get_engine, get_session, init_db
    from src.db.orm import CompanyORM
    from src.outreach.warmup_tracker import (
        InvalidWarmUpTransitionError,
        WarmUpAction,
        WarmUpTracker,
    )

    # Validate action enum value
    action_upper = action.upper()
    try:
        warmup_action = WarmUpAction(action_upper)
    except ValueError:
        valid_actions = ", ".join(a.value.lower() for a in WarmUpAction)
        console.print(
            f"[red]Invalid action '{action}'. Valid actions: {valid_actions}[/red]"
        )
        raise typer.Exit(1)

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    # Look up company by name (partial match)
    comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()
    if not comp:
        console.print(f"[red]Company '{company}' not found in database.[/red]")
        session.close()
        raise typer.Exit(1)

    tracker = WarmUpTracker(session)

    try:
        tracker.record_action(comp.id, contact, warmup_action, notes or "")
    except InvalidWarmUpTransitionError as e:
        console.print(f"[red]Cannot record action:[/red] {e}")
        session.close()
        raise typer.Exit(1)

    # Show current state after recording
    status = tracker.get_status(comp.id, contact)
    console.print(
        f"[green]Recorded {warmup_action.value} for {contact} at {comp.name}[/green]"
    )
    console.print(f"  State: [bold]{status['state']}[/bold]")
    console.print(
        f"  Completed: {', '.join(status['completed_actions']) or 'none'}"
    )
    console.print(
        f"  Remaining: {', '.join(status['remaining_actions']) or 'none'}"
    )
    if status["is_ready"]:
        console.print("  [bold green]Contact is READY for outreach![/bold green]")

    session.close()

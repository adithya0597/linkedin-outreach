"""Outreach-related CLI commands.

Consolidated from 19 commands to 10 primary commands.
All old command names preserved as hidden aliases for backward compatibility.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


# ===========================================================================
# 1. draft — Draft outreach messages (single + batch)
# ===========================================================================


@app.command()
def draft(
    company: str = typer.Argument(None, help="Company name"),
    contact: str = typer.Argument(None, help="Contact name"),
    template: str = typer.Option("connection_request_a.j2", help="Template file name"),
    list_templates: bool = typer.Option(False, "--list", help="List available templates"),
    personalize: bool = typer.Option(False, "--personalize", help="Use domain-matched personalization"),
    all_companies: bool = typer.Option(False, "--all", help="Batch draft for all qualifying companies"),
    tier: str = typer.Option(None, "--tier", help="Filter by tier (batch mode)"),
    limit: int = typer.Option(None, "--limit", help="Max companies (batch mode)"),
    types: str = typer.Option("connection_request", "--types", help="Comma-separated message types (batch mode)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show count without creating records (batch mode)"),
):
    """Draft outreach messages using Jinja2 templates.

    Single mode: draft COMPANY CONTACT [--template T] [--personalize]
    Batch mode:  draft --all [--tier T] [--limit N] [--types T] [--dry-run]
    List:        draft --list
    """
    if all_companies:
        _draft_all_impl(tier=tier, limit=limit, types=types, dry_run=dry_run)
        console.print(
            "\n[dim]Next: Run [bold]outreach send[/bold] to queue for delivery[/dim]"
        )
        return

    if list_templates:
        _draft_list_impl()
        return

    _draft_single_impl(company, contact, template, personalize)
    console.print(
        "\n[dim]Next: Run [bold]outreach send[/bold] to queue for delivery[/dim]"
    )


def _draft_list_impl():
    """List available templates."""
    from src.outreach.template_engine import OutreachTemplateEngine

    engine_tmpl = OutreachTemplateEngine()
    console.print("[bold]Available templates:[/bold]")
    for t in engine_tmpl.list_templates():
        console.print(f"  {t}")


def _draft_single_impl(company, contact, template, personalize):
    """Draft a single outreach message."""
    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM, ContactORM
    from src.outreach.template_engine import OutreachTemplateEngine

    engine_tmpl = OutreachTemplateEngine()

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
    console.print(f"\n{'---' * 17}")
    console.print(rendered)
    console.print(f"{'---' * 17}")

    session.close()


def _draft_all_impl(tier, limit, types, dry_run):
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


# Hidden alias for backward compatibility
@app.command(name="draft-all", hidden=True)
def draft_all(
    tier: str = typer.Option(None, help="Filter by tier (e.g. 'Tier 1 - HIGH')"),
    limit: int = typer.Option(None, help="Max companies to draft"),
    types: str = typer.Option("connection_request", help="Comma-separated message types"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show count without creating records"),
):
    """[DEPRECATED] Use 'draft --all' instead."""
    _draft_all_impl(tier=tier, limit=limit, types=types, dry_run=dry_run)


# ===========================================================================
# 2. sequence — Build outreach sequences + auto follow-up
# ===========================================================================


@app.command()
def sequence(
    company: str = typer.Argument(None, help="Company name"),
    contact: str = typer.Argument(None, help="Contact name"),
    start_date: str = typer.Option(None, help="Start date (YYYY-MM-DD), defaults to today"),
    auto_draft: bool = typer.Option(False, "--auto-draft", help="Auto-create follow-up drafts for overdue items"),
    max_drafts: int = typer.Option(10, "--max-drafts", help="Maximum auto-drafts to create"),
):
    """Build outreach sequences and auto-draft follow-ups.

    Sequence: sequence COMPANY CONTACT [--start-date D]
    Auto:     sequence --auto-draft [--max-drafts N]
    """
    if auto_draft:
        _auto_followup_impl(max_drafts)
        return

    if not company or not contact:
        console.print("[red]Both COMPANY and CONTACT are required (or use --auto-draft).[/red]")
        raise typer.Exit(1)

    _sequence_impl(company, contact, start_date)


def _sequence_impl(company, contact, start_date):
    """Build a 14-day outreach sequence with template recommendations."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.batch_engine import BatchOutreachEngine

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    batch = BatchOutreachEngine(session)
    seq = batch.build_sequence(company, contact, start_date)

    if not seq:
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

    for step in seq:
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


def _auto_followup_impl(max_drafts):
    """Auto-create follow-up drafts for overdue outreach items."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.followup_manager import FollowUpManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    mgr = FollowUpManager(session)
    result = mgr.auto_draft_followups(max_drafts=max_drafts)

    console.print("\n[bold]Auto Follow-Up Drafts[/bold]")
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


# Hidden aliases for backward compatibility
@app.command(name="outreach-sequence", hidden=True)
def outreach_sequence(
    company: str = typer.Argument(help="Company name"),
    contact: str = typer.Argument(help="Contact name"),
    start_date: str = typer.Option(None, help="Start date (YYYY-MM-DD), defaults to today"),
):
    """[DEPRECATED] Use 'sequence' instead."""
    _sequence_impl(company, contact, start_date)


@app.command(name="auto-followup", hidden=True)
def auto_followup(
    max_drafts: int = typer.Option(10, "--max-drafts", help="Maximum drafts to create"),
):
    """[DEPRECATED] Use 'sequence --auto-draft' instead."""
    _auto_followup_impl(max_drafts)


# ===========================================================================
# 3. followups — Show overdue and upcoming outreach follow-ups
# ===========================================================================


@app.command()
def followups(
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


# Hidden alias
@app.command(name="outreach-followups", hidden=True)
def outreach_followups(
    days: int = typer.Option(7, help="Look-ahead window in days"),
    overdue_only: bool = typer.Option(False, "--overdue-only", help="Show only overdue follow-ups"),
):
    """[DEPRECATED] Use 'followups' instead."""
    followups(days=days, overdue_only=overdue_only)


# ===========================================================================
# 4. send — Send queue + mark sent
# ===========================================================================


@app.command()
def send(
    company: str | None = typer.Argument(None, help="Company name (for --mark)"),
    step: str | None = typer.Argument(None, help="Sequence step (for --mark)"),
    mark: bool = typer.Option(False, "--mark", help="Mark an outreach step as sent"),
    contact_name: str = typer.Option(None, "--contact", help="Contact name (for --mark)"),
    limit: int = typer.Option(20, "--limit", help="Max sends for today"),
    week_status: bool = typer.Option(False, "--week-status", help="Show weekly rate limit status only"),
):
    """Show daily send queue or mark outreach as sent.

    Queue:     send [--limit N] [--week-status]
    Mark sent: send COMPANY STEP --mark [--contact NAME]
    """
    if mark:
        if not company or not step:
            console.print("[red]COMPANY and STEP are required with --mark.[/red]")
            raise typer.Exit(1)
        _mark_sent_impl(company, step, contact_name)
        console.print(
            "\n[dim]Next: Run [bold]outreach status[/bold] to track responses[/dim]"
        )
        return

    _send_queue_impl(limit, week_status)
    console.print(
        "\n[dim]Next: Run [bold]outreach status[/bold] to track responses[/dim]"
    )


def _send_queue_impl(limit, week_status):
    """Show daily prioritized send queue with rate limiting."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.send_queue import SendQueueManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    mgr = SendQueueManager(session)

    # Always show rate limit status
    status = mgr.get_rate_limit_status()
    console.print("\n[bold]Weekly Rate Limit:[/bold]")
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


def _mark_sent_impl(company, step, contact_name):
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


# Hidden aliases
@app.command(name="send-queue", hidden=True)
def send_queue(
    limit: int = typer.Option(20, help="Max sends for today"),
    week_status: bool = typer.Option(False, "--week-status", help="Show weekly rate limit status only"),
):
    """[DEPRECATED] Use 'send' instead."""
    _send_queue_impl(limit, week_status)


@app.command(name="outreach-mark-sent", hidden=True)
def outreach_mark_sent(
    company: str = typer.Argument(help="Company name"),
    step: str = typer.Argument(help="Sequence step (connection_request, follow_up, etc.)"),
    contact_name: str = typer.Option(None, help="Contact name (optional)"),
):
    """[DEPRECATED] Use 'send COMPANY STEP --mark' instead."""
    _mark_sent_impl(company, step, contact_name)


# ===========================================================================
# 5. respond — Log + classify responses
# ===========================================================================


@app.command()
def respond(
    company: str = typer.Argument(None, help="Company name (for logging)"),
    text: str = typer.Option("", "--text", help="Response text"),
    classify_only: str = typer.Option(None, "--classify-only", help="Classify text without logging (keyword-based)"),
    llm: bool = typer.Option(False, "--llm", help="Use LLM classifier instead of keyword-based"),
    classify: str = typer.Option(None, "--classify", help="Manual classification (POSITIVE, NEUTRAL, NEGATIVE, REFERRAL, AUTO_REPLY)"),
    response: str = typer.Option("", "--response", help="Response text (alias for --text)"),
    mark_responded: bool = typer.Option(False, "--mark-responded", help="Mark outreach as responded (legacy mode)"),
):
    """Log and classify LinkedIn responses.

    Log response:    respond COMPANY --text "..." [--classify POSITIVE]
    Classify only:   respond --classify-only "text" [--llm]
    Mark responded:  respond COMPANY --mark-responded [--response "..."]
    """
    if classify_only:
        if llm:
            _classify_llm_impl(classify_only, company or "")
        else:
            _classify_response_impl(classify_only)
        return

    if mark_responded:
        if not company:
            console.print("[red]COMPANY is required with --mark-responded.[/red]")
            raise typer.Exit(1)
        _mark_responded_impl(company, response or text)
        return

    if not company:
        console.print("[red]COMPANY is required (or use --classify-only).[/red]")
        raise typer.Exit(1)

    _log_response_impl(company, text, classify)


def _log_response_impl(company, text, classify):
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


def _mark_responded_impl(company, response_text):
    """Mark outreach as responded."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.sequence_tracker import SequenceTracker

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    tracker = SequenceTracker(session)
    record = tracker.mark_responded(company, response_text)

    if record:
        console.print(f"[green]Marked responded:[/green] {company}")
        console.print(f"  Stage: {record.stage}, Responded at: {record.response_at}")
    else:
        console.print(f"[yellow]No sent outreach found for '{company}'.[/yellow]")

    session.close()


def _classify_response_impl(text):
    """Classify a response text using the v2 score-based classifier."""
    from src.outreach.response_tracker import _NEXT_ACTIONS, ResponseTracker

    classification = ResponseTracker.classify_response(text)
    next_action = _NEXT_ACTIONS.get(classification, "Unknown")

    console.print("\n[bold]Response Classification[/bold]")
    console.print(f"  Text: {text[:100]}{'...' if len(text) > 100 else ''}")
    console.print(f"  Classification: [bold]{classification}[/bold]")
    console.print(f"  Next action: {next_action}")


def _classify_llm_impl(text, company):
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


# Hidden aliases
@app.command(name="outreach-mark-responded", hidden=True)
def outreach_mark_responded(
    company: str = typer.Argument(help="Company name"),
    response: str = typer.Option("", "--response", help="Response text"),
):
    """[DEPRECATED] Use 'respond COMPANY --mark-responded' instead."""
    _mark_responded_impl(company, response)


@app.command(name="log-response", hidden=True)
def log_response(
    company: str = typer.Argument(help="Company name"),
    text: str = typer.Option("", "--text", help="Response text"),
    classify: str = typer.Option(None, "--classify", help="Classification"),
):
    """[DEPRECATED] Use 'respond' instead."""
    _log_response_impl(company, text, classify)


@app.command(name="classify-response", hidden=True)
def classify_response(
    text: str = typer.Argument(..., help="Response text to classify"),
):
    """[DEPRECATED] Use 'respond --classify-only' instead."""
    _classify_response_impl(text)


@app.command(name="classify-llm", hidden=True)
def classify_llm(
    text: str = typer.Argument(..., help="Response text to classify"),
    company: str = typer.Option("", "--company", help="Company context"),
):
    """[DEPRECATED] Use 'respond --classify-only --llm' instead."""
    _classify_llm_impl(text, company)


# ===========================================================================
# 6. transition — Transition outreach stage with validation
# ===========================================================================


@app.command()
def transition(
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
            status_str = "[green]VALID[/green]" if can else "[red]INVALID[/red]"
            console.print(f"Transition to '{stage}': {status_str}")
            console.print(f"Available transitions: {', '.join(available)}")
        else:
            sm.transition(company, stage)
            console.print(f"[green]Transitioned {company} -> {stage}[/green]")
            trail = sm.get_audit_trail(company)
            if trail:
                console.print(f"  Audit trail: {len(trail)} entries")
    except InvalidTransitionError as e:
        console.print(f"[red]Invalid transition:[/red] {e}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")

    session.close()


# Hidden alias
@app.command(name="outreach-transition", hidden=True)
def outreach_transition(
    company: str = typer.Argument(help="Company name"),
    stage: str = typer.Argument(help="New stage"),
    check_only: bool = typer.Option(False, "--check-only", help="Only check if transition is valid"),
):
    """[DEPRECATED] Use 'transition' instead."""
    transition(company=company, stage=stage, check_only=check_only)


# ===========================================================================
# 7. status — Audit trail + kickoff
# ===========================================================================


@app.command()
def status(
    company: str = typer.Argument(None, help="Company name for audit trail"),
    kickoff: bool = typer.Option(False, "--kickoff", help="Run Tier 1 kickoff instead"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run (with --kickoff)"),
):
    """Show outreach status / audit trail, or run Tier 1 kickoff.

    Audit trail: status COMPANY
    Kickoff:     status --kickoff [--dry-run]
    """
    if kickoff:
        _kickoff_impl(dry_run)
        return

    if not company:
        console.print("[red]COMPANY is required (or use --kickoff).[/red]")
        raise typer.Exit(1)

    _audit_trail_impl(company)


def _audit_trail_impl(company):
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

    console.print(f"[bold]{outreach.company_name}[/bold] -- Stage: {outreach.stage}")
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


def _kickoff_impl(dry_run):
    """Run Tier 1 kickoff: draft -> sequence -> send report."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.kickoff import Tier1Kickoff

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    kickoff_runner = Tier1Kickoff(session)
    result = kickoff_runner.run(dry_run=dry_run)

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


# Hidden aliases
@app.command(name="outreach-audit-trail", hidden=True)
def outreach_audit_trail(
    company: str = typer.Argument(..., help="Company name (partial match)"),
):
    """[DEPRECATED] Use 'status COMPANY' instead."""
    _audit_trail_impl(company)


@app.command(name="kickoff-tier1", hidden=True)
def kickoff_tier1(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show ready companies without creating records"),
):
    """[DEPRECATED] Use 'status --kickoff' instead."""
    _kickoff_impl(dry_run)


# ===========================================================================
# 8. templates — Template analytics, export, and A/B testing
# ===========================================================================


@app.command()
def templates(
    compare: bool = typer.Option(False, "--compare", help="Show connection request comparison"),
    trends: bool = typer.Option(False, "--trends", help="Show weekly trends"),
    export: str = typer.Option(None, "--export", help="Export report or CSV to file"),
    export_csv: str = typer.Option(None, "--export-csv", help="Export analytics to CSV file"),
    ab_create: str = typer.Option(None, "--ab-create", help="Create A/B experiment with this name"),
    ab_variants: str = typer.Option("connection_request_a,connection_request_b", "--ab-variants", help="Comma-separated variant names"),
    ab_results: str = typer.Option(None, "--ab-results", help="Show results for A/B experiment"),
    ab_list: bool = typer.Option(False, "--ab-list", help="List all A/B experiments"),
):
    """Template performance analytics, export, and A/B testing.

    Stats:      templates [--compare] [--trends]
    Export:     templates --export FILE | --export-csv FILE
    A/B test:   templates --ab-create NAME [--ab-variants V1,V2]
    A/B results: templates --ab-results NAME | --ab-list
    """
    # A/B testing branch
    if ab_create or ab_results or ab_list:
        _ab_test_impl(ab_create, ab_variants, ab_results, ab_list)
        return

    # Export CSV branch
    if export_csv:
        _template_export_impl(export_csv)
        return

    # Main template stats
    _template_stats_impl(compare, trends, export)


def _template_stats_impl(compare, trends, export):
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


def _ab_test_impl(create, variants, results_name, list_all):
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
        console.print("[yellow]Use --ab-create, --ab-results, or --ab-list[/yellow]")

    session.close()


def _template_export_impl(file):
    """Export template analytics to CSV."""
    from src.db.database import get_session, init_db
    from src.outreach.template_analytics import TemplateAnalytics

    engine = init_db()
    session = get_session(engine)
    analytics = TemplateAnalytics(session)
    count = analytics.export_csv(file)
    console.print(f"[green]Exported {count} template stats to {file}[/green]")
    session.close()


# Hidden aliases
@app.command(name="template-stats", hidden=True)
def template_stats(
    compare: bool = typer.Option(False, "--compare", help="Show connection request comparison"),
    trends: bool = typer.Option(False, "--trends", help="Show weekly trends"),
    export: str = typer.Option(None, "--export", help="Export full report to file"),
):
    """[DEPRECATED] Use 'templates' instead."""
    _template_stats_impl(compare, trends, export)


@app.command(name="ab-test", hidden=True)
def ab_test(
    create: str = typer.Option(None, "--create", help="Create experiment with this name"),
    variants: str = typer.Option("connection_request_a,connection_request_b", "--variants", help="Comma-separated variant names"),
    results_name: str = typer.Option(None, "--results", help="Show results for experiment"),
    list_all: bool = typer.Option(False, "--list", help="List all experiments"),
):
    """[DEPRECATED] Use 'templates --ab-*' instead."""
    _ab_test_impl(create, variants, results_name, list_all)


@app.command(name="template-export", hidden=True)
def template_export(
    file: str = typer.Argument(..., help="Output CSV file path"),
):
    """[DEPRECATED] Use 'templates --export-csv' instead."""
    _template_export_impl(file)


# ===========================================================================
# 9. email-fallback — Email follow-ups for stale connections
# ===========================================================================


@app.command(name="email-fallback")
def email_fallback(
    threshold: int = typer.Option(14, "--threshold", help="Days before considering stale"),
    batch: bool = typer.Option(False, "--batch", help="Prepare email drafts for all stale connections"),
    status_flag: bool = typer.Option(False, "--status", help="Show email outreach status"),
):
    """Email follow-ups for stale LinkedIn connections."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.email_outreach import EmailOutreach

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    email = EmailOutreach(session)

    if status_flag:
        st = email.get_email_status()
        console.print("\n[bold]Email Outreach Status[/bold]")
        console.print(f"  Stale connections: {st['total_stale']}")
        console.print(f"  With email: {st['with_email']}")
        console.print(f"  Without email: {st['without_email']}")
        console.print(f"  Drafts prepared: {st['drafts_prepared']}")
    elif batch:
        result = email.batch_prepare_emails(threshold_days=threshold)
        console.print("\n[bold]Email Fallback -- Batch Prepare[/bold]")
        console.print(f"  Total stale: {result['total_stale']}")
        console.print(f"  Drafts prepared: {len(result['drafts'])}")
        console.print(f"  Skipped (no email): {result['skipped_no_email']}")
        for draft_item in result["drafts"][:5]:
            console.print(f"\n  [bold]{draft_item['contact']} at {draft_item['company']}[/bold]")
            console.print(f"  Subject: {draft_item['subject']}")
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


# ===========================================================================
# 10. schedule — Create calendar events for interview follow-up
# ===========================================================================


@app.command()
def schedule(
    company: str = typer.Argument(..., help="Company name"),
    contact: str = typer.Argument(..., help="Contact name"),
    days_out: int = typer.Option(3, "--days-out", help="Days from now for follow-up"),
):
    """Create a calendar event payload for interview follow-up."""
    from src.integrations.calendar_bridge import CalendarBridge

    bridge = CalendarBridge()
    event = bridge.create_followup_event(company, contact, days_out=days_out)
    console.print("[green]Calendar event prepared:[/green]")
    console.print(f"  Summary: {event['summary']}")
    console.print(f"  Start: {event['start']['dateTime']}")
    console.print(f"  End: {event['end']['dateTime']}")
    console.print(f"  Description: {event.get('description', '')[:100]}")


# Hidden alias
@app.command(name="schedule-interview", hidden=True)
def schedule_interview(
    company: str = typer.Argument(..., help="Company name"),
    contact: str = typer.Argument(..., help="Contact name"),
    days_out: int = typer.Option(3, "--days-out", help="Days from now for follow-up"),
):
    """[DEPRECATED] Use 'schedule' instead."""
    schedule(company=company, contact=contact, days_out=days_out)

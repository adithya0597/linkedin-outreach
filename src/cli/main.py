"""LinkedIn Outreach CLI — Typer-based command interface.

Thin router that registers commands from domain sub-modules.
All command implementations live in src/cli/*_commands.py files.
"""

import typer
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(
    name="outreach",
    help="LinkedIn outreach automation — deterministic scoring, scraping, and CRM sync",
    no_args_is_help=True,
)

# Import all domain sub-apps
from src.cli.contact_commands import app as contact_app
from src.cli.gmail_commands import app as gmail_app
from src.cli.linkedin_commands import app as linkedin_app
from src.cli.notion_commands import app as notion_app
from src.cli.outreach_commands import app as outreach_app
from src.cli.pipeline_commands import app as pipeline_app
from src.cli.portal_commands import app as portal_app
from src.cli.scan_commands import app as scan_app
from src.cli.system_commands import app as system_app
from src.cli.validate_commands import app as validate_app
from src.cli.warmup_commands import app as warmup_app
from src.cli.workflow_commands import app as workflow_app

# Register all commands from sub-apps into the main app (flat namespace)
for sub_app in [
    scan_app,
    validate_app,
    outreach_app,
    notion_app,
    pipeline_app,
    portal_app,
    contact_app,
    gmail_app,
    linkedin_app,
    system_app,
    warmup_app,
    workflow_app,
]:
    for command in sub_app.registered_commands:
        # Typer leaves name=None when derived from function name;
        # fall back to callback.__name__ with underscores → hyphens
        name = command.name or command.callback.__name__.replace("_", "-")
        app.command(name)(command.callback)


if __name__ == "__main__":
    app()

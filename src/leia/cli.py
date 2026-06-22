"""The ``leia`` command-line interface.

Phase 0 ships: version, init-db, config-check. The pipeline commands (run,
dashboard) are stubs that point at Phase 1.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from leia import __version__
from leia.config import (
    get_settings,
    load_app_settings,
    load_icp,
    load_message_guidelines,
    load_value_prop,
)
from leia.db import resolve_database_url, upgrade_database

app = typer.Typer(
    help="PROJECT-LEIA - your personal AI lead-gen agent.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"PROJECT-LEIA [bold]{__version__}[/]")


@app.command(name="init-db")
def init_db_cmd() -> None:
    """Create/upgrade the local database schema via migrations (idempotent).

    Run this from the repository root.
    """
    upgrade_database()
    console.print(f"[green]OK[/] database ready at [bold]{resolve_database_url()}[/]")


@app.command(name="config-check")
def config_check() -> None:
    """Validate config/icp.yaml, config/value_prop.yaml and message_guidelines.md."""
    problems: list[str] = []
    icp = vp = None

    try:
        icp = load_icp()
    except Exception as e:  # noqa: BLE001 - surface any config error to the user
        problems.append(f"icp.yaml: {e}")
    try:
        vp = load_value_prop()
    except Exception as e:  # noqa: BLE001
        problems.append(f"value_prop.yaml: {e}")
    try:
        load_message_guidelines()
    except Exception as e:  # noqa: BLE001
        problems.append(f"message_guidelines.md: {e}")

    if problems:
        for p in problems:
            console.print(f"[red]x[/] {p}")
        raise typer.Exit(code=1)

    settings = get_settings()
    app_settings = load_app_settings()

    table = Table(title="Config OK", show_header=True, header_style="bold")
    table.add_column("Item")
    table.add_column("Value")
    assert icp is not None and vp is not None
    table.add_row("ICP", f"{icp.name} (v{icp.version}, threshold {icp.score_threshold})")
    table.add_row("Industries", ", ".join(icp.industries) or "-")
    table.add_row("Geographies", ", ".join(icp.geographies) or "-")
    table.add_row("Offer", (vp.offer[:70] + "...") if len(vp.offer) > 70 else vp.offer)
    table.add_row("Brain model", app_settings.models.brain)
    table.add_row("Anthropic key", "set" if settings.anthropic_api_key else "[yellow]missing[/]")
    table.add_row("Prospeo key", "set" if settings.prospeo_api_key else "[yellow]missing[/]")
    console.print(table)

    if not settings.anthropic_api_key:
        console.print(
            "[yellow]Note:[/] ANTHROPIC_API_KEY is not set. Add it to .env before running "
            "scoring/drafting (Phase 1)."
        )


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Stub all sends; nothing leaves."),
) -> None:
    """Run the find -> enrich -> score -> draft -> approve pipeline (Phase 1)."""
    console.print(
        "[yellow]The pipeline arrives in Phase 1.[/] Phase 0 built the foundation: "
        "run [bold]leia init-db[/] and [bold]leia config-check[/]."
    )


@app.command()
def dashboard() -> None:
    """Launch the Streamlit approval queue (Phase 1)."""
    console.print("[yellow]The Streamlit approval dashboard arrives in Phase 1.[/]")


if __name__ == "__main__":
    app()

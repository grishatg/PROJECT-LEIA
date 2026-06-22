"""The ``leia`` command-line interface.

Commands: version, init-db, config-check, run, send, dashboard.
"""

from __future__ import annotations

from pathlib import Path

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
    input_csv: Path = typer.Option(
        None, "--input", "-i", help="CSV of prospects (manual_csv source)."
    ),
    source: str = typer.Option("manual_csv", help="Signal source. Phase 1: manual_csv."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Stub brain + enricher: zero spend, zero sends."
    ),
    limit: int = typer.Option(None, help="Max prospects to process this run."),
) -> None:
    """Run find -> enrich -> score -> draft -> queue. Drafts await your approval."""
    from leia.db import make_engine, make_session_factory, session_scope
    from leia.pipeline import build_components, run_until_queue
    from leia.sources.manual_csv import ManualCSVSource

    if source != "manual_csv":
        console.print(f"[red]Unknown source '{source}'. Phase 1 supports: manual_csv.[/]")
        raise typer.Exit(code=2)
    if input_csv is None:
        console.print("[red]--input <prospects.csv> is required for manual_csv.[/]")
        raise typer.Exit(code=2)

    icp = load_icp()
    vp = load_value_prop()
    guidelines = load_message_guidelines()
    settings = get_settings()
    app_settings = load_app_settings()

    try:
        components = build_components(
            dry_run=dry_run, settings=settings, app_settings=app_settings
        )
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1) from e

    for note in components.notes:
        console.print(f"[yellow]note:[/] {note}")

    engine = make_engine()
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        reports = run_until_queue(
            session,
            source=ManualCSVSource(input_csv),
            components=components,
            icp_config=icp,
            value_prop=vp,
            guidelines=guidelines,
            limit=limit,
        )

    table = Table(title="Pipeline run", show_header=True, header_style="bold")
    table.add_column("Stage")
    table.add_column("Result")
    table.add_row(
        "ingest",
        f"{reports['ingest']['signals']} signals, {reports['ingest']['prospects']} prospects",
    )
    table.add_row(
        "enrich",
        f"{reports['enrich']['enriched']} with email, {reports['enrich']['failed']} without",
    )
    table.add_row("score", f"{reports['score']['scored']} scored")
    table.add_row("draft", f"{reports['draft']['drafted']} drafts")
    table.add_row("queue", f"{reports['enqueue']['queued']} awaiting your approval")
    table.add_row("Claude cost", f"${reports['total_cost_usd']:.4f}")
    console.print(table)
    console.print("Review and approve in the dashboard: [bold]leia dashboard[/]")


@app.command()
def send(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Stub channel: nothing actually leaves."
    ),
) -> None:
    """Send the drafts you've APPROVED. Nothing else is touched."""
    from leia.db import make_engine, make_session_factory, session_scope
    from leia.pipeline import build_components, send_approved

    settings = get_settings()
    app_settings = load_app_settings()
    components = build_components(
        dry_run=dry_run, settings=settings, app_settings=app_settings, require_brain=False
    )
    for note in components.notes:
        console.print(f"[yellow]note:[/] {note}")

    engine = make_engine()
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        report = send_approved(
            session, components.channel_for, daily_cap=app_settings.limits.daily_send_cap
        )
    sent = report.counts.get("sent", 0)
    failed = report.counts.get("failed", 0)
    console.print(f"[green]sent[/] {sent}   [red]failed[/] {failed}")
    if dry_run:
        console.print("[yellow](dry-run: stub channel — nothing actually left the building)[/]")


@app.command()
def dashboard(
    port: int = typer.Option(8501, help="Port for the Streamlit app."),
) -> None:
    """Launch the Streamlit approval queue in your browser."""
    import subprocess
    import sys

    app_path = Path(__file__).resolve().parents[2] / "app" / "dashboard.py"
    console.print(f"[green]Launching dashboard[/] at http://localhost:{port} (Ctrl+C to stop)")
    subprocess.run(  # noqa: S603 - launching our own bundled Streamlit app
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)],
        check=False,
    )


if __name__ == "__main__":
    app()

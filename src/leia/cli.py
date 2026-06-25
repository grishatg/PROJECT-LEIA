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

    def _key(val: str | None) -> str:
        return "set" if val else "[yellow]missing[/]"

    table = Table(title="Config OK", show_header=True, header_style="bold")
    table.add_column("Item")
    table.add_column("Value")
    assert icp is not None and vp is not None
    table.add_row("ICP", f"{icp.name} (v{icp.version}, threshold {icp.score_threshold})")
    table.add_row("Industries", ", ".join(icp.industries) or "-")
    table.add_row("Geographies", ", ".join(icp.geographies) or "-")
    table.add_row("Offer", (vp.offer[:70] + "...") if len(vp.offer) > 70 else vp.offer)
    table.add_row("Brain model", app_settings.models.brain)
    table.add_row("Anthropic key", _key(settings.anthropic_api_key))
    table.add_row("Lusha key (enrichment)", _key(settings.lusha_api_key))
    table.add_row("Instantly key (email)", _key(settings.instantly_api_key))
    table.add_row("Apify token (LinkedIn signals)", _key(settings.apify_token))
    table.add_row("Unipile key (LinkedIn send)", _key(settings.unipile_api_key))
    console.print(table)

    if not settings.anthropic_api_key:
        console.print(
            "[yellow]Note:[/] ANTHROPIC_API_KEY is not set. Add it to .env before running "
            "scoring/drafting."
        )


_VALID_SOURCES = (
    "manual_csv",
    "lusha_prospecting",
    "lusha_signals",
    "apify_linkedin",
    "companies_house",
    "jobspy",
)


@app.command()
def run(
    input_csv: Path = typer.Option(
        None, "--input", "-i", help="CSV of prospects (manual_csv source only)."
    ),
    source: str = typer.Option(
        "manual_csv",
        help=f"Signal source: {', '.join(_VALID_SOURCES)}.",
    ),
    dataset: str = typer.Option(
        None, "--dataset", help="Apify dataset ID (required for apify_linkedin source)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Stub brain + enricher: zero spend, zero sends."
    ),
    limit: int = typer.Option(None, help="Max prospects to process this run."),
) -> None:
    """Run find -> enrich -> score -> draft -> queue. Drafts await your approval."""
    from leia.db import make_engine, make_session_factory, session_scope
    from leia.pipeline import build_components, run_until_queue
    from leia.sources.base import SignalSource as SignalSourceProto

    if source not in _VALID_SOURCES:
        console.print(
            f"[red]Unknown source '{source}'. Valid options: {', '.join(_VALID_SOURCES)}.[/]"
        )
        raise typer.Exit(code=2)

    icp = load_icp()
    vp = load_value_prop()
    guidelines = load_message_guidelines()
    settings = get_settings()
    app_settings = load_app_settings()

    # ── Build the signal source ────────────────────────────────────────────
    signal_source: SignalSourceProto
    if source == "manual_csv":
        from leia.sources.manual_csv import ManualCSVSource

        if input_csv is None:
            console.print("[red]--input <prospects.csv> is required for manual_csv.[/]")
            raise typer.Exit(code=2)
        signal_source = ManualCSVSource(input_csv)

    elif source == "apify_linkedin":
        if not dataset:
            console.print(
                "[red]--dataset <DATASET_ID> is required for apify_linkedin. "
                "Run your Apify actor first and copy the dataset ID.[/]"
            )
            raise typer.Exit(code=2)
        if not settings.apify_token:
            console.print(
                "[red]APIFY_TOKEN is not set in .env. "
                "Add it before using the apify_linkedin source.[/]"
            )
            raise typer.Exit(code=1)
        from leia.sources.apify_linkedin import ApifyLinkedInSource

        signal_source = ApifyLinkedInSource(settings.apify_token, dataset)

    elif source == "lusha_prospecting":
        if dry_run:
            from leia.sources.lusha_stub import StubLushaProspectingSource

            signal_source = StubLushaProspectingSource()
        else:
            if not settings.lusha_api_key:
                console.print("[red]LUSHA_API_KEY is required for lusha_prospecting.[/]")
                raise typer.Exit(code=1)
            from leia.sources.lusha import LushaProspectingSource

            max_results = app_settings.lusha.max_prospects
            if limit:
                max_results = min(max_results, limit)
            signal_source = LushaProspectingSource(
                settings.lusha_api_key,
                icp,
                max_results=max_results,
            )

    elif source == "lusha_signals":
        if dry_run:
            from leia.sources.lusha_stub import StubLushaSignalsSource

            signal_source = StubLushaSignalsSource(
                signal_types=app_settings.lusha.signal_types
            )
        else:
            if not settings.lusha_api_key:
                console.print("[red]LUSHA_API_KEY is required for lusha_signals.[/]")
                raise typer.Exit(code=1)
            from leia.sources.lusha import LushaSignalsSource

            max_results = app_settings.lusha.max_prospects
            if limit:
                max_results = min(max_results, limit)
            signal_source = LushaSignalsSource(
                settings.lusha_api_key,
                icp,
                days_back=app_settings.lusha.signals_days_back,
                signal_types=app_settings.lusha.signal_types,
                max_results=max_results,
            )

    elif source == "companies_house":
        if dry_run:
            from leia.sources.discovery_stub import StubCompaniesHouseSource

            signal_source = StubCompaniesHouseSource()
        else:
            if not settings.companies_house_api_key:
                console.print("[red]COMPANIES_HOUSE_API_KEY is required for companies_house.[/]")
                raise typer.Exit(code=1)
            from leia.sources.companies_house import CompaniesHouseSource

            ch = app_settings.companies_house
            signal_source = CompaniesHouseSource(
                settings.companies_house_api_key,
                sic_codes=ch.sic_codes,
                location=ch.location,
                max_companies=min(ch.max_companies, limit) if limit else ch.max_companies,
                officers_per_company=ch.officers_per_company,
            )

    else:  # jobspy
        if dry_run:
            from leia.sources.discovery_stub import StubJobSpySource

            signal_source = StubJobSpySource()
        else:
            from leia.sources.jobspy import JobSpySource

            js = app_settings.jobspy
            signal_source = JobSpySource(
                search_terms=js.search_terms,
                location=js.location,
                sites=js.sites,
                results=min(js.results, limit) if limit else js.results,
            )

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
            source=signal_source,
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
def rescore(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Stub brain: zero spend (heuristic scores)."
    ),
    limit: int = typer.Option(None, help="Max prospects to re-score this run."),
) -> None:
    """Re-score every enriched prospect against the current ICP, updating each
    verdict in place. Run this after editing config/icp.yaml or the scoring prompt
    so existing prospects reflect the new criteria. Drafts/approvals are untouched."""
    from leia.db import make_engine, make_session_factory, session_scope
    from leia.pipeline import build_components, rescore_all

    icp = load_icp()
    vp = load_value_prop()
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
    if components.brain is None:
        console.print("[red]A brain is required to score prospects.[/]")
        raise typer.Exit(code=1)

    engine = make_engine()
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        report = rescore_all(session, components.brain, icp, vp, limit=limit)

    scored = report.counts.get("scored", 0)
    console.print(
        f"[green]re-scored[/] {scored} prospect(s) against "
        f"[bold]{icp.name}[/] (threshold {icp.score_threshold})   "
        f"Claude cost ${report.cost_usd:.4f}"
    )
    console.print("Review the updated scores in the dashboard: [bold]leia dashboard[/]")


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
def export(
    out: Path = typer.Option("prospects.csv", "--out", "-o", help="Output CSV path."),
) -> None:
    """Export every prospect (+ enrichment, latest score, draft status) to a CSV file."""
    from leia.db import make_engine, make_session_factory, session_scope
    from leia.web.serializers import export_prospects_csv

    engine = make_engine()
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        csv_text = export_prospects_csv(session)
    out.write_text(csv_text, encoding="utf-8")
    rows = max(0, csv_text.count("\n") - 1)
    console.print(f"[green]Exported[/] {rows} prospect(s) to [bold]{out}[/]")


@app.command()
def dashboard(
    port: int = typer.Option(8000, help="Port for the web control center."),
    host: str = typer.Option("127.0.0.1", help="Bind address (local only by default)."),
) -> None:
    """Launch the web control center in your browser (run, review, approve, send)."""
    import uvicorn

    console.print(
        f"[green]Launching LEIA[/] at [bold]http://localhost:{port}[/] (Ctrl+C to stop)"
    )
    if host == "127.0.0.1":
        console.print("[dim]Local only — not reachable from other devices.[/]")
    uvicorn.run("leia.web.server:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()

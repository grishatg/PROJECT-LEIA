# CLAUDE.md — guide for working in PROJECT-LEIA

This file orients Claude Code (and you) when working in this repo. Read it first.

## What this project is

A **personal AI lead-generation agent**. It runs a staged pipeline:

```
ingest → dedupe → enrich → score (Claude) → draft (Claude) → approval queue → send
```

It finds prospects, enriches them (emails + firmographics), scores them against the user's ICP
using Claude, writes personalized email/LinkedIn messages with Claude, and queues every message
for **human approval before anything sends**. Built for a non-technical solo builder; later it
can grow into a multi-tenant SaaS.

## Golden rules

1. **Nothing sends without an approved `ApprovalItem`.** The approval gate is the core safety
   property. Channels only act on approved drafts. Keep it that way until the user explicitly
   enables auto-send (Phase 3).
2. **Secrets live only in `.env`** (gitignored). Never hardcode keys; never put secrets in
   prompts, logs, or commits. Load via `leia.config.get_settings()`.
3. **External services sit behind a `base.py` protocol** (`sources/`, `enrichment/`,
   `channels/`). Adding a provider = write one new file implementing the protocol. Don't scatter
   vendor SDK calls through the pipeline.
4. **The brain = direct `anthropic` SDK, one structured call per task.** Scoring and drafting are
   pure functions `(input) -> validated Pydantic object`. No autonomous tool-loop in the MVP.
   This keeps cost predictable and every step unit-testable with a fake client.
5. **Keep it readable.** A non-technical owner reads this code with Claude's help. Prefer clear
   names and small functions over cleverness.

## Models

- `claude-opus-4-8` — scoring and drafting (quality is the product).
- `claude-haiku-4-5` — optional cheap pre-filter to drop obvious non-fits before paying for Opus.
- Cost controls: prompt-cache the stable ICP/value-prop prefix, log tokens+cost per row, enforce
  a daily spend cap. The brain runs on the **pay-as-you-go Anthropic API** (an API key), which is
  separate from the user's Claude Max chat subscription.

## Layout

| Path | Purpose |
|---|---|
| `config/icp.yaml` | WHO to target (editable). Snapshotted into the `ICP` table per run. |
| `config/value_prop.yaml` | WHAT you offer / proof points. |
| `config/message_guidelines.md` | HOW to write (tone, length, do/don't) — prose for Claude. |
| `config/settings.example.toml` | Non-secret knobs (model ids, caps). Copy to `settings.toml`. |
| `prompts/*.md` | Stable system prompts (kept byte-stable so prompt caching works). |
| `src/leia/models.py` | SQLAlchemy data model (load-bearing). |
| `src/leia/db.py` | Engine/session, `init_db()`. |
| `src/leia/config.py` | Loads + validates `.env`, `icp.yaml`, `value_prop.yaml`. |
| `src/leia/schemas.py` | Pydantic I/O schemas for Claude (`ScoreResult`, `DraftResult`). |
| `src/leia/dedupe.py` | URL canonicalization + idempotency keys (pure logic). |
| `src/leia/pipeline.py` | Staged orchestration (Phase 1). |
| `src/leia/llm/` | Anthropic wrapper + scoring + drafting (Phase 1). |
| `src/leia/sources/` `enrichment/` `channels/` | Pluggable providers behind protocols. |
| `src/leia/web/` | FastAPI web control center: run/review/approve/send/stats/settings (zero-build HTML). |
| `tests/` | Offline tests: in-memory SQLite + fake Anthropic client. |

## Commands

```bash
uv sync                 # install deps
uv run leia init-db     # create the SQLite schema
uv run leia config-check# validate config files (icp.yaml / value_prop.yaml)
uv run leia run --dry-run --input data/fixtures/contacts.sample.csv  # full pipeline, stubbed
uv run leia dashboard   # web control center at http://localhost:8000 (local only)
uv run leia send --dry-run  # send APPROVED drafts (stubbed in dry-run)
uv run pytest           # run the offline test suite
uv run ruff check .     # lint
```

## Data model notes

- SQLite (`data/leia.db`) via SQLAlchemy 2.0 ORM. Postgres-ready: swap `DATABASE_URL`, run Alembic.
- Every top-level table has a nullable `account_id` defaulting to `"local"` — the cheap hedge that
  keeps multi-tenant productization open without a rewrite. Don't remove it.
- `EnrichedContact.provider_raw_json` caches the raw provider payload so we never re-pay to
  re-derive a field. `OutreachLog` is append-only — the audit trail of everything sent.

## Phased roadmap (where we are → where we're going)

- **Phase 0 (done):** scaffold, data model, config, test harness, `leia init-db`.
- **Phase 1 (done):** email MVP end-to-end — manual_csv source + Prospeo enrichment (stub
  fallback) + Claude scoring + Claude drafting + web approval queue + gated email send.
  Dry-run mode (`--dry-run`) runs the whole thing with stub providers: zero spend, zero sends.
- **Phase 2 (next):** LinkedIn — Apify signals + Unipile sending; campaign sequencing.
- **Phase 3:** auto-send toggle + APScheduler, gated by caps + kill switch.
- **Phase 4:** productize — activate `account_id`, Postgres, auth, Stripe billing, real web UI.

## Account setup checklist (only the user can do these)

1. **Anthropic API key** → https://console.anthropic.com → set a low monthly spend cap. Put in `.env`.
2. **Prospeo** (enrichment) → https://prospeo.io → API key into `.env`. (Or Dropcontact for GDPR-first.)
3. **Instantly** (email) → https://instantly.ai → use a *spare* sending domain; warm it up ~2 weeks.
4. *(Phase 2)* **Apify** + **Unipile** accounts.

## Conventions

- Python ≥ 3.11, `uv` for deps, `ruff` for lint, `pytest` for tests.
- Tests must run **offline and free**: no real network or Claude calls — inject the fake client.
- Branch: `claude/sharp-mayer-reavd2`. Commit in small, descriptive steps; open a draft PR.

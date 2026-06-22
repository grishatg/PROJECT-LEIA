# PROJECT-LEIA

**Your own AI lead-generation agent.** PROJECT-LEIA finds prospects, enriches them, scores
them against *your* Ideal Customer Profile (ICP) with Claude, and writes personalized email +
LinkedIn outreach — then puts every message in a **review queue so you approve before anything
sends**. Inspired by tools like Gojiberry.ai, but yours to own, customize, and (eventually)
sell.

> **Status:** Phases 0–2 integrated. The pipeline runs end-to-end behind a manual-approval gate
> with **four lead sources** (manual CSV, Lusha prospecting, Lusha intent signals, Apify/LinkedIn)
> and **two outreach channels** (Instantly email + Unipile LinkedIn). 96 offline tests pass.

## The pipeline

```
ingest → dedupe → enrich → score (Claude) → draft (Claude) → approval queue → send
```

Each stage is a discrete, testable step. Nothing is sent without your approval.

## Try it now (no API keys, no cost)

```bash
uv sync
uv run leia init-db
# Dry-run uses stub providers: zero spend, zero sends.
uv run leia run --dry-run --input data/fixtures/contacts.sample.csv
uv run leia dashboard        # review the drafts, click Approve
uv run leia send --dry-run   # "sends" only what you approved (stubbed)
```

Then add your real keys to `.env`, drop `--dry-run`, and point `--input` at your own CSV.

## Quick start

```bash
# 1. Install dependencies (uses uv: https://docs.astral.sh/uv/)
uv sync

# 2. Copy the secrets template and fill in your keys
cp .env.example .env      # then edit .env

# 3. Create the local database
uv run leia init-db

# 4. Check your config is valid
uv run leia config-check
```

## What you need to set up (you start from zero)

| Service | What for | Notes |
|---|---|---|
| **Anthropic API key** | The brain (scoring + drafting) | Pay-as-you-go; set a spend cap. Separate from Claude Max. |
| **Lusha** | Enrichment + prospecting + intent signals | Powers email/firmographic lookup and the `lusha_prospecting` / `lusha_signals` sources. Swap in one file if you prefer another provider. |
| **Instantly** | Cold-email sending | Use a *spare* sending domain; let warmup run before real volume. |
| Apify | LinkedIn prospect source | Run a LinkedIn scraper actor, pass its dataset id via `--dataset`. Optional. |
| Unipile | LinkedIn sending | Connect a LinkedIn account; sends connection-request notes (≤300 chars). Optional. |

See `CLAUDE.md` for the full build plan and architecture.

## Lead sources

Choose a source with `leia run --source <name>`:

| Source | Flag | Needs |
|---|---|---|
| `manual_csv` | `--input prospects.csv` | nothing (works offline) |
| `lusha_prospecting` | — | `LUSHA_API_KEY` + `config/icp.yaml` filters |
| `lusha_signals` | — | `LUSHA_API_KEY` (returns only contacts with recent buying-intent events) |
| `apify_linkedin` | `--dataset <ID>` | `APIFY_TOKEN` + a LinkedIn-scraper dataset |

Every source supports `--dry-run` (deterministic stubs, zero spend, zero sends).

## Project layout

```
config/      your editable knobs: icp.yaml, value_prop.yaml, message_guidelines.md
prompts/     stable system prompts for Claude (scoring, drafting)
src/leia/    the application (models, db, config, pipeline, llm, sources, channels, ...)
app/         the Streamlit approval dashboard (Phase 1)
tests/       offline tests (in-memory DB + a fake Claude client)
data/        local SQLite DB (gitignored) + sample fixtures
```

## Cost (rough, monthly)

Lusha ~$40 + Anthropic ~$5–20 + Instantly ~$30–37 ≈ **$75–95** for the email MVP. Claude is
the *smallest* line item. This isn't about saving money month one — it's about owning the stack.

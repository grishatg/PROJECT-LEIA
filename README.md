# PROJECT-LEIA

**Your own AI lead-generation agent.** PROJECT-LEIA finds prospects, enriches them, scores
them against *your* Ideal Customer Profile (ICP) with Claude, and writes personalized email +
LinkedIn outreach — then puts every message in a **review queue so you approve before anything
sends**. Inspired by tools like Gojiberry.ai, but yours to own, customize, and (eventually)
sell.

> **Status:** Phase 0 — project scaffold, data model, config, and test harness. The full
> find → enrich → score → draft → approve → send pipeline arrives in Phase 1.

## The pipeline

```
ingest → dedupe → enrich → score (Claude) → draft (Claude) → approval queue → send
```

Each stage is a discrete, testable step. Nothing is sent without your approval.

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
| **Prospeo** | Enrichment (find emails) | Cheaper-than-Apollo; swap in one file if you prefer Dropcontact/Snov.io/Hunter. |
| **Instantly** | Cold-email sending | Use a *spare* sending domain; let warmup run before real volume. |
| Apify + Unipile | LinkedIn (Phase 2) | Add later. |

See `CLAUDE.md` for the full build plan and architecture.

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

Prospeo ~$39 + Anthropic ~$5–20 + Instantly ~$30–37 ≈ **$75–95** for the email MVP. Claude is
the *smallest* line item. This isn't about saving money month one — it's about owning the stack.

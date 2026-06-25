# LEIA — session handoff

A running status doc so a new session (or a human) can pick up fast. Last updated
end of the build session that took LEIA from "Phase 1 + stubs" to "live keys, reading
LinkedIn replies, persona-driven."

## What LEIA is
A personal AI lead-gen agent for **Greg Tugulea, BDM at Equity Energies** (UK B2B
energy / Net Zero consultancy). Staged pipeline:
`ingest → dedupe → enrich → score (Claude) → draft (Claude) → approval queue → send`,
plus a Phase-2 **conversation engine** that reads replies and converses to book meetings.
**Golden rule: nothing sends without an approved item; meeting proposals are always gated.**

## ✅ Done this session (all merged to `main`)
- **#11 UI rebuild** on the finalised "leia" design system (amber/Schibsted, light+dark).
- **#12 Phase-2 foundation**: suppression/opt-out list (PECR/GDPR), reply parsing
  (`replies/parse.py`), conversation brain (`Brain.converse` + `prompts/converse_system.md`),
  UK discovery sources (Companies House, JobSpy), models + migration
  (`ConversationThread`, `Message`, `Meeting`, `SuppressionList`).
- **#13 Conversation engine** (`conversation.py`): hybrid autonomy — auto-send simple
  `continue` replies (under cap), **gate meeting proposals for human approval**,
  auto-suppress opt-outs. `POST /api/tasks/tick` scheduler entrypoint.
- **#14 Persona**: Greg's real voice from his sent-mail analysis baked into
  `config/message_guidelines.md` (+ `value_prop.yaml`). Hard rules enforced in prompts:
  proof points are **EE's** results (never "I delivered"), never fabricate a figure,
  no LOA/data ask in first touch. Fixed the old "never use I" rule.
- **#15 Run UI**: a **Run-outreach modal** (opened from "Start today's outreach →" and
  Prospects "Find more leads →") with a **people-count** input (default 5 — caps the run so
  it won't burn credits), a **real CSV file upload** (`POST /api/upload`, validates columns,
  stores under `data/uploads/`), source chooser, practice-run toggle, result summary.
  Plus storyboard fidelity (search box, Light/Dark/Auto theme, settings badges, ring score).
- **#16 Companies House**: key verified live; ICP-targeted **SIC starter set** in
  `settings.toml` (food/drink mfg, cold storage, cement, glass, steel, paper, plastics) —
  returns real targets (Dunbia, Omagh Meats, etc.). `data/uploads/` gitignored (PII).
- **#17 UnipileInbox** (`inbox/unipile.py`): **LEIA can now READ LinkedIn replies** —
  polls Unipile messaging API, keeps inbound only, never crashes the tick, idempotent on
  `provider_id`. Tick uses it live when creds present.
- **Booking link** wired: meeting-proposal replies carry Greg's Outlook Bookings URL.

Test suite: **139 passing**, ruff clean. All offline/free (in-memory SQLite + fake clients).

## 🔑 Credentials (all in gitignored `.env` locally — NEVER committed)
Set and loading: Anthropic, Lusha, Apify, Instantly (key+campaign), Unipile (key+DSN+account_id
`Greg Tugulea`/Running), Companies House, Booking URL, Supabase (url+anon+jwt), DATABASE_URL.
**`DATABASE_URL` now points at Supabase Postgres** (not SQLite).

> ⚠️ The dev container is **ephemeral** — this `.env` does not exist in production.
> **You must set every one of these as environment variables in Render** (dashboard →
> service → Environment) for the deployed app to work.

## ❌ Not done yet / known gaps (roughly in priority order)
1. **LinkedIn reply → prospect matching.** The reader works, but an inbound LinkedIn
   message isn't yet tied to the right prospect. Fix: when LEIA sends the opener via
   Unipile, store the returned `chat_id` on the `ConversationThread`; match inbound by
   `provider_chat_id` (already carried on `InboundReply`). Needs a thread column + send-side
   wiring. **This is the next build** — after it, LinkedIn conversations run end-to-end.
2. **Initiation in the tick**: the tick reads + replies, but doesn't yet *start* new
   conversations (send openers to freshly-scored leads under caps).
3. **Scheduler cron + human pacing**: `POST /api/tasks/tick` exists but nothing calls it on
   a schedule. Add a Render cron + business-hours/jitter/daily-cap pacing + a kill switch.
4. **Postgres migration**: with `DATABASE_URL`=Postgres, the schema must be created there.
   Needs the `psycopg` driver added to deps and Alembic run against Supabase
   (`alembic upgrade head`). Tests still use in-memory SQLite, so they're unaffected.
5. **Email reply reading**: only LinkedIn (Unipile) inbox exists; no Instantly reply reader.
6. **Conversation/booking UI**: surface `AWAITING_HUMAN` threads + a "Mark booked" action in
   the Outreach tab (gated meeting proposals currently have no review surface).
7. **Auto-send toggle (Phase 3)**: chosen autonomy = "auto-converse, gate the meeting."
   Currently meeting/escalate replies are drafted but not surfaced for one-tap approval (see #6).
8. **Visual-only UI bits**: Analytics 7d/30d/90d selector and Settings "daily send limit"/
   "default tone" badges have no backend yet.
9. **CI**: none configured. Optional: add a GitHub Actions workflow running `pytest` + `ruff`.

## 📋 What Greg still needs to provide
- **Render env vars** (all of the `.env` above) — required to deploy.
- **3–5 real LinkedIn DMs** — biggest remaining *voice* gap (Gmail analysis had no LinkedIn).
- **Signature block + direct dial** — for message sign-offs.
- *(Optional, high value)* a few real **Microsoft 365 sent client emails** — his true prospect
  voice (Gmail confirmed it isn't there).
- Confirm the **Parkwood £171k** case-study figure is cleared for external use.

## Orientation for the next session
- `CLAUDE.md` — project guide + golden rules (read first).
- Conversation engine: `src/leia/conversation.py`; inbox providers: `src/leia/inbox/`
  (`base.py` protocol, `unipile.py`, `stub.py`); outbound: `src/leia/channels/`.
- Brain: `src/leia/llm/` (`client.py` real, `stub.py` fake) + `prompts/*.md`.
- Voice/config: `config/message_guidelines.md`, `config/value_prop.yaml`, `config/icp.yaml`,
  `settings.toml`.
- Web: `src/leia/web/server.py` (+ `static/app.js`, `templates/index.html`).
- Tests: `tests/` (offline). Run `uv run pytest`, `uv run ruff check .`.
- Branch: develop on `claude/leia-*`, open a draft PR, keep the suite green.

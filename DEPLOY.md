# Deploying LEIA to the cloud (Render + Supabase)

Goal: run LEIA on the internet behind a login so you can use it from any device
(including your iPad). **Supabase** provides the database + login; **Render** runs
the app. You won't touch a server — it's all dashboards.

> ⚠️ The login is what protects your spending (Claude/Lusha) and email sending.
> Set it up fully and **disable public sign-ups** so only you can get in.

---

## Part 1 — Supabase (database + login)

1. Go to **https://supabase.com** → sign up → **New project**. Pick a name and a
   strong database password (save it). Choose a region near you.
2. When it finishes building, collect four values:
   - **Project URL** and **anon key**: left sidebar → **Project Settings → API** →
     "Project URL" and "Project API keys → `anon` `public`".
   - **JWT secret**: same **API** page → "JWT Settings → JWT Secret".
   - **Database connection string**: **Project Settings → Database → Connection
     string → URI**. Copy it. It looks like
     `postgresql://postgres:[YOUR-PASSWORD]@db.xxxx.supabase.co:5432/postgres`.
     **Change the prefix** to `postgresql+psycopg://` and put your real password in.
     → this is your **`DATABASE_URL`**.
3. Create your login user: left sidebar → **Authentication → Users → Add user** →
   enter your email + a password. (This is the account you'll log in with.)
4. Lock the door: **Authentication → Providers → Email** (or **Sign In / Up
   settings**) → turn **OFF** "Allow new users to sign up". Now only the user you
   created can log in.

## Part 2 — Render (runs the app)

1. Push this repo to GitHub (already done) and go to **https://render.com** → sign
   up with GitHub.
2. **New + → Blueprint** → pick the `PROJECT-LEIA` repo. Render reads `render.yaml`
   and proposes a web service named **leia**. Click to create it.
3. It will ask for the secret values (everything marked `sync:false`). Paste:
   - `DATABASE_URL` → the Supabase URI from Part 1 (with `postgresql+psycopg://`).
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET` → from Part 1.
   - `ANTHROPIC_API_KEY`, `LUSHA_API_KEY`, `INSTANTLY_API_KEY`,
     `INSTANTLY_CAMPAIGN_ID` → your keys.
   - `APIFY_TOKEN`, `UNIPILE_API_KEY`, `UNIPILE_DSN` → optional (LinkedIn).
4. Click **Deploy**. The first build takes a few minutes. On boot it runs the
   database migrations automatically against Supabase.
5. When it's live, open the Render URL (e.g. `https://leia.onrender.com`). You'll see
   the **login page** → sign in with the user you created. Done — use it from any
   device, including your iPad.

## Everyday notes
- **Free plan** sleeps after ~15 min idle; the first visit then takes ~30–60s to
  wake. Upgrade the service to **Starter (~$7/mo)** in Render for always-on.
- **Supabase free** database pauses after ~7 days idle — un-pause it in the Supabase
  dashboard if that happens.
- **Dry-run is free.** Real lead-finding needs **Lusha credits**; drafting/sending
  needs your Anthropic/Instantly keys.
- **Change your password / add a user:** Supabase → Authentication → Users.
- **Rotate keys:** because the API keys were shared in chat earlier, regenerate them
  in each provider and update the values in Render → your service → **Environment**.

## Run it locally too (optional)
Locally you don't need Supabase — leave `SUPABASE_*` unset and the app skips the
login (it only listens on your own machine):
```
uv run leia init-db
uv run leia dashboard      # http://localhost:8000
```

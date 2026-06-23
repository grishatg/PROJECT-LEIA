# Sourcing prospects from LinkedIn Sales Navigator

LinkedIn has **no official Sales Navigator API** (it's closed to new partners), so LEIA
sources Sales Nav leads via **Apify** — you run a Sales Nav scraper, then LEIA imports the
result. This is a gray area under LinkedIn's terms; use your own account, keep volumes modest,
and accept some account risk.

## Steps

1. **Build your search in Sales Navigator** using the Equity Energies filter recipes (see the ICP
   playbook). For example, the multi-site / Finance-Procurement recipe:
   - Geography: United Kingdom
   - Industry: Retail · Hospitality · Food & Beverage · Logistics · Residential Construction …
   - Company headcount: 201–500 · 501–1,000 · 1,001–5,000
   - Seniority: Director · VP · CXO · Owner
   - Job titles: Finance Director, Head of Procurement, Energy Manager, Head of Sustainability …
   - Optional: "Changed jobs in last 90 days" for warm, new-in-role targets.

2. **Run an Apify Sales Navigator scraper.** In [Apify](https://apify.com) → Store, search
   "LinkedIn Sales Navigator", pick a scraper actor, paste your Sales Nav search URL, and Run it.

3. **Copy the dataset id.** When the run finishes, open its **Storage / Dataset** tab — the
   dataset id is in the page (and the URL).

4. **Import into LEIA.** Either:
   - In the dashboard → **Run** → Source = *Apify / LinkedIn* → paste the dataset id → Run; or
   - CLI: `uv run leia run --source apify_linkedin --dataset <DATASET_ID>`

LEIA normalises the common scraper output shapes (name, headline, company, LinkedIn URL, email if
present), dedupes, scores against your ICP, and drafts — exactly like any other source.

## Notes
- `APIFY_TOKEN` must be set (it already is in your deployment).
- Start small (`--limit`) to check quality and spend before a large pull.
- A direct in-app Sales Nav search (via Unipile) is possible later but carries higher ToS/ban
  risk; Apify export is the lower-setup route and is what's supported today.

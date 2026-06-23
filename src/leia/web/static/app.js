"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// Supabase auth state (set during boot). When auth is disabled (local mode),
// SB stays null and requests go out without a token.
let SB = null;
let AUTH_ENABLED = false;

async function authHeader() {
  if (!AUTH_ENABLED || !SB) return {};
  const { data } = await SB.auth.getSession();
  return data.session ? { Authorization: "Bearer " + data.session.access_token } : {};
}

async function api(path, method = "GET", body) {
  const headers = { "Content-Type": "application/json", ...(await authHeader()) };
  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Please log in again");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || ("Request failed: " + res.status));
  return data;
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isError ? " err" : "");
  setTimeout(() => (t.className = "toast"), 2600);
}

// ── Navigation ────────────────────────────────────────────────────────────
function showView(name) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  if (name === "dashboard") loadDashboard();
  if (name === "review") loadReview();
  if (name === "settings") loadIcp();
}
$$(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

// ── Dashboard ───────────────────────────────────────────────────────────────
const TILE_DEFS = [
  { key: "prospects", icon: "👥", label: "Prospects Fetched" },
  { key: "enriched", icon: "✨", label: "Enriched" },
  { key: "queued", icon: "📝", label: "Drafts Queued" },
  { key: "approved", icon: "✅", label: "Approved" },
  { key: "sent", icon: "📨", label: "Sent" },
  { key: "spend_usd", icon: "💰", label: "Claude Spend", money: true },
];

async function loadDashboard() {
  try {
    const [st, stats, hist] = await Promise.all([
      api("/api/status"),
      api("/api/stats"),
      api("/api/history"),
    ]);
    renderTiles(st);
    renderKeys(st.keys);
    $("#nav-pending").textContent = st.tiles.queued;
    renderChart(stats);
    renderHistory(hist);
  } catch (e) {
    toast(e.message, true);
  }
}

function renderTiles(st) {
  const tiles = TILE_DEFS.map((d) => {
    let v = st.tiles[d.key];
    v = d.money ? "$" + Number(v).toFixed(2) : v;
    return `<div class="tile"><div class="icon">${d.icon}</div>
      <div class="num">${v}</div><div class="label">${d.label}</div></div>`;
  });
  st.coming_soon.forEach((m) => {
    tiles.push(`<div class="tile soon"><div class="icon">📧</div>
      <div class="num">—</div><div class="label">${m[0].toUpperCase() + m.slice(1)}<span class="tag-soon">soon</span></div></div>`);
  });
  $("#tiles").innerHTML = tiles.join("");
}

function renderKeys(keys) {
  const names = { anthropic: "Anthropic", lusha: "Lusha", instantly: "Instantly", apify: "Apify", unipile: "Unipile" };
  $("#key-status").innerHTML = Object.entries(names)
    .map(([k, label]) => `<div class="key-row"><span class="dot ${keys[k] ? "key-on" : "key-off"}"></span>${label}</div>`)
    .join("");
}

function renderChart(stats) {
  const max = Math.max(1, ...stats.drafted, ...stats.sent);
  const html = stats.labels
    .map((lbl, i) => {
      const dh = Math.round((stats.drafted[i] / max) * 150);
      const sh = Math.round((stats.sent[i] / max) * 150);
      return `<div class="day"><div class="bars">
        <div class="bar bar-blue" style="height:${dh}px" title="Drafted: ${stats.drafted[i]}"></div>
        <div class="bar bar-green" style="height:${sh}px" title="Sent: ${stats.sent[i]}"></div>
      </div><small>${lbl}</small></div>`;
    })
    .join("");
  $("#chart-activity").innerHTML = html;
}

function renderHistory(rows) {
  if (!rows.length) {
    $("#history").innerHTML = `<p class="muted">Nothing sent yet. Approve a draft, then use Send.</p>`;
    return;
  }
  $("#history").innerHTML = rows
    .map(
      (r) => `<div class="hrow"><div class="avatar" style="width:32px;height:32px;font-size:12px">${(r.full_name || "?")[0]}</div>
      <div><strong>${r.full_name}</strong> <span class="muted">· ${r.company_name || ""}</span><br>
      <span class="muted">${r.subject || r.channel}</span></div>
      <span class="he">${r.event}</span></div>`
    )
    .join("");
}

// ── Review (inbox) ────────────────────────────────────────────────────────────
let CURRENT = [];
async function loadReview() {
  try {
    CURRENT = await api("/api/approvals");
    $("#nav-pending").textContent = CURRENT.length;
    const list = $("#inbox-list");
    if (!CURRENT.length) {
      list.innerHTML = `<p class="muted">No drafts awaiting review. Head to Run to generate some.</p>`;
      $("#inbox-read").innerHTML = `<div class="empty-read">Nothing to review 🎉</div>`;
      return;
    }
    list.innerHTML = CURRENT.map(
      (c) => `<div class="inbox-item" data-id="${c.id}">
        <div class="avatar">${c.initials}</div>
        <div><div class="who">${c.full_name}</div><div class="co">${c.company_name || c.headline || ""}</div></div>
        <div class="meta"><span class="badge tier-${c.tier || "C"}">${c.score ?? "—"}</span></div>
      </div>`
    ).join("");
    $$("#inbox-list .inbox-item").forEach((el) =>
      el.addEventListener("click", () => selectDraft(el.dataset.id))
    );
    selectDraft(CURRENT[0].id);
  } catch (e) {
    toast(e.message, true);
  }
}

function selectDraft(id) {
  const c = CURRENT.find((x) => x.id === id);
  if (!c) return;
  $$("#inbox-list .inbox-item").forEach((el) => el.classList.toggle("selected", el.dataset.id === id));
  const isEmail = c.channel === "email";
  $("#inbox-read").innerHTML = `
    <div class="read-head">
      <div class="avatar">${c.initials}</div>
      <div><div class="who">${c.full_name}</div>
        <div class="co">${[c.headline, c.company_name].filter(Boolean).join(" · ")}</div></div>
      <span class="badge tier-${c.tier || "C"}" style="margin-left:auto">Tier ${c.tier || "?"} · ${c.score ?? "—"}</span>
    </div>
    <div class="read-meta">
      ${c.email ? `<span class="chip">✉️ ${c.email} (${c.email_status})</span>` : ""}
      <span class="chip">📡 ${c.channel}</span>
      <span class="chip">💰 $${c.spend_usd.toFixed(4)} · ${c.model_id}</span>
    </div>
    ${c.rationale ? `<div class="rationale"><strong>Why this score:</strong> ${c.rationale}</div>` : ""}
    ${isEmail ? `<div class="field-label">Subject</div><input id="ed-subject" value="${(c.subject || "").replace(/"/g, "&quot;")}">` : ""}
    <div class="field-label">Message</div>
    <textarea id="ed-body" rows="9">${c.body || ""}</textarea>
    <div class="field-label">Note (optional)</div>
    <input id="ed-note" placeholder="Reason / reminder…">
    <div class="read-actions">
      <button class="btn approve" id="btn-approve">✅ Approve</button>
      <button class="btn reject" id="btn-reject">✕ Reject</button>
    </div>`;

  $("#btn-approve").addEventListener("click", () => decide(c, "approve"));
  $("#btn-reject").addEventListener("click", () => decide(c, "reject"));
}

async function decide(c, action) {
  const note = $("#ed-note").value.trim();
  try {
    if (action === "approve") {
      const body = { note };
      const subEl = $("#ed-subject");
      const bodyEl = $("#ed-body");
      if (subEl && subEl.value !== (c.subject || "")) body.edited_subject = subEl.value;
      if (bodyEl && bodyEl.value !== (c.body || "")) body.edited_body = bodyEl.value;
      await api(`/api/approvals/${c.id}/approve`, "POST", body);
      toast("Approved ✓");
    } else {
      await api(`/api/approvals/${c.id}/reject`, "POST", { note });
      toast("Rejected");
    }
    loadReview();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Run ───────────────────────────────────────────────────────────────────
$("#run-source").addEventListener("change", (e) => {
  const v = e.target.value;
  $("#row-csv").style.display = v === "manual_csv" ? "block" : "none";
  $("#row-dataset").style.display = v === "apify_linkedin" ? "block" : "none";
});

$("#btn-run").addEventListener("click", async () => {
  const btn = $("#btn-run");
  btn.disabled = true;
  btn.textContent = "⏳ Working…";
  $("#run-result").innerHTML = "";
  try {
    const payload = {
      source: $("#run-source").value,
      dry_run: $("#run-dry").checked,
      limit: Number($("#run-limit").value) || null,
      input_csv: $("#run-csv").value,
      dataset: $("#run-dataset").value,
    };
    const r = await api("/api/run", "POST", payload);
    $("#run-result").innerHTML = `<table>
      <tr><td>Prospects ingested</td><td>${r.ingest.prospects}</td></tr>
      <tr><td>Enriched with email</td><td>${r.enrich.enriched}</td></tr>
      <tr><td>Scored</td><td>${r.score.scored}</td></tr>
      <tr><td>Drafts written</td><td>${r.draft.drafted}</td></tr>
      <tr><td>Queued for approval</td><td>${r.enqueue.queued}</td></tr>
      <tr><td>Claude cost</td><td>$${r.total_cost_usd.toFixed(4)}</td></tr>
    </table>${(r.notes || []).map((n) => `<p class="muted">• ${n}</p>`).join("")}`;
    toast(`Done — ${r.enqueue.queued} draft(s) queued`);
  } catch (e) {
    toast(e.message, true);
    $("#run-result").innerHTML = `<p class="muted">${e.message}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "🚀 Run pipeline";
  }
});

// ── Send ────────────────────────────────────────────────────────────────────
$("#btn-send").addEventListener("click", async () => {
  const btn = $("#btn-send");
  btn.disabled = true;
  btn.textContent = "⏳ Sending…";
  try {
    const r = await api("/api/send", "POST", { dry_run: $("#send-dry").checked });
    $("#send-result").innerHTML = `<table>
      <tr><td>Sent</td><td>${r.counts.sent || 0}</td></tr>
      <tr><td>Failed</td><td>${r.counts.failed || 0}</td></tr>
    </table>${r.dry_run ? `<p class="muted">Dry-run: nothing actually left the building.</p>` : ""}`;
    toast(`Sent ${r.counts.sent || 0}`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "📤 Send approved";
  }
});

// ── Settings (ICP) ────────────────────────────────────────────────────────────
const lines = (arr) => (arr || []).join("\n");
const parseLines = (s) => s.split("\n").map((x) => x.trim()).filter(Boolean);

async function loadIcp() {
  try {
    const icp = await api("/api/config/icp");
    $("#icp-name").value = icp.name || "";
    $("#icp-industries").value = lines(icp.industries);
    $("#icp-titles").value = lines(icp.titles);
    $("#icp-geographies").value = lines(icp.geographies);
    $("#icp-keywords").value = lines(icp.keywords);
    $("#icp-exclude").value = lines(icp.exclude);
    $("#icp-size-min").value = icp.company_size?.min ?? "";
    $("#icp-size-max").value = icp.company_size?.max ?? "";
    $("#icp-threshold").value = icp.score_threshold ?? 60;
  } catch (e) {
    toast(e.message, true);
  }
}

$("#btn-save-icp").addEventListener("click", async () => {
  try {
    const payload = {
      name: $("#icp-name").value || "My ICP",
      industries: parseLines($("#icp-industries").value),
      titles: parseLines($("#icp-titles").value),
      geographies: parseLines($("#icp-geographies").value),
      keywords: parseLines($("#icp-keywords").value),
      exclude: parseLines($("#icp-exclude").value),
      company_size: {
        min: $("#icp-size-min").value ? Number($("#icp-size-min").value) : null,
        max: $("#icp-size-max").value ? Number($("#icp-size-max").value) : null,
      },
      score_threshold: Number($("#icp-threshold").value) || 60,
    };
    await api("/api/config/icp", "PUT", payload);
    toast("ICP saved ✓");
  } catch (e) {
    toast(e.message, true);
  }
});

// ── Logout ────────────────────────────────────────────────────────────────
const logoutBtn = $("#btn-logout");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    if (SB) await SB.auth.signOut();
    window.location.href = "/login";
  });
}

// ── Boot: check auth, then load the dashboard ───────────────────────────────
async function boot() {
  try {
    const cfg = await fetch("/api/public-config").then((r) => r.json());
    AUTH_ENABLED = cfg.auth_enabled;
    if (AUTH_ENABLED) {
      if (!window.supabase || !cfg.supabase_url || !cfg.supabase_anon_key) {
        window.location.href = "/login";
        return;
      }
      SB = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key);
      const { data } = await SB.auth.getSession();
      if (!data.session) {
        window.location.href = "/login";
        return;
      }
      if (logoutBtn) logoutBtn.style.display = "";
    }
    loadDashboard();
  } catch (e) {
    toast(e.message, true);
  }
}

boot();

"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

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
  if (!res.ok) throw new Error(data.detail || "Request failed: " + res.status);
  return data;
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isError ? " err" : "");
  setTimeout(() => (t.className = "toast"), 2600);
}

function initials(name) {
  const parts = String(name || "").split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// ── Lead-score component (design system v1.0) ───────────────────────────────
function tierInfo(score) {
  const s = Number(score) || 0;
  if (s >= 85) return { word: "Excellent fit", seg: "", wordLow: false, band: "A" };
  if (s >= 70) return { word: "Strong", seg: "", wordLow: false, band: "A" };
  if (s >= 55) return { word: "Worth a look", seg: "mid", wordLow: true, band: "B" };
  return { word: "Low", seg: "low", wordLow: true, band: "C" };
}
function segsHtml(score, sizeCls = "") {
  const { seg } = tierInfo(score);
  const filled = Math.max(0, Math.min(5, Math.round((Number(score) || 0) / 20))); // round per DS examples
  let h = `<div class="segs ${sizeCls}">`;
  for (let i = 0; i < 5; i++) h += `<span class="seg ${i < filled ? "on " + seg : ""}"></span>`;
  return h + "</div>";
}
function scoreBlock(score) {
  const t = tierInfo(score);
  return `<div class="score-head"><span class="score-num">${score ?? "—"}</span>
    <span class="score-tier ${t.wordLow ? "low" : ""}">${t.word}</span></div>${segsHtml(score)}`;
}
function miniScore(score) {
  const t = tierInfo(score);
  const pct = Math.max(0, Math.min(100, Number(score) || 0));
  return `<div class="score-mini">
    <div class="score-head" style="margin-bottom:5px"><span class="score-num sm">${score ?? "—"}</span>
      <span class="score-tier sm ${t.wordLow ? "low" : ""}">${t.word}</span></div>
    <div class="bar-track"><div class="bar-fill ${t.seg}" style="width:${pct}%"></div></div></div>`;
}
// Ring variant for the lead-detail drawer (design system: r=50, stroke 10, −90°).
function scoreRing(score) {
  const t = tierInfo(score);
  const pct = Math.max(0, Math.min(100, Number(score) || 0));
  const C = 2 * Math.PI * 50; // circumference, r=50
  const offset = C * (1 - pct / 100);
  return `<div class="score-ring">
    <svg viewBox="0 0 120 120">
      <circle class="ring-track" cx="60" cy="60" r="50" fill="none" stroke-width="10"/>
      <circle class="ring-fill ${t.seg}" cx="60" cy="60" r="50" fill="none" stroke-width="10"
        stroke-linecap="round" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
        transform="rotate(-90 60 60)"/>
      <text class="ring-num" x="60" y="57" text-anchor="middle">${score ?? "—"}</text>
      <text class="ring-word ${t.wordLow ? "low" : ""}" x="60" y="76" text-anchor="middle">${t.word.toUpperCase()}</text>
    </svg></div>`;
}
const avatarHue = (i) => ["", "slate", "neutral"][i % 3];

// ── Theme ───────────────────────────────────────────────────────────────────
// THEME_CHOICE is the persisted preference: "light" | "dark" | "auto".
// applyTheme resolves "auto" to the OS setting and writes data-theme.
let THEME_CHOICE = "light";
const prefersDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function resolveTheme(choice) {
  if (choice === "auto") return prefersDark && prefersDark.matches ? "dark" : "light";
  return choice;
}
function applyTheme(choice) {
  THEME_CHOICE = choice === "auto" || choice === "dark" ? choice : "light";
  localStorage.setItem("leia-theme", THEME_CHOICE);
  document.documentElement.setAttribute("data-theme", resolveTheme(THEME_CHOICE));
  syncThemeControls();
}
function syncThemeControls() {
  $$("#theme-segmented .seg-opt").forEach((b) =>
    b.classList.toggle("active", b.dataset.themeMode === THEME_CHOICE)
  );
}
if (prefersDark) {
  prefersDark.addEventListener("change", () => {
    if (THEME_CHOICE === "auto")
      document.documentElement.setAttribute("data-theme", resolveTheme("auto"));
  });
}
// Sidebar quick-toggle: flip between the two resolved appearances.
$("#btn-theme").addEventListener("click", () =>
  applyTheme(resolveTheme(THEME_CHOICE) === "dark" ? "light" : "dark")
);
$$("#theme-segmented .seg-opt").forEach((b) =>
  b.addEventListener("click", () => applyTheme(b.dataset.themeMode))
);

// ── Navigation ───────────────────────────────────────────────────────────────
function showView(name) {
  $$(".nav-item[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  if (name === "today") loadToday();
  if (name === "prospects") loadProspects();
  if (name === "outreach") loadOutreach();
  if (name === "analytics") loadAnalytics();
  if (name === "settings") { loadIcp(); loadSettings(); }
}
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-view]");
  if (el) showView(el.dataset.view);
});

// ── Today ─────────────────────────────────────────────────────────────────────
let TODAY_MODE = "a";
function spark(values) {
  const max = Math.max(1, ...values);
  const n = values.length || 1;
  const pts = values.map((v, i) => `${(2 + i * (74 / (n - 1 || 1))).toFixed(0)} ${(28 - (v / max) * 23).toFixed(0)}`);
  return `<svg class="spark" viewBox="0 0 78 30" fill="none"><path d="M${pts.join(" L")}"/></svg>`;
}

async function loadToday() {
  try {
    const [st, stats, approvals, hist, convos] = await Promise.all([
      api("/api/status"), api("/api/stats"), api("/api/approvals"), api("/api/history"),
      api("/api/conversations").catch(() => []),
    ]);
    setPending(approvals.length);
    const hour = new Date().getHours();
    $("#today-greeting").textContent =
      (hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening") +
      (window.LEIA_NAME ? ", " + window.LEIA_NAME : "");
    $("#today-date").textContent = new Date().toLocaleDateString("en-GB", {
      weekday: "long", day: "numeric", month: "long",
    });

    const mk = stats.kpis && stats.kpis.meetings_booked;
    const cards = [
      { label: "To contact today", num: st.tiles.queued, spark: stats.sent,
        delta: st.tiles.queued ? "in your review queue" : "queue is clear", flat: true },
      { label: "Replies waiting", num: convos.length, spark: stats.kpis && stats.kpis.reply_rate.spark,
        delta: convos.length ? "need your reply" : "all caught up", flat: convos.length === 0 },
      { label: "Meetings booked", num: mk ? mk.value : 0, spark: mk && mk.spark,
        delta: mk ? deltaText(mk.delta, "").txt : "—", flat: !mk || !mk.delta },
    ];
    $("#today-stats").innerHTML = cards
      .map(
        (c) => `<div class="stat"><div class="stat-label">${c.label}</div>
        <div class="stat-row"><div class="stat-num">${c.num}</div>${c.spark ? spark(c.spark) : ""}</div>
        <div class="stat-delta ${c.flat ? "flat" : ""}">${c.delta}</div></div>`
      )
      .join("");

    // Contact today — the pending review drafts, highest score first.
    const list = [...approvals].sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 6);
    $("#contact-today").innerHTML = list.length
      ? list
          .map(
            (c, i) => `<div class="row click" data-go-outreach="1">
        <span class="avatar ${avatarHue(i)}" style="width:38px;height:38px">${esc(c.initials)}</span>
        <div class="grow"><div class="who">${esc(c.full_name)}</div>
          <div class="meta">${esc([c.headline, c.company_name].filter(Boolean).join(" · ")) || "—"}</div></div>
        ${miniScore(c.score)}
        <button class="btn inline" data-go-outreach="1">Review</button></div>`
          )
          .join("")
      : `<div class="row"><span class="muted">Nothing to review yet. Find prospects in Settings, then approve drafts here.</span></div>`;
    $$("#contact-today [data-go-outreach]").forEach((el) =>
      el.addEventListener("click", () => showView("outreach"))
    );

    // Activity feed — recent outreach log.
    const feed = hist.slice(0, 6);
    $("#activity-feed").innerHTML = feed.length
      ? feed
          .map((r) => {
            const dot = r.event === "replied" ? "green" : r.event === "sent" ? "amber" : "mid";
            return `<div class="feed-item"><span class="feed-dot ${dot}"></span>
          <div><div class="feed-text">${esc(r.full_name)} <span>· ${esc(r.event)}${r.company_name ? " · " + esc(r.company_name) : ""}</span></div>
          <div class="feed-time">${r.occurred_at ? new Date(r.occurred_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</div></div></div>`;
          })
          .join("")
      : `<span class="muted">No activity yet.</span>`;

    // layout A/B toggle
    applyTodayMode();
  } catch (e) {
    toast(e.message, true);
  }
}
function applyTodayMode() {
  const focus = TODAY_MODE === "b";
  $("#today-stats").style.display = focus ? "none" : "";
  $("#today-cols").style.gridTemplateColumns = focus ? "1fr" : "1.55fr 1fr";
  $$("#today-cols > .card")[1].style.display = focus ? "none" : "";
  $("#today-layout").textContent = focus ? "Full view" : "Focus view";
}
$("#today-layout").addEventListener("click", () => {
  TODAY_MODE = TODAY_MODE === "a" ? "b" : "a";
  applyTodayMode();
});

// ── Prospects ───────────────────────────────────────────────────────────────
let PROSPECTS = [];
let SCORE_FILTER = "all", STATUS_FILTER = "all", INDUSTRY_FILTER = "all";
let SEARCH = "";
async function loadProspects() {
  try {
    PROSPECTS = await api("/api/prospects");
    populateIndustries();
    renderProspects();
  } catch (e) {
    toast(e.message, true);
  }
}
function populateIndustries() {
  const sel = $("#filter-industry");
  if (!sel) return;
  const inds = Array.from(new Set(PROSPECTS.map((p) => p.industry).filter(Boolean))).sort();
  const cur = sel.value;
  sel.innerHTML =
    `<option value="all">Any industry</option>` +
    inds.map((i) => `<option value="${esc(i)}">${esc(i)}</option>`).join("");
  sel.value = inds.includes(cur) ? cur : "all";
}
function renderProspects() {
  const q = SEARCH.trim().toLowerCase();
  const filtered = SCORE_FILTER !== "all" || STATUS_FILTER !== "all" || INDUSTRY_FILTER !== "all" || q;
  const rows = PROSPECTS.filter((p) => {
    if (SCORE_FILTER !== "all" && tierInfo(p.score).band !== SCORE_FILTER) return false;
    if (STATUS_FILTER !== "all" && (p.status || "New") !== STATUS_FILTER) return false;
    if (INDUSTRY_FILTER !== "all" && p.industry !== INDUSTRY_FILTER) return false;
    if (!q) return true;
    return [p.full_name, p.company_name].some((v) => String(v || "").toLowerCase().includes(q));
  });
  const count = $("#prospect-count");
  if (count) {
    const nw = PROSPECTS.filter((p) => (p.status || "New") === "New").length;
    count.textContent = PROSPECTS.length
      ? `${rows.length} of ${PROSPECTS.length} lead${PROSPECTS.length === 1 ? "" : "s"} · ${nw} new`
      : "";
  }
  const grid = $("#prospect-grid");
  if (!rows.length) {
    grid.innerHTML = filtered
      ? `<div class="card"><span class="muted">No matching prospects.</span></div>`
      : `<div class="card"><span class="muted">No prospects yet. Click “Find more leads” to get started.</span></div>`;
    return;
  }
  grid.innerHTML = rows
    .map((p, i) => {
      const status = p.status || "New";
      const cls = status === "Replied" ? "green" : status === "Contacted" ? "amber" : "";
      const sigs = (p.signals || [])
        .slice(0, 3)
        .map((s) => `<span class="pill">${esc(s)}</span>`)
        .join("");
      return `<div class="lead-card" data-id="${esc(p.id)}">
        <div class="head"><span class="avatar ${avatarHue(i)}">${esc(p.initials)}</span>
          <div class="grow"><div class="name">${esc(p.full_name)}</div>
            <div class="role">${esc([p.title || p.headline, p.company_name].filter(Boolean).join(" · ")) || "—"}</div></div>
          <span class="pill ${cls}">${esc(status)}</span></div>
        ${scoreBlock(p.score)}
        ${sigs ? `<div class="sigs">${sigs}</div>` : ""}</div>`;
    })
    .join("");
  $$("#prospect-grid .lead-card").forEach((el) =>
    el.addEventListener("click", () => openDrawer(el.dataset.id))
  );
}
// Analytics range selector → reloads the stats for that window.
let ANALYTICS_PERIOD = "7d";
$$("#analytics-range .seg-opt").forEach((b) =>
  b.addEventListener("click", () => {
    $$("#analytics-range .seg-opt").forEach((x) => x.classList.toggle("active", x === b));
    ANALYTICS_PERIOD = b.dataset.range + "d";
    loadAnalytics();
  })
);

$("#filter-score").addEventListener("change", (e) => { SCORE_FILTER = e.target.value; renderProspects(); });
$("#filter-status").addEventListener("change", (e) => { STATUS_FILTER = e.target.value; renderProspects(); });
$("#filter-industry").addEventListener("change", (e) => { INDUSTRY_FILTER = e.target.value; renderProspects(); });
$("#prospect-search").addEventListener("input", (e) => {
  SEARCH = e.target.value;
  renderProspects();
});

// Re-score every enriched prospect against the current ICP, in place.
$("#btn-rescore").addEventListener("click", async () => {
  const btn = $("#btn-rescore"), orig = btn.innerHTML;
  let dryRun = false;
  try {
    const st = await api("/api/status");
    dryRun = !(st.keys && st.keys.anthropic);
  } catch (e) { /* fall back to a real run; the API will report if a key is missing */ }
  const n = PROSPECTS.filter((p) => p.score !== null && p.score !== undefined).length;
  const msg = dryRun
    ? "No Anthropic key set — re-score with the free heuristic (stub) brain?"
    : `Re-score ${n || "all"} prospect(s) against the current ICP with Claude? This costs one scoring call each.`;
  if (!confirm(msg)) return;
  btn.disabled = true;
  btn.textContent = "Re-scoring…";
  try {
    const r = await api("/api/rescore", "POST", { dry_run: dryRun });
    const scored = (r.counts && r.counts.scored) || 0;
    await loadProspects();
    toast(`Re-scored ${scored} prospect(s)` + (r.dry_run ? " (heuristic)" : ` · $${(r.cost_usd || 0).toFixed(4)}`));
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
});

// ── Lead detail (slide-over) ──────────────────────────────────────────────────
function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer-backdrop").classList.remove("open");
}
$("#drawer-backdrop").addEventListener("click", closeDrawer);
async function openDrawer(id) {
  try {
    const d = await api("/api/prospects/" + encodeURIComponent(id));
    const role = [d.title || d.headline, d.company_name].filter(Boolean).join(" · ");
    const outreach = (d.outreach || [])
      .map(
        (o) => `<div class="row"><div class="grow"><div class="who" style="font-size:13px">${esc(o.subject || o.channel)}</div>
        <div class="meta">${esc(o.channel)} · ${esc(o.event)}</div></div>
        <span class="meta">${o.occurred_at ? new Date(o.occurred_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : ""}</span></div>`
      )
      .join("");
    $("#drawer-body").innerHTML = `
      <div class="drawer-top"><span class="avatar" style="width:48px;height:48px;font-size:16px">${esc(d.initials)}</span>
        <div><div style="font:600 20px/1.2 'Schibsted Grotesk'">${esc(d.full_name)}</div>
          <div class="meta">${esc(role) || "—"}</div></div></div>
      <div class="detail-block" style="display:flex; align-items:center; gap:24px; flex-wrap:wrap">
        ${scoreRing(d.score)}<div style="flex:1; min-width:160px">${scoreBlock(d.score)}</div></div>
      ${d.rationale ? `<div class="detail-block"><h4>Why they fit</h4><div class="detail-text">${esc(d.rationale)}</div></div>` : ""}
      ${
        (d.matched_criteria || []).length
          ? `<div class="detail-block"><h4>Matched</h4><div class="sigs" style="display:flex;gap:6px;flex-wrap:wrap">${d.matched_criteria
              .map((m) => `<span class="pill amber">${esc(m)}</span>`)
              .join("")}</div></div>`
          : ""
      }
      <div class="detail-block"><h4>Signals</h4><div class="detail-text">${esc(d.signal_summary) || "—"}</div></div>
      ${d.email ? `<div class="detail-block"><h4>Contact</h4><div class="detail-text">${esc(d.email)} <span class="muted">(${esc(d.email_status)})</span></div></div>` : ""}
      <div class="detail-block"><h4>Outreach so far</h4>${outreach || `<div class="detail-text">No outreach yet.</div>`}</div>`;
    $("#drawer-foot").innerHTML = d.pending
      ? `<button class="btn primary full" id="drawer-action">Review the draft →</button>`
      : `<button class="btn secondary full" id="drawer-close">Close</button>`;
    $("#drawer").classList.add("open");
    $("#drawer-backdrop").classList.add("open");
    const act = $("#drawer-action");
    if (act) act.addEventListener("click", () => { closeDrawer(); showView("outreach"); });
    const cl = $("#drawer-close");
    if (cl) cl.addEventListener("click", closeDrawer);
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Outreach review queue ─────────────────────────────────────────────────────
let QUEUE = [];
let QI = 0;
let EDITING = false;
async function loadOutreach() {
  try {
    QUEUE = await api("/api/approvals");
    setPending(QUEUE.length);
    QI = 0;
    EDITING = false;
    renderOutreach();
    loadConversations();
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadConversations() {
  try {
    const convos = await api("/api/conversations");
    const section = $("#conversations-section");
    const host = $("#conversations-host");
    if (!convos.length) {
      section.style.display = "none";
      host.innerHTML = "";
      return;
    }
    section.style.display = "block";
    host.innerHTML = convos
      .map((c) => {
        const intent = (c.last_intent || (c.is_opener ? "opener" : "reply")).replace(/_/g, " ");
        const their = c.their_message
          ? `<div class="conv-quote them"><strong>Them:</strong> ${esc(c.their_message)}</div>`
          : "";
        const draft = c.draft_reply
          ? `<div class="conv-draft">${esc(c.draft_reply)}</div>`
          : `<div class="muted">No draft yet.</div>`;
        return `<div class="conv-card">
          <div class="conv-top"><span class="avatar" style="width:34px;height:34px;font-size:12px">${esc(initials(c.name))}</span>
            <div class="grow"><div class="conv-name">${esc(c.name)}</div>
              <div class="conv-meta">${esc([c.company, c.channel].filter(Boolean).join(" · ")) || "—"}</div></div>
            <span class="intent-pill">${esc(intent)}</span></div>
          ${their}${draft}
          <div class="conv-actions">
            <button class="btn primary" data-conv-send="${esc(c.thread_id)}">Approve &amp; send</button>
            <button class="btn secondary" data-conv-booked="${esc(c.thread_id)}">Mark booked</button>
          </div></div>`;
      })
      .join("");
    $$("#conversations-host [data-conv-send]").forEach((b) =>
      b.addEventListener("click", () => convAction(b.dataset.convSend, "send"))
    );
    $$("#conversations-host [data-conv-booked]").forEach((b) =>
      b.addEventListener("click", () => convAction(b.dataset.convBooked, "mark-booked"))
    );
  } catch (e) {
    /* conversations are an optional surface — never block the review queue */
  }
}

async function convAction(tid, action) {
  try {
    await api(`/api/conversations/${tid}/${action}`, "POST", {});
    toast(action === "send" ? "Sent" : "Marked booked");
    loadConversations();
  } catch (e) {
    toast(e.message, true);
  }
}
function renderOutreach() {
  const host = $("#msg-host");
  const rail = $("#queue-list");
  if (!QUEUE.length) {
    $("#outreach-progress").textContent = "Nothing waiting";
    host.innerHTML = `<div class="msg-card"><div class="empty-state"><div><p>Your queue is clear.</p>
      <small>Find prospects in Settings, then approved drafts appear here one at a time.</small></div></div></div>`;
    rail.innerHTML = "";
    return;
  }
  if (QI >= QUEUE.length) QI = QUEUE.length - 1;
  const c = QUEUE[QI];
  const isEmail = c.channel === "email";
  $("#outreach-progress").textContent = `Message ${QI + 1} of ${QUEUE.length} · drafted for you`;

  const bodyView = EDITING
    ? `${isEmail ? `<input type="text" id="ed-subject" value="${esc(c.subject)}">` : ""}
       <textarea id="ed-body" rows="9">${esc(c.body)}</textarea>`
    : `${isEmail && c.subject ? `<div class="msg-subject">${esc(c.subject)}</div>` : ""}
       <div class="msg-body">${esc(c.body)}</div>`;

  host.innerHTML = `<div class="msg-card">
    <div class="msg-to"><span class="avatar">${esc(c.initials)}</span>
      <div class="grow"><div class="who">To ${esc(c.full_name)}</div>
        <div class="meta">${esc([c.headline, c.company_name].filter(Boolean).join(" · ")) || "—"}</div></div>
      <span class="pill amber">Score ${c.score ?? "—"}</span></div>
    ${bodyView}
    <div class="tone"><span class="tone-label">Adjust tone</span>
      <span class="tone-chip" data-adjust="warmer">Warmer</span><span class="tone-chip" data-adjust="shorter">Shorter</span><span class="tone-chip" data-adjust="more_direct">More direct</span></div>
    <div class="msg-actions">
      <button class="btn primary" id="btn-approve">Approve &amp; send
        <svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 11h13M12 6l5 5-5 5"/></svg></button>
      <button class="btn secondary" id="btn-edit">${EDITING ? "Done" : "Edit"}</button>
      <button class="btn text" id="btn-reject">Not a fit</button>
      <button class="btn text" id="btn-skip" style="margin-left:auto">Skip</button>
    </div></div>`;

  rail.innerHTML = QUEUE.map(
    (q, i) => `<div class="q-item ${i < QI ? "done" : i === QI ? "current" : ""}" data-i="${i}">
      <span class="q-dot"></span><span class="q-name">${esc(q.full_name)}${i < QI ? " · done" : ""}</span></div>`
  ).join("");
  $$("#queue-list .q-item").forEach((el) =>
    el.addEventListener("click", () => { QI = Number(el.dataset.i); EDITING = false; renderOutreach(); })
  );

  $("#btn-edit").addEventListener("click", () => { EDITING = !EDITING; renderOutreach(); });
  $("#btn-skip").addEventListener("click", () => { QI = Math.min(QUEUE.length - 1, QI + 1); EDITING = false; renderOutreach(); });
  $("#btn-approve").addEventListener("click", () => decide(c, "approve"));
  $("#btn-reject").addEventListener("click", () => decide(c, "reject"));
  $$("#msg-host .tone-chip").forEach((ch) =>
    ch.addEventListener("click", () => retone(c, ch.dataset.adjust))
  );
}

async function retone(c, adjustment) {
  const chips = $$("#msg-host .tone-chip");
  chips.forEach((ch) => ch.classList.add("busy"));
  toast("Adjusting tone…");
  try {
    const r = await api(`/api/approvals/${c.id}/retone`, "POST", { adjustment });
    const idx = QUEUE.findIndex((x) => x.id === c.id);
    if (idx >= 0) { QUEUE[idx].subject = r.subject; QUEUE[idx].body = r.body; }
    EDITING = false;
    renderOutreach();
    toast("Tone updated");
  } catch (e) {
    toast(e.message, true);
    chips.forEach((ch) => ch.classList.remove("busy"));
  }
}
async function decide(c, action) {
  try {
    if (action === "approve") {
      const body = {};
      if (EDITING) {
        const sub = $("#ed-subject"), bod = $("#ed-body");
        if (sub && sub.value !== (c.subject || "")) body.edited_subject = sub.value;
        if (bod && bod.value !== (c.body || "")) body.edited_body = bod.value;
      }
      await api(`/api/approvals/${c.id}/approve`, "POST", body);
      // Approve & send: dispatch the now-approved draft right away.
      try {
        const r = await api("/api/send", "POST", { dry_run: false });
        const n = (r.counts && r.counts.sent) || 0;
        toast(n ? "Approved & sent" : "Approved — will send shortly");
      } catch (e) {
        toast("Approved (sending shortly)");
      }
    } else {
      await api(`/api/approvals/${c.id}/reject`, "POST", {});
      toast("Marked not a fit");
    }
    QUEUE = QUEUE.filter((x) => x.id !== c.id);
    setPending(QUEUE.length);
    EDITING = false;
    renderOutreach();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Analytics ─────────────────────────────────────────────────────────────────
function areaChart(values, labels) {
  const W = 620, H = 150, pad = 10;
  const max = Math.max(1, ...values);
  const n = values.length;
  const X = (i) => pad + i * ((W - 2 * pad) / (n - 1 || 1));
  const Y = (v) => pad + (1 - v / max) * (H - 2 * pad);
  const pts = values.map((v, i) => `${X(i).toFixed(0)} ${Y(v).toFixed(0)}`);
  const line = "M" + pts.join(" L");
  const area = `${line} L${X(n - 1).toFixed(0)} ${H - pad} L${pad} ${H - pad} Z`;
  const grid = [0.25, 0.5, 0.75]
    .map((g) => `<line x1="${pad}" y1="${(pad + g * (H - 2 * pad)).toFixed(0)}" x2="${W - pad}" y2="${(pad + g * (H - 2 * pad)).toFixed(0)}"/>`)
    .join("");
  const ticks = labels
    .map((l, i) => `<text class="chart-tick" x="${X(i).toFixed(0)}" y="${H + 4}" text-anchor="middle">${esc(l)}</text>`)
    .join("");
  return `<svg class="chart-svg" viewBox="0 0 ${W} ${H + 16}" fill="none">
    <g class="chart-grid">${grid}<line class="base" x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}"/></g>
    <path class="chart-area" d="${area}"/><path class="chart-line" d="${line}"/>
    <circle cx="${X(n - 1).toFixed(0)}" cy="${Y(values[n - 1]).toFixed(0)}" r="4" fill="var(--amber)"/>
    ${ticks}</svg>`;
}
function deltaText(delta, suffix) {
  if (!delta) return { cls: "flat", txt: "No change vs previous" };
  const up = delta > 0;
  return { cls: up ? "" : "down", txt: `${up ? "↑" : "↓"} ${Math.abs(delta)}${suffix || ""} vs previous` };
}
function kpiCard(label, kpi) {
  const d = deltaText(kpi.delta, kpi.suffix);
  return `<div class="kpi"><div class="kpi-label">${label}</div>
    <div class="kpi-mid"><div class="kpi-num">${kpi.value}${kpi.suffix || ""}</div>${spark(kpi.spark || [])}</div>
    <div class="kpi-delta ${d.cls}">${d.txt}</div></div>`;
}
async function loadAnalytics() {
  try {
    const stats = await api("/api/stats?period=" + ANALYTICS_PERIOD);
    const k = stats.kpis;
    $("#kpi-row").innerHTML =
      kpiCard("Reply rate", k.reply_rate) +
      kpiCard("Meetings booked", k.meetings_booked) +
      kpiCard("Avg lead score", k.avg_lead_score);

    $("#chart-activity").innerHTML = areaChart(stats.sent, stats.labels);
    const totalSent = stats.sent.reduce((a, b) => a + b, 0);
    $("#activity-context").textContent = totalSent
      ? `${totalSent} message${totalSent === 1 ? "" : "s"} sent in this period`
      : "No messages sent yet in this period";

    const rr = stats.reply_rate_trend;
    $("#chart-replyrate").innerHTML = areaChart(rr.values, rr.labels);

    const pmax = Math.max(1, ...stats.pipeline.map((p) => p.count));
    $("#pipeline").innerHTML = stats.pipeline
      .map(
        (p) => `<div class="pipe-row"><span class="lbl">${esc(p.stage)}</span>
        <div class="bar-wrap"><span class="bar" style="width:${Math.max(2, (p.count / pmax) * 100)}%"></span>
        <span class="val">${p.count}</span></div></div>`
      )
      .join("");

    const dmax = Math.max(1, ...stats.score_distribution.map((d) => d.count));
    $("#distribution").innerHTML =
      `<div class="dist">` +
      stats.score_distribution
        .map((d, i) => {
          const cls = i <= 1 ? "low" : i === 2 ? "mid" : "";
          return `<div class="dist-col"><span class="dist-val">${d.count}</span>
            <div class="dist-bar ${cls}" style="height:${Math.max(3, (d.count / dmax) * 116)}px"></div>
            <span class="dist-lbl">${esc(d.band)}</span></div>`;
        })
        .join("") +
      `</div>`;
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Settings: ICP / run / send / export / keys ─────────────────────────────────
const linesOf = (arr) => (arr || []).join("\n");
const parseLines = (s) => s.split("\n").map((x) => x.trim()).filter(Boolean);

async function loadIcp() {
  try {
    const [icp, st] = await Promise.all([api("/api/config/icp"), api("/api/status")]);
    $("#icp-name").value = icp.name || "";
    $("#icp-industries").value = linesOf(icp.industries);
    $("#icp-titles").value = linesOf(icp.titles);
    $("#icp-geographies").value = linesOf(icp.geographies);
    $("#icp-keywords").value = linesOf(icp.keywords);
    $("#icp-exclude").value = linesOf(icp.exclude);
    $("#icp-size-min").value = icp.company_size?.min ?? "";
    $("#icp-size-max").value = icp.company_size?.max ?? "";
    $("#icp-threshold").value = icp.score_threshold ?? 60;
    renderKeys(st.keys);
  } catch (e) {
    toast(e.message, true);
  }
}
function renderKeys(keys) {
  const names = { anthropic: "Anthropic", lusha: "Lusha", instantly: "Instantly", apify: "Apify", unipile: "Unipile" };
  $("#key-status").innerHTML = Object.entries(names)
    .map(
      ([k, label]) =>
        `<div class="key-row"><span class="key-dot ${keys[k] ? "on" : "off"}"></span>${label}
        <span class="ks">${keys[k] ? "connected" : "not set"}</span></div>`
    )
    .join("");
}
// ── Settings: runtime knobs (always-ask, kill switch, cap, tone, signals) ──
let SETTINGS = {};
let TONE_OPTIONS = [];
const TOGGLE_KEYS = [
  "always_ask", "outreach_paused", "research_web_enabled",
  "signal_hiring_funding", "signal_new_website", "signal_contract_renewal",
];
async function loadSettings() {
  try {
    const r = await api("/api/settings");
    SETTINGS = r.settings || {};
    TONE_OPTIONS = r.tone_options || [];
    renderSettings();
  } catch (e) {
    toast(e.message, true);
  }
}
function renderSettings() {
  TOGGLE_KEYS.forEach((k) => {
    const el = $("#set-" + k);
    if (!el) return;
    el.classList.toggle("on", !!SETTINGS[k]);
    el.setAttribute("aria-checked", String(!!SETTINGS[k]));
  });
  const cap = $("#set-daily_send_cap");
  if (cap) cap.textContent = SETTINGS.daily_send_cap ?? 25;
  const sel = $("#set-default_tone");
  if (sel) {
    sel.innerHTML = TONE_OPTIONS.map(
      (o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`
    ).join("");
    sel.value = SETTINGS.default_tone || "warm_concise";
  }
}
async function saveSetting(key, value, rowEl) {
  try {
    const r = await api("/api/settings", "PUT", { settings: { [key]: value } });
    SETTINGS = r.settings || SETTINGS;
    renderSettings();
    if (rowEl) { rowEl.classList.remove("saved"); void rowEl.offsetWidth; rowEl.classList.add("saved"); }
    toast("Saved");
  } catch (e) {
    toast(e.message, true);
    loadSettings();
  }
}
TOGGLE_KEYS.forEach((k) => {
  const el = $("#set-" + k);
  if (el) el.addEventListener("click", () => saveSetting(k, !SETTINGS[k], el.closest(".setting-row")));
});
if ($("#cap-minus"))
  $("#cap-minus").addEventListener("click", () =>
    saveSetting("daily_send_cap", Math.max(0, (SETTINGS.daily_send_cap || 25) - 5), $("#cap-minus").closest(".setting-row"))
  );
if ($("#cap-plus"))
  $("#cap-plus").addEventListener("click", () =>
    saveSetting("daily_send_cap", (SETTINGS.daily_send_cap || 25) + 5, $("#cap-plus").closest(".setting-row"))
  );
if ($("#set-default_tone"))
  $("#set-default_tone").addEventListener("change", (e) =>
    saveSetting("default_tone", e.target.value, e.target.closest(".setting-row"))
  );

$("#btn-save-icp").addEventListener("click", async () => {
  try {
    await api("/api/config/icp", "PUT", {
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
    });
    toast("Profile saved");
  } catch (e) {
    toast(e.message, true);
  }
});

$("#run-source").addEventListener("change", (e) => {
  $("#row-csv").style.display = e.target.value === "manual_csv" ? "block" : "none";
  $("#row-dataset").style.display = e.target.value === "apify_linkedin" ? "block" : "none";
});
$("#btn-run").addEventListener("click", async () => {
  const btn = $("#btn-run"), orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  $("#run-result").innerHTML = "";
  try {
    const r = await api("/api/run", "POST", {
      source: $("#run-source").value,
      dry_run: $("#run-dry").checked,
      limit: Number($("#run-limit").value) || null,
      input_csv: $("#run-csv").value,
      dataset: $("#run-dataset").value,
    });
    $("#run-result").innerHTML = `<table>
      <tr><td>Prospects ingested</td><td>${r.ingest.prospects}</td></tr>
      <tr><td>Enriched with email</td><td>${r.enrich.enriched}</td></tr>
      <tr><td>Scored</td><td>${r.score.scored}</td></tr>
      <tr><td>Drafts written</td><td>${r.draft.drafted}</td></tr>
      <tr><td>Queued for review</td><td>${r.enqueue.queued}</td></tr>
      <tr><td>Claude cost</td><td>$${r.total_cost_usd.toFixed(4)}</td></tr></table>
      ${(r.notes || []).map((n) => `<p class="muted">• ${esc(n)}</p>`).join("")}`;
    toast(`Done — ${r.enqueue.queued} draft(s) queued`);
  } catch (e) {
    toast(e.message, true);
    $("#run-result").innerHTML = `<p class="muted">${esc(e.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
});

$("#btn-send").addEventListener("click", async () => {
  const btn = $("#btn-send"), orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    const r = await api("/api/send", "POST", { dry_run: $("#send-dry").checked });
    $("#send-result").innerHTML = `<table>
      <tr><td>Sent</td><td>${r.counts.sent || 0}</td></tr>
      <tr><td>Failed</td><td>${r.counts.failed || 0}</td></tr></table>
      ${r.dry_run ? `<p class="muted">Dry-run: nothing actually left the building.</p>` : ""}`;
    toast(`Sent ${r.counts.sent || 0}`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
});

// ── Run outreach modal (P0) ───────────────────────────────────────────────────
let RM_FILE = null; // {path, rows, filename} after a successful upload, else null
let RM_RAW = null;  // the picked File before upload

function rmSource() {
  const sel = $('#run-modal input[name="rm-source"]:checked');
  return sel ? sel.value : "lusha_prospecting";
}
function rmSyncSourceRows() {
  const s = rmSource();
  $("#rm-csv-row").style.display = s === "manual_csv" ? "block" : "none";
  $("#rm-dataset-row").style.display = s === "apify_linkedin" ? "block" : "none";
}
function openRunModal() {
  // reset to a clean state each open
  $("#rm-result").style.display = "none";
  $("#rm-result").innerHTML = "";
  $("#rm-foot").style.display = "";
  $("#run-modal-body").style.display = "";
  rmSyncSourceRows();
  $("#run-modal-backdrop").classList.add("open");
  $("#run-modal").classList.add("open");
}
function closeRunModal() {
  $("#run-modal-backdrop").classList.remove("open");
  $("#run-modal").classList.remove("open");
}
$("#btn-open-run-today").addEventListener("click", openRunModal);
$("#btn-open-run-prospects").addEventListener("click", openRunModal);
$("#run-modal-close").addEventListener("click", closeRunModal);
$("#rm-cancel").addEventListener("click", closeRunModal);
$("#run-modal-backdrop").addEventListener("click", closeRunModal);
$$('#run-modal input[name="rm-source"]').forEach((r) =>
  r.addEventListener("change", rmSyncSourceRows)
);

// File picker + drop-zone
function rmSetFile(file) {
  RM_RAW = file || null;
  RM_FILE = null; // force a fresh upload on Run
  const dz = $("#rm-dropzone");
  const info = $("#rm-file-info");
  if (file) {
    $("#rm-file-label").textContent = file.name;
    dz.classList.add("has-file");
    info.style.display = "block";
    info.textContent = "Ready to upload on Run.";
  } else {
    $("#rm-file-label").textContent = "Choose a CSV file, or drop one here";
    dz.classList.remove("has-file");
    info.style.display = "none";
  }
}
$("#rm-file").addEventListener("change", (e) => {
  const f = e.target.files && e.target.files[0];
  rmSetFile(f || null);
});
const rmDz = $("#rm-dropzone");
["dragenter", "dragover"].forEach((ev) =>
  rmDz.addEventListener(ev, (e) => { e.preventDefault(); rmDz.classList.add("drag"); })
);
["dragleave", "drop"].forEach((ev) =>
  rmDz.addEventListener(ev, (e) => { e.preventDefault(); rmDz.classList.remove("drag"); })
);
rmDz.addEventListener("drop", (e) => {
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) { $("#rm-file").files = e.dataTransfer.files; rmSetFile(f); }
});

function readFileText(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(new Error("Could not read that file"));
    fr.readAsText(file);
  });
}

async function refreshAfterRun() {
  // Refresh whatever is currently relevant — these are all safe no-ops if empty.
  try { await loadToday(); } catch (e) { /* ignore */ }
  try {
    const approvals = await api("/api/approvals");
    setPending(approvals.length);
  } catch (e) { /* ignore */ }
}

$("#rm-run").addEventListener("click", async () => {
  const btn = $("#rm-run");
  const orig = btn.innerHTML;
  const inline = $("#rm-result");
  inline.style.display = "none";
  inline.innerHTML = "";
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    const source = rmSource();
    let inputCsv = null;

    if (source === "manual_csv") {
      if (!RM_RAW && !RM_FILE) throw new Error("Please choose a CSV file first");
      if (!RM_FILE) {
        const text = await readFileText(RM_RAW);
        const up = await api("/api/upload", "POST", { filename: RM_RAW.name, content: text });
        RM_FILE = up; // {path, rows, filename}
      }
      inputCsv = RM_FILE.path;
    }

    const dataset = source === "apify_linkedin" ? ($("#rm-dataset").value || null) : null;
    const limit = Number($("#rm-limit").value) || 5;

    const r = await api("/api/run", "POST", {
      source,
      dry_run: $("#rm-dry").checked,
      limit,
      input_csv: inputCsv,
      dataset,
    });

    $("#run-modal-body").style.display = "none";
    $("#rm-foot").style.display = "none";
    inline.style.display = "block";
    inline.innerHTML = `<div class="result">
      <table>
        <tr><td>People found</td><td>${r.ingest.prospects}</td></tr>
        <tr><td>Enriched with email</td><td>${r.enrich.enriched}</td></tr>
        <tr><td>Scored</td><td>${r.score.scored}</td></tr>
        <tr><td>Drafts written</td><td>${r.draft.drafted}</td></tr>
        <tr><td>Queued for review</td><td>${r.enqueue.queued}</td></tr>
        <tr><td>Claude cost</td><td>$${(r.total_cost_usd || 0).toFixed(4)}</td></tr>
      </table>
      ${(r.notes || []).map((n) => `<p class="muted">• ${esc(n)}</p>`).join("")}
      <button class="btn primary full" id="rm-review" style="margin-top:16px">Review drafts →</button>
    </div>`;
    $("#rm-review").addEventListener("click", () => { closeRunModal(); showView("outreach"); });
    await refreshAfterRun();
    toast(`Done — ${r.enqueue.queued} draft(s) queued`);
  } catch (e) {
    toast(e.message, true);
    inline.style.display = "block";
    inline.innerHTML = `<div class="result"><p class="muted">${esc(e.message)}</p></div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
});

$("#btn-export").addEventListener("click", async () => {
  const btn = $("#btn-export"), orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Exporting…";
  try {
    const res = await fetch("/api/export/prospects.csv", { headers: await authHeader() });
    if (res.status === 401) return (window.location.href = "/login");
    if (!res.ok) throw new Error("Export failed: " + res.status);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "leia-prospects.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Prospects exported");
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
});

// ── Shared ──────────────────────────────────────────────────────────────────
function setPending(n) {
  const b = $("#nav-pending");
  b.textContent = n;
  b.classList.toggle("zero", !n);
}
const logoutBtn = $("#btn-logout");
logoutBtn.addEventListener("click", async () => {
  if (SB) await SB.auth.signOut();
  window.location.href = "/login";
});

// ── Boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  applyTheme(localStorage.getItem("leia-theme") || "light");
  try {
    const cfg = await fetch("/api/public-config").then((r) => r.json());
    AUTH_ENABLED = cfg.auth_enabled;
    if (AUTH_ENABLED) {
      if (!window.supabase || !cfg.supabase_url || !cfg.supabase_anon_key)
        return (window.location.href = "/login");
      SB = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key);
      const { data } = await SB.auth.getSession();
      if (!data.session) return (window.location.href = "/login");
      logoutBtn.style.display = "";
      const email = data.session.user?.email || "";
      window.LEIA_NAME = email.split("@")[0].split(/[.\-_]/)[0].replace(/^\w/, (c) => c.toUpperCase());
      $("#user-name").textContent = email || "Signed in";
      $("#user-initials").textContent = initials(window.LEIA_NAME || email);
    } else {
      $("#user-name").textContent = "Local mode";
      $("#user-initials").textContent = "··";
    }
    loadToday();
  } catch (e) {
    toast(e.message, true);
  }
}
boot();

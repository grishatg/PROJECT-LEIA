"use strict";

const $ = (s) => document.querySelector(s);

async function boot() {
  const cfg = await fetch("/api/public-config").then((r) => r.json());
  // If auth isn't configured (local mode), there's nothing to log into.
  if (!cfg.auth_enabled) {
    window.location.href = "/";
    return;
  }
  if (!window.supabase || !cfg.supabase_url || !cfg.supabase_anon_key) {
    $("#login-msg").textContent =
      "Login isn't configured yet (missing Supabase settings). See DEPLOY.md.";
    return;
  }

  const sb = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key);

  // Already signed in? Go straight in.
  const { data: existing } = await sb.auth.getSession();
  if (existing.session) {
    window.location.href = "/";
    return;
  }

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#login-msg").textContent = "Signing in…";
    const { error } = await sb.auth.signInWithPassword({
      email: $("#email").value.trim(),
      password: $("#password").value,
    });
    if (error) {
      $("#login-msg").textContent = error.message;
      return;
    }
    window.location.href = "/";
  });
}

boot();

"""DB-backed runtime settings so the web Settings page survives redeploys.

Mirrors ``config_store.py`` (which persists the ICP). These are the knobs the user flips
in the UI — the "always ask" safety gate, the daily send limit, the default tone, which
signals to watch, the outreach kill switch, web research — stored in the ``app_config``
key/value table under a ``setting:`` prefix. Reads fall back to sensible defaults (aligned
with ``settings.toml`` and the storyboard) so a fresh install just works.

Everything is typed + validated here, so callers (the API, the tick) get clean values.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from leia.llm.tone import DEFAULT_TONE, TONES
from leia.models import AppConfig

_PREFIX = "setting:"

# key -> (type, default). Defaults match settings.toml + the storyboard's shown state.
_DEFS: dict[str, tuple[str, object]] = {
    "always_ask": ("bool", True),          # review every message — LEIA's core safety rule
    "outreach_paused": ("bool", False),    # kill switch: when on, the tick sends nothing
    "daily_send_cap": ("int", 25),
    "default_tone": ("tone", DEFAULT_TONE),
    "research_web_enabled": ("bool", False),
    # Signals to watch (storyboard: Hiring & funding ON, New website ON, Renewal OFF).
    "signal_hiring_funding": ("bool", True),
    "signal_new_website": ("bool", True),
    "signal_contract_renewal": ("bool", False),
}

_TRUE = {"1", "true", "yes", "on"}


def _truthy(val: object) -> bool:
    return val is True or str(val).strip().lower() in _TRUE


def _coerce(typ: str, raw: object, default: object) -> object:
    if typ == "bool":
        return _truthy(raw)
    if typ == "int":
        try:
            return max(0, min(int(raw), 1000))
        except (TypeError, ValueError):
            return default
    if typ == "tone":
        return raw if raw in TONES else default
    return raw


def get_runtime_settings(session: Session) -> dict:
    """Every runtime setting, typed, with defaults filled in."""
    rows = {
        r.key[len(_PREFIX):]: r.value
        for r in session.query(AppConfig).filter(AppConfig.key.like(_PREFIX + "%")).all()
    }
    out: dict = {}
    for key, (typ, default) in _DEFS.items():
        out[key] = _coerce(typ, rows[key], default) if key in rows else default
    return out


def save_runtime_settings(session: Session, updates: dict) -> dict:
    """Validate + persist a partial settings update; returns the full new settings."""
    for key, val in updates.items():
        if key not in _DEFS:
            continue  # ignore unknown keys — the API surface stays closed
        typ, default = _DEFS[key]
        coerced = _coerce(typ, val, default)
        sval = (
            ("true" if coerced else "false") if typ == "bool" else str(coerced)
        )
        dbkey = _PREFIX + key
        row = session.get(AppConfig, dbkey)
        if row:
            row.value = sval
        else:
            session.add(AppConfig(key=dbkey, value=sval))
    session.commit()
    return get_runtime_settings(session)

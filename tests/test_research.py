"""Research stage: per-prospect opener hooks (offline, free).

Covers the signal-derived researcher, the engine's ranking/safety, the pipeline
stage (populate + idempotent), and that the hook reaches the drafting facts.
"""

from __future__ import annotations

from leia.config import load_icp
from leia.llm.prompts import render_facts
from leia.models import Prospect, ResearchNote, ScoredLead, Signal
from leia.pipeline import _best_hook_text, build_facts, ensure_icp_row, research
from leia.research.base import ResearchHook, research_prospect
from leia.research.signal import SignalResearcher
from leia.research.stub import StubResearcher
from leia.schemas import ProspectFacts

FACTS = ProspectFacts(full_name="Aline Akpovi", company_name="Caudalie", title="CFO")


# ── SignalResearcher ────────────────────────────────────────────────────────


def test_signal_promotion_is_high_confidence():
    h = SignalResearcher().find_hook(
        FACTS, signal_source="lusha_signals", signal_raw={"signals": ["promotion"]}
    )
    assert h is not None
    assert h.confidence == "high"
    assert h.source == "signal"


def test_signal_jobchange_source_names_the_company():
    h = SignalResearcher().find_hook(FACTS, signal_source="jobchange", signal_raw={})
    assert h is not None
    assert "Caudalie" in h.text


def test_signal_hiring_hook_is_medium_and_keeps_url():
    h = SignalResearcher().find_hook(
        FACTS,
        signal_source="jobspy",
        signal_raw={"job_title": "Energy Manager", "job_url": "https://jobs/x"},
    )
    assert h is not None
    assert h.confidence == "medium"
    assert h.url == "https://jobs/x"


def test_signal_returns_none_without_a_signal():
    assert (
        SignalResearcher().find_hook(FACTS, signal_source="manual_csv", signal_raw={})
        is None
    )


# ── Engine ──────────────────────────────────────────────────────────────────


def test_engine_prefers_high_confidence():
    low = StubResearcher(ResearchHook(text="low one", source="a", confidence="low"))
    high = StubResearcher(ResearchHook(text="high one", source="b", confidence="high"))
    best = research_prospect(FACTS, researchers=[low, high])
    assert best is not None and best.text == "high one"


def test_engine_survives_a_researcher_that_raises():
    class Boom:
        name = "boom"

        def find_hook(self, *a, **k):
            raise RuntimeError("provider down")

    good = StubResearcher(ResearchHook(text="still works", source="b"))
    best = research_prospect(FACTS, researchers=[Boom(), good])
    assert best is not None and best.text == "still works"


def test_engine_returns_none_when_nothing_found():
    assert research_prospect(FACTS, researchers=[StubResearcher(None)]) is None


# ── render_facts ────────────────────────────────────────────────────────────


def test_render_facts_anchors_on_the_hook():
    out = render_facts(ProspectFacts(full_name="X", research_hook="They were promoted."))
    assert "They were promoted." in out
    assert "faithfully" in out.lower()


def test_render_facts_warns_against_faking_when_no_hook():
    out = render_facts(ProspectFacts(full_name="X"))
    assert "none found" in out.lower()
    assert "fake" in out.lower()


# ── Pipeline stage ──────────────────────────────────────────────────────────


def _seed(session, *, signals: dict):
    icp_row = ensure_icp_row(session, load_icp())
    sig = Signal(source="lusha_signals", dedupe_key="sig-1", raw_json=signals)
    session.add(sig)
    session.flush()
    prospect = Prospect(
        full_name="Aline Akpovi",
        company_name="Caudalie",
        dedupe_key="pro-1",
        origin_signal_id=sig.id,
    )
    session.add(prospect)
    session.flush()
    session.add(ScoredLead(prospect_id=prospect.id, icp_id=icp_row.id, score=85, tier="A"))
    session.commit()
    return icp_row, prospect


def test_research_stage_populates_and_is_idempotent(session):
    icp_row, prospect = _seed(session, signals={"signals": ["promotion"]})

    rep = research(session, [SignalResearcher()], icp_row, threshold=60)
    assert rep.counts["researched"] == 1
    note = session.query(ResearchNote).filter_by(prospect_id=prospect.id).one()
    assert note.confidence == "high"

    # Re-running never re-pays for a prospect we've already researched.
    rep2 = research(session, [SignalResearcher()], icp_row, threshold=60)
    assert rep2.counts["researched"] == 0


def test_hook_flows_into_draft_facts(session):
    icp_row, prospect = _seed(session, signals={"signals": ["promotion"]})
    research(session, [SignalResearcher()], icp_row, threshold=60)

    hook = _best_hook_text(session, prospect.id, "local")
    facts = build_facts(prospect, None, research_hook=hook)
    assert facts.research_hook
    assert "faithfully" in render_facts(facts).lower()


def test_research_stage_noop_without_researchers(session):
    icp_row, _ = _seed(session, signals={"signals": ["promotion"]})
    assert research(session, [], icp_row, threshold=60).counts["researched"] == 0


# ── WebResearcher (paid path, exercised offline with fakes) ──────────────────


def test_web_researcher_uses_injected_search_fn():
    from leia.research.web import WebResearcher

    hook = ResearchHook(
        text="Opened a new Leeds DC", source="web", url="https://x", confidence="medium"
    )
    out = WebResearcher(lambda facts: hook).find_hook(FACTS)
    assert out is hook


def test_web_researcher_skips_when_no_company():
    from leia.research.web import WebResearcher

    called = {"n": 0}

    def _fn(facts):
        called["n"] += 1
        return None

    assert WebResearcher(_fn).find_hook(ProspectFacts(full_name="X")) is None
    assert called["n"] == 0  # no company => never even searched


def test_parse_hook_reads_strict_format():
    from leia.research.web import parse_hook

    h = parse_hook("HOOK: They opened a Leeds site || URL: https://news/x || CONFIDENCE: high")
    assert h is not None
    assert h.source == "web" and h.confidence == "high" and h.url == "https://news/x"


def test_parse_hook_none_and_garbage_return_none():
    from leia.research.web import parse_hook

    assert parse_hook("HOOK: NONE") is None
    assert parse_hook("no structured line here") is None
    assert parse_hook("") is None


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeAnthropic:
    def __init__(self, text="", raises=False):
        self._text = text
        self._raises = raises
        self.messages = self

    def create(self, **kwargs):
        if self._raises:
            raise RuntimeError("API down")
        return _FakeResp(self._text)


def test_anthropic_web_search_parses_a_hook():
    from leia.research.web import anthropic_web_search

    client = _FakeAnthropic(
        "HOOK: Published a 2030 Net Zero target || URL: https://x || CONFIDENCE: medium"
    )
    hook = anthropic_web_search(client)(FACTS)
    assert hook is not None and hook.source == "web"


def test_anthropic_web_search_swallows_errors():
    from leia.research.web import anthropic_web_search

    assert anthropic_web_search(_FakeAnthropic(raises=True))(FACTS) is None


def test_engine_short_circuits_on_high_confidence_signal():
    """A free high-confidence signal hook must skip the paid web researcher entirely."""
    web_calls = {"n": 0}

    class SpyWeb:
        name = "web"

        def find_hook(self, facts, **k):
            web_calls["n"] += 1
            return ResearchHook(text="web hook", source="web")

    high = StubResearcher(ResearchHook(text="signal hook", source="signal", confidence="high"))
    best = research_prospect(FACTS, researchers=[high, SpyWeb()])
    assert best is not None and best.source == "signal"
    assert web_calls["n"] == 0  # never paid for web research

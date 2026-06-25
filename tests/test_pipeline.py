"""End-to-end dry-run: CSV -> enrich -> score -> draft -> queue -> approve -> send.

Uses stub providers throughout: zero network, zero spend, zero real sends.
"""

from __future__ import annotations

from leia.approval.queue import approve, list_pending
from leia.channels.stub import StubChannel
from leia.config import load_icp, load_message_guidelines, load_value_prop
from leia.enrichment.stub import StubEnricher
from leia.llm.stub import StubBrain
from leia.models import DraftMessage, DraftStatus, OutreachLog
from leia.pipeline import Components, run_until_queue, send_approved
from leia.sources.manual_csv import ManualCSVSource

SAMPLE_CSV = "data/fixtures/contacts.sample.csv"


def _components() -> Components:
    return Components(
        brain=StubBrain(),
        enricher=StubEnricher(),
        channel_for=lambda ch: StubChannel(ch),
        dry_run=True,
    )


def _run(session):
    return run_until_queue(
        session,
        source=ManualCSVSource(SAMPLE_CSV),
        components=_components(),
        icp_config=load_icp(),
        value_prop=load_value_prop(),
        guidelines=load_message_guidelines(),
    )


def test_dry_run_pipeline_end_to_end(session):
    reports = _run(session)

    assert reports["ingest"]["prospects"] == 5
    assert reports["enrich"]["enriched"] == 5  # stub synthesizes emails for all
    assert reports["score"]["scored"] == 5
    # The "Student" row is excluded by the ICP -> scores 0 -> not drafted.
    assert reports["draft"]["drafted"] == 4
    assert reports["enqueue"]["queued"] == 4
    assert reports["total_cost_usd"] == 0.0  # stub brain is free

    pending = list_pending(session)
    assert len(pending) == 4
    draft = session.get(DraftMessage, pending[0].draft_message_id)
    assert draft.body  # a readable, personalized message
    assert draft.subject  # email channel always has a subject


def test_rerun_is_idempotent(session):
    _run(session)
    second = _run(session)
    assert second["ingest"]["prospects"] == 0
    assert second["score"]["scored"] == 0
    assert second["draft"]["drafted"] == 0


def test_rescore_updates_existing_verdicts_in_place(session):
    """rescore_all re-runs scoring over enriched prospects and updates each
    ScoredLead in place (no duplicate rows), reflecting the current ICP."""
    from leia.config import load_value_prop
    from leia.llm.base import ScoreOutput
    from leia.models import ScoredLead
    from leia.pipeline import rescore_all
    from leia.schemas import ScoreResult

    _run(session)
    before = session.query(ScoredLead).all()
    assert before, "expected the dry-run to have scored prospects"
    n_rows = len(before)

    class FixedBrain:
        """A brain that scores every prospect 73/tier B with a fresh rationale."""

        def score(self, facts, icp, value_prop):
            return ScoreOutput(
                result=ScoreResult(
                    score=73, tier="B", rationale="rescored", matched_criteria=["industry: test"]
                ),
                model_id="stub",
            )

    report = rescore_all(session, FixedBrain(), load_icp(), load_value_prop())
    assert report.counts["scored"] == n_rows

    after = session.query(ScoredLead).all()
    assert len(after) == n_rows  # updated in place, not duplicated
    assert all(s.score == 73 and s.tier == "B" and s.rationale == "rescored" for s in after)


def test_approve_then_send_only_touches_approved(session):
    _run(session)
    pending = list_pending(session)
    approve(session, pending[0].id)

    report = send_approved(session, channel_for=lambda ch: StubChannel(ch))
    assert report.counts["sent"] == 1
    assert report.counts["failed"] == 0

    sent_draft = session.get(DraftMessage, pending[0].draft_message_id)
    assert sent_draft.status == DraftStatus.SENT

    logs = session.query(OutreachLog).all()
    assert len(logs) == 1
    assert logs[0].event == "queued"  # stub channel records intent, sends nothing

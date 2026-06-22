"""The staged pipeline: ingest -> enrich -> score -> draft -> enqueue; and send.

Each stage reads rows in one status and writes the next, so the pipeline is
resumable (re-run picks up where it left off) and inspectable (query the DB
between any two stages). ``build_components`` chooses stub vs. real providers
based on --dry-run and which API keys are present.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from leia.approval.queue import enqueue_pending
from leia.channels.base import Channel, OutboundMessage
from leia.channels.email_instantly import InstantlyEmailChannel
from leia.channels.stub import StubChannel
from leia.config import AppSettings, ICPConfig, Settings, ValuePropConfig
from leia.dedupe import (
    canonicalize_linkedin_url,
    normalize_email,
    prospect_dedupe_key,
    signal_dedupe_key,
)
from leia.enrichment.base import Enricher, EnrichmentQuery
from leia.enrichment.lusha import LushaEnricher
from leia.enrichment.stub import StubEnricher
from leia.llm.base import Brain
from leia.llm.client import LLMBrain
from leia.llm.stub import StubBrain
from leia.models import (
    ICP,
    DraftMessage,
    DraftStatus,
    EmailStatus,
    EnrichedContact,
    EnrichmentStatus,
    OutreachLog,
    Prospect,
    ScoredLead,
    Signal,
    SignalStatus,
    utcnow,
)
from leia.schemas import ProspectFacts
from leia.sources.base import SignalSource


@dataclass
class StageReport:
    counts: dict = field(default_factory=dict)
    cost_usd: float = 0.0


@dataclass
class Components:
    brain: Brain | None
    enricher: Enricher
    channel_for: Callable[[str], Channel]
    dry_run: bool
    notes: list[str] = field(default_factory=list)


def build_components(
    *,
    dry_run: bool,
    settings: Settings,
    app_settings: AppSettings,
    require_brain: bool = True,
) -> Components:
    """Pick stub vs. real providers. Stubs => zero spend, zero sends.

    ``require_brain=False`` (used by ``send``) skips the Anthropic key check,
    since sending approved drafts doesn't call the LLM.
    """
    notes: list[str] = []
    brain: Brain | None = None
    if dry_run:
        brain = StubBrain()
        enricher: Enricher = StubEnricher()
        notes.append("dry-run: using stub brain + stub enricher (no spend, no sends)")
    else:
        if require_brain:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set. Add it to .env, or use --dry-run."
                )
            brain = LLMBrain(brain_model=app_settings.models.brain)
        if settings.lusha_api_key:
            enricher = LushaEnricher(settings.lusha_api_key)
        else:
            enricher = StubEnricher()
            notes.append("LUSHA_API_KEY missing: falling back to stub enricher")

    def channel_for(channel: str) -> Channel:
        if (
            channel == "email"
            and not dry_run
            and settings.instantly_api_key
            and settings.instantly_campaign_id
        ):
            return InstantlyEmailChannel(
                settings.instantly_api_key, settings.instantly_campaign_id
            )
        return StubChannel(channel)

    return Components(
        brain=brain, enricher=enricher, channel_for=channel_for, dry_run=dry_run, notes=notes
    )


def _get_signal_summary(session: Session, prospect: Prospect) -> str | None:
    """Look up the prospect's origin signal and return a human-readable summary
    of any Lusha intent-signal events, or None if no signals were recorded."""
    if not prospect.origin_signal_id:
        return None
    sig = session.get(Signal, prospect.origin_signal_id)
    if sig is None:
        return None
    signal_types: list[str] = sig.raw_json.get("signals") or []
    if not signal_types:
        return None
    start_date: str = sig.raw_json.get("signal_start_date", "")
    label = ", ".join(signal_types)
    return f"Recent signal: {label}" + (f" (since {start_date})" if start_date else "")


def build_facts(prospect: Prospect, signal_summary: str | None = None) -> ProspectFacts:
    ec = prospect.enrichment
    return ProspectFacts(
        full_name=prospect.full_name,
        headline=prospect.headline,
        company_name=prospect.company_name,
        title=getattr(ec, "title", None),
        seniority=getattr(ec, "seniority", None),
        industry=getattr(ec, "industry", None),
        country=getattr(ec, "country", None),
        company_size=getattr(ec, "company_size", None),
        signal_summary=signal_summary,
    )


def ensure_icp_row(session: Session, icp_config: ICPConfig, account_id: str = "local") -> ICP:
    """Load or create the persisted ICP snapshot (keeps scores reproducible)."""
    criteria = icp_config.model_dump()
    existing = session.execute(
        select(ICP).where(
            ICP.account_id == account_id,
            ICP.name == icp_config.name,
            ICP.version == icp_config.version,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.criteria_json != criteria:
            existing.criteria_json = criteria
            session.commit()
        return existing
    row = ICP(
        account_id=account_id,
        name=icp_config.name,
        version=icp_config.version,
        criteria_json=criteria,
        active=True,
    )
    session.add(row)
    session.commit()
    return row


# ── Stages ─────────────────────────────────────────────────────────────────


def ingest(session: Session, source: SignalSource, account_id: str = "local") -> dict:
    new_signals = 0
    new_prospects = 0
    for rs in source.fetch():
        identity = prospect_dedupe_key(
            linkedin_url=rs.linkedin_url,
            email=rs.email,
            full_name=rs.full_name,
            company_name=rs.company_name,
        )
        sig_key = signal_dedupe_key(rs.source, rs.source_ref, identity)
        if session.execute(
            select(Signal).where(Signal.account_id == account_id, Signal.dedupe_key == sig_key)
        ).scalar_one_or_none():
            continue

        sig = Signal(
            account_id=account_id,
            source=rs.source,
            source_ref=rs.source_ref,
            raw_json=rs.raw,
            dedupe_key=sig_key,
            observed_at=utcnow(),
            status=SignalStatus.NEW,
        )
        session.add(sig)
        session.flush()
        new_signals += 1

        prospect = session.execute(
            select(Prospect).where(
                Prospect.account_id == account_id, Prospect.dedupe_key == identity
            )
        ).scalar_one_or_none()
        if prospect is None:
            prospect = Prospect(
                account_id=account_id,
                full_name=rs.full_name,
                headline=rs.headline,
                company_name=rs.company_name,
                linkedin_url=canonicalize_linkedin_url(rs.linkedin_url),
                dedupe_key=identity,
                origin_signal_id=sig.id,
                enrichment_status=EnrichmentStatus.PENDING,
            )
            session.add(prospect)
            session.flush()
            new_prospects += 1
            # If the CSV already provided an email, store it and skip paid enrichment.
            if rs.email:
                session.add(
                    EnrichedContact(
                        account_id=account_id,
                        prospect_id=prospect.id,
                        email=normalize_email(rs.email),
                        email_status=EmailStatus.GUESS,
                        provider="csv",
                        enriched_at=utcnow(),
                    )
                )
                prospect.enrichment_status = EnrichmentStatus.ENRICHED
        sig.status = SignalStatus.PROCESSED

    session.commit()
    return {"signals": new_signals, "prospects": new_prospects}


def enrich(
    session: Session, enricher: Enricher, account_id: str = "local", limit: int | None = None
) -> dict:
    q = select(Prospect).where(
        Prospect.account_id == account_id,
        Prospect.enrichment_status == EnrichmentStatus.PENDING,
        Prospect.suppressed.is_(False),
    )
    prospects = list(session.execute(q).scalars().all())
    if limit:
        prospects = prospects[:limit]

    enriched = 0
    failed = 0
    for p in prospects:
        res = enricher.enrich(
            EnrichmentQuery(
                full_name=p.full_name, company_name=p.company_name, linkedin_url=p.linkedin_url
            )
        )
        session.add(
            EnrichedContact(
                account_id=account_id,
                prospect_id=p.id,
                email=res.email,
                email_status=res.email_status,
                title=res.title,
                seniority=res.seniority,
                company_domain=res.company_domain,
                company_size=res.company_size,
                industry=res.industry,
                country=res.country,
                provider=res.provider,
                provider_raw_json=res.raw,
                enriched_at=utcnow(),
            )
        )
        if res.email:
            p.enrichment_status = EnrichmentStatus.ENRICHED
            enriched += 1
        else:
            p.enrichment_status = EnrichmentStatus.FAILED
            failed += 1

    session.commit()
    return {"enriched": enriched, "failed": failed}


def score(
    session: Session,
    brain: Brain,
    icp_config: ICPConfig,
    value_prop: ValuePropConfig,
    icp_row: ICP,
    account_id: str = "local",
    limit: int | None = None,
) -> StageReport:
    q = select(Prospect).where(
        Prospect.account_id == account_id,
        Prospect.enrichment_status == EnrichmentStatus.ENRICHED,
        Prospect.suppressed.is_(False),
    )
    scored = 0
    cost = 0.0
    for p in session.execute(q).scalars().all():
        if session.execute(
            select(ScoredLead).where(
                ScoredLead.prospect_id == p.id, ScoredLead.icp_id == icp_row.id
            )
        ).scalar_one_or_none():
            continue
        out = brain.score(build_facts(p, _get_signal_summary(session, p)), icp_config, value_prop)
        session.add(
            ScoredLead(
                account_id=account_id,
                prospect_id=p.id,
                icp_id=icp_row.id,
                score=out.result.score,
                tier=out.result.tier,
                rationale=out.result.rationale,
                matched_criteria_json=out.result.matched_criteria,
                model_id=out.model_id,
                tokens_in=out.tokens_in,
                tokens_out=out.tokens_out,
                cache_read_tokens=out.cache_read_tokens,
                cache_write_tokens=out.cache_write_tokens,
                cost_usd=out.cost_usd,
                scored_at=utcnow(),
            )
        )
        scored += 1
        cost += out.cost_usd
        if limit and scored >= limit:
            break

    session.commit()
    return StageReport(counts={"scored": scored}, cost_usd=cost)


def draft(
    session: Session,
    brain: Brain,
    value_prop: ValuePropConfig,
    guidelines: str,
    icp_row: ICP,
    channels: tuple[str, ...] = ("email",),
    threshold: int = 60,
    account_id: str = "local",
    limit: int | None = None,
) -> StageReport:
    q = select(ScoredLead).where(
        ScoredLead.account_id == account_id,
        ScoredLead.icp_id == icp_row.id,
        ScoredLead.score >= threshold,
    )
    drafted = 0
    cost = 0.0
    for lead in session.execute(q).scalars().all():
        prospect = session.get(Prospect, lead.prospect_id)
        facts = build_facts(prospect, _get_signal_summary(session, prospect))
        for ch in channels:
            if session.execute(
                select(DraftMessage).where(
                    DraftMessage.scored_lead_id == lead.id, DraftMessage.channel == ch
                )
            ).scalar_one_or_none():
                continue
            out = brain.draft(facts, value_prop, guidelines, ch)
            session.add(
                DraftMessage(
                    account_id=account_id,
                    scored_lead_id=lead.id,
                    channel=ch,
                    subject=out.result.subject,
                    body=out.result.body,
                    model_id=out.model_id,
                    tokens_in=out.tokens_in,
                    tokens_out=out.tokens_out,
                    cache_read_tokens=out.cache_read_tokens,
                    cache_write_tokens=out.cache_write_tokens,
                    cost_usd=out.cost_usd,
                    status=DraftStatus.DRAFT,
                )
            )
            drafted += 1
            cost += out.cost_usd
        if limit and drafted >= limit:
            break

    session.commit()
    return StageReport(counts={"drafted": drafted}, cost_usd=cost)


def send_approved(
    session: Session,
    channel_for: Callable[[str], Channel],
    account_id: str = "local",
    daily_cap: int | None = None,
) -> StageReport:
    """Send ONLY drafts a human has approved. The pipeline's safety boundary."""
    q = select(DraftMessage).where(
        DraftMessage.account_id == account_id, DraftMessage.status == DraftStatus.APPROVED
    )
    sent = 0
    failed = 0
    for d in session.execute(q).scalars().all():
        lead = session.get(ScoredLead, d.scored_lead_id)
        prospect = session.get(Prospect, lead.prospect_id)
        ec = prospect.enrichment
        message = OutboundMessage(
            channel=d.channel,
            to_email=(ec.email if ec else None),
            to_linkedin_url=prospect.linkedin_url,
            subject=d.subject,
            body=d.body,
        )
        result = channel_for(d.channel).send(message)
        session.add(
            OutreachLog(
                account_id=account_id,
                draft_message_id=d.id,
                channel=d.channel,
                provider=result.provider,
                provider_message_id=result.provider_message_id,
                event=result.event,
                payload_json=result.raw,
            )
        )
        if result.ok:
            d.status = DraftStatus.SENT
            sent += 1
        else:
            d.status = DraftStatus.FAILED
            failed += 1
        if daily_cap and sent >= daily_cap:
            break

    session.commit()
    return StageReport(counts={"sent": sent, "failed": failed})


def run_until_queue(
    session: Session,
    *,
    source: SignalSource,
    components: Components,
    icp_config: ICPConfig,
    value_prop: ValuePropConfig,
    guidelines: str,
    account_id: str = "local",
    limit: int | None = None,
) -> dict:
    """ingest -> enrich -> score -> draft -> enqueue. Stops at the approval queue."""
    if components.brain is None:
        raise RuntimeError("A brain is required to run the pipeline.")
    icp_row = ensure_icp_row(session, icp_config, account_id)
    reports: dict = {}
    reports["ingest"] = ingest(session, source, account_id)
    reports["enrich"] = enrich(session, components.enricher, account_id, limit)

    score_rep = score(
        session, components.brain, icp_config, value_prop, icp_row, account_id, limit
    )
    reports["score"] = score_rep.counts
    total_cost = score_rep.cost_usd

    draft_rep = draft(
        session,
        components.brain,
        value_prop,
        guidelines,
        icp_row,
        channels=("email",),
        threshold=icp_config.score_threshold,
        account_id=account_id,
        limit=limit,
    )
    reports["draft"] = draft_rep.counts
    total_cost += draft_rep.cost_usd

    reports["enqueue"] = {"queued": enqueue_pending(session, account_id)}
    reports["total_cost_usd"] = round(total_cost, 6)
    return reports

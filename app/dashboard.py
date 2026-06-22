"""Streamlit approval queue — review AI-drafted messages, approve before sending.

Launch with:  uv run leia dashboard
Nothing is ever sent from here; approving only marks a draft ready for `leia send`.
"""

from __future__ import annotations

import streamlit as st

from leia.approval.queue import approve, list_pending, reject
from leia.db import make_engine, make_session_factory
from leia.models import DraftMessage, Prospect, ScoredLead

st.set_page_config(page_title="PROJECT-LEIA — Approval Queue", page_icon="✅", layout="wide")


@st.cache_resource
def _session_factory():
    return make_session_factory(make_engine())


def main() -> None:
    st.title("✅ PROJECT-LEIA — Approval Queue")
    st.caption("Review each AI-drafted message. Nothing is sent until you approve it.")

    session = _session_factory()()
    try:
        pending = list_pending(session)
        if not pending:
            st.success(
                "No drafts awaiting approval. Generate some with "
                "`uv run leia run --input your_prospects.csv`."
            )
            return

        st.write(f"**{len(pending)}** draft(s) awaiting your review.")
        for item in pending:
            draft = session.get(DraftMessage, item.draft_message_id)
            lead = session.get(ScoredLead, draft.scored_lead_id)
            prospect = session.get(Prospect, lead.prospect_id)
            enrichment = prospect.enrichment

            with st.container(border=True):
                left, right = st.columns([3, 1])
                with left:
                    st.subheader(prospect.full_name)
                    st.caption(
                        " · ".join(
                            x for x in [prospect.headline, prospect.company_name] if x
                        )
                    )
                    if enrichment and enrichment.email:
                        st.caption(f"✉️ {enrichment.email}  ({enrichment.email_status})")
                with right:
                    st.metric("Score", lead.score)
                    st.caption(f"Tier {lead.tier} · {draft.channel}")

                st.caption(f"Why this score: {lead.rationale}")

                # Spend transparency: scoring + drafting cost for this lead, and
                # prompt-cache token activity (only shown once caching engages).
                spend = (lead.cost_usd or 0.0) + (draft.cost_usd or 0.0)
                meter = f"💰 ${spend:.4f} to score + draft · {draft.model_id or 'stub'}"
                cache_read = (lead.cache_read_tokens or 0) + (draft.cache_read_tokens or 0)
                cache_write = (lead.cache_write_tokens or 0) + (draft.cache_write_tokens or 0)
                if cache_read or cache_write:
                    meter += f" · cache {cache_read:,}r / {cache_write:,}w tok"
                st.caption(meter)

                new_subject = draft.subject or ""
                if draft.channel == "email":
                    new_subject = st.text_input(
                        "Subject", value=draft.subject or "", key=f"sub_{item.id}"
                    )
                new_body = st.text_area(
                    "Message", value=draft.body, key=f"body_{item.id}", height=170
                )
                note = st.text_input("Note (optional)", key=f"note_{item.id}")

                approve_col, reject_col, _ = st.columns([1, 1, 5])
                with approve_col:
                    if st.button("✅ Approve", key=f"approve_{item.id}", type="primary"):
                        approve(
                            session,
                            item.id,
                            note=note or None,
                            edited_subject=(
                                new_subject
                                if draft.channel == "email"
                                and new_subject != (draft.subject or "")
                                else None
                            ),
                            edited_body=(new_body if new_body != draft.body else None),
                        )
                        st.rerun()
                with reject_col:
                    if st.button("✕ Reject", key=f"reject_{item.id}"):
                        reject(session, item.id, note=note or None)
                        st.rerun()
    finally:
        session.close()


main()

"""Offline tests for the Instantly email inbox + the composite inbox (no network)."""

from __future__ import annotations

import pytest

from leia.inbox.base import InboundReply
from leia.inbox.instantly import InstantlyInbox
from leia.inbox.multi import MultiInbox


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


class _FakeClient:
    def __init__(self, data, *, raises=False):
        self._d = data
        self._raises = raises
        self.calls: list = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if self._raises:
            raise RuntimeError("boom")
        return _Resp(self._d)

    def close(self):
        pass


_PAYLOAD = {
    "items": [
        {
            "id": "e1", "ue_type": 2,  # received => a reply
            "from_address_email": "maya@northwind.com",
            "body": {"text": "Thanks — yes, let's talk."},
        },
        {"id": "e2", "ue_type": 1, "from_address_email": "greg@equityenergies.com",
         "body": {"text": "our own outbound send"}},  # sent => skipped
        {"id": "e3", "ue_type": 2, "from_address_email": "x@y.com",
         "body": {"text": "   "}},  # empty => skipped
    ]
}


def test_parses_only_inbound_replies():
    fake = _FakeClient(_PAYLOAD)
    replies = InstantlyInbox("key", client=fake).fetch_new()
    assert len(replies) == 1  # e2 is ours, e3 is empty
    r = replies[0]
    assert r.provider_id == "e1"
    assert r.channel == "email"
    assert r.from_email == "maya@northwind.com"
    assert r.body == "Thanks — yes, let's talk."


def test_hits_the_v2_emails_endpoint():
    fake = _FakeClient({"items": []})
    InstantlyInbox("key", client=fake).fetch_new()
    path, _params = fake.calls[0]
    assert path == "/api/v2/emails"


def test_network_error_returns_empty_not_crash():
    fake = _FakeClient({}, raises=True)
    assert InstantlyInbox("key", client=fake).fetch_new() == []


def test_requires_key():
    with pytest.raises(ValueError):
        InstantlyInbox("")


# ── MultiInbox ───────────────────────────────────────────────────────────────


class _StaticInbox:
    def __init__(self, replies, *, raises=False):
        self._replies = replies
        self._raises = raises

    def fetch_new(self):
        if self._raises:
            raise RuntimeError("provider down")
        return self._replies


def test_multi_merges_all_inboxes():
    a = _StaticInbox([InboundReply(provider_id="a1", channel="linkedin", body="hi")])
    b = _StaticInbox([InboundReply(provider_id="b1", channel="email", body="yo")])
    merged = MultiInbox([a, b]).fetch_new()
    assert {r.provider_id for r in merged} == {"a1", "b1"}


def test_multi_isolates_a_failing_inbox():
    good = _StaticInbox([InboundReply(provider_id="ok", channel="email", body="hi")])
    bad = _StaticInbox([], raises=True)
    merged = MultiInbox([bad, good]).fetch_new()
    assert [r.provider_id for r in merged] == ["ok"]  # bad one didn't sink the good one

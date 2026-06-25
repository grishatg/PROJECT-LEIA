"""Offline tests for the Unipile LinkedIn inbox (no network — fake client)."""

from __future__ import annotations

from leia.inbox.unipile import UnipileInbox


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
            "id": "m1", "chat_id": "c1", "is_sender": False,
            "text": "Sounds interesting — tell me more.",
            "sender_id": "urn:li:person:123",
            "sender_attendee": {"public_identifier": "maya-rao"},
        },
        {"id": "m2", "chat_id": "c1", "is_sender": True, "text": "our own outbound"},
        {"id": "m3", "chat_id": "c2", "is_sender": False, "text": "   "},  # empty -> skipped
    ]
}


def test_parses_only_inbound_messages():
    fake = _FakeClient(_PAYLOAD)
    box = UnipileInbox("key", "api9.unipile.com:13443", "acct-1", client=fake)
    replies = box.fetch_new()

    assert len(replies) == 1  # m2 is ours, m3 is empty
    r = replies[0]
    assert r.provider_id == "m1"
    assert r.channel == "linkedin"
    assert r.body == "Sounds interesting — tell me more."
    assert r.from_linkedin_url == "https://www.linkedin.com/in/maya-rao"
    assert r.provider_chat_id == "c1"
    assert r.from_provider_id == "urn:li:person:123"


def test_passes_account_id_filter():
    fake = _FakeClient({"items": []})
    UnipileInbox("key", "https://api9.unipile.com", "acct-7", client=fake).fetch_new()
    path, params = fake.calls[0]
    assert path == "/api/v1/messages"
    assert params["account_id"] == "acct-7"


def test_network_error_returns_empty_not_crash():
    fake = _FakeClient({}, raises=True)
    assert UnipileInbox("key", "dsn", client=fake).fetch_new() == []


def test_requires_key_and_dsn():
    import pytest

    with pytest.raises(ValueError):
        UnipileInbox("", "dsn")

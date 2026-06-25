"""UnipileLinkedInChannel: validation, HTTP interactions, error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from leia.channels.base import OutboundMessage
from leia.channels.linkedin_unipile import UnipileLinkedInChannel


def _ch() -> UnipileLinkedInChannel:
    return UnipileLinkedInChannel("key123", "api3.unipile.com:13178")


def _resp(data: dict | list, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    r.content = b"ok"
    r.raise_for_status = MagicMock()
    return r


# ── validate() ────────────────────────────────────────────────────────────────


def test_validate_ok():
    ch = _ch()
    msg = OutboundMessage(
        channel="linkedin",
        to_linkedin_url="https://linkedin.com/in/jane",
        body="Hi Jane!",
    )
    assert ch.validate(msg) == []


def test_validate_missing_url():
    ch = _ch()
    msg = OutboundMessage(channel="linkedin", body="Hi!")
    assert "missing to_linkedin_url (or provider_chat_id)" in ch.validate(msg)


def test_validate_accepts_chat_id_without_url():
    # A continuation/reply targets an existing chat, so no profile URL is required.
    ch = _ch()
    msg = OutboundMessage(channel="linkedin", body="Thanks!", provider_chat_id="chat-123")
    assert ch.validate(msg) == []


def test_validate_empty_body():
    ch = _ch()
    msg = OutboundMessage(
        channel="linkedin", to_linkedin_url="https://linkedin.com/in/j", body="  "
    )
    assert "empty body" in ch.validate(msg)


def test_validate_channel_mismatch():
    ch = _ch()
    msg = OutboundMessage(channel="email", to_email="a@b.com", subject="hi", body="hi")
    assert any("channel mismatch" in p for p in ch.validate(msg))


# ── constructor ───────────────────────────────────────────────────────────────


def test_dsn_normalised_to_https():
    ch = UnipileLinkedInChannel("k", "api3.unipile.com:13178")
    assert ch.base_url == "https://api3.unipile.com:13178"


def test_dsn_with_https_prefix_unchanged():
    ch = UnipileLinkedInChannel("k", "https://api3.unipile.com:13178")
    assert ch.base_url == "https://api3.unipile.com:13178"


def test_constructor_requires_key_and_dsn():
    with pytest.raises(ValueError):
        UnipileLinkedInChannel("", "dsn")
    with pytest.raises(ValueError):
        UnipileLinkedInChannel("key", "")


# ── send() — happy path ───────────────────────────────────────────────────────


def test_send_happy_path():
    accounts_resp = _resp({"items": [{"id": "acc1", "type": "LINKEDIN"}]})
    profile_resp = _resp({"provider_id": "ACoAA123"})
    invite_resp = _resp({"id": "inv42"})

    ch = _ch()
    msg = OutboundMessage(
        channel="linkedin",
        to_linkedin_url="https://linkedin.com/in/jane",
        body="Hi Jane, loved your post about energy efficiency!",
    )

    with patch("leia.channels.linkedin_unipile.httpx.get") as mock_get, \
         patch("leia.channels.linkedin_unipile.httpx.post", return_value=invite_resp):
        mock_get.side_effect = [accounts_resp, profile_resp]
        result = ch.send(msg)

    assert result.ok is True
    assert result.event == "sent"
    assert result.provider == "unipile"
    assert result.provider_message_id == "inv42"


def test_send_caches_account_id():
    """Second send should not re-fetch accounts."""
    accounts_resp = _resp({"items": [{"id": "acc1", "type": "LINKEDIN"}]})
    profile_resp = _resp({"provider_id": "ACoAA123"})
    invite_resp = _resp({"id": "inv1"})

    ch = _ch()
    msg = OutboundMessage(
        channel="linkedin",
        to_linkedin_url="https://linkedin.com/in/jane",
        body="Hi!",
    )
    with patch("leia.channels.linkedin_unipile.httpx.get") as mock_get, \
         patch("leia.channels.linkedin_unipile.httpx.post", return_value=invite_resp):
        mock_get.side_effect = [accounts_resp, profile_resp, profile_resp]
        ch.send(msg)
        ch.send(msg)
        # accounts fetched once; profiles fetched twice (one per send)
        assert mock_get.call_count == 3


def test_send_truncates_long_body():
    accounts_resp = _resp({"items": [{"id": "acc1", "type": "LINKEDIN"}]})
    profile_resp = _resp({"provider_id": "ACoAA123"})
    invite_resp = _resp({})

    ch = _ch()
    long_body = "x" * 500
    msg = OutboundMessage(
        channel="linkedin",
        to_linkedin_url="https://linkedin.com/in/jane",
        body=long_body,
    )
    with patch("leia.channels.linkedin_unipile.httpx.get") as mock_get, \
         patch("leia.channels.linkedin_unipile.httpx.post") as mock_post:
        mock_get.side_effect = [accounts_resp, profile_resp]
        mock_post.return_value = invite_resp
        ch.send(msg)

    sent_note = mock_post.call_args.kwargs["json"]["message"]
    assert len(sent_note) == 300


# ── send() — error paths ──────────────────────────────────────────────────────


def test_send_no_linkedin_account_returns_failed():
    accounts_resp = _resp({"items": [{"id": "acc1", "type": "SLACK"}]})
    ch = _ch()
    msg = OutboundMessage(
        channel="linkedin",
        to_linkedin_url="https://linkedin.com/in/jane",
        body="Hi!",
    )
    with patch("leia.channels.linkedin_unipile.httpx.get", return_value=accounts_resp):
        result = ch.send(msg)
    assert result.ok is False
    assert "No LinkedIn account" in result.detail


def test_send_unresolvable_profile_returns_failed():
    accounts_resp = _resp({"items": [{"id": "acc1", "type": "LINKEDIN"}]})
    profile_resp = _resp({})  # empty — no provider_id

    ch = _ch()
    msg = OutboundMessage(
        channel="linkedin",
        to_linkedin_url="https://linkedin.com/in/nobody",
        body="Hi!",
    )
    with patch("leia.channels.linkedin_unipile.httpx.get") as mock_get:
        mock_get.side_effect = [accounts_resp, profile_resp]
        result = ch.send(msg)
    assert result.ok is False
    assert "provider ID" in result.detail


def test_send_validation_failure_short_circuits():
    """Validate failure must not make any HTTP calls."""
    ch = _ch()
    msg = OutboundMessage(channel="linkedin", body="hi")  # missing to_linkedin_url
    with patch("leia.channels.linkedin_unipile.httpx.get") as mock_get:
        result = ch.send(msg)
        mock_get.assert_not_called()
    assert result.ok is False

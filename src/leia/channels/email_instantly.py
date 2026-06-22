"""Email sending via Instantly (cold-email platform with managed deliverability).

Instantly sends through campaigns, so "send" here means: add the approved lead to
a configured Instantly campaign, passing the drafted subject/body as custom
variables your campaign template references ({{leia_subject}} / {{leia_body}}).

⚠️ Cold outreach only belongs on a platform like Instantly — never a transactional
API (Resend/Postmark/SES), whose terms ban it. Verify the endpoint/fields against
your Instantly plan on first real run.
"""

from __future__ import annotations

import httpx

from leia.channels.base import OutboundMessage, SendResult
from leia.models import OutreachEvent

INSTANTLY_LEADS_URL = "https://api.instantly.ai/api/v2/leads"


class InstantlyEmailChannel:
    channel = "email"
    name = "instantly"

    def __init__(self, api_key: str, campaign_id: str, *, timeout: float = 20.0):
        if not api_key or not campaign_id:
            raise ValueError("Instantly api_key and campaign_id are required")
        self.api_key = api_key
        self.campaign_id = campaign_id
        self.timeout = timeout

    def validate(self, message: OutboundMessage) -> list[str]:
        problems: list[str] = []
        if message.channel != self.channel:
            problems.append(f"channel mismatch: {message.channel} != {self.channel}")
        if not message.to_email:
            problems.append("missing to_email")
        if not message.subject:
            problems.append("missing subject")
        if not message.body or not message.body.strip():
            problems.append("empty body")
        return problems

    def send(self, message: OutboundMessage) -> SendResult:
        problems = self.validate(message)
        if problems:
            return SendResult(
                ok=False, event=OutreachEvent.FAILED, provider=self.name, detail="; ".join(problems)
            )

        body = {
            "campaign": self.campaign_id,
            "email": message.to_email,
            "custom_variables": {
                "leia_subject": message.subject,
                "leia_body": message.body,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(
                INSTANTLY_LEADS_URL, json=body, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001 - surface as a failed send, don't crash
            return SendResult(
                ok=False, event=OutreachEvent.FAILED, provider=self.name, detail=str(e)
            )

        lead_id = (data or {}).get("id") if isinstance(data, dict) else None
        return SendResult(
            ok=True,
            event=OutreachEvent.SENT,
            provider=self.name,
            provider_message_id=lead_id,
            raw=data if isinstance(data, dict) else {},
        )

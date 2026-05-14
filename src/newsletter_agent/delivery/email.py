"""Email delivery via Resend API."""

from __future__ import annotations

import logging

import resend

from newsletter_agent.delivery.templates import render_digest_html
from newsletter_agent.models import Digest

logger = logging.getLogger(__name__)


class EmailDelivery:
    def __init__(self, api_key: str, from_address: str, to_addresses: list[str]):
        resend.api_key = api_key
        self.from_address = from_address
        self.to_addresses = to_addresses

    def send_digest(self, digest: Digest) -> str:
        html = render_digest_html(digest)
        subject = f"Security & AI Digest — {digest.date.strftime('%B %d, %Y')}"

        critical_count = len(digest.critical)
        if critical_count > 0:
            subject = f"[{critical_count} CRITICAL] {subject}"

        params: resend.Emails.SendParams = {
            "from": self.from_address,
            "to": self.to_addresses,
            "subject": subject,
            "html": html,
        }
        response = resend.Emails.send(params)
        email_id = response.get("id", "unknown") if isinstance(response, dict) else str(response)
        logger.info("Digest sent via Resend (id=%s)", email_id)
        return email_id

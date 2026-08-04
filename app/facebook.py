"""Facebook Messenger integration.

Two things people usually get wrong and that break the bot in production:
  1. The webhook must reply 200 within a few seconds or Meta retries and
     eventually disables the subscription — so answering happens in a
     background task, not inline.
  2. X-Hub-Signature-256 must be verified against the RAW body. Re-serializing
     the parsed JSON produces a different byte string and the check fails.
"""

from __future__ import annotations

import hashlib
import hmac

import httpx

from .config import settings


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    if not settings.fb_app_secret:
        return True  # not configured yet — allow, but log a warning at startup
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.fb_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{settings.fb_api_version}/{path}"


async def send_text(recipient_id: str, text: str) -> None:
    # Messenger truncates above 2000 characters; split rather than lose the tail.
    for part in [text[i : i + 1900] for i in range(0, len(text), 1900)] or [""]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                _url("me/messages"),
                params={"access_token": settings.fb_page_token},
                json={
                    "recipient": {"id": recipient_id},
                    "messaging_type": "RESPONSE",
                    "message": {"text": part},
                },
            )


async def send_action(recipient_id: str, action: str = "typing_on") -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            _url("me/messages"),
            params={"access_token": settings.fb_page_token},
            json={"recipient": {"id": recipient_id}, "sender_action": action},
        )


def extract_messages(payload: dict) -> list[tuple[str, str]]:
    """Return [(sender_id, text)] from a webhook payload, skipping echoes."""
    out = []
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            if message.get("is_echo"):
                continue
            text = message.get("text")
            sender = (event.get("sender") or {}).get("id")
            if text and sender:
                out.append((sender, text))
    return out

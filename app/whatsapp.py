"""
WhatsApp Business Cloud API client.

Provides:
- Webhook verification
- Signature validation (X-Hub-Signature-256)
- Incoming message parsing
- All send methods (text, image, interactive buttons/list, template)
- 24-hour session window enforcement
- Automatic retry with exponential back-off
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
_last_user_message_at: dict[str, float] = {}  # phone -> unix timestamp


# ── Helpers ───────────────────────────────────────────────────────────────────


def _within_24h_window(phone: str) -> bool:
    """Return True if user sent a message within the last 24 hours."""
    ts = _last_user_message_at.get(phone)
    if ts is None:
        return False
    return (time.time() - ts) < 86400


def _record_user_message(phone: str) -> None:
    _last_user_message_at[phone] = time.time()


def _retry_request(func, *args, max_attempts: int = 3, **kwargs) -> httpx.Response:
    """Call *func* up to *max_attempts* times with exponential back-off."""
    last_exc: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            resp = func(*args, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "WhatsApp API HTTP error (attempt %d/%d): %s",
                attempt + 1,
                max_attempts,
                exc,
            )
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
        except httpx.RequestError as exc:
            logger.warning(
                "WhatsApp API request error (attempt %d/%d): %s",
                attempt + 1,
                max_attempts,
                exc,
            )
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"WhatsApp API call failed after {max_attempts} attempts") from last_exc


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _messages_url() -> str:
    return f"{GRAPH_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"


# ── Webhook ───────────────────────────────────────────────────────────────────


def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    """
    Verify the WhatsApp webhook subscription challenge.

    Returns the challenge string on success, None on failure.
    """
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified successfully")
        return challenge
    logger.warning("Webhook verification failed: mode=%s", mode)
    return None


def verify_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Validate the X-Hub-Signature-256 header sent by Meta.

    Returns True when the HMAC-SHA256 matches.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received_sig = signature_header[len("sha256="):]
    expected_sig = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(received_sig, expected_sig)


# ── Parsing ───────────────────────────────────────────────────────────────────


def parse_incoming_message(data: dict) -> Optional[dict]:
    """
    Parse a WhatsApp webhook payload.

    Returns a normalised dict:
        {phone, message_id, type, text, location}
    or None if the payload is not a user message.
    """
    try:
        entry = data["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        if "messages" not in value:
            return None

        msg = value["messages"][0]
        phone = msg["from"]
        message_id = msg["id"]
        msg_type = msg.get("type", "unknown")

        text: Optional[str] = None
        location: Optional[dict] = None

        if msg_type == "text":
            text = msg["text"]["body"]
        elif msg_type == "interactive":
            interactive = msg["interactive"]
            itype = interactive.get("type")
            if itype == "button_reply":
                text = interactive["button_reply"]["title"]
            elif itype == "list_reply":
                text = interactive["list_reply"]["title"]
        elif msg_type == "location":
            location = {
                "latitude": msg["location"]["latitude"],
                "longitude": msg["location"]["longitude"],
                "name": msg["location"].get("name", ""),
                "address": msg["location"].get("address", ""),
            }
            text = f"[Location: {location['name'] or location['address'] or 'shared'}]"

        _record_user_message(phone)

        return {
            "phone": phone,
            "message_id": message_id,
            "type": msg_type,
            "text": text,
            "location": location,
        }
    except (KeyError, IndexError) as exc:
        logger.debug("Could not parse incoming message: %s", exc)
        return None


# ── Send methods ──────────────────────────────────────────────────────────────


def send_text(phone: str, text: str) -> dict:
    """Send a plain text message."""
    if not _within_24h_window(phone):
        logger.warning(
            "Skipping free-form text to %s — outside 24h window. Use a template.", phone
        )
        return {"skipped": True, "reason": "outside_24h_window"}

    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }
    resp = _retry_request(
        httpx.post, _messages_url(), headers=_headers(), json=payload
    )
    return resp.json()


def send_image(phone: str, image_path: str, caption: str = "") -> dict:
    """Upload and send a local image file."""
    if not _within_24h_window(phone):
        logger.warning("Skipping image send to %s — outside 24h window.", phone)
        return {"skipped": True, "reason": "outside_24h_window"}

    upload_url = f"{GRAPH_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/media"
    path = Path(image_path)
    with path.open("rb") as fh:
        resp = _retry_request(
            httpx.post,
            upload_url,
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            files={"file": (path.name, fh, "image/png")},
            data={"messaging_product": "whatsapp"},
        )
    media_id = resp.json()["id"]

    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "image",
        "image": {"id": media_id, "caption": caption},
    }
    resp2 = _retry_request(
        httpx.post, _messages_url(), headers=_headers(), json=payload
    )
    return resp2.json()


def send_interactive_buttons(
    phone: str,
    body: str,
    buttons: list[dict],
    header: Optional[str] = None,
    footer: Optional[str] = None,
) -> dict:
    """
    Send an interactive button message.

    buttons: [{"id": "...", "title": "..."}, ...]  — max 3
    """
    if not _within_24h_window(phone):
        return {"skipped": True, "reason": "outside_24h_window"}

    interactive: dict[str, Any] = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                for b in buttons[:3]
            ]
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header}
    if footer:
        interactive["footer"] = {"text": footer}

    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": interactive,
    }
    resp = _retry_request(
        httpx.post, _messages_url(), headers=_headers(), json=payload
    )
    return resp.json()


def send_interactive_list(
    phone: str,
    header: str,
    body: str,
    sections: list[dict],
    button_text: str = "Выбрать",
    footer: Optional[str] = None,
) -> dict:
    """
    Send an interactive list message.

    sections: [{"title": "...", "rows": [{"id": "...", "title": "...", "description": "..."}]}]
    """
    if not _within_24h_window(phone):
        return {"skipped": True, "reason": "outside_24h_window"}

    interactive: dict[str, Any] = {
        "type": "list",
        "header": {"type": "text", "text": header},
        "body": {"text": body},
        "action": {"button": button_text, "sections": sections},
    }
    if footer:
        interactive["footer"] = {"text": footer}

    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": interactive,
    }
    resp = _retry_request(
        httpx.post, _messages_url(), headers=_headers(), json=payload
    )
    return resp.json()


def send_template(
    phone: str,
    template_name: str,
    language_code: str = "ru",
    components: Optional[list[dict]] = None,
) -> dict:
    """Send a pre-approved WhatsApp template message."""
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components

    resp = _retry_request(
        httpx.post, _messages_url(), headers=_headers(), json=payload
    )
    return resp.json()


def mark_as_read(message_id: str) -> dict:
    """Mark a received message as read (displays double blue ticks)."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    resp = _retry_request(
        httpx.post, _messages_url(), headers=_headers(), json=payload
    )
    return resp.json()

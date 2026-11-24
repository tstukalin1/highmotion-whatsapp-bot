"""
Payment processing module.

Handles:
- Incoming payment webhook signature verification
- Idempotent payment processing
- Booking status updates
- Post-payment actions (Word export, notifications)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Booking, BookingStatus, Client, Payment

logger = logging.getLogger(__name__)


def verify_payment_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Verify the payment webhook signature.

    Uses HMAC-SHA256 with PAYMENT_WEBHOOK_SECRET.
    Supports 'sha256=<hex>' header format used by many payment providers.
    """
    if not settings.PAYMENT_WEBHOOK_SECRET or settings.PAYMENT_WEBHOOK_SECRET.startswith("<<"):
        logger.warning("PAYMENT_WEBHOOK_SECRET not configured, skipping signature check")
        return True  # Allow in unconfigured state (dev mode)

    if not signature_header:
        return False

    # Strip common prefixes
    sig = signature_header
    for prefix in ("sha256=", "v1=", "sha1="):
        if sig.startswith(prefix):
            sig = sig[len(prefix):]
            break

    expected = hmac.new(
        settings.PAYMENT_WEBHOOK_SECRET.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(sig, expected)


def _post_payment_actions(session: Session, booking: Booking) -> None:
    """Actions executed after a payment is confirmed."""
    from app import notifications, word_export

    client = session.query(Client).filter(Client.id == booking.client_id).first()
    client_phone = client.phone if client else None

    # 1. Export to Word document
    try:
        file_path = word_export.export_booking(session=session, booking_id=booking.id)
        logger.info("Booking %d exported to %s", booking.id, file_path)
    except Exception as exc:
        logger.error("Word export failed for booking %d: %s", booking.id, exc)

    # 2. Send confirmation to client
    if client_phone:
        try:
            notifications.notify_client_booking_confirmed(
                phone=client_phone,
                booking_number=booking.booking_number,
            )
        except Exception as exc:
            logger.error("Client confirmation failed for booking %d: %s", booking.id, exc)

    # 3. Notify manager
    try:
        notifications.notify_manager_new_booking(booking_id=booking.id)
    except Exception as exc:
        logger.error("Manager notification failed for booking %d: %s", booking.id, exc)


def process_payment_webhook(session: Session, data: dict) -> dict:
    """
    Process an incoming payment webhook payload.

    Idempotency: if external_id already processed, return {"status": "ok", "idempotent": True}.
    On success: update booking to 'paid', trigger post-payment actions.

    Expected data keys (provider-agnostic):
        external_id  : unique payment identifier from provider
        booking_id   : (optional) our booking ID if passed as metadata
        amount       : payment amount
        status       : payment status ("succeeded" / "paid" / "completed")
        provider     : payment provider name
    """
    external_id: Optional[str] = data.get("external_id") or data.get("id")
    amount = data.get("amount", 0)
    status = data.get("status", "")
    provider = data.get("provider", settings.PAYMENT_PROVIDER)
    booking_ref = data.get("booking_number") or data.get("reference") or data.get("metadata", {}).get("booking_number")

    # Idempotency check
    if external_id:
        existing_payment = (
            session.query(Payment).filter(Payment.external_id == external_id).first()
        )
        if existing_payment:
            logger.info("Payment %s already processed (idempotent)", external_id)
            return {"status": "ok", "idempotent": True}

    # Determine if payment is successful
    success_statuses = {"succeeded", "paid", "completed", "success", "confirmed"}
    if status.lower() not in success_statuses:
        logger.info("Payment webhook received non-success status: %s", status)
        return {"status": "ignored", "reason": f"Non-success status: {status}"}

    # Find booking
    booking: Optional[Booking] = None
    if booking_ref:
        booking = session.query(Booking).filter(Booking.booking_number == booking_ref).first()

    if not booking and data.get("booking_id"):
        booking = session.query(Booking).filter(Booking.id == int(data["booking_id"])).first()

    if not booking:
        logger.error("Payment webhook: cannot find booking for %s", data)
        return {"status": "error", "reason": "Booking not found"}

    # Record payment
    payment = Payment(
        booking_id=booking.id,
        external_id=external_id,
        amount=amount,
        status="confirmed",
        provider=provider,
        confirmed_at=datetime.now(timezone.utc),
    )
    session.add(payment)

    # Update booking status
    booking.status = BookingStatus.paid
    session.commit()

    logger.info("Booking %s marked as paid (payment %s)", booking.booking_number, external_id)

    # Post-payment actions
    _post_payment_actions(session, booking)

    return {"status": "ok", "idempotent": False, "booking_number": booking.booking_number}


def confirm_booking_manually(session: Session, booking_id: int) -> dict:
    """
    Manually confirm a booking (admin action).

    Same flow as automatic payment confirmation but without a payment record.
    """
    booking = session.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return {"success": False, "error": "Бронирование не найдено"}

    if booking.status == BookingStatus.paid:
        return {"success": False, "error": "Бронирование уже подтверждено"}

    if booking.status in (BookingStatus.cancelled, BookingStatus.expired):
        return {
            "success": False,
            "error": f"Нельзя подтвердить бронирование со статусом {booking.status.value}",
        }

    # Create a manual payment record
    payment = Payment(
        booking_id=booking.id,
        external_id=f"manual_{booking.booking_number}",
        amount=float(booking.prepayment_amount or booking.total_price or 0),
        status="confirmed",
        provider="manual",
        confirmed_at=datetime.now(timezone.utc),
    )
    session.add(payment)
    booking.status = BookingStatus.paid
    session.commit()

    logger.info("Booking %s confirmed manually", booking.booking_number)

    _post_payment_actions(session, booking)

    return {
        "success": True,
        "booking_number": booking.booking_number,
        "status": booking.status.value,
    }

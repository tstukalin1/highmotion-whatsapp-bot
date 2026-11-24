"""
Notification helpers for managers and clients.

In DEV_MODE email sending is replaced with logging.
WhatsApp notifications use pre-approved templates.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


def _get_session() -> "Session":
    """Import and return a fresh DB session. Avoids circular imports."""
    from app.database import SessionLocal  # type: ignore[import]

    return SessionLocal()


def _send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. In DEV_MODE just logs the content."""
    if settings.DEV_MODE:
        logger.info(
            "[DEV_MODE] Email suppressed → %s\nSubject: %s\n%s", to, subject, body
        )
        return

    # Basic SMTP — configure SMTP_* vars in .env if needed.
    # For production consider using an SMTP relay like SendGrid/Mailgun.
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"{settings.BUSINESS_NAME} <noreply@{settings.BUSINESS_NAME.lower().replace(' ', '')}.com>"
        msg["To"] = to

        # Minimal SMTP — replace with proper SMTP_HOST/PORT/USER/PASS env vars as needed
        with smtplib.SMTP("localhost", 25, timeout=10) as smtp:
            smtp.sendmail(msg["From"], [to], msg.as_string())
            logger.info("Email sent to %s: %s", to, subject)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)


def notify_manager_new_booking(
    booking_id: Optional[int],
    custom_message: Optional[str] = None,
) -> None:
    """
    Notify the manager about a new booking or a handoff request.

    Sends WhatsApp template (if configured) and/or email.
    """
    from app import whatsapp

    if booking_id is not None:
        session = _get_session()
        try:
            from app.models import Booking, Client, Package

            booking = session.query(Booking).filter(Booking.id == booking_id).first()
            if not booking:
                logger.warning("notify_manager_new_booking: booking %d not found", booking_id)
                return

            client = session.query(Client).filter(Client.id == booking.client_id).first()
            package = session.query(Package).filter(Package.id == booking.package_id).first()

            client_info = f"{client.name} ({client.phone})" if client else "unknown"
            package_info = package.name if package else str(booking.package_id)

            message = (
                f"Новое бронирование!\n"
                f"Номер: {booking.booking_number}\n"
                f"Клиент: {client_info}\n"
                f"Пакет: {package_info}\n"
                f"Дата: {booking.travel_date} {booking.travel_time or ''}\n"
                f"Кол-во человек: {booking.people_count}\n"
                f"Сумма: {booking.total_price} руб.\n"
                f"Предоплата: {booking.prepayment_amount} руб.\n"
                f"Статус: {booking.status.value}"
            )
        finally:
            session.close()
    else:
        message = custom_message or "Новое уведомление от бота"

    # WhatsApp notification to manager
    if settings.MANAGER_PHONE and not settings.MANAGER_PHONE.startswith("<<"):
        try:
            whatsapp.send_text(phone=settings.MANAGER_PHONE, text=message)
            logger.info("Manager WhatsApp notification sent to %s", settings.MANAGER_PHONE)
        except Exception as exc:
            logger.error("Failed to send WhatsApp to manager: %s", exc)

    # Email notification to manager
    if settings.MANAGER_EMAIL and not settings.MANAGER_EMAIL.startswith("<<"):
        _send_email(
            to=settings.MANAGER_EMAIL,
            subject=f"[{settings.BUSINESS_NAME}] Новое бронирование",
            body=message,
        )


def notify_client_booking_confirmed(phone: str, booking_number: str) -> None:
    """
    Send a booking confirmation to the client via WhatsApp template.
    """
    from app import whatsapp

    template_name = settings.WA_TEMPLATE_BOOKING_CONFIRMED
    if not template_name or template_name.startswith("<<"):
        # Fallback to plain text if template not configured
        logger.warning("WA_TEMPLATE_BOOKING_CONFIRMED not configured, using text fallback")
        try:
            whatsapp.send_text(
                phone=phone,
                text=(
                    f"Ваше бронирование {booking_number} подтверждено! "
                    "Ждём вас в поездке. Спасибо за выбор нашей компании!"
                ),
            )
        except Exception as exc:
            logger.error("Failed to send confirmation text: %s", exc)
        return

    try:
        whatsapp.send_template(
            phone=phone,
            template_name=template_name,
            language_code="ru",
            components=[
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": booking_number},
                    ],
                }
            ],
        )
        logger.info("Booking confirmation template sent to %s", phone)
    except Exception as exc:
        logger.error("Failed to send booking confirmation template: %s", exc)


def notify_client_payment_reminder(phone: str, booking_id: int) -> None:
    """
    Send a payment reminder to the client via WhatsApp template.
    """
    from app import whatsapp
    from app.models import Booking

    session = _get_session()
    try:
        booking = session.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            logger.warning("notify_client_payment_reminder: booking %d not found", booking_id)
            return

        template_name = settings.WA_TEMPLATE_PAYMENT_REMINDER
        if not template_name or template_name.startswith("<<"):
            logger.warning("WA_TEMPLATE_PAYMENT_REMINDER not configured, using text fallback")
            try:
                whatsapp.send_text(
                    phone=phone,
                    text=(
                        f"Напоминание: оплата по бронированию {booking.booking_number} "
                        f"ещё не получена. Пожалуйста, оплатите предоплату "
                        f"{booking.prepayment_amount} руб. для подтверждения брони."
                    ),
                )
            except Exception as exc:
                logger.error("Failed to send reminder text: %s", exc)
            return

        try:
            whatsapp.send_template(
                phone=phone,
                template_name=template_name,
                language_code="ru",
                components=[
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": booking.booking_number},
                            {
                                "type": "text",
                                "text": str(booking.prepayment_amount),
                            },
                        ],
                    }
                ],
            )
            logger.info("Payment reminder template sent to %s for booking %d", phone, booking_id)
        except Exception as exc:
            logger.error("Failed to send payment reminder template: %s", exc)
    finally:
        session.close()

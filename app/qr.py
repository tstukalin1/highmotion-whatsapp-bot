"""
QR code generation for payment.

Supports three providers:
  - sbp     : Russian Fast Payment System (СБП) string format
  - stripe  : Stripe payment link with amount query param
  - generic : PAYMENT_DETAILS used as-is
"""

from __future__ import annotations

import logging
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_H

from app.config import settings

logger = logging.getLogger(__name__)

QR_DIR = Path(__file__).parent.parent / "qr_images"


def _ensure_dir() -> None:
    QR_DIR.mkdir(parents=True, exist_ok=True)


def _build_sbp_string(amount: float, booking_number: str) -> str:
    """
    Build the СБП QR string according to ГОСТ Р 56042.

    Placeholders for bank details must be filled in .env / config.
    """
    amount_str = f"{int(amount * 100):d}"  # kopecks, no separator
    # Re-format: SBP expects whole roubles with trailing "00" in some implementations.
    # Using a safe representation: integer roubles + "00" kopecks when amount is whole,
    # otherwise full kopeck value.
    if amount == int(amount):
        sum_value = f"{int(amount)}00"
    else:
        kopecks = round(amount * 100)
        sum_value = str(kopecks)

    return (
        "ST00011"
        f"|Name=<<SBP_RECIPIENT_NAME>>"
        f"|PersonalAcc=<<SBP_ACCOUNT>>"
        f"|BankName=<<SBP_BANK_NAME>>"
        f"|BIC=<<SBP_BIC>>"
        f"|Sum={sum_value}"
        f"|Purpose=Бронь {booking_number}"
    )


def _build_stripe_url(amount: float, booking_number: str) -> str:
    """Append amount query param to the Stripe payment link."""
    base = settings.PAYMENT_DETAILS.rstrip("?&")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}amount={int(amount * 100)}&reference={booking_number}"


def _build_generic_content(amount: float, booking_number: str) -> str:
    """Use PAYMENT_DETAILS as-is; append booking reference if it looks like a URL."""
    details = settings.PAYMENT_DETAILS
    if details.startswith("http"):
        separator = "&" if "?" in details else "?"
        return f"{details}{separator}ref={booking_number}"
    return details


def generate_payment_qr(
    booking_id: int,
    amount: float,
    booking_number: str,
) -> str:
    """
    Generate a payment QR PNG for the given booking.

    Returns the absolute path to the saved PNG file.
    """
    _ensure_dir()

    provider = settings.PAYMENT_PROVIDER.lower()

    if provider == "sbp":
        content = _build_sbp_string(amount, booking_number)
    elif provider == "stripe":
        content = _build_stripe_url(amount, booking_number)
    else:
        content = _build_generic_content(amount, booking_number)

    logger.debug("QR content for booking %s: %s", booking_number, content)

    qr = qrcode.QRCode(
        version=None,  # auto-size
        error_correction=ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    output_path = QR_DIR / f"booking_{booking_id}.png"
    img.save(str(output_path))

    logger.info("Payment QR saved: %s", output_path)
    return str(output_path)

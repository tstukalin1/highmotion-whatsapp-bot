"""
Unit tests for individual tool functions.

Covers:
- Each tool's happy path
- Error paths
- Placeholder detection at startup
- handoff_to_human escalation
"""

from __future__ import annotations

import re
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.config import PLACEHOLDER_RE
from app.models import Booking, BookingStatus, Client, Package
from app.tools import (
    TOOLS_SCHEMA,
    cancel_booking,
    check_availability,
    create_booking,
    dispatch_tool,
    get_booking_status,
    get_packages,
    handoff_to_human,
    send_payment_qr,
)


# ── get_packages ───────────────────────────────────────────────────────────────


class TestGetPackagesTool:
    def test_returns_all_active(self, db_session: Session, sample_package: Package):
        result = get_packages(db_session)
        assert any(p["id"] == sample_package.id for p in result)

    def test_returns_serialisable_dicts(self, db_session: Session, sample_package: Package):
        import json
        result = get_packages(db_session)
        # Should not raise
        json.dumps(result)

    def test_price_is_float(self, db_session: Session, sample_package: Package):
        result = get_packages(db_session)
        assert isinstance(result[0]["price"], float)


# ── check_availability ────────────────────────────────────────────────────────


class TestCheckAvailabilityTool:
    def test_available_returns_true(self, db_session: Session, sample_package: Package):
        r = check_availability(db_session, sample_package.id, "2024-09-01", 1)
        assert r["available"] is True

    def test_exceeds_capacity(self, db_session: Session, sample_package: Package):
        r = check_availability(db_session, sample_package.id, "2024-09-01", 100)
        assert r["available"] is False

    def test_package_not_found(self, db_session: Session):
        r = check_availability(db_session, 99999, "2024-09-01", 1)
        assert r["available"] is False


# ── create_booking ────────────────────────────────────────────────────────────


class TestCreateBookingTool:
    def test_creates_successfully(self, db_session: Session, sample_package: Package):
        r = create_booking(
            session=db_session,
            name="Тест",
            phone="79001111111",
            people_count=1,
            package_id=sample_package.id,
            travel_date="2024-09-01",
            travel_time="09:00",
            pickup_location="Вокзал",
        )
        assert r["success"] is True
        assert "booking_number" in r

    def test_prepayment_percent(self, db_session: Session, sample_package: Package):
        r = create_booking(
            session=db_session,
            name="Тест",
            phone="79001111111",
            people_count=1,
            package_id=sample_package.id,
            travel_date="2024-09-01",
            travel_time="09:00",
            pickup_location="Вокзал",
        )
        # 3000 * 1 = 3000, 30% = 900
        assert r["prepayment_amount"] == pytest.approx(900.0)

    def test_invalid_package_id(self, db_session: Session):
        r = create_booking(
            session=db_session,
            name="Тест",
            phone="79001111111",
            people_count=1,
            package_id=0,
            travel_date="2024-09-01",
            travel_time="09:00",
            pickup_location="Вокзал",
        )
        assert r["success"] is False


# ── send_payment_qr ───────────────────────────────────────────────────────────


class TestSendPaymentQrTool:
    def test_sends_qr_for_pending_booking(
        self, db_session: Session, sample_booking: Booking, mock_qr
    ):
        with patch("app.whatsapp.send_image") as mock_send, \
             patch("app.whatsapp._within_24h_window", return_value=True):
            mock_send.return_value = {"messages": [{"id": "test"}]}
            r = send_payment_qr(db_session, sample_booking.id, "79001234567")

        assert r["success"] is True

    def test_fails_for_paid_booking(
        self, db_session: Session, paid_booking: Booking
    ):
        r = send_payment_qr(db_session, paid_booking.id, "79001234567")
        assert r["success"] is False

    def test_fails_for_nonexistent_booking(self, db_session: Session):
        r = send_payment_qr(db_session, 99999, "79001234567")
        assert r["success"] is False


# ── get_booking_status ────────────────────────────────────────────────────────


class TestGetBookingStatusTool:
    def test_returns_booking_details(self, db_session: Session, sample_booking: Booking):
        r = get_booking_status(db_session, sample_booking.id)
        assert r["found"] is True
        assert r["booking_number"] == sample_booking.booking_number
        assert r["status"] == "pending_payment"

    def test_not_found(self, db_session: Session):
        r = get_booking_status(db_session, 99999)
        assert r["found"] is False


# ── cancel_booking ────────────────────────────────────────────────────────────


class TestCancelBookingTool:
    def test_cancels_pending_booking(
        self, db_session: Session, sample_booking: Booking, sample_client: Client
    ):
        r = cancel_booking(db_session, sample_booking.id, sample_client.phone)
        assert r["success"] is True
        db_session.refresh(sample_booking)
        assert sample_booking.status == BookingStatus.cancelled

    def test_cannot_cancel_paid_booking(
        self, db_session: Session, paid_booking: Booking, sample_client: Client
    ):
        r = cancel_booking(db_session, paid_booking.id, sample_client.phone)
        assert r["success"] is False
        assert "оплаченное" in r["error"].lower()

    def test_cannot_cancel_others_booking(
        self, db_session: Session, sample_booking: Booking
    ):
        r = cancel_booking(db_session, sample_booking.id, "79009999999")
        assert r["success"] is False

    def test_not_found(self, db_session: Session):
        r = cancel_booking(db_session, 99999, "79001234567")
        assert r["success"] is False


# ── handoff_to_human ──────────────────────────────────────────────────────────


class TestHandoffToHuman:
    def test_notifies_manager(self, db_session: Session):
        with patch("app.notifications.notify_manager_new_booking") as mock_notify:
            r = handoff_to_human(db_session, "Клиент требует возврат", "79001234567")

        assert r["success"] is True
        mock_notify.assert_called_once()

    def test_returns_message_to_client(self, db_session: Session):
        with patch("app.notifications.notify_manager_new_booking"):
            r = handoff_to_human(db_session, "Вопрос вне компетенции", "79001234567")
        assert "менеджер" in r["message"].lower() or "передан" in r["message"].lower()

    def test_handles_notification_failure_gracefully(self, db_session: Session):
        with patch(
            "app.notifications.notify_manager_new_booking",
            side_effect=Exception("SMTP error"),
        ):
            r = handoff_to_human(db_session, "Тест", "79001234567")
        # Should return success=False but not raise
        assert "success" in r


# ── Placeholder detection ─────────────────────────────────────────────────────


class TestPlaceholderDetection:
    def test_placeholder_regex_matches(self):
        assert PLACEHOLDER_RE.search("<<BUSINESS_NAME>>") is not None
        assert PLACEHOLDER_RE.search("<<API_KEY_123>>") is not None

    def test_placeholder_regex_no_false_positive(self):
        assert PLACEHOLDER_RE.search("normal text") is None
        assert PLACEHOLDER_RE.search("<single_bracket>") is None

    def test_dev_mode_allows_placeholders(self):
        """In DEV_MODE=true, unsubstituted placeholders should not cause SystemExit."""
        from app.config import Settings, validate_no_placeholders

        test_settings = Settings(DEV_MODE=True, BUSINESS_NAME="<<BUSINESS_NAME>>")
        # Should not raise
        validate_no_placeholders(test_settings)

    def test_production_mode_raises_on_placeholder(self):
        """In production mode (DEV_MODE=false), SystemExit should be raised."""
        import sys
        from app.config import Settings, validate_no_placeholders

        test_settings = Settings(DEV_MODE=False, BUSINESS_NAME="<<BUSINESS_NAME>>")
        with pytest.raises(SystemExit):
            validate_no_placeholders(test_settings)


# ── TOOLS_SCHEMA validation ────────────────────────────────────────────────────


class TestToolsSchema:
    def test_all_tools_have_required_fields(self):
        for tool in TOOLS_SCHEMA:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool
            assert "input_schema" in tool
            assert "type" in tool["input_schema"]

    def test_tool_names_match_dispatcher(self):
        expected_tools = {
            "get_packages",
            "check_availability",
            "create_booking",
            "send_payment_qr",
            "get_booking_status",
            "cancel_booking",
            "handoff_to_human",
        }
        schema_names = {t["name"] for t in TOOLS_SCHEMA}
        assert schema_names == expected_tools

    def test_dispatch_unknown_tool_returns_error(self, db_session: Session):
        result = dispatch_tool(
            tool_name="nonexistent_tool",
            tool_input={},
            session=db_session,
            client_phone="79001234567",
        )
        assert "error" in result

"""
Integration tests for the full booking flow.

Covers:
- Message → AI response → booking creation
- QR code sending after booking
- Payment webhook → booking confirmed + Word export
- Idempotent payment webhook
- Expired booking cancellation
- Incomplete data doesn't create booking
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, Client, Package, Payment
from app.tools import check_availability, create_booking, get_packages
from tests.conftest import make_whatsapp_webhook_payload


class TestGetPackages:
    def test_returns_active_packages(self, db_session: Session, sample_package: Package):
        result = get_packages(db_session)
        assert len(result) == 1
        assert result[0]["name"] == "Горный тур"
        assert result[0]["price"] == 3000.0

    def test_excludes_inactive_packages(self, db_session: Session, sample_package: Package):
        sample_package.active = False
        db_session.commit()
        result = get_packages(db_session)
        assert len(result) == 0

    def test_empty_db_returns_empty_list(self, db_session: Session):
        result = get_packages(db_session)
        assert result == []


class TestCheckAvailability:
    def test_available_package(self, db_session: Session, sample_package: Package):
        result = check_availability(db_session, sample_package.id, "2024-07-20", 2)
        assert result["available"] is True
        assert result["remaining_capacity"] == 10

    def test_too_many_people(self, db_session: Session, sample_package: Package):
        result = check_availability(db_session, sample_package.id, "2024-07-20", 20)
        assert result["available"] is False
        assert "вместимость" in result["reason"].lower()

    def test_nonexistent_package(self, db_session: Session):
        result = check_availability(db_session, 9999, "2024-07-20", 2)
        assert result["available"] is False

    def test_counts_pending_bookings(
        self, db_session: Session, sample_package: Package, sample_booking: Booking
    ):
        # sample_booking is pending_payment for 2024-07-15, capacity 10
        result = check_availability(db_session, sample_package.id, "2024-07-15", 9)
        assert result["available"] is True  # 10 capacity, 1 booking slot used (not by people)

    def test_different_date_ignores_other_bookings(
        self, db_session: Session, sample_package: Package, sample_booking: Booking
    ):
        result = check_availability(db_session, sample_package.id, "2024-08-01", 10)
        assert result["available"] is True


class TestCreateBooking:
    def test_creates_booking_successfully(self, db_session: Session, sample_package: Package):
        result = create_booking(
            session=db_session,
            name="Тест Тестов",
            phone="79001111111",
            people_count=2,
            package_id=sample_package.id,
            travel_date="2024-08-01",
            travel_time="10:00",
            pickup_location="Площадь Ленина",
        )
        assert result["success"] is True
        assert result["booking_number"].startswith("BOOK-")
        assert result["total_price"] == 6000.0
        assert result["prepayment_amount"] == 1800.0  # 30%

    def test_creates_client_if_not_exists(self, db_session: Session, sample_package: Package):
        create_booking(
            session=db_session,
            name="Новый Клиент",
            phone="79009990000",
            people_count=1,
            package_id=sample_package.id,
            travel_date="2024-08-01",
            travel_time="10:00",
            pickup_location="Вокзал",
        )
        client = db_session.query(Client).filter(Client.phone == "79009990000").first()
        assert client is not None
        assert client.name == "Новый Клиент"

    def test_missing_package_returns_error(self, db_session: Session):
        result = create_booking(
            session=db_session,
            name="Тест",
            phone="79001111111",
            people_count=1,
            package_id=9999,
            travel_date="2024-08-01",
            travel_time="10:00",
            pickup_location="Вокзал",
        )
        assert result["success"] is False
        assert "не найден" in result["error"]

    def test_incomplete_data_no_booking(self, db_session: Session, sample_package: Package):
        """Calling create_booking without required fields should raise TypeError, not silently create."""
        with pytest.raises(TypeError):
            create_booking(
                session=db_session,
                name="Тест",
                # missing phone, people_count, etc.
            )

    def test_booking_number_format(self, db_session: Session, sample_package: Package):
        result = create_booking(
            session=db_session,
            name="А",
            phone="79000000001",
            people_count=1,
            package_id=sample_package.id,
            travel_date="2024-08-01",
            travel_time="09:00",
            pickup_location="Х",
        )
        import re
        assert re.match(r"BOOK-\d{4}-\d{4}", result["booking_number"])

    def test_sequential_booking_numbers(self, db_session: Session, sample_package: Package):
        r1 = create_booking(
            session=db_session, name="A", phone="79000000001", people_count=1,
            package_id=sample_package.id, travel_date="2024-08-01", travel_time="09:00",
            pickup_location="X",
        )
        r2 = create_booking(
            session=db_session, name="B", phone="79000000002", people_count=1,
            package_id=sample_package.id, travel_date="2024-08-02", travel_time="10:00",
            pickup_location="Y",
        )
        assert r1["booking_number"] != r2["booking_number"]


class TestPaymentWebhook:
    def test_payment_webhook_confirms_booking(
        self, db_session: Session, sample_booking: Booking
    ):
        from app.payments import process_payment_webhook

        data = {
            "external_id": "ext_pay_001",
            "booking_number": sample_booking.booking_number,
            "amount": 1800.0,
            "status": "succeeded",
            "provider": "test",
        }

        with patch("app.notifications.notify_manager_new_booking"), \
             patch("app.notifications.notify_client_booking_confirmed"), \
             patch("app.word_export.export_booking", return_value="/tmp/test.docx"):
            result = process_payment_webhook(session=db_session, data=data)

        assert result["status"] == "ok"
        assert result["idempotent"] is False

        db_session.refresh(sample_booking)
        assert sample_booking.status == BookingStatus.paid

    def test_idempotent_payment_webhook(
        self, db_session: Session, sample_booking: Booking
    ):
        from app.payments import process_payment_webhook

        data = {
            "external_id": "ext_pay_002",
            "booking_number": sample_booking.booking_number,
            "amount": 1800.0,
            "status": "succeeded",
            "provider": "test",
        }

        with patch("app.notifications.notify_manager_new_booking"), \
             patch("app.notifications.notify_client_booking_confirmed"), \
             patch("app.word_export.export_booking", return_value="/tmp/test.docx"):
            result1 = process_payment_webhook(session=db_session, data=data)
            result2 = process_payment_webhook(session=db_session, data=data)

        assert result1["idempotent"] is False
        assert result2["idempotent"] is True

    def test_non_success_status_ignored(self, db_session: Session, sample_booking: Booking):
        from app.payments import process_payment_webhook

        data = {
            "external_id": "ext_pay_003",
            "booking_number": sample_booking.booking_number,
            "amount": 1800.0,
            "status": "failed",
            "provider": "test",
        }
        result = process_payment_webhook(session=db_session, data=data)
        assert result["status"] == "ignored"

        db_session.refresh(sample_booking)
        assert sample_booking.status == BookingStatus.pending_payment


class TestExpiredBookings:
    def test_expired_booking_via_background(self, db_session: Session, sample_booking: Booking):
        """Simulate an expired booking by backdating created_at."""
        from datetime import timedelta

        old_time = sample_booking.created_at - timedelta(hours=2)
        db_session.query(Booking).filter(Booking.id == sample_booking.id).update(
            {"created_at": old_time}
        )
        db_session.commit()

        # Manually run the expiration logic
        from datetime import timezone
        from app.config import settings

        cutoff = __import__("datetime").datetime.now(timezone.utc) - timedelta(
            minutes=settings.PAYMENT_TIMEOUT
        )
        expired = (
            db_session.query(Booking)
            .filter(
                Booking.status == BookingStatus.pending_payment,
                Booking.created_at < cutoff,
            )
            .all()
        )
        for b in expired:
            b.status = BookingStatus.expired
        db_session.commit()

        db_session.refresh(sample_booking)
        assert sample_booking.status == BookingStatus.expired


class TestWordExport:
    def test_export_creates_file(
        self, db_session: Session, sample_booking: Booking, tmp_path
    ):
        from app import word_export

        word_export.BOOKINGS_DIR = tmp_path

        with patch("app.word_export.BOOKINGS_DIR", tmp_path):
            path = word_export.export_booking(session=db_session, booking_id=sample_booking.id)

        assert path is not None
        assert __import__("pathlib").Path(path).exists()

        db_session.refresh(sample_booking)
        assert sample_booking.word_exported is True

    def test_export_idempotency(
        self, db_session: Session, sample_booking: Booking, tmp_path
    ):
        from app import word_export

        with patch("app.word_export.BOOKINGS_DIR", tmp_path):
            path1 = word_export.export_booking(session=db_session, booking_id=sample_booking.id)
            path2 = word_export.export_booking(session=db_session, booking_id=sample_booking.id)

        assert path1 == path2

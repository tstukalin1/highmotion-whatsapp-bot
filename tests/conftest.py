"""
pytest fixtures for the WhatsApp AI bot test suite.

Provides:
  - In-memory SQLite database (isolated per test)
  - FastAPI test client
  - Mock WhatsApp API client
  - Mock Anthropic client
  - Sample packages and bookings
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# ── Patch settings BEFORE importing app modules ────────────────────────────────

import os

os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456789")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_verify_token")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test_app_secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test_anthropic_key")
os.environ.setdefault("ADMIN_API_TOKEN", "test_admin_token")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "test_payment_secret")
os.environ.setdefault("BUSINESS_NAME", "Test Tours")
os.environ.setdefault("PAYMENT_PROVIDER", "generic")
os.environ.setdefault("PAYMENT_DETAILS", "https://pay.example.com")
os.environ.setdefault("MANAGER_PHONE", "79001234567")
os.environ.setdefault("MANAGER_EMAIL", "manager@example.com")

from app.models import Base, Booking, BookingStatus, Client, Message, MessageRole, Package
from app.main import app, get_db

# ── Database ───────────────────────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def reset_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with DB dependency override."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ── Sample data ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_package(db_session: Session) -> Package:
    package = Package(
        name="Горный тур",
        description="Однодневный тур в горы",
        price=Decimal("3000.00"),
        capacity=10,
        duration_hours=8,
        includes=["Трансфер", "Обед"],
        active=True,
    )
    db_session.add(package)
    db_session.commit()
    db_session.refresh(package)
    return package


@pytest.fixture
def sample_client(db_session: Session) -> Client:
    client = Client(phone="79001234567", name="Иван Иванов")
    db_session.add(client)
    db_session.commit()
    db_session.refresh(client)
    return client


@pytest.fixture
def sample_booking(db_session: Session, sample_client: Client, sample_package: Package) -> Booking:
    booking = Booking(
        booking_number="BOOK-2024-0001",
        client_id=sample_client.id,
        package_id=sample_package.id,
        people_count=2,
        travel_date="2024-07-15",
        travel_time="09:00",
        pickup_location="ул. Ленина 1",
        notes="",
        status=BookingStatus.pending_payment,
        total_price=Decimal("6000.00"),
        prepayment_amount=Decimal("1800.00"),
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)
    return booking


@pytest.fixture
def paid_booking(db_session: Session, sample_booking: Booking) -> Booking:
    sample_booking.status = BookingStatus.paid
    db_session.commit()
    db_session.refresh(sample_booking)
    return sample_booking


# ── Mocks ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_whatsapp():
    """Mock WhatsApp send functions."""
    with patch("app.whatsapp.send_text") as mock_text, \
         patch("app.whatsapp.send_image") as mock_image, \
         patch("app.whatsapp.send_template") as mock_template, \
         patch("app.whatsapp.mark_as_read") as mock_read, \
         patch("app.whatsapp._within_24h_window", return_value=True):
        mock_text.return_value = {"messages": [{"id": "wamid.test123"}]}
        mock_image.return_value = {"messages": [{"id": "wamid.test456"}]}
        mock_template.return_value = {"messages": [{"id": "wamid.test789"}]}
        mock_read.return_value = {"success": True}
        yield {
            "send_text": mock_text,
            "send_image": mock_image,
            "send_template": mock_template,
            "mark_as_read": mock_read,
        }


@pytest.fixture
def mock_anthropic():
    """Mock Anthropic client for AI agent tests."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(type="text", text="Мок-ответ от ассистента")]

    with patch("anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = mock_response
        yield instance


@pytest.fixture
def mock_qr(tmp_path):
    """Mock QR generation to avoid PIL dependency in tests."""
    qr_path = str(tmp_path / "booking_1.png")
    # Create a minimal PNG-like file
    Path_obj = __import__("pathlib").Path
    Path_obj(qr_path).write_bytes(b"\x89PNG\r\n\x1a\n")

    with patch("app.qr.generate_payment_qr", return_value=qr_path):
        yield qr_path


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_whatsapp_webhook_payload(
    phone: str = "79001234567",
    message_id: str = "wamid.test001",
    text: str = "Привет",
) -> dict:
    """Build a minimal WhatsApp webhook payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "ENTRY_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "79009999999",
                                "phone_number_id": "123456789",
                            },
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

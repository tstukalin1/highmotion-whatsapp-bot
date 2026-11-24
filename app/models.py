"""
SQLAlchemy ORM models.

Default backend: SQLite (suitable for development and small deployments).
To switch to PostgreSQL set DATABASE_URL=postgresql+asyncpg://... in .env
and install asyncpg / psycopg2-binary.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────


class BookingStatus(str, enum.Enum):
    draft = "draft"
    pending_payment = "pending_payment"
    paid = "paid"
    cancelled = "cancelled"
    expired = "expired"


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


# ── Models ────────────────────────────────────────────────────────────────────


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    gdpr_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    bookings: Mapped[List["Booking"]] = relationship("Booking", back_populates="client")
    messages: Mapped[List["Message"]] = relationship(
        "Message", foreign_keys="Message.client_phone", primaryjoin="Client.phone == Message.client_phone"
    )


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    includes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    bookings: Mapped[List["Booking"]] = relationship("Booking", back_populates="package")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)

    people_count: Mapped[int] = mapped_column(Integer, nullable=False)
    travel_date: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # YYYY-MM-DD
    travel_time: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)   # HH:MM
    pickup_location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus), default=BookingStatus.draft, nullable=False
    )
    total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    prepayment_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    word_exported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    client: Mapped["Client"] = relationship("Client", back_populates="bookings")
    package: Mapped["Package"] = relationship("Package", back_populates="bookings")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="booking")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    booking: Mapped["Booking"] = relationship("Booking", back_populates="payments")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tool_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def generate_booking_number(session: Session, year: int) -> str:
    """Generate a sequential booking number like BOOK-2024-0001."""
    prefix = f"BOOK-{year}-"
    # Count existing bookings for this year
    count = session.scalar(
        select(func.count()).select_from(Booking).where(
            Booking.booking_number.like(f"{prefix}%")
        )
    ) or 0
    return f"{prefix}{count + 1:04d}"

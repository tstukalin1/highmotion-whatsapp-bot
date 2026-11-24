"""
Tool definitions for the Claude AI agent.

Each tool has:
- A Python implementation function
- An Anthropic-format tool schema entry in TOOLS_SCHEMA

Tool implementations interact directly with the database and other app modules.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Booking,
    BookingStatus,
    Client,
    Package,
    generate_booking_number,
)

logger = logging.getLogger(__name__)


# ── Tool implementations ──────────────────────────────────────────────────────


def get_packages(session: Session) -> list[dict]:
    """Return all active tour packages from the database."""
    packages = session.query(Package).filter(Package.active == True).all()
    result = []
    for p in packages:
        result.append(
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price": float(p.price),
                "capacity": p.capacity,
                "duration_hours": p.duration_hours,
                "includes": p.includes or [],
            }
        )
    return result


def check_availability(
    session: Session,
    package_id: int,
    travel_date: str,
    people_count: int,
) -> dict:
    """
    Check if a package is available on a given date for the requested number of people.

    Returns availability status and remaining capacity.
    """
    package = session.query(Package).filter(Package.id == package_id).first()
    if not package:
        return {"available": False, "reason": "Пакет не найден"}
    if not package.active:
        return {"available": False, "reason": "Пакет недоступен"}

    # Count existing paid/pending bookings for this package on the same date
    existing_count = (
        session.query(Booking)
        .filter(
            Booking.package_id == package_id,
            Booking.travel_date == travel_date,
            Booking.status.in_(
                [BookingStatus.paid, BookingStatus.pending_payment]
            ),
        )
        .count()
    )

    if people_count > package.capacity:
        return {
            "available": False,
            "reason": f"Максимальная вместимость пакета — {package.capacity} человек",
        }

    total_booked = existing_count
    if total_booked >= package.capacity:
        return {"available": False, "reason": "На эту дату мест нет"}

    remaining = package.capacity - total_booked
    return {
        "available": True,
        "remaining_capacity": remaining,
        "package_name": package.name,
        "price_per_person": float(package.price),
        "total_price": float(package.price) * people_count,
    }


def create_booking(
    session: Session,
    name: str,
    phone: str,
    people_count: int,
    package_id: int,
    travel_date: str,
    travel_time: str,
    pickup_location: str,
    notes: str = "",
) -> dict:
    """
    Create a new booking in the database.

    Creates or updates the client record, then creates a draft booking.
    Returns booking details including the booking number.
    """
    # Validate package exists
    package = session.query(Package).filter(Package.id == package_id).first()
    if not package:
        return {"success": False, "error": "Пакет не найден"}

    # Get or create client
    client = session.query(Client).filter(Client.phone == phone).first()
    if client:
        if name and not client.gdpr_deleted:
            client.name = name
    else:
        client = Client(phone=phone, name=name)
        session.add(client)
        session.flush()  # get id

    # Calculate prices
    total_price = Decimal(str(package.price)) * people_count
    prepayment_amount = (total_price * settings.PREPAYMENT_PERCENT / 100).quantize(
        Decimal("0.01")
    )

    year = datetime.now().year
    booking_number = generate_booking_number(session, year)

    booking = Booking(
        booking_number=booking_number,
        client_id=client.id,
        package_id=package_id,
        people_count=people_count,
        travel_date=travel_date,
        travel_time=travel_time,
        pickup_location=pickup_location,
        notes=notes,
        status=BookingStatus.pending_payment,
        total_price=total_price,
        prepayment_amount=prepayment_amount,
    )
    session.add(booking)
    session.commit()
    session.refresh(booking)

    return {
        "success": True,
        "booking_id": booking.id,
        "booking_number": booking.booking_number,
        "total_price": float(total_price),
        "prepayment_amount": float(prepayment_amount),
        "status": booking.status.value,
        "message": (
            f"Бронирование {booking_number} создано. "
            f"Предоплата: {prepayment_amount} руб. "
            f"QR-код для оплаты будет отправлен."
        ),
    }


def send_payment_qr(session: Session, booking_id: int, phone: str) -> dict:
    """Generate a payment QR code and send it to the client via WhatsApp."""
    from app import qr as qr_module
    from app import whatsapp

    booking = session.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return {"success": False, "error": "Бронирование не найдено"}

    if booking.status not in (BookingStatus.pending_payment, BookingStatus.draft):
        return {"success": False, "error": f"Бронирование в статусе {booking.status.value}"}

    try:
        qr_path = qr_module.generate_payment_qr(
            booking_id=booking.id,
            amount=float(booking.prepayment_amount or booking.total_price),
            booking_number=booking.booking_number,
        )
        caption = (
            f"Оплата брони {booking.booking_number}\n"
            f"Сумма предоплаты: {booking.prepayment_amount} руб.\n"
            f"Общая стоимость: {booking.total_price} руб.\n"
            f"Способ оплаты: {settings.PAYMENT_PROVIDER.upper()}\n\n"
            f"После оплаты ваше бронирование будет подтверждено."
        )
        whatsapp.send_image(phone=phone, image_path=qr_path, caption=caption)
        return {
            "success": True,
            "qr_path": qr_path,
            "message": "QR-код для оплаты отправлен",
        }
    except Exception as exc:
        logger.error("Failed to send payment QR: %s", exc)
        return {"success": False, "error": str(exc)}


def get_booking_status(session: Session, booking_id: int) -> dict:
    """Return current status and details of a booking."""
    booking = session.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return {"found": False, "error": "Бронирование не найдено"}

    return {
        "found": True,
        "booking_id": booking.id,
        "booking_number": booking.booking_number,
        "status": booking.status.value,
        "travel_date": booking.travel_date,
        "travel_time": booking.travel_time,
        "people_count": booking.people_count,
        "total_price": float(booking.total_price) if booking.total_price else None,
        "prepayment_amount": float(booking.prepayment_amount) if booking.prepayment_amount else None,
        "pickup_location": booking.pickup_location,
        "notes": booking.notes,
    }


def cancel_booking(session: Session, booking_id: int, phone: str) -> dict:
    """Cancel a booking if it belongs to the requesting phone number."""
    booking = session.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return {"success": False, "error": "Бронирование не найдено"}

    # Verify ownership
    client = session.query(Client).filter(Client.phone == phone).first()
    if not client or booking.client_id != client.id:
        return {"success": False, "error": "Нет доступа к этому бронированию"}

    if booking.status in (BookingStatus.cancelled, BookingStatus.expired):
        return {"success": False, "error": "Бронирование уже отменено"}

    if booking.status == BookingStatus.paid:
        return {
            "success": False,
            "error": "Оплаченное бронирование нельзя отменить через бот. Обратитесь к менеджеру.",
        }

    booking.status = BookingStatus.cancelled
    session.commit()

    return {
        "success": True,
        "booking_number": booking.booking_number,
        "message": f"Бронирование {booking.booking_number} отменено.",
    }


def handoff_to_human(session: Session, reason: str, phone: str) -> dict:
    """
    Escalate the conversation to a human manager.

    Sends a notification to the manager via WhatsApp and/or email.
    """
    from app import notifications

    try:
        # We pass booking_id=None as we don't have one in this context
        notifications.notify_manager_new_booking(
            booking_id=None,
            custom_message=(
                f"Клиент {phone} запросил помощь менеджера.\n"
                f"Причина: {reason}"
            ),
        )
        return {
            "success": True,
            "message": (
                "Ваш запрос передан менеджеру. "
                "Мы свяжемся с вами в ближайшее время."
            ),
        }
    except Exception as exc:
        logger.error("handoff_to_human failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "message": "Не удалось связаться с менеджером. Попробуйте позвонить напрямую.",
        }


# ── Anthropic tool schemas ────────────────────────────────────────────────────

TOOLS_SCHEMA: list[dict] = [
    {
        "name": "get_packages",
        "description": (
            "Получить список всех доступных туристических пакетов/экскурсий. "
            "Используй этот инструмент когда клиент хочет узнать о доступных турах или ценах."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "check_availability",
        "description": (
            "Проверить наличие мест в туре на конкретную дату. "
            "Используй перед созданием бронирования."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "integer",
                    "description": "ID пакета/тура из get_packages",
                },
                "travel_date": {
                    "type": "string",
                    "description": "Дата поездки в формате YYYY-MM-DD",
                },
                "people_count": {
                    "type": "integer",
                    "description": "Количество человек",
                },
            },
            "required": ["package_id", "travel_date", "people_count"],
        },
    },
    {
        "name": "create_booking",
        "description": (
            "Создать новое бронирование. Используй ТОЛЬКО когда клиент подтвердил "
            "все детали (имя, дата, количество людей, место отправления). "
            "Перед созданием обязательно вызови check_availability."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Имя клиента"},
                "phone": {"type": "string", "description": "Номер телефона клиента"},
                "people_count": {"type": "integer", "description": "Количество человек"},
                "package_id": {"type": "integer", "description": "ID пакета"},
                "travel_date": {
                    "type": "string",
                    "description": "Дата поездки YYYY-MM-DD",
                },
                "travel_time": {
                    "type": "string",
                    "description": "Время отправления HH:MM",
                },
                "pickup_location": {
                    "type": "string",
                    "description": "Место откуда забрать клиента",
                },
                "notes": {
                    "type": "string",
                    "description": "Дополнительные пожелания клиента",
                },
            },
            "required": [
                "name",
                "phone",
                "people_count",
                "package_id",
                "travel_date",
                "travel_time",
                "pickup_location",
            ],
        },
    },
    {
        "name": "send_payment_qr",
        "description": (
            "Отправить QR-код для оплаты предоплаты клиенту. "
            "Вызывай после успешного создания бронирования."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "integer",
                    "description": "ID бронирования из create_booking",
                },
                "phone": {
                    "type": "string",
                    "description": "WhatsApp номер клиента",
                },
            },
            "required": ["booking_id", "phone"],
        },
    },
    {
        "name": "get_booking_status",
        "description": (
            "Получить текущий статус и детали бронирования по его ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "integer",
                    "description": "ID бронирования",
                },
            },
            "required": ["booking_id"],
        },
    },
    {
        "name": "cancel_booking",
        "description": (
            "Отменить бронирование по запросу клиента. "
            "Работает только для не оплаченных броней."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "integer", "description": "ID бронирования"},
                "phone": {
                    "type": "string",
                    "description": "Телефон клиента для проверки владельца",
                },
            },
            "required": ["booking_id", "phone"],
        },
    },
    {
        "name": "handoff_to_human",
        "description": (
            "Передать разговор живому менеджеру. Используй когда: "
            "клиент явно просит менеджера, вопрос вне компетенции бота, "
            "конфликтная ситуация, жалоба, нестандартный запрос."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Причина передачи менеджеру (для уведомления)",
                },
                "phone": {
                    "type": "string",
                    "description": "Телефон клиента",
                },
            },
            "required": ["reason", "phone"],
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────


def dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    session: Session,
    client_phone: str,
) -> Any:
    """
    Route a tool call from the AI agent to the correct implementation.

    Returns a JSON-serialisable result.
    """
    logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_input, ensure_ascii=False))

    if tool_name == "get_packages":
        return get_packages(session)

    elif tool_name == "check_availability":
        return check_availability(
            session=session,
            package_id=tool_input["package_id"],
            travel_date=tool_input["travel_date"],
            people_count=tool_input["people_count"],
        )

    elif tool_name == "create_booking":
        return create_booking(
            session=session,
            name=tool_input["name"],
            phone=tool_input.get("phone", client_phone),
            people_count=tool_input["people_count"],
            package_id=tool_input["package_id"],
            travel_date=tool_input["travel_date"],
            travel_time=tool_input["travel_time"],
            pickup_location=tool_input["pickup_location"],
            notes=tool_input.get("notes", ""),
        )

    elif tool_name == "send_payment_qr":
        return send_payment_qr(
            session=session,
            booking_id=tool_input["booking_id"],
            phone=tool_input.get("phone", client_phone),
        )

    elif tool_name == "get_booking_status":
        return get_booking_status(session=session, booking_id=tool_input["booking_id"])

    elif tool_name == "cancel_booking":
        return cancel_booking(
            session=session,
            booking_id=tool_input["booking_id"],
            phone=tool_input.get("phone", client_phone),
        )

    elif tool_name == "handoff_to_human":
        return handoff_to_human(
            session=session,
            reason=tool_input["reason"],
            phone=tool_input.get("phone", client_phone),
        )

    else:
        logger.error("Unknown tool called: %s", tool_name)
        return {"error": f"Unknown tool: {tool_name}"}

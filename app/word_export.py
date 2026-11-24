"""
Word document export for bookings.

One .docx file is created per travel date:
    bookings/bookings_YYYY-MM-DD.docx

Each booking is appended as a row in the document's table.
File-level locks prevent concurrent corruption.
Idempotency is guaranteed via the Booking.word_exported flag.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Pt, RGBColor
from sqlalchemy.orm import Session

from app.models import Booking, Client, Package

logger = logging.getLogger(__name__)

BOOKINGS_DIR = Path(__file__).parent.parent / "bookings"

# Map file path -> threading lock (created on first access)
_file_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def _get_lock(file_path: str) -> threading.Lock:
    """Return (or create) a per-file threading lock."""
    with _locks_meta:
        if file_path not in _file_locks:
            _file_locks[file_path] = threading.Lock()
        return _file_locks[file_path]


def _ensure_dir() -> None:
    BOOKINGS_DIR.mkdir(parents=True, exist_ok=True)


def _create_document(travel_date: str, business_name: str) -> Document:
    """Create a fresh document with header and empty table."""
    doc = Document()

    # ── Header ────────────────────────────────────────────────────────────────
    heading = doc.add_heading(business_name, level=1)
    heading.runs[0].font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)

    doc.add_paragraph(f"Список бронирований на {travel_date}")
    doc.add_paragraph(f"Сформирован: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    doc.add_paragraph("")  # spacer

    # ── Table ─────────────────────────────────────────────────────────────────
    columns = [
        "№",
        "Имя клиента",
        "Телефон",
        "Кол-во человек",
        "Пакет",
        "Дата и время",
        "Откуда забрать",
        "Сумма / Предоплата",
        "Комментарии",
    ]
    table = doc.add_table(rows=1, cols=len(columns))
    table.style = "Table Grid"

    hdr_row = table.rows[0]
    for i, col_name in enumerate(columns):
        cell = hdr_row.cells[i]
        cell.text = col_name
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(10)

    return doc


def _load_or_create_document(file_path: str, travel_date: str) -> Document:
    """Load existing document or create a new one."""
    from app.config import settings

    path = Path(file_path)
    if path.exists():
        return Document(str(path))

    _ensure_dir()

    # Try to get business name from business.example.json
    business_json = Path(__file__).parent.parent / "data" / "business.example.json"
    business_name = settings.BUSINESS_NAME
    if business_json.exists():
        try:
            data = json.loads(business_json.read_text(encoding="utf-8"))
            business_name = data.get("name", business_name)
        except Exception:
            pass

    return _create_document(travel_date, business_name)


def export_booking(session: Session, booking_id: int) -> Optional[str]:
    """
    Export a booking to the daily Word document.

    Returns the file path, or None if already exported (idempotent).
    """
    booking = session.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        logger.error("export_booking: booking %d not found", booking_id)
        return None

    if booking.word_exported:
        logger.info("Booking %d already exported, skipping", booking_id)
        travel_date = booking.travel_date or datetime.now().strftime("%Y-%m-%d")
        return str(BOOKINGS_DIR / f"bookings_{travel_date}.docx")

    travel_date = booking.travel_date or datetime.now().strftime("%Y-%m-%d")
    file_path = str(BOOKINGS_DIR / f"bookings_{travel_date}.docx")
    lock = _get_lock(file_path)

    with lock:
        # Reload booking inside lock to re-check idempotency flag
        session.refresh(booking)
        if booking.word_exported:
            return file_path

        doc = _load_or_create_document(file_path, travel_date)

        # Fetch related data
        client = session.query(Client).filter(Client.id == booking.client_id).first()
        package = session.query(Package).filter(Package.id == booking.package_id).first()

        client_name = (client.name or client.phone) if client else str(booking.client_id)
        client_phone = client.phone if client else ""
        package_name = package.name if package else str(booking.package_id)

        total = f"{booking.total_price}" if booking.total_price else "—"
        prepay = f"{booking.prepayment_amount}" if booking.prepayment_amount else "—"
        money_cell = f"{total} / {prepay}"

        datetime_cell = f"{booking.travel_date or ''} {booking.travel_time or ''}".strip()

        # Find the table (should be index 0)
        if not doc.tables:
            logger.error("No table found in document %s", file_path)
            return None

        table = doc.tables[0]
        row_count = len(table.rows) - 1  # excluding header
        new_row = table.add_row()

        values = [
            str(row_count + 1),
            client_name,
            client_phone,
            str(booking.people_count),
            package_name,
            datetime_cell,
            booking.pickup_location or "—",
            money_cell,
            booking.notes or "",
        ]

        for i, value in enumerate(values):
            cell = new_row.cells[i]
            cell.text = value
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9)

        doc.save(file_path)

        # Mark as exported
        booking.word_exported = True
        session.commit()

        logger.info("Booking %d exported to %s", booking_id, file_path)
        return file_path

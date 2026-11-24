"""
FastAPI application entry point.

Endpoints:
  GET  /webhook                     — WhatsApp webhook verification
  POST /webhook                     — Incoming WhatsApp messages
  POST /webhook/payment             — Payment provider webhook
  POST /admin/bookings/{id}/confirm — Manual booking confirmation
  POST /admin/bookings/{id}/cancel  — Admin cancel booking
  GET  /admin/bookings              — List bookings
  DELETE /admin/clients/{phone}     — GDPR delete client

Background tasks:
  - Expire unpaid bookings every 60 seconds
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    Security,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings, validate_no_placeholders
from app.models import Base, Booking, BookingStatus, Client, Message, Package
from app import whatsapp, ai_agent, payments as pay_module

logger = logging.getLogger(__name__)
logging.basicConfig(level=settings.LOG_LEVEL)

# ── Database setup ─────────────────────────────────────────────────────────────

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Rate limiting (in-memory) ──────────────────────────────────────────────────

_rate_counters: dict[str, list[float]] = {}  # phone -> list of timestamps


def _is_rate_limited(phone: str) -> bool:
    now = time.time()
    window = 3600  # 1 hour
    timestamps = _rate_counters.get(phone, [])
    # Remove old entries
    timestamps = [t for t in timestamps if now - t < window]
    if len(timestamps) >= settings.RATE_LIMIT_PER_HOUR:
        _rate_counters[phone] = timestamps
        return True
    timestamps.append(now)
    _rate_counters[phone] = timestamps
    return False


# ── Background: expire unpaid bookings ────────────────────────────────────────

import asyncio


async def _expire_bookings_loop() -> None:
    """Background coroutine: cancel bookings whose payment window has expired."""
    while True:
        await asyncio.sleep(60)
        try:
            db = SessionLocal()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.PAYMENT_TIMEOUT)
                expired = (
                    db.query(Booking)
                    .filter(
                        Booking.status == BookingStatus.pending_payment,
                        Booking.created_at < cutoff,
                    )
                    .all()
                )
                for booking in expired:
                    booking.status = BookingStatus.expired
                    logger.info("Booking %s expired", booking.booking_number)
                if expired:
                    db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.error("Error in expire_bookings_loop: %s", exc)


# ── Seed packages ─────────────────────────────────────────────────────────────


def _seed_packages_if_empty(db: Session) -> None:
    """Populate Package table from data/packages.example.json if DB is empty."""
    if db.query(Package).count() > 0:
        return

    packages_file = Path(__file__).parent.parent / "data" / "packages.example.json"
    if not packages_file.exists():
        logger.warning("packages.example.json not found, skipping seed")
        return

    try:
        data = json.loads(packages_file.read_text(encoding="utf-8"))
        for item in data:
            try:
                price = float(str(item.get("price", "0")).replace("<<", "0").replace(">>", ""))
            except ValueError:
                price = 0.0
            try:
                capacity = int(str(item.get("capacity", "10")).replace("<<", "10").replace(">>", ""))
            except ValueError:
                capacity = 10
            try:
                duration = int(str(item.get("duration_hours", "8")).replace("<<", "8").replace(">>", ""))
            except ValueError:
                duration = 8

            package = Package(
                name=item.get("name", "Package"),
                description=item.get("description", ""),
                price=price,
                capacity=capacity,
                duration_hours=duration,
                includes=item.get("includes", []),
                active=item.get("active", True),
            )
            db.add(package)
        db.commit()
        logger.info("Seeded %d packages from packages.example.json", len(data))
    except Exception as exc:
        logger.error("Failed to seed packages: %s", exc)


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    validate_no_placeholders(settings)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed_packages_if_empty(db)
    finally:
        db.close()
    task = asyncio.create_task(_expire_bookings_loop())
    logger.info("Application started — %s", settings.BUSINESS_NAME)
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=f"{settings.BUSINESS_NAME} WhatsApp Bot",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Auth ───────────────────────────────────────────────────────────────────────

bearer_scheme = HTTPBearer()


def require_admin_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> None:
    if credentials.credentials != settings.ADMIN_API_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token")


# ── WhatsApp webhook ───────────────────────────────────────────────────────────


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    challenge = whatsapp.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return Response(content=challenge, media_type="text/plain")


@app.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    body_bytes = await request.body()

    # Signature verification
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp.verify_signature(body_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    parsed = whatsapp.parse_incoming_message(data)
    if not parsed:
        return {"status": "ignored"}

    phone = parsed["phone"]
    message_id = parsed.get("message_id")
    text = parsed.get("text")

    if not text:
        return {"status": "ignored", "reason": "no_text"}

    # Rate limiting
    if _is_rate_limited(phone):
        logger.warning("Rate limit exceeded for %s", phone)
        # Mark as read but don't process
        if message_id:
            try:
                whatsapp.mark_as_read(message_id)
            except Exception:
                pass
        return {"status": "rate_limited"}

    # Mark as read immediately
    if message_id:
        background_tasks.add_task(_mark_read_safe, message_id)

    # Process message in background to return 200 quickly
    background_tasks.add_task(_handle_message, phone, text)

    return {"status": "ok"}


async def _mark_read_safe(message_id: str) -> None:
    try:
        whatsapp.mark_as_read(message_id)
    except Exception as exc:
        logger.warning("mark_as_read failed: %s", exc)


async def _handle_message(phone: str, text: str) -> None:
    db = SessionLocal()
    try:
        response_text = ai_agent.process_message(session=db, phone=phone, text=text)
        if response_text:
            whatsapp.send_text(phone=phone, text=response_text)
    except Exception as exc:
        logger.error("Error handling message from %s: %s", phone, exc)
        try:
            whatsapp.send_text(
                phone=phone,
                text="Произошла ошибка. Пожалуйста, попробуйте позже или обратитесь к менеджеру.",
            )
        except Exception:
            pass
    finally:
        db.close()


# ── Payment webhook ────────────────────────────────────────────────────────────


@app.post("/webhook/payment")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    body_bytes = await request.body()
    signature = request.headers.get("X-Payment-Signature", "") or request.headers.get(
        "X-Hub-Signature-256", ""
    )

    if not pay_module.verify_payment_signature(body_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid payment signature")

    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    result = pay_module.process_payment_webhook(session=db, data=data)
    return result


# ── Admin endpoints ────────────────────────────────────────────────────────────


@app.post("/admin/bookings/{booking_id}/confirm", dependencies=[Depends(require_admin_token)])
async def admin_confirm_booking(booking_id: int, db: Session = Depends(get_db)):
    result = pay_module.confirm_booking_manually(session=db, booking_id=booking_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@app.post("/admin/bookings/{booking_id}/cancel", dependencies=[Depends(require_admin_token)])
async def admin_cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status in (BookingStatus.cancelled, BookingStatus.expired):
        raise HTTPException(status_code=400, detail="Already cancelled")
    booking.status = BookingStatus.cancelled
    db.commit()
    return {"success": True, "booking_number": booking.booking_number}


@app.get("/admin/bookings", dependencies=[Depends(require_admin_token)])
async def admin_list_bookings(
    db: Session = Depends(get_db),
    travel_date: Optional[str] = Query(None, description="Filter by travel date YYYY-MM-DD"),
    booking_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
):
    query = db.query(Booking)
    if travel_date:
        query = query.filter(Booking.travel_date == travel_date)
    if booking_status:
        try:
            query = query.filter(Booking.status == BookingStatus(booking_status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {booking_status}")
    total = query.count()
    bookings = query.order_by(Booking.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "bookings": [
            {
                "id": b.id,
                "booking_number": b.booking_number,
                "client_id": b.client_id,
                "package_id": b.package_id,
                "people_count": b.people_count,
                "travel_date": b.travel_date,
                "travel_time": b.travel_time,
                "status": b.status.value,
                "total_price": float(b.total_price) if b.total_price else None,
                "prepayment_amount": float(b.prepayment_amount) if b.prepayment_amount else None,
                "created_at": b.created_at.isoformat(),
            }
            for b in bookings
        ],
    }


@app.delete("/admin/clients/{phone}", dependencies=[Depends(require_admin_token)])
async def gdpr_delete_client(phone: str, db: Session = Depends(get_db)):
    """
    GDPR right-to-erasure: anonymise client data while preserving booking records.
    """
    client = db.query(Client).filter(Client.phone == phone).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.name = "[DELETED]"
    client.gdpr_deleted = True

    # Anonymise message history
    db.query(Message).filter(Message.client_phone == phone).delete()

    db.commit()
    return {"success": True, "phone": phone}

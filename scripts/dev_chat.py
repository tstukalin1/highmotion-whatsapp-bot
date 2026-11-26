#!/usr/bin/env python3
"""
Dev chat CLI — тест ИИ-агента без WhatsApp.

Запуск:
    # Из корня проекта:
    DEV_MODE=true ANTHROPIC_API_KEY=sk-ant-... python scripts/dev_chat.py

    # Или если уже есть .env:
    DEV_MODE=true python scripts/dev_chat.py

Что происходит:
  - Создаётся временная in-memory SQLite БД
  - Пакеты загружаются из data/packages.example.json (если файл заполнен)
  - Ты вводишь текст — агент отвечает как будто это WhatsApp-сообщение
  - Все звонки к Meta API перехватываются заглушкой (DEV_MODE=true)
  - Только ANTHROPIC_API_KEY реальный — ответы от Claude настоящие

Команды:
  /quit, /exit, /q  — выйти
  /reset            — сбросить историю диалога (новый клиент)
  /status           — показать текущие брони в БД
  /bookings         — то же, что /status
  /phone <номер>    — сменить тестовый номер телефона (default: 79001234567)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Убедимся, что корень проекта в PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Загружаем .env до всех проверок
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# Включаем DEV_MODE до импорта конфига
os.environ.setdefault("DEV_MODE", "true")

# Минимальные заглушки для незаполненных плейсхолдеров
_STUBS = {
    "WHATSAPP_ACCESS_TOKEN": "dev_stub",
    "WHATSAPP_PHONE_NUMBER_ID": "dev_stub",
    "WHATSAPP_VERIFY_TOKEN": "dev_stub",
    "WHATSAPP_APP_SECRET": "dev_stub_secret_32byteslong______",
    "PAYMENT_WEBHOOK_SECRET": "dev_stub",
    "PAYMENT_DETAILS": "dev_stub",
    "PAYMENT_PROVIDER": "generic",
    "ADMIN_API_TOKEN": "dev_stub",
    "MANAGER_PHONE": "70000000000",
    "MANAGER_EMAIL": "dev@example.com",
    "BUSINESS_NAME": "Тестовая компания",
    "MAIN_LANGUAGE": "ru",
    "LEGAL_REGION": "RU",
    "WA_TEMPLATE_PAYMENT_REMINDER": "payment_reminder",
    "WA_TEMPLATE_BOOKING_CONFIRMED": "booking_confirmed",
    "PAYMENT_CONFIRMATION_MODE": "manual",
}
for key, val in _STUBS.items():
    os.environ.setdefault(key, val)

# ANTHROPIC_API_KEY должен быть реальным — проверяем
if not os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "").startswith("<<"):
    print(
        "\n❌  Нужен реальный ANTHROPIC_API_KEY.\n"
        "    Запусти так:\n\n"
        "    ANTHROPIC_API_KEY=sk-ant-... python scripts/dev_chat.py\n"
        "    — или добавь ANTHROPIC_API_KEY в .env\n"
    )
    sys.exit(1)

# Импортируем после установки env
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import Base, Package  # noqa: E402

# --- In-memory SQLite для тестов ---
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# Monkey-patch app.models.get_db чтобы агент использовал нашу тестовую БД
import app.models as _models  # noqa: E402

_models._engine = engine  # type: ignore[attr-defined]
_models._SessionLocal = SessionLocal  # type: ignore[attr-defined]


def _seed_packages(db) -> None:
    """Загружаем пакеты из data/packages.example.json если там нет плейсхолдеров."""
    import json
    from decimal import Decimal

    packages_file = ROOT / "data" / "packages.json"
    if not packages_file.exists():
        packages_file = ROOT / "data" / "packages.example.json"
    if not packages_file.exists():
        print("⚠️  data/packages.json не найден — пакеты не загружены.")
        return

    try:
        raw = json.loads(packages_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"⚠️  Не удалось прочитать {packages_file.name}: {exc}")
        return

    loaded = 0
    for item in raw:
        # Пропускаем строки с незаполненными плейсхолдерами
        if any("<<" in str(v) for v in item.values()):
            continue
        pkg = Package(
            id=item.get("id"),
            name=item["name"],
            description=item.get("description", ""),
            price=Decimal(str(item.get("price", 0))),
            capacity=int(item.get("capacity", 10)),
            duration_hours=float(item.get("duration_hours", 4)),
            includes=item.get("includes", []),
            active=item.get("active", True),
        )
        db.add(pkg)
        loaded += 1

    db.commit()
    if loaded:
        print(f"📦  Загружено {loaded} пакет(ов) из {packages_file.name}")
    else:
        print(
            "⚠️  Пакеты содержат плейсхолдеры — ИИ не сможет показать пакеты, но диалог работает."
        )


def _print_bookings(db) -> None:
    from app.models import Booking

    bookings = db.query(Booking).all()
    if not bookings:
        print("  (броней нет)")
        return
    for b in bookings:
        print(
            f"  #{b.booking_number} | {b.status.value} | "
            f"pkg={b.package_id} | {b.people_count}чел | "
            f"{b.travel_date} {b.travel_time} | {b.pickup_location}"
        )


def main() -> None:
    print("\n" + "=" * 60)
    print("  WhatsApp AI Bot — dev chat (без реального WhatsApp)")
    print("=" * 60)
    print("  /quit — выйти   /reset — новый диалог   /status — брони")
    print("  /phone <номер>  — сменить тестовый телефон")
    print("=" * 60 + "\n")

    db = SessionLocal()
    _seed_packages(db)

    # Импортируем агента после инициализации БД
    from app.ai_agent import process_message  # noqa: E402  (import side-effects safe now)

    test_phone = "79001234567"
    print(f"📱  Тестовый номер: +{test_phone}  (смени командой /phone <номер>)\n")

    while True:
        try:
            user_input = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nПока!")
            break

        if not user_input:
            continue

        # --- Команды ---
        if user_input.lower() in ("/quit", "/exit", "/q"):
            print("Пока!")
            break

        if user_input.lower() == "/reset":
            from app.models import Message

            db.query(Message).filter(Message.client_phone == test_phone).delete()
            db.commit()
            print("🔄  История сброшена — новый диалог.\n")
            continue

        if user_input.lower() in ("/status", "/bookings"):
            print("📋  Брони в БД:")
            _print_bookings(db)
            print()
            continue

        if user_input.lower().startswith("/phone "):
            test_phone = user_input.split(maxsplit=1)[1].strip().lstrip("+")
            print(f"📱  Телефон изменён на: +{test_phone}\n")
            continue

        # --- Агент ---
        try:
            response = process_message(session=db, phone=test_phone, text=user_input)
            print(f"\nБот: {response}\n")
        except Exception as exc:
            print(f"\n❌  Ошибка агента: {exc}\n")

    db.close()


if __name__ == "__main__":
    main()

"""
Application configuration loaded from environment variables via pydantic-settings.

At startup, all env values and prompts/system_prompt.md are scanned for
unsubstituted <<...>> patterns. In production (DEV_MODE=false) any found
pattern causes SystemExit. In DEV_MODE=true only warnings are emitted.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"<<[A-Z0-9_]+>>")

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    WHATSAPP_ACCESS_TOKEN: str = "<<WHATSAPP_ACCESS_TOKEN>>"
    WHATSAPP_PHONE_NUMBER_ID: str = "<<WHATSAPP_PHONE_NUMBER_ID>>"
    WHATSAPP_VERIFY_TOKEN: str = "<<WHATSAPP_VERIFY_TOKEN>>"
    WHATSAPP_APP_SECRET: str = "<<WHATSAPP_APP_SECRET>>"

    # ── Anthropic ─────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = "<<ANTHROPIC_API_KEY>>"
    CLAUDE_MODEL: str = "claude-opus-4-6"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./whatsapp_bot.db"

    # ── Payments ──────────────────────────────────────────────────────────────
    PAYMENT_CONFIRMATION_MODE: str = "manual"  # "auto" | "manual"
    PAYMENT_WEBHOOK_SECRET: str = "<<PAYMENT_WEBHOOK_SECRET>>"
    PAYMENT_DETAILS: str = "<<PAYMENT_DETAILS>>"
    PAYMENT_PROVIDER: str = "<<PAYMENT_PROVIDER>>"  # sbp | stripe | generic
    PREPAYMENT_PERCENT: int = 30
    PAYMENT_TIMEOUT: int = 60  # minutes

    # ── Admin ─────────────────────────────────────────────────────────────────
    ADMIN_API_TOKEN: str = "<<ADMIN_API_TOKEN>>"

    # ── Manager contacts ──────────────────────────────────────────────────────
    MANAGER_PHONE: Optional[str] = "<<MANAGER_PHONE>>"
    MANAGER_EMAIL: Optional[str] = "<<MANAGER_EMAIL>>"

    # ── Business ──────────────────────────────────────────────────────────────
    BUSINESS_NAME: str = "<<BUSINESS_NAME>>"
    MAIN_LANGUAGE: str = "ru"
    LEGAL_REGION: str = "<<LEGAL_REGION>>"

    # ── WhatsApp templates ────────────────────────────────────────────────────
    WA_TEMPLATE_PAYMENT_REMINDER: str = "<<WA_TEMPLATE_PAYMENT_REMINDER>>"
    WA_TEMPLATE_BOOKING_CONFIRMED: str = "<<WA_TEMPLATE_BOOKING_CONFIRMED>>"

    # ── Feature flags ─────────────────────────────────────────────────────────
    DEV_MODE: bool = False

    # ── Limits ────────────────────────────────────────────────────────────────
    MAX_MESSAGES_CONTEXT: int = 20
    RATE_LIMIT_PER_HOUR: int = 30

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"

    @field_validator("PAYMENT_CONFIRMATION_MODE")
    @classmethod
    def validate_payment_mode(cls, v: str) -> str:
        if v not in ("auto", "manual"):
            raise ValueError("PAYMENT_CONFIRMATION_MODE must be 'auto' or 'manual'")
        return v


def _collect_placeholders_from_settings(settings: Settings) -> list[str]:
    """Return list of field names whose values still contain <<...>>."""
    found: list[str] = []
    for field_name in settings.model_fields:
        value = getattr(settings, field_name)
        if isinstance(value, str) and PLACEHOLDER_RE.search(value):
            found.append(f"{field_name}={value!r}")
    return found


def _collect_placeholders_from_prompt() -> list[str]:
    """Scan prompts/system_prompt.md for unsubstituted placeholders."""
    prompt_file = PROMPTS_DIR / "system_prompt.md"
    if not prompt_file.exists():
        return []
    text = prompt_file.read_text(encoding="utf-8")
    matches = PLACEHOLDER_RE.findall(text)
    return [f"system_prompt.md: {m}" for m in set(matches)]


def validate_no_placeholders(settings: Settings) -> None:
    """
    Check all configured values and prompt file for <<...>> patterns.

    - In production (DEV_MODE=false): raise SystemExit if any found.
    - In DEV_MODE=true: emit warnings and continue.
    """
    issues: list[str] = []
    issues.extend(_collect_placeholders_from_settings(settings))
    issues.extend(_collect_placeholders_from_prompt())

    if not issues:
        return

    if settings.DEV_MODE:
        for issue in issues:
            logger.warning("DEV_MODE — незаполненный плейсхолдер: %s", issue)
    else:
        for issue in issues:
            # Extract placeholder name for the user-facing message
            match = PLACEHOLDER_RE.search(issue)
            placeholder = match.group(0) if match else issue
            print(
                f"Заполни {placeholder} в .env",
                file=sys.stderr,
            )
        sys.exit(
            "Остановка: обнаружены незаполненные плейсхолдеры. "
            "Заполни .env или установи DEV_MODE=true для разработки."
        )


# Singleton settings instance — imported everywhere else in the app.
settings = Settings()

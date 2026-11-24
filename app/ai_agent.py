"""
Claude AI agent with tool use.

The agent:
- Loads conversation history from the DB (last N messages)
- Sends messages to Claude claude-opus-4-6 with tools
- Processes tool_use / tool_result cycles
- Applies prompt injection protection
- Retries on API errors
- Caps tool calls per turn to prevent infinite loops
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import anthropic
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Message, MessageRole
from app.tools import TOOLS_SCHEMA, dispatch_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.md"
MAX_TOOL_CALLS_PER_TURN = 10

_anthropic_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


def _load_system_prompt() -> str:
    """Load and interpolate the system prompt from prompts/system_prompt.md."""
    if not SYSTEM_PROMPT_PATH.exists():
        logger.warning("system_prompt.md not found, using minimal fallback")
        return (
            f"Ты ассистент компании {settings.BUSINESS_NAME}. "
            "Помогаешь клиентам забронировать туры."
        )
    text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    text = text.replace("<<BUSINESS_NAME>>", settings.BUSINESS_NAME)
    text = text.replace("<<MAIN_LANGUAGE>>", settings.MAIN_LANGUAGE)
    return text


def _sanitize_user_message(text: str) -> str:
    """
    Prompt injection protection.

    Wraps the user's raw text in a tag that instructs Claude to treat it
    as opaque data, not as instructions.
    """
    return f"<user_message>\n{text}\n</user_message>"


def _load_history(session: Session, phone: str) -> list[dict]:
    """
    Load the last MAX_MESSAGES_CONTEXT messages for a phone number from the DB.

    Returns a list of Anthropic-format message dicts.
    """
    messages = (
        session.query(Message)
        .filter(Message.client_phone == phone)
        .order_by(Message.created_at.desc())
        .limit(settings.MAX_MESSAGES_CONTEXT)
        .all()
    )
    messages = list(reversed(messages))

    result: list[dict] = []
    for msg in messages:
        if msg.role == MessageRole.user:
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == MessageRole.assistant:
            result.append({"role": "assistant", "content": msg.content or ""})
        # tool messages are stored but reconstructed inline — skip raw tool rows
        # to keep history clean for the API

    return result


def _save_message(
    session: Session,
    phone: str,
    role: MessageRole,
    content: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_result: Optional[str] = None,
) -> None:
    msg = Message(
        client_phone=phone,
        role=role,
        content=content,
        tool_name=tool_name,
        tool_result=tool_result,
    )
    session.add(msg)
    session.commit()


def process_message(session: Session, phone: str, text: str) -> str:
    """
    Process an incoming WhatsApp message and return the assistant's response.

    Flow:
    1. Load conversation history
    2. Append new user message (sanitized)
    3. Call Claude in a loop, handling tool calls
    4. Save assistant response to DB
    5. Return final text response
    """
    client = _get_client()
    system_prompt = _load_system_prompt()

    # Sanitize user input against prompt injection
    safe_text = _sanitize_user_message(text)

    # Save incoming user message
    _save_message(session, phone, MessageRole.user, content=text)

    # Build history for API (re-load after save to include latest)
    history = _load_history(session, phone)
    # history already includes the new message via _save_message above
    # but let's rebuild to ensure the last message is included properly

    # We rebuild explicitly: all history minus the last user msg, then add sanitized version
    history_for_api = history[:-1] if history else []
    history_for_api.append({"role": "user", "content": safe_text})

    tool_call_count = 0
    final_response = ""

    for attempt in range(3):  # outer retry on API error
        try:
            messages_for_api = list(history_for_api)

            while True:
                if tool_call_count >= MAX_TOOL_CALLS_PER_TURN:
                    logger.warning(
                        "Max tool calls (%d) reached for phone %s",
                        MAX_TOOL_CALLS_PER_TURN,
                        phone,
                    )
                    final_response = (
                        "Извините, возникла техническая проблема. "
                        "Пожалуйста, попробуйте снова или обратитесь к менеджеру."
                    )
                    break

                response = client.messages.create(
                    model=settings.CLAUDE_MODEL,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=TOOLS_SCHEMA,
                    messages=messages_for_api,
                )

                # Check stop reason
                if response.stop_reason == "end_turn":
                    # Collect all text blocks
                    text_parts = [
                        block.text
                        for block in response.content
                        if hasattr(block, "text")
                    ]
                    final_response = "\n".join(text_parts)
                    break

                elif response.stop_reason == "tool_use":
                    # Process all tool calls in this response
                    tool_results = []
                    assistant_content = []

                    for block in response.content:
                        assistant_content.append(block)
                        if block.type == "tool_use":
                            tool_call_count += 1
                            tool_input = block.input if isinstance(block.input, dict) else {}
                            result = dispatch_tool(
                                tool_name=block.name,
                                tool_input=tool_input,
                                session=session,
                                client_phone=phone,
                            )
                            result_str = json.dumps(result, ensure_ascii=False)
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result_str,
                                }
                            )
                            # Persist tool call
                            _save_message(
                                session,
                                phone,
                                MessageRole.tool,
                                tool_name=block.name,
                                tool_result=result_str,
                            )

                    # Append assistant turn and tool results to conversation
                    messages_for_api.append(
                        {"role": "assistant", "content": assistant_content}
                    )
                    messages_for_api.append(
                        {"role": "user", "content": tool_results}
                    )

                else:
                    # Unexpected stop reason
                    logger.error("Unexpected stop_reason: %s", response.stop_reason)
                    final_response = (
                        "Произошла ошибка. Пожалуйста, повторите запрос."
                    )
                    break

            # Success — exit retry loop
            break

        except anthropic.APIConnectionError as exc:
            logger.warning("Claude API connection error (attempt %d): %s", attempt + 1, exc)
            if attempt == 2:
                final_response = (
                    "Сервис временно недоступен. Пожалуйста, попробуйте через несколько минут."
                )
        except anthropic.RateLimitError as exc:
            logger.warning("Claude API rate limit (attempt %d): %s", attempt + 1, exc)
            if attempt == 2:
                final_response = (
                    "Высокая нагрузка на сервис. Пожалуйста, повторите запрос позже."
                )
        except anthropic.APIStatusError as exc:
            logger.error("Claude API status error: %s", exc)
            final_response = (
                "Произошла ошибка при обработке запроса. Обратитесь к менеджеру."
            )
            break

    # Save assistant response
    if final_response:
        _save_message(session, phone, MessageRole.assistant, content=final_response)

    return final_response or "Не удалось получить ответ. Пожалуйста, попробуйте снова."

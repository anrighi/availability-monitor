from __future__ import annotations

import html
import logging
from typing import Any

import requests


def normalize_chat_id(raw: str) -> str:
    value = (raw or "").strip().strip('"').strip("'")
    if not value:
        return ""
    if value.startswith("@"):
        return value
    if value.startswith("-") and value[1:].isdigit():
        return value
    if not value.isdigit():
        return value
    if value.startswith("100") and len(value) >= 13:
        return f"-{value}"
    if len(value) == 10:
        return f"-100{value}"
    return value


def format_chat_id_for_api(chat_id: str) -> str | int:
    normalized = normalize_chat_id(chat_id)
    if normalized.lstrip("-").isdigit():
        return int(normalized)
    return normalized


def send_plain(
    session: requests.Session,
    *,
    token: str,
    chat_id: str,
    message: str,
    parse_mode: str | None = None,
) -> tuple[bool, str]:
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": format_chat_id_for_api(chat_id),
        "text": message,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        response = session.post(api, json=payload, timeout=20)
        if response.status_code != 200:
            return False, response.text[:500]
        body = response.json()
        if not body.get("ok"):
            return False, str(body)
    except requests.RequestException as exc:
        return False, str(exc)
    return True, "ok"


def send_html_alert(
    session: requests.Session,
    *,
    token: str,
    chat_id: str,
    title: str,
    body_html: str,
    url: str | None = None,
    dry_run: bool = False,
) -> bool:
    safe_title = html.escape(title, quote=True)
    parts = [f"<b>{safe_title}</b>", body_html]
    if url:
        safe_url = html.escape(url, quote=True)
        parts.append(f'<a href="{safe_url}">Open</a>')
    text = "\n".join(parts)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if dry_run:
        logging.info("Telegram dry-run payload: %s", payload)
        return True
    ok, err = send_plain(
        session,
        token=token,
        chat_id=chat_id,
        message=text,
        parse_mode="HTML",
    )
    if not ok:
        logging.error("Telegram failed: %s", err)
    return ok


def verify_telegram_channel(
    session: requests.Session,
    *,
    token: str,
    chat_id: str,
    channel_only: bool = False,
) -> tuple[bool, str]:
    if channel_only and not chat_id.startswith("@"):
        return False, "must start with @"
    api = f"https://api.telegram.org/bot{token}/getChat"
    try:
        response = session.get(
            api,
            params={"chat_id": format_chat_id_for_api(chat_id)},
            timeout=20,
        )
    except requests.RequestException as exc:
        return False, f"telegram: {exc}"
    try:
        body = response.json()
    except ValueError:
        return False, f"telegram: non-JSON response (HTTP {response.status_code})"
    if response.status_code != 200 or not body.get("ok"):
        description = body.get("description") if isinstance(body, dict) else None
        return False, f"telegram: {description or response.text[:300]}"
    if not channel_only:
        return True, "ok"
    result = body.get("result") or {}
    chat_type = str(result.get("type") or "")
    if chat_type != "channel":
        return False, f"not a channel (got {chat_type or 'unknown'})"
    return True, "ok"

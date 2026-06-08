from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from availability_monitor.protocol import MonitorProvider, RunReport, StorageHandle
from availability_monitor import storage, telegram


def resolve_telegram_credentials(
    settings: dict[str, str], env: dict[str, str]
) -> tuple[str | None, str | None]:
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip() or (
        settings.get("telegram_bot_token") or ""
    ).strip()
    chat = (env.get("TELEGRAM_CHAT_ID") or "").strip() or (
        settings.get("telegram_chat_id") or ""
    ).strip()
    chat = telegram.normalize_chat_id(chat) if chat else ""
    token = token or None
    chat = chat or None
    return token, chat


def get_effective_settings(
    provider: MonitorProvider,
    data_dir: Path,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    runtime_env = dict(os.environ)
    if env:
        runtime_env.update(env)
    db_file = storage.db_path_for_data_dir(data_dir)
    storage.ensure_defaults(
        db_file,
        default_settings=provider.default_settings(),
        allowed_keys=provider.all_setting_keys(),
    )
    stored = storage.get_all_settings(db_file)
    merged = provider.merge_settings_with_env(stored, runtime_env)
    return merged, runtime_env


def _maybe_send_heartbeat(
    *,
    provider: MonitorProvider,
    db_file: Path,
    cfg: Any,
    report: RunReport,
    token: str | None,
    chat: str | None,
    dry_run: bool,
    telegram_dry_run: bool,
    trust_proxy_env: bool,
) -> None:
    if dry_run or telegram_dry_run or not token or not chat:
        return
    interval_s = float(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", str(6 * 3600)))
    if interval_s <= 0:
        return
    now = time.time()
    last = storage.get_heartbeat_last_sent(db_file)
    if last is None:
        storage.set_heartbeat_last_sent(db_file, now)
        return
    if now - last < interval_s:
        return
    message = provider.build_heartbeat_message(report, cfg)
    session = requests.Session()
    session.trust_env = trust_proxy_env
    ok, err = telegram.send_plain(
        session, token=token, chat_id=chat, message=message
    )
    if ok:
        storage.set_heartbeat_last_sent(db_file, now)
        logging.info("Heartbeat Telegram sent")
        return
    logging.warning("Heartbeat Telegram failed: %s", err)


def run_stored_monitor_pass(
    provider: MonitorProvider,
    data_dir: Path,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    telegram_dry_run: bool = False,
    trust_proxy_env: bool = False,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    if dry_run:
        env["MONITOR_DRY_RUN"] = "1"
    if telegram_dry_run:
        env["TELEGRAM_DRY_RUN"] = "1"
    if trust_proxy_env:
        env["TRUST_PROXY_ENV"] = "1"
    db_file = storage.db_path_for_data_dir(data_dir)
    merged, runtime_env = get_effective_settings(provider, data_dir, env)
    handle = StorageHandle(db_file=db_file)
    cfg = provider.load_config(merged, runtime_env, storage=handle)

    exec_id = storage.start_execution(db_file)
    report = provider.run_cycle(cfg, storage=handle)
    if exec_id <= 0:
        logging.warning("Execution log insert failed; skipping finish_execution")
    summary: dict[str, Any] = {
        "provider": provider.name,
        "alerts": report.alerts,
        "error": report.error,
        **report.summary,
    }
    if exec_id > 0:
        storage.finish_execution(
            db_file,
            exec_id,
            exit_code=report.exit_code,
            summary=summary,
        )

    token, chat = resolve_telegram_credentials(merged, runtime_env)
    _maybe_send_heartbeat(
        provider=provider,
        db_file=db_file,
        cfg=cfg,
        report=report,
        token=token,
        chat=chat,
        dry_run=dry_run,
        telegram_dry_run=telegram_dry_run,
        trust_proxy_env=trust_proxy_env,
    )
    return {"exit_code": report.exit_code, "summary": summary}

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterable

SHARED_SETTING_KEYS = frozenset({"telegram_bot_token", "telegram_chat_id"})
_HEARTBEAT_KEY = "heartbeat_last_sent_unix"


def db_path_for_data_dir(data_dir: Path) -> Path:
    return data_dir / "app.db"


@contextmanager
def connect(db_file: Path) -> Generator[sqlite3.Connection, None, None]:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema(db_file: Path) -> None:
    with connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY NOT NULL,
              value TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS executions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at REAL NOT NULL,
              finished_at REAL,
              exit_code INTEGER,
              summary_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS state_items (
              item_key TEXT PRIMARY KEY NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tracked_items (
              item_key TEXT PRIMARY KEY NOT NULL
            );
            """
        )


def ensure_defaults(
    db_file: Path,
    *,
    default_settings: dict[str, str],
    allowed_keys: frozenset[str],
) -> None:
    init_schema(db_file)
    with connect(db_file) as conn:
        for key, value in default_settings.items():
            if key not in allowed_keys:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        for key in allowed_keys:
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, '')",
                (key,),
            )
        for key in SHARED_SETTING_KEYS:
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, '')",
                (key,),
            )


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        return ""
    return str(row["value"] or "")


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_all_settings(db_file: Path) -> dict[str, str]:
    init_schema(db_file)
    with connect(db_file) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {str(r["key"]): str(r["value"] or "") for r in rows}


def set_settings_batch(
    db_file: Path, updates: dict[str, str], *, allowed_keys: frozenset[str]
) -> None:
    init_schema(db_file)
    with connect(db_file) as conn:
        for key, value in updates.items():
            if key not in allowed_keys and key not in SHARED_SETTING_KEYS:
                continue
            set_setting(conn, key, value)


def list_state_items(db_file: Path) -> set[str]:
    init_schema(db_file)
    with connect(db_file) as conn:
        rows = conn.execute("SELECT item_key FROM state_items").fetchall()
    return {str(r["item_key"]) for r in rows}


def add_state_items(db_file: Path, keys: Iterable[str]) -> None:
    init_schema(db_file)
    with connect(db_file) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO state_items (item_key) VALUES (?)",
            [(k,) for k in keys],
        )


def clear_state_items(db_file: Path) -> None:
    init_schema(db_file)
    with connect(db_file) as conn:
        conn.execute("DELETE FROM state_items")


def list_tracked_items(db_file: Path) -> list[str]:
    init_schema(db_file)
    with connect(db_file) as conn:
        rows = conn.execute(
            "SELECT item_key FROM tracked_items ORDER BY item_key"
        ).fetchall()
    return [str(r["item_key"]) for r in rows]


def tracked_filter_is_active(db_file: Path) -> bool:
    return len(list_tracked_items(db_file)) > 0


def replace_tracked_items(db_file: Path, keys: Iterable[str]) -> None:
    init_schema(db_file)
    normalized = sorted({str(k).strip() for k in keys if str(k).strip()})
    with connect(db_file) as conn:
        conn.execute("DELETE FROM tracked_items")
        conn.executemany(
            "INSERT INTO tracked_items (item_key) VALUES (?)",
            [(k,) for k in normalized],
        )


def clear_tracked_items(db_file: Path) -> None:
    init_schema(db_file)
    with connect(db_file) as conn:
        conn.execute("DELETE FROM tracked_items")


def start_execution(db_file: Path) -> int:
    init_schema(db_file)
    now = time.time()
    with connect(db_file) as conn:
        cur = conn.execute(
            "INSERT INTO executions (started_at, summary_json) VALUES (?, ?)",
            (now, "{}"),
        )
        return int(cur.lastrowid or 0)


def finish_execution(
    db_file: Path,
    execution_id: int,
    *,
    exit_code: int,
    summary: dict[str, Any],
) -> None:
    init_schema(db_file)
    now = time.time()
    with connect(db_file) as conn:
        conn.execute(
            """
            UPDATE executions
            SET finished_at = ?, exit_code = ?, summary_json = ?
            WHERE id = ?
            """,
            (now, exit_code, json.dumps(summary, ensure_ascii=False), execution_id),
        )


def list_executions(db_file: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    init_schema(db_file)
    with connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT id, started_at, finished_at, exit_code, summary_json
            FROM executions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except json.JSONDecodeError:
            summary = {}
        out.append(
            {
                "id": int(row["id"]),
                "started_at": float(row["started_at"] or 0),
                "finished_at": row["finished_at"],
                "exit_code": row["exit_code"],
                "summary": summary,
            }
        )
    return out


def get_heartbeat_last_sent(db_file: Path) -> float | None:
    init_schema(db_file)
    with connect(db_file) as conn:
        raw = get_setting(conn, _HEARTBEAT_KEY).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def set_heartbeat_last_sent(db_file: Path, ts: float) -> None:
    init_schema(db_file)
    with connect(db_file) as conn:
        set_setting(conn, _HEARTBEAT_KEY, str(ts))

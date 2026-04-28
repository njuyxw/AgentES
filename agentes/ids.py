from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional


PREFIX_TABLE = {
    "run": "runs",
    "trace": "traces",
    "ev": "evidence",
    "exp": "experiences",
    "reuse": "reuse_events",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def id_date(now: Optional[datetime] = None) -> str:
    return (now or utc_now()).strftime("%Y%m%d")


def next_id(conn: sqlite3.Connection, prefix: str) -> str:
    table = PREFIX_TABLE[prefix]
    date_part = id_date()
    stem = f"{prefix}_{date_part}_"
    row = conn.execute(
        f"SELECT id FROM {table} WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{stem}%",),
    ).fetchone()
    next_number = 1
    if row:
        suffix = str(row["id"]).rsplit("_", 1)[-1]
        if suffix.isdigit():
            next_number = int(suffix) + 1
    return f"{stem}{next_number:03d}"

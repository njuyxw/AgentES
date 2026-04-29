from __future__ import annotations

import re
import sqlite3
from typing import Optional


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
NEGATIVE_STATUSES = ("failure", "partial", "warning")


def allowed_confidences(minimum: str) -> tuple[str, ...]:
    cutoff = CONFIDENCE_ORDER.get(minimum, 0)
    return tuple(name for name, rank in CONFIDENCE_ORDER.items() if rank >= cutoff)


def fts_query(query: str) -> str:
    tokens = [tok for tok in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()) if len(tok) > 1]
    return " OR ".join(tokens)


def search_experiences(
    conn: sqlite3.Connection,
    query: str,
    task_type: Optional[str] = None,
    status: Optional[str] = None,
    include_negative: bool = False,
    negative_only: bool = False,
    warning: bool = False,
    failure_mode: Optional[str] = None,
    min_confidence: str = "low",
    limit: int = 10,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[object] = []

    if task_type:
        clauses.append("e.task_type = ?")
        params.append(task_type)
    if status:
        clauses.append("e.status = ?")
        params.append(status)
    elif warning:
        clauses.append("e.status = ?")
        params.append("warning")
    elif negative_only:
        clauses.append(f"e.status IN ({','.join('?' for _ in NEGATIVE_STATUSES)})")
        params.extend(NEGATIVE_STATUSES)
    elif not include_negative:
        clauses.append("e.status NOT IN (?, ?, ?)")
        params.extend(NEGATIVE_STATUSES)
    if failure_mode:
        like = f"%{failure_mode}%"
        clauses.append(
            "(e.problem LIKE ? OR e.diagnosis LIKE ? OR e.applies_when LIKE ? OR e.avoid_when LIKE ?)"
        )
        params.extend([like, like, like, like])

    confidences = allowed_confidences(min_confidence)
    clauses.append(f"e.confidence IN ({','.join('?' for _ in confidences)})")
    params.extend(confidences)

    where = ""
    if clauses:
        where = " AND " + " AND ".join(clauses)

    reuse_counts = """
        (SELECT COUNT(*) FROM reuse_events r
         WHERE r.experience_id = e.id AND r.result = 'success') AS success_reuses,
        (SELECT COUNT(*) FROM reuse_events r
         WHERE r.experience_id = e.id) AS total_reuses
    """

    match = fts_query(query)
    if match:
        rows = conn.execute(
            f"""
            SELECT e.*, bm25(experience_fts) AS score, {reuse_counts}
            FROM experience_fts
            JOIN experiences e ON e.id = experience_fts.experience_id
            WHERE experience_fts MATCH ? {where}
            ORDER BY score, e.evidence_count DESC, e.updated_at DESC
            LIMIT ?
            """,
            [match, *params, limit],
        ).fetchall()
    else:
        base_where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            f"""
            SELECT e.*, 0.0 AS score, {reuse_counts}
            FROM experiences e
            {base_where}
            ORDER BY e.evidence_count DESC, e.updated_at DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

    return list(rows)

from __future__ import annotations

import re
import sqlite3
from typing import Optional


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def confidence_allows(value: str, minimum: str) -> bool:
    return CONFIDENCE_ORDER.get(value, 0) >= CONFIDENCE_ORDER.get(minimum, 0)


def fts_query(query: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query.lower())
    return " OR ".join(tokens)


def search_experiences(
    conn: sqlite3.Connection,
    query: str,
    task_type: Optional[str] = None,
    status: Optional[str] = None,
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

    where = ""
    if clauses:
        where = " AND " + " AND ".join(clauses)

    match = fts_query(query)
    if match:
        rows = conn.execute(
            f"""
            SELECT e.*, bm25(experience_fts) AS score
            FROM experience_fts
            JOIN experiences e ON e.id = experience_fts.experience_id
            WHERE experience_fts MATCH ? {where}
            ORDER BY score, e.evidence_count DESC, e.updated_at DESC
            LIMIT ?
            """,
            [match, *params, limit * 3],
        ).fetchall()
    else:
        base_where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            f"""
            SELECT e.*, 0.0 AS score
            FROM experiences e
            {base_where}
            ORDER BY e.evidence_count DESC, e.updated_at DESC
            LIMIT ?
            """,
            [*params, limit * 3],
        ).fetchall()

    filtered = [row for row in rows if confidence_allows(row["confidence"], min_confidence)]
    return filtered[:limit]

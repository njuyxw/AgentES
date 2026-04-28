from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from .storage import Store, flatten_text


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  task_type TEXT,
  task_summary TEXT,
  status TEXT,
  project TEXT,
  repo TEXT,
  started_at TEXT,
  finished_at TEXT,
  manifest_path TEXT
);

CREATE TABLE IF NOT EXISTS traces (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  path TEXT,
  created_at TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  type TEXT,
  claim TEXT,
  strength TEXT,
  path TEXT,
  created_at TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS experiences (
  id TEXT PRIMARY KEY,
  status TEXT,
  confidence TEXT,
  task_type TEXT,
  domain TEXT,
  project TEXT,
  repo TEXT,
  title TEXT,
  summary TEXT,
  problem TEXT,
  diagnosis TEXT,
  applies_when TEXT,
  avoid_when TEXT,
  required_checks TEXT,
  evidence_count INTEGER,
  created_at TEXT,
  updated_at TEXT,
  last_validated_at TEXT,
  manifest_path TEXT
);

CREATE TABLE IF NOT EXISTS experience_evidence (
  experience_id TEXT,
  evidence_id TEXT,
  PRIMARY KEY (experience_id, evidence_id),
  FOREIGN KEY(experience_id) REFERENCES experiences(id),
  FOREIGN KEY(evidence_id) REFERENCES evidence(id)
);

CREATE TABLE IF NOT EXISTS reuse_events (
  id TEXT PRIMARY KEY,
  experience_id TEXT,
  run_id TEXT,
  result TEXT,
  notes TEXT,
  created_at TEXT,
  FOREIGN KEY(experience_id) REFERENCES experiences(id),
  FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS experience_fts USING fts5(
  experience_id UNINDEXED,
  title,
  summary,
  problem,
  diagnosis,
  applies_when,
  avoid_when,
  required_checks
);
"""


def connect(store: Store) -> sqlite3.Connection:
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(store: Store) -> None:
    with connect(store) as conn:
        conn.executescript(SCHEMA)


def fetch_one(conn: sqlite3.Connection, query: str, params: Iterable[Any]) -> Optional[sqlite3.Row]:
    return conn.execute(query, tuple(params)).fetchone()


def evidence_exists(conn: sqlite3.Connection, evidence_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    return row is not None


def experience_row(conn: sqlite3.Connection, experience_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM experiences WHERE id = ?", (experience_id,)).fetchone()
    if row is None:
        raise KeyError(f"Experience not found: {experience_id}")
    return row


def run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"Run not found: {run_id}")
    return row


def trace_for_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM traces WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"Trace not found for run: {run_id}")
    return row


def upsert_experience(conn: sqlite3.Connection, manifest: dict[str, Any], manifest_path: str) -> None:
    task = manifest.get("task") or {}
    lifecycle = manifest.get("lifecycle") or {}
    reuse = manifest.get("reuse") or {}
    problem = manifest.get("problem") or {}
    diagnosis = manifest.get("diagnosis") or {}
    evidence_refs = [str(item) for item in ((manifest.get("evidence") or {}).get("refs") or [])]
    resolved_evidence_refs: list[str] = []
    for evidence_id in evidence_refs:
        if evidence_exists(conn, evidence_id) and evidence_id not in resolved_evidence_refs:
            resolved_evidence_refs.append(evidence_id)

    title = str(task.get("summary") or manifest.get("id"))
    summary = str(task.get("summary") or "")
    problem_text = flatten_text(problem)
    diagnosis_text = flatten_text(diagnosis)
    applies_when = "\n".join(str(item) for item in reuse.get("applies_when") or [])
    avoid_when = "\n".join(str(item) for item in reuse.get("avoid_when") or [])
    required_checks = "\n".join(str(item) for item in reuse.get("required_checks") or [])

    values = {
        "id": manifest["id"],
        "status": manifest.get("status", "success"),
        "confidence": manifest.get("confidence", "medium"),
        "task_type": task.get("type"),
        "domain": task.get("domain"),
        "project": task.get("project"),
        "repo": task.get("repo"),
        "title": title,
        "summary": summary,
        "problem": problem_text,
        "diagnosis": diagnosis_text,
        "applies_when": applies_when,
        "avoid_when": avoid_when,
        "required_checks": required_checks,
        "evidence_count": len(resolved_evidence_refs),
        "created_at": lifecycle.get("created_at"),
        "updated_at": lifecycle.get("updated_at"),
        "last_validated_at": lifecycle.get("last_validated_at"),
        "manifest_path": manifest_path,
    }
    conn.execute(
        """
        INSERT INTO experiences (
          id, status, confidence, task_type, domain, project, repo, title, summary,
          problem, diagnosis, applies_when, avoid_when, required_checks, evidence_count,
          created_at, updated_at, last_validated_at, manifest_path
        )
        VALUES (
          :id, :status, :confidence, :task_type, :domain, :project, :repo, :title, :summary,
          :problem, :diagnosis, :applies_when, :avoid_when, :required_checks, :evidence_count,
          :created_at, :updated_at, :last_validated_at, :manifest_path
        )
        ON CONFLICT(id) DO UPDATE SET
          status = excluded.status,
          confidence = excluded.confidence,
          task_type = excluded.task_type,
          domain = excluded.domain,
          project = excluded.project,
          repo = excluded.repo,
          title = excluded.title,
          summary = excluded.summary,
          problem = excluded.problem,
          diagnosis = excluded.diagnosis,
          applies_when = excluded.applies_when,
          avoid_when = excluded.avoid_when,
          required_checks = excluded.required_checks,
          evidence_count = excluded.evidence_count,
          created_at = excluded.created_at,
          updated_at = excluded.updated_at,
          last_validated_at = excluded.last_validated_at,
          manifest_path = excluded.manifest_path
        """,
        values,
    )

    conn.execute("DELETE FROM experience_fts WHERE experience_id = ?", (manifest["id"],))
    conn.execute(
        """
        INSERT INTO experience_fts (
          experience_id, title, summary, problem, diagnosis, applies_when, avoid_when, required_checks
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            manifest["id"],
            title,
            summary,
            problem_text,
            diagnosis_text,
            applies_when,
            avoid_when,
            required_checks,
        ),
    )

    conn.execute("DELETE FROM experience_evidence WHERE experience_id = ?", (manifest["id"],))
    for evidence_id in resolved_evidence_refs:
        conn.execute(
            "INSERT OR IGNORE INTO experience_evidence (experience_id, evidence_id) VALUES (?, ?)",
            (manifest["id"], evidence_id),
        )


def path_from_row(project_root: Path, row: sqlite3.Row, column: str = "manifest_path") -> Path:
    return project_root / row[column]

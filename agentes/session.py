from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from pydantic import ValidationError

from . import db
from .ids import iso_now, next_id
from .models import (
    EvidenceManifest,
    EvidenceSource,
    ExperienceManifest,
    RunContext,
    RunManifest,
    RunTask,
    TranscriptEvent,
    TraceEvent,
    TraceRef,
)
from .render import diagnosis_markdown, reuse_markdown, summary_markdown
from .search import search_experiences
from .skill import install_default_skill
from .storage import (
    Store,
    append_jsonl,
    as_list,
    copy_blob,
    ensure_dirs,
    model_to_dict,
    read_jsonl,
    read_yaml,
    safe_child,
    validate_object_id,
    write_text,
    write_yaml,
)


STATE_NAME = "codex_session.json"
PROJECT_MARKERS = [".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod"]


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate
    return current


def find_existing_store(start: Path, stop_at: Optional[Path] = None) -> Optional[Path]:
    current = start.resolve()
    stop = stop_at.resolve() if stop_at else None
    for candidate in [current, *current.parents]:
        if (candidate / ".agentes").is_dir():
            return candidate
        if stop is not None and candidate == stop:
            break
    return None


def session_root(start: Optional[Path] = None) -> Path:
    current = (start or Path.cwd()).resolve()
    project_root = find_project_root(current)
    return find_existing_store(current, stop_at=project_root) or project_root


def ensure_session_store(start: Optional[Path] = None) -> Store:
    root = session_root(start)
    store = Store(root)
    ensure_dirs(store)
    db.init_db(store)
    install_default_skill(store)
    return store


def state_path(store: Store) -> Path:
    return store.root / "tmp" / STATE_NAME


def read_state(store: Store) -> dict[str, Any]:
    path = state_path(store)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(store: Store, state: dict[str, Any]) -> None:
    path = state_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git_remote(root: Path) -> Optional[str]:
    proc = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    value = proc.stdout.strip()
    return value or None


def current_run(store: Store, explicit_run: Optional[str] = None) -> str:
    if explicit_run:
        return explicit_run
    state = read_state(store)
    if state.get("finished_at"):
        raise ValueError("The last AgentES session run is finished. Start a new one with `agentes session start`.")
    run_id = state.get("run_id")
    if not run_id:
        raise ValueError("No active AgentES session run. Start one with `agentes session start`.")
    return str(run_id)


def create_run(
    store: Store,
    task_type: str,
    summary: str,
    project: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    now = iso_now()
    with db.connect(store) as conn:
        run_id = next_id(conn, "run")
        trace_id = next_id(conn, "trace")
        run_dir = store.runs / run_id
        trace_path = store.traces / f"{trace_id}.jsonl"
        transcript_path = store.transcripts / f"{run_id}.jsonl"
        input_path = run_dir / "input.md"
        output_path = run_dir / "output.md"
        manifest_path = run_dir / "manifest.yaml"
        write_text(input_path, summary + "\n")
        write_text(output_path, "")
        write_text(trace_path, "")
        write_text(transcript_path, "")
        manifest = RunManifest(
            id=run_id,
            task=RunTask(type=task_type, summary=summary, input_path=store.rel(input_path)),
            context=RunContext(project=project, repo=repo),
            status="running",
            trace=TraceRef(id=trace_id, path=store.rel(trace_path)),
            transcript=TraceRef(id=run_id, path=store.rel(transcript_path)),
            created_at=now,
        )
        write_yaml(manifest_path, model_to_dict(manifest))
        conn.execute(
            """
            INSERT INTO runs (id, task_type, task_summary, status, project, repo, started_at, manifest_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, task_type, summary, "running", project, repo, now, store.rel(manifest_path)),
        )
        conn.execute(
            "INSERT INTO traces (id, run_id, path, created_at) VALUES (?, ?, ?, ?)",
            (trace_id, run_id, store.rel(trace_path), now),
        )
    return run_id


def finish_run(store: Store, run_id: str, status: str) -> str:
    now = iso_now()
    with db.connect(store) as conn:
        row = db.run_row(conn, run_id)
        manifest_path = store.project_root / row["manifest_path"]
        manifest = read_yaml(manifest_path)
        manifest["status"] = status
        manifest["finished_at"] = now
        write_yaml(manifest_path, manifest)
        conn.execute(
            "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
            (status, now, run_id),
        )
    return run_id


def add_trace(
    store: Store,
    run_id: str,
    type_: str,
    summary: str,
    command: Optional[str] = None,
    exit_code: Optional[int] = None,
    stdout: Optional[Path] = None,
    stderr: Optional[Path] = None,
    extra: Optional[dict[str, Any]] = None,
) -> int:
    with db.connect(store) as conn:
        trace = db.trace_for_run(conn, run_id)
        trace_path = store.project_root / trace["path"]
        step = len(read_jsonl(trace_path)) + 1
        event_id = f"{run_id}_step_{step}"
        stdout_path = copy_blob(store, stdout, "stdout", event_id, ".out")
        stderr_path = copy_blob(store, stderr, "stderr", event_id, ".err")
        event = TraceEvent(
            step=step,
            type=type_,
            summary=summary,
            timestamp=iso_now(),
            command=command,
            exit_code=exit_code,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            **(extra or {}),
        )
        append_jsonl(trace_path, model_to_dict(event))
    return step


def transcript_path(store: Store, run_id: str) -> Path:
    validate_object_id(run_id, "run id")
    return store.transcripts / f"{run_id}.jsonl"


def add_transcript_event(
    store: Store,
    run_id: str,
    type_: str,
    role: Optional[str] = None,
    content: Optional[str] = None,
    **extra: Any,
) -> int:
    with db.connect(store) as conn:
        db.run_row(conn, run_id)
    path = transcript_path(store, run_id)
    seq = len(read_jsonl(path)) + 1
    event = TranscriptEvent(
        seq=seq,
        type=type_,
        role=role,
        content=content,
        timestamp=iso_now(),
        **extra,
    )
    append_jsonl(path, model_to_dict(event))
    return seq


def add_message(store: Store, run_id: str, role: str, content: str) -> tuple[int, int]:
    if role not in {"user", "assistant", "system"}:
        raise ValueError("Invalid role. Use one of: user, assistant, system.")
    seq = add_transcript_event(store, run_id, "message", role=role, content=content)
    step = add_trace(
        store,
        run_id,
        "message",
        content,
        extra={
            "role": role,
            "content": content,
            "visibility": "visible",
            "transcript_seq": seq,
        },
    )
    return seq, step


def add_observation(store: Store, run_id: str, content: str) -> int:
    return add_trace(
        store,
        run_id,
        "observation",
        content,
        extra={
            "content": content,
            "visibility": "visible",
            "sensitivity": "normal",
        },
    )


def parse_rejected_alternatives(values: Optional[List[str]]) -> list[dict[str, str]]:
    rejected: list[dict[str, str]] = []
    for value in values or []:
        item = value.strip()
        if not item:
            continue
        if "::" in item:
            alternative, reason = item.split("::", 1)
            rejected.append({"alternative": alternative.strip(), "reason": reason.strip()})
        else:
            rejected.append({"alternative": item})
    return rejected


def reasoning_summary_text(
    summary: Optional[str],
    observations: List[str],
    hypotheses: List[str],
    decisions: List[str],
    diagnosis: Optional[str],
) -> str:
    if summary:
        return summary
    parts: list[str] = []
    if observations:
        parts.append(f"Observation: {observations[0]}")
    if hypotheses:
        parts.append(f"Hypothesis: {hypotheses[0]}")
    if decisions:
        parts.append(f"Decision: {decisions[0]}")
    if diagnosis:
        parts.append(f"Diagnosis: {diagnosis}")
    return " ".join(parts) or "Reasoning summary"


def add_reasoning_summary(
    store: Store,
    run_id: str,
    summary: Optional[str] = None,
    observations: Optional[List[str]] = None,
    hypotheses: Optional[List[str]] = None,
    decisions: Optional[List[str]] = None,
    rejected_alternatives: Optional[List[str]] = None,
    diagnosis: Optional[str] = None,
    linked_evidence: Optional[List[str]] = None,
) -> int:
    observations = [item.strip() for item in observations or [] if item.strip()]
    hypotheses = [item.strip() for item in hypotheses or [] if item.strip()]
    decisions = [item.strip() for item in decisions or [] if item.strip()]
    rejected = parse_rejected_alternatives(rejected_alternatives)
    linked = [item.strip() for item in linked_evidence or [] if item.strip()]
    if not any([summary, observations, hypotheses, decisions, rejected, diagnosis]):
        raise ValueError("At least one reasoning field is required.")
    with db.connect(store) as conn:
        db.run_row(conn, run_id)
        for evidence_id in linked:
            validate_object_id(evidence_id, "evidence id")
        missing = [evidence_id for evidence_id in linked if not db.evidence_exists(conn, evidence_id)]
    if missing:
        raise ValueError(f"Missing evidence refs: {', '.join(missing)}")
    return add_trace(
        store,
        run_id,
        "reasoning_summary",
        reasoning_summary_text(summary, observations, hypotheses, decisions, diagnosis),
        extra={
            "visibility": "visible",
            "sensitivity": "summary",
            "content": summary,
            "observations": observations,
            "hypotheses": hypotheses,
            "decisions": decisions,
            "rejected_alternatives": rejected,
            "diagnosis": diagnosis,
            "linked_evidence": linked,
        },
    )


def create_evidence(
    store: Store,
    run_id: str,
    type_: str,
    claim: str,
    strength: str = "medium",
    command: Optional[str] = None,
    exit_code: Optional[int] = None,
    trace_step: Optional[int] = None,
) -> str:
    with db.connect(store) as conn:
        db.run_row(conn, run_id)
        evidence_id = next_id(conn, "ev")
        manifest = EvidenceManifest(
            id=evidence_id,
            type=type_,
            claim=claim,
            strength=strength,
            source=EvidenceSource(run=run_id, trace_step=trace_step),
            data={
                "command": command,
                "exit_code": exit_code,
            },
            created_at=iso_now(),
        )
        manifest_path = store.evidence / f"{evidence_id}.yaml"
        write_yaml(manifest_path, model_to_dict(manifest))
        conn.execute(
            """
            INSERT INTO evidence (id, run_id, type, claim, strength, path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (evidence_id, run_id, type_, claim, strength, store.rel(manifest_path), manifest.created_at),
        )
    state = read_state(store)
    state.setdefault("evidence", []).append(evidence_id)
    write_state(store, state)
    return evidence_id


def import_experience_data(store: Store, raw: dict[str, Any]) -> str:
    with db.connect(store) as conn:
        if not raw.get("id"):
            raw["id"] = next_id(conn, "exp")
        now = iso_now()
        raw.setdefault("lifecycle", {})
        raw["lifecycle"].setdefault("created_at", now)
        raw["lifecycle"]["updated_at"] = now
        manifest = ExperienceManifest(**raw)
        data = model_to_dict(manifest)
        validate_object_id(data["id"], "experience id")
        evidence_block = data.setdefault("evidence", {})
        refs = as_list(evidence_block.get("refs"))
        normalized_refs: List[str] = []
        for ref in refs:
            validate_object_id(ref, "evidence ref")
            if ref not in normalized_refs:
                normalized_refs.append(ref)
        missing_refs = [ref for ref in normalized_refs if not db.evidence_exists(conn, ref)]
        if missing_refs:
            raise ValueError(f"Missing evidence refs: {', '.join(missing_refs)}")
        evidence_block["refs"] = normalized_refs
        exp_dir = safe_child(store.experiences, data["id"], "experience id")
        manifest_path = exp_dir / "manifest.yaml"
        write_yaml(manifest_path, data)
        write_text(exp_dir / "summary.md", summary_markdown(data))
        write_text(exp_dir / "reuse.md", reuse_markdown(data))
        write_text(exp_dir / "diagnosis.md", diagnosis_markdown(data))
        db.upsert_experience(conn, data, store.rel(manifest_path))
    return data["id"]


def repeatable(values: Optional[List[str]], fallback: str) -> List[str]:
    cleaned = [item.strip() for item in (values or []) if item.strip()]
    return cleaned or [fallback]


def start_session(
    summary: str,
    task_type: str,
    project: Optional[str] = None,
    repo: Optional[str] = None,
) -> tuple[Store, str]:
    store = ensure_session_store()
    project_name = project or store.project_root.name
    repo_name = repo or git_remote(store.project_root) or store.project_root.name
    run_id = create_run(store, task_type, summary, project_name, repo_name)
    write_state(
        store,
        {
            "run_id": run_id,
            "summary": summary,
            "task_type": task_type,
            "project": project_name,
            "repo": repo_name,
            "started_at": iso_now(),
            "status": "running",
        },
    )
    return store, run_id


def search_session(
    query: str,
    task_type: Optional[str] = None,
    status: Optional[str] = None,
    include_negative: bool = False,
    negative_only: bool = False,
    warning: bool = False,
    failure_mode: Optional[str] = None,
    min_confidence: str = "low",
    limit: int = 10,
) -> str:
    store = ensure_session_store()
    with db.connect(store) as conn:
        rows = search_experiences(
            conn,
            query=query,
            task_type=task_type,
            status=status,
            include_negative=include_negative,
            negative_only=negative_only,
            warning=warning,
            failure_mode=failure_mode,
            min_confidence=min_confidence,
            limit=limit,
        )
    from .render import search_cards

    return search_cards(rows)


def capture_session(
    title: str,
    task_type: str,
    domain: str,
    actions: str,
    outcome: str,
    diagnosis: str,
    applies_when: List[str],
    required_check: List[str],
    validation_after_reuse: List[str],
    project: Optional[str] = None,
    repo: Optional[str] = None,
    problem: Optional[List[str]] = None,
    observation: Optional[List[str]] = None,
    hypothesis: Optional[List[str]] = None,
    verified_fact: Optional[List[str]] = None,
    avoid_when: Optional[List[str]] = None,
    command: Optional[List[str]] = None,
    residual_issue: Optional[List[str]] = None,
    evidence: Optional[str] = None,
    evidence_claim: Optional[str] = None,
    evidence_strength: str = "medium",
    evidence_type: str = "session_result",
    status: str = "success",
    confidence: str = "medium",
    run: Optional[str] = None,
) -> tuple[str, str, str]:
    store = ensure_session_store()
    state = read_state(store)
    if not run and (not state.get("run_id") or state.get("finished_at")):
        _, started_run = start_session(title, task_type, project=project, repo=repo)
        run_id = started_run
        state = read_state(store)
    else:
        run_id = current_run(store, run)

    evidence_id = evidence or create_evidence(
        store,
        run_id,
        evidence_type,
        evidence_claim or f"Codex session outcome: {outcome}",
        evidence_strength,
    )
    manifest = {
        "schema_version": 1,
        "object_type": "experience",
        "status": status,
        "confidence": confidence,
        "task": {
            "type": task_type,
            "domain": domain,
            "project": project or state.get("project") or store.project_root.name,
            "repo": repo or state.get("repo") or store.project_root.name,
            "summary": title,
        },
        "problem": {
            "symptoms": repeatable(problem, title),
        },
        "actions": {
            "summary": actions,
            "commands": command or [],
        },
        "outcome": {
            "result": status,
            "validation": [evidence_id],
            "residual_issues": residual_issue or [],
        },
        "diagnosis": {
            "observations": repeatable(observation, problem[0] if problem else title),
            "hypotheses": hypothesis or [],
            "verified_facts": repeatable(verified_fact, outcome),
            "root_cause": diagnosis,
        },
        "reuse": {
            "applies_when": repeatable(applies_when, "A future task has the same symptoms and constraints"),
            "avoid_when": avoid_when or [],
            "required_checks": repeatable(required_check, "Confirm the current context matches the reuse boundary"),
            "validation_after_reuse": repeatable(validation_after_reuse, "Run the relevant local validation"),
        },
        "evidence": {"refs": [evidence_id]},
        "provenance": {"source_run": run_id, "created_by": "codex"},
        "lifecycle": {"created_at": iso_now(), "updated_at": iso_now()},
    }
    tmp = store.root / "tmp" / f"codex_experience_{run_id}.yaml"
    write_yaml(tmp, manifest)
    try:
        experience_id = import_experience_data(store, manifest)
    except (ValidationError, ValueError):
        raise
    finish_run(store, run_id, status)
    state = read_state(store)
    state["last_experience_id"] = experience_id
    state["last_evidence_id"] = evidence_id
    state["finished_at"] = iso_now()
    state["status"] = status
    write_state(store, state)
    return experience_id, evidence_id, run_id

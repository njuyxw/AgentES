from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional

import typer
import yaml
from pydantic import ValidationError

from . import db
from .ids import iso_now, next_id
from .models import (
    CurrentContext,
    EvidenceManifest,
    EvidenceSource,
    RunContext,
    RunManifest,
    RunTask,
    TraceEvent,
    TraceRef,
)
from .render import (
    evidence_view,
    search_cards,
    validation_report,
)
from .search import search_experiences
from . import session as session_ops
from .skill import (
    DEFAULT_SKILL_NAME,
    SKILL_TARGETS,
    install_default_skill,
    install_external_skill,
)
from .storage import (
    StoreNotFound,
    append_jsonl,
    as_list,
    copy_blob,
    ensure_dirs,
    find_store,
    model_to_dict,
    read_jsonl,
    read_text,
    read_yaml,
    store_for_init,
    validate_object_id,
    write_text,
    write_yaml,
)
from .validate import checklist_for, validate_use


app = typer.Typer(no_args_is_help=True, help="Agent Experience Store CLI.")
run_app = typer.Typer(no_args_is_help=True, help="Record agent runs.")
trace_app = typer.Typer(no_args_is_help=True, help="Append trace events.")
evidence_app = typer.Typer(no_args_is_help=True, help="Create evidence manifests.")
experience_app = typer.Typer(no_args_is_help=True, help="Import, search, open, and validate experiences.")
reuse_app = typer.Typer(no_args_is_help=True, help="Record experience reuse outcomes.")
skill_app = typer.Typer(no_args_is_help=True, help="Open installed AgentES skills.")
session_app = typer.Typer(no_args_is_help=True, help="Manage Codex-style AgentES sessions.")


def get_store_or_exit():
    try:
        return find_store()
    except StoreNotFound as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)


def load_experience_manifest(conn: sqlite3.Connection, experience_id: str) -> dict:
    try:
        validate_object_id(experience_id, "experience id")
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    try:
        row = db.experience_row(conn, experience_id)
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    store = find_store()
    return read_yaml(store.project_root / row["manifest_path"])


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Reinstall schema and default skill if the store exists."),
) -> None:
    """Create a project-local .agentes store."""
    store = store_for_init()
    already_exists = store.root.exists()
    ensure_dirs(store)
    db.init_db(store)
    install_default_skill(store, force=force)
    if already_exists and not force:
        typer.echo(f"AgentES store already exists: {store.rel(store.root)}")
        return
    typer.echo(f"Initialized AgentES store: {store.rel(store.root)}")


@run_app.command("start")
def run_start(
    task_type: str = typer.Option(..., "--task-type"),
    summary: str = typer.Option(..., "--summary"),
    project: Optional[str] = typer.Option(None, "--project"),
    repo: Optional[str] = typer.Option(None, "--repo"),
) -> None:
    """Start a run and print its run id."""
    store = get_store_or_exit()
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
    typer.echo(run_id)


RUN_STATUS_CHOICES = {"success", "failure", "partial"}


@run_app.command("finish")
def run_finish(
    run_id: str,
    status: str = typer.Option(..., "--status"),
) -> None:
    """Finish a run."""
    if status not in RUN_STATUS_CHOICES:
        typer.echo(
            f"Invalid status. Use one of: {', '.join(sorted(RUN_STATUS_CHOICES))}.",
            err=True,
        )
        raise typer.Exit(code=1)
    store = get_store_or_exit()
    now = iso_now()
    with db.connect(store) as conn:
        try:
            row = db.run_row(conn, run_id)
        except KeyError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1)
        manifest_path = store.project_root / row["manifest_path"]
        manifest = read_yaml(manifest_path)
        manifest["status"] = status
        manifest["finished_at"] = now
        write_yaml(manifest_path, manifest)
        conn.execute(
            "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
            (status, now, run_id),
        )
    typer.echo(run_id)


@trace_app.command("add")
def trace_add(
    run_id: str,
    type_: str = typer.Option(..., "--type"),
    summary: str = typer.Option(..., "--summary"),
    command: Optional[str] = typer.Option(None, "--command"),
    exit_code: Optional[int] = typer.Option(None, "--exit-code"),
    stdout: Optional[Path] = typer.Option(None, "--stdout", exists=True, dir_okay=False),
    stderr: Optional[Path] = typer.Option(None, "--stderr", exists=True, dir_okay=False),
) -> None:
    """Append one event to a run trace."""
    store = get_store_or_exit()
    with db.connect(store) as conn:
        try:
            trace = db.trace_for_run(conn, run_id)
        except KeyError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1)
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
        )
        append_jsonl(trace_path, model_to_dict(event))
    typer.echo(f"trace_step={step}")


@evidence_app.command("create")
def evidence_create(
    run_id: str,
    type_: str = typer.Option(..., "--type"),
    claim: str = typer.Option(..., "--claim"),
    strength: str = typer.Option("medium", "--strength"),
    command: Optional[str] = typer.Option(None, "--command"),
    exit_code: Optional[int] = typer.Option(None, "--exit-code"),
    stdout: Optional[Path] = typer.Option(None, "--stdout", exists=True, dir_okay=False),
    stderr: Optional[Path] = typer.Option(None, "--stderr", exists=True, dir_okay=False),
    trace_step: Optional[int] = typer.Option(None, "--trace-step"),
) -> None:
    """Create evidence for a run and print its evidence id."""
    store = get_store_or_exit()
    try:
        with db.connect(store) as conn:
            try:
                db.run_row(conn, run_id)
            except KeyError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=1)
            evidence_id = next_id(conn, "ev")
            stdout_path = copy_blob(store, stdout, "stdout", evidence_id, ".out")
            stderr_path = copy_blob(store, stderr, "stderr", evidence_id, ".err")
            manifest = EvidenceManifest(
                id=evidence_id,
                type=type_,
                claim=claim,
                strength=strength,
                source=EvidenceSource(run=run_id, trace_step=trace_step),
                data={
                    "command": command,
                    "exit_code": exit_code,
                    "stdout_path": stdout_path,
                    "stderr_path": stderr_path,
                },
                created_at=iso_now(),
            )
            manifest_path = store.evidence / f"{evidence_id}.yaml"
            conn.execute(
                """
                INSERT INTO evidence (id, run_id, type, claim, strength, path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (evidence_id, run_id, type_, claim, strength, store.rel(manifest_path), manifest.created_at),
            )
            write_yaml(manifest_path, model_to_dict(manifest))
    except ValidationError as exc:
        typer.echo(f"Invalid evidence: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(evidence_id)


@experience_app.command("import")
def experience_import(path: Path) -> None:
    """Import an experience YAML into the store and index it."""
    store = get_store_or_exit()
    try:
        raw = read_yaml(path)
        data = session_ops.import_experience_data(store, raw)
    except (ValidationError, ValueError, OSError) as exc:
        typer.echo(f"Import failed: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(data)


@experience_app.command("search")
def experience_search(
    query: str = typer.Option("", "--query"),
    task_type: Optional[str] = typer.Option(None, "--task-type"),
    status: Optional[str] = typer.Option(None, "--status"),
    include_negative: bool = typer.Option(False, "--include-negative", help="Include failure, partial, and warning experiences."),
    negative_only: bool = typer.Option(False, "--negative-only", help="Search only failure, partial, and warning experiences."),
    warning: bool = typer.Option(False, "--warning", help="Search warning experiences only."),
    failure_mode: Optional[str] = typer.Option(None, "--failure-mode", help="Filter by failure mode text in problem/diagnosis/reuse fields."),
    min_confidence: str = typer.Option("low", "--min-confidence"),
    limit: int = typer.Option(10, "--limit", min=1, max=50),
) -> None:
    """Search indexed experiences."""
    if sum(1 for item in [bool(status), negative_only, warning] if item) > 1:
        typer.echo("Choose only one of --status, --negative-only, or --warning.", err=True)
        raise typer.Exit(code=1)
    store = get_store_or_exit()
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
    typer.echo(search_cards(rows), nl=False)


@experience_app.command("open")
def experience_open(
    experience_id: str,
    summary: bool = typer.Option(False, "--summary"),
    reuse: bool = typer.Option(False, "--reuse"),
    evidence: bool = typer.Option(False, "--evidence"),
    full: bool = typer.Option(False, "--full"),
) -> None:
    """Open a readable view of an experience."""
    store = get_store_or_exit()
    with db.connect(store) as conn:
        manifest = load_experience_manifest(conn, experience_id)
    exp_dir = store.experiences / experience_id
    selected = [summary, reuse, evidence, full]
    if sum(1 for item in selected if item) == 0:
        summary = True
    if sum(1 for item in selected if item) > 1:
        typer.echo("Choose only one of --summary, --reuse, --evidence, or --full.", err=True)
        raise typer.Exit(code=1)
    if summary:
        typer.echo(read_text(exp_dir / "summary.md"), nl=False)
    elif reuse:
        typer.echo(read_text(exp_dir / "reuse.md"), nl=False)
    elif evidence:
        refs = as_list((manifest.get("evidence") or {}).get("refs"))
        manifests = {}
        for ref in refs:
            try:
                validate_object_id(ref, "evidence ref")
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=1)
            path = store.evidence / f"{ref}.yaml"
            if path.exists():
                manifests[ref] = read_yaml(path)
        typer.echo(evidence_view(refs, manifests), nl=False)
    else:
        typer.echo(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), nl=False)


@experience_app.command("validate-use")
def experience_validate_use(
    experience_id: str,
    context: Path = typer.Option(..., "--context", exists=True, dir_okay=False),
) -> None:
    """Check whether an experience is applicable to the current context."""
    store = get_store_or_exit()
    with db.connect(store) as conn:
        manifest = load_experience_manifest(conn, experience_id)
    try:
        current_context = CurrentContext(**read_yaml(context))
    except ValidationError as exc:
        typer.echo(f"Invalid context: {exc}", err=True)
        raise typer.Exit(code=1)
    result = validate_use(manifest, model_to_dict(current_context))
    typer.echo(validation_report(result), nl=False)


@experience_app.command("adapt")
def experience_adapt(
    experience_id: str,
    context: Path = typer.Option(..., "--context", exists=True, dir_okay=False),
) -> None:
    """Convert an experience into a local checklist."""
    store = get_store_or_exit()
    with db.connect(store) as conn:
        manifest = load_experience_manifest(conn, experience_id)
    try:
        current_context = CurrentContext(**read_yaml(context))
    except ValidationError as exc:
        typer.echo(f"Invalid context: {exc}", err=True)
        raise typer.Exit(code=1)
    validation = validate_use(manifest, model_to_dict(current_context))
    typer.echo(checklist_for(manifest, validation), nl=False)


@reuse_app.command("record")
def reuse_record(
    experience: str = typer.Option(..., "--experience"),
    run: Optional[str] = typer.Option(None, "--run"),
    result: str = typer.Option(..., "--result"),
    notes: str = typer.Option("", "--notes"),
) -> None:
    """Record a reuse outcome."""
    if result not in {"success", "failure", "partial"}:
        typer.echo("Invalid result. Use one of: success, failure, partial.", err=True)
        raise typer.Exit(code=1)
    store = get_store_or_exit()
    now = iso_now()
    with db.connect(store) as conn:
        try:
            row = db.experience_row(conn, experience)
            if run:
                db.run_row(conn, run)
        except KeyError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1)
        reuse_id = next_id(conn, "reuse")
        conn.execute(
            """
            INSERT INTO reuse_events (id, experience_id, run_id, result, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (reuse_id, experience, run, result, notes, now),
        )
        if result == "success":
            conn.execute(
                "UPDATE experiences SET last_validated_at = ?, updated_at = ? WHERE id = ?",
                (now, now, experience),
            )
            manifest_path = store.project_root / row["manifest_path"]
            manifest = read_yaml(manifest_path)
            manifest.setdefault("lifecycle", {})
            manifest["lifecycle"]["last_validated_at"] = now
            manifest["lifecycle"]["updated_at"] = now
            write_yaml(manifest_path, manifest)
    typer.echo(reuse_id)


@skill_app.command("open")
def skill_open(name: str = DEFAULT_SKILL_NAME) -> None:
    """Print an installed skill."""
    store = get_store_or_exit()
    skill_id = name[:-3] if name.endswith(".md") else name
    try:
        validate_object_id(skill_id, "skill name")
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    path = store.skills / f"{skill_id}.md"
    if not path.exists():
        typer.echo(f"Skill not found: {name}", err=True)
        raise typer.Exit(code=1)
    typer.echo(read_text(path), nl=False)


@skill_app.command("install")
def skill_install(
    target: str = typer.Option(
        "claude-code",
        "--target",
        help=f"Skill target. Choices: {', '.join(sorted(SKILL_TARGETS))}.",
    ),
    dir_: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Override the skills directory. Defaults to the target's standard location.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing SKILL.md."),
) -> None:
    """Install the AgentES skill into a Claude Code or Codex skills directory."""
    if target not in SKILL_TARGETS:
        typer.echo(
            f"Unknown target {target!r}. Choose one of: {', '.join(sorted(SKILL_TARGETS))}.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        skill_path = install_external_skill(target, dir_override=dir_, force=force)
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    except (ValueError, OSError) as exc:
        typer.echo(f"Skill install failed: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(str(skill_path))


def handle_session_error(exc: Exception) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1)


def resolve_content(content: Optional[str], content_file: Optional[Path], label: str) -> str:
    if content and content_file:
        typer.echo(f"Use only one of --{label} or --{label}-file.", err=True)
        raise typer.Exit(code=1)
    if content_file:
        return read_text(content_file)
    if content:
        return content
    typer.echo(f"Either --{label} or --{label}-file is required.", err=True)
    raise typer.Exit(code=1)


@session_app.command("start")
def session_start(
    summary: str = typer.Option(..., "--summary"),
    task_type: str = typer.Option("coding_session", "--task-type"),
    project: Optional[str] = typer.Option(None, "--project"),
    repo: Optional[str] = typer.Option(None, "--repo"),
    force: bool = typer.Option(False, "--force", help="Replace an active run instead of refusing."),
) -> None:
    """Start a project-local AgentES session run."""
    try:
        _, run_id = session_ops.start_session(
            summary, task_type, project=project, repo=repo, force=force
        )
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(run_id)


@session_app.command("search")
def session_search(
    query: str = typer.Option(..., "--query"),
    task_type: Optional[str] = typer.Option(None, "--task-type"),
    status: Optional[str] = typer.Option(None, "--status"),
    include_negative: bool = typer.Option(False, "--include-negative", help="Include failure, partial, and warning experiences."),
    negative_only: bool = typer.Option(False, "--negative-only", help="Search only failure, partial, and warning experiences."),
    warning: bool = typer.Option(False, "--warning", help="Search warning experiences only."),
    failure_mode: Optional[str] = typer.Option(None, "--failure-mode", help="Filter by failure mode text in problem/diagnosis/reuse fields."),
    min_confidence: str = typer.Option("low", "--min-confidence"),
    limit: int = typer.Option(10, "--limit", min=1, max=50),
) -> None:
    """Search experiences from the current session store."""
    if sum(1 for item in [bool(status), negative_only, warning] if item) > 1:
        typer.echo("Choose only one of --status, --negative-only, or --warning.", err=True)
        raise typer.Exit(code=1)
    try:
        output = session_ops.search_session(
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
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(output, nl=False)


@session_app.command("trace")
def session_trace(
    summary: str = typer.Option(..., "--summary"),
    type_: str = typer.Option("note", "--type"),
    command: Optional[str] = typer.Option(None, "--command"),
    exit_code: Optional[int] = typer.Option(None, "--exit-code"),
    stdout: Optional[Path] = typer.Option(None, "--stdout", exists=True, dir_okay=False),
    stderr: Optional[Path] = typer.Option(None, "--stderr", exists=True, dir_okay=False),
    run: Optional[str] = typer.Option(None, "--run"),
) -> None:
    """Add a trace event to the active session run."""
    try:
        store = session_ops.ensure_session_store()
        run_id = session_ops.current_run(store, run)
        step = session_ops.add_trace(
            store,
            run_id,
            type_=type_,
            summary=summary,
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(f"trace_step={step}")


@session_app.command("message")
def session_message(
    role: str = typer.Option(..., "--role", help="Visible message role: user, assistant, or system."),
    content: Optional[str] = typer.Option(None, "--content", help="Visible message content to store in the session transcript."),
    content_file: Optional[Path] = typer.Option(None, "--content-file", exists=True, dir_okay=False),
    run: Optional[str] = typer.Option(None, "--run"),
) -> None:
    """Append a visible message to the session transcript and trace."""
    resolved_content = resolve_content(content, content_file, "content")
    try:
        store = session_ops.ensure_session_store()
        run_id = session_ops.current_run(store, run)
        seq, step = session_ops.add_message(store, run_id, role=role, content=resolved_content)
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(f"transcript_seq={seq}")
    typer.echo(f"trace_step={step}")


@session_app.command("observe")
def session_observe(
    content: Optional[str] = typer.Option(None, "--content", help="Visible observation to store as a trace event."),
    content_file: Optional[Path] = typer.Option(None, "--content-file", exists=True, dir_okay=False),
    run: Optional[str] = typer.Option(None, "--run"),
) -> None:
    """Append a structured observation to the active session trace."""
    resolved_content = resolve_content(content, content_file, "content")
    try:
        store = session_ops.ensure_session_store()
        run_id = session_ops.current_run(store, run)
        step = session_ops.add_observation(store, run_id, resolved_content)
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(f"trace_step={step}")


@session_app.command("reason")
def session_reason(
    summary: Optional[str] = typer.Option(None, "--summary", help="Optional compact reasoning summary."),
    observation: Optional[List[str]] = typer.Option(None, "--observation", help="Repeatable visible observation."),
    hypothesis: Optional[List[str]] = typer.Option(None, "--hypothesis", help="Repeatable explicit hypothesis."),
    decision: Optional[List[str]] = typer.Option(None, "--decision", help="Repeatable decision made from visible context."),
    rejected_alternative: Optional[List[str]] = typer.Option(
        None,
        "--rejected-alternative",
        help="Repeatable rejected alternative. Use 'alternative :: reason' for structured storage.",
    ),
    diagnosis: Optional[str] = typer.Option(None, "--diagnosis"),
    linked_evidence: Optional[List[str]] = typer.Option(None, "--linked-evidence", help="Repeatable evidence id."),
    run: Optional[str] = typer.Option(None, "--run"),
) -> None:
    """Append a structured reasoning summary without storing hidden chain-of-thought."""
    try:
        store = session_ops.ensure_session_store()
        run_id = session_ops.current_run(store, run)
        step = session_ops.add_reasoning_summary(
            store,
            run_id,
            summary=summary,
            observations=observation,
            hypotheses=hypothesis,
            decisions=decision,
            rejected_alternatives=rejected_alternative,
            diagnosis=diagnosis,
            linked_evidence=linked_evidence,
        )
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(f"trace_step={step}")


@session_app.command("evidence")
def session_evidence(
    claim: str = typer.Option(..., "--claim"),
    strength: str = typer.Option("medium", "--strength"),
    type_: str = typer.Option("session_result", "--type"),
    command: Optional[str] = typer.Option(None, "--command"),
    exit_code: Optional[int] = typer.Option(None, "--exit-code"),
    trace_step: Optional[int] = typer.Option(None, "--trace-step"),
    run: Optional[str] = typer.Option(None, "--run"),
) -> None:
    """Create evidence for the active session run."""
    try:
        store = session_ops.ensure_session_store()
        run_id = session_ops.current_run(store, run)
        evidence_id = session_ops.create_evidence(
            store,
            run_id,
            type_=type_,
            claim=claim,
            strength=strength,
            command=command,
            exit_code=exit_code,
            trace_step=trace_step,
        )
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(evidence_id)


@session_app.command("capture")
def session_capture(
    title: str = typer.Option(..., "--title"),
    task_type: str = typer.Option("coding_session", "--task-type"),
    domain: str = typer.Option("software", "--domain"),
    actions: str = typer.Option(..., "--actions"),
    outcome: str = typer.Option(..., "--outcome"),
    diagnosis: str = typer.Option(..., "--diagnosis"),
    applies_when: Optional[List[str]] = typer.Option(None, "--applies-when"),
    required_check: Optional[List[str]] = typer.Option(None, "--required-check"),
    validation_after_reuse: Optional[List[str]] = typer.Option(None, "--validation-after-reuse"),
    project: Optional[str] = typer.Option(None, "--project"),
    repo: Optional[str] = typer.Option(None, "--repo"),
    problem: Optional[List[str]] = typer.Option(None, "--problem"),
    observation: Optional[List[str]] = typer.Option(None, "--observation"),
    hypothesis: Optional[List[str]] = typer.Option(None, "--hypothesis"),
    verified_fact: Optional[List[str]] = typer.Option(None, "--verified-fact"),
    avoid_when: Optional[List[str]] = typer.Option(None, "--avoid-when"),
    command: Optional[List[str]] = typer.Option(None, "--command"),
    residual_issue: Optional[List[str]] = typer.Option(None, "--residual-issue"),
    evidence: Optional[str] = typer.Option(None, "--evidence"),
    evidence_claim: Optional[str] = typer.Option(None, "--evidence-claim"),
    evidence_strength: str = typer.Option("medium", "--evidence-strength"),
    evidence_type: str = typer.Option("session_result", "--evidence-type"),
    status: str = typer.Option("success", "--status"),
    confidence: str = typer.Option("medium", "--confidence"),
    run: Optional[str] = typer.Option(None, "--run"),
) -> None:
    """Capture a reusable session lesson as an evidence-backed experience."""
    if status not in {"success", "failure", "partial"}:
        typer.echo("Invalid status. Use one of: success, failure, partial.", err=True)
        raise typer.Exit(code=1)
    if confidence not in {"low", "medium", "high"}:
        typer.echo("Invalid confidence. Use one of: low, medium, high.", err=True)
        raise typer.Exit(code=1)
    if not applies_when:
        typer.echo("At least one --applies-when is required.", err=True)
        raise typer.Exit(code=1)
    if not required_check:
        typer.echo("At least one --required-check is required.", err=True)
        raise typer.Exit(code=1)
    if not validation_after_reuse:
        typer.echo("At least one --validation-after-reuse is required.", err=True)
        raise typer.Exit(code=1)
    try:
        experience_id, evidence_id, run_id = session_ops.capture_session(
            title=title,
            task_type=task_type,
            domain=domain,
            actions=actions,
            outcome=outcome,
            diagnosis=diagnosis,
            applies_when=applies_when,
            required_check=required_check,
            validation_after_reuse=validation_after_reuse,
            project=project,
            repo=repo,
            problem=problem,
            observation=observation,
            hypothesis=hypothesis,
            verified_fact=verified_fact,
            avoid_when=avoid_when,
            command=command,
            residual_issue=residual_issue,
            evidence=evidence,
            evidence_claim=evidence_claim,
            evidence_strength=evidence_strength,
            evidence_type=evidence_type,
            status=status,
            confidence=confidence,
            run=run,
        )
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(f"experience={experience_id}")
    typer.echo(f"evidence={evidence_id}")
    typer.echo(f"run={run_id}")


@session_app.command("finish")
def session_finish(
    status: str = typer.Option("success", "--status"),
    run: Optional[str] = typer.Option(None, "--run"),
) -> None:
    """Finish the active session run."""
    if status not in {"success", "failure", "partial"}:
        typer.echo("Invalid status. Use one of: success, failure, partial.", err=True)
        raise typer.Exit(code=1)
    try:
        store = session_ops.ensure_session_store()
        run_id = session_ops.current_run(store, run)
        session_ops.finish_run(store, run_id, status)
        state = session_ops.read_state(store)
        state["finished_at"] = iso_now()
        state["status"] = status
        session_ops.write_state(store, state)
    except Exception as exc:
        handle_session_error(exc)
    typer.echo(run_id)


app.add_typer(run_app, name="run")
app.add_typer(trace_app, name="trace")
app.add_typer(evidence_app, name="evidence")
app.add_typer(experience_app, name="experience")
app.add_typer(reuse_app, name="reuse")
app.add_typer(skill_app, name="skill")
app.add_typer(session_app, name="session")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

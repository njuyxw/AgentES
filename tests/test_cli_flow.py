from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentes.cli import app


runner = CliRunner()


EXPERIENCE_TEMPLATE = """
schema_version: 1
id: exp_generated_artifact
object_type: experience
status: success
confidence: medium
task:
  type: code_debugging
  domain: typescript
  project: demo
  repo: demo-repo
  summary: "Fix import error after schema update"
problem:
  symptoms:
    - "Tests fail with Cannot find module './generated/client'"
diagnosis:
  observations:
    - "Generated client was missing"
  hypotheses:
    - "Schema update did not trigger code generation"
  verified_facts:
    - "After running generator, tests passed"
  root_cause: "Stale generated artifact"
actions:
  summary: "Ran generator and reran tests"
  commands:
    - "pnpm openapi:generate"
    - "pnpm test"
outcome:
  result: success
reuse:
  applies_when:
    - "Schema or IDL changed"
    - "Import error references generated code"
    - "Repo has generator script"
  avoid_when:
    - "Generated files are intentionally not committed"
  required_checks:
    - "Inspect package.json for generator script"
    - "Confirm generated path is expected"
  validation_after_reuse:
    - "Run relevant test suite"
evidence:
  refs:
    - __EVIDENCE_REF__
provenance:
  source_run: run_20260428_001
  created_by: agent
lifecycle:
  created_at: "2026-04-28T12:00:00Z"
  updated_at: "2026-04-28T12:00:00Z"
"""


CONTEXT = """
task_type: code_debugging
domain: typescript
project: demo
repo: demo-repo
symptoms:
  - "Cannot find module './generated/client'"
environment:
  package_manager: pnpm
  language: typescript
observed:
  - "OpenAPI schema changed"
  - "package.json has openapi:generate script"
  - "Generated path is expected"
"""


def invoke(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def invoke_fail(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code != 0, result.output
    return result


def test_init_creates_store(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])

    assert (tmp_path / ".agentes" / "agentes.db").exists()
    assert (tmp_path / ".agentes" / "objects" / "skills" / "global_experience_retrieval.md").exists()


def test_full_experience_reuse_flow(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exp_path = tmp_path / "exp.yaml"
    ctx_path = tmp_path / "context.yaml"
    ctx_path.write_text(CONTEXT, encoding="utf-8")

    invoke(["init"])
    run = invoke(
        [
            "run",
            "start",
            "--task-type",
            "code_debugging",
            "--summary",
            "Fix generated client import error",
            "--project",
            "demo",
            "--repo",
            "demo-repo",
        ]
    ).output.strip()
    assert run.startswith("run_")

    trace = invoke(
        [
            "trace",
            "add",
            run,
            "--type",
            "command",
            "--command",
            "pnpm test",
            "--exit-code",
            "1",
            "--summary",
            "Tests failed with missing generated client",
        ]
    )
    assert "trace_step=1" in trace.output

    evidence = invoke(
        [
            "evidence",
            "create",
            run,
            "--type",
            "command_result",
            "--claim",
            "Tests passed after regenerating generated client",
            "--strength",
            "strong",
            "--command",
            "pnpm test",
            "--exit-code",
            "0",
        ]
    ).output.strip()
    assert evidence.startswith("ev_")

    exp_path.write_text(
        EXPERIENCE_TEMPLATE.replace("__EVIDENCE_REF__", evidence),
        encoding="utf-8",
    )

    imported = invoke(["experience", "import", str(exp_path)]).output.strip()
    assert imported == "exp_generated_artifact"

    search = invoke(
        [
            "experience",
            "search",
            "--query",
            "import error generated client schema update",
            "--task-type",
            "code_debugging",
        ]
    )
    assert "exp_generated_artifact" in search.output

    reuse = invoke(["experience", "open", "exp_generated_artifact", "--reuse"])
    assert "Applies When" in reuse.output

    evidence_view = invoke(["experience", "open", "exp_generated_artifact", "--evidence"])
    assert "ev_20260428_001" in evidence_view.output

    validation = invoke(
        [
            "experience",
            "validate-use",
            "exp_generated_artifact",
            "--context",
            str(ctx_path),
        ]
    )
    assert "applicability: high" in validation.output

    adapt = invoke(
        [
            "experience",
            "adapt",
            "exp_generated_artifact",
            "--context",
            str(ctx_path),
        ]
    )
    assert "Adapted Checklist" in adapt.output

    reuse_event = invoke(
        [
            "reuse",
            "record",
            "--experience",
            "exp_generated_artifact",
            "--run",
            run,
            "--result",
            "success",
        ]
    ).output.strip()
    assert reuse_event.startswith("reuse_")


def test_experience_import_rejects_unsafe_id(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    exp_path = tmp_path / "bad_exp.yaml"
    exp_path.write_text(
        EXPERIENCE_TEMPLATE.replace("exp_generated_artifact", "../escaped")
        .replace("__EVIDENCE_REF__", "ev_missing"),
        encoding="utf-8",
    )

    result = invoke_fail(["experience", "import", str(exp_path)])

    assert "Invalid experience id" in result.output
    assert not (tmp_path.parent / "escaped").exists()


def test_experience_import_rejects_missing_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    exp_path = tmp_path / "missing_evidence.yaml"
    exp_path.write_text(
        EXPERIENCE_TEMPLATE.replace("__EVIDENCE_REF__", "ev_missing"),
        encoding="utf-8",
    )

    result = invoke_fail(["experience", "import", str(exp_path)])

    assert "Missing evidence refs: ev_missing" in result.output


def test_reuse_record_rejects_invalid_result(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])

    result = invoke_fail(
        [
            "reuse",
            "record",
            "--experience",
            "exp_generated_artifact",
            "--result",
            "sucess",
        ]
    )

    assert "Invalid result" in result.output


def test_session_capture_flow(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    run = invoke(
        [
            "session",
            "start",
            "--summary",
            "Codex session memory flow",
            "--task-type",
            "code_editing",
        ]
    ).output.strip()
    assert run.startswith("run_")
    assert (tmp_path / ".agentes" / "tmp" / "codex_session.json").exists()

    trace = invoke(
        [
            "session",
            "trace",
            "--summary",
            "Recorded a session trace",
            "--type",
            "note",
        ]
    )
    assert "trace_step=1" in trace.output

    evidence = invoke(
        [
            "session",
            "evidence",
            "--claim",
            "Session evidence command works",
            "--strength",
            "strong",
        ]
    ).output.strip()
    assert evidence.startswith("ev_")

    capture = invoke(
        [
            "session",
            "capture",
            "--title",
            "Codex session capture stores reusable lessons",
            "--task-type",
            "code_editing",
            "--domain",
            "python",
            "--problem",
            "Codex needs session memory in the main CLI",
            "--actions",
            "Added built-in session commands",
            "--outcome",
            "Session commands created an experience",
            "--diagnosis",
            "Session capture belongs in the primary CLI",
            "--applies-when",
            "A future Codex session needs to save reusable lessons",
            "--required-check",
            "Run session capture in a temporary project",
            "--validation-after-reuse",
            "Search for the captured session experience",
            "--evidence",
            evidence,
        ]
    )
    assert "experience=exp_" in capture.output
    assert f"evidence={evidence}" in capture.output
    assert f"run={run}" in capture.output

    search = invoke(
        [
            "session",
            "search",
            "--query",
            "Codex session capture reusable lessons",
            "--task-type",
            "code_editing",
        ]
    )
    assert "Codex session capture stores reusable lessons" in search.output

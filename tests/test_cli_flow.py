from __future__ import annotations

import json
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


NEGATIVE_EXPERIENCE_TEMPLATE = """
schema_version: 1
id: exp_negative_generated_artifact
object_type: experience
status: failure
confidence: medium
task:
  type: code_debugging
  domain: typescript
  project: demo
  repo: demo-repo
  summary: "Do not regenerate client when generated files are uncommitted"
problem:
  symptoms:
    - "Import error references generated client"
  failure_modes:
    - "stale_generated_artifact"
diagnosis:
  observations:
    - "Generated files were intentionally not committed"
  verified_facts:
    - "Running the generator produced noisy unrelated diffs"
  root_cause: "Generated artifact policy mismatch"
actions:
  summary: "Tried generator and reverted the noisy result"
outcome:
  result: failure
reuse:
  applies_when:
    - "Generated client import fails"
  avoid_when:
    - "Generated files are intentionally not committed"
  required_checks:
    - "Check repository policy for generated files"
  validation_after_reuse:
    - "Confirm the actual package resolution path"
evidence:
  refs:
    - __EVIDENCE_REF__
lifecycle:
  created_at: "2026-04-28T12:00:00Z"
  updated_at: "2026-04-28T12:00:00Z"
"""


WARNING_EXPERIENCE_TEMPLATE = """
schema_version: 1
id: exp_warning_generated_artifact
object_type: experience
status: warning
confidence: low
task:
  type: code_debugging
  domain: typescript
  project: demo
  repo: demo-repo
  summary: "Generated client fixes may hide package resolution problems"
problem:
  symptoms:
    - "Generated client import fails"
  failure_modes:
    - "package_resolution"
diagnosis:
  observations:
    - "Similar import errors came from package resolution"
  verified_facts:
    - "Search should surface warning experiences when requested"
  root_cause: "Ambiguous generated client failure"
actions:
  summary: "Warned to inspect package resolution before generation"
outcome:
  result: warning
reuse:
  applies_when:
    - "Generated client import fails"
  avoid_when:
    - "The generated path is confirmed missing"
  required_checks:
    - "Inspect package resolution"
  validation_after_reuse:
    - "Run module resolution check"
evidence:
  refs:
    - __EVIDENCE_REF__
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


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_init_creates_store(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])

    assert (tmp_path / ".agentes" / "agentes.db").exists()
    skill_path = tmp_path / ".agentes" / "objects" / "skills" / "global_experience_retrieval.md"
    assert skill_path.exists()
    assert "agentes session reason \\\n  --observation" in skill_path.read_text(encoding="utf-8")


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
    assert evidence in evidence_view.output

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


def test_run_finish_rejects_invalid_status(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    run = invoke(
        [
            "run",
            "start",
            "--task-type",
            "code_debugging",
            "--summary",
            "Bad status fixture",
        ]
    ).output.strip()
    result = invoke_fail(["run", "finish", run, "--status", "done"])
    assert "Invalid status" in result.output


def test_evidence_create_rejects_invalid_strength(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    run = invoke(
        [
            "run",
            "start",
            "--task-type",
            "code_debugging",
            "--summary",
            "Strength fixture",
        ]
    ).output.strip()
    result = invoke_fail(
        [
            "evidence",
            "create",
            run,
            "--type",
            "command_result",
            "--claim",
            "Tests passed",
            "--strength",
            "very-strong",
        ]
    )
    assert "strength" in result.output.lower()


def test_init_preserves_user_skill_edits(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    skill_path = tmp_path / ".agentes" / "objects" / "skills" / "global_experience_retrieval.md"
    skill_path.write_text("# My customized skill\n", encoding="utf-8")
    invoke(["init"])
    assert skill_path.read_text(encoding="utf-8") == "# My customized skill\n"
    invoke(["init", "--force"])
    assert "Skill: Using AgentES" in skill_path.read_text(encoding="utf-8")


def test_skill_install_claude_code(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    target_dir = tmp_path / "claude_skills" / "agentes"
    output = invoke(
        [
            "skill",
            "install",
            "--target",
            "claude-code",
            "--dir",
            str(target_dir),
        ]
    ).output.strip()
    skill_path = target_dir / "SKILL.md"
    assert output == str(skill_path)
    body = skill_path.read_text(encoding="utf-8")
    assert body.startswith("---\nname: agentes\n")
    assert "description:" in body.splitlines()[2]
    assert "agentes session capture" in body

    refuse = invoke_fail(
        [
            "skill",
            "install",
            "--target",
            "claude-code",
            "--dir",
            str(target_dir),
        ]
    )
    assert "already exists" in refuse.output

    invoke(
        [
            "skill",
            "install",
            "--target",
            "claude-code",
            "--dir",
            str(target_dir),
            "--force",
        ]
    )


def test_skill_install_codex_has_no_frontmatter(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    target_dir = tmp_path / "codex_skills" / "agentes"
    invoke(
        [
            "skill",
            "install",
            "--target",
            "codex",
            "--dir",
            str(target_dir),
        ]
    )
    body = (target_dir / "SKILL.md").read_text(encoding="utf-8")
    assert not body.startswith("---")
    assert "AgentES Experience Store" in body


def test_skill_install_rejects_unknown_target(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    result = invoke_fail(["skill", "install", "--target", "vscode"])
    assert "Unknown target" in result.output


def test_shipped_skill_files_match_constants(tmp_path: Path):
    from agentes.skill import SKILL_TARGETS

    repo_root = Path(__file__).resolve().parents[1]
    for key, target in SKILL_TARGETS.items():
        shipped = repo_root / "skills" / key.replace("-", "_") / target.name / "SKILL.md"
        assert shipped.exists(), f"missing shipped skill: {shipped}"
        assert shipped.read_text(encoding="utf-8") == target.render(), (
            f"shipped skill drift: {shipped}"
        )


def test_session_start_refuses_when_run_active(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(
        [
            "session",
            "start",
            "--summary",
            "First session",
            "--task-type",
            "code_editing",
        ]
    )
    result = invoke_fail(
        [
            "session",
            "start",
            "--summary",
            "Second session",
            "--task-type",
            "code_editing",
        ]
    )
    assert "still active" in result.output


def test_experience_search_negative_filters(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(["init"])
    run = invoke(
        [
            "run",
            "start",
            "--task-type",
            "code_debugging",
            "--summary",
            "Search negative generated artifact experiences",
            "--project",
            "demo",
            "--repo",
            "demo-repo",
        ]
    ).output.strip()
    evidence = invoke(
        [
            "evidence",
            "create",
            run,
            "--type",
            "command_result",
            "--claim",
            "Negative search fixture evidence",
            "--strength",
            "medium",
        ]
    ).output.strip()

    success_path = tmp_path / "success.yaml"
    negative_path = tmp_path / "negative.yaml"
    warning_path = tmp_path / "warning.yaml"
    success_path.write_text(EXPERIENCE_TEMPLATE.replace("__EVIDENCE_REF__", evidence), encoding="utf-8")
    negative_path.write_text(NEGATIVE_EXPERIENCE_TEMPLATE.replace("__EVIDENCE_REF__", evidence), encoding="utf-8")
    warning_path.write_text(WARNING_EXPERIENCE_TEMPLATE.replace("__EVIDENCE_REF__", evidence), encoding="utf-8")
    invoke(["experience", "import", str(success_path)])
    invoke(["experience", "import", str(negative_path)])
    invoke(["experience", "import", str(warning_path)])

    default = invoke(
        [
            "experience",
            "search",
            "--query",
            "generated client",
            "--task-type",
            "code_debugging",
        ]
    )
    assert "exp_generated_artifact" in default.output
    assert "exp_negative_generated_artifact" not in default.output
    assert "exp_warning_generated_artifact" not in default.output

    include_negative = invoke(
        [
            "experience",
            "search",
            "--query",
            "generated client",
            "--task-type",
            "code_debugging",
            "--include-negative",
        ]
    )
    assert "exp_negative_generated_artifact" in include_negative.output
    assert "exp_warning_generated_artifact" in include_negative.output

    negative_only = invoke(
        [
            "experience",
            "search",
            "--query",
            "generated client",
            "--negative-only",
            "--failure-mode",
            "stale_generated_artifact",
        ]
    )
    assert "exp_negative_generated_artifact" in negative_only.output
    assert "exp_generated_artifact" not in negative_only.output
    assert "exp_warning_generated_artifact" not in negative_only.output

    warning = invoke(
        [
            "experience",
            "search",
            "--query",
            "generated client",
            "--warning",
            "--failure-mode",
            "package_resolution",
        ]
    )
    assert "exp_warning_generated_artifact" in warning.output
    assert "exp_negative_generated_artifact" not in warning.output


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

    stdout_path = tmp_path / "session.out"
    stderr_path = tmp_path / "session.err"
    stdout_path.write_text("trace stdout\n", encoding="utf-8")
    stderr_path.write_text("trace stderr\n", encoding="utf-8")
    trace = invoke(
        [
            "session",
            "trace",
            "--summary",
            "Recorded a session trace",
            "--type",
            "note",
            "--stdout",
            str(stdout_path),
            "--stderr",
            str(stderr_path),
        ]
    )
    assert "trace_step=1" in trace.output
    assert (tmp_path / ".agentes" / "objects" / "blobs" / "stdout" / f"{run}_step_1.out").exists()
    assert (tmp_path / ".agentes" / "objects" / "blobs" / "stderr" / f"{run}_step_1.err").exists()

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


def test_session_transcript_observe_reason_flow(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    run = invoke(
        [
            "session",
            "start",
            "--summary",
            "Record visible session context",
            "--task-type",
            "code_editing",
        ]
    ).output.strip()
    transcript_path = tmp_path / ".agentes" / "objects" / "transcripts" / f"{run}.jsonl"
    assert transcript_path.exists()

    user_message = invoke(
        [
            "session",
            "message",
            "--role",
            "user",
            "--content",
            "Fix failing tests after schema update",
        ]
    )
    assert "transcript_seq=1" in user_message.output
    assert "trace_step=1" in user_message.output

    assistant_message_path = tmp_path / "assistant_message.md"
    assistant_message_path.write_text("I will inspect the failing test output first.", encoding="utf-8")
    assistant_message = invoke(
        [
            "session",
            "message",
            "--role",
            "assistant",
            "--content-file",
            str(assistant_message_path),
        ]
    )
    assert "transcript_seq=2" in assistant_message.output
    assert "trace_step=2" in assistant_message.output

    observe = invoke(
        [
            "session",
            "observe",
            "--content",
            "Tests fail with Cannot find module './generated/client'",
        ]
    )
    assert "trace_step=3" in observe.output

    evidence = invoke(
        [
            "session",
            "evidence",
            "--claim",
            "After running the generator, tests passed",
            "--strength",
            "strong",
        ]
    ).output.strip()

    reason = invoke(
        [
            "session",
            "reason",
            "--observation",
            "Generated client import is missing",
            "--hypothesis",
            "Generated artifacts may be stale",
            "--decision",
            "Run generator before patching imports",
            "--rejected-alternative",
            "Patch import path directly :: Generated path appears expected",
            "--diagnosis",
            "Regeneration fixed the missing module",
            "--linked-evidence",
            evidence,
        ]
    )
    assert "trace_step=4" in reason.output

    transcript_events = read_jsonl(transcript_path)
    assert [event["role"] for event in transcript_events] == ["user", "assistant"]
    assert transcript_events[0]["content"] == "Fix failing tests after schema update"

    trace_path = next((tmp_path / ".agentes" / "objects" / "traces").glob("*.jsonl"))
    trace_events = read_jsonl(trace_path)
    assert [event["type"] for event in trace_events] == [
        "message",
        "message",
        "observation",
        "reasoning_summary",
    ]
    assert trace_events[0]["transcript_seq"] == 1
    assert trace_events[2]["content"] == "Tests fail with Cannot find module './generated/client'"
    assert trace_events[3]["observations"] == ["Generated client import is missing"]
    assert trace_events[3]["hypotheses"] == ["Generated artifacts may be stale"]
    assert trace_events[3]["decisions"] == ["Run generator before patching imports"]
    assert trace_events[3]["rejected_alternatives"] == [
        {"alternative": "Patch import path directly", "reason": "Generated path appears expected"}
    ]
    assert trace_events[3]["linked_evidence"] == [evidence]

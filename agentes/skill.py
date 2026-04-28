from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .storage import Store, write_text


DEFAULT_SKILL_NAME = "global_experience_retrieval"


PROJECT_SKILL_BODY = """# Skill: Using AgentES

AgentES stores evidence-backed experiences from prior agent runs.

## Rules

1. Do not reuse an experience based only on title or summary.
2. Before using an experience, inspect reuse and evidence.
3. Search negative or failed experiences when planning a risky strategy.
4. Validate applicability with `agentes experience validate-use`.
5. Convert experience into a checklist; do not copy old commands blindly.
6. After use, record the outcome with `agentes reuse record`.
7. If a new reusable lesson was learned, create an experience YAML and import it.
8. For Codex-style sessions, save visible transcript messages and structured reasoning summaries, not hidden chain-of-thought.

## Standard Flow

1. Classify the task.
2. Search experiences:

```bash
agentes experience search --query "<task symptoms>" --task-type "<type>"
agentes experience search --query "<task symptoms>" --task-type "<type>" --include-negative
agentes experience search --query "<failure mode>" --negative-only --failure-mode "<mode>"
```

3. Open relevant experience:

```bash
agentes experience open <id> --reuse
agentes experience open <id> --evidence
```

4. Validate:

```bash
agentes experience validate-use <id> --context current_context.yaml
```

5. Adapt:

```bash
agentes experience adapt <id> --context current_context.yaml
```

6. Act and validate locally.

7. Record reuse:

```bash
agentes reuse record --experience <id> --run <run_id> --result success|failure|partial
```

## Session Memory Flow

For substantial Codex sessions, use the built-in session commands:

```bash
agentes session start --summary "<task>" --task-type "<type>"
agentes session message --role user --content "<visible user message>"
agentes session message --role assistant --content-file /tmp/assistant-message.md
agentes session trace --summary "<tool result>" --type tool_result --command "<command>" --exit-code 0
agentes session observe --content "<visible observation>"
agentes session reason \\
  --observation "<what was observed>" \\
  --hypothesis "<explicit hypothesis>" \\
  --decision "<decision made>" \\
  --rejected-alternative "<alternative :: reason>"
agentes session capture --title "<lesson>" ...
```

Transcript messages are stored under `.agentes/objects/transcripts/<run_id>.jsonl`; trace, observation, and reasoning summary events remain in `.agentes/objects/traces/`.
"""


CLAUDE_CODE_SKILL_NAME = "agentes"
CLAUDE_CODE_SKILL_DESCRIPTION = (
    "Search, validate, and reuse evidence-backed experiences from prior coding sessions "
    "stored in a project-local .agentes/ directory. Use PROACTIVELY: at task start to "
    "recall prior solutions, when planning a risky change to surface known failure modes, "
    "and after a notable success or failure to capture a reusable lesson with linked "
    "evidence. Triggers on phrases like 'have we seen this before', 'prior experience', "
    "'lesson learned', 'failure mode', 'negative experience', 'record this fix', or any "
    "request to save or look up a past solution."
)


CLAUDE_CODE_SKILL_BODY = """# Skill: AgentES Experience Store

AgentES is a local-first, evidence-backed experience store. It saves coding-session
runs, traces, transcripts, evidence, and reusable experiences in a project-local
`.agentes/` directory so future sessions can search and validate them.

## When to invoke this skill

Use it proactively at three points in a session:

1. **Task start.** Search prior experiences for the same symptoms before planning.
   If a validated experience exists, retrieve its reuse boundary instead of starting
   from scratch.
2. **Planning a risky change.** Run a `--negative-only` search for the relevant
   failure mode, so known traps surface before action.
3. **End of substantial work.** Capture a reusable lesson with linked evidence
   whenever the outcome is non-obvious, contradicts intuition, or would have
   saved time if known earlier.

## Setup (once per repository)

```bash
agentes init
```

Creates `.agentes/` with a SQLite index, FTS5 search, and YAML/Markdown object store.

## Standard flow

### 1. Start a session run

```bash
RUN=$(agentes session start \\
  --summary "<task description>" \\
  --task-type code_debugging)
```

The run id is stored in `.agentes/tmp/codex_session.json` so subsequent
session commands default to it.

### 2. Search prior experience

```bash
agentes experience search --query "<task symptoms>" --task-type "<type>"
agentes experience search --query "<task symptoms>" --task-type "<type>" --include-negative
agentes experience search --query "<failure mode>" --negative-only --failure-mode "<mode>"
```

Always run a positive search first, then a `--include-negative` or `--negative-only`
pass before committing to an approach.

### 3. Inspect a candidate before reusing

```bash
agentes experience open <exp_id> --reuse
agentes experience open <exp_id> --evidence
```

Never reuse an experience based on title or summary alone — open `--reuse` and
`--evidence` first.

### 4. Validate applicability

```bash
cat > current_context.yaml <<'EOF'
task_type: code_debugging
domain: typescript
symptoms:
  - "<the symptom you are facing now>"
environment:
  package_manager: pnpm
EOF

agentes experience validate-use <exp_id> --context current_context.yaml
agentes experience adapt <exp_id> --context current_context.yaml
```

`adapt` returns a local checklist; do not copy old commands blindly.

### 5. Record visible session context as work progresses

```bash
agentes session message --role user --content "<visible user instruction>"
agentes session message --role assistant --content-file /tmp/assistant_msg.md
agentes session trace --type tool_result \\
  --command "pnpm test" --exit-code 0 \\
  --summary "<short result>" --stdout /tmp/stdout.txt
agentes session observe --content "<visible observation>"
agentes session reason \\
  --observation "<what was observed>" \\
  --hypothesis "<explicit hypothesis>" \\
  --decision "<decision made>" \\
  --rejected-alternative "<alternative :: reason>"
```

Use `--content-file` for long messages. Save only visible transcript messages
and structured reasoning summaries — never hidden chain-of-thought.

### 6. Record reuse outcome

```bash
agentes reuse record --experience <exp_id> --run "$RUN" --result success
```

### 7. Capture a new reusable lesson with evidence

```bash
EV=$(agentes session evidence \\
  --type command_result \\
  --claim "Tests passed after regenerating client" \\
  --strength strong \\
  --command "pnpm test" --exit-code 0)

agentes session capture \\
  --title "Regenerate client when schema changes" \\
  --task-type code_debugging \\
  --domain typescript \\
  --actions "Ran pnpm openapi:generate then pnpm test" \\
  --outcome "Tests passed" \\
  --diagnosis "Stale generated artifact" \\
  --applies-when "Schema or IDL changed" \\
  --required-check "Inspect package.json for generator script" \\
  --validation-after-reuse "Run relevant test suite" \\
  --evidence "$EV"

agentes session finish --status success
```

## Rules

1. Do not reuse an experience based only on title or summary.
2. Before any risky change, run a `--negative-only` search.
3. Convert experiences into local checklists with `experience adapt`.
4. Always record the reuse outcome so future ranking can learn.
5. Capture a new lesson only with linked evidence (a passing/failing command
   with stdout/stderr, a verified fact, or a metric measurement).
6. Store visible context only — no hidden chain-of-thought.
"""


CODEX_SKILL_BODY = CLAUDE_CODE_SKILL_BODY


@dataclass(frozen=True)
class SkillTarget:
    name: str
    body: str
    frontmatter: bool
    description: str = ""
    default_dir_env: str = ""
    default_dir_fallback: str = ""

    def render(self) -> str:
        if not self.frontmatter:
            return self.body
        front = (
            "---\n"
            f"name: {self.name}\n"
            f"description: {self.description}\n"
            "---\n\n"
        )
        return front + self.body

    def default_dir(self) -> Path:
        env_value = os.environ.get(self.default_dir_env)
        base = Path(env_value).expanduser() if env_value else Path(self.default_dir_fallback).expanduser()
        return base / "skills" / self.name


SKILL_TARGETS: Dict[str, SkillTarget] = {
    "claude-code": SkillTarget(
        name=CLAUDE_CODE_SKILL_NAME,
        body=CLAUDE_CODE_SKILL_BODY,
        frontmatter=True,
        description=CLAUDE_CODE_SKILL_DESCRIPTION,
        default_dir_env="CLAUDE_HOME",
        default_dir_fallback="~/.claude",
    ),
    "codex": SkillTarget(
        name=CLAUDE_CODE_SKILL_NAME,
        body=CODEX_SKILL_BODY,
        frontmatter=False,
        default_dir_env="CODEX_HOME",
        default_dir_fallback="~/.codex",
    ),
}


def install_default_skill(store: Store, force: bool = False) -> None:
    path = store.skills / f"{DEFAULT_SKILL_NAME}.md"
    if path.exists() and not force:
        return
    write_text(path, PROJECT_SKILL_BODY)


def install_external_skill(target: str, dir_override: Path | None = None, force: bool = False) -> Path:
    if target not in SKILL_TARGETS:
        raise ValueError(
            f"Unknown skill target: {target}. Choose one of: {', '.join(sorted(SKILL_TARGETS))}."
        )
    descriptor = SKILL_TARGETS[target]
    target_dir = dir_override.expanduser() if dir_override else descriptor.default_dir()
    skill_path = target_dir / "SKILL.md"
    if skill_path.exists() and not force:
        raise FileExistsError(
            f"Skill already exists at {skill_path}. Pass --force to overwrite."
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    write_text(skill_path, descriptor.render())
    return skill_path

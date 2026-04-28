from __future__ import annotations

from .storage import Store, write_text


DEFAULT_SKILL_NAME = "global_experience_retrieval"


DEFAULT_SKILL = """# Skill: Using AgentES

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


def install_default_skill(store: Store) -> None:
    write_text(store.skills / f"{DEFAULT_SKILL_NAME}.md", DEFAULT_SKILL)

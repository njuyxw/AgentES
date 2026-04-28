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

## Standard Flow

1. Classify the task.
2. Search experiences:

```bash
agentes experience search --query "<task symptoms>" --task-type "<type>"
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
"""


def install_default_skill(store: Store) -> None:
    write_text(store.skills / f"{DEFAULT_SKILL_NAME}.md", DEFAULT_SKILL)

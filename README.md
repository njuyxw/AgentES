# AgentES

AgentES is a local-first, evidence-backed experience store for coding and research agents. It stores runs, traces, evidence, reusable experiences, and reuse events in a project-local `.agentes/` directory.

The MVP implements the core loop from `agentes_design.html`:

```text
search -> inspect evidence -> validate applicability -> adapt -> record reuse
```

## Quickstart

Run without installing:

```bash
uv run agentes init
```

Run the demo:

```bash
bash examples/run_demo.sh
```

For development tests:

```bash
uv run --python 3.9 --extra dev pytest
```

Build a standalone executable:

```bash
uv run --python 3.9 --extra build python scripts/build_binary.py --clean
./dist/agentes --help
```

The resulting `dist/agentes` binary can be moved onto PATH, for example:

```bash
install -m 755 dist/agentes ~/.local/bin/agentes
```

Or run the core flow manually:

```bash
agentes init

RUN=$(agentes run start \
  --task-type code_debugging \
  --summary "Fix generated client import error" \
  --project demo \
  --repo demo-repo)

agentes trace add "$RUN" \
  --type command \
  --command "pnpm test" \
  --exit-code 1 \
  --summary "Tests failed with missing generated client"

EV=$(agentes evidence create "$RUN" \
  --type command_result \
  --claim "Tests passed after regenerating generated client" \
  --strength strong \
  --command "pnpm test" \
  --exit-code 0)

EXP_IMPORT=".agentes/tmp/exp_generated_artifact_${RUN}.yaml"
sed \
  -e "s/ev_20260428_001/${EV}/g" \
  -e "s/run_20260428_001/${RUN}/g" \
  examples/exp_generated_artifact.yaml > "$EXP_IMPORT"

agentes experience import "$EXP_IMPORT"

agentes experience search \
  --query "import error generated client schema update" \
  --task-type code_debugging

agentes experience open exp_generated_artifact --reuse
agentes experience open exp_generated_artifact --evidence

agentes experience validate-use exp_generated_artifact \
  --context examples/context_generated_artifact.yaml

agentes experience adapt exp_generated_artifact \
  --context examples/context_generated_artifact.yaml

agentes reuse record \
  --experience exp_generated_artifact \
  --run "$RUN" \
  --result success
```

## Storage

`agentes init` creates:

```text
.agentes/
  agentes.db
  objects/
    runs/
    traces/
    evidence/
    experiences/
    blobs/
    skills/
  inbox/
    unreviewed_experiences/
  tmp/
```

SQLite owns metadata and FTS search. YAML, Markdown, and JSONL keep the stored objects readable.

## Codex Skill Integration

This machine has an AgentES Codex skill installed at:

```text
/home/jinyx/.codex/skills/agentes
```

AgentES includes built-in session commands for Codex-style memory capture:

```bash
agentes session start --summary "<task>" --task-type code_editing
agentes session search --query "<task symptoms>"
agentes session capture --title "<lesson>" ...
```

Use it to start an AgentES run at the beginning of a substantial Codex session, search prior experience before planning, record important trace points, and capture evidence-backed reusable lessons at the end.

# AgentES

AgentES is a local-first, evidence-backed experience store for coding and research agents. It stores runs, transcripts, traces, evidence, reusable experiences, and reuse events in a project-local `.agentes/` directory.

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

agentes experience search \
  --query "generated client schema" \
  --task-type code_debugging \
  --include-negative

agentes experience search \
  --query "generated client" \
  --negative-only \
  --failure-mode stale_generated_artifact

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
    transcripts/
    evidence/
    experiences/
    blobs/
    skills/
  inbox/
    unreviewed_experiences/
  tmp/
```

SQLite owns metadata and FTS search. YAML, Markdown, and JSONL keep the stored objects readable.

## Editor / Agent Integrations

AgentES ships skill descriptors for both Codex and Claude Code under `skills/`.
The `agentes skill install` command writes the appropriate `SKILL.md` into the
target's standard skills directory.

### Claude Code

Install the skill for a single user:

```bash
agentes skill install --target claude-code
# → ~/.claude/skills/agentes/SKILL.md
```

Override the install location with `--dir`, or set `CLAUDE_HOME`:

```bash
CLAUDE_HOME=/opt/claude agentes skill install --target claude-code
agentes skill install --target claude-code --dir /tmp/skills/agentes
```

Pass `--force` to overwrite an existing SKILL.md.

The shipped skill includes a Claude-Code-friendly `description` so Claude Code
auto-invokes it on phrases such as "have we seen this before", "lesson learned",
"failure mode", or any request to record/look up a past solution. The skill
body documents the `agentes session` flow Claude Code should run.

### Codex

```bash
agentes skill install --target codex
# → ~/.codex/skills/agentes/SKILL.md
```

The repository also keeps a project-local Codex skill at
`skills/global_experience_retrieval.md`; `agentes init` writes a copy of this
into `.agentes/objects/skills/` for project-scoped usage. Existing user edits
are preserved on subsequent `agentes init` calls; pass `--force` to reinstall
the bundled version.

AgentES includes built-in session commands for Codex-style memory capture:

```bash
agentes session start --summary "<task>" --task-type code_editing
agentes session message --role user --content "<visible user message>"
agentes session message --role assistant --content-file /tmp/assistant-message.md
agentes session message --role assistant --content "<visible assistant response>"
agentes session search --query "<task symptoms>"
agentes session trace \
  --summary "<tool or command result>" \
  --type tool_result \
  --command "<command>" \
  --exit-code 0 \
  --stdout /tmp/stdout.txt \
  --stderr /tmp/stderr.txt
agentes session observe --content "<visible observation>"
agentes session reason \
  --observation "<what was observed>" \
  --hypothesis "<explicit hypothesis>" \
  --decision "<decision made>" \
  --rejected-alternative "<alternative :: reason>"
agentes session capture --title "<lesson>" ...
```

Use it to start an AgentES run at the beginning of a substantial Codex session, search prior experience before planning, store visible transcript messages in `.agentes/objects/transcripts/<run_id>.jsonl`, record important trace points, and capture evidence-backed reusable lessons at the end. Use `--content-file` for long visible messages. AgentES stores visible transcript and structured reasoning summaries; it does not store hidden chain-of-thought.

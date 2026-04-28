---
name: agentes
description: Search, validate, and reuse evidence-backed experiences from prior coding sessions stored in a project-local .agentes/ directory. Use PROACTIVELY: at task start to recall prior solutions, when planning a risky change to surface known failure modes, and after a notable success or failure to capture a reusable lesson with linked evidence. Triggers on phrases like 'have we seen this before', 'prior experience', 'lesson learned', 'failure mode', 'negative experience', 'record this fix', or any request to save or look up a past solution.
---

# Skill: AgentES Experience Store

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
RUN=$(agentes session start \
  --summary "<task description>" \
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
agentes session trace --type tool_result \
  --command "pnpm test" --exit-code 0 \
  --summary "<short result>" --stdout /tmp/stdout.txt
agentes session observe --content "<visible observation>"
agentes session reason \
  --observation "<what was observed>" \
  --hypothesis "<explicit hypothesis>" \
  --decision "<decision made>" \
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
EV=$(agentes session evidence \
  --type command_result \
  --claim "Tests passed after regenerating client" \
  --strength strong \
  --command "pnpm test" --exit-code 0)

agentes session capture \
  --title "Regenerate client when schema changes" \
  --task-type code_debugging \
  --domain typescript \
  --actions "Ran pnpm openapi:generate then pnpm test" \
  --outcome "Tests passed" \
  --diagnosis "Stale generated artifact" \
  --applies-when "Schema or IDL changed" \
  --required-check "Inspect package.json for generator script" \
  --validation-after-reuse "Run relevant test suite" \
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

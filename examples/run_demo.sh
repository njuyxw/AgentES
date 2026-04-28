#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

agentes_cmd() {
  if command -v agentes >/dev/null 2>&1; then
    agentes "$@"
  else
    uv run agentes "$@"
  fi
}

agentes_cmd init

RUN="$(agentes_cmd run start \
  --task-type code_debugging \
  --summary "Fix generated client import error" \
  --project demo \
  --repo demo-repo)"

agentes_cmd trace add "$RUN" \
  --type command \
  --command "pnpm test" \
  --exit-code 1 \
  --summary "Tests failed with missing generated client"

EV="$(agentes_cmd evidence create "$RUN" \
  --type command_result \
  --claim "Tests passed after regenerating generated client" \
  --strength strong \
  --command "pnpm test" \
  --exit-code 0)"

EXP_IMPORT=".agentes/tmp/exp_generated_artifact_${RUN}.yaml"
sed \
  -e "s/ev_20260428_001/${EV}/g" \
  -e "s/run_20260428_001/${RUN}/g" \
  examples/exp_generated_artifact.yaml > "$EXP_IMPORT"

agentes_cmd experience import "$EXP_IMPORT"

agentes_cmd experience search \
  --query "import error generated client schema update" \
  --task-type code_debugging

agentes_cmd experience open exp_generated_artifact --reuse
agentes_cmd experience open exp_generated_artifact --evidence

agentes_cmd experience validate-use exp_generated_artifact \
  --context examples/context_generated_artifact.yaml

agentes_cmd experience adapt exp_generated_artifact \
  --context examples/context_generated_artifact.yaml

agentes_cmd reuse record \
  --experience exp_generated_artifact \
  --run "$RUN" \
  --result success \
  --notes "Demo reuse completed"

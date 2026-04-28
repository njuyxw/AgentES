from __future__ import annotations

import sqlite3
from typing import Any

from .storage import as_list, list_to_markdown


def search_cards(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "No experiences found.\n"
    chunks: list[str] = []
    for row in rows:
        chunks.append(
            "\n".join(
                [
                    row["id"],
                    f"  title: {row['title']}",
                    f"  status: {row['status']} | confidence: {row['confidence']} | evidence: {row['evidence_count']}",
                    f"  summary: {row['summary']}",
                    f"  next: agentes experience open {row['id']} --reuse && agentes experience open {row['id']} --evidence",
                ]
            )
        )
    return "\n\n".join(chunks) + "\n"


def summary_markdown(manifest: dict[str, Any]) -> str:
    task = manifest.get("task") or {}
    problem = manifest.get("problem") or {}
    outcome = manifest.get("outcome") or {}
    return "\n".join(
        [
            f"# {task.get('summary') or manifest.get('id')}",
            "",
            f"- ID: {manifest.get('id')}",
            f"- Status: {manifest.get('status')}",
            f"- Confidence: {manifest.get('confidence')}",
            f"- Task type: {task.get('type', '')}",
            f"- Domain: {task.get('domain', '')}",
            "",
            "## Problem",
            list_to_markdown(as_list(problem.get("symptoms"))),
            "## Outcome",
            f"- Result: {outcome.get('result', manifest.get('status'))}",
        ]
    ).strip() + "\n"


def reuse_markdown(manifest: dict[str, Any]) -> str:
    reuse = manifest.get("reuse") or {}
    return "\n".join(
        [
            f"# Reuse Boundary: {manifest.get('id')}",
            "",
            "## Applies When",
            list_to_markdown(as_list(reuse.get("applies_when"))),
            "## Avoid When",
            list_to_markdown(as_list(reuse.get("avoid_when"))),
            "## Required Checks",
            list_to_markdown(as_list(reuse.get("required_checks"))),
            "## Validation After Reuse",
            list_to_markdown(as_list(reuse.get("validation_after_reuse"))),
        ]
    ).strip() + "\n"


def diagnosis_markdown(manifest: dict[str, Any]) -> str:
    diagnosis = manifest.get("diagnosis") or {}
    return "\n".join(
        [
            f"# Diagnosis: {manifest.get('id')}",
            "",
            "## Observations",
            list_to_markdown(as_list(diagnosis.get("observations"))),
            "## Hypotheses",
            list_to_markdown(as_list(diagnosis.get("hypotheses"))),
            "## Verified Facts",
            list_to_markdown(as_list(diagnosis.get("verified_facts"))),
            "## Root Cause",
            f"- {diagnosis.get('root_cause', 'Unknown')}",
        ]
    ).strip() + "\n"


def validation_report(result: dict[str, Any]) -> str:
    def condition_lines(items: list[Any]) -> list[str]:
        if not items:
            return ["- None"]
        return [
            f"- {item.condition} (score={item.score:.2f}, tokens={', '.join(item.matched_tokens) or 'none'})"
            for item in items
        ]

    lines = [
        f"experience: {result['experience_id']}",
        f"applicability: {result['applicability']}",
        f"transfer_risk: {result['transfer_risk']}",
        f"recommendation: {result['recommendation']}",
        "",
        "matched_applies_when:",
        *condition_lines(result["matched_applies_when"]),
        "",
        "triggered_avoid_when:",
        *condition_lines(result["triggered_avoid_when"]),
        "",
        "completed_required_checks:",
        *condition_lines(result["completed_required_checks"]),
        "",
        "missing_required_checks:",
        *condition_lines(result["missing_required_checks"]),
        "",
        "validation_after_reuse:",
    ]
    validations = result.get("validation_after_reuse") or []
    lines.extend(f"- {item}" for item in validations)
    if not validations:
        lines.append("- Run relevant local validation.")
    return "\n".join(lines) + "\n"


def evidence_view(refs: list[str], manifests: dict[str, dict[str, Any]]) -> str:
    if not refs:
        return "No evidence refs declared.\n"
    chunks: list[str] = []
    for ref in refs:
        manifest = manifests.get(ref)
        if manifest is None:
            chunks.append(f"{ref}\n  status: missing local evidence manifest")
            continue
        chunks.append(
            "\n".join(
                [
                    ref,
                    f"  type: {manifest.get('type')}",
                    f"  strength: {manifest.get('strength')}",
                    f"  claim: {manifest.get('claim')}",
                    f"  run: {(manifest.get('source') or {}).get('run')}",
                ]
            )
        )
    return "\n\n".join(chunks) + "\n"

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .storage import as_list, flatten_text


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "has",
    "in",
    "is",
    "it",
    "of",
    "or",
    "the",
    "to",
    "when",
    "with",
}


@dataclass
class ConditionMatch:
    condition: str
    score: float
    matched_tokens: list[str]

    @property
    def matched(self) -> bool:
        return self.score >= 0.25


def tokens(text: str) -> set[str]:
    raw = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    return {item for item in raw if len(item) > 1 and item not in STOPWORDS}


def condition_match(condition: str, context_text: str) -> ConditionMatch:
    condition_lower = condition.lower()
    context_lower = context_text.lower()
    condition_tokens = tokens(condition_lower)
    if not condition_tokens:
        return ConditionMatch(condition=condition, score=0.0, matched_tokens=[])
    if condition_lower in context_lower:
        return ConditionMatch(condition=condition, score=1.0, matched_tokens=sorted(condition_tokens))
    context_tokens = tokens(context_lower)
    matched = sorted(condition_tokens & context_tokens)
    score = len(matched) / len(condition_tokens)
    return ConditionMatch(condition=condition, score=score, matched_tokens=matched)


def validate_use(manifest: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    reuse = manifest.get("reuse") or {}
    context_text = flatten_text(context)
    applies = [
        condition_match(condition, context_text)
        for condition in as_list(reuse.get("applies_when"))
    ]
    avoids = [
        condition_match(condition, context_text)
        for condition in as_list(reuse.get("avoid_when"))
    ]
    checks = [
        condition_match(condition, context_text)
        for condition in as_list(reuse.get("required_checks"))
    ]

    matched_applies = [item for item in applies if item.matched]
    triggered_avoids = [item for item in avoids if item.score >= 0.75]
    completed_checks = [item for item in checks if item.score >= 0.4]
    missing_checks = [item for item in checks if item.score < 0.4]

    if triggered_avoids:
        applicability = "low"
        transfer_risk = "high"
        recommendation = "Do not reuse directly. Investigate the avoid condition first."
    elif applies and len(matched_applies) / len(applies) >= 0.5:
        applicability = "high"
        transfer_risk = "low" if not missing_checks else "medium"
        recommendation = "Use through the adapted checklist, then validate locally."
    elif matched_applies:
        applicability = "medium"
        transfer_risk = "medium"
        recommendation = "Reuse only after completing missing checks."
    else:
        applicability = "low"
        transfer_risk = "medium"
        recommendation = "Treat as background context, not a reusable plan."

    return {
        "experience_id": manifest.get("id"),
        "applicability": applicability,
        "transfer_risk": transfer_risk,
        "matched_applies_when": matched_applies,
        "triggered_avoid_when": triggered_avoids,
        "completed_required_checks": completed_checks,
        "missing_required_checks": missing_checks,
        "validation_after_reuse": as_list(reuse.get("validation_after_reuse")),
        "recommendation": recommendation,
    }


def checklist_for(manifest: dict[str, Any], validation: dict[str, Any]) -> str:
    reuse = manifest.get("reuse") or {}
    actions = manifest.get("actions") or {}
    lines = [
        f"# Adapted Checklist: {manifest.get('id')}",
        "",
        "## Applicability",
        f"- Applicability: {validation['applicability']}",
        f"- Transfer risk: {validation['transfer_risk']}",
        f"- Recommendation: {validation['recommendation']}",
        "",
        "## Required Checks",
    ]

    checks = as_list(reuse.get("required_checks"))
    if checks:
        lines.extend(f"- [ ] {item}" for item in checks)
    else:
        lines.append("- [ ] Confirm the current context matches the experience boundary.")

    lines.extend(["", "## Adapted Actions"])
    action_summary = actions.get("summary")
    if action_summary:
        lines.append(f"- [ ] Adapt action: {action_summary}")
    for command in as_list(actions.get("commands")):
        lines.append(f"- [ ] Consider local equivalent for command: `{command}`")
    if not action_summary and not as_list(actions.get("commands")):
        lines.append("- [ ] Derive local actions from the diagnosis and evidence.")

    lines.extend(["", "## Validation After Reuse"])
    validations = as_list(reuse.get("validation_after_reuse"))
    if validations:
        lines.extend(f"- [ ] {item}" for item in validations)
    else:
        lines.append("- [ ] Run the smallest relevant local validation.")

    avoid = as_list(reuse.get("avoid_when"))
    if avoid:
        lines.extend(["", "## Stop Conditions"])
        lines.extend(f"- [ ] Stop or reassess if: {item}" for item in avoid)

    return "\n".join(lines) + "\n"

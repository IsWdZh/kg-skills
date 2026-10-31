#!/usr/bin/env python3
"""Validate recommendation responses against trust and ownership boundaries."""

import json
import sys
from pathlib import Path


FORBIDDEN_KEYS = {"auto_apply", "write_back", "patch", "business_status", "approval_result", "transition", "final_result"}


def nested_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from nested_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from nested_keys(item)


def main(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    for key in ("request_id", "correlation_id", "knowledge_version", "status", "candidates"):
        if key not in data:
            errors.append(f"missing {key}")
    forbidden = FORBIDDEN_KEYS.intersection(set(nested_keys(data)))
    if forbidden:
        errors.append(f"forbidden write/decision fields: {sorted(forbidden)}")
    for index, item in enumerate(data.get("candidates", []), 1):
        for key in ("candidate_id", "content", "candidate_status", "confidence", "evidence_refs", "knowledge_roles", "applicable_conditions", "differences", "risks"):
            if key not in item:
                errors.append(f"candidate[{index}] missing {key}")
        if item.get("candidate_status") != "suggestion":
            errors.append(f"candidate[{index}] must remain suggestion")
        roles = set(item.get("knowledge_roles", []))
        if item.get("cross_domain_refs") and not item.get("adaptation_required", False):
            errors.append(f"candidate[{index}] cross-domain reference requires adaptation confirmation")
        if not item.get("evidence_refs") and "模型建议" not in roles:
            errors.append(f"candidate[{index}] has no evidence and is not marked model suggestion")
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_recommendation.py <recommendation.json>")
    raise SystemExit(main(Path(sys.argv[1])))

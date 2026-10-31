#!/usr/bin/env python3
"""Validate a reusable case asset manifest."""

import json
import sys
from pathlib import Path


REQUIRED = {"case_id", "title", "version", "review_status", "region", "industry", "access_scope", "applicability", "not_applicable", "evidence_refs", "reuse_units"}
ALLOWED_STATUS = {"已审核", "已发布", "已确认可沉淀"}


def main(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = [f"missing field: {key}" for key in sorted(REQUIRED - set(data))]
    if data.get("review_status") not in ALLOWED_STATUS:
        errors.append("review_status must be approved for knowledge governance")
    for key in ("applicability", "not_applicable", "evidence_refs", "reuse_units"):
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key} must be an array")
    for index, unit in enumerate(data.get("reuse_units", []), 1):
        for key in ("unit_id", "content", "evidence_refs", "applicable_conditions", "risks"):
            if key not in unit:
                errors.append(f"reuse_units[{index}] missing {key}")
        if not unit.get("evidence_refs"):
            errors.append(f"reuse_units[{index}] must cite evidence")
    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_case.py <case-manifest.json>")
    raise SystemExit(main(Path(sys.argv[1])))

#!/usr/bin/env python3
"""Validate method/rule assets and reject upper-layer workflow configuration."""

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


FORBIDDEN = {"workflow", "stages", "transitions", "approval", "approvers", "business_status", "auto_writeback", "form_crud", "report_template"}
TYPES = {"method", "guidance", "validation_rule", "response_template"}


def walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_keys(item)


def main(root: Path) -> int:
    errors = []
    manifests = list(root.rglob("manifest.yaml")) + list(root.rglob("manifest.yml")) + list(root.rglob("manifest.json"))
    if not manifests:
        errors.append("no manifest found")
    for path in manifests:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in ("asset_id", "asset_type", "version", "applicable_tasks", "inputs", "outputs", "owner", "sources"):
            if key not in data:
                errors.append(f"{path}: missing {key}")
        if data.get("asset_type") not in TYPES:
            errors.append(f"{path}: invalid asset_type")
        found = FORBIDDEN.intersection(set(walk_keys(data)))
        if found:
            errors.append(f"{path}: forbidden business workflow keys {sorted(found)}")
        if data.get("asset_type") == "validation_rule":
            for key in ("severity", "applicability", "evidence_requirement", "exceptions", "repair_advice", "tests"):
                if key not in data:
                    errors.append(f"{path}: validation rule missing {key}")
    print(json.dumps({"valid": not errors, "checked": len(manifests), "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_method_rules.py <asset-root>")
    raise SystemExit(main(Path(sys.argv[1])))

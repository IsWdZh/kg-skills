#!/usr/bin/env python3
"""Validate a knowledge-service integration package."""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


REQUIRED_ENDPOINTS = {"document-intake", "context-retrieve", "evidence-pack", "recommend", "verify", "feedback", "impact-notify"}
FORBIDDEN = {"business-object-crud", "workflow-transition", "approval", "auto-writeback", "report-render"}


def read(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main(root: Path) -> int:
    errors = []
    required_files = [
        "manifest.yaml", "context-mapping.yaml", "retrieval-profiles.yaml",
        "api-contract/endpoints.yaml", "api-contract/error-codes.yaml",
    ]
    for name in required_files:
        if not (root / name).exists():
            errors.append(f"missing {name}")
    endpoints = {}
    endpoint_file = root / "api-contract" / "endpoints.yaml"
    if endpoint_file.exists():
        endpoints = read(endpoint_file) or {}
        names = {x.get("name") for x in endpoints.get("endpoints", [])}
        for name in sorted(REQUIRED_ENDPOINTS - names):
            errors.append(f"missing endpoint {name}")
        forbidden = names.intersection(FORBIDDEN)
        if forbidden:
            errors.append(f"forbidden upper-layer endpoints {sorted(forbidden)}")
        for item in endpoints.get("endpoints", []):
            for key in ("name", "method", "path", "request_schema", "response_schema", "auth", "idempotency"):
                if key not in item:
                    errors.append(f"endpoint {item.get('name', '?')} missing {key}")
    schemas = list((root / "response-schemas").glob("*.json")) if (root / "response-schemas").exists() else []
    for path in schemas:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON schema {path}: {exc}")
    result = {"valid": not errors, "endpoints": len(endpoints.get("endpoints", [])), "schemas": len(schemas), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_contract.py <integration-directory>")
    raise SystemExit(main(Path(sys.argv[1])))

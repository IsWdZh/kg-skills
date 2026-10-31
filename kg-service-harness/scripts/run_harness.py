#!/usr/bin/env python3
"""Run static contract, golden, permission and ownership-boundary tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


FORBIDDEN_KEYS = {"auto_apply", "write_back", "patch", "business_status", "approval_result", "workflow_transition"}


def load(path: Path):
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


def validate_schema(value, schema: dict, path="$" ) -> list[str]:
    errors = []
    expected = schema.get("type")
    checks = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool}
    expected_types = expected if isinstance(expected, list) else [expected]
    known = [checks[item] for item in expected_types if item in checks]
    allows_null = "null" in expected_types
    if value is None and allows_null:
        return []
    if known and not any(isinstance(value, item) for item in known):
        return [f"{path}: expected {expected}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not in enum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        for key, child in schema.get("properties", {}).items():
            if key in value:
                errors.extend(validate_schema(value[key], child, f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{index}]"))
    return errors


def nested_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from nested_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from nested_keys(item)


def result(name: str, passed: bool, details: list[str] | None = None) -> dict:
    return {"name": name, "passed": passed, "details": details or []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("integration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.integration.resolve()
    results = []

    required = [
        "manifest.yaml", "context-mapping.yaml", "retrieval-profiles.yaml",
        "api-contract/endpoints.yaml", "api-contract/error-codes.yaml",
        "tests/contract-tests.yaml", "tests/golden-responses.yaml", "tests/permission-tests.yaml",
    ]
    missing = [name for name in required if not (root / name).exists()]
    results.append(result("required-files", not missing, missing))

    contract_file = root / "tests" / "contract-tests.yaml"
    if contract_file.exists():
        for test in (load(contract_file) or {}).get("tests", []):
            payload_path = root / test["payload"]
            schema_path = root / test["schema"]
            details = []
            if not payload_path.exists() or not schema_path.exists():
                details.append("payload or schema missing")
            else:
                details.extend(validate_schema(load(payload_path), load(schema_path)))
            results.append(result(f"contract:{test['name']}", not details, details))

    golden_file = root / "tests" / "golden-responses.yaml"
    applications = set()
    if golden_file.exists():
        for test in (load(golden_file) or {}).get("tests", []):
            payload = load(root / test["response"])
            details = []
            forbidden = FORBIDDEN_KEYS.intersection(set(nested_keys(payload)))
            if forbidden:
                details.append(f"forbidden ownership keys: {sorted(forbidden)}")
            for path, expected in test.get("assert_equals", {}).items():
                value = payload
                for part in path.split("."):
                    value = value.get(part) if isinstance(value, dict) else None
                if value != expected:
                    details.append(f"{path}: expected {expected!r}, got {value!r}")
            app = test.get("application")
            if app:
                applications.add(app)
            results.append(result(f"golden:{test['name']}", not details, details))
    results.append(result(
        "cross-application-contract",
        len(applications) >= 2,
        [] if len(applications) >= 2 else ["golden tests must cover at least two distinct applications"],
    ))

    permission_file = root / "tests" / "permission-tests.yaml"
    if permission_file.exists():
        for test in (load(permission_file) or {}).get("tests", []):
            payload = load(root / test["response"])
            encoded = json.dumps(payload, ensure_ascii=False)
            leaked = [token for token in test.get("must_not_contain", []) if token in encoded]
            results.append(result(f"permission:{test['name']}", not leaked, [f"leaked token: {x}" for x in leaked]))

    passed = all(item["passed"] for item in results)
    report = {"integration": root.name, "passed": passed, "tests": results}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 知识服务集成试跑报告", "", f"结论：{'通过' if passed else '未通过'}", "", "| 测试 | 结果 | 详情 |", "|---|---|---|"]
    for item in results:
        lines.append(f"| {item['name']} | {'通过' if item['passed'] else '失败'} | {'；'.join(item['details'])} |")
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "total": len(results), "failed": sum(not x['passed'] for x in results)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run generic deterministic validation rules against a read-only snapshot."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


def value_at(obj: dict, path: str):
    value = obj
    for part in path.split(".") if path else []:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def applies(rule: dict, obj: dict) -> bool:
    expected = rule.get("object_type")
    return not expected or expected == "*" or obj.get("type") == expected


def finding(rule: dict, obj: dict, message: str, evidence=None) -> dict:
    return {
        "finding_id": f"F-{rule['id']}-{obj.get('id', 'unknown')}",
        "rule_id": rule["id"],
        "object_id": obj.get("id"),
        "object_type": obj.get("type"),
        "severity": rule.get("severity", "warning"),
        "message": message,
        "evidence": evidence or [],
        "repair_advice": rule.get("repair_advice", "请由业务责任人在上层应用中核验并处理"),
        "decision_owner": "external_business_owner",
    }


def run_rule(rule: dict, obj: dict, snapshot: dict) -> list[dict]:
    kind = rule.get("type")
    path = rule.get("path", "")
    value = value_at(obj, path)
    out = []
    if kind == "required" and (value is None or value == "" or value == []):
        out.append(finding(rule, obj, f"必填字段缺失：{path}"))
    elif kind == "enum" and value is not None and value not in rule.get("allowed", []):
        out.append(finding(rule, obj, f"字段 {path} 的值不在允许范围"))
    elif kind == "regex" and value is not None and not re.search(rule.get("pattern", ".*"), str(value)):
        out.append(finding(rule, obj, f"字段 {path} 不符合格式要求"))
    elif kind == "evidence_required":
        mappings = snapshot.get("evidence_mappings", [])
        refs = [m for m in mappings if m.get("object_id") == obj.get("id") and (not path or m.get("field") == path)]
        if not refs or not any(m.get("evidence_refs") for m in refs):
            out.append(finding(rule, obj, f"字段 {path or '*'} 缺少证据映射"))
    elif kind == "relation_exists":
        direction = rule.get("direction", "out")
        relation = rule.get("relation")
        relations = snapshot.get("relations", [])
        if direction == "out":
            matches = [r for r in relations if r.get("source") == obj.get("id") and (not relation or r.get("type") == relation)]
        else:
            matches = [r for r in relations if r.get("target") == obj.get("id") and (not relation or r.get("type") == relation)]
        if not matches:
            out.append(finding(rule, obj, f"缺少关系：{direction}/{relation or '*'}"))
    elif kind == "semantic_review":
        out.append(finding(rule, obj, f"需要语义模型或人工审查：{rule.get('prompt', path)}"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    config = yaml.safe_load(args.rules.read_text(encoding="utf-8")) or {}
    findings = []
    for rule in config.get("rules", []):
        if not rule.get("id"):
            raise SystemExit("every rule needs id")
        for obj in snapshot.get("objects", []):
            if applies(rule, obj):
                findings.extend(run_rule(rule, obj, snapshot))

    # Generic duplicate identifiers are always invalid.
    seen = set()
    for obj in snapshot.get("objects", []):
        oid = obj.get("id")
        if oid in seen:
            findings.append({
                "finding_id": f"F-SYS-DUPLICATE-{oid}", "rule_id": "SYS-DUPLICATE-ID",
                "object_id": oid, "object_type": obj.get("type"), "severity": "blocker",
                "message": "外部快照存在重复对象 ID", "evidence": [],
                "repair_advice": "请在上层应用中修复对象标识", "decision_owner": "external_business_owner",
            })
        seen.add(oid)

    report = {
        "request_id": snapshot.get("request_id"),
        "correlation_id": snapshot.get("correlation_id"),
        "business_version": snapshot.get("business_version"),
        "rule_set_version": config.get("version", "unknown"),
        "read_only": True,
        "summary": {
            "blocker": sum(1 for f in findings if f["severity"] == "blocker"),
            "warning": sum(1 for f in findings if f["severity"] == "warning"),
            "suggestion": sum(1 for f in findings if f["severity"] == "suggestion"),
        },
        "findings": findings,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 1 if report["summary"]["blocker"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

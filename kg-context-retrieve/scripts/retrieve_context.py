#!/usr/bin/env python3
"""Deterministic trust-aware lexical retrieval for local skill trials."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path


ROLE_WEIGHT = {
    "有效依据": 7.0,
    "上位约束": 6.0,
    "现状事实": 5.0,
    "历史材料": 4.0,
    "实践经验": 3.0,
    "方法规范": 2.0,
    "模型建议": 1.0,
    "待确认": 0.0,
}

# 适用范围值命中任一项即视为对请求上下文适用
UNIVERSAL_SCOPES = {"全国", "通用", "未知"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def grams(text: str) -> set[str]:
    clean = re.sub(r"\s+", "", text.lower())
    latin = set(re.findall(r"[a-z0-9_\-]+", clean))
    chinese = {clean[i : i + 2] for i in range(max(0, len(clean) - 1))}
    return latin | chinese | set(clean)


def lexical_score(query: str, text: str) -> float:
    q = grams(query)
    if not q:
        return 0.0
    overlap = q.intersection(grams(text))
    return len(overlap) / len(q)


def date_active(item: dict, at_time: str) -> bool:
    if not at_time:
        return True
    try:
        point = dt.date.fromisoformat(at_time[:10])
    except ValueError:
        return True
    for key, lower in (("valid_from", True), ("valid_to", False)):
        raw = item.get(key)
        if not raw or raw in {"未知", "长期", "none", None}:
            continue
        try:
            value = dt.date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if lower and point < value:
            return False
        if not lower and point > value:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    items = load_jsonl(args.index)
    context = request.get("caller_context", {})
    allowed = set(context.get("allowed_access_scopes", []))
    region = context.get("region")
    at_time = context.get("at_time", "")
    query = request.get("query", "")
    top_k = int(request.get("top_k", 10))

    required = ("request_id", "correlation_id", "caller", "query", "caller_context")
    missing = [key for key in required if key not in request]
    if missing:
        raise SystemExit(f"missing request fields: {missing}")
    if not allowed:
        raise SystemExit("caller_context.allowed_access_scopes is required")

    filtered = {"permission": 0, "time": 0, "low_relevance": 0}
    ranked = []
    for item in items:
        if item.get("access_scope", "未知") not in allowed:
            filtered["permission"] += 1
            continue
        if not date_active(item, at_time):
            filtered["time"] += 1
            continue
        role = item.get("knowledge_role", "待确认")
        item_region = item.get("region", "未知")
        # 分区按请求上下文×知识适用范围计算：适用命中/跨域参考；跨域项不过滤，只降入参考分区
        applicable = not region or item_region == region or item_region in UNIVERSAL_SCOPES
        score = lexical_score(query, f"{item.get('document_title', '')} {item.get('content', '')}")
        if score <= 0:
            filtered["low_relevance"] += 1
            continue
        score += ROLE_WEIGHT.get(role, 0) / 10.0
        if region and item_region == region:
            score += 0.5
        ranked.append((score, applicable, item))

    ranked.sort(key=lambda entry: (-entry[0], entry[2].get("evidence_id", "")))
    selected = []
    for score, applicable, item in ranked[:top_k]:
        selected.append({
            "evidence_id": item.get("evidence_id"),
            "content": item.get("content"),
            "source_locator": item.get("source_locator"),
            "knowledge_role": item.get("knowledge_role"),
            "region": item.get("region"),
            "valid_from": item.get("valid_from"),
            "valid_to": item.get("valid_to"),
            "access_scope": item.get("access_scope"),
            "partition": "适用命中" if applicable else "跨域参考",
            "score": round(score, 4),
        })

    buckets = {"valid_evidence": [], "upper_constraints": [], "current_facts": [], "practice_experience": [], "methods": [], "other": [], "cross_domain_reference": []}
    mapping = {
        "有效依据": "valid_evidence",
        "上位约束": "upper_constraints",
        "现状事实": "current_facts",
        "实践经验": "practice_experience",
        "方法规范": "methods",
    }
    for item in selected:
        if item["partition"] == "跨域参考":
            buckets["cross_domain_reference"].append(item)
        else:
            buckets[mapping.get(item["knowledge_role"], "other")].append(item)

    applicable_hits = [item for item in selected if item["partition"] == "适用命中"]
    response = {
        "request_id": request["request_id"],
        "correlation_id": request["correlation_id"],
        "status": "ok" if applicable_hits else "insufficient_evidence",
        "knowledge_version": request.get("knowledge_version", "current"),
        "external_object_id": request.get("external_object_id"),
        "evidence": buckets,
        "conflicts": [],
        "gaps": [] if applicable_hits else ["没有在权限、时效和查询条件内找到适用命中的证据；跨域参考不得填平缺口"],
        "trace": {"index_count": len(items), "selected_count": len(selected), "applicable_count": len(applicable_hits), "filtered": filtered},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(response["trace"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

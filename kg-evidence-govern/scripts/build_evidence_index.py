#!/usr/bin/env python3
"""Build paragraph-level evidence cards from parsed Markdown documents."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


ANCHOR_RE = re.compile(r"^\[p(\d{3,})\]\s*(.*)$")


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
    return meta, parts[2]


def paragraphs(body: str):
    current_anchor = None
    current_lines: list[str] = []
    for raw in body.splitlines():
        match = ANCHOR_RE.match(raw.strip())
        if match:
            if current_anchor and any(x.strip() for x in current_lines):
                yield current_anchor, "\n".join(current_lines).strip()
            current_anchor = f"p{match.group(1)}"
            current_lines = [match.group(2)] if match.group(2) else []
        elif current_anchor:
            current_lines.append(raw)
    if current_anchor and any(x.strip() for x in current_lines):
        yield current_anchor, "\n".join(current_lines).strip()


def infer_role(meta: dict[str, str]) -> str:
    explicit = meta.get("知识角色") or meta.get("证据角色")
    if explicit:
        return explicit
    doc_type = (meta.get("文档类型") or "").lower()
    if any(k in doc_type for k in ("方法", "规范", "指南")):
        return "方法规范"
    if any(k in doc_type for k in ("调研", "访谈", "纪要")):
        return "现状事实"
    return "待确认"


def make_card(path: Path, meta: dict[str, str], anchor: str, content: str) -> dict:
    doc_id = meta.get("编号") or path.stem
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    role = infer_role(meta)
    return {
        "evidence_id": f"EV-{doc_id}-{anchor}",
        "document_id": doc_id,
        "document_title": meta.get("标题", path.stem),
        "document_version": meta.get("内容哈希") or digest,
        "content": content,
        "content_hash": digest,
        "source_locator": {
            "type": "paragraph",
            "anchor": f"{doc_id}#{anchor}",
            "source_file": meta.get("源文件", "未知"),
        },
        "knowledge_role": role,
        "authority_level": meta.get("来源权威级别", "待确认"),
        "region": meta.get("地区", "未知"),
        "organization": meta.get("机构") or meta.get("发布机构", "未知"),
        "valid_from": meta.get("生效时间", "未知"),
        "valid_to": meta.get("失效时间", "未知"),
        "access_scope": meta.get("访问范围", "未知"),
        "classification": meta.get("密级", "未知"),
        "generation_method": "source_extraction",
        "confidence": "high" if role != "待确认" else "pending",
        "status": "candidate" if role == "待确认" else "governed",
    }


def main(workspace: Path) -> int:
    parsed = workspace / "10-解析文档"
    output = workspace / "50-知识资产" / "_证据"
    output.mkdir(parents=True, exist_ok=True)
    cards: list[dict] = []
    for path in sorted(parsed.rglob("*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        for anchor, content in paragraphs(body):
            cards.append(make_card(path, meta, anchor, content))

    jsonl = output / "证据卡.jsonl"
    jsonl.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cards), encoding="utf-8")
    roles = Counter(x["knowledge_role"] for x in cards)
    pending = [x for x in cards if x["status"] == "candidate" or x["access_scope"] == "未知"]
    lines = ["# 证据索引", "", f"共 {len(cards)} 条证据卡。", "", "| 知识角色 | 数量 |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in sorted(roles.items()))
    lines.extend(["", f"待确认或权限未知：{len(pending)} 条。", ""])
    (output / "证据索引.md").write_text("\n".join(lines), encoding="utf-8")
    gaps = ["# 冲突与缺口", ""]
    gaps.extend(f"- {x['evidence_id']}：知识角色={x['knowledge_role']}，访问范围={x['access_scope']}" for x in pending)
    (output / "冲突与缺口.md").write_text("\n".join(gaps) + "\n", encoding="utf-8")
    print(json.dumps({"cards": len(cards), "pending": len(pending), "output": str(jsonl)}, ensure_ascii=False))
    return 0 if cards else 2


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_evidence_index.py <workspace>")
    raise SystemExit(main(Path(sys.argv[1])))

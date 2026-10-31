# -*- coding: utf-8 -*-
"""从已确认词表和文档级打标结果生成候选知识服务单元。"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def load_config(ws: Path) -> dict:
    path = ws / "治理参数.json"
    if not path.exists():
        raise RuntimeError(f"缺少工作区配置: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_labels(domain: dict) -> list[dict]:
    output = []
    for item in domain.get("labels", []):
        output.append({"name": item, "role": "primary"} if isinstance(item, str) else item)
    return [item for item in output if item.get("name")]


def source_code(doc_id: str) -> str:
    return doc_id.rsplit("-", 1)[0] if "-" in doc_id else doc_id


def read_tag_rows(ws: Path) -> list[dict]:
    path = ws / "20-打标结果" / "文档级打标.md"
    if not path.exists():
        raise RuntimeError(f"缺少文档级打标结果: {path}")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and re.fullmatch(r"[A-Z][A-Z0-9]{1,15}-\d{3}", cells[0]):
            rows.append({"id": cells[0], "domain": cells[2], "labels": cells[3]})
    return rows


def main(ws: Path) -> None:
    config = load_config(ws)
    domains = (config.get("tagging") or {}).get("domains") or []
    if not domains:
        raise RuntimeError("治理参数.json/tagging/domains 为空")
    versions = config.get("applicability_versions") or [{"code": "ALL", "name": "全部来源", "source_codes": []}]
    common = set(config.get("common_knowledge_labels") or [])
    rows = read_tag_rows(ws)
    out_dir = ws / "30-业务图与场景"
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 候选知识服务单元清单", "",
        "> 候选项由工作区已确认词表和文档级打标结果生成；业务边界、编码和治理方式仍需人工确认。", "",
        "| 动作 | 含义 |", "|---|---|",
        "| 采纳 | 分配正式编码并进入服务单元目录 |",
        "| 合并 | 并入其他服务单元并记录去向 |",
        "| 否决 | 归入共性知识、标签维度或明确不治理 |",
        "| 改名 | 修正名称后采纳 |", "",
    ]
    total = 0
    for domain_index, domain in enumerate(domains, 1):
        domain_name = str(domain.get("name") or f"业务域{domain_index}")
        domain_code = re.sub(r"[^A-Z0-9]", "", str(domain.get("code", "")).upper()) or f"D{domain_index:02d}"
        labels = normalize_labels(domain)
        lines.extend(["---", "", f"## {domain_name}（{domain_code}）", ""])
        headers = ["候选编码", "候选名称", *[str(item.get("name") or item.get("code")) for item in versions], "建议", "归宿"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for index, label in enumerate(labels, 1):
            name = str(label["name"])
            counts = []
            matched_total = 0
            for version in versions:
                allowed = set(version.get("source_codes") or [])
                count = sum(
                    1 for row in rows
                    if name in re.split(r"[；;,]", row["labels"])
                    and (not allowed or source_code(row["id"]) in allowed)
                )
                counts.append(str(count))
                matched_total += count
            role = label.get("role", "primary")
            if name in common or role == "common":
                action, destination = "否决", "共性知识层"
            elif role == "secondary":
                action, destination = "待确认合并", str(label.get("merge_to") or "待指定")
            elif matched_total == 0:
                action, destination = "待确认", "无命中文档"
            else:
                action, destination = "建议采纳", "独立服务单元"
            candidate = f"{domain_code}-{index:02d}"
            lines.append("| " + " | ".join([candidate, name, *counts, action, destination]) + " |")
            total += 1
        lines.append("")

    target = out_dir / "候选单元场景清单.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"候选知识服务单元已生成: {total} 个，输出 {target}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python gen_scenarios.py <工作区目录>")
        raise SystemExit(1)
    main(Path(sys.argv[1]))

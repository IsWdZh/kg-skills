# -*- coding: utf-8 -*-
"""配置驱动的多维打标脚本。

行业、地区、来源和主题词表必须来自<工作区>/治理参数.json的tagging节点，
核心脚本不提供任何领域默认值。
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def load_config(ws: Path) -> tuple[dict, Path]:
    path = ws / "治理参数.json"
    if not path.exists():
        raise RuntimeError(f"缺少工作区配置: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    tagging = data.get("tagging") or {}
    if not tagging.get("domains"):
        raise RuntimeError("治理参数.json/tagging/domains 为空；必须先确认词表再打标")
    return tagging, path


def parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, parts[2]


def normalize_labels(domain: dict) -> list[dict]:
    output = []
    for item in domain.get("labels", []):
        if isinstance(item, str):
            output.append({"name": item, "keywords": [item]})
        else:
            name = str(item.get("name", "")).strip()
            if name:
                output.append({"name": name, "keywords": item.get("keywords") or [name]})
    return output


def keyword_score(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword and keyword in text)


def classify(text: str, domains: list[dict]) -> tuple[list[str], list[str], str]:
    domain_hits = []
    label_hits = []
    best_score = 0
    for domain in domains:
        name = str(domain.get("name", "")).strip()
        score = keyword_score(text, domain.get("keywords", []))
        labels = normalize_labels(domain)
        matched_labels = [item["name"] for item in labels if keyword_score(text, item["keywords"])]
        if score or matched_labels:
            domain_hits.append(name)
            label_hits.extend(matched_labels)
            best_score = max(best_score, score + len(matched_labels))
    confidence = "高" if best_score >= 3 else ("中" if best_score >= 1 else "低")
    return list(dict.fromkeys(domain_hits)), list(dict.fromkeys(label_hits)), confidence


def detect_genre(title: str, genres: list[dict]) -> str:
    for item in genres:
        name = str(item.get("name", "")).strip()
        patterns = item.get("patterns") or item.get("keywords") or []
        if any(re.search(pattern, title) for pattern in patterns):
            return name
    return "未分类"


def time_status(meta: dict) -> str:
    relation = meta.get("版本关系", "")
    if relation:
        return relation
    if meta.get("失效时间") not in {None, "", "未知"}:
        return "已失效或待核验"
    return "时效待确认"


def write_vocabulary(out_dir: Path, tagging: dict, config_path: Path) -> None:
    lines = ["# 词表与标签体系", "", f"生成日期：{date.today().isoformat()}", f"配置来源：`{config_path.name}`", ""]
    lines.extend(["## 来源层级", ""])
    for code, name in (tagging.get("source_levels") or {}).items():
        lines.append(f"- **{code}** → {name}")
    lines.extend(["", "## 业务域与内容标签", ""])
    for domain in tagging["domains"]:
        labels = [item["name"] for item in normalize_labels(domain)]
        lines.extend([
            f"### {domain.get('name', '未命名业务域')}", "",
            f"- 业务域码：{domain.get('code', '未配置')}",
            f"- 关键词：{'、'.join(domain.get('keywords', [])) or '未配置'}",
            f"- 内容标签：{'、'.join(labels) or '未配置'}", "",
        ])
    lines.extend(["## 地区维度", ""])
    regions = tagging.get("regions") or []
    lines.extend(f"- {region}" for region in regions)
    lines.extend(["", "## 打标规则", "", "- 高：标题与正文存在多个词表命中。", "- 中：存在单一词表命中，进入待确认清单。", "- 低：没有词表命中，不得自动创建新标签。", ""])
    (out_dir / "词表与标签体系.md").write_text("\n".join(lines), encoding="utf-8")


def main(ws: Path) -> None:
    tagging, config_path = load_config(ws)
    parsed_root = ws / "10-解析文档"
    out_dir = ws / "20-打标结果"
    paragraph_dir = out_dir / "段落级打标"
    paragraph_dir.mkdir(parents=True, exist_ok=True)
    write_vocabulary(out_dir, tagging, config_path)

    results = []
    pending = []
    for path in sorted(parsed_root.rglob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(raw)
        doc_id = meta.get("编号") or path.stem
        title = meta.get("标题") or path.stem
        domains, labels, confidence = classify(f"{title}\n{body}", tagging["domains"])
        genre = detect_genre(title, tagging.get("genres") or [])
        region = meta.get("地区", "未知") or "未知"
        results.append((doc_id, title, "；".join(domains) or "待确认", "；".join(labels) or "待确认", genre, confidence, meta.get("发布时间", "未知"), region, time_status(meta)))
        if confidence != "高" or not domains:
            pending.append((doc_id, title, "业务域/标签", "词表命中不足"))

        paragraph_lines = [f"# 段落级打标：{doc_id}", "", "| 锚点 | 业务域 | 内容标签 | 置信度 |", "|---|---|---|---|"]
        sections = re.split(r"(?m)(?=^\[p\d{3}\])", body)
        for section in sections:
            anchor = re.match(r"^\[(p\d{3})\]", section)
            if not anchor:
                continue
            p_domains, p_labels, p_confidence = classify(section, tagging["domains"])
            paragraph_lines.append(f"| {doc_id}#{anchor.group(1)} | {'；'.join(p_domains) or '待确认'} | {'；'.join(p_labels) or '待确认'} | {p_confidence} |")
        (paragraph_dir / f"{doc_id}.md").write_text("\n".join(paragraph_lines) + "\n", encoding="utf-8")

    table = ["# 文档级打标结果", "", "| 编号 | 标题 | 业务域 | 内容标签 | 体裁 | 置信度 | 发布时间 | 地区 | 时间属性 |", "|---|---|---|---|---|---|---|---|---|"]
    table.extend("| " + " | ".join(row) + " |" for row in results)
    (out_dir / "文档级打标.md").write_text("\n".join(table) + "\n", encoding="utf-8")

    review = ["# 待人工确认清单", "", "| 编号 | 标题 | 待确认维度 | 原因 |", "|---|---|---|---|"]
    review.extend("| " + " | ".join(row) + " |" for row in pending)
    (out_dir / "待人工确认清单.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    print(f"打标完成: {len(results)} 份，待确认 {len(pending)} 份")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python tag_docs.py <工作区目录>")
        raise SystemExit(1)
    main(Path(sys.argv[1]))

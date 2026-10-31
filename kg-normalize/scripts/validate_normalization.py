#!/usr/bin/env python3
"""校验多模态归一准入状态（layout_version 2：条件校验）。

恒有项：原件快照、文本副本、清单登记、结构化对象（stub 亦可）。
条件项：visual_required=true 时必须有视觉资产；识别链路状态必须有质检报告。
兼容 layout_version 1 工作区（绝对路径、无 required 字段时退回旧规则）。
"""

import json
import os
import re
import sys
from pathlib import Path

PASS_STATES = {"归一完成", "已OCR-质检通过", "已视觉复核", "已人工复核"}
REVIEW_STATES = {"已视觉复核", "已人工复核"}
RECOGNITION_STATES = {"待视觉转写", "已OCR-质检通过", "已OCR-待视觉复核", "已视觉复核", "已人工复核", "结构识别失败"}


def resolve(ws: Path, value: str) -> Path:
    return Path(value) if os.path.isabs(value) else ws / value


def front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    head = text.split("---", 2)[1]
    result = {}
    for line in head.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def main(workspace: Path) -> int:
    markdown_root = workspace / "00-原始MD"
    quality_root = workspace / "00-识别质检"
    rows = []
    manifest = {}
    manifest_path = workspace / "00-多模态清单" / "多模态清单.jsonl"
    manifest_errors = []
    if not manifest_path.exists():
        manifest_errors.append("缺少多模态清单")
    else:
        for number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                doc_id = item["document_id"]
                if doc_id in manifest:
                    manifest_errors.append(f"多模态清单文档ID重复: {doc_id}")
                manifest[doc_id] = item
            except Exception as exc:
                manifest_errors.append(f"多模态清单第{number}行无法解析: {type(exc).__name__}")
    markdown_ids = set()
    for path in sorted(markdown_root.rglob("*.md")):
        if path.name == "转换清单.md" or "_图片" in path.parts:
            continue
        meta = front_matter(path)
        doc_id = meta.get("编号") or path.stem
        markdown_ids.add(doc_id)
        status = meta.get("归一状态", "缺失")
        problems = []
        mm = manifest.get(doc_id)
        if not mm:
            problems.append("文本副本未登记到多模态清单")
        else:
            # 恒有项：原件快照与结构化对象
            for field, label in (("original_path", "原件快照"), ("structured_path", "结构化对象")):
                target = mm.get(field)
                if not target or not resolve(workspace, target).exists():
                    problems.append(f"缺少{label}")
            # 条件项：应有视觉资产而缺失（layout_version 1 无该字段时跳过）
            if mm.get("visual_required"):
                visual = mm.get("visual_path")
                visual_dir = resolve(workspace, visual) if visual else None
                if not visual_dir or not visual_dir.exists() or not any(visual_dir.iterdir()):
                    problems.append("visual_required=true 但缺少视觉资产")
            elif mm.get("visual_required") is False and not mm.get("visual_path") and not mm.get("visual_skip_reason"):
                problems.append("视觉资产跳过但未登记 visual_skip_reason")
            manifest_status = mm.get("normalization_status")
            if manifest_status and manifest_status != status:
                problems.append(f"清单状态与MD状态不一致: {manifest_status}/{status}")
            if mm.get("errors"):
                problems.append("清单登记生成错误: " + "；".join(str(x) for x in mm["errors"]))
        report_path = quality_root / f"{doc_id}.json"
        report = {}
        # 条件项：识别链路状态必须有质检报告；纯文本（归一完成）无需报告
        if status in RECOGNITION_STATES:
            if not report_path.exists():
                problems.append("识别链路状态缺少识别质检报告")
            else:
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    problems.append(f"质检报告无法解析: {type(exc).__name__}")
        if status not in PASS_STATES:
            problems.append(f"阻断状态: {status}")
        if report and report.get("status") != status:
            problems.append(f"MD状态与质检报告不一致: {status}/{report.get('status')}")
        if status in REVIEW_STATES:
            review = report.get("review") or {}
            if not review.get("method") or not review.get("reviewed_at"):
                problems.append("复核状态缺少复核方式或时间")
            if review.get("unresolved_items"):
                problems.append("仍有未解决识别差异")
        if status == "已OCR-质检通过" and report.get("object_types"):
            problems.append("复杂对象不得仅凭OCR自动通过")
        body = path.read_text(encoding="utf-8")
        content_length = len(re.sub(r"\s+", "", body.split("---", 2)[-1]))
        minimum = 1 if meta.get("原始格式") in {"md", "markdown"} else 20
        if content_length < minimum:
            problems.append("文本副本为空或过短")
        rows.append({"document_id": doc_id, "status": status, "passed": not problems, "problems": problems})

    for doc_id in sorted(set(manifest) - markdown_ids):
        rows.append({"document_id": doc_id, "status": manifest[doc_id].get("normalization_status", "缺失"), "passed": False, "problems": ["多模态清单已有登记，但缺少文本副本"]})
    for problem in manifest_errors:
        rows.append({"document_id": "_MANIFEST_", "status": "阻断", "passed": False, "problems": [problem]})

    output = quality_root / "归一验收报告.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"passed": bool(rows) and all(row["passed"] for row in rows), "documents": rows}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 归一验收报告", "", f"结论：{'通过' if result['passed'] else '阻断'}", "", "| 文档 | 状态 | 结果 | 问题 |", "|---|---|---|---|"]
    lines.extend(f"| {row['document_id']} | {row['status']} | {'通过' if row['passed'] else '阻断'} | {'；'.join(row['problems'])} |" for row in rows)
    (quality_root / "归一验收报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "documents": len(rows), "blocked": sum(not row["passed"] for row in rows)}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法: python validate_normalization.py <本次工作区目录>")
    raise SystemExit(main(Path(sys.argv[1])))

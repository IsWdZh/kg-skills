#!/usr/bin/env python3
"""登记已实际完成的视觉/人工复核；不执行识别，也不替代正文修正。"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ALLOWED = {"已视觉复核", "已人工复核", "结构识别失败"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("document_id")
    parser.add_argument("--status", choices=sorted(ALLOWED), required=True)
    parser.add_argument("--review-file", type=Path, required=True)
    parser.add_argument("--reviewer", default="agent")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    if not args.review_file.exists():
        raise SystemExit(f"复核结果不存在: {args.review_file}")
    review_data = json.loads(args.review_file.read_text(encoding="utf-8"))
    unresolved = review_data.get("unresolved_items") or []
    if args.status != "结构识别失败" and unresolved:
        raise SystemExit("仍有未解决项，不能登记为复核通过")

    report_path = args.workspace / "00-识别质检" / f"{args.document_id}.json"
    if not report_path.exists():
        raise SystemExit(f"识别质检报告不存在: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    corrected = str(review_data.get("corrected_markdown") or "").strip()
    if args.status != "结构识别失败" and not corrected:
        raise SystemExit("复核结果缺少 corrected_markdown，不能登记为复核通过")
    complex_types = set(report.get("object_types") or [])
    if args.status != "结构识别失败" and complex_types.intersection({"table_or_multicolumn", "flow_or_diagram"}) and not review_data.get("structure"):
        raise SystemExit("复杂表格或流程图复核结果缺少 structure")

    matches = list((args.workspace / "00-原始MD").rglob(f"{args.document_id}.md"))
    if len(matches) != 1:
        raise SystemExit(f"无法唯一定位文本副本: {args.document_id}")
    path = matches[0]
    text = path.read_text(encoding="utf-8")
    if not re.search(r"^归一状态:", text, re.MULTILINE):
        raise SystemExit("文本副本缺少归一状态")

    # 复核文件引用存工作区相对路径（不在工作区内则只存文件名），保持工作区可搬迁
    try:
        review_ref = args.review_file.resolve().relative_to(args.workspace.resolve()).as_posix()
    except ValueError:
        review_ref = args.review_file.name
    report["status"] = args.status
    report["review"] = {
        "method": "large_model_vision" if args.status == "已视觉复核" else "human_review",
        "reviewer": args.reviewer,
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notes": args.notes,
        "review_file": review_ref,
        "unresolved_items": unresolved,
        "structure": review_data.get("structure"),
    }
    text = re.sub(r"^归一状态:\s*.*$", f"归一状态: {args.status}", text, count=1, flags=re.MULTILINE)
    if corrected:
        heading = re.search(r"(?m)^# .+$", text)
        if not heading:
            raise SystemExit("文本副本缺少一级标题")
        text = text[:heading.end()] + f"\n\n> 已完成复核，复核记录：{args.review_file.name}\n\n" + corrected + "\n"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    # 同步多模态清单中的归一状态，保持清单、MD、质检报告三处一致
    manifest_path = args.workspace / "00-多模态清单" / "多模态清单.jsonl"
    if manifest_path.exists():
        lines = []
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("document_id") == args.document_id:
                row["normalization_status"] = args.status
                row["status"] = "complete" if args.status in {"已视觉复核", "已人工复核"} else "blocked"
            lines.append(json.dumps(row, ensure_ascii=False))
        manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"document_id": args.document_id, "status": args.status, "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

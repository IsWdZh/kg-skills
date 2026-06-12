# -*- coding: utf-8 -*-
"""校验知识资产、发布包与原文锚点的一致性。

用法: python check_links.py <工作区目录>
"""

import re
import sys
from pathlib import Path
from urllib.parse import unquote


sys.stdout.reconfigure(encoding="utf-8")

ANCHOR_RE = re.compile(r"([A-Z][A-Z0-9]{1,7}-\d{3})#p(\d{3})(?:-p(\d{3}))?")
KC_RE = re.compile(r"KC-(?:[A-Z0-9]+-)+\d{3}(?:/\d{3})*")
PLACEHOLDER_RE = re.compile(r"(?:KC|QA|RULE|R|E)-?(?:…|\.\.\.)")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def expand_kc_reference(value: str) -> list[str]:
    """Expand KC-...-001/002 into two complete IDs."""
    parts = value.split("/")
    first = parts[0]
    if len(parts) == 1:
        return [first]
    prefix = first[:-3]
    return [first, *[prefix + suffix for suffix in parts[1:]]]


def line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def main(ws: Path) -> None:
    anchors: set[str] = set()
    for file in (ws / "10-解析文档").rglob("*.md"):
        doc_id = file.stem
        text = file.read_text(encoding="utf-8")
        for match in re.finditer(r"^\[p(\d{3})\]", text, re.M):
            anchors.add(f"{doc_id}#p{match.group(1)}")

    chunk_ids: set[str] = set()
    asset_root = ws / "50-知识资产"
    for file in asset_root.rglob("知识块.md"):
        text = file.read_text(encoding="utf-8")
        chunk_ids.update(re.findall(r"^## (KC-[A-Z0-9-]+)", text, re.M))
    for file in asset_root.rglob("共性知识库.md"):
        text = file.read_text(encoding="utf-8")
        chunk_ids.update(re.findall(r"^## (GJJ-CK-\d+)", text, re.M))

    errors: list[str] = []
    checked_anchors = 0
    checked_kc = 0
    checked_links = 0

    markdown_files = sorted(ws.rglob("*.md"))
    for file in markdown_files:
        text = file.read_text(encoding="utf-8")
        rel = file.relative_to(ws)

        for match in PLACEHOLDER_RE.finditer(text):
            errors.append(
                f"[占位引用] {rel}:{line_number(text, match.start())}: {match.group(0)}"
            )

        for match in ANCHOR_RE.finditer(text):
            doc, start, end = match.group(1), int(match.group(2)), match.group(3)
            span = range(start, int(end) + 1) if end else [start]
            for number in span:
                checked_anchors += 1
                anchor = f"{doc}#p{number:03d}"
                if anchor not in anchors:
                    errors.append(
                        f"[锚点缺失] {rel}:{line_number(text, match.start())}: {anchor}"
                    )

        for match in KC_RE.finditer(text):
            for chunk_id in expand_kc_reference(match.group(0)):
                checked_kc += 1
                if chunk_id not in chunk_ids:
                    errors.append(
                        f"[知识块引用缺失] {rel}:{line_number(text, match.start())}: {chunk_id}"
                    )

        for match in LINK_RE.finditer(text):
            target = match.group(1).split("#", 1)[0]
            if not target or re.match(r"^(?:https?|mailto|obsidian):", target):
                continue
            checked_links += 1
            resolved = (file.parent / unquote(target)).resolve()
            if not resolved.exists():
                errors.append(
                    f"[文件链接缺失] {rel}:{line_number(text, match.start())}: {target}"
                )

        if file.name in {"知识块.md", "问答对.md", "Wiki页.md", "知识图谱.md"}:
            if not re.search(r"(?:^|[-|])\s*来源\s*[:|]", text, re.M):
                errors.append(f"[缺少来源字段] {rel}")

        if file.name in {"知识块.md", "问答对.md"}:
            for section in re.split(r"(?m)(?=^## (?:KC|QA)-)", text):
                if not re.match(r"^## (?:KC|QA)-", section):
                    continue
                heading = section.splitlines()[0]
                if not re.search(r"(?m)^- 来源\s*:", section):
                    errors.append(f"[条目缺少来源] {rel}: {heading}")

        if file.name == "知识图谱.md":
            for section in re.split(r"(?m)(?=^### RULE-)", text):
                if not section.startswith("### RULE-"):
                    continue
                heading = section.splitlines()[0]
                if not re.search(r"(?m)^- 来源\s*:", section):
                    errors.append(f"[规则缺少来源] {rel}: {heading}")

        if file.name == "Wiki页.md" and "已生成待审" in text:
            errors.append(f"[发布状态冲突] {rel}: Wiki 仍标记为已生成待审")

    print(f"有效锚点 {len(anchors)} 个；知识块 {len(chunk_ids)} 个")
    print(
        f"校验锚点引用 {checked_anchors} 处、知识块引用 {checked_kc} 处、文件链接 {checked_links} 处"
    )
    if errors:
        print(f"\n发现 {len(errors)} 个问题：")
        for error in errors:
            print(" ", error)
        raise SystemExit(1)
    print("校验通过：无失效引用、占位引用或发布状态冲突")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法: python check_links.py <工作区目录>")
    main(Path(sys.argv[1]))

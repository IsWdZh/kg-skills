# -*- coding: utf-8 -*-
"""校验知识资产、发布包与原文锚点的一致性。

用法: python check_links.py <工作区目录>
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


sys.stdout.reconfigure(encoding="utf-8")

ANCHOR_RE = re.compile(r"([A-Z][A-Z0-9]{1,7}-\d{3})#p(\d{3})(?:-p(\d{3}))?")
KC_RE = re.compile(r"KC-(?:[A-Z0-9]+-)+\d{3}(?:/\d{3})*")
PLACEHOLDER_RE = re.compile(r"(?:KC|QA|RULE|R|E)-?(?:…|\.\.\.)")
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SRCMAP_ROW_RE = re.compile(r"^\|\s*([A-Z][A-Z0-9]{1,7}-\d{3})\s*\|", re.M)
CK_REF_RE = re.compile(r"CK-[A-Z0-9][A-Z0-9_-]*-\d{3}")


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


def build_ck_sources(ws: Path) -> dict[str, set[str]]:
    """共性知识编号 → 其底层源文档编号集合（取自共性知识条目的来源锚点）。"""
    ck_sources: dict[str, set[str]] = {}
    for file in (ws / "50-知识资产").rglob("共性知识库.md"):
        text = file.read_text(encoding="utf-8")
        for section in re.split(r"(?m)(?=^## CK-[A-Z0-9][A-Z0-9_-]*-\d{3})", text):
            head = re.match(r"^## (CK-[A-Z0-9][A-Z0-9_-]*-\d{3})", section)
            if not head:
                continue
            docs = {m.group(1) for m in ANCHOR_RE.finditer(section)}
            ck_sources.setdefault(head.group(1), set()).update(docs)
    return ck_sources


def check_package_source_maps(
    ws: Path, ck_sources: dict[str, set[str]]
) -> tuple[list[str], list[str]]:
    """校验每个知识包的「来源文档」映射表是否覆盖全部被引用文档编号。

    含直接锚点引用与所挂接共性知识（CK-*）的底层源文档。
    旧格式包（无映射表）只提示待升级，不计为错误。
    """
    errors: list[str] = []
    notices: list[str] = []
    pkg_root = ws / "60-知识包"
    if not pkg_root.exists():
        return errors, notices

    enabled = legacy = 0
    for manifest in sorted(pkg_root.rglob("包清单.md")):
        manifest_text = manifest.read_text(encoding="utf-8")
        rel = manifest.relative_to(ws)
        mapping = set(SRCMAP_ROW_RE.findall(manifest_text))

        referenced: set[str] = set()
        ck_refs = set(CK_REF_RE.findall(manifest_text))
        for asset in (manifest.parent / "资产").rglob("*.md"):
            asset_text = asset.read_text(encoding="utf-8")
            referenced.update(m.group(1) for m in ANCHOR_RE.finditer(asset_text))
            ck_refs.update(CK_REF_RE.findall(asset_text))
        for ck in ck_refs:
            referenced.update(ck_sources.get(ck, set()))

        if not mapping:
            legacy += 1
            if referenced:
                notices.append(
                    f"[来源映射待升级] {rel}: 旧格式包未设「编号→文件名」映射表"
                    f"（引用 {len(referenced)} 个文档编号，服务端需回查台账解析文件名）"
                )
            continue

        enabled += 1
        for code in sorted(referenced - mapping):
            errors.append(
                f"[来源映射缺失] {rel}: 引用文档 {code} 未登记到「来源文档」映射表"
                "（含共性知识底层来源），服务端无法把编号还原为文件名"
            )

    notices.insert(
        0,
        f"知识包来源映射：检查 {enabled + legacy} 个包"
        f"（{enabled} 个已启用映射表，{legacy} 个旧格式待升级）",
    )
    return errors, notices


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
        chunk_ids.update(re.findall(r"^## (CK-[A-Z0-9][A-Z0-9_-]*-\d{3})", text, re.M))

    errors: list[str] = []
    checked_anchors = 0
    checked_kc = 0
    checked_links = 0

    evidence_path = asset_root / "_证据" / "证据卡.jsonl"
    if evidence_path.exists():
        for number, line in enumerate(evidence_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                card = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"[证据卡JSON错误] {evidence_path.relative_to(ws)}:{number}: {exc}")
                continue
            evidence_id = card.get("evidence_id", f"line-{number}")
            locator = card.get("source_locator") or {}
            if not locator.get("anchor") and not any(locator.get(key) for key in ("page", "cell", "image_region", "flow_node")):
                errors.append(f"[证据定位缺失] {evidence_id}")
            if locator.get("type") == "paragraph" and locator.get("anchor") not in anchors:
                errors.append(f"[证据锚点缺失] {evidence_id}: {locator.get('anchor')}")
            if card.get("knowledge_role") in {None, "", "待确认"}:
                errors.append(f"[证据角色待确认] {evidence_id}")
            if card.get("access_scope") in {None, "", "未知"}:
                errors.append(f"[证据权限待确认] {evidence_id}")

    for path in (sorted((asset_root / "_案例").rglob("案例清单.json")) if (asset_root / "_案例").exists() else []):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"[案例JSON错误] {path.relative_to(ws)}: {exc}")
            continue
        if case.get("review_status") not in {"已审核", "已发布", "已确认可沉淀"}:
            errors.append(f"[案例准入失败] {path.relative_to(ws)}: 审核状态不足")
        for unit in case.get("reuse_units", []):
            if not unit.get("evidence_refs") or not unit.get("applicable_conditions") or not unit.get("risks"):
                errors.append(f"[案例复用信息缺失] {path.relative_to(ws)}: {unit.get('unit_id', 'unknown')}")

    method_root = asset_root / "_方法规则"
    if method_root.exists():
        try:
            import yaml
        except ImportError:
            errors.append("[方法规则未校验] 缺少 PyYAML")
        else:
            forbidden = {"workflow", "stages", "transitions", "approval", "business_status", "auto_writeback"}
            for path in sorted(method_root.rglob("manifest.yaml")):
                manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                keys = set(manifest)
                if forbidden.intersection(keys):
                    errors.append(f"[方法规则越界] {path.relative_to(ws)}: 含外部业务流程字段")
                if not all(manifest.get(key) for key in ("asset_id", "asset_type", "version", "sources")):
                    errors.append(f"[方法规则字段缺失] {path.relative_to(ws)}")

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

        # 实体知识块必须含真锚点（编号#pNNN），仅"服务引导/缺口块"可豁免
        if file.name == "知识块.md":
            for section in re.split(r"(?m)(?=^## KC-)", text):
                if not section.startswith("## KC-"):
                    continue
                heading = section.splitlines()[0]
                typ_match = re.search(r"(?m)^- 类型\s*[:：]\s*(.+)$", section)
                typ = typ_match.group(1).strip() if typ_match else ""
                if "服务引导" in typ:
                    continue
                if not ANCHOR_RE.search(section):
                    errors.append(
                        f"[知识块缺锚点] {rel}: {heading}"
                        f"（类型={typ or '未标'}，实体知识块须含 编号#pNNN 来源锚点，"
                        "仅服务引导/缺口块可豁免）"
                    )

        if file.name == "知识图谱.md":
            for section in re.split(r"(?m)(?=^### RULE-)", text):
                if not section.startswith("### RULE-"):
                    continue
                heading = section.splitlines()[0]
                if not re.search(r"(?m)^- 来源\s*:", section):
                    errors.append(f"[规则缺少来源] {rel}: {heading}")

        if file.name == "Wiki页.md" and "已生成待审" in text:
            errors.append(f"[发布状态冲突] {rel}: Wiki 仍标记为已生成待审")

    ck_sources = build_ck_sources(ws)
    map_errors, map_notices = check_package_source_maps(ws, ck_sources)
    errors.extend(map_errors)

    print(f"有效锚点 {len(anchors)} 个；知识块 {len(chunk_ids)} 个")
    print(
        f"校验锚点引用 {checked_anchors} 处、知识块引用 {checked_kc} 处、文件链接 {checked_links} 处"
    )
    for notice in map_notices:
        print(notice)
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

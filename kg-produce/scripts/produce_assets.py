# -*- coding: utf-8 -*-
"""按治理配置生产可追溯的基础知识资产。

本脚本只使用工作区配置、已确认服务单元和解析文档，不内置行业词表、
地区版本或来源码。复杂推理、方法规则和案例仍由对应 Skill 治理。
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DOC_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}-\d{3}$")
SCENE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*-\d{2}$")


def load_config(ws: Path) -> dict:
    path = ws / "治理参数.json"
    if not path.exists():
        raise RuntimeError(f"缺少工作区配置: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


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


def parse_scenes(ws: Path) -> list[dict]:
    path = ws / "30-业务图与场景" / "单元场景目录.md"
    if not path.exists():
        raise RuntimeError(f"缺少已确认服务单元目录: {path}")
    scenes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and SCENE_ID_RE.fullmatch(cells[0]):
            scenes.append({
                "code": cells[0],
                "name": cells[1],
                "domain": cells[2] if len(cells) > 2 else "未配置",
                "tier": next((cell for cell in cells if cell in {"轻治理", "标准治理", "推理治理"}), "标准治理"),
            })
    if not scenes:
        raise RuntimeError("单元场景目录中没有可识别的已确认编码")
    return scenes


def label_keywords(config: dict) -> dict[str, list[str]]:
    result = {}
    for domain in (config.get("tagging") or {}).get("domains", []):
        for item in domain.get("labels", []):
            if isinstance(item, str):
                result[item] = [item]
            else:
                name = str(item.get("name", "")).strip()
                if name:
                    result[name] = item.get("keywords") or [name]
    for unit in config.get("service_units", []):
        if unit.get("name"):
            result[str(unit["name"])] = unit.get("keywords") or [str(unit["name"])]
    return result


def load_documents(ws: Path) -> list[dict]:
    docs = []
    for path in sorted((ws / "10-解析文档").rglob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(raw)
        doc_id = meta.get("编号") or path.stem
        if not DOC_ID_RE.fullmatch(doc_id):
            continue
        paragraphs = []
        for section in re.split(r"(?m)(?=^\[p\d{3}\])", body):
            match = re.match(r"^\[(p\d{3})\]\s*(.*)", section, re.S)
            if match and match.group(2).strip():
                paragraphs.append((f"{doc_id}#{match.group(1)}", match.group(2).strip()))
        docs.append({
            "id": doc_id,
            "source": doc_id.rsplit("-", 1)[0],
            "title": meta.get("标题") or path.stem,
            "region": meta.get("地区", "未知"),
            "access_scope": meta.get("访问范围", "未知"),
            "paragraphs": paragraphs,
        })
    return docs


def applicable_versions(config: dict, docs: list[dict]) -> list[dict]:
    versions = config.get("applicability_versions") or []
    if versions:
        return versions
    return [
        {"code": source, "name": source, "source_codes": [source]}
        for source in sorted({doc["source"] for doc in docs})
    ]


def forms_for_tier(tier: str) -> list[str]:
    if tier == "轻治理":
        return ["知识块"]
    if tier == "推理治理":
        return ["知识块", "Wiki", "问答对", "知识图谱"]
    return ["知识块", "Wiki", "问答对"]


def matching_paragraphs(docs: list[dict], source_codes: set[str], keywords: list[str]) -> list[tuple]:
    output = []
    for doc in docs:
        if source_codes and doc["source"] not in source_codes:
            continue
        for anchor, content in doc["paragraphs"]:
            if any(keyword and keyword in content for keyword in keywords):
                output.append((doc, anchor, content))
    return output


def write_assets(out_dir: Path, scene: dict, version: dict, matches: list[tuple], domain_code: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_code = scene["code"]
    scope = str(version["code"])
    forms = forms_for_tier(scene["tier"])
    chunks = []
    for index, (doc, anchor, content) in enumerate(matches, 1):
        chunks.append({
            "id": f"KC-{scene_code}-{scope}-{index:03d}",
            "title": f"{scene['name']}依据{index}",
            "content": content,
            "source": f"〔{doc['title']}〕{anchor}",
            "scope": version.get("name") or scope,
            "access_scope": doc["access_scope"],
        })

    kc_lines = [f"# 知识块库：{scene_code}/{scope}", "", f"> 治理档位: {scene['tier']} | 生产日期: {date.today().isoformat()}", ""]
    if not chunks:
        kc_lines.extend(["> 当前适用版本没有命中证据，必须按缺口策略降级，不得用其他版本补全。", ""])
    for chunk in chunks:
        kc_lines.extend([
            f"## {chunk['id']} {chunk['title']}", "",
            "- 类型: 依据块", f"- 适用范围: {chunk['scope']}",
            f"- 访问范围: {chunk['access_scope']}", f"- 内容: {chunk['content']}",
            f"- 来源: {chunk['source']}", "",
        ])
    (out_dir / "知识块.md").write_text("\n".join(kc_lines), encoding="utf-8")

    if "Wiki" in forms:
        wiki = [f"# Wiki：{scene['name']}（{version.get('name') or scope}）", "", "## 已核实依据", ""]
        wiki.extend(f"- {chunk['content']}（来源：{chunk['source']}）" for chunk in chunks)
        if not chunks:
            wiki.append("- 暂无已核实依据。")
        (out_dir / "Wiki.md").write_text("\n".join(wiki) + "\n", encoding="utf-8")

    if "问答对" in forms:
        qa = [f"# 问答对：{scene['name']}（{version.get('name') or scope}）", ""]
        for index, chunk in enumerate(chunks, 1):
            qa.extend([
                f"## QA-{scene_code}-{scope}-{index:03d}", "",
                f"- 标准问: 关于“{chunk['title']}”的已核实内容是什么？",
                f"- 标准答案: {chunk['content']}", f"- 来源知识块: {chunk['id']}",
                f"- 来源: {chunk['source']}", "",
            ])
        (out_dir / "问答对.md").write_text("\n".join(qa), encoding="utf-8")

    if "知识图谱" in forms:
        graph = [f"# 知识图谱：{scene['name']}（{version.get('name') or scope}）", "", "> 当前仅登记可追溯依据节点；实体关系和规则必须另行审核后补充。", ""]
        for index, chunk in enumerate(chunks, 1):
            graph.extend([f"## E{index:03d} {chunk['title']}", "", f"- 类型: 依据节点", f"- 来源知识块: {chunk['id']}", ""])
        (out_dir / "知识图谱.md").write_text("\n".join(graph), encoding="utf-8")
    return {"chunks": len(chunks), "forms": len(forms)}


def write_common_knowledge(ws: Path, config: dict, docs: list[dict], domain_code: str) -> None:
    entries = config.get("common_knowledge") or []
    if not entries:
        return
    lines = ["# 共性知识库", ""]
    for index, item in enumerate(entries, 1):
        name = str(item.get("name") or f"共性知识{index}")
        keywords = item.get("keywords") or [name]
        matches = matching_paragraphs(docs, set(item.get("source_codes") or []), keywords)
        asset_id = f"CK-{domain_code}-{index:03d}"
        lines.extend([f"## {asset_id} {name}", "", f"- 适用范围: {item.get('applicability', '跨服务单元')}"])
        if matches:
            lines.append(f"- 内容: {matches[0][2]}")
            lines.append(f"- 来源: 〔{matches[0][0]['title']}〕{matches[0][1]}")
        else:
            lines.extend(["- 内容: 待治理", "- 来源: 待补充"])
        lines.append("")
    target = ws / "50-知识资产" / "_共性知识" / "共性知识库.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")


def main(ws: Path) -> None:
    config = load_config(ws)
    domain_code = re.sub(r"[^A-Z0-9]", "", str(config.get("domain_code", "DOM")).upper()) or "DOM"
    scenes = parse_scenes(ws)
    docs = load_documents(ws)
    versions = applicable_versions(config, docs)
    keywords_by_name = label_keywords(config)
    out_root = ws / "50-知识资产"
    totals = {"units": 0, "chunks": 0}
    for scene in scenes:
        keywords = keywords_by_name.get(scene["name"], [scene["name"]])
        for version in versions:
            scope = str(version.get("code", "")).strip()
            if not scope:
                continue
            matches = matching_paragraphs(docs, set(version.get("source_codes") or []), keywords)
            result = write_assets(out_root / scene["code"] / scope, scene, version, matches, domain_code)
            totals["units"] += 1
            totals["chunks"] += result["chunks"]
    write_common_knowledge(ws, config, docs, domain_code)
    print(f"资产生产完成: {totals['units']} 个服务单元版本，{totals['chunks']} 个可追溯知识块")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python produce_assets.py <工作区目录>")
        raise SystemExit(1)
    main(Path(sys.argv[1]))

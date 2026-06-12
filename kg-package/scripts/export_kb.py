# -*- coding: utf-8 -*-
"""Export frozen Markdown knowledge packages to JSONL, SQLite, and Cypher.

Usage: python export_kb.py <workspace> [output-directory]
The Markdown governance workspace remains the source of truth. All generated
artifacts are disposable projections and are rebuilt idempotently.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote


sys.stdout.reconfigure(encoding="utf-8")

ANCHOR_RE = re.compile(r"([A-Z][A-Z0-9]{1,7}-\d{3})#p(\d{3})(?:-p(\d{3}))?")
KC_RE = re.compile(r"KC-(?:[A-Z0-9]+-)+\d{3}(?:/\d{3})*")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)\)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_front_matter(text: str) -> dict[str, str]:
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def meta_value(meta: dict[str, str], chinese: str, english: str, default: str = "") -> str:
    return meta.get(chinese, meta.get(english, default))


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_tables(text: str) -> list[list[dict[str, str]]]:
    lines = text.splitlines()
    tables: list[list[dict[str, str]]] = []
    index = 0
    while index + 1 < len(lines):
        if lines[index].lstrip().startswith("|") and re.match(
            r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$", lines[index + 1]
        ):
            headers = split_table_row(lines[index])
            index += 2
            rows: list[dict[str, str]] = []
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                values = split_table_row(lines[index])
                if len(values) == len(headers):
                    rows.append(dict(zip(headers, values)))
                index += 1
            tables.append(rows)
            continue
        index += 1
    return tables


def first_table_with(text: str, required: set[str]) -> list[dict[str, str]]:
    for table in markdown_tables(text):
        if table and required.issubset(table[0].keys()):
            return table
    return []


def section_fields(text: str, heading_pattern: str) -> list[tuple[str, str, dict[str, str]]]:
    heading_re = re.compile(heading_pattern, re.M)
    matches = list(heading_re.finditer(text))
    result: list[tuple[str, str, dict[str, str]]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        fields: dict[str, str] = {}
        for line in body.splitlines():
            field = re.match(r"^-\s*([^:：]+)[:：]\s*(.*)$", line)
            if field:
                fields[field.group(1).strip()] = field.group(2).strip()
        result.append((match.group(1), match.group(2).strip() if match.lastindex and match.lastindex >= 2 else "", fields))
    return result


def expand_kc(value: str) -> list[str]:
    values: list[str] = []
    for match in KC_RE.finditer(value):
        parts = match.group(0).split("/")
        first = parts[0]
        values.append(first)
        prefix = first[:-3]
        values.extend(prefix + suffix for suffix in parts[1:])
    return values


def anchors(value: str) -> list[str]:
    output: list[str] = []
    for match in ANCHOR_RE.finditer(value):
        start, end = int(match.group(2)), match.group(3)
        span = range(start, int(end) + 1) if end else [start]
        output.extend(f"{match.group(1)}#p{number:03d}" for number in span)
    return output


def parse_release_records(workspace: Path) -> list[dict[str, str]]:
    path = workspace / "60-知识包" / "发布记录.md"
    table = first_table_with(path.read_text(encoding="utf-8"), {"地区版本", "版本", "当前有效版本"})
    return [row for row in table if row.get("版本") == row.get("当前有效版本")]


def parse_manifest(path: Path) -> tuple[dict[str, str], dict[str, Path]]:
    text = path.read_text(encoding="utf-8")
    metadata_table = first_table_with(text, {"项", "值"})
    metadata = {row["项"]: row["值"] for row in metadata_table}
    assets: dict[str, Path] = {}
    for _label, target in LINK_RE.findall(text):
        resolved = (path.parent / unquote(target)).resolve()
        if resolved.parent.name == "资产":
            assets[resolved.stem] = resolved
    return metadata, assets


def parse_documents(workspace: Path) -> list[dict]:
    output = []
    for path in sorted((workspace / "10-解析文档").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta = parse_front_matter(text)
        output.append(
            {
                "编号": meta_value(meta, "编号", "doc_id", path.stem),
                "标题": meta_value(meta, "标题", "title"),
                "地区": meta_value(meta, "地区", "region"),
                "发布机构": meta_value(meta, "发布机构", "source_org"),
                "文档类型": meta_value(meta, "文档类型", "doc_type"),
                "发布时间": meta_value(meta, "发布时间", "publish_date", "未知"),
                "生效时间": meta_value(meta, "生效时间", "effective_date", "未知"),
                "源文件": meta_value(meta, "源文件", "source_file"),
                "来源URL": meta_value(meta, "来源URL", "source_url", "未知"),
                "权限范围": meta_value(meta, "权限范围", "access_scope", "未指定"),
                "内容哈希": meta_value(meta, "内容哈希", "content_hash"),
                "完整性": meta_value(meta, "完整性", "completeness"),
                "解析文件": str(path.relative_to(workspace)).replace("\\", "/"),
                "解析文件SHA256": sha256(path),
            }
        )
    return output


def parse_chunk_file(path: Path, scene: str, region: str, package_version: str) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    output = []
    for asset_id, title, fields in section_fields(text, r"^##[ \t]+(KC-[A-Z0-9-]+)(?:[ \t]+(.*))?$"):
        source = fields.get("来源", "")
        output.append(
            {
                "编号": asset_id,
                "标题": title,
                "场景编码": scene,
                "地区码": region,
                "知识包版本": package_version,
                "类型": fields.get("类型", ""),
                "内容": fields.get("内容", ""),
                "适用范围": fields.get("适用范围", ""),
                "时效说明": fields.get("时效说明", ""),
                "来源原文": source,
                "来源锚点": anchors(source),
                "快照文件": str(path),
            }
        )
    return output


def parse_qa_file(path: Path, scene: str, region: str, package_version: str) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    output = []
    for asset_id, title, fields in section_fields(text, r"^##[ \t]+(QA-[A-Z0-9-]+)(?:[ \t]+(.*))?$"):
        similar = [item.strip() for item in re.split(r"[｜|]", fields.get("相似问法", "")) if item.strip()]
        source = fields.get("来源", "")
        output.append(
            {
                "编号": asset_id,
                "标题": title,
                "场景编码": scene,
                "地区码": region,
                "知识包版本": package_version,
                "标准问": fields.get("标准问", ""),
                "相似问法": similar,
                "标准答案": fields.get("标准答案", ""),
                "适用范围": fields.get("适用范围", ""),
                "来源原文": source,
                "来源知识块": expand_kc(source),
                "来源锚点": anchors(source),
                "快照文件": str(path),
            }
        )
    return output


def parse_wiki_file(path: Path, scene: str, region: str, package_version: str) -> dict:
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", text, re.M)
    status_match = re.search(r"Wiki 状态:\s*([^|\n]+)", text)
    headings = re.findall(r"^##\s+(.+)$", text, re.M)
    return {
        "编号": f"WK-{scene}-{region}",
        "标题": title_match.group(1).strip() if title_match else path.stem,
        "场景编码": scene,
        "地区码": region,
        "知识包版本": package_version,
        "状态": status_match.group(1).strip() if status_match else "未知",
        "章节": headings,
        "内容": text,
        "来源知识块": sorted(set(expand_kc(text))),
        "来源锚点": sorted(set(anchors(text))),
        "快照文件": str(path),
    }


def parse_graph_file(path: Path, scene: str, region: str, package_version: str) -> tuple[list[dict], list[dict], list[dict]]:
    text = path.read_text(encoding="utf-8")
    entities_table = first_table_with(text, {"ID", "实体", "类型"})
    relations_table = first_table_with(text, {"ID", "头", "关系", "尾", "来源"})
    entities = [
        {
            "全局ID": f"{scene}/{region}/{row['ID']}",
            "本地ID": row["ID"],
            "名称": row["实体"],
            "类型": row["类型"],
            "Wiki锚点": row.get("Wiki 锚点", ""),
            "场景编码": scene,
            "地区码": region,
            "知识包版本": package_version,
        }
        for row in entities_table
    ]
    relations = [
        {
            "全局ID": f"{scene}/{region}/{row['ID']}",
            "本地ID": row["ID"],
            "头表达式": row["头"],
            "关系": row["关系"],
            "尾表达式": row["尾"],
            "来源原文": row["来源"],
            "来源知识块": expand_kc(row["来源"]),
            "场景编码": scene,
            "地区码": region,
            "知识包版本": package_version,
        }
        for row in relations_table
    ]
    rules = []
    rule_re = re.compile(r"^###\s+(RULE-[A-Z0-9-]+)\s*(.*)$", re.M)
    matches = list(rule_re.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else text.find("\n## ", match.end())
        if end < 0:
            end = len(text)
        body = text[match.end() : end].strip()
        rules.append(
            {
                "全局ID": f"{scene}/{region}/{match.group(1)}",
                "规则ID": match.group(1),
                "规则名": match.group(2).strip(),
                "场景编码": scene,
                "地区码": region,
                "知识包版本": package_version,
                "规则文本": body,
                "来源知识块": expand_kc(body),
                "来源锚点": anchors(body),
            }
        )
    return entities, relations, rules


def parse_common_knowledge(workspace: Path) -> list[dict]:
    path = workspace / "50-知识资产" / "_共性知识" / "共性知识库.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    output = []
    for asset_id, title, fields in section_fields(text, r"^##[ \t]+(GJJ-CK-\d+)(?:[ \t]+(.*))?$"):
        source = fields.get("来源", "")
        output.append(
            {
                "编号": asset_id,
                "名称": title,
                "适用范围": fields.get("适用范围", ""),
                "时效": fields.get("时效", ""),
                "内容": fields.get("内容", ""),
                "来源原文": source,
                "来源锚点": anchors(source),
            }
        )
    return output


def collect(workspace: Path) -> tuple[dict[str, list[dict]], list[str], list[str]]:
    data: dict[str, list[dict]] = {
        "文档": parse_documents(workspace),
        "知识包": [],
        "知识块": [],
        "问答对": [],
        "Wiki页": [],
        "图谱实体": [],
        "图谱关系": [],
        "图谱规则": [],
        "共性知识": parse_common_knowledge(workspace),
        "发布记录": parse_release_records(workspace),
    }
    errors: list[str] = []
    warnings: list[str] = []

    for release in data["发布记录"]:
        scene_region = release["地区版本"]
        if "/" not in scene_region:
            errors.append(f"发布记录地区版本格式错误: {scene_region}")
            continue
        scene, region = scene_region.split("/", 1)
        version = release["版本"]
        manifest = workspace / "60-知识包" / scene / region / version / "包清单.md"
        if not manifest.exists():
            errors.append(f"发布记录对应包清单不存在: {manifest.relative_to(workspace)}")
            continue
        metadata, assets = parse_manifest(manifest)
        package_id = f"{scene}/{region}/{version}"
        data["知识包"].append(
            {
                "包ID": package_id,
                "场景编码": scene,
                "地区码": region,
                "版本": version,
                "发布动作": release.get("动作", ""),
                "发布状态": metadata.get("发布状态", ""),
                "治理档位": metadata.get("治理档位", ""),
                "时效基准": metadata.get("时效基准", ""),
                "包清单": str(manifest.relative_to(workspace)).replace("\\", "/"),
                "包清单SHA256": sha256(manifest),
            }
        )
        if not assets:
            errors.append(f"{package_id}: 未使用冻结资产快照")
            continue
        for label, path in assets.items():
            if not path.exists():
                errors.append(f"{package_id}: 快照文件缺失 {label}: {path}")
                continue
            if label == "知识块":
                data["知识块"].extend(parse_chunk_file(path, scene, region, version))
            elif label == "问答对":
                data["问答对"].extend(parse_qa_file(path, scene, region, version))
            elif label == "Wiki页":
                wiki = parse_wiki_file(path, scene, region, version)
                data["Wiki页"].append(wiki)
                if "待审" in wiki["状态"]:
                    errors.append(f"{package_id}: Wiki 快照仍为待审状态")
            elif label == "知识图谱":
                entities, relations, rules = parse_graph_file(path, scene, region, version)
                data["图谱实体"].extend(entities)
                data["图谱关系"].extend(relations)
                data["图谱规则"].extend(rules)

    chunk_ids = {row["编号"] for row in data["知识块"]}
    for row in data["知识块"]:
        if not row["内容"] or (not row["来源锚点"] and "GJJ-CK-" not in row["来源原文"]):
            errors.append(f"{row['编号']}: 知识块缺内容或可追溯来源")
    for row in data["问答对"]:
        if not row["标准问"] or not row["标准答案"]:
            errors.append(f"{row['编号']}: 问答对缺标准问或标准答案")
        for chunk_id in row["来源知识块"]:
            if chunk_id not in chunk_ids:
                errors.append(f"{row['编号']}: 来源知识块不存在 {chunk_id}")
    for row in data["图谱关系"] + data["图谱规则"]:
        for chunk_id in row["来源知识块"]:
            if chunk_id not in chunk_ids:
                errors.append(f"{row.get('全局ID')}: 来源知识块不存在 {chunk_id}")
    missing_urls = sum(document["来源URL"] == "未知" for document in data["文档"])
    missing_access = sum(document["权限范围"] == "未指定" for document in data["文档"])
    if missing_urls:
        warnings.append(f"{missing_urls} 份文档缺来源URL，无法自动复查网页现行状态")
    if missing_access:
        warnings.append(f"{missing_access} 份文档缺权限范围，尚不能执行分权检索")
    pending = (workspace / "20-打标结果" / "待人工确认清单.md").read_text(encoding="utf-8")
    pending_count = len(re.findall(r"\|\s*待确认\s*\|", pending))
    if pending_count:
        warnings.append(f"仍有 {pending_count} 项待人工确认，发布投影不得视为生产终审")
    return data, errors, warnings


def write_jsonl(output_dir: Path, data: dict[str, list[dict]]) -> None:
    exchange = output_dir / "交换态"
    exchange.mkdir(parents=True, exist_ok=True)
    for name, rows in data.items():
        path = exchange / f"{name}.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_sqlite(path: Path, data: dict[str, list[dict]], warnings: list[str]) -> None:
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE "元数据" ("键" TEXT PRIMARY KEY, "值" TEXT NOT NULL);
        CREATE TABLE "文档" (
          "编号" TEXT PRIMARY KEY, "标题" TEXT, "地区" TEXT, "发布机构" TEXT,
          "文档类型" TEXT, "发布时间" TEXT, "生效时间" TEXT, "源文件" TEXT,
          "来源URL" TEXT, "权限范围" TEXT, "内容哈希" TEXT, "完整性" TEXT,
          "解析文件" TEXT, "解析文件SHA256" TEXT NOT NULL
        );
        CREATE TABLE "知识包" (
          "包ID" TEXT PRIMARY KEY, "场景编码" TEXT NOT NULL, "地区码" TEXT NOT NULL,
          "版本" TEXT NOT NULL, "发布动作" TEXT, "发布状态" TEXT, "治理档位" TEXT,
          "时效基准" TEXT, "包清单" TEXT, "包清单SHA256" TEXT NOT NULL
        );
        CREATE TABLE "知识块" (
          "编号" TEXT PRIMARY KEY, "标题" TEXT, "场景编码" TEXT NOT NULL,
          "地区码" TEXT NOT NULL, "知识包版本" TEXT NOT NULL, "类型" TEXT,
          "内容" TEXT NOT NULL, "适用范围" TEXT, "时效说明" TEXT, "来源原文" TEXT
        );
        CREATE TABLE "知识块来源" (
          "知识块编号" TEXT NOT NULL REFERENCES "知识块"("编号") ON DELETE CASCADE,
          "锚点" TEXT NOT NULL, PRIMARY KEY ("知识块编号", "锚点")
        );
        CREATE TABLE "问答对" (
          "编号" TEXT PRIMARY KEY, "标题" TEXT, "场景编码" TEXT NOT NULL,
          "地区码" TEXT NOT NULL, "知识包版本" TEXT NOT NULL, "标准问" TEXT NOT NULL,
          "标准答案" TEXT NOT NULL, "适用范围" TEXT, "来源原文" TEXT
        );
        CREATE TABLE "相似问法" (
          "问答对编号" TEXT NOT NULL REFERENCES "问答对"("编号") ON DELETE CASCADE,
          "问法" TEXT NOT NULL, PRIMARY KEY ("问答对编号", "问法")
        );
        CREATE TABLE "问答对来源" (
          "问答对编号" TEXT NOT NULL REFERENCES "问答对"("编号") ON DELETE CASCADE,
          "知识块编号" TEXT, "锚点" TEXT
        );
        CREATE TABLE "Wiki页" (
          "编号" TEXT PRIMARY KEY, "标题" TEXT, "场景编码" TEXT NOT NULL,
          "地区码" TEXT NOT NULL, "知识包版本" TEXT NOT NULL, "状态" TEXT,
          "章节JSON" TEXT, "内容" TEXT NOT NULL, "来源知识块JSON" TEXT, "来源锚点JSON" TEXT
        );
        CREATE TABLE "图谱实体" (
          "全局ID" TEXT PRIMARY KEY, "本地ID" TEXT NOT NULL, "名称" TEXT NOT NULL,
          "类型" TEXT, "Wiki锚点" TEXT, "场景编码" TEXT NOT NULL, "地区码" TEXT NOT NULL,
          "知识包版本" TEXT NOT NULL
        );
        CREATE TABLE "图谱关系" (
          "全局ID" TEXT PRIMARY KEY, "本地ID" TEXT NOT NULL, "头表达式" TEXT NOT NULL,
          "关系" TEXT NOT NULL, "尾表达式" TEXT NOT NULL, "来源原文" TEXT,
          "来源知识块JSON" TEXT, "场景编码" TEXT NOT NULL, "地区码" TEXT NOT NULL,
          "知识包版本" TEXT NOT NULL
        );
        CREATE TABLE "图谱规则" (
          "全局ID" TEXT PRIMARY KEY, "规则ID" TEXT NOT NULL, "规则名" TEXT,
          "场景编码" TEXT NOT NULL, "地区码" TEXT NOT NULL, "知识包版本" TEXT NOT NULL,
          "规则文本" TEXT NOT NULL, "来源知识块JSON" TEXT, "来源锚点JSON" TEXT
        );
        CREATE TABLE "共性知识" (
          "编号" TEXT PRIMARY KEY, "名称" TEXT, "适用范围" TEXT, "时效" TEXT,
          "内容" TEXT, "来源原文" TEXT, "来源锚点JSON" TEXT
        );
        CREATE TABLE "发布记录" (
          "序号" TEXT, "时间" TEXT, "地区版本" TEXT, "版本" TEXT, "动作" TEXT,
          "审核依据" TEXT, "回滚点" TEXT, "当前有效版本" TEXT
        );
        """
    )
    db.executemany('INSERT INTO "元数据" VALUES (?, ?)', [("生成日期", date.today().isoformat()), ("事实源", "冻结 Markdown 知识包快照")])
    doc_cols = ["编号", "标题", "地区", "发布机构", "文档类型", "发布时间", "生效时间", "源文件", "来源URL", "权限范围", "内容哈希", "完整性", "解析文件", "解析文件SHA256"]
    db.executemany(f'INSERT INTO "文档" VALUES ({",".join("?" for _ in doc_cols)})', [[row.get(col, "") for col in doc_cols] for row in data["文档"]])
    package_cols = ["包ID", "场景编码", "地区码", "版本", "发布动作", "发布状态", "治理档位", "时效基准", "包清单", "包清单SHA256"]
    db.executemany(f'INSERT INTO "知识包" VALUES ({",".join("?" for _ in package_cols)})', [[row.get(col, "") for col in package_cols] for row in data["知识包"]])
    for row in data["知识块"]:
        db.execute('INSERT INTO "知识块" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [row.get(key, "") for key in ["编号", "标题", "场景编码", "地区码", "知识包版本", "类型", "内容", "适用范围", "时效说明", "来源原文"]])
        db.executemany('INSERT INTO "知识块来源" VALUES (?, ?)', [(row["编号"], anchor) for anchor in row["来源锚点"]])
    for row in data["问答对"]:
        db.execute('INSERT INTO "问答对" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [row.get(key, "") for key in ["编号", "标题", "场景编码", "地区码", "知识包版本", "标准问", "标准答案", "适用范围", "来源原文"]])
        db.executemany('INSERT INTO "相似问法" VALUES (?, ?)', [(row["编号"], question) for question in row["相似问法"]])
        sources = [(row["编号"], chunk, None) for chunk in row["来源知识块"]] + [(row["编号"], None, anchor) for anchor in row["来源锚点"]]
        db.executemany('INSERT INTO "问答对来源" VALUES (?, ?, ?)', sources)
    for row in data["Wiki页"]:
        db.execute('INSERT INTO "Wiki页" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (row["编号"], row["标题"], row["场景编码"], row["地区码"], row["知识包版本"], row["状态"], json_text(row["章节"]), row["内容"], json_text(row["来源知识块"]), json_text(row["来源锚点"])))
    for row in data["图谱实体"]:
        db.execute('INSERT INTO "图谱实体" VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [row[key] for key in ["全局ID", "本地ID", "名称", "类型", "Wiki锚点", "场景编码", "地区码", "知识包版本"]])
    for row in data["图谱关系"]:
        db.execute('INSERT INTO "图谱关系" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (row["全局ID"], row["本地ID"], row["头表达式"], row["关系"], row["尾表达式"], row["来源原文"], json_text(row["来源知识块"]), row["场景编码"], row["地区码"], row["知识包版本"]))
    for row in data["图谱规则"]:
        db.execute('INSERT INTO "图谱规则" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (row["全局ID"], row["规则ID"], row["规则名"], row["场景编码"], row["地区码"], row["知识包版本"], row["规则文本"], json_text(row["来源知识块"]), json_text(row["来源锚点"])))
    for row in data["共性知识"]:
        db.execute('INSERT INTO "共性知识" VALUES (?, ?, ?, ?, ?, ?, ?)', (row["编号"], row["名称"], row["适用范围"], row["时效"], row["内容"], row["来源原文"], json_text(row["来源锚点"])))
    release_cols = ["#", "时间", "地区版本", "版本", "动作", "审核依据", "回滚点", "当前有效版本"]
    db.executemany('INSERT INTO "发布记录" VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [[row.get(col, "") for col in release_cols] for row in data["发布记录"]])

    try:
        db.execute("CREATE VIRTUAL TABLE \"知识检索\" USING fts5(\"资产ID\" UNINDEXED, \"资产类型\" UNINDEXED, \"场景编码\" UNINDEXED, \"地区码\" UNINDEXED, \"标题\", \"内容\", tokenize='trigram')")
    except sqlite3.OperationalError:
        warnings.append("当前 SQLite 不支持 FTS5 trigram，已回退 unicode61；中文子串检索能力会下降")
        db.execute("CREATE VIRTUAL TABLE \"知识检索\" USING fts5(\"资产ID\" UNINDEXED, \"资产类型\" UNINDEXED, \"场景编码\" UNINDEXED, \"地区码\" UNINDEXED, \"标题\", \"内容\")")
    search_rows = []
    search_rows.extend((row["编号"], "知识块", row["场景编码"], row["地区码"], row["标题"], row["内容"]) for row in data["知识块"])
    search_rows.extend((row["编号"], "问答对", row["场景编码"], row["地区码"], row["标准问"], row["标准答案"]) for row in data["问答对"])
    search_rows.extend((row["编号"], "Wiki", row["场景编码"], row["地区码"], row["标题"], row["内容"]) for row in data["Wiki页"])
    search_rows.extend((row["编号"], "共性知识", "", "", row["名称"], row["内容"]) for row in data["共性知识"])
    db.executemany('INSERT INTO "知识检索" VALUES (?, ?, ?, ?, ?, ?)', search_rows)
    db.commit()
    db.close()


def cypher_quote(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\\u2028", " ").replace("\\u2029", " ")


def props(mapping: dict) -> str:
    return "{" + ", ".join(f"`{key}`: {cypher_quote(value)}" for key, value in mapping.items()) + "}"


def write_cypher(path: Path, data: dict[str, list[dict]]) -> None:
    lines = [
        "// Generated projection. Rebuild from frozen Markdown packages; do not edit in Neo4j.",
        "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:`文档`) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT package_id IF NOT EXISTS FOR (n:`知识包`) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:`知识块`) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:`图谱实体`) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT rule_id IF NOT EXISTS FOR (n:`图谱规则`) REQUIRE n.id IS UNIQUE;",
        "CREATE CONSTRAINT relation_id IF NOT EXISTS FOR (n:`图谱关系`) REQUIRE n.id IS UNIQUE;",
        "",
    ]
    for row in data["文档"]:
        lines.append(f"MERGE (n:`文档` {{id: {cypher_quote(row['编号'])}}}) SET n += {props({'标题': row['标题'], '地区': row['地区'], '发布时间': row['发布时间'], '完整性': row['完整性']})};")
    for row in data["知识包"]:
        lines.append(f"MERGE (n:`知识包` {{id: {cypher_quote(row['包ID'])}}}) SET n += {props({'场景编码': row['场景编码'], '地区码': row['地区码'], '版本': row['版本'], '发布状态': row['发布状态']})};")
    for row in data["知识块"]:
        lines.append(f"MERGE (n:`知识块` {{id: {cypher_quote(row['编号'])}}}) SET n += {props({'类型': row['类型'], '内容': row['内容'], '适用范围': row['适用范围']})};")
        package_id = f"{row['场景编码']}/{row['地区码']}/{row['知识包版本']}"
        lines.append(f"MATCH (p:`知识包` {{id: {cypher_quote(package_id)}}}), (n:`知识块` {{id: {cypher_quote(row['编号'])}}}) MERGE (p)-[:`拥有`]->(n);")
        for anchor in row["来源锚点"]:
            doc_id = anchor.split("#", 1)[0]
            lines.append(f"MATCH (n:`知识块` {{id: {cypher_quote(row['编号'])}}}), (d:`文档` {{id: {cypher_quote(doc_id)}}}) MERGE (n)-[r:`来源于` {{锚点: {cypher_quote(anchor)}}}]->(d);")
    for row in data["图谱实体"]:
        lines.append(f"MERGE (n:`图谱实体` {{id: {cypher_quote(row['全局ID'])}}}) SET n += {props({'本地ID': row['本地ID'], '名称': row['名称'], '类型': row['类型']})};")
    for row in data["图谱关系"]:
        lines.append(f"MERGE (n:`图谱关系` {{id: {cypher_quote(row['全局ID'])}}}) SET n += {props({'头表达式': row['头表达式'], '关系': row['关系'], '尾表达式': row['尾表达式']})};")
        for chunk_id in row["来源知识块"]:
            lines.append(f"MATCH (r:`图谱关系` {{id: {cypher_quote(row['全局ID'])}}}), (k:`知识块` {{id: {cypher_quote(chunk_id)}}}) MERGE (r)-[:`依据`]->(k);")
        if re.fullmatch(r"E\d+", row["头表达式"]) and re.fullmatch(r"E\d+", row["尾表达式"]):
            head = f"{row['场景编码']}/{row['地区码']}/{row['头表达式']}"
            tail = f"{row['场景编码']}/{row['地区码']}/{row['尾表达式']}"
            lines.append(f"MATCH (a:`图谱实体` {{id: {cypher_quote(head)}}}), (b:`图谱实体` {{id: {cypher_quote(tail)}}}) MERGE (a)-[r:`业务关系` {{id: {cypher_quote(row['全局ID'])}}}]->(b) SET r.`名称` = {cypher_quote(row['关系'])};")
    for row in data["图谱规则"]:
        lines.append(f"MERGE (n:`图谱规则` {{id: {cypher_quote(row['全局ID'])}}}) SET n += {props({'规则ID': row['规则ID'], '规则名': row['规则名'], '规则文本': row['规则文本']})};")
        for chunk_id in row["来源知识块"]:
            lines.append(f"MATCH (r:`图谱规则` {{id: {cypher_quote(row['全局ID'])}}}), (k:`知识块` {{id: {cypher_quote(chunk_id)}}}) MERGE (r)-[:`依据`]->(k);")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(path: Path, data: dict[str, list[dict]], errors: list[str], warnings: list[str]) -> None:
    lines = [
        "# 知识库导出报告",
        "",
        f"> 生成日期: {date.today().isoformat()} | 事实源: 当前有效版本的冻结 Markdown 知识包快照",
        "",
        "## 对象统计",
        "",
        "| 对象 | 数量 |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {len(rows)} |" for name, rows in data.items())
    lines.extend(["", "## 校验结果", ""])
    lines.append(f"- 错误: {len(errors)}")
    lines.append(f"- 警告: {len(warnings)}")
    if errors:
        lines.extend(["", "### 错误", ""] + [f"- {item}" for item in errors])
    if warnings:
        lines.extend(["", "### 警告", ""] + [f"- {item}" for item in warnings])
    lines.extend(
        [
            "",
            "## 生成物",
            "",
            "- `交换态/*.jsonl`: 跨数据库、跨模型的稳定交换契约",
            "- `知识库.db`: 关系表、来源表与 FTS5 检索投影",
            "- `导入Neo4j.cypher`: 图查询投影；当前复合头尾表达式保留为关系节点，避免伪造实体边",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main(workspace: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data, errors, warnings = collect(workspace)
    write_report(output_dir / "导出报告.md", data, errors, warnings)
    if errors:
        for error in errors:
            print("ERROR", error)
        raise SystemExit(f"导出失败：{len(errors)} 个错误；见 {output_dir / '导出报告.md'}")
    write_jsonl(output_dir, data)
    build_sqlite(output_dir / "知识库.db", data, warnings)
    write_cypher(output_dir / "导入Neo4j.cypher", data)
    write_report(output_dir / "导出报告.md", data, errors, warnings)
    print("导出完成")
    for name, rows in data.items():
        print(f"  {name}: {len(rows)}")
    print(f"  警告: {len(warnings)}")
    print(f"  输出: {output_dir}")


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("用法: python export_kb.py <工作区目录> [输出目录]")
    ws = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) == 3 else ws / "80-知识库导出"
    main(ws, out)

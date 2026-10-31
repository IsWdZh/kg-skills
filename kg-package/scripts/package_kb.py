# -*- coding: utf-8 -*-
"""兼容组包入口：按现有知识资产目录动态生成不可变试跑包。

核心 Skill 不内置场景、地区或行业列表。场景与适用版本直接取自
50-知识资产/<服务单元>/<适用版本>/，显示名与发布参数可由治理参数.json提供。
"""

import hashlib
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ASSET_LABELS = {
    "知识块.md": "知识块",
    "问答对.md": "问答对",
    "Wiki.md": "Wiki",
    "Wiki页.md": "Wiki",
    "知识图谱.md": "知识图谱",
}
DOC_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,15}-\d{3})(?:#[A-Za-z0-9:!._-]+)?")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config(ws: Path) -> dict:
    path = ws / "治理参数.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def parse_registry(ws: Path) -> dict[str, str]:
    path = ws / "00-文档台账" / "台账.md"
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and re.fullmatch(r"[A-Z][A-Z0-9]{1,15}-\d{3}", cells[0]):
            result[cells[0]] = cells[1]
    return result


def parse_scene_catalog(ws: Path) -> dict[str, dict]:
    path = ws / "30-业务图与场景" / "单元场景目录.md"
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*-\d{2}", cells[0]):
            result[cells[0]] = {
                "name": cells[1],
                "domain": cells[2] if len(cells) > 2 else "未配置",
                "tier": next((c for c in cells if c in {"轻治理", "标准治理", "推理治理"}), "标准治理"),
            }
    return result


def freeze_copy(source: Path, target: Path) -> str:
    digest = sha256_file(source)
    if target.exists():
        if sha256_file(target) != digest:
            raise RuntimeError(f"不可变版本内容冲突: {target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return digest


def main(ws: Path) -> None:
    config = load_config(ws)
    version = str(config.get("knowledge_version", "v0.1")).strip()
    if not version.startswith("v"):
        version = f"v{version}"
    level = str(config.get("publication_level", "受限试跑"))
    applicability = {
        str(item.get("code")): str(item.get("name") or item.get("code"))
        for item in config.get("applicability_versions", [])
        if item.get("code")
    }
    today = date.today().isoformat()
    asset_root = ws / "50-知识资产"
    package_root = ws / "60-知识包"
    package_root.mkdir(parents=True, exist_ok=True)
    registry = parse_registry(ws)
    catalog = parse_scene_catalog(ws)
    records = []

    for scene_dir in sorted(p for p in asset_root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        scene = scene_dir.name
        meta = catalog.get(scene, {"name": scene, "domain": "未配置", "tier": "标准治理"})
        for scope_dir in sorted(p for p in scene_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
            scope = scope_dir.name
            asset_files = [p for p in sorted(scope_dir.glob("*.md")) if p.name in ASSET_LABELS]
            if not asset_files:
                continue
            package_dir = package_root / scene / scope / version
            snapshot_dir = package_dir / "资产"
            source_docs = set()
            asset_rows = []
            for source in asset_files:
                text = source.read_text(encoding="utf-8")
                source_docs.update(DOC_ID_RE.findall(text))
                digest = freeze_copy(source, snapshot_dir / source.name)
                asset_rows.append((ASSET_LABELS[source.name], source.name, source.stat().st_size, digest))

            lines = [
                f"# 知识包清单：{scene}/{scope} {version}", "",
                "| 项 | 值 |", "|---|---|",
                f"| 知识服务单元 | {scene} {meta['name']} |",
                f"| 业务域 | {meta['domain']} |",
                f"| 适用版本 | {applicability.get(scope, scope)}（{scope}） |",
                f"| 治理档位 | {meta['tier']} |",
                f"| 包版本 | {version} |",
                f"| 发布状态 | {level}（{today}） |", "",
                "## 资产清单", "", "| 形态 | 文件 | 大小 | SHA-256 |", "|---|---|---|---|",
            ]
            lines.extend(
                f"| {label} | [资产/{name}](资产/{name}) | {size}B | {digest} |"
                for label, name, size, digest in asset_rows
            )
            lines.extend(["", "## 来源文档", "", "| 编号 | 标题 |", "|---|---|"])
            lines.extend(f"| {doc_id} | {registry.get(doc_id, doc_id)} |" for doc_id in sorted(source_docs))
            lines.extend(["", "## 调用约束", "", "- 先执行权限、适用版本和时效过滤，再按资产形态路由。", "- 所有事实性响应必须返回底层文档锚点。", ""])
            (package_dir / "包清单.md").write_text("\n".join(lines), encoding="utf-8")
            records.append((scene, scope, version, level, today))

    release = [
        "# 发布记录", "",
        "| # | 时间 | 地区版本 | 版本 | 动作 | 审核依据 | 回滚点 | 当前有效版本 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    release.extend(
        f"| {index} | {day} | {scene}/{scope} | {version} | {level}发布 | 兼容组包入口 | 无 | {version} |"
        for index, (scene, scope, version, level, day) in enumerate(records, 1)
    )
    (package_root / "发布记录.md").write_text("\n".join(release) + "\n", encoding="utf-8")
    print(f"知识包组装完成: {len(records)} 个，版本 {version}，发布级别 {level}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python package_kb.py <工作区目录>")
        raise SystemExit(1)
    main(Path(sys.argv[1]))

#!/usr/bin/env python3
"""Verify root-level and nested Markdown inputs survive the full early governance chain."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, *args: Path) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / script), *map(str, args)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kg-md-pass-") as temp:
        base = Path(temp)
        source = base / "source"
        workspace = base / "workspace"
        (source / "team" / "nested").mkdir(parents=True)
        (source / "root-note.md").write_text("# 根目录短文\n\n有效。\n", encoding="utf-8")
        (source / "team" / "nested" / "guide.markdown").write_text(
            """---
标题: 嵌套指南
地区: 示例区域
访问范围: 内部
知识角色: 方法规范
版本关系: 当前有效
---

# 嵌套指南

设备巡检应形成记录，并由责任人复核。
""",
            encoding="utf-8",
        )
        config = {
            "domain_code": "TECH",
            "tagging": {
                "domains": [
                    {
                        "name": "运维管理",
                        "code": "OPS",
                        "keywords": ["设备", "巡检"],
                        "labels": [{"name": "设备巡检", "keywords": ["设备巡检", "巡检记录"]}],
                    }
                ]
            },
        }
        workspace.mkdir()
        (workspace / "治理参数.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        run("kg-normalize/scripts/normalize.py", source, workspace)
        run("kg-normalize/scripts/validate_normalization.py", workspace)
        run("kg-intake/scripts/parse_docs.py", Path("--from-md"), workspace)
        run("kg-tagging/scripts/tag_docs.py", workspace)
        run("kg-evidence-govern/scripts/build_evidence_index.py", workspace)

        normalized = [
            path for path in (workspace / "00-原始MD").rglob("*.md")
            if path.name != "转换清单.md" and "_图片" not in path.parts
        ]
        parsed = list((workspace / "10-解析文档").rglob("*.md"))
        manifest = [line for line in (workspace / "00-多模态清单" / "多模态清单.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(normalized) == len(parsed) == len(manifest) == 2
        formats = {re.search(r"^原始格式:\s*(.+)$", path.read_text(encoding="utf-8"), re.M).group(1) for path in normalized}
        assert formats == {"md", "markdown"}
        assert any("有效。" in path.read_text(encoding="utf-8") for path in parsed)
        assert any("设备巡检应形成记录" in path.read_text(encoding="utf-8") for path in parsed)
        ledger = (workspace / "00-文档台账" / "台账.md").read_text(encoding="utf-8")
        assert ledger.count("| ROOT-") + ledger.count("| TEAM-") == 2
        tags = (workspace / "20-打标结果" / "文档级打标.md").read_text(encoding="utf-8")
        assert "ROOT-001" in tags and "TEAM-001" in tags
        print(json.dumps({"passed": True, "documents": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

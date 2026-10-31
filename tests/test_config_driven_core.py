#!/usr/bin/env python3
"""Exercise the legacy batch helpers with a non-project-specific workspace config."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, workspace: Path) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / script), str(workspace)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kg-generic-") as temp:
        workspace = Path(temp) / "治理工作区-20260701-0900"
        parsed = workspace / "10-解析文档" / "SRC1"
        parsed.mkdir(parents=True)
        config = {
            "domain_code": "TECH",
            "projection_prefix": "kg_tech",
            "knowledge_version": "v1.0",
            "tagging": {
                "source_levels": {"SRC1": "内部规范"},
                "regions": ["示例区域"],
                "domains": [
                    {
                        "name": "运维管理",
                        "code": "OPS",
                        "keywords": ["运维", "设备"],
                        "labels": [
                            {"name": "设备巡检", "keywords": ["设备巡检", "巡检记录"]}
                        ],
                    }
                ],
                "genres": [{"name": "规范文件", "patterns": ["规范"]}],
            },
            "applicability_versions": [
                {"code": "MAIN", "name": "示例版", "source_codes": ["SRC1"]}
            ],
        }
        (workspace / "治理参数.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (parsed / "SRC1-001.md").write_text(
            """---
编号: SRC1-001
标题: 设备巡检规范
地区: 示例区域
发布时间: 2026-01-01
访问范围: 内部
版本关系: 当前有效
---

[p001] 设备巡检应每日执行并记录异常。
[p002] 巡检记录由责任人员复核。
""",
            encoding="utf-8",
        )

        run("kg-tagging/scripts/tag_docs.py", workspace)
        run("kg-scenario-map/scripts/gen_scenarios.py", workspace)
        scene = workspace / "30-业务图与场景" / "单元场景目录.md"
        scene.write_text(
            """# 单元场景目录

| 编码 | 名称 | 业务域 | 状态 | 治理方式 |
|---|---|---|---|---|
| OPS-01 | 设备巡检 | 运维管理 | 已确认 | 标准治理 |
""",
            encoding="utf-8",
        )
        run("kg-produce/scripts/produce_assets.py", workspace)
        run("kg-package/scripts/package_kb.py", workspace)
        run("kg-package/scripts/gen_exchange.py", workspace)

        sys.path.insert(0, str(ROOT / "kg-package" / "scripts"))
        from load_pg import derive_db

        assert derive_db(workspace) == "kg_tech_20260701_0900"
        required = [
            workspace / "20-打标结果" / "文档级打标.md",
            workspace / "30-业务图与场景" / "候选单元场景清单.md",
            workspace / "50-知识资产" / "OPS-01" / "MAIN" / "知识块.md",
            workspace / "60-知识包" / "OPS-01" / "MAIN" / "v1.0" / "包清单.md",
            workspace / "80-知识库导出" / "导出报告.md",
        ]
        assert all(path.exists() for path in required)
        knowledge = required[2].read_text(encoding="utf-8")
        assert "SRC1-001#p001" in knowledge
        print(json.dumps({"passed": True, "projection": derive_db(workspace)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

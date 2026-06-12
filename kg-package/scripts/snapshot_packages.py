# -*- coding: utf-8 -*-
"""Freeze published knowledge-package assets and add SHA-256 checksums.

Usage: python snapshot_packages.py <workspace>
Existing snapshots are immutable. Publish a new version instead of overwriting a
snapshot whose bytes differ from the governance source.
"""

import hashlib
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote


sys.stdout.reconfigure(encoding="utf-8")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+\.md)\)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_manifest(manifest: Path, workspace: Path) -> tuple[int, str]:
    text = manifest.read_text(encoding="utf-8")
    asset_dir = manifest.parent / "资产"
    asset_dir.mkdir(exist_ok=True)
    checksums: list[tuple[str, str]] = []
    replacements: list[tuple[str, str]] = []

    for match in LINK_RE.finditer(text):
        label, target = match.group(1), match.group(2)
        source = (manifest.parent / unquote(target)).resolve()
        if not source.exists():
            raise ValueError(f"{manifest}: asset link does not exist: {target}")

        if source.parent == asset_dir.resolve():
            frozen = source
        elif workspace.resolve() in source.parents and "50-知识资产" in source.parts:
            frozen = asset_dir / source.name
            if frozen.exists() and sha256(frozen) != sha256(source):
                raise ValueError(
                    f"{manifest}: immutable snapshot differs from governance source: {source.name}; "
                    "publish a new version"
                )
            if not frozen.exists():
                shutil.copy2(source, frozen)
            replacements.append((target, f"资产/{source.name}"))
        else:
            continue
        checksums.append((frozen.name, sha256(frozen)))

    for old, new in replacements:
        text = text.replace(f"]({old})", f"]({new})")

    text = re.sub(r"\n## 资产快照校验\n.*\Z", "", text, flags=re.S).rstrip()
    if not checksums:
        raise ValueError(f"{manifest}: no knowledge assets found")

    checksums = sorted(set(checksums))
    package_hash = hashlib.sha256(
        "\n".join(f"{name}:{digest}" for name, digest in checksums).encode("utf-8")
    ).hexdigest()
    lines = [
        "",
        "## 资产快照校验",
        "",
        "> 本版本资产已冻结。治理态修订必须发布新版本，不得覆盖本目录快照。",
        "",
        "| 文件 | SHA-256 |",
        "|---|---|",
    ]
    lines.extend(f"| {name} | `{digest}` |" for name, digest in checksums)
    lines.extend(["", f"- 包指纹: `{package_hash}`", ""])
    manifest.write_text(text + "\n" + "\n".join(lines), encoding="utf-8")
    return len(checksums), package_hash


def main(workspace: Path) -> None:
    manifests = sorted((workspace / "60-知识包").glob("*/*/v*/包清单.md"))
    if not manifests:
        raise SystemExit("未找到知识包清单")
    for manifest in manifests:
        count, package_hash = snapshot_manifest(manifest, workspace)
        print(f"{manifest.relative_to(workspace)}: {count} assets, {package_hash[:12]}")
    print(f"已冻结 {len(manifests)} 个知识包版本")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法: python snapshot_packages.py <工作区目录>")
    main(Path(sys.argv[1]))

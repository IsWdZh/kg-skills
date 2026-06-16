# -*- coding: utf-8 -*-
"""把知识资产 来源 字段中的纯文档锚点（编号#pNNN）前置〔原始文件标题〕。

标题取自 00-文档台账/台账.md。对外服务（尤其纯大模型按 skill 跑）由此可
直接照抄出文件名，无需答题时再查表。

幂等：已带〔…〕前缀的锚点跳过。默认处理 50-知识资产/（治理态事实源）；
重新冻结包（snapshot_packages.py 发新版本）后投影到 60-知识包/。

用法: python enrich_source_titles.py <工作区目录> [--dry-run]
"""

import re
import sys
from pathlib import Path


sys.stdout.reconfigure(encoding="utf-8")

# 仅匹配紧跟 #pNNN 的文档编号本身（#pNNN 用后顾断言保留，不消费）
DOC_ANCHOR_RE = re.compile(r"([A-Z][A-Z0-9]{1,7}-\d{3})(?=#p\d{3})")
CODE_RE = re.compile(r"[A-Z][A-Z0-9]{1,7}-\d{3}")


def load_ledger(ws: Path) -> dict[str, str]:
    ledger_file = ws / "00-文档台账" / "台账.md"
    if not ledger_file.exists():
        raise SystemExit(f"未找到台账: {ledger_file}")
    ledger: dict[str, str] = {}
    for line in ledger_file.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 3 and CODE_RE.fullmatch(cells[1]):
            ledger[cells[1]] = cells[2]  # 标题列
    return ledger


def enrich(text: str, ledger: dict[str, str]) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match) -> str:
        code = match.group(1)
        prev = match.string[match.start() - 1] if match.start() > 0 else ""
        if prev == "〕":  # 已带〔标题〕前缀
            return code
        title = ledger.get(code)
        if not title:  # 台账无此编号 → 保持原样
            return code
        nonlocal count
        count += 1
        return f"〔{title}〕{code}"

    return DOC_ANCHOR_RE.sub(repl, text), count


def main(ws: Path, dry_run: bool) -> None:
    ledger = load_ledger(ws)
    asset_root = ws / "50-知识资产"
    if not asset_root.exists():
        raise SystemExit(f"未找到知识资产目录: {asset_root}")

    total_files = total_anchors = 0
    for file in sorted(asset_root.rglob("*.md")):
        text = file.read_text(encoding="utf-8")
        new_text, n = enrich(text, ledger)
        if n:
            total_files += 1
            total_anchors += n
            print(f"  {file.relative_to(ws)}: 补全 {n} 处")
            if not dry_run:
                file.write_text(new_text, encoding="utf-8")

    mode = "试运行（未写入）" if dry_run else "已写入"
    print(f"\n{mode}：{total_files} 个文件、{total_anchors} 处文档锚点前置〔标题〕")
    if not dry_run and total_anchors:
        print(
            "提示：50-知识资产 已更新。如对外服务从冻结包读取，请重跑 "
            "snapshot_packages.py 发布新版本，使 60-知识包 同步。"
        )


if __name__ == "__main__":
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(positional) != 1:
        raise SystemExit("用法: python enrich_source_titles.py <工作区目录> [--dry-run]")
    main(Path(positional[0]), "--dry-run" in sys.argv)

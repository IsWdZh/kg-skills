# -*- coding: utf-8 -*-
"""从 10-解析文档/ 的 front matter 重建 00-文档台账/台账.md。

用法: python rebuild_registry.py <工作区目录>
解析文档被人工修订（如视觉转写）后运行本脚本，保持台账与解析结果一致。
"""
import sys, re, io, hashlib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def parse_front_matter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = {}
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta


def value(meta: dict, chinese: str, english: str, default: str = "") -> str:
    """Read current Chinese keys and legacy English keys without corrupting either."""
    return meta.get(chinese, meta.get(english, default))


def main(ws: Path):
    rows, hash_seen = [], {}
    for f in sorted((ws / "10-解析文档").rglob("*.md")):
        text = f.read_text(encoding="utf-8")
        meta = parse_front_matter(text)
        body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
        paras = re.findall(r"^\[p\d{3}\]", body, re.M)
        chars = len(re.sub(r"\s+", "", body))
        h = value(
            meta,
            "内容哈希",
            "content_hash",
            hashlib.sha256(re.sub(r"\s+", "", body).encode()).hexdigest(),
        )
        dup = hash_seen.get(h, "")
        if not dup:
            hash_seen[h] = value(meta, "编号", "doc_id", f.stem)
        source_file = value(meta, "源文件", "source_file")
        rows.append((value(meta, "编号", "doc_id", f.stem), value(meta, "标题", "title"),
                     value(meta, "地区", "region"), value(meta, "文档类型", "doc_type"),
                     value(meta, "发布时间", "publish_date", "未知"),
                     Path(source_file).suffix.lstrip("."), len(paras), chars,
                     value(meta, "完整性", "completeness"),
                     f"重复于{dup}" if dup else "唯一", source_file))
    out = io.StringIO()
    out.write("# 文档台账\n\n")
    out.write(f"共登记 {len(rows)} 份文档。状态说明：`已接入`=登记并解析完成，待打标。\n\n")
    out.write("| 编号 | 标题 | 适用地区 | 文档类型 | 发布时间 | 格式 | 段落数 | 字数 | 完整性 | 去重 | 源文件 |\n")
    out.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        out.write("| " + " | ".join(str(x) for x in r) + " |\n")
    (ws / "00-文档台账" / "台账.md").write_text(out.getvalue(), encoding="utf-8")
    dups = [r for r in rows if r[9] != "唯一"]
    print(f"台账重建完成：{len(rows)} 份；疑似重复 {len(dups)} 份")
    for r in dups:
        print(" 疑似重复:", r[0], r[1], "->", r[9])


if __name__ == "__main__":
    main(Path(sys.argv[1]))

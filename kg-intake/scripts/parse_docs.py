# -*- coding: utf-8 -*-
"""文档接入解析脚本：HTML/docx/PDF -> 带段落锚点的结构化 Markdown + 文档台账。

用法: python parse_docs.py <源文档根目录> <工作区目录>
源目录下按来源分子文件夹；来源码、地区和机构通过源目录下的
source-map.json 配置，未配置的文件夹分配稳定通用来源码。
"""
import sys, re, html, hashlib, io, json
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

def load_source_map(src_root: Path):
    """Load source-map.json and add stable mappings for unconfigured input locations."""
    config = src_root / "source-map.json"
    mapping = {}
    if config.exists():
        raw = json.loads(config.read_text(encoding="utf-8"))
        for folder, item in raw.items():
            if isinstance(item, list):
                mapping[folder] = tuple(item[:3])
            else:
                mapping[folder] = (
                    item["code"], item.get("region", "未知"), item.get("organization", "未知")
                )
    used_codes = {item[0] for item in mapping.values()}

    def unique_code(preferred: str, fallback_index: int) -> str:
        base = preferred or f"SRC{fallback_index:02d}"
        code = base
        suffix = 2
        while code in used_codes:
            code = f"{base[:6]}{suffix:02d}"
            suffix += 1
        used_codes.add(code)
        return code

    folders = sorted((path for path in src_root.iterdir() if path.is_dir()), key=lambda path: path.name)
    for index, path in enumerate(folders, 1):
        if path.name in mapping:
            continue
        ascii_code = re.sub(r"[^A-Z0-9]", "", path.name.upper())[:8]
        code = unique_code(ascii_code, index)
        mapping[path.name] = (code, "未知", "未知")
    direct_files = [path for path in src_root.iterdir() if path.is_file() and path.name != "source-map.json"]
    if direct_files and "." not in mapping:
        mapping["."] = (unique_code("ROOT", 0), "未知", "未知")
    return mapping


def iter_source_groups(src_root: Path, extensions) -> list[tuple[str, tuple, list[Path]]]:
    """Assign every supported file recursively to the most specific configured source."""
    allowed = {ext.lower() for ext in extensions}
    mapping = load_source_map(src_root)
    roots = []
    for folder, meta in mapping.items():
        root = (src_root / folder).resolve()
        if root.exists():
            roots.append((folder, meta, root))
    assigned = {folder: [] for folder, _meta, _root in roots}
    for path in sorted(src_root.rglob("*"), key=lambda item: item.relative_to(src_root).as_posix()):
        if not path.is_file() or path.name == "source-map.json" or path.suffix.lower() not in allowed:
            continue
        resolved = path.resolve()
        candidates = []
        for folder, meta, root in roots:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            candidates.append((len(root.parts), folder, meta))
        if not candidates:
            continue
        _depth, folder, _meta = max(candidates, key=lambda item: (item[0], item[1]))
        assigned[folder].append(path)
    return [
        (folder, meta, assigned[folder])
        for folder, meta, _root in sorted(roots, key=lambda item: (item[1][0], item[0]))
        if assigned[folder]
    ]

DOC_TYPE_RULES = [  # (关键词正则, 文档类型)
    (r"办事指南|须知|须准备", "办事指南"),
    (r"操作规程|办理规范", "业务规程"),
    (r"通知|办法|规定|文件|印发", "政策文件"),
    (r"您知道吗|可以这样", "宣传问答"),
]


def detect_doc_type(title: str) -> str:
    for pat, t in DOC_TYPE_RULES:
        if re.search(pat, title):
            return t
    return "其他"


def detect_publish_date(text: str) -> str:
    m = re.search(r"发布日期[：:]\s*(\d{4}-\d{1,2}-\d{1,2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text[-600:])  # 落款日期常在结尾
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"[〔\[](\d{4})[〕\]]\s*\d+\s*号", text)
    if m:
        return f"{m.group(1)}(文号年份)"
    return "未知"


def extract_html(path: Path) -> list[str]:
    from bs4 import BeautifulSoup, Comment
    raw = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    blocks = []
    # 政务页面常见正文容器优先；找不到再用 body
    body = (soup.select_one("div#zoom") or soup.select_one("div.article-conter")
            or soup.select_one("div.bt_content") or soup.body or soup)
    img_count = len(body.find_all("img"))
    if img_count:
        blocks.append(f"〔注：本页含 {img_count} 张图片，文字可能在图片中，需视觉识别〕")
    for el in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
        if el.attrs.get("__consumed__"):
            continue
        if el.name == "table":
            # 含多个 <p> 的视为布局表格，跳过让内部段落正常输出
            if len(el.find_all("p")) > 3:
                continue
            rows = []
            for tr in el.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                header_sep = "|" + "---|" * (rows[0].count("|") - 1)
                blocks.append("\n".join([rows[0], header_sep] + rows[1:]))
            for sub in el.find_all(["p", "li"]):
                sub.attrs["__consumed__"] = "1"
            continue
        if el.find("table"):
            continue
        txt = el.get_text(" ", strip=True)
        if txt:
            blocks.append(html.unescape(txt))
    if not blocks:  # 无块级结构时退化为按行切
        text = re.sub(r"<[^>]+>", "\n", raw)
        blocks = [l.strip() for l in html.unescape(text).split("\n") if l.strip()]
    return blocks


def extract_docx(path: Path) -> list[str]:
    import docx
    d = docx.Document(str(path))
    blocks = []
    for para in d.paragraphs:
        t = para.text.strip()
        if t:
            blocks.append(t)
    for tb in d.tables:
        rows = []
        for r in tb.rows:
            cells = [c.text.strip().replace("\n", " ") for c in r.cells]
            if any(cells):
                rows.append("| " + " | ".join(cells) + " |")
        if rows:
            header_sep = "|" + "---|" * (rows[0].count("|") - 1)
            blocks.append("\n".join([rows[0], header_sep] + rows[1:]))
    return blocks


def extract_pdf(path: Path) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    blocks = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        paras, buf = [], []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                if buf:
                    paras.append(" ".join(buf)); buf = []
                continue
            buf.append(line)
            if re.search(r"[。；：]$", line):  # 句末断段
                paras.append(" ".join(buf)); buf = []
        if buf:
            paras.append(" ".join(buf))
        for p in paras:
            if p.strip():
                blocks.append(f"〔页{i}〕{p.strip()}")
    return blocks


def extract_markdown(path: Path) -> list[str]:
    """Read an existing Markdown document without treating front matter as body content."""
    _meta, body = parse_front_matter(path.read_text(encoding="utf-8", errors="ignore"))
    return [line.rstrip() for line in body.splitlines() if line.strip()]


def parse_front_matter(text: str):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    meta, body = {}, text
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    return meta, body


def _write_registry(ws: Path, registry):
    reg_dir = ws / "00-文档台账"
    reg_dir.mkdir(parents=True, exist_ok=True)
    out = io.StringIO()
    out.write("# 文档台账\n\n")
    out.write(f"共登记 {len(registry)} 份文档。状态说明：`已接入`=登记并解析完成，待打标。\n\n")
    out.write("| 编号 | 标题 | 适用地区 | 文档类型 | 发布时间 | 格式 | 段落数 | 字数 | 完整性 | 去重 | 源文件 |\n")
    out.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in registry:
        out.write("| " + " | ".join(str(x) for x in r) + " |\n")
    (reg_dir / "台账.md").write_text(out.getvalue(), encoding="utf-8")
    _write_version_and_locator_index(ws, reg_dir)
    print(f"\n台账已写入 {reg_dir / '台账.md'}")


def _write_version_and_locator_index(ws: Path, reg_dir: Path):
    multimodal = {}
    multimodal_path = ws / "00-多模态清单" / "多模态清单.jsonl"
    if multimodal_path.exists():
        import json
        for line in multimodal_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                multimodal[row["document_id"]] = row
    versions, locators = [], []
    for path in sorted((ws / "10-解析文档").rglob("*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        doc_id = meta.get("编号", path.stem)
        mm = multimodal.get(doc_id, {})
        _source_sha = meta.get("源文件哈希", "未知")
        if _source_sha == "未知":
            _source_sha = mm.get("original_sha256", "未知")
        versions.append({
            "document_id": doc_id,
            "document_version": meta.get("内容哈希", "未知"),
            "source_sha256": _source_sha,
            "version_relation": meta.get("版本关系", "待确认"),
            "knowledge_role": meta.get("知识角色", "待确认"),
            "access_scope": meta.get("访问范围", "未知"),
            "classification": meta.get("密级", "未知"),
        })
        for match in re.finditer(r"^\[p(\d{3,})\]", body, re.M):
            anchor = f"{doc_id}#p{match.group(1)}"
            locators.append({
                "anchor": anchor,
                "document_id": doc_id,
                "original_path": mm.get("original_path"),
                "visual_path": mm.get("visual_path"),
                "structured_path": mm.get("structured_path"),
                "locator_type": "paragraph",
            })
    import json
    (reg_dir / "文档版本.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in versions), encoding="utf-8")
    (reg_dir / "定位器映射.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in locators), encoding="utf-8")


def main_from_md(ws: Path):
    """从 00-原始MD（kg-normalize 归一产物）解析为带锚点结构化文档 + 台账。"""
    registry, hash_seen = [], {}
    batch_id = f"INTAKE-{date.today().isoformat()}"
    src_root = ws / "00-原始MD"
    if not src_root.exists():
        print("未找到 00-原始MD/，请先运行 normalize.py 完成格式归一（kg-normalize 环节）")
        return
    allowed_states = {"归一完成", "已OCR-质检通过", "已视觉复核", "已人工复核"}
    source_files = [
        path for path in sorted(src_root.rglob("*.md"))
        if path.name != "转换清单.md" and "_图片" not in path.parts
    ]
    blocked = []
    if not source_files:
        blocked.append("00-原始MD中没有可接入的Markdown文本副本")
    markdown_ids = set()
    for source_file in source_files:
        meta, _body = parse_front_matter(source_file.read_text(encoding="utf-8"))
        doc_id = meta.get("编号", source_file.stem)
        if doc_id in markdown_ids:
            blocked.append(f"文本副本文档ID重复:{doc_id}")
        markdown_ids.add(doc_id)
        status = meta.get("归一状态", "缺失")
        if status not in allowed_states:
            blocked.append(f"{doc_id}={status}")
    # 加载多模态清单，用于补全源文件哈希等归一产物未写入 front matter 的字段
    multimodal = {}
    multimodal_path = ws / "00-多模态清单" / "多模态清单.jsonl"
    if multimodal_path.exists():
        for line in multimodal_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                multimodal[row["document_id"]] = row
    else:
        blocked.append("缺少多模态清单")
    missing_in_manifest = markdown_ids - set(multimodal)
    missing_markdown = set(multimodal) - markdown_ids
    if missing_in_manifest:
        blocked.append("文本副本未登记多模态清单:" + ",".join(sorted(missing_in_manifest)))
    if missing_markdown:
        blocked.append("多模态清单缺少文本副本:" + ",".join(sorted(missing_markdown)))
    if blocked:
        raise SystemExit("kg-normalize归一验收未通过，禁止接入: " + "，".join(blocked))

    parsed_root = ws / "10-解析文档"
    for f in source_files:
        relative = f.relative_to(src_root)
        code = relative.parts[0] if len(relative.parts) > 1 else (f.stem.rsplit("-", 1)[0] or "ROOT")
        out_dir = parsed_root / code
        out_dir.mkdir(parents=True, exist_ok=True)
        meta, body = parse_front_matter(f.read_text(encoding="utf-8"))
        doc_id = meta.get("编号", f.stem)
        title = meta.get("标题", doc_id)
        pub = meta.get("发布时间", "未知")
        mm = multimodal.get(doc_id, {})
        source_sha = meta.get("源文件哈希", "未知")
        if source_sha == "未知":
            source_sha = mm.get("original_sha256", "未知")
        paras = []
        for line in body.split("\n"):
            s = line.strip()
            if not s or s.startswith("# "):
                continue
            paras.append(re.sub(r"^>\s*", "", s))
        full = "".join(paras)
        h = hashlib.sha256(re.sub(r"\s+", "", full).encode()).hexdigest()
        dup = hash_seen.get(h, "")
        if not dup:
            hash_seen[h] = doc_id
        dtype = detect_doc_type(title)
        chars = len(re.sub(r"\s+", "", full))
        comp = []
        if pub == "未知":
            comp.append("缺发布时间")
        if chars < 100:
            comp.append("正文过短")
        comp = "；".join(comp) if comp else "完整"
        lines = ["---", f"编号: {doc_id}", f"标题: {title}",
                 f"地区: {meta.get('地区','')}", f"发布机构: {meta.get('发布机构','')}",
                 f"文档类型: {dtype}", f"发布时间: {pub}", "生效时间: 未知", "失效时间: 未知",
                 f"源文件: {meta.get('源文件','')}", f"源文件哈希: {source_sha}", f"内容哈希: {h}",
                 "内容哈希算法: sha256-normalized-v1", f"接入批次: {batch_id}",
                 f"接入时间: {date.today().isoformat()}", f"来源网址: {meta.get('来源网址','未知')}",
                 f"访问范围: {meta.get('访问范围','未知')}", f"密级: {meta.get('密级','未知')}",
                 f"知识角色: {meta.get('知识角色','待确认')}", f"来源权威级别: {meta.get('来源权威级别','待确认')}",
                 f"项目: {meta.get('项目','未关联')}", f"版本关系: {meta.get('版本关系','待确认')}",
                 f"模型出域策略: {meta.get('模型出域策略','需审批')}", "责任人: 未指定", f"完整性: {comp}",
                 "上游: 00-原始MD（格式归一产物）", "---", "", f"# {title}", ""]
        for i, p in enumerate(paras, 1):
            lines.append(f"[p{i:03d}] {p}")
        (out_dir / f"{doc_id}.md").write_text("\n".join(lines), encoding="utf-8")
        registry.append((doc_id, title, meta.get("地区", ""), dtype, pub,
                         meta.get("原始格式", ""), len(paras), chars, comp,
                         f"重复于{dup}" if dup else "唯一", meta.get("源文件", "")))
        print(f"{doc_id}  {comp:<16} {len(paras):>3}段 {chars:>6}字  {title[:26]}")
    _write_registry(ws, registry)


def main(src_root: Path, ws: Path):
    registry, hash_seen = [], {}
    batch_id = f"INTAKE-{date.today().isoformat()}"
    parsed_root = ws / "10-解析文档"
    direct_exts = (".html", ".htm", ".docx", ".pdf", ".md", ".markdown")
    for folder, (code, region, org), files in iter_source_groups(src_root, direct_exts):
        out_dir = parsed_root / code
        out_dir.mkdir(parents=True, exist_ok=True)
        for idx, f in enumerate(files, 1):
            doc_id = f"{code}-{idx:03d}"
            title = re.sub(r"^\d+\.", "", f.stem).strip()
            try:
                if f.suffix.lower() in (".html", ".htm"):
                    blocks = extract_html(f)
                elif f.suffix.lower() == ".docx":
                    blocks = extract_docx(f)
                elif f.suffix.lower() in (".md", ".markdown"):
                    blocks = extract_markdown(f)
                else:
                    blocks = extract_pdf(f)
                err = ""
            except Exception as e:
                blocks, err = [], f"{type(e).__name__}: {e}"
            full = "\n".join(blocks)
            h = hashlib.sha256(re.sub(r"\s+", "", full).encode()).hexdigest()
            source_sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
            dup = hash_seen.get(h, "")
            if not dup:
                hash_seen[h] = doc_id
            pub = detect_publish_date(full)
            if pub == "未知" and f.suffix.lower() in (".html", ".htm"):
                # 发布日期常在正文容器之外的页头区域
                raw_text = re.sub(r"<[^>]+>", " ", f.read_text(encoding="utf-8", errors="ignore")[:20000])
                pub = detect_publish_date(raw_text)
            dtype = detect_doc_type(title)
            chars = len(full)
            completeness = []
            if pub == "未知":
                completeness.append("缺发布时间")
            if chars < 100:
                completeness.append("正文过短")
            if err:
                completeness.append("解析失败")
            comp = "；".join(completeness) if completeness else "完整"
            lines = [
                "---",
                f"编号: {doc_id}",
                f"标题: {title}",
                f"地区: {region}",
                f"发布机构: {org}",
                f"文档类型: {dtype}",
                f"发布时间: {pub}",
                "生效时间: 未知",
                "失效时间: 未知",
                f"源文件: {f.name}",
                f"源文件哈希: {source_sha256}",
                f"内容哈希: {h}",
                "内容哈希算法: sha256-normalized-v1",
                f"接入批次: {batch_id}",
                f"接入时间: {date.today().isoformat()}",
                "来源网址: 未知",
                "访问范围: 未知",
                "密级: 未知",
                "知识角色: 待确认",
                "来源权威级别: 待确认",
                "项目: 未关联",
                "版本关系: 待确认",
                "模型出域策略: 需审批",
                "责任人: 未指定",
                f"完整性: {comp}",
                "---",
                "",
                f"# {title}",
                "",
            ]
            for i, b in enumerate(blocks, 1):
                if "\n" in b:  # 表格块
                    lines.append(f"[p{i:03d}]\n{b}\n")
                else:
                    lines.append(f"[p{i:03d}] {b}")
            (out_dir / f"{doc_id}.md").write_text("\n".join(lines), encoding="utf-8")
            registry.append((doc_id, title, region, dtype, pub, f.suffix.lower()[1:],
                             len(blocks), chars, comp, f"重复于{dup}" if dup else "唯一", f.name))
            print(f"{doc_id}  {comp:<6} {len(blocks):>3}段 {chars:>6}字  {title[:30]}")

    _write_registry(ws, registry)


if __name__ == "__main__":
    # 标准流程：先 kg-normalize 出 00-原始MD，再 --from-md 做结构化解析
    #   python parse_docs.py --from-md <工作区目录>
    # 已弃用的旧流程（绕过归一直接解析原始文件，与 kg-normalize 抽取逻辑重复维护，
    # 且不产出原件快照/多模态清单/识别质检）：必须显式加 --legacy 才能执行
    #   python parse_docs.py --legacy <源文档根目录> <工作区目录>
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--from-md" in sys.argv:
        main_from_md(Path(pos[0]))
    elif "--legacy" in sys.argv:
        print("[弃用警告] --legacy 模式绕过 kg-normalize，缺少原件快照、多模态清单与识别质检，"
              "仅用于历史工作区兼容回归；新批次一律使用 normalize.py + --from-md。")
        main(Path(pos[0]), Path(pos[1]))
    else:
        raise SystemExit(
            "用法: python parse_docs.py --from-md <工作区目录>\n"
            "旧流程已弃用；如确需绕过归一直接解析原始文件，显式使用: python parse_docs.py --legacy <源文档根目录> <工作区目录>"
        )

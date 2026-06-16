# -*- coding: utf-8 -*-
"""格式归一（治理第 0 环节）：把原始异构文件统一转成纯文本 Markdown 原料。

用法: python to_markdown.py <源文档根目录> <本次工作区目录>
例:   python to_markdown.py 公积金场景 治理工作区-20260613-1530

职责（区别于 kg-intake）:
- 本步只做"格式数字化/归一"——docx/html/pdf/图片型 → 统一纯文本 md，忠实原文、不加治理锚点；
- 为每份原料分配文档编号（来源码-序号），写最小 front matter；
- 图片型文档：导出内嵌图片，正文标注"待视觉转写"，留给 kg-intake 处理；
- 产物：<工作区>/00-原始MD/{来源码}/{编号}.md + 00-原始MD/转换清单.md。
复用 parse_docs 的解析器，零重复逻辑。
"""
import sys, re, base64, io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse_docs as P                       # 复用 SOURCE_MAP / extract_* / detect_*

sys.stdout.reconfigure(encoding="utf-8")
EXTS = (".docx", ".html", ".htm", ".pdf")


def extract_pdf(path: Path):
    from pypdf import PdfReader
    blocks = []
    for i, page in enumerate(PdfReader(str(path)).pages, 1):
        for para in (page.extract_text() or "").split("\n"):
            if para.strip():
                blocks.append(f"〔页{i}〕{para.strip()}")
    return blocks


def dump_images(raw_html: str, out_dir: Path, doc_id: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for ext, b64 in re.findall(r"data:image/(\w+);base64,([A-Za-z0-9+/=]+)", raw_html):
        try:
            (out_dir / f"{doc_id}-img{n+1}.{ext}").write_bytes(base64.b64decode(b64))
            n += 1
        except Exception:
            pass
    return n


_ocr_engine, _ocr_tried = None, False


def get_ocr():
    """懒加载离线 OCR 引擎（rapidocr-onnxruntime，自带模型，离线可用）。"""
    global _ocr_engine, _ocr_tried
    if not _ocr_tried:
        _ocr_tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        except Exception:
            _ocr_engine = None
    return _ocr_engine


def ocr_doc_images(img_root: Path, doc_id: str, img_n: int):
    """对一份图片型文档导出的所有图片做 OCR，返回 (识别文字行, 是否成功)。"""
    eng = get_ocr()
    if eng is None:
        return [], False
    lines = []
    for i in range(1, img_n + 1):
        p = next((img_root / f"{doc_id}-img{i}.{e}" for e in ("png", "jpeg", "jpg")
                  if (img_root / f"{doc_id}-img{i}.{e}").exists()), None)
        if not p:
            continue
        try:
            res, _ = eng(str(p))
            if res:
                if img_n > 1:
                    lines.append(f"〔图{i}〕")
                lines += [r[1].strip() for r in res if r[1].strip()]
        except Exception:
            pass
    return lines, bool(lines)


def main(src_root: Path, ws: Path):
    out_root = ws / "00-原始MD"
    img_root = out_root / "_图片"
    rows = []
    for folder, (code, region, org) in P.SOURCE_MAP.items():
        d = src_root / folder
        if not d.exists():
            continue
        out_dir = out_root / code
        out_dir.mkdir(parents=True, exist_ok=True)
        files = [x for x in sorted(d.iterdir(), key=lambda p: p.name)
                 if x.suffix.lower() in EXTS]
        for idx, f in enumerate(files, 1):
            doc_id = f"{code}-{idx:03d}"
            title = re.sub(r"^\d+\.", "", f.stem).strip()
            ext = f.suffix.lower()
            img_n = 0
            raw = ""
            try:
                if ext in (".html", ".htm"):
                    blocks = P.extract_html(f)
                    raw = f.read_text(encoding="utf-8", errors="ignore")
                    img_n = dump_images(raw, img_root, doc_id) if "data:image" in raw else 0
                elif ext == ".docx":
                    blocks = P.extract_docx(f)
                else:
                    blocks = extract_pdf(f)
                err = ""
            except Exception as e:
                blocks, err = [], f"{type(e).__name__}: {e}"
            full = "\n".join(blocks)
            chars = len(re.sub(r"\s+", "", full))
            pub = P.detect_publish_date(full)
            if pub == "未知" and ext in (".html", ".htm") and raw:
                pub = P.detect_publish_date(re.sub(r"<[^>]+>", " ", raw[:20000]))
            图片型 = (img_n > 0 and chars < 200) or chars < 100
            fmt = ext.lstrip(".")
            if err:
                状态, body = "解析失败", [b for b in blocks if b.strip()]
            elif 图片型:
                # 图片型文档：在本（格式归一）环节即把图片内容 OCR 识别为 md 文字
                ocr_lines, ok = ocr_doc_images(img_root, doc_id, img_n)
                if ok:
                    状态 = "图片型-已OCR识别"
                    chars = len("".join(ocr_lines).replace(" ", ""))
                    pub = P.detect_publish_date("".join(ocr_lines)) if pub == "未知" else pub
                    body = [f"> 📷 本文为图片型文档（{img_n} 张图），以下正文由 OCR（rapidocr）在格式归一环节自动识别；"
                            "数字/表格/印章请以原图复核。", ""] + ocr_lines
                else:
                    状态 = "图片型-待视觉转写"
                    body = [f"> ⚠️ 本文为图片型文档（内嵌 {img_n} 张图片，已导出至 00-原始MD/_图片/）。",
                            "> OCR 引擎不可用，请在本（kg-normalize）环节用大模型视觉转写补全后再进入接入。", ""] + \
                           [b for b in blocks if b.strip()]
            else:
                状态, body = "已转换", [b for b in blocks if b.strip()]
            lines = ["---", f"编号: {doc_id}", f"标题: {title}", f"地区: {region}",
                     f"发布机构: {org}", f"原始格式: {fmt}", f"源文件: {f.name}",
                     f"发布时间: {pub}", f"字数: {chars}", f"内嵌图片: {img_n}",
                     f"归一状态: {状态}", "---", "", f"# {title}", ""] + body
            (out_dir / f"{doc_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            rows.append((doc_id, title, fmt, chars, img_n, 状态))
            print(f"{doc_id}  {fmt:<4} {chars:>6}字  图{img_n}  {状态:<14} {title[:28]}")

    out = io.StringIO()
    out.write("# 格式归一转换清单\n\n")
    out.write(f"源目录：`{src_root}` → 本次工作区：`{ws.name}`\n\n")
    n_img = sum(1 for r in rows if "图片型" in r[5])
    n_ocr = sum(1 for r in rows if "已OCR" in r[5])
    out.write(f"共归一 {len(rows)} 份原始文件为统一 Markdown 原料。"
              f"其中图片型 {n_img} 份，已在本环节 OCR 识别为文字 {n_ocr} 份"
              f"（如需更高精度可用大模型视觉复核）。归一后所有文档均为完整 md，可直接进入接入环节。\n\n")
    out.write("| 编号 | 标题 | 原始格式 | 字数 | 内嵌图片 | 归一状态 |\n|---|---|---|---|---|---|\n")
    for r in rows:
        out.write("| " + " | ".join(str(x) for x in r) + " |\n")
    (out_root / "转换清单.md").write_text(out.getvalue(), encoding="utf-8")
    by_fmt = {}
    for r in rows:
        by_fmt[r[2]] = by_fmt.get(r[2], 0) + 1
    print(f"\n归一完成 {len(rows)} 份 → {out_root}")
    print("格式分布:", "，".join(f"{k} {v}份" for k, v in sorted(by_fmt.items())))
    print(f"转换清单: {out_root / '转换清单.md'}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python to_markdown.py <源文档根目录> <本次工作区目录>")
        sys.exit(1)
    main(Path(sys.argv[1]), Path(sys.argv[2]))

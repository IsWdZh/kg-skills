# -*- coding: utf-8 -*-
"""治理第0环节（单趟归一）。

一次遍历源目录，为每份文档生成：原件快照、统一图像库（00-视觉快照）、结构化对象、
Markdown 文本副本、识别质检（仅识别链路文档）和多模态清单（layout_version=2，工作区相对路径）。

按需物化策略：
- 图像只存一份，统一在 00-视觉快照/{doc-id}/；00-原始MD 不再存图片；
- 纯文本文档的结构化对象为 stub（structured_level=stub）；
- 文本型 PDF 不整页渲染，只登记 page_count 与文本块坐标；图片型 PDF 渲染一次供 OCR；
- 识别质检报告仅在发生 OCR/视觉识别时生成；
- 已复核（已视觉复核/已人工复核/结构识别失败）的文档重跑时不重生成文本副本与质检报告。
"""

import base64
import io
import json
import os
import re
import shutil
import sys
import zipfile
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "kg-intake" / "scripts"))
import parse_docs as P

sys.stdout.reconfigure(encoding="utf-8")

LAYOUT_VERSION = 2
EXTS = (".docx", ".html", ".htm", ".pdf", ".xlsx", ".xlsm", ".pptx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".md", ".markdown")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
PASS_STATES = {"归一完成", "已OCR-质检通过", "已视觉复核", "已人工复核"}
REVIEW_PRESERVE_STATES = {"已视觉复核", "已人工复核", "结构识别失败"}
MEAN_THRESHOLD = float(os.getenv("KG_OCR_MEAN_CONFIDENCE", "0.93"))
P10_THRESHOLD = float(os.getenv("KG_OCR_P10_CONFIDENCE", "0.80"))
LOW_RATIO_THRESHOLD = float(os.getenv("KG_OCR_LOW_CONFIDENCE_RATIO", "0.10"))
LOW_ITEM_THRESHOLD = float(os.getenv("KG_OCR_LOW_ITEM_CONFIDENCE", "0.80"))

_ocr_engine = None
_ocr_tried = False


def rel(path: Path, ws: Path) -> str:
    return path.relative_to(ws).as_posix()


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


# ---------- 文本提取 ----------

def extract_pdf_text(path: Path) -> list[str]:
    from pypdf import PdfReader
    blocks = []
    for index, page in enumerate(PdfReader(str(path)).pages, 1):
        blocks.extend(f"〔页{index}〕{line.strip()}" for line in (page.extract_text() or "").splitlines() if line.strip())
    return blocks


def extract_xlsx(path: Path) -> list[str]:
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=False)
    blocks = []
    for sheet in workbook.worksheets:
        blocks.append(f"## 工作表：{sheet.title}")
        for row in sheet.iter_rows():
            values = ["" if cell.value is None else str(cell.value) for cell in row]
            if any(value.strip() for value in values):
                blocks.append(" | ".join(values))
    return blocks


def extract_pptx_text(path: Path) -> list[str]:
    from pptx import Presentation
    blocks = []
    for index, slide in enumerate(Presentation(path).slides, 1):
        blocks.append(f"## 幻灯片 {index}")
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                blocks.extend(line.strip() for line in shape.text.splitlines() if line.strip())
    return blocks


def extract_md(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    _meta, body = P.parse_front_matter(text)
    return [body.rstrip()] if body.strip() else []


# ---------- 视觉资产（统一图像库） ----------

def dump_docx_images(path: Path, visual_dir: Path) -> list[Path]:
    images = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(x for x in archive.namelist() if x.startswith("word/media/"))
            if names:
                visual_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                suffix = Path(name).suffix or ".bin"
                target = visual_dir / f"image-{len(images) + 1:04d}{suffix}"
                target.write_bytes(archive.read(name))
                images.append(target)
    except Exception:
        return images
    return images


def dump_html_images(raw_html: str, visual_dir: Path) -> list[Path]:
    images = []
    for ext, encoded in re.findall(r"data:image/(\w+);base64,([A-Za-z0-9+/=]+)", raw_html):
        try:
            data = base64.b64decode(encoded)
        except Exception:
            continue
        visual_dir.mkdir(parents=True, exist_ok=True)
        target = visual_dir / f"image-{len(images) + 1:04d}.{ext}"
        target.write_bytes(data)
        images.append(target)
    return images


def render_pdf_pages(path: Path, visual_dir: Path) -> list[Path]:
    try:
        import fitz
    except Exception:
        return []
    images = []
    document = fitz.open(path)
    visual_dir.mkdir(parents=True, exist_ok=True)
    for index, page in enumerate(document, 1):
        target = visual_dir / f"page-{index:04d}.png"
        page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(target)
        images.append(target)
    return images


# ---------- 结构化对象 ----------

def docx_structured(path: Path, image_rels: list[str]) -> tuple[dict, str, list[str]]:
    errors = []
    tables = []
    try:
        from docx import Document
        from docx.oxml.ns import qn
        document = Document(path)
        for t_index, table in enumerate(document.tables, 1):
            rows = []
            for tr in table._tbl.tr_lst:
                cells = []
                for tc in tr.tc_lst:
                    text = "".join(t.text or "" for t in tc.findall(".//" + qn("w:t"))).strip()
                    grid_span, v_merge = 1, None
                    tc_pr = tc.tcPr
                    if tc_pr is not None:
                        gs = tc_pr.find(qn("w:gridSpan"))
                        if gs is not None:
                            grid_span = int(gs.get(qn("w:val")) or 1)
                        vm = tc_pr.find(qn("w:vMerge"))
                        if vm is not None:
                            v_merge = vm.get(qn("w:val")) or "continue"
                    cells.append({"text": text, "grid_span": grid_span, "v_merge": v_merge})
                rows.append(cells)
            tables.append({"table": t_index, "rows": rows})
    except Exception as exc:
        errors.append(f"docx structure extraction unavailable: {exc}")
    if tables or image_rels:
        return {"type": "docx", "tables": tables, "images": image_rels}, "full", errors
    return {"type": "docx", "status": "no_complex_structure"}, "stub", errors


def xlsx_structured(path: Path) -> tuple[dict, str, list[str]]:
    errors = []
    result = {"type": "xlsx", "sheets": []}
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=False, data_only=False)
        for sheet in workbook.worksheets:
            cells = []
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        cells.append({"coordinate": cell.coordinate, "value": str(cell.value), "data_type": cell.data_type})
            result["sheets"].append({"title": sheet.title, "merged_ranges": [str(x) for x in sheet.merged_cells.ranges], "cells": cells})
    except Exception as exc:
        errors.append(f"xlsx structure extraction unavailable: {exc}")
    return result, "full", errors


def pptx_structured(path: Path, visual_dir: Path, ws: Path) -> tuple[dict, str, list[Path], list[str]]:
    errors = []
    images: list[Path] = []
    result = {"type": "pptx", "slides": []}
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        for s_index, slide in enumerate(Presentation(path).slides, 1):
            shapes = []
            for shape in slide.shapes:
                item = {"name": shape.name, "left": shape.left, "top": shape.top, "width": shape.width, "height": shape.height}
                if hasattr(shape, "text"):
                    item["text"] = shape.text
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    visual_dir.mkdir(parents=True, exist_ok=True)
                    target = visual_dir / f"slide-{s_index:04d}-image-{len(images) + 1:04d}.{shape.image.ext}"
                    target.write_bytes(shape.image.blob)
                    images.append(target)
                    item["image"] = rel(target, ws)
                shapes.append(item)
            result["slides"].append({"slide": s_index, "shapes": shapes})
    except Exception as exc:
        errors.append(f"pptx structure extraction unavailable: {exc}")
    return result, "full", images, errors


def pdf_structured(path: Path, page_snapshots: list[Path], ws: Path) -> tuple[dict, str, list[str]]:
    errors = []
    pages = []
    page_count = 0
    try:
        import fitz
        document = fitz.open(path)
        page_count = len(document)
        snapshot_by_page = {index + 1: rel(target, ws) for index, target in enumerate(page_snapshots)}
        for index, page in enumerate(document, 1):
            pages.append({"page": index, "text_blocks": page.get_text("blocks"), "snapshot": snapshot_by_page.get(index)})
    except Exception as exc:
        errors.append(f"pdf structure extraction unavailable: {exc}")
        return {"type": "pdf", "status": "structure_unavailable"}, "stub", errors
    return {"type": "pdf", "page_count": page_count, "pages": pages}, "full", errors


# ---------- OCR 与质量分流 ----------

def get_ocr():
    global _ocr_engine, _ocr_tried
    if not _ocr_tried:
        _ocr_tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        except Exception:
            _ocr_engine = None
    return _ocr_engine


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))]


def layout_reasons(entries: list[dict], image_path: Path) -> tuple[list[str], list[str]]:
    reasons = []
    object_types = []
    text = " ".join(item["text"] for item in entries)
    if re.search(r"(?:金额|合计|总计|比例|百分比|编号|日期|印章|签字|盖章)|\d{4}[年./-]\d{1,2}|\d+(?:\.\d+)?%", text):
        reasons.append("包含需逐项复核的数字、日期、编号、比例或签章字段")
        object_types.append("critical_fields")
    boxes = [item["bbox"] for item in entries if item.get("bbox") and len(item["bbox"]) >= 4]
    rows = []
    for box in boxes:
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        center_y = sum(ys) / len(ys)
        height = max(ys) - min(ys)
        placed = False
        for row in rows:
            if abs(row["y"] - center_y) <= max(row["height"], height, 8) * 0.7:
                row["items"] += 1
                placed = True
                break
        if not placed:
            rows.append({"y": center_y, "height": height, "items": 1})
    multi_item_rows = sum(row["items"] >= 2 for row in rows)
    if multi_item_rows >= 3:
        reasons.append("检测到多列或表格化版面")
        object_types.append("table_or_multicolumn")
    if re.search(r"流程图|开始|结束|判断|分支|泳道", text) and (multi_item_rows >= 2 or len(entries) >= 12):
        reasons.append("疑似流程图或带连线的结构图")
        object_types.append("flow_or_diagram")
    try:
        from PIL import Image
        with Image.open(image_path) as image:
            if image.width < 800 or image.height < 800:
                reasons.append("图像分辨率较低")
    except Exception:
        pass
    return list(dict.fromkeys(reasons)), list(dict.fromkeys(object_types))


def recognize_image(path: Path) -> dict:
    engine = get_ocr()
    base = {"image": str(path), "engine": "rapidocr-onnxruntime", "entries": [], "reasons": [], "object_types": []}
    if engine is None:
        return {**base, "status": "待视觉转写", "reasons": ["OCR引擎不可用"]}
    try:
        result, _ = engine(str(path))
    except Exception as exc:
        return {**base, "status": "待视觉转写", "reasons": [f"OCR执行失败: {type(exc).__name__}"]}
    for item in result or []:
        if len(item) < 2 or not str(item[1]).strip():
            continue
        try:
            confidence = float(item[2]) if len(item) > 2 else None
        except (TypeError, ValueError):
            confidence = None
        bbox = item[0].tolist() if hasattr(item[0], "tolist") else item[0]
        base["entries"].append({"bbox": bbox, "text": str(item[1]).strip(), "confidence": confidence})
    if not base["entries"]:
        return {**base, "status": "待视觉转写", "reasons": ["OCR未返回有效文字"]}
    confidences = [item["confidence"] for item in base["entries"] if item["confidence"] is not None]
    mean = sum(confidences) / len(confidences) if confidences else None
    p10 = percentile(confidences, 0.10)
    low_ratio = sum(value < LOW_ITEM_THRESHOLD for value in confidences) / len(confidences) if confidences else 1.0
    base["metrics"] = {"mean_confidence": mean, "p10_confidence": p10, "low_confidence_ratio": low_ratio, "text_blocks": len(base["entries"])}
    reasons, object_types = layout_reasons(base["entries"], path)
    if mean is None or mean < MEAN_THRESHOLD:
        reasons.append(f"平均置信度未达门槛{MEAN_THRESHOLD:.2f}")
    if p10 is None or p10 < P10_THRESHOLD:
        reasons.append(f"低分位置信度未达门槛{P10_THRESHOLD:.2f}")
    if low_ratio > LOW_RATIO_THRESHOLD:
        reasons.append(f"低置信文字比例超过门槛{LOW_RATIO_THRESHOLD:.0%}")
    base["reasons"] = list(dict.fromkeys(reasons))
    base["object_types"] = object_types
    base["status"] = "已OCR-待视觉复核" if reasons else "已OCR-质检通过"
    return base


def aggregate_reports(reports: list[dict]) -> dict:
    if not reports:
        return {
            "status": "待视觉转写", "reasons": ["没有可识别的视觉快照"], "object_types": [], "images": [],
            "review": {"method": None, "reviewer": None, "reviewed_at": None, "notes": None, "unresolved_items": []},
        }
    statuses = {report["status"] for report in reports}
    if "待视觉转写" in statuses:
        status = "待视觉转写"
    elif "已OCR-待视觉复核" in statuses:
        status = "已OCR-待视觉复核"
    else:
        status = "已OCR-质检通过"
    return {
        "status": status,
        "reasons": list(dict.fromkeys(reason for report in reports for reason in report.get("reasons", []))),
        "object_types": list(dict.fromkeys(kind for report in reports for kind in report.get("object_types", []))),
        "thresholds": {"mean_confidence": MEAN_THRESHOLD, "p10_confidence": P10_THRESHOLD, "low_confidence_ratio": LOW_RATIO_THRESHOLD},
        "images": reports,
        "review": {"method": None, "reviewer": None, "reviewed_at": None, "notes": None, "unresolved_items": []},
    }


# ---------- 单文档处理 ----------

def front_matter_of(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    head = text.split("---", 2)[1]
    result = {}
    for line in head.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def process_doc(source: Path, doc_id: str, code: str, region: str, org: str, src_root: Path, ws: Path) -> dict:
    ext = source.suffix.lower()
    original_dir = ws / "00-原始资料" / code
    original_dir.mkdir(parents=True, exist_ok=True)
    original = original_dir / f"{doc_id}--{source.name}"
    shutil.copy2(source, original)

    visual_dir = ws / "00-视觉快照" / doc_id
    structured_dir = ws / "00-结构化对象"
    structured_dir.mkdir(parents=True, exist_ok=True)
    structured_path = structured_dir / f"{doc_id}.json"
    md_dir = ws / "00-原始MD" / code
    md_dir.mkdir(parents=True, exist_ok=True)
    md_path = md_dir / f"{doc_id}.md"
    quality_root = ws / "00-识别质检"
    quality_root.mkdir(parents=True, exist_ok=True)
    quality_path = quality_root / f"{doc_id}.json"
    source_ref = source.relative_to(src_root).as_posix()

    # 重跑保护：已复核/已裁决的文档不重生成文本副本与质检报告
    preserved_meta = front_matter_of(md_path) if md_path.exists() else {}
    if preserved_meta.get("归一状态") in REVIEW_PRESERVE_STATES:
        status = preserved_meta["归一状态"]
        body = md_path.read_text(encoding="utf-8").split("---", 2)[-1]
        chars = len(re.sub(r"\s+", "", body))
        image_count = int(preserved_meta.get("内嵌图片") or 0)
        title = preserved_meta.get("标题") or source.stem
        row = {
            "document_id": doc_id, "source_name": source_ref, "title": title,
            "original_path": rel(original, ws), "original_sha256": digest(original),
            "markdown_path": rel(md_path, ws),
            "visual_path": rel(visual_dir, ws) if visual_dir.exists() else None,
            "visual_required": visual_dir.exists() or image_count > 0,
            "visual_skip_reason": None,
            "structured_path": rel(structured_path, ws) if structured_path.exists() else None,
            "structured_level": "full" if structured_path.exists() else "stub",
            "quality_report_path": rel(quality_path, ws) if quality_path.exists() else None,
            "image_count": image_count,
            "normalization_status": status, "errors": [],
            "status": "complete" if status in PASS_STATES else "blocked",
            "layout_version": LAYOUT_VERSION, "preserved": True,
        }
        if not structured_path.exists():
            structured_path.write_text(json.dumps({"type": ext.lstrip("."), "status": "preserved_no_structure"}, ensure_ascii=False, indent=2), encoding="utf-8")
            row["structured_path"] = rel(structured_path, ws)
        return {**row, "clist": (doc_id, title, ext.lstrip("."), chars, image_count, status)}

    blocks, error, raw, source_meta = [], "", "", {}
    images: list[Path] = []
    structured, structured_level, structure_errors = {"type": ext.lstrip("."), "status": "not_applicable"}, "stub", []
    page_count = None
    try:
        if ext in (".html", ".htm"):
            blocks = P.extract_html(source)
            raw = source.read_text(encoding="utf-8", errors="ignore")
            images = dump_html_images(raw, visual_dir)
            if images:
                structured, structured_level = {"type": "html", "images": [rel(x, ws) for x in images]}, "full"
            else:
                structured, structured_level = {"type": "html", "status": "no_complex_structure"}, "stub"
        elif ext == ".docx":
            blocks = P.extract_docx(source)
            images = dump_docx_images(source, visual_dir)
            structured, structured_level, structure_errors = docx_structured(source, [rel(x, ws) for x in images])
        elif ext in (".xlsx", ".xlsm"):
            blocks = extract_xlsx(source)
            structured, structured_level, structure_errors = xlsx_structured(source)
        elif ext == ".pptx":
            blocks = extract_pptx_text(source)
            structured, structured_level, images, structure_errors = pptx_structured(source, visual_dir, ws)
        elif ext in (".md", ".markdown"):
            source_meta, _body = P.parse_front_matter(source.read_text(encoding="utf-8", errors="ignore"))
            blocks = extract_md(source)
            structured, structured_level = {"type": "markdown", "status": "text_passthrough"}, "stub"
        elif ext in IMAGE_EXTS:
            visual_dir.mkdir(parents=True, exist_ok=True)
            target = visual_dir / f"image{ext}"
            shutil.copy2(source, target)
            images = [target]
            structured, structured_level = {"type": "image", "snapshot": rel(target, ws)}, "full"
        else:  # pdf
            blocks = extract_pdf_text(source)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    full = "\n".join(blocks)
    chars = len(re.sub(r"\s+", "", full))
    image_based = ext in IMAGE_EXTS or (len(images) > 0 and chars < 200) or (ext == ".pdf" and chars < 100)
    if ext == ".pdf":
        page_snapshots = render_pdf_pages(source, visual_dir) if image_based else []
        if image_based:
            images = page_snapshots
        structured, structured_level, structure_errors = pdf_structured(source, page_snapshots, ws)
        page_count = structured.get("page_count")

    image_count = len(images)
    reports = [recognize_image(path) for path in images] if image_based else []
    quality = aggregate_reports(reports) if image_based else None
    status = quality["status"] if quality else ("解析失败" if error else "归一完成")
    if error and quality:
        quality["status"] = status = "解析失败"
        quality["reasons"] = [error]

    ocr_lines = []
    for number, report in enumerate(reports, 1):
        if len(reports) > 1:
            ocr_lines.append(f"〔图{number}〕")
        ocr_lines.extend(item["text"] for item in report.get("entries", []))
    if image_based:
        blocks = [
            f"> 图片识别状态：{status}。OCR仅为候选文本；复杂结构、数字和关键字段须按识别质检报告对照原图。",
            f"> 质检报告：00-识别质检/{doc_id}.json",
            f"> 视觉资产：00-视觉快照/{doc_id}/", "",
            *ocr_lines,
        ]

    title = source_meta.get("标题") or re.sub(r"^\d+\.", "", source.stem).strip()
    region_value = source_meta.get("地区") or region
    org_value = source_meta.get("发布机构") or source_meta.get("机构") or org
    pub = source_meta.get("发布时间") or P.detect_publish_date("\n".join(ocr_lines) or full)
    if pub == "未知" and raw:
        pub = P.detect_publish_date(re.sub(r"<[^>]+>", " ", raw[:20000]))
    chars = len(re.sub(r"\s+", "", "\n".join(blocks)))

    structured_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
    if quality is not None:
        quality.update({"document_id": doc_id, "source_file": source_ref, "markdown": rel(md_path, ws)})
        quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    elif quality_path.exists():
        quality_path.unlink()

    reasons = "；".join(quality.get("reasons", [])) if quality else ("" if not error else error)
    reasons = reasons or "无"
    method = "OCR+质量分流" if image_based else "原生结构/文本提取"
    lines = [
        "---", f"编号: {doc_id}", f"标题: {title}", f"地区: {region_value}", f"发布机构: {org_value}",
        f"原始格式: {ext.lstrip('.')}", f"源文件: {source_ref}", f"发布时间: {pub}", f"字数: {chars}",
        f"内嵌图片: {image_count}", f"识别方式: {method}", f"识别质量: {reasons}", f"归一状态: {status}",
    ]
    for key in ("来源网址", "访问范围", "密级", "知识角色", "来源权威级别", "项目", "版本关系", "模型出域策略"):
        if source_meta.get(key):
            lines.append(f"{key}: {source_meta[key]}")
    lines.extend(["---", "", f"# {title}", "", *[block for block in blocks if block.strip()]])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    visual_required = bool(images) or (ext in IMAGE_EXTS)
    if visual_required:
        visual_skip_reason = None
    elif ext in (".md", ".markdown"):
        visual_skip_reason = "Markdown直通，无视觉对象"
    elif ext == ".pdf":
        visual_skip_reason = "文本型PDF，页面快照按需生成（page_count已登记）"
    else:
        visual_skip_reason = "纯文本内容，无视觉对象"

    errors = ([error] if error else []) + structure_errors
    row = {
        "document_id": doc_id, "source_name": source_ref, "title": title,
        "original_path": rel(original, ws), "original_sha256": digest(original),
        "markdown_path": rel(md_path, ws),
        "visual_path": rel(visual_dir, ws) if visual_dir.exists() else None,
        "visual_required": visual_required, "visual_skip_reason": visual_skip_reason,
        "structured_path": rel(structured_path, ws), "structured_level": structured_level,
        "quality_report_path": rel(quality_path, ws) if quality is not None else None,
        "image_count": image_count,
        "normalization_status": status, "errors": errors,
        "status": "complete" if (status in PASS_STATES and not errors) else "blocked",
        "layout_version": LAYOUT_VERSION,
    }
    if page_count is not None:
        row["page_count"] = page_count
    return {**row, "clist": (doc_id, title, ext.lstrip("."), chars, image_count, status)}


def main(src_root: Path, ws: Path) -> int:
    rows = []
    for _folder, (code, region, org), files in P.iter_source_groups(src_root, EXTS):
        for index, source in enumerate(files, 1):
            row = process_doc(source, f"{code}-{index:03d}", code, region, org, src_root, ws)
            clist = row.pop("clist")
            row.pop("preserved", None)
            rows.append((row, clist))
            print(f"{clist[0]} {('.' + clist[2]):<6} {clist[3]:>6}字 图{clist[4]} {clist[5]} {str(clist[1])[:24]}")

    manifest_dir = ws / "00-多模态清单"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "多模态清单.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row, _ in rows), encoding="utf-8")

    clist_rows = [clist for _, clist in rows]
    blocked = sum(item[5] not in PASS_STATES for item in clist_rows)
    output = io.StringIO()
    output.write("# 格式归一转换清单\n\n")
    output.write(f"共处理 {len(clist_rows)} 份；准入通过 {len(clist_rows) - blocked} 份，阻断 {blocked} 份。阻断项完成视觉/人工复核后再运行验收。\n\n")
    output.write("| 编号 | 标题 | 原始格式 | 字数 | 图片数 | 归一状态 |\n|---|---|---|---|---|---|\n")
    for item in clist_rows:
        output.write("| " + " | ".join(str(value) for value in item) + " |\n")
    (ws / "00-原始MD" / "转换清单.md").write_text(output.getvalue(), encoding="utf-8")
    print(json.dumps({"documents": len(rows), "degraded": blocked, "layout_version": LAYOUT_VERSION}, ensure_ascii=False))
    return 0 if rows else 2


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("用法: python normalize.py <源文档根目录> <本次工作区目录>")
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))

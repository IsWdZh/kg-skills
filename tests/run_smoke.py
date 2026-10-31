#!/usr/bin/env python3
"""End-to-end smoke test for the generic knowledge governance/service skills."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run(*args, expected=(0,)) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1")
    result = subprocess.run([sys.executable, *map(str, args)], text=True, capture_output=True, encoding="utf-8", env=env)
    if result.returncode not in expected:
        raise AssertionError(f"command failed ({result.returncode}): {' '.join(map(str, args))}\n{result.stdout}\n{result.stderr}")
    return result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kg-skills-smoke-") as raw:
        temp = Path(raw)
        source = temp / "source"
        formal = source / "正式资料"
        formal.mkdir(parents=True)
        write_json(source / "source-map.json", {"正式资料": {"code": "SC", "region": "四川", "organization": "示例单位"}})
        (formal / "01-职责规定.html").write_text(
            "<html><body><h1>职责规定</h1><p>发布日期：2026-01-01</p>"
            "<p>示例单位负责公共服务事项的组织实施、监督检查和跨部门协调，并依法形成工作记录。</p>"
            "<p>业务办理应说明责任主体、输入材料、办理步骤、输出结果和政策依据，确保结论可以追溯。</p>"
            "<p>涉及其他地区经验时，应结合本单位职责、制度、系统和数据条件进行适配确认。</p></body></html>",
            encoding="utf-8",
        )
        from docx import Document
        document = Document()
        document.add_heading("项目调研记录", level=1)
        document.add_paragraph("调研确认现有流程包含受理、审核和反馈三个环节。")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text, table.cell(0, 1).text = "环节", "责任人"
        table.cell(1, 0).text, table.cell(1, 1).text = "受理", "业务人员"
        document.save(formal / "02-调研.docx")
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "需求清单"
        sheet.append(["编号", "问题", "需求"])
        sheet.append(["D-001", "重复提交", "数据共享"])
        workbook.save(formal / "03-清单.xlsx")
        from pptx import Presentation
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = "案例总结"
        slide.placeholders[1].text = "通过流程优化减少重复提交"
        presentation.save(formal / "04-案例.pptx")
        import fitz
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "Policy basis and process evidence 2026")
        pdf.save(formal / "05-政策.pdf")
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (600, 120), "white")
        ImageDraw.Draw(image).text((20, 40), "Policy evidence 2026", fill="black")
        image.save(formal / "06-扫描.png")
        workspace = temp / "workspace"
        run(ROOT / "kg-normalize/scripts/normalize.py", source, workspace)
        multimodal_rows = [json.loads(line) for line in (workspace / "00-多模态清单/多模态清单.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(multimodal_rows) == 6
        assert {Path(row["source_name"]).suffix.lower() for row in multimodal_rows} == {".html", ".docx", ".xlsx", ".pptx", ".pdf", ".png"}
        assert all((workspace / row["original_path"]).exists() and (workspace / row["structured_path"]).exists() for row in multimodal_rows)
        assert all(row.get("layout_version") == 2 for row in multimodal_rows)
        by_ext = {Path(row["source_name"]).suffix.lower(): row for row in multimodal_rows}
        assert by_ext[".png"]["visual_required"] and by_ext[".png"]["visual_path"]
        assert by_ext[".html"]["visual_required"] is False and by_ext[".html"]["visual_skip_reason"]
        assert by_ext[".docx"]["structured_level"] == "full"  # 含表格
        docx_structured = json.loads((workspace / by_ext[".docx"]["structured_path"]).read_text(encoding="utf-8"))
        assert "paragraphs" not in docx_structured and docx_structured["tables"]
        assert not (workspace / "00-原始MD" / "_图片").exists()
        for row in multimodal_rows:
            if row["normalization_status"] in {"归一完成", "已OCR-质检通过", "已视觉复核", "已人工复核"}:
                continue
            review_path = temp / f"{row['document_id']}-review.json"
            report = json.loads((workspace / row["quality_report_path"]).read_text(encoding="utf-8"))
            review = {
                "corrected_markdown": f"经人工复核，{row['source_name']}中的示例内容已完整转写并可用于测试。",
                "unresolved_items": [],
            }
            if set(report.get("object_types") or []).intersection({"table_or_multicolumn", "flow_or_diagram"}):
                review["structure"] = {"nodes": [], "edges": [], "unresolved_items": []}
            write_json(review_path, review)
            run(
                ROOT / "kg-normalize/scripts/record_visual_review.py",
                workspace,
                row["document_id"],
                "--status",
                "已人工复核",
                "--review-file",
                review_path,
            )
        run(ROOT / "kg-normalize/scripts/validate_normalization.py", workspace)
        run(ROOT / "kg-intake/scripts/parse_docs.py", "--from-md", workspace)
        parsed = workspace / "10-解析文档/SC/SC-001.md"
        for parsed_doc in (workspace / "10-解析文档").rglob("*.md"):
            text = parsed_doc.read_text(encoding="utf-8").replace("访问范围: 未知", "访问范围: 公开").replace("知识角色: 待确认", "知识角色: 有效依据")
            parsed_doc.write_text(text, encoding="utf-8")
        run(ROOT / "kg-evidence-govern/scripts/build_evidence_index.py", workspace)
        evidence_path = workspace / "50-知识资产/_证据/证据卡.jsonl"
        cards = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert cards and any(card["source_locator"]["anchor"].startswith("SC-001#p") for card in cards)
        assert all(card["source_locator"]["anchor"].startswith("SC-") for card in cards)
        cards.extend([
            {**cards[0], "evidence_id": "EV-CQ-001-p001", "content": "跨地区流程优化实践经验", "knowledge_role": "实践经验", "region": "重庆"},
            {**cards[0], "evidence_id": "SECRET-EVIDENCE-001", "content": "受限原文内容", "access_scope": "受限"},
        ])
        evidence_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cards), encoding="utf-8")

        request = {
            "request_id": "REQ-SMOKE", "correlation_id": "CORR-SMOKE", "caller": "policy-research",
            "query": "职责流程优化", "external_object_id": "REPORT-1", "knowledge_version": "v1.0", "top_k": 20,
            "caller_context": {"region": "四川", "at_time": "2026-06-30", "allowed_access_scopes": ["公开"]},
        }
        request_path = temp / "request.json"
        response_path = temp / "response.json"
        write_json(request_path, request)
        run(ROOT / "kg-context-retrieve/scripts/retrieve_context.py", "--request", request_path, "--index", evidence_path, "--output", response_path)
        response_text = response_path.read_text(encoding="utf-8")
        response = json.loads(response_text)
        assert "SECRET-EVIDENCE-001" not in response_text
        assert response["trace"]["filtered"]["permission"] == 1
        assert response["evidence"]["cross_domain_reference"]
        assert all(item["partition"] == "跨域参考" for item in response["evidence"]["cross_domain_reference"])

        recommendation = ROOT / "integrations/matter-sorting/examples/recommendation-response.json"
        run(ROOT / "kg-recommend/scripts/validate_recommendation.py", recommendation)

        verify_output = temp / "verify.json"
        run(
            ROOT / "kg-verify/scripts/verify_snapshot.py",
            "--snapshot", ROOT / "integrations/matter-sorting/examples/verify-snapshot.json",
            "--rules", ROOT / "integrations/matter-sorting/validation-rules/cross-object.yaml",
            "--output", verify_output,
        )
        verification = json.loads(verify_output.read_text(encoding="utf-8"))
        assert verification["read_only"] is True and verification["summary"]["warning"] == 1

        method_root = temp / "method/MR-RULE-001"
        method_root.mkdir(parents=True)
        (method_root / "manifest.yaml").write_text(yaml.safe_dump({
            "asset_id": "MR-RULE-001", "asset_type": "validation_rule", "version": "1.0.0",
            "applicable_tasks": ["content-check"], "inputs": ["snapshot"], "outputs": ["findings"],
            "owner": "knowledge-team", "sources": ["SC-001#p001"], "severity": "warning",
            "applicability": "all", "evidence_requirement": "required", "exceptions": [],
            "repair_advice": "review", "tests": ["positive", "negative"],
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")
        run(ROOT / "kg-method-rule/scripts/validate_method_rules.py", temp / "method")

        case = {
            "case_id": "CASE-GOV-001", "title": "示例案例", "version": "1.0.0", "review_status": "已审核",
            "region": "重庆", "industry": "政务", "access_scope": "内部", "applicability": ["同类职责"],
            "not_applicable": ["职责不同"], "evidence_refs": ["EV-CQ-001-p001"],
            "reuse_units": [{"unit_id": "RU-001", "content": "流程优化经验", "evidence_refs": ["EV-CQ-001-p001"], "applicable_conditions": ["职责相似"], "risks": ["需适配确认"], "adaptation_checklist": ["比较目标域职责、制度、系统和数据条件"]}],
        }
        case_path = temp / "case.json"
        write_json(case_path, case)
        run(ROOT / "kg-case-asset/scripts/validate_case.py", case_path)
        case_asset = workspace / "50-知识资产/_案例/CASE-GOV-001/案例清单.json"
        write_json(case_asset, case)
        method_asset = workspace / "50-知识资产/_方法规则/MR-RULE-001/manifest.yaml"
        method_asset.parent.mkdir(parents=True, exist_ok=True)
        method_asset.write_text((method_root / "manifest.yaml").read_text(encoding="utf-8"), encoding="utf-8")

        artifact = temp / "approved.txt"
        artifact.write_text("approved result", encoding="utf-8")
        feedback = {
            "batch_id": "FB-001", "caller": "matter-sorting", "project_id": "P-001", "business_version": "biz-v1",
            "review_status": "已审核", "access_scope": "内部", "correlation_id": "CORR-FB",
            "artifacts": [{"path": str(artifact), "external_object_id": "OBJ-001"}],
        }
        feedback_path = temp / "feedback.json"
        write_json(feedback_path, feedback)
        run(ROOT / "kg-feedback/scripts/ingest_feedback.py", "--batch", feedback_path, "--workspace", workspace)
        idempotent = run(ROOT / "kg-feedback/scripts/ingest_feedback.py", "--batch", feedback_path, "--workspace", workspace)
        assert "idempotent" in idempotent.stdout

        old = temp / "old.jsonl"
        new = temp / "new.jsonl"
        mappings = temp / "mappings.jsonl"
        old.write_text(json.dumps({"knowledge_id": "K-1", "version": "1.0", "content_hash": "a", "status": "active", "access_scope": "内部"}) + "\n", encoding="utf-8")
        new.write_text(json.dumps({"knowledge_id": "K-1", "version": "2.0", "content_hash": "b", "status": "active", "access_scope": "内部"}) + "\n", encoding="utf-8")
        mappings.write_text(json.dumps({"knowledge_id": "K-1", "external_application": "matter-sorting", "external_object_id": "OBJ-001", "business_version": "biz-v1"}) + "\n", encoding="utf-8")
        impact_output = temp / "impact.jsonl"
        run(ROOT / "kg-impact/scripts/analyze_impact.py", "--old", old, "--new", new, "--mappings", mappings, "--output", impact_output)
        impact = json.loads(impact_output.read_text(encoding="utf-8").strip())
        assert impact["external_object_id"] == "OBJ-001" and impact["write_back"] is False

        service_root = workspace / "70-服务运行"
        service_root.mkdir(parents=True, exist_ok=True)
        (service_root / "外部对象映射.jsonl").write_text(mappings.read_text(encoding="utf-8"), encoding="utf-8")
        tagging = workspace / "20-打标结果"
        tagging.mkdir(parents=True, exist_ok=True)
        (tagging / "待人工确认清单.md").write_text("# 待人工确认清单\n\n无。\n", encoding="utf-8")
        packages = workspace / "60-知识包"
        packages.mkdir(parents=True, exist_ok=True)
        (packages / "发布记录.md").write_text("# 发布记录\n\n| # | 时间 | 地区版本 | 版本 | 动作 | 审核依据 | 回滚点 | 当前有效版本 |\n|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
        run(ROOT / "kg-coordinate/scripts/check_links.py", workspace)
        run(ROOT / "kg-package/scripts/export_kb.py", workspace)
        assert (workspace / "80-知识库导出/知识库.db").exists()
        assert (workspace / "80-知识库导出/交换态/证据卡.jsonl").exists()

        integration = ROOT / "integrations/matter-sorting"
        run(ROOT / "kg-open-service/scripts/validate_contract.py", integration)
        run(ROOT / "kg-service-harness/scripts/run_harness.py", integration, "--output", temp / "harness")
        print(json.dumps({"passed": True, "workspace": str(workspace), "evidence_cards": len(cards)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Ingest approved external results and recommendation feedback without write-back."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


APPROVED = {"已审核", "已发布", "已确认可沉淀"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    required = ("batch_id", "caller", "project_id", "business_version", "review_status", "access_scope", "correlation_id")
    missing = [key for key in required if key not in batch]
    if missing:
        raise SystemExit(f"missing fields: {missing}")

    root = args.workspace / "50-知识资产" / "_回流批次" / batch["batch_id"]
    if root.exists():
        existing = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if existing.get("payload_hash") == hashlib.sha256(args.batch.read_bytes()).hexdigest():
            print(json.dumps({"status": "idempotent", "batch_id": batch["batch_id"]}, ensure_ascii=False))
            return 0
        raise SystemExit("batch_id already exists with different payload")
    root.mkdir(parents=True)

    artifacts = []
    snapshot_dir = root / "artifacts"
    for raw in batch.get("artifacts", []):
        source = Path(raw["path"])
        if not source.exists():
            raise SystemExit(f"artifact not found: {source}")
        snapshot_dir.mkdir(exist_ok=True)
        target = snapshot_dir / source.name
        shutil.copy2(source, target)
        artifacts.append({"name": source.name, "sha256": sha256(target), "external_object_id": raw.get("external_object_id")})

    eligible = batch["review_status"] in APPROVED
    manifest = {
        **batch,
        "payload_hash": hashlib.sha256(args.batch.read_bytes()).hexdigest(),
        "artifacts": artifacts,
        "case_governance_eligible": eligible,
        "business_master_source": "external_application",
        "knowledge_copy_mode": "immutable_snapshot",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    task = {
        "task_id": f"CASE-TASK-{batch['batch_id']}",
        "status": "待治理" if eligible else "仅记录反馈",
        "next_skill": "kg-case-asset" if eligible else None,
        "reason": "审核状态满足案例准入" if eligible else "草稿或未审核成果不得进入共享案例",
    }
    (root / "governance-task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "accepted", "eligible": eligible, "path": str(root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

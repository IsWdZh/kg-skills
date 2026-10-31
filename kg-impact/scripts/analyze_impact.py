#!/usr/bin/env python3
"""Compare knowledge versions and emit external-object impact notices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--mappings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    old = {x["knowledge_id"]: x for x in load_jsonl(args.old)}
    new = {x["knowledge_id"]: x for x in load_jsonl(args.new)}
    mappings = load_jsonl(args.mappings)
    by_knowledge: dict[str, list[dict]] = {}
    for mapping in mappings:
        by_knowledge.setdefault(mapping["knowledge_id"], []).append(mapping)

    notices = []
    keys = sorted(set(old) | set(new))
    for kid in keys:
        before, after = old.get(kid), new.get(kid)
        changed = []
        if before is None:
            changed.append("created")
        elif after is None:
            changed.append("removed")
        else:
            for field in ("content_hash", "status", "valid_to", "access_scope", "version"):
                if before.get(field) != after.get(field):
                    changed.append(field)
        if not changed:
            continue
        level = "必须复核" if any(x in changed for x in ("removed", "status", "valid_to", "access_scope")) else "建议复核"
        for mapping in by_knowledge.get(kid, []):
            notices.append({
                "notice_id": f"IM-{kid}-{mapping['external_object_id']}",
                "knowledge_id": kid,
                "external_application": mapping.get("external_application"),
                "external_object_id": mapping["external_object_id"],
                "business_version": mapping.get("business_version"),
                "level": level,
                "changes": changed,
                "old_version": before.get("version") if before else None,
                "new_version": after.get("version") if after else None,
                "suggested_action": "由外部应用创建复核任务" if level == "必须复核" else "由外部应用决定是否复核",
                "write_back": False,
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in notices), encoding="utf-8")
    print(json.dumps({"changed_knowledge": len({x['knowledge_id'] for x in notices}), "notices": len(notices)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

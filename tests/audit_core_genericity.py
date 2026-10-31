#!/usr/bin/env python3
"""Fail when core skills regain known scenario-specific defaults or credentials."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"integrations", "tests", "_models", "__pycache__"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".jsonl", ".yaml", ".yml"}
FORBIDDEN = {
    "legacy projection prefix": re.compile(r"kg[_-]gjj", re.I),
    "legacy common-knowledge id": re.compile(r"GJJ-CK", re.I),
    "fixed source code": re.compile(r"SC-(?:GOV|GWY|MTG|BRIEF)"),
    "fixed project geography": re.compile(r"甘肃|四川|重庆|兰州|嘉峪关|川渝|成渝"),
    "fixed project domain": re.compile(r"公积金|缴存地|购房类|还贷类"),
    "private environment credential": re.compile(r"192\.168\.\d+\.\d+|Jczh@"),
}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return path.suffix.lower() in TEXT_SUFFIXES and not any(part in EXCLUDED for part in relative.parts)


def main() -> int:
    errors = []
    for path in sorted(p for p in ROOT.rglob("*") if p.is_file() and included(p)):
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{path.relative_to(ROOT)}:{line}: {label}: {match.group(0)}")
    if errors:
        print("\n".join(errors))
        return 1
    print("core genericity audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

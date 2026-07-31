"""Validate local Markdown references and one-level progressive disclosure."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    head = root / "SKILL.md"
    for source in [head, *sorted((root / "references").glob("*.md"))]:
        text = source.read_text(encoding="utf-8")
        for raw in LINK.findall(text):
            if "://" in raw or raw.startswith("#"):
                continue
            target = (source.parent / raw.split("#", 1)[0]).resolve()
            if not target.exists():
                errors.append(f"BROKEN:{source.relative_to(root)}->{raw}")
            if source.parent.name == "references" and "references" in Path(raw).parts:
                errors.append(f"DEPTH_GT_1:{source.relative_to(root)}->{raw}")
    nested = [p for p in (root / "references").rglob("*") if p.is_file() and p.parent != root / "references"]
    errors.extend(f"NESTED_REFERENCE:{p.relative_to(root)}" for p in nested)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()
    try:
        errors = validate(args.root.resolve())
        print(json.dumps({"schema": "omni-reference-validation-v1", "status": "PASS" if not errors else "FAIL", "errors": errors}, sort_keys=True, separators=(",", ":")))
        return 0 if not errors else 1
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"schema": "omni-reference-validation-v1", "status": "BLOCKED", "errors": [f"INPUT_INVALID:{type(error).__name__}:{error}"]}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

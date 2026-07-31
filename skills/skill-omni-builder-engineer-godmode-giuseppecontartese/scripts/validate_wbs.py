"""Validate a WBS DAG, exact identifiers, dependencies, owners, and gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        import yaml  # type: ignore
    except ImportError as error:
        raise RuntimeError("PYYAML_REQUIRED_FOR_YAML") from error
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate(data: object) -> list[str]:
    if not isinstance(data, dict):
        return ["WBS_NOT_OBJECT"]
    packages = data.get("packages", [])
    errors: list[str] = []
    identifiers = [item.get("id") for item in packages]
    if len(identifiers) != len(set(identifiers)):
        errors.append("DUPLICATE_ID")
    known = set(identifiers)
    graph = {item["id"]: set(item.get("depends_on", [])) for item in packages if item.get("id")}
    for identifier, deps in graph.items():
        for dep in deps:
            if dep not in known:
                errors.append(f"UNKNOWN_DEPENDENCY:{identifier}:{dep}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"CYCLE:{node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, set()):
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    for item in packages:
        for required in ("id", "owner", "acceptance", "status"):
            if not item.get(required):
                errors.append(f"MISSING_{required.upper()}:{item.get('id', '?')}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load(args.path))
        print(json.dumps({"schema": "omni-wbs-validation-v1", "status": "PASS" if not errors else "FAIL", "errors": errors}, sort_keys=True, separators=(",", ":")))
        return 0 if not errors else 1
    except (OSError, UnicodeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "omni-wbs-validation-v1", "status": "BLOCKED", "errors": [f"INPUT_INVALID:{type(error).__name__}:{error}"]}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Fuse builder/verifier findings without ordinal or identifier collisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fuse(builder: list[dict], verifier: list[dict]) -> dict:
    combined = builder + verifier
    identifiers = [item["id"] for item in combined]
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("IDENTIFIER_COLLISION")
    fused = []
    for ordinal, item in enumerate(sorted(combined, key=lambda value: value["id"]), start=1):
        fused.append({**item, "fused_ordinal": ordinal})
    return {"schema": "omni-lane-fusion-v1", "count": len(fused), "members": fused}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("builder", type=Path)
    parser.add_argument("verifier", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = fuse(json.loads(args.builder.read_text(encoding="utf-8")), json.loads(args.verifier.read_text(encoding="utf-8")))
        if args.output.exists():
            raise RuntimeError("CREATE_ONCE_COLLISION")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"schema": "omni-lane-fusion-result-v1", "status": "PASS", "members": result["count"]}, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "omni-lane-fusion-result-v1", "status": "BLOCKED", "reason": f"{type(error).__name__}:{error}"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

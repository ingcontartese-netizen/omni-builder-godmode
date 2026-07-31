"""Check the explicit authority, profile, lease, and sentinel handoff contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED = {
    "schema", "handoff_id", "objective_sha256", "authority_source",
    "predecessor_session_id", "successor_session_id", "profile_sha256",
    "manifest_sha256", "lease_owner", "sentinels", "forbidden_effects",
}


def validate(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["HANDOFF_NOT_OBJECT"]
    errors = [f"MISSING:{field}" for field in sorted(REQUIRED - record.keys())]
    if record.get("predecessor_session_id") == record.get("successor_session_id"):
        errors.append("SUCCESSOR_NOT_DISTINCT")
    if record.get("lease_owner") not in {"PREDECESSOR", "SUCCESSOR", "NONE"}:
        errors.append("INVALID_LEASE_OWNER")
    forbidden = set(record.get("forbidden_effects", []))
    if not {"F5_DELIVERY", "INSTALLATION", "PUBLICATION", "EXTERNAL_EFFECTS"}.issubset(forbidden):
        errors.append("FORBIDDEN_EFFECTS_INCOMPLETE")
    sentinels = record.get("sentinels", {})
    if not isinstance(sentinels, dict) or set(sentinels) != {"agentic", "script", "context"}:
        errors.append("SENTINEL_SET_INCOMPLETE")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(json.loads(args.path.read_text(encoding="utf-8")))
        result = {"schema": "omni-handoff-validation-v1", "status": "PASS" if not errors else "FAIL", "errors": errors}
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if not errors else 1
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "omni-handoff-validation-v1", "status": "BLOCKED", "errors": [f"INPUT_INVALID:{type(error).__name__}:{error}"]}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

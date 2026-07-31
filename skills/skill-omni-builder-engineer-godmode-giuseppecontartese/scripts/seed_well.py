"""Create the first durable well record from frozen project authority."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SENTRY = Path(__file__).parent / "sentry"
sys.path.insert(0, str(SENTRY))
from io_safe import canonical_json, create_once_text, sha256_bytes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--objective", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scope", default="F3_F4_ONLY")
    args = parser.parse_args()
    try:
        if not args.objective.strip() or not args.authority.strip() or args.scope != "F3_F4_ONLY":
            raise ValueError("SEED_AUTHORITY_OR_SCOPE_INVALID")
        objective_digest = sha256_bytes(args.objective.encode("utf-8"))
        record = {
            "schema": "omni-well-seed-v1", "objective": args.objective,
            "objective_sha256": objective_digest, "authority": args.authority,
            "scope": args.scope, "f5_allowed": False, "external_effects_allowed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        status = create_once_text(args.output, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(canonical_json({"schema": "omni-well-seed-result-v1", "status": status, "objective_sha256": objective_digest}))
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(canonical_json({"schema": "omni-well-seed-result-v1", "status": "BLOCKED", "reason": f"{type(error).__name__}:{error}"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

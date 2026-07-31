"""Host-denominator context sentinel; unknown capacity is never treated as safe."""

from __future__ import annotations

import argparse

from io_safe import canonical_json


def evaluate(used: int, capacity: int, warn_percent: int = 70, rotate_percent: int = 85) -> dict:
    if any(isinstance(value, bool) for value in (used, capacity, warn_percent, rotate_percent)):
        raise ValueError("CONTEXT_VALUES_MUST_BE_INTEGERS")
    if capacity <= 0:
        raise ValueError("HOST_CONTEXT_DENOMINATOR_UNKNOWN")
    if used < 0 or used > capacity:
        raise ValueError("HOST_CONTEXT_USAGE_INVALID")
    if not 0 < warn_percent < rotate_percent < 100:
        raise ValueError("CONTEXT_THRESHOLDS_INVALID")
    basis_points = used * 10000 // capacity
    state = "HEALTHY"
    if basis_points >= rotate_percent * 100:
        state = "ROTATION_REQUIRED"
    elif basis_points >= warn_percent * 100:
        state = "HANDOFF_FREEZE_REQUIRED"
    return {
        "schema": "omni-context-sentinel-v1", "status": "PASS", "state": state,
        "used": used, "capacity": capacity, "basis_points": basis_points,
        "warn_percent": warn_percent, "rotate_percent": rotate_percent,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--used", required=True, type=int)
    parser.add_argument("--capacity", required=True, type=int)
    parser.add_argument("--warn-percent", type=int, default=70)
    parser.add_argument("--rotate-percent", type=int, default=85)
    args = parser.parse_args()
    try:
        print(canonical_json(evaluate(args.used, args.capacity, args.warn_percent, args.rotate_percent)))
        return 0
    except ValueError as error:
        print(canonical_json({"schema": "omni-context-sentinel-v1", "status": "BLOCKED", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

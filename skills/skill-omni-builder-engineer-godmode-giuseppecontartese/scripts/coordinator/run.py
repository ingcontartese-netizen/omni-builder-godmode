"""Execute one bounded governed turn; orchestration remains explicit and inspectable."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SENTRY = ROOT / "scripts" / "sentry"
sys.path.insert(0, str(SENTRY))
from budgets import Budget  # noqa: E402
from cycle import run_cycle  # noqa: E402
from loop import EchoDetector  # noqa: E402
from io_safe import strict_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--objective-digest", required=True)
    parser.add_argument("--wake-limit", type=int, default=3)
    parser.add_argument("--authority-ok", action="store_true")
    parser.add_argument("--objective-satisfiable", action="store_true")
    parser.add_argument("--infra-failure", action="store_true")
    parser.add_argument("--signals", type=Path, help="Strict JSON object of typed brake signals")
    args = parser.parse_args()
    try:
        signals = strict_json(args.signals.read_text(encoding="utf-8")) if args.signals else {}
        if not isinstance(signals, dict):
            raise ValueError("SIGNALS_NOT_OBJECT")
        result = run_cycle(
            previous=strict_json(args.previous.read_text(encoding="utf-8")),
            current=strict_json(args.current.read_text(encoding="utf-8")),
            objective_digest=args.objective_digest,
            authority_ok=args.authority_ok,
            objective_satisfiable=args.objective_satisfiable,
            infra_failure=args.infra_failure,
            signals=signals, wake_budget=Budget("wakeups", args.wake_limit),
            echo_detector=EchoDetector(),
        )
        print(json.dumps({"schema": "omni-coordinator-turn-v1", "status": "PASS", "result": result}, sort_keys=True, separators=(",", ":")))
        return 0 if not result["decision"].startswith("FAIL_CLOSED") else 1
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"schema": "omni-coordinator-turn-v1", "status": "BLOCKED", "reason": f"{type(error).__name__}:{error}"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

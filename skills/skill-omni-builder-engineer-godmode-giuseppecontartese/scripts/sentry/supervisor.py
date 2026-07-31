"""Bounded script-sentinel supervisor. It never starts an AI session."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from io_safe import atomic_write_text, canonical_json, create_once_text, sha256_bytes


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def acquire_lock(path: Path, owner: str, generation: int) -> None:
    payload = {"owner": owner, "generation": generation, "pid": os.getpid(), "acquired_at": now()}
    create_once_text(path, json.dumps(payload, indent=2) + "\n")


def heartbeat(path: Path, owner: str, generation: int, baseline: int) -> dict:
    payload = {
        "schema": "omni-script-sentinel-heartbeat-v1", "owner": owner,
        "generation": generation, "pid": os.getpid(), "baseline": baseline,
        "heartbeat_at": now(),
    }
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
    observed = json.loads(path.read_text(encoding="utf-8"))
    if observed != payload:
        raise RuntimeError("HEARTBEAT_READBACK_FAIL")
    return observed


def handover(path: Path, old_owner: str, new_owner: str, generation: int, reason: str,
             profile_sha256: str) -> dict:
    if old_owner == new_owner:
        raise ValueError("HANDOVER_REQUIRES_DISTINCT_OWNERS")
    if len(profile_sha256) != 64 or any(char not in "0123456789ABCDEF" for char in profile_sha256):
        raise ValueError("HANDOVER_PROFILE_SHA256_INVALID")
    handover_id = sha256_bytes(canonical_json({
        "old_owner": old_owner, "new_owner": new_owner, "generation": generation, "reason": reason,
    }).encode("utf-8"))[:32]
    payload = {
        "schema": "omni-ownership-handover-v1", "handover_id": handover_id,
        "old_owner": old_owner, "new_owner": new_owner, "generation": generation,
        "reason": reason, "old_owner_quiescence_required": True,
        "old_owner_quiescent": False, "new_owner_readback_verified": False,
        "profile_sha256": profile_sha256, "created_at": now(),
    }
    create_once_text(path, json.dumps(payload, indent=2) + "\n")
    observed = json.loads(path.read_text(encoding="utf-8"))
    if observed != payload:
        raise RuntimeError("HANDOVER_READBACK_FAIL")
    return observed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--baseline", required=True, type=int)
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args()
    try:
        if args.max_cycles < 1 or args.interval_seconds < 0 or args.generation < 1:
            raise ValueError("INVALID_BUDGET_OR_GENERATION")
        args.state_dir.mkdir(parents=True, exist_ok=True)
        acquire_lock(args.state_dir / "supervisor.lock.json", args.owner, args.generation)
        cycles = []
        for index in range(args.max_cycles):
            observed = heartbeat(args.state_dir / "heartbeat.json", args.owner, args.generation, args.baseline)
            cycles.append({"cycle": index + 1, "heartbeat_sha256": sha256_bytes(canonical_json(observed).encode())})
            if index + 1 < args.max_cycles:
                time.sleep(args.interval_seconds)
        print(canonical_json({"schema": "omni-script-sentinel-run-v1", "status": "PASS", "cycles": cycles}))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(canonical_json({"schema": "omni-script-sentinel-run-v1", "status": "BLOCKED", "reason": f"{type(error).__name__}:{error}"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

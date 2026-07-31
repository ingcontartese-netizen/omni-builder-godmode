"""Read a partitioned physical channel and wake on MAX > baseline."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

PATTERN = re.compile(r"^(codex_to_claude|claude_to_codex)_(\d+)_.*$")


@dataclass(frozen=True)
class ChannelRecord:
    number: int
    lane: str
    path: Path


def scan(directory: str | Path) -> list[ChannelRecord]:
    records: list[ChannelRecord] = []
    for path in Path(directory).iterdir():
        match = PATTERN.match(path.name) if path.is_file() else None
        if not match:
            continue
        number = int(match.group(2))
        lane = match.group(1)
        expected_even = lane == "codex_to_claude"
        if (number % 2 == 0) != expected_even:
            raise RuntimeError(f"PARITY_VIOLATION:{path.name}")
        records.append(ChannelRecord(number, lane, path))
    numbers = [record.number for record in records]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError("ORDINAL_COLLISION")
    return sorted(records, key=lambda record: record.number)


def after_baseline(directory: str | Path, baseline: int) -> list[ChannelRecord]:
    return [record for record in scan(directory) if record.number > baseline]


def gaps(records: list[ChannelRecord]) -> list[int]:
    if not records:
        return []
    present = {record.number for record in records}
    return [number for number in range(records[0].number, records[-1].number + 1) if number not in present]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--baseline", type=int, required=True)
    args = parser.parse_args()
    try:
        all_records = scan(args.directory)
        fresh = [record for record in all_records if record.number > args.baseline]
        physical_max = all_records[-1].number if all_records else -1
        result = {"schema": "omni-channel-wakeup-v1", "status": "PASS", "physical_max": physical_max, "wake": bool(fresh), "gaps": gaps(all_records), "fresh": [str(record.path) for record in fresh]}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"schema": "omni-channel-wakeup-v1", "status": "BLOCKED", "reason": f"{type(error).__name__}:{error}"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

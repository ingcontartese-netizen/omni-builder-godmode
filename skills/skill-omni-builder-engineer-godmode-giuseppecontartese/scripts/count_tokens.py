"""Measure SKILL.md size with an explicit tokenizer or a deterministic fallback."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def measure(text: str) -> tuple[int, str]:
    try:
        import tiktoken  # type: ignore
        return len(tiktoken.get_encoding("o200k_base").encode(text)), "tiktoken:o200k_base"
    except Exception:
        return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)), "regex:words_plus_punctuation"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=Path(__file__).parents[1] / "SKILL.md")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    try:
        if args.limit < 1:
            raise ValueError("LIMIT_MUST_BE_POSITIVE")
        text = args.path.read_text(encoding="utf-8")
        tokens, method = measure(text)
        result = {"schema": "omni-token-count-v1", "status": "PASS" if tokens < args.limit else "FAIL", "path": str(args.path), "tokens": tokens, "method": method, "limit": args.limit}
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"schema": "omni-token-count-v1", "status": "BLOCKED", "reason": f"{type(error).__name__}:{error}"}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

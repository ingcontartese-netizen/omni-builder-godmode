"""Semantic progress detection; timestamps and narration never count as evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

VOLATILE = {"created_at", "updated_at", "heartbeat_at", "elapsed_seconds", "narration"}


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in sorted(value.items()) if key not in VOLATILE}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def semantic_digest(value: Any) -> str:
    encoded = json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def has_new_evidence(previous: Any, current: Any) -> bool:
    return semantic_digest(previous) != semantic_digest(current)

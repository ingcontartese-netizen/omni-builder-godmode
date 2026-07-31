"""Detect objective echo without treating a repeated wakeup as progress."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class EchoDetector:
    limit: int = 3
    history: deque[str] = field(default_factory=deque)

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or self.limit < 1:
            raise ValueError(f"ECHO_LIMIT_MUST_BE_POSITIVE:{self.limit}")

    def observe(self, objective_digest: str, evidence_digest: str) -> bool:
        marker = f"{objective_digest}:{evidence_digest}"
        self.history.append(marker)
        while len(self.history) > self.limit:
            self.history.popleft()
        return len(self.history) == self.limit and len(set(self.history)) == 1

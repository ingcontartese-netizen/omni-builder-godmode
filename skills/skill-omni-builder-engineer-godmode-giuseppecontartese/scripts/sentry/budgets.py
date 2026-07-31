"""Explicit bounded counters for work, retries, spawns, and wakeups."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Budget:
    name: str
    limit: int
    used: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or isinstance(self.used, bool) or self.limit < 0 or self.used < 0 or self.used > self.limit:
            raise ValueError(f"INVALID_BUDGET_STATE:{self.name}:{self.used}/{self.limit}")

    def consume(self, amount: int = 1) -> None:
        if isinstance(amount, bool) or amount < 0:
            raise ValueError(f"INVALID_BUDGET_AMOUNT:{self.name}:{amount}")
        if self.used + amount > self.limit:
            raise RuntimeError(f"BUDGET_EXHAUSTED:{self.name}:{self.used}/{self.limit}")
        self.used += amount

    @property
    def remaining(self) -> int:
        return self.limit - self.used

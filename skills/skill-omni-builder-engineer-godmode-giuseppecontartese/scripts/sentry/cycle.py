"""One deterministic sentry cycle with semantic-progress and budget checks."""

from __future__ import annotations

from budgets import Budget
from brake import assert_clear
from decide import decide
from loop import EchoDetector
from progress import has_new_evidence, semantic_digest

ESCALATIONS = {
    "AUTHORITY_LOST": "BLOCKED_PENDING_HUMAN:AUTHORITY_MISMATCH",
    "INFRA_UNAVAILABLE": "BLOCKED_PENDING_INFRA",
    "NO_PROGRESS_ECHO": "BLOCKED_PENDING_HUMAN:ECHO_WITHOUT_PROGRESS",
    "BUDGET_EXHAUSTED": "FAIL_CLOSED:BUDGET_EXHAUSTED",
}


def escalate(event: str) -> str:
    try:
        return ESCALATIONS[event]
    except KeyError as error:
        raise ValueError(f"UNKNOWN_ESCALATION:{event}") from error


def run_cycle(*, previous: dict, current: dict, objective_digest: str,
              authority_ok: bool, objective_satisfiable: bool,
              infra_failure: bool, signals: dict[str, bool],
              wake_budget: Budget, echo_detector: EchoDetector) -> dict:
    wake_budget.consume()
    assert_clear(signals)
    changed = has_new_evidence(previous, current)
    echo = echo_detector.observe(objective_digest, semantic_digest(current))
    outcome = decide(
        authority_ok=authority_ok,
        objective_satisfiable=objective_satisfiable,
        new_evidence=changed,
        hard_stop=None,
        infra_failure=infra_failure,
        echo=echo,
    )
    return {"decision": outcome, "new_evidence": changed, "echo": echo, "wake_remaining": wake_budget.remaining}

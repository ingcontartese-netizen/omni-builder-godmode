"""Pure decision table for a governed cycle."""

from __future__ import annotations


def decide(*, authority_ok: bool, objective_satisfiable: bool, new_evidence: bool,
           hard_stop: str | None, infra_failure: bool, echo: bool) -> str:
    if hard_stop:
        return f"FAIL_CLOSED:{hard_stop}"
    if not authority_ok:
        return "BLOCKED_PENDING_HUMAN:AUTHORITY_MISMATCH"
    if not objective_satisfiable:
        return "BLOCKED_PENDING_HUMAN:UNSATISFIABLE_OBJECTIVE"
    if infra_failure:
        return "BLOCKED_PENDING_INFRA"
    if echo and not new_evidence:
        return "BLOCKED_PENDING_HUMAN:ECHO_WITHOUT_PROGRESS"
    if new_evidence:
        return "CONTINUE"
    return "WAIT_FOR_ADMISSIBLE_EVIDENCE"

# WBS, Stele, and phase gates

## Stele Zero

Freeze purpose, authority, invariants, modes, risks, acceptance evidence, and forbidden effects before implementation. Amend by a successor artifact; do not rewrite the freeze.

## Work package contract

Each package needs a canonical `OBE-Fx-NNN` ID, one result, persistent artifact, dependencies, precondition, tool/capability, budget, acceptance evidence, verifier, rollback, failure states, and next gate.

Validate the DAG before work. Reject duplicate IDs, missing dependencies, cycles, forward references disguised as prerequisites, unbounded fan-out, or a package that can close on narrative confidence.

## State lifecycle

Use `PLANNED → READY → ACTIVE → BUILT_SELF_CHECKED → INDEPENDENT_RECHECK → CLOSED` plus typed non-pass states `BLOCKED_PENDING_HUMAN`, `BLOCKED_PENDING_INFRA`, `INCONCLUSIVE`, `ABORTED`, and `SUPERSEDED`.

## Phase boundary

F3 produces a candidate; F4 attacks and improves it. F3/F4 never imply F5. Stop at `READY_FOR_GIUSEPPE_PRE_INSTALL_TESTS` unless delivery, installation, publication, and external effects receive separate authority.

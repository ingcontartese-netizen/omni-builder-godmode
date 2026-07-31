# Bounded autonomy and persistent objectives

## Objective contract

An objective must contain an observable terminal condition, scope, forbidden effects, evidence, rollback, owner, verifier, budgets, and exact blocker/resume semantics. Test satisfiability before activating it.

If a one-time human decision is truly necessary, emit `BLOCKED_PENDING_HUMAN` with one exact request and resume condition. Do not keep printing equivalent wait messages. If infrastructure is unavailable, use `BLOCKED_PENDING_INFRA` and preserve state.

## Persistent operation

Use all three:

- an **agentic sentinel** owned by the host objective/automation surface;
- a **script sentinel** with lock, identity, heartbeat, bounded rearm budget, physical readback, and typed handover;
- a **host-context sentinel** bound to a measured denominator and explicit warn/rotate thresholds.

No sentinel grants authority. After rotation, restore and prove all three separately. Detect automatic predecessor wakeups and fence all seven control classes before lease transfer: objective, heartbeat, retry, schedule, background job, automation, and archived-task wakeup.

Exactly one script supervisor is legitimate for each project root. Derive its canonical namespace from the normalized project root, keep one owner/generation lock there, and treat a second state directory as a protocol violation rather than a second supervisor. The supervisor's guardian must test this project-wide uniqueness, not merely the local lock file.

## Budgets

Bound turns, repairs, tool calls, fan-out, runtime diagnostics, API cost, writes, and effects. Wall-clock time diagnoses liveness; it is not truth. Progress is new admissible evidence or state, not repeated narration.

## Kill switch

The PM retains an immediate reversible stop. A stop cancels future authority but does not erase history or fabricate task completion.

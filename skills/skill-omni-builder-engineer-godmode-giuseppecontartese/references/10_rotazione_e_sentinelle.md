# Governed session rotation and sentinel continuity

Read this file completely before rotating any agent.

Here, **make-before-break** means creating and restoring a distinct shadow successor before revoking the predecessor, without ever permitting two writers. A **surface profile** is the frozen host/UI/CLI/API identity plus runtime settings; a **host-context sentinel** compares measured use with a known context denominator and grants no authority.

## Safety envelope

Freeze request ID, generation, nonce, predecessor identity, project root, manifest, payload hash, channel baseline, single-writer lease, authority, forbidden effects, `max_spawn=1`, `recurrence=false`, and the surface profile. A rotation continues existing authority; it never broadens it.

The agent must not opaque-spawn itself. Use a proven native host carrier or one externally authorized per-action operator. `HOST_ACTION_DENIED` ends in `ROTATION_ABORTED` without retry.

## Validated state chain

1. `ROTATION_REQUESTED`
2. `HANDOFF_FROZEN` (`INPUTS_FROZEN` is a required fact)
3. `SUCCESSOR_CREATED`
4. `SESSION_BOUND`
5. `ATTACH_PASS`
6. `RESTORE_PASS`
7. `AUTHORITY_ENVELOPE_BOUND` (binds scope; transfers no authority)
8. `VISIBLE_SESSION_SELECTED`
9. `PREDECESSOR_FENCE_STARTED`
10. `PREDECESSOR_AUTHORITY_REVOKED`
11. `PREDECESSOR_QUIESCENT`
12. `LEASE_GRANTED`
13. `RESUME_PASS`
14. `WORK_ACKED`
15. `WORK_STARTED_PROBE` (a zero-effect probe)
16. `WORK_RESUMED_NOTIFIED`
17. `PEER_COUNTERSIGN`
18. `SUBSTANTIVE_WORK_RELEASED`

`ROTATION_ABORTED` is a legal terminal from every nonterminal state and is never retried automatically. Every state needs preconditions, evidence, producer, typed failure codes, and a reasoned status validator. Only `SUBSTANTIVE_WORK_RELEASED` authorizes substantive work.

## A — ATTACH

The successor reads the frozen manifest and native creation receipt, proves a distinct session ID, validates all files, records channel physical MAX, and emits an attachment receipt. It remains `SHADOW_READ_ONLY`: no product write, authority inheritance, or lease.

## B — RESTORE

Reread all frozen files and every governed delta after the baseline. Reconstruct identity, phase, roles, prohibitions, closed gates, open work, first next action, surface profile, objective, and sentinels. Recheck the manifest after reading. Emit a restore receipt; still no lease.

## UI switch and fencing

Prove `VISIBLE_SESSION_SELECTED` separately; it sets `grants_lease=false`. Inventory predecessor control sources before and after cutover: goal, heartbeat, automations, background tasks, retries, wakeups, and sentinels.

Emit typed ownership handover, revoke predecessor authority, recheck fencing, prove quiescence, then grant the successor lease create-once. Require `revoked_at < released_at < granted_at`. Rename, archive, safe-park, or UI switch alone never prevents an automatic goal wakeup.

## C — RESUME

Validate the complete receipt chain and current manifest, prove profile parity, restore agentic, script, and host-context sentinels, acquire the unique lease, then perform only a zero-effect `WORK_STARTED_PROBE`. Emit `RESUME_PASS`, `WORK_ACKED`, `WORK_RESUMED_NOTIFIED`, wait for peer counter-signature, and emit `SUBSTANTIVE_WORK_RELEASED` before substantial work.

## Team bracket

Announce `ROTATION_INTENT` to both endpoints before rotation and `WORK_RESUMED_NOTIFIED` after it. Receivers must not treat silence as death, attack moving bytes, or close obligations by implication. Without both announcements, individual continuity may be proven but team continuity is not.

## Channel discipline

Use append-only lanes, parity/partition rules, and physical filenames as truth. Wake on `MAX > baseline`, never on one expected number. Record gaps and never backfill them. Read back before retrying any create-once or message write.

## Sentinel rehydration

After every rotation:

1. prove the host objective/automation is active, bound to the successor, and carries the terminal project goal;
2. prove the script supervisor lock, PID/instance identity, heartbeat freshness, budget, baseline, target rule, and child status;
3. exercise one bounded wake→exit→readback→rearm cycle;
4. fence every predecessor automation and watcher;
5. emit separate rehydration and wake/rearm receipts.

Also run `scripts/sentry/context.py` with a measured host denominator. Unknown or invalid denominators block; thresholds yield `HEALTHY`, `HANDOFF_FREEZE_REQUIRED`, or `ROTATION_REQUIRED`. This sentinel diagnoses context pressure and grants no authority.

The supervisor needs its own guardian or bounded self-health proof. A heartbeat is diagnostics, not authority or work evidence.

## Final profile receipt

Bind exact host/version, surface ID, native session ID, predecessor ID, model, reasoning effort, permission/sandbox, project root, source snapshot, tools/plugins/MCP, objective, agentic sentinel, script sentinel, host-context sentinel, and channel cursor. Refuse `PEER_COUNTERSIGN` on any unapproved drift.

The chain validator must reject every nonterminal prefix, validate the first record, apply the semantic schema at runtime, enforce immutable request/profile/manifest/payload fields, and require `revoked_at < released_at < granted_at`. Never infer a terminal PASS from a legal prefix.

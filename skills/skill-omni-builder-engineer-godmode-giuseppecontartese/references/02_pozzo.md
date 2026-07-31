# Durable well and state layers

Keep project memory on disk, not in conversational recollection.

## L2 entry gate

Do not create, seed, or mutate any knowledge well during activation or guided intake. The first well operation requires an exact `INTAKE_READY` receipt proving all of the following:

- Q0 selected `TEAM_DUAL_LANE` or `SOLO_DUAL_HAT`;
- two distinct native sessions are bound as one immutable session pair;
- both brains acknowledged the same Team Card digest;
- all critical questions have matching builder/verifier question-and-answer readbacks;
- critical closure was recomputed from the matrices and is closed;
- both brains read back the same intake-proposal digest;
- `WORKSPACE_ACCESS_ENVELOPE` physically proves the exact named roots and non-destructive capabilities needed for this write, with a retained create-once probe receipt and the same locked session pair;
- separate downstream authority permits the intended read, web, download, or write effect.

`TEAM_CARD_DUAL_ACK` is necessary but not sufficient for a well write. A single-session or simulated-two-hat fallback is `PROFILE_DEGRADED` and cannot bootstrap the well. `PM_RELAY` may transport exact intake records, but it is not a governed channel and grants no well authority.

L2 defines the entry boundary: retain `well.state=WELL_WRITE_SCOPE_PENDING` until it closes. L3 starts only after `INTAKE_READY`, physical workspace access, and separate downstream write authority exist. `ACCESS_READY` proves only the exact roots/capabilities in its envelope and never network, download, execution, installation, publication, deletion, movement, overwrite of preexisting user files, or external effects. The physical design remains one project well folder, never two project wells, containing separate lane-owned files; no file is co-written. Its later governed fusion gate is described below.

## L3 one-well layout

Create exactly one project well, never one well per agent. Give the two native sessions separate brains and non-overlapping write lanes inside it. A recommended physical layout is:

- `control/`: research brief, material-join manifest, effect-authority bindings, state records, channel ledger, and gates;
- `brains/builder/` and `brains/verifier/`: separately restorable identity and context;
- `sources/quarantine/builder/` and `sources/quarantine/verifier/`: inert downloaded bytes, never executed;
- `lanes/builder/` and `lanes/verifier/`: lane-owned material notes, light map, deep plan, deep research, dossier, and freeze;
- `fused/knowledge/`: create-once knowledge fusion artifacts and countersigns;
- `plans/builder/`, `plans/verifier/`, and `plans/fused/`: unavailable until knowledge fusion passes;
- `evidence/`: manifests, hashes, receipts, negative tests, and provenance records.

No file is co-written. Prefix shared names with stable builder/verifier ownership or keep them under exclusive lane roots. The peer may read only frozen lane bytes; it must not supply an answer key, edit the other lane, or synthesize the other lane before both freezes.

## State chain

The global L3 chain is `INTAKE_READY -> WELL_BOOTSTRAPPING -> WELL_READY -> MATERIAL_QUARANTINE -> MATERIAL_JOINED -> LANES_ACTIVE -> LANES_FROZEN -> FUSION_EMITTED -> KNOWLEDGE_FUSION_PASS`. Each lane independently advances through `MATERIAL_BOUND -> LIGHT_MAP_FROZEN -> DEEP_PLAN_FROZEN -> DEEP_RESEARCH_ACTIVE -> LANE_DOSSIER_READY -> LANE_FROZEN`.

The light map and deep plan are create-once boundaries. Research after either freeze cannot silently rewrite it; issue a successor revision with provenance. Both lane freezes are mandatory even when the user supplied excellent material, because supplied material never replaces independent current web research.

Only a PM-reserved `KNOWLEDGE_FUSION` gate may authorize the builder to emit a fused knowledge artifact from both frozen lane dossiers. A distinct verifier session must reproduce its sources, conflicts, dissent, exclusions, and provenance before countersigning `KNOWLEDGE_FUSION_PASS`. No realization plan, plan fusion, Mode selection, or autonomous runtime may start before that pass.

## Seven organs

1. **Purpose:** objective, non-objectives, sovereign, terminal state.
2. **Authority:** scopes, approvals, reserved transitions, prohibitions.
3. **Canonical state:** current phase, owner, lease, open work, next action.
4. **Plan/WBS:** dependency graph, budgets, acceptance evidence.
5. **Knowledge:** frozen sources, provenance, decisions, assumptions.
6. **Evidence:** manifests, receipts, tests, counter-signatures.
7. **Learning:** incidents converted into rules, controls, and fixtures.

Separate identity-bearing state from narrative notes. A narrative summary cannot override a receipt, manifest, lease, or current filesystem measurement.

## Restore order

Read authority → latest physical channel records → canonical state → active manifest → receipts → open findings → relevant knowledge. Compare cached maps with current bytes and state every divergence. Do not use implicit memory to fill gaps.

## Write discipline

Prefer create-once artifacts for receipts, freezes, approvals, and revisions. Use a new path for corrections. For mutable operational state, use atomic replacement, generation/fencing tokens, and post-write readback.

Conversation scale must not create one file per message or one co-written file. Use one append-only ledger stream per physical writer, stream-local sequence and event identity, causal/vector checkpoints, writer lease plus fencing, and periodic sealed-volume rotation. A solo two-hat run may use one physical stream but must declare `independent_verifier=false`. See [11](11_relay_ledger.md).

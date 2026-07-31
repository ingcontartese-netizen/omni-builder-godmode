# GOVERNED HANDOFF — OMNI_FULL ONLY

`applicability=OMNI_FULL_ONLY`; `activation_level=OMNI_FULL`; `MODULE_INSTANTIATION_FORBIDDEN`. This template contains Q0, guided intake, fused program, and Mode fields and must never instantiate for `OMNI_AWARE` or `OMNI_MODULE`; a module uses its separate mini-contract and typed outcome.

## Identity and authority

- Handoff ID:
- Objective SHA-256:
- Authority source:
- Activation receipt path / bytes / SHA-256 / `ACTIVATION_ALLOWED` decision:
- Activation path / `CURRENT_TASK_ONLY` / run kind / effect policy:
- Sole grant `METHOD_USE` and exact six non-grants:
- Activation trace: `knowledge_available` / `skill_invoked` / activation level `OMNI_FULL` / real packaged modules / authority grants / artifact grants / `requested_effects` / `effect_authorized` / effect grants / non-grants / access-envelope ID / next gate:
- Invariant: `KNOWLEDGE_AVAILABLE != SKILL_INVOKED != EFFECT_AUTHORIZED`; no silent upgrade; downgrade is allowed:
- Guided-intake state path / bytes / SHA-256 / record digest / `INTAKE_READY`:
- Scope: F3/F4 only
- Forbidden: F5, installation, publication, external effects

## Sessions and ownership

- Topology: `SOLO_DUAL_HAT` or `TEAM_DUAL_LANE`
- PM topology-selection `RELAY-nnn` / payload path / bytes / SHA-256 / authorization (`ACCEPTED` required for both topologies):
- TEAM_CARD path / bytes / SHA-256 / status (`TEAM_CARD_DUAL_ACK` required):
- Session pair ID / SHA-256 / lock status (`LOCKED_UNTIL_CUTOVER`):
- Builder brain / verifier brain:
- Builder mandate path / bytes / SHA-256:
- Verifier mandate path / bytes / SHA-256:
- Predecessor session ID:
- Successor session ID:
- Current lease owner: PREDECESSOR
- Builder write lane / owned paths:
- Verifier write lane / owned paths:
- Message lane: `PM_RELAY` (`governed_channel_equivalent: false`):
- Relay ledger path / bytes / SHA-256:
- Last `RELAY-nnn` / payload path / bytes / SHA-256:

## Workspace access before learning

- `WORKSPACE_ACCESS_ENVELOPE` canonical `binding` (path / bytes / SHA-256) + standalone `artifact` (full schema-valid object) / record digest / `ACCESS_GRANTED_NON_DESTRUCTIVE` / `ACCESS_READY`:
- Task root / project root / locked session-pair SHA-256:
- Named source roots with `READ_NAMED_SOURCES` proof:
- Exact grants: `READ_NAMED_SOURCES`, `CREATE_DIRECTORIES_IN_PROJECT_ROOT`, `CREATE_FILES_IN_PROJECT_ROOT`, `WRITE_OWNED_LANE_FILES`:
- Exact non-grants: `DELETE`, `MOVE`, `RENAME_OUTSIDE_ROOT`, `OVERWRITE_PREEXISTING_USER_FILE`, `EXECUTE`, `INSTALL`, `PUBLISH`, `EXTERNAL_EFFECTS`:
- Separate authorizations required: exactly `NETWORK_RESEARCH`, `DOWNLOAD`:
- Closed `omni-workspace-access-probe-receipt-v1` canonical `binding` (path / bytes / SHA-256) + standalone `artifact` (full schema-valid object) / record digest / `CREATE_ONCE_PROBE_RETAINED`:
- Probe identity and bindings: receipt/envelope/task IDs / activation digest / task, project, source, owned-lane roots / session-pair digest / exact four capabilities:
- Probe mutation proof: `create_once=true` / `overwritten=false` / `retained=true` / probe path + bytes + SHA-256:
- Physical `read_proofs` entries `{path, bytes, sha256}` (a narrative access claim is never evidence):
- Path canonicality proof: `CANONICAL_ABSOLUTE_PATH_REQUIRED`; `REJECT_CWD_RELATIVE` / `REJECT_DRIVE_RELATIVE` / `REJECT_NTFS_ADS` / `REJECT_DEVICE_ALIAS`; `NUL_FAMILY_NOT_MODULE_SURFACE`:

## Knowledge corridor

- One well root and well-state binding (path / bytes / SHA-256 / state):
- Shared research brief path / bytes / SHA-256:
- Material-join manifest path / bytes / SHA-256 and same builder/verifier readback:
- Knowledge-effect authority path / bytes / SHA-256; `NETWORK_RESEARCH` grant; independent `DOWNLOAD` grant or explicit `CAPTURE_MD_ONLY`:
- Official governed channel path / state / physical MAX; `PM_RELAY` remains non-equivalent:
- Builder/verifier lane-access envelope paths / bytes / SHA-256 / non-overlap proof:
- Builder light-map freeze / deep-plan freeze / source-capture manifest / dossier / `LANE_FROZEN` receipt:
- Verifier light-map freeze / deep-plan freeze / source-capture manifest / dossier / `LANE_FROZEN` receipt:
- Download quarantine hashes or Markdown-only capture evidence; no downloaded material executed:
- `NO_ORACLE_CONTAMINATION_BEFORE_LANE_FREEZE` evidence:
- PM-reserved `KNOWLEDGE_FUSION` gate receipt:
- Builder-authored fusion path / bytes / SHA-256 / record digest; provenance, conflicts, dissent, exclusions, gaps, confidence, freshness:
- Distinct-verifier countersign path / bytes / SHA-256 / record digest / `KNOWLEDGE_FUSION_PASS`:
- Plan gate (no canonical realization plan before `KNOWLEDGE_FUSION_PASS`):
- Operating intent `GUIDED_PM | AUTONOMOUS`; selected Mode; autonomy authority; separate `ARM_AUTOMATION`; sentinels/budgets/stops/kill switch:

## Frozen state

- Manifest path / bytes / SHA-256:
- Channel physical MAX and digest:
- Mirrored `QUESTION_ID` matrix SHA-256:
- Four-readback status (builder/verifier question + builder/verifier answer):
- Open critical question IDs (must be recomputed, never narrated):
- Intake proposal path / bytes / SHA-256 / dual readback:
- Fused program schema `omni-fused-program-v2` / canonical `binding` (path / bytes / SHA-256) + standalone `artifact` / `PROGRAM_FUSION_FROZEN` candidate / ID / all required author, topology, profile, run-kind, lane-origin, work-item, knowledge, and session-pair fields:
- Independent program countersign receipt `omni-program-countersign-receipt-v2` / canonical `binding` (path / bytes / SHA-256) + standalone `artifact` / `PROGRAM_COUNTERSIGN_ACCEPTED` / `ACCEPTED` / exact reproduction matrix and distinct verifier session:
- Sovereign PROGRAM_BAPTISM decision and `PROGRAM_BAPTIZED` receipt / each path / bytes / SHA-256 / record digest / exact program and countersign bindings:
- Mode status (must remain `MODE_BEFORE_PROGRAM` until physical workspace access, the verified `INTAKE_READY` state, `KNOWLEDGE_FUSION_PASS`, the frozen fused-program candidate, independent accepted countersign, and sovereign baptism receipt are all byte-bound to the same locked session pair):
- Open work:
- Closed gates:
- First next action:

## Runtime parity

- Host runtime version tuple (app / embedded agent / PATH CLI):
- Surface ID:
- Model:
- Effort UI label:
- Effort runtime key:
- Effort mapping evidence:
- Permission surface:
- Project root:
- Tool inventory SHA-256:
- Agentic sentinel ID:
- Script sentinel generation:
- Host-context sentinel:

This file transfers meaning, never authority. It cannot self-declare activation, silently raise an activation level, select a topology or partner, change the locked session pair, close a missing readback, authorize mandatory research, infer download from network access, arm automation, or relabel PM relay as a governed channel. Every referenced receipt, state, EvidenceRef, relay payload, mandate, ledger, workspace envelope, retained probe, lane freeze, knowledge fusion, program, and countersign receipt is opened at its exact path and checked against bytes and SHA-256 before use. Authority changes only through typed gates and the rotation chain.

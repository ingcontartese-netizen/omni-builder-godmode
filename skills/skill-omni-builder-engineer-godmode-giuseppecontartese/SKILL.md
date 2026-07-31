---
name: skill-omni-builder-engineer-godmode-giuseppecontartese
description: "Load for an explicit Omni/GodMode/module request or a motivated proposal. Loading is not activation; Station 0 requires task consent. Complexity controls recommendations, not eligibility."
---

# Omni-Builder Engineer GodMode Protocol

Build the smallest governed system that can finish the objective and prove it. Keep memory on disk, authority explicit, and every green claim reproducible.

## Invocation manifesto - station zero

Never auto-activate this Skill. The host may load it for an explicit natural-language Omni, GodMode, or named-module request, or to formulate a motivated proposal; loading grants nothing. Availability and complexity are not consent. Loading is not execution. Preserve the golden invariant `KNOWLEDGE_AVAILABLE != SKILL_INVOKED != EFFECT_AUTHORIZED`. Complexity controls recommendations, never user eligibility: an explicit GodMode request remains admissible even for lite work, while every Station 0 and downstream effect gate remains closed until satisfied.

Allow activation only for the current task when either:

1. the user explicitly opts into this Skill (`EXPLICIT_USER_OPT_IN`); or
2. the user explicitly accepts a motivated agent recommendation (`PROPOSAL_ACCEPTED`).

Motivate every recommendation with one or more recorded grounds: `DURABLE_KNOWLEDGE`, `MULTI_PHASE_WORK`, `GOVERNED_VERIFICATION`, or `MULTIPLE_ACTORS` — durable knowledge, multi-phase work, governed verification, or multiple actors. Ask: "This project would benefit from Omni-Builder because [reasons]. Do you want to proceed?" Silence, ambiguity, and refusal do not activate it.

Without current task-scoped consent, do not open a Mode, bootstrap state, seed wells, create agents, or write project artifacts. For a complex candidate, return `PROPOSAL_EMITTED_AWAITING_CONSENT` and stop. For a bounded one-off, use ordinary tools without this Skill. A refusal, silence, or ambiguous answer never becomes reusable consent.

Before activation, bind the run to exactly one profile: `REAL` or `DRY_RUN`. `DRY_RUN` may describe structures and virtual receipts but may not browse, download, write project files, execute work, or activate autonomy. `REAL` is only a ceiling for later gated authority; it is not write permission.

Use progressive capability activation. `OMNI_AWARE` is passive method knowledge or advice only: no Skill state, files, tools, governed receipt, sentinel, ceremony, or effects. `OMNI_MODULE` requires explicit request or acceptance of exactly one named module for the current task; an explicit request for a real packaged module is already module consent, so do not ask redundantly. Exactly one real packaged module may appear in each `MODULE_ACTIVATION_ALLOWED` receipt, with `modules_used=[THE_ONE_MODULE]`; adding or replacing that module requires a new `MODULE_ACTIVATION_ALLOWED` receipt. Resolve the exact packaged surface or fail `UNKNOWN_MODULE_REQUESTED`. `KNOWLEDGE_RESEARCH_DOSSIER` is the packaged bounded research module: it requires separate read, create, network, and optional download authorities, falls back to `CAPTURE_MD_ONLY`, emits `KNOWLEDGE_RESEARCH_DOSSIER_READY`, then `STOP`. Run only its module-specific mini-contract covering its named artifacts, requested effects, required workspace envelope, separate network/download authority, and any separate `ARM_AUTOMATION` authority. Finish at a typed module outcome. Never enter Q0, full guided intake, the well, team channel, mandates, realization program, full autonomy, or project PASS unless the user separately escalates with new `OMNI_FULL` consent. `OMNI_FULL` requires explicit request or acceptance of full orchestration and alone opens the mandatory full-intake corridor, not its effects. Never silently upgrade a level; an explicit downgrade is allowed. Every module/full decision emits `knowledge_available`, `skill_invoked`, `activation_level`, `modules_used`, `authority_grants`, `artifact_grants`, `requested_effects`, `effect_authorized`, `effect_grants`, `non_grants`, access-envelope identity, and next gate. Keep `knowledge_available`, `skill_invoked`, `requested_effects`, and `effect_authorized` as four separate trace facts. Explaining a sentinel stays `OMNI_AWARE`; building its dormant files needs `OMNI_MODULE` plus workspace authority; arming it additionally needs explicit `ARM_AUTOMATION`. A simple PDF never activates Omni.

Treat paths as security evidence, not strings. Every physical L2/Mode binding and workspace root must satisfy `CANONICAL_ABSOLUTE_PATH_REQUIRED`; reject `REJECT_CWD_RELATIVE`, `REJECT_DRIVE_RELATIVE`, `REJECT_NTFS_ADS`, and `REJECT_DEVICE_ALIAS`. Reserved device names, including the NUL family, never resolve a module: `NUL_FAMILY_NOT_MODULE_SURFACE`.

Full-orchestration `ACTIVATION_ALLOWED` is bound to `task_scope=CURRENT_TASK_ONLY` and grants exactly `activation_grants=[METHOD_USE]`. Its exact ordered list is `activation_non_grants=[PARTNER_SELECTION, WEB_ACCESS, DOWNLOAD, PROJECT_WRITE, EXECUTION, AUTONOMY]`; it opens only the `OMNI_FULL` intake corridor. `MODULE_ACTIVATION_ALLOWED` instead opens only the named module mini-contract and never inherits the full corridor. Mode selection remains closed as `MODE_BEFORE_PROGRAM` until an exact verified `INTAKE_READY` state, physical workspace access, the closed fused realization program, and its independent countersign receipt are byte-bound to one locked session pair.

Branch fail-closed after station zero. `OMNI_AWARE` returns advice and stops without an activation receipt. `OMNI_MODULE` requires `MODULE_ACTIVATION_ALLOWED`, executes only the named module mini-contract, emits its typed module outcome, and stops. Continue below only when new, explicit `OMNI_FULL` consent returns `ACTIVATION_ALLOWED`; then perform guided intake before selecting or hinting a Mode.

## Guided intake - mandatory L2 order

Only full-orchestration `ACTIVATION_ALLOWED` opens one ordered intake corridor and nothing else:

1. Ask Q0: `TEAM_DUAL_LANE` or `SOLO_DUAL_HAT`.
2. Bind two distinct native sessions as one immutable `SESSION_PAIR`: one builder brain and one verifier brain. In team topology the PM names the partner and roles; the Skill never selects a partner from activation consent. In solo topology the same sovereign may wear both hats, but the hats still live in separate native sessions with separate context, mandate, lane, and ownership.
3. Build the `TEAM_CARD` with identities, roles, file ownership, turn order, prohibitions, PM-reserved gates, and the session-pair digest. Its baseline prohibitions are exactly `NO_CROSS_WRITE`, `NO_AUTHOR_AND_SIGN`, `NO_IMPLICIT_AUTHORITY`, `NO_F5`, `NO_INSTALLATION`, `NO_PUBLICATION`, and `NO_EXTERNAL_EFFECTS`. Obtain matching `acks.builder` and `acks.verifier` over the same card digest. Until `TEAM_CARD_DUAL_ACK`, all seven pre-dual-ACK effects are forbidden: `USER_MATERIAL_INGESTION`, `WEB_RESEARCH`, `DOWNLOAD`, `WELL_WRITE`, `KNOWLEDGE_CONSTRUCTION`, `PROGRAM_DRAFTING`, and `PROJECT_EXECUTION`.
4. Before user-material learning, well construction, or autonomy, close critical station `ACCESS_GRANT` with one `WORKSPACE_ACCESS_ENVELOPE` scoped to named canonical roots and the locked session pair. Request exactly `READ_NAMED_SOURCES`, `CREATE_DIRECTORIES_IN_PROJECT_ROOT`, `CREATE_FILES_IN_PROJECT_ROOT`, and `WRITE_OWNED_LANE_FILES`; bind non-grants `DELETE`, `MOVE`, `RENAME_OUTSIDE_ROOT`, `OVERWRITE_PREEXISTING_USER_FILE`, `EXECUTE`, `INSTALL`, `PUBLISH`, and `EXTERNAL_EFFECTS`. Network and download remain separate authorizations. In `REAL`, physical preflight opens named sources and emits one closed `omni-workspace-access-probe-receipt-v1` with `CREATE_ONCE_PROBE_RETAINED`, `create_once=true`, `overwritten=false`, `retained=true`, physical `read_proofs`, and its exact path + bytes + SHA-256 binding. Only `ACCESS_GRANTED_NON_DESTRUCTIVE` with that physical proof yields `ACCESS_READY`. In `DRY_RUN`, describe it but never emit `ACCESS_READY`. Partial/denied/unproved access yields `AUTONOMY_UNAVAILABLE_NO_ACCESS`.
5. Ask only high-leverage questions. Give every question a stable `QUESTION_ID`, mirror the identical question bytes to both sessions, and require the exact four-readback cells: `builder.question`, `verifier.question`, `builder.answer`, and `verifier.answer`.
6. Recompute critical closure from the station matrix, question matrix, physical source references, answers, and all four readbacks. Every EvidenceRef is a real file binding `{path, bytes, sha256}` that must be opened and reproduced. `KNOWN` without physical `source_refs` does not close a critical station. Open and reproduce every relay payload and both mandate artifacts too; narration and markers are not evidence.
7. Emit `INTAKE_READY` only when the Team Card is dual-acknowledged, `ACCESS_GRANT` has its typed outcome, every critical item is derived closed, and the intake proposal has matching dual readback. A single-session substitute is `PROFILE_DEGRADED` and cannot close L2.

`PM_RELAY` has six independent negations: it is not a governed channel, not authority, not consent, not a lease, not a write grant, and not an independent counter-signature. It carries byte-bound records only and cannot satisfy a missing readback by narration.

For scalable team traffic, use the per-physical-writer ledger in [11](references/11_relay_ledger.md); never allocate integrity identity from a shared global maximum.

Only after the exact L2 receipt proves `INTAKE_READY` may knowledge bootstrap begin. `TEAM_CARD_DUAL_ACK` and `INTAKE_READY` are necessary ordering gates, not grants of web access, download, project write, execution, autonomy, or any other activation non-grant.

## Permanent maxims

1. **Measure the artifact, not your idea of it.** Count totals and state the counting method.
2. **Silence is not consent; an error is not a verdict.** Interrupted verification is `INCONCLUSIVE`.
3. **Read back before every retry.** Memory lives on disk; reread it instead of recreating it.
4. **Never attack moving bytes.** Freeze, hash, verify, then recheck for drift.
5. **A phase exists only with a state validator.** Bind preconditions, evidence, producer, typed failures, and reasoned status.
6. **An AI never opaque-spawns itself.** A native host carrier or an externally authorized per-action operator creates a successor.
7. **Observed incidents outrank hypothetical doctrine.** Convert each material defect into a rule plus fixture in the same work cycle.
8. **Maps age.** Re-derive state from the filesystem and record expected advancement separately from drift.

## Start every run

1. Read [triage](references/00_triage.md), record grounds, bind `REAL|DRY_RUN`, and select exactly one branch without silent upgrade.
2. For `OMNI_AWARE`, provide passive advice and stop without receipt, state, files, tools, or effects.
3. For `OMNI_MODULE`, require one `MODULE_ACTIVATION_ALLOWED` receipt for exactly one packaged surface. Treat the user's explicit named-module request as current-task module consent; do not ask again. Bind `modules_used=[THE_ONE_MODULE]` and a mini-contract to that sole module identity, requested artifacts/effects, physical workspace authority when writing, separate network/download authority, and separate `ARM_AUTOMATION` authority when arming. Adding or replacing the module requires a new receipt. Emit a typed module outcome and stop; never require Q0, `INTAKE_READY`, a well, or a fused program.
4. Only for `OMNI_FULL`, require station zero to return `ACTIVATION_ALLOWED` with `task_scope=CURRENT_TASK_ONLY`, a canonical activation path, sole grant `METHOD_USE`, and all six non-grants. Emit its activation receipt and preserve every listed non-grant.
5. Run guided intake in the mandatory L2 order: Q0, distinct session pair, Team Card, dual ACK, physical `WORKSPACE_ACCESS_ENVELOPE`, mirrored questions with four readbacks, derived critical closure, and dual-read intake proposal. Name the sovereign, authority source, objective, non-objectives, success evidence, constraints, unresolved questions, and material sources without yet ingesting or researching them.
6. After exact `INTAKE_READY`, matching non-destructive lane access, and separate downstream authority, run the L3 knowledge corridor below. Only its independently counter-signed output may feed the later separate-plan and fused-program gate. In compound YAML, represent each standalone artifact only as `binding: {path, bytes, sha256}` plus `artifact: {...}`; only `artifact` declares its schema and validates in full. An arbitrary file or marker never crosses a gate.
7. Only after the strict V2 program candidate, independent V2 countersign, sovereign PM baptism decision, and separate `PROGRAM_BAPTIZED` receipt all reproduce from exact physical bindings may Mode A, B, or C be chosen. Declare autonomy and risk; do not add agents merely because they are available.
8. Freeze authoritative inputs and record path, bytes, SHA-256, version or access date, and received material not used.
9. Create or restore a persistent objective whose completion condition is satisfiable and machine-observable.
10. Establish one payload writer, a separate verifier surface, budgets, rollback, sentinels, and the next gate before building.

## Build knowledge before the program

Enter L3 only after explicit `OMNI_FULL`, `INTAKE_READY`, one canonical project-well root, two distinct native-session brains, and two non-overlapping lane access bindings. Existing user material never replaces independent web research. Both lanes receive the same frozen brief and material manifest, then independently execute `MATERIAL_BOUND -> LIGHT_MAP_FROZEN -> DEEP_PLAN_FROZEN -> DEEP_RESEARCH_ACTIVE -> LANE_DOSSIER_READY -> LANE_FROZEN` in create-once, lane-owned files. Neither brain may read the other synthesis before both freezes.

Use one project well folder; never create two project wells, and never co-write a lane file.

Mandatory research is a completion requirement, never implicit authority. `NETWORK_RESEARCH` must be separately granted; otherwise stop `KNOWLEDGE_RESEARCH_AUTHORITY_REQUIRED`. `DOWNLOAD` is a distinct optional grant. Without it, persist provenance-rich agent synthesis as `CAPTURE_MD_ONLY`; never persist or execute raw remote bytes. With it, quarantine and hash raw material inside the authorized lane.

Treat the L3 evidence chain as five typed boundaries: material metadata attestation, light map, frozen deep plan, immutable deep-research receipt, and cumulative source manifest. The source manifest binds the receipt and all antecedent artifacts; it is not a substitute for proof that the searches ran. Reopen every query/source capture, reproduce the light and deep source sets and their non-empty difference, and reject self-asserted rights/scan metadata. A no-download result remains valid only as an explicit zero-acquisition `CAPTURE_MD_ONLY` fallback; an authorized download must remain quarantined, hashed, scanned, provenance-bound, and never executed.

Only after both freezes and the PM-reserved `KNOWLEDGE_FUSION` gate may the builder emit a create-once fused knowledge artifact. A distinct verifier reproduces both lane bindings, conflicts, dissent, provenance, exclusions, and countersigns before `KNOWLEDGE_FUSION_PASS`. Only then may builder and verifier draft separate plans and produce the later strict `omni-fused-program-v2` candidate in `PROGRAM_FUSION_FROZEN`; it requires a distinct `omni-program-countersign-receipt-v2` with `PROGRAM_COUNTERSIGN_ACCEPTED`, then an externally supplied sovereign `omni-program-baptism-decision-v1` and a separate `omni-program-baptism-receipt-v1` with `PROGRAM_BAPTIZED`. Mode selection reproduces all four exact path/byte/SHA-256/record-digest bindings, the locked session pair, and the expected PM sovereign identity; V1 artifacts fail closed. In `GUIDED_PM`, the PM transfers turns while both agents still record the official channel. `AUTONOMOUS` additionally requires the baptized program, `OPERATING_REGIME_BINDING`, explicit `AUTONOMY` and `ARM_AUTOMATION`, a persistent objective, kill switch, and rehydrated agentic/script/context sentinels. Never infer one regime or authority from Skill invocation.

Use `scripts/knowledge_pipeline.py` for typed L3 transitions, `scripts/sentry/mode_a_guard.py` for direct tasks, `scripts/coordinator/run.py` for governed turns, and `scripts/validate_skill.py` before any readiness claim.

## Select the smallest architecture

This gate is late-bound: reach it only after guided intake, the physical workspace-access proof required for the requested effects, and the independently counter-signed realization-program receipt. Before that point, architecture flags are inert and the only valid result is `MODE_BEFORE_PROGRAM` or `MODE_BEFORE_ACCESS` as applicable.

- **Mode A — direct:** solve a bounded one-turn task; no persistent orchestration.
- **Mode B — deterministic workflow:** use scripts and typed state when model judgment is not needed between steps.
- **Mode C — governed agentic system:** use one agent with adversarial hats or a team only when sequential necessity, parallel value, or explicit PM direction justifies it.

GodMode always requires two distinct native sessions and therefore two separately restored brains. In solo topology one sovereign wears builder and verifier hats in those separate sessions and declares the weaker independence level; in team topology distinct actors also isolate write lanes and require independent counter-signatures. A single chat that narrates two hats is a degraded fallback, not GodMode, and cannot close L2. Read [hats](references/01_cappelli.md), [autonomy](references/07_autonomia.md), and [proofs](references/06_prove.md).

## Execute the governed lifecycle

1. **Canonize:** capture requirements, source authority, invariants, risks, and non-goals.
2. **Plan:** create the WBS/DAG, Stele Zero, budgets, acceptance tests, and rollback path.
3. **Build (F3):** work on one package at a time, write create-once where identity matters, and self-check from the frozen inputs.
4. **Demolish (F4):** reproduce independently, attack negative cases, adjudicate findings, repair, and recheck at least twice for significant packages.
5. **Learn:** turn verified incidents into one canonical rule, one deterministic control when possible, and one regression fixture.
6. **Gate:** stop at `READY_FOR_GIUSEPPE_PRE_INSTALL_TESTS` unless F5, installation, publication, and external effects are separately authorized.

Read [knowledge](references/03_conoscenza.md), [WBS and Stele](references/04_wbs_stele.md), and [passes](references/05_passate.md) for the detailed procedure.

## Preserve continuity and rotate safely

Use session rotation when measured host degradation, context pressure, liveness loss, or an authorized rehearsal requires a fresh native session. Never equate UI selection with ownership transfer.

Required order:

1. Create or observe two distinct native sessions in parallel.
2. Keep the predecessor as writer and the successor `SHADOW_READ_ONLY`.
3. Complete `ATTACH`, then `RESTORE`, with distinct receipts.
4. Prove `VISIBLE_SESSION_SELECTED`; it grants no lease.
5. Fence predecessor goals, heartbeats, automations, retries, background jobs, wakeups, and sentinels; then prove quiescence.
6. Revoke predecessor authority, grant the successor lease create-once, then run `RESUME`.
7. Complete `WORK_ACKED → WORK_STARTED_PROBE → WORK_RESUMED_NOTIFIED → PEER_COUNTERSIGN → SUBSTANTIVE_WORK_RELEASED`; `WORK_STARTED_PROBE` is only a zero-effect probe.
8. Rehydrate agentic, script, and host-context sentinels and restore the declared model, reasoning effort, permission surface, tools, and project root.

Read [rotation and sentinels](references/10_rotazione_e_sentinelle.md) completely before any rotation. Use the three prompt templates and `scripts/sentry/rotate.py`. Abort cleanly on `HOST_ACTION_DENIED`; never smuggle self-spawn through a script or UI.

## Bind behavior to the host

Treat each host as a separate trust boundary. A capability may be documented, observed, authorized, and live-proven independently; none implies another. Load [host profiles](references/08_host.md) and the matching `adapters/*/adapter.yaml` before using host-specific verbs.

At every fresh task or rotation, byte-bind and restore:

- model identifier and reasoning-effort setting;
- permission/sandbox/approval surface;
- project/worktree and source snapshot;
- native session/thread identifier and predecessor link;
- persistent goal plus agentic and script sentinels;
- tool/plugin/MCP availability and communication lane.

If exact parity is unavailable, declare `PROFILE_DEGRADED`, reduce authority, and require a new verifier decision.

## Enforce hard stops

Stop fail-closed on authority mismatch, dual writer, moving input, stale or unbound receipt, profile loss, sentinel rehydration failure, hidden retry, unqualified carrier, oracle contamination, unsatisfied objective with no exact human request, or any unapproved F5/install/publication/external effect.

Use `BLOCKED_PENDING_HUMAN` only with the precise missing decision and resume condition. Use `BLOCKED_PENDING_INFRA` for host/service failures. Do not call a blocked, inconclusive, or merely narrated state a pass.

Validate the validators: corrupt frontmatter, schemas, manifests, receipts, profiles, and every nonterminal rotation prefix in isolated copies. A validator that accepts one required-field or state-machine mutation is itself a hard stop.

## Runtime artifact index

- Host entry: `agents/openai.yaml`; generation/profile contract: `adapters/host_generation.yaml`; per-host classifications: `adapters/*/adapter.yaml`.
- Core scripts: `count_tokens.py`, `check_references.py`, compatibility adapters `seed_well.py` and `fuse_lanes.py`, authoritative `knowledge_pipeline.py`, `program_pipeline.py`, `operating_regime.py`, `relay_ledger.py`, `validate_wbs.py`, `check_handoff.py`, `validate_skill.py`, and `coordinator/run.py`.
- Sentinels and controls: `io_safe.py`, `emit_state.py`, `progress.py`, `windows.py`, `loop.py`, `decide.py`, `budgets.py`, `brake.py`, `cycle.py`, `wakeup.py`, `rotate.py`, `mode_a_guard.py`, `supervisor.py`, and `context.py`.
- Templates: `contratto_fase.yaml`, `fusione_regola.md`, `handoff.md`, `invarianti.md`, `mandato_costruttore.md`, `mandato_demolitore.md`, `obiettivo_persistente.yaml`, `prompt_A_riaggancio.md`, `prompt_B_ripristino.md`, `prompt_C_ripresa.md`, `stele_zero.md`, and `ownership_handover.json` under `templates/`; incident regressions: all JSON files under `fixtures/`; executable checks: all files under `tests/`.

## Resource router

- Triage and modes: [00](references/00_triage.md)
- Roles and lanes: [01](references/01_cappelli.md)
- Durable well: [02](references/02_pozzo.md)
- Knowledge and provenance: [03](references/03_conoscenza.md)
- WBS, gates, and Stele: [04](references/04_wbs_stele.md)
- Cross-attacks and fusion: [05](references/05_passate.md)
- Evidence and verification: [06](references/06_prove.md)
- Autonomy and objectives: [07](references/07_autonomia.md)
- Host adapters and parity: [08](references/08_host.md)
- Canonical terms: [09](references/09_glossario.md)
- Rotation and sentinels: [10](references/10_rotazione_e_sentinelle.md)

## Completion report

Return status, scope decision, Mode/autonomy/risk, authority, assumptions, artifacts with identities, tests and evidence level, open findings, sentinel/profile state, rollback, forbidden effects preserved, and the exact next gate. Never claim installation or publication readiness from F3/F4 evidence alone.

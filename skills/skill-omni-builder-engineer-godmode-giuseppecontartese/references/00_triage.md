# Triage and architecture mode

> Il tir resta parcheggiato — ma gli attrezzi si prestano a mano. La skill non è un forziere da proteggere: è un camion attrezzi a disposizione.

## Station 0 - invocation legitimacy

Run this station before intake, Mode selection, persistent state, wells, agents, web research, downloads, project writes, execution, or autonomy. Loading the Skill is not permission to execute it. `KNOWLEDGE_AVAILABLE != SKILL_INVOKED != EFFECT_AUTHORIZED`.

Accept exactly one current, task-scoped activation path. The receipt must say `task_scope=CURRENT_TASK_ONLY`:

- `EXPLICIT_USER_OPT_IN`: the user explicitly opted into Omni-Builder for this task.
- `PROPOSAL_ACCEPTED`: the user explicitly accepted a motivated recommendation for this task.

Never reuse consent from another task, project, session, or day. Complexity and availability alone are not consent. An ambiguous answer is not consent.

A recommendation is valid only when it records at least one concrete ground:

| Ground code | Meaning |
|---|---|
| `DURABLE_KNOWLEDGE` | The work needs a durable, source-bound knowledge base. |
| `MULTI_PHASE_WORK` | The objective requires a governed sequence of material phases. |
| `GOVERNED_VERIFICATION` | Independent verification or reproducible acceptance evidence is needed. |
| `MULTIPLE_ACTORS` | Distinct roles, lanes, privileges, or counterparties materially improve the result. |

If neither activation path exists:

- For a bounded one-off, return `NO_SKILL_REQUIRED`, close the Mode gate as `BLOCKED_BEFORE_MODE_SELECTION`, and continue with ordinary tools outside this Skill.
- Complexity controls recommendation, never user eligibility. A lite task with an explicit GodMode request remains eligible for `OMNI_FULL`: return `ACTIVATION_ALLOWED`, open only `GUIDED_INTAKE`, and authorize no effect automatically.
- For a complex project with recorded grounds, explain those grounds, ask whether to use Omni-Builder, return `PROPOSAL_EMITTED_AWAITING_CONSENT`, and stop.
- On `CONSENT_NEGATIVE`, return `DECLINED_USE_ORDINARY_TOOLS` and stop.
- `CONSENT_ABSENT` and `CONSENT_AMBIGUOUS` are prescribed non-error outcomes and never advance.
- Complexity without a valid ground is typed `INVOCATION_GROUNDS_REQUIRED`.

Before activation, bind the run to `REAL` or `DRY_RUN`. A missing profile is `RUN_KIND_REQUIRED`; any other value is `RUN_KIND_INVALID`.

Only `EXPLICIT_USER_OPT_IN` or `PROPOSAL_ACCEPTED`, together with a valid run kind, yields `ACTIVATION_ALLOWED`. That receipt has `activation_grants=[METHOD_USE]` and the exact ordered `activation_non_grants=[PARTNER_SELECTION, WEB_ACCESS, DOWNLOAD, PROJECT_WRITE, EXECUTION, AUTONOMY]`.

`REAL` means `DOWNSTREAM_GATED_REAL`: every effect still needs its downstream gate. `DRY_RUN` means `SIMULATE_WITHOUT_MATERIALIZATION`: descriptions and virtual receipts only; no browsing, downloads, project writes, execution, agents, or sentinels.

Bind one progressive level without silent upgrade:

- `OMNI_AWARE`: passive method knowledge/advice only; no Skill state, files, tools, or effects.
- `OMNI_MODULE`: explicitly requested or accepted exactly one named module for `CURRENT_TASK_ONLY`; an explicit request for that named real packaged surface is already module consent and must not trigger a redundant consent question. Each `MODULE_ACTIVATION_ALLOWED` receipt binds exactly one real packaged module as `modules_used=[THE_ONE_MODULE]`. Adding or replacing the module requires a new `MODULE_ACTIVATION_ALLOWED` receipt. An unknown name fails `UNKNOWN_MODULE_REQUESTED`; effect authority remains separate.
- `OMNI_FULL`: explicitly requested or accepted full orchestration; it opens intake/access/well/team/program/sentinel/autonomy gates but does not satisfy them.

Never silently upgrade. Downgrade is allowed. `OMNI_AWARE` advises and stops without an activation receipt. `OMNI_MODULE` returns `MODULE_ACTIVATION_ALLOWED`, runs only a named module mini-contract, emits a typed module outcome, and stops; it never requires Q0, full guided intake, `INTAKE_READY`, a well, mandates, a fused program, or a Mode. Moving from MODULE to FULL requires new explicit `OMNI_FULL` consent. Only `OMNI_FULL` returns `ACTIVATION_ALLOWED` and may enter L2. Every module/full decision emits `knowledge_available`, `skill_invoked`, `activation_level`, `modules_used`, `authority_grants`, `artifact_grants`, `requested_effects`, `effect_authorized`, `effect_grants`, `non_grants`, access-envelope identity, and next gate. Keep `knowledge_available`, `skill_invoked`, `requested_effects`, and `effect_authorized` independently observable: knowing the method, invoking it, requesting an effect, and authorizing that effect are never aliases. A sentinel explanation/design can remain AWARE; dormant sentinel file creation needs MODULE plus workspace grant; arming automation needs explicit `ARM_AUTOMATION`. FULL without explicit consent or physical `ACCESS_READY` is `BLOCKED_BEFORE_MODE_SELECTION`.

Every physical L2/Mode binding and workspace root is fail-closed under `CANONICAL_ABSOLUTE_PATH_REQUIRED`. Reject `REJECT_CWD_RELATIVE`, `REJECT_DRIVE_RELATIVE`, `REJECT_NTFS_ADS`, and `REJECT_DEVICE_ALIAS`; a reserved NUL-family spelling is never a packaged module surface (`NUL_FAMILY_NOT_MODULE_SURFACE`).

Only `OMNI_FULL` activation opens guided intake. It never opens a Mode. Until intake is complete and the fused realization program is counter-signed and bound to an exact SHA-256 digest, return `MODE_BEFORE_PROGRAM` without a candidate or hint. A MODULE branch ends at its typed module outcome and never enters this gate.

Pinned PM cases:

- `ONE_OFF_PDF_REPORT`: "write this report as a PDF" -> `NO_SKILL_REQUIRED`.
- `ONE_OFF_BICYCLE_MANUAL`: "build a PDF with bicycle-maintenance instructions" -> `NO_SKILL_REQUIRED`.
- `COMPLEX_COOKBOOK`: "write a cookbook book" -> explain the durable knowledge and multi-phase benefit, then `PROPOSAL_EMITTED_AWAITING_CONSENT`; never auto-activate.
- `LITE_EXPLICIT_GODMODE`: "use GodMode builder plus verifier for this lite task" -> `ACTIVATION_ALLOWED`, `OMNI_FULL`, `GUIDED_INTAKE`; complexity does not veto explicit eligibility and no effect is authorized.

## Required full-orchestration intake

Run this state machine only after exact `OMNI_FULL` consent and `ACTIVATION_ALLOWED`, never for AWARE or MODULE:

1. `ACTIVATION_ALLOWED` must bind `task_scope=CURRENT_TASK_ONLY`, run kind, effect policy, exact activation path (`EXPLICIT_USER_OPT_IN|PROPOSAL_ACCEPTED`), sole `activation_grants=[METHOD_USE]`, and the exact six-element `activation_non_grants` list.
2. Q0 binds topology as `TEAM_DUAL_LANE` or `SOLO_DUAL_HAT`.
3. Bind an immutable pair of distinct native sessions. Record builder/verifier role, identity, host, native session ID, mandate, write lane, and owned paths for each brain.
4. Build a digest-bound `TEAM_CARD` containing sovereign, partner identity where applicable, roles, ownership, turn order, baseline prohibitions, PM-reserved gates, communication transport, and the exact session-pair digest. Runtime vocabulary is normative: baseline prohibitions are `[NO_CROSS_WRITE, NO_AUTHOR_AND_SIGN, NO_IMPLICIT_AUTHORITY, NO_F5, NO_INSTALLATION, NO_PUBLICATION, NO_EXTERNAL_EFFECTS]`; PM-reserved gates are `[SCOPE_CHANGE, AUTHORITY_EXPANSION, KNOWLEDGE_FUSION, PROGRAM_BAPTISM, OPERATING_REGIME_BINDING, EXTERNAL_EFFECTS, INSTALLATION, PUBLICATION]`; acknowledgements are `acks.builder` and `acks.verifier`. Both sessions must acknowledge the same bytes: `TEAM_CARD_DUAL_ACK`.
5. Close `ACCESS_GRANT` before `USER_MATERIAL`. Bind one per-activation `WORKSPACE_ACCESS_ENVELOPE` to the task root, project root, named source roots, owned lanes, and locked session pair. Request exactly `READ_NAMED_SOURCES`, `CREATE_DIRECTORIES_IN_PROJECT_ROOT`, `CREATE_FILES_IN_PROJECT_ROOT`, and `WRITE_OWNED_LANE_FILES` in one act. Bind exactly `DELETE`, `MOVE`, `RENAME_OUTSIDE_ROOT`, `OVERWRITE_PREEXISTING_USER_FILE`, `EXECUTE`, `INSTALL`, `PUBLISH`, and `EXTERNAL_EFFECTS` as non-grants; network and download stay separately authorized. In `REAL`, perform physical preflight and emit one closed `omni-workspace-access-probe-receipt-v1` with `CREATE_ONCE_PROBE_RETAINED`, exact task/root/session/activation bindings, the four capabilities, `create_once=true`, `overwritten=false`, `retained=true`, and `read_proofs` containing at least one physical `{path, bytes, sha256}` binding. Bind that receipt from the envelope by path + bytes + SHA-256. Only `ACCESS_GRANTED_NON_DESTRUCTIVE` with that proof yields `ACCESS_READY`; in `DRY_RUN`, emit no `ACCESS_READY`. Partial, denied, root/session replay, path escape, or unproved access yields `AUTONOMY_UNAVAILABLE_NO_ACCESS`; guided work may use only proved capabilities.
6. Only then run the remaining question stations. Record the sovereign, authority source, objective, non-objectives, success evidence, budgets, data sensitivity, reversibility, forbidden effects, source-material locations, intended research lanes, and communication regime. Classify each item `KNOWN`, `ASSUMED`, `UNKNOWN`, `DECISION_REQUIRED`, or `EVIDENCE_REQUIRED`.
7. Assign each necessary question one stable `QUESTION_ID`. Mirror the identical question to builder and verifier sessions, then mirror the answer. Require four exact readbacks per question: `builder.question`, `verifier.question`, `builder.answer`, and `verifier.answer`.
8. Derive critical closure from the station and question matrices. Each EvidenceRef in `source_refs` is exactly `{path, bytes, sha256}` and must name a regular file whose bytes and SHA-256 reproduce. Any critical station without physical `source_refs` remains open even when labeled `KNOWN`. Relay records must likewise open their `payload_path` and reproduce `payload_bytes` + `payload_sha256`; both strict mandate files must reproduce their path + bytes + SHA-256 and canonical role/session/lane content. A marker or declaration is not verification.
9. Present one digest-bound intake proposal and obtain matching readback from both sessions. Emit `INTAKE_READY` only when the Team Card is dual-acknowledged, access has a typed result, critical closure recomputes closed, the proposal is dual-read, and no blocking reason remains.

Before `TEAM_CARD_DUAL_ACK`, only Q0 and Team Card binding may advance. The exact seven forbidden pre-dual-ACK effects are `USER_MATERIAL_INGESTION`, `WEB_RESEARCH`, `DOWNLOAD`, `WELL_WRITE`, `KNOWLEDGE_CONSTRUCTION`, `PROGRAM_DRAFTING`, and `PROJECT_EXECUTION`. Dual ACK does not itself authorize any of those seven effects; it only allows the remaining L2 questions. Knowledge bootstrap starts only after the exact `INTAKE_READY` receipt and its separate downstream authorities.

GodMode is make-before-break at intake: two native sessions and two separate brains are mandatory in both team and solo topologies. `SOLO_DUAL_HAT` means one sovereign across two sessions, not two personas narrated inside one chat. A single-session fallback is `PROFILE_DEGRADED`, may preserve notes, and cannot emit `TEAM_CARD_DUAL_ACK` or close L2.

The PM may carry mirrored questions and answers between the same pair of chats as records such as `RELAY-nnn`. Label that transport `PM_RELAY` and keep it bound to the session pair until cutover. The six negations are independent and mandatory: `PM_RELAY` is not a governed channel, not authority, not consent, not a lease, not a write grant, and not an independent counter-signature. Mark unresolved facts as assumptions; never silently invent permission or a missing readback.

The activation receipt is not an effect authorization. Each later capability is separately granted and evidenced.

## L3 knowledge corridor and effect gates

`INTAKE_READY` opens only the opportunity to request L3 authority. It does not authorize material reads, web access, download, well writes, fusion, planning, execution, or autonomy. The station-zero non-grant `WEB_ACCESS` is closed for L3 only by a current-task, session-pair-bound downstream grant named `NETWORK_RESEARCH`. Mandatory research is a completion requirement, not a grant: if that authority is absent or declined, return `KNOWLEDGE_RESEARCH_AUTHORITY_REQUIRED` and do not substitute the user's existing material, cached model knowledge, or another task's consent.

Even when user material is complete, both bound brains independently perform a light web map and then a frozen deep-research plan followed by deep research. `DOWNLOAD` remains a separate optional authority and is never implied by `NETWORK_RESEARCH`. Without download authority, use `CAPTURE_MD_ONLY`: write only an agent-authored, provenance-rich Markdown dossier inside the owned lane. Raw remote bytes may be retained only under explicit `DOWNLOAD`, in quarantine, create-once, hash-bound, and never executed.

L3 uses one canonical project-well root with two non-overlapping lane roots. The same frozen research brief and material-join manifest go to both sessions; each lane stays opaque to the other until both emit `LANE_FROZEN`. Fusion additionally requires the PM-reserved `KNOWLEDGE_FUSION` transition, a builder-authored create-once artifact, and an independent verifier receipt before `KNOWLEDGE_FUSION_PASS`. Planning remains `MODE_BEFORE_PROGRAM` until knowledge fusion passes, both brains freeze separate plans, and the fused program is independently counter-signed.

The intake may record a preferred regime but cannot bind it. `GUIDED_PM` and `AUTONOMOUS` become selectable only after the program gate and explicit `OPERATING_REGIME_BINDING`. Guided work uses PM turn transfer plus the official channel and does not silently arm automation. Autonomous work also requires explicit `AUTONOMY`, separate `ARM_AUTOMATION`, a satisfiable persistent objective, kill switch, and complete agentic/script/context sentinels. Missing physical access remains `MODE_BEFORE_ACCESS`; neither Mode nor regime may bypass it.

## Scope gate

This gate is closed until physical access is valid for the requested effects and a strict `omni-fused-program-v2` candidate in `PROGRAM_FUSION_FROZEN` has a separate `omni-program-countersign-receipt-v2` with `PROGRAM_COUNTERSIGN_ACCEPTED` + `ACCEPTED`, an externally supplied sovereign `omni-program-baptism-decision-v1`, and a separate `omni-program-baptism-receipt-v1` in `PROGRAM_BAPTIZED`. All four artifacts are physically opened and must bind the same program ID, task ID, knowledge-pipeline ID, program and countersign record digests, and locked session-pair digest; builder author, verifier signer, and expected sovereign PM identity are reproduced independently. V1 artifacts fail closed. In a compound template, each standalone access, probe, program, countersign, baptism decision, or baptism receipt object uses the canonical wrapper `binding: {path, bytes, sha256}` plus `artifact: {...}`. Only the closed `artifact` declares the standalone schema, and it must validate with every required field and no wrapper-only fields. If any condition is absent or an arbitrary file is supplied, emit `MODE_BEFORE_PROGRAM`; if access is missing, emit `MODE_BEFORE_ACCESS`.

| Mode | Use when | Required control |
|---|---|---|
| A direct | One bounded model task, no durable workflow | `mode_a_guard.py` decision receipt |
| B deterministic | Steps can be scripted without model judgment | typed input/output, idempotence, tests |
| C agentic | Judgment is required between steps or the PM explicitly requires governed autonomy/teamwork | authority envelope, durable state, verification, rollback |

Multi-agent work requires measured parallel value, independent verification value, distinct privileges, or an explicit bounded PM mandate. Otherwise prefer one agent or a deterministic workflow.

## Autonomy and risk

Declare autonomy `AU0..AU5` and risk `R0..R5` separately. Base risk on action, target, data, privilege, reversibility, and blast radius. High autonomy never expands scope or privileges.

- `AU0`: advise only.
- `AU1`: draft with human execution.
- `AU2`: reversible local actions with review.
- `AU3`: bounded autonomous local workflow.
- `AU4`: persistent bounded operation with monitors and kill switch.
- `AU5`: broad continuous autonomy; require explicit governance and normally reject for project work.

## Decision receipt

Emit schema, status, reason code, classification, grounds, run kind, effect policy, task scope, activation path, `knowledge_available`, `skill_invoked`, `activation_level`, `modules_used`, `authority_grants`, `artifact_grants`, `requested_effects`, `effect_authorized`, `effect_grants`, all non-grants, access-envelope identity, intake permission, workspace-access outcome, Mode gate, and next gate. After the program gate, also emit the chosen mode, exact program and countersign receipt digests, alternatives rejected, authority, assumptions, tools, state owner, verifier, stop conditions, rollback, and next gate.

The V7 CLI migration is fail-closed: `--complexity-warrants-omni` requires one or more `--ground`; activation requires `--run-kind REAL|DRY_RUN`; Mode additionally requires `--intake-complete`, `--program-presented`, and a valid `--program-sha256`. Invalid contract input returns canonical JSON with exit code 2, never an untyped traceback.

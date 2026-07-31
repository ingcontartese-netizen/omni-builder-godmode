# Hats, roles, and write lanes

## Canonical roles

- **PM/sovereign:** defines intent, reserved transitions, risk tolerance, and kill switch.
- **Builder:** owns the candidate payload and deterministic self-checks.
- **Verifier/demolisher:** reproduces from frozen inputs, derives adversarial cases, and never writes product bytes.
- **Sentinel:** observes liveness/readiness and reports; it grants no authority.
- **External operator:** performs one explicitly authorized host action such as native successor creation.

## Single writer

Maintain one writer per payload and one writer per message lane. Shared files require a typed lease, compare-and-swap identity, and readback. A selected UI window, running process, or heartbeat does not confer ownership.

## GodMode session pair

GodMode is defined by two distinct native sessions and two separately restorable brains before substantive intake can close. Bind them create-once as one `SESSION_PAIR`:

- one builder session with its own native session ID, mandate, context, write lane, and owned paths;
- one verifier session with a different native session ID, mandate, context, write lane, and owned paths;
- one pair digest that both sessions read back and that cannot change before an explicit cutover.

Do not substitute model role-play, two labels in one transcript, a UI split, or two processes attached to the same native conversation. Such a fallback is `PROFILE_DEGRADED`: it may preserve emergency continuity, but it is not GodMode and cannot close L2.

## Team Card before intake effects

Immediately after Q0, build the `TEAM_CARD` for the bound session pair. It records sovereign, partner identity if team-based, role assignment, file ownership, turn order, prohibitions, PM-reserved gates, and communication transport. The PM supplies the partner identity and reserved authority; activation does not grant partner selection. Use the runtime vocabulary exactly: prohibitions `[NO_CROSS_WRITE, NO_AUTHOR_AND_SIGN, NO_IMPLICIT_AUTHORITY, NO_F5, NO_INSTALLATION, NO_PUBLICATION, NO_EXTERNAL_EFFECTS]`; reserved gates `[SCOPE_CHANGE, AUTHORITY_EXPANSION, KNOWLEDGE_FUSION, PROGRAM_BAPTISM, OPERATING_REGIME_BINDING, EXTERNAL_EFFECTS, INSTALLATION, PUBLICATION]`; acknowledgements `acks.builder` and `acks.verifier`.

Both sessions must acknowledge the same Team Card digest. Before `TEAM_CARD_DUAL_ACK`, permit only Q0 and Team Card completion. Block all seven pre-dual-ACK effects: `USER_MATERIAL_INGESTION`, `WEB_RESEARCH`, `DOWNLOAD`, `WELL_WRITE`, `KNOWLEDGE_CONSTRUCTION`, `PROGRAM_DRAFTING`, and `PROJECT_EXECUTION`. Mode selection is separately blocked until the later program-digest gate.

Immediately after dual ACK and before `USER_MATERIAL`, both sessions read back the same `WORKSPACE_ACCESS_ENVELOPE`. It binds named source/project roots, owned lanes, the exact four non-destructive grants and eight non-grants from [414], separately authorized network/download, the locked session-pair digest, and physical preflight evidence. The retained create-once probe receipt is never deleted. A narrative grant, different root/pair, or `DRY_RUN` cannot emit `ACCESS_READY`.

## Solo dual-hat topology

In `SOLO_DUAL_HAT`, one sovereign wears both hats across two distinct native sessions. Run builder and verifier work sequentially, freeze the candidate, retire the builder self-pass, rebuild verifier context from sources in the second brain, and record `INDEPENDENCE=ADVERSARIAL_SOLO`, not team-equivalent independence.

## Team dual-lane topology

In `TEAM_DUAL_LANE`, the PM names the partner and assigns bounded roles. Use disjoint work areas and append-only envelopes. The verifier receives artifact identities and public specifications, not the builder's intended answers. Require a peer counter-signature before terminal closure.

## Mirrored questions and four readbacks

After `TEAM_CARD_DUAL_ACK`, use few high-leverage questions. Give each question one canonical `QUESTION_ID` and one digest. Deliver those same bytes to both sessions, then deliver the same answer bytes to both sessions. A question closes only when all four cells agree:

1. `builder.question` readback agrees;
2. `verifier.question` readback agrees;
3. `builder.answer` readback agrees;
4. `verifier.answer` readback agrees.

A missing cell, mismatched digest, unanswered critical question, or non-`KNOWN` final classification keeps critical closure open. Recompute closure from evidence; never let either brain assert it narratively.

When the PM relays these records between the same pair of chats, use ordered `RELAY-nnn` identities and preserve physical `payload_path`, `payload_bytes`, and `payload_sha256`. Open and reproduce each payload before accepting it. `PM_RELAY` is a user-mediated transport with six independent negations: not a governed channel, not authority, not consent, not a lease, not a write grant, and not an independent counter-signature. Keep the same pair of sessions through intake; a replacement requires typed cutover and renewed binding.

L2 closes only after a dual-read intake proposal and evidence-derived critical closure produce `INTAKE_READY`. A critical `KNOWN` station without physical `source_refs` objects `{path, bytes, sha256}` remains open; every reference must be opened and recomputed. Both mandate artifacts are also opened and must reproduce their physical bindings and canonical role/session/lane content. Only after L2 and later downstream authority may both lanes write separate lane-owned files inside one project well folder; never create two project wells, never co-write one lane file, and do not fuse before the later fusion gate.

## L3 dual-lane knowledge isolation

Deliver one byte-identical frozen research brief and one material-join manifest to both brains. Inside the single project well, builder and verifier own different canonical lane roots and create files sequentially under their own namespace. Each independently reads authorized user material, makes a light web map, freezes a deep plan, performs deep research, captures provenance, emits a dossier, and freezes its lane. Existing material never exempts either lane from web research.

Before both lane freezes, neither brain may read the other's synthesis, claims, search conclusions, or private evaluation notes. This is `NO_ORACLE_CONTAMINATION_BEFORE_LANE_FREEZE`; shared immutable source bytes and the common brief are allowed, peer answers are not. After both freezes, the builder may author the fusion only under `KNOWLEDGE_FUSION`; the verifier may read and independently counter-sign it but never modify its bytes. The same sovereign in `SOLO_DUAL_HAT` still uses two native sessions and declares adversarial-solo independence.

Bootstrap questions may travel through `PM_RELAY`, but all later governed decisions and artifact identities are also recorded in the official channel. In `GUIDED_PM`, the PM explicitly transfers the turn and continuous autonomy sentinels remain unarmed. In `AUTONOMOUS`, channel turns may advance without per-turn PM relay only after the program and operating-regime gates plus explicit `AUTONOMY` and `ARM_AUTOMATION`; agentic, script, and context sentinels observe but never grant authority.

## Handoff

Create `OWNERSHIP_HANDOVER` before stopping a healthy watcher or writer. Include current owner, next owner, generation, lease state, reason, exact artifacts, profile, sentinels, and fencing evidence. Prove the old owner quiescent and the new owner read back the handoff.

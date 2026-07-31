# Evidence and verification

## Evidence ladder

1. `CLAIMED`: narrative only; never closes a gate.
2. `OBSERVED`: one direct observation, not independently reproduced.
3. `REPRODUCED`: deterministic rerun from frozen inputs.
4. `INDEPENDENTLY_COUNTERSIGNED`: separate verifier reproduces without answer leakage.
5. `LIVE_QUALIFIED`: controlled live exercise with bounded authority and rollback.

State the reached level and explicit `does_not_prove` fields.

## Receipt minimum

Include schema, run/request/generation/nonce, producer and role, predecessor record hash, subject path/bytes/SHA-256, status, method, observed results, mismatches, authority, lease effect, profile, sentinels, prohibited effects, timestamp, and record digest where the protocol requires it.

## L3 knowledge evidence minimum

A `KNOWLEDGE_FUSION_PASS` claim additionally requires physical, reproducible bindings for:

- the same project/research brief, material-join manifest, activation, intake, and immutable session pair;
- distinct native builder/verifier sessions, brains, mandates, and non-overlapping lane access envelopes;
- the effect-authority artifact proving `NETWORK_RESEARCH` and independently stating whether `DOWNLOAD` is granted;
- each admitted material's typed metadata attestation, bound to the exact source bytes and physical rights/privacy/ACL/scan/parse evidence;
- each lane's typed light-map freeze, deep-plan freeze, immutable deep-research execution receipt, cumulative source manifest, dossier, and `LANE_FROZEN` receipt;
- physical query-result and source captures proving that web evidence is not a locally invented unschematized note;
- exact set equations for light source IDs, deep source IDs, and the non-empty deep-minus-light novelty set;
- raw-download quarantine hashes when downloads were authorized, or `CAPTURE_MD_ONLY` records when they were not;
- a no-oracle-contamination assertion backed by access/order evidence, not narration;
- the create-once fusion artifact with complete claim-to-source provenance, conflicts, dissent, exclusions, gaps, and author identity;
- an independent verifier countersign bound to the same fusion bytes, lane freezes, brief, material manifest, and session pair.

The evidence must state what it does not prove. Network capability does not prove network authority; network authority does not prove download authority; file creation does not prove execution authority; two lane files do not prove independence; a fusion artifact does not prove countersign; `KNOWLEDGE_FUSION_PASS` does not prove the realization program, Mode selection, automation, installation, publication, or F5.

Multi-file transitions also require transaction evidence. Reserve the state transition before publishing side artifacts, bind nonce disposition into the state chain, keep transient staging outside the governed freeze set, and make recovery deterministic. A losing CAS writer must not leave a non-adoptable create-once orphan. `verify` must receive an exact expected phase and report a valid intermediate state as intermediate, never as phase `PASS`.

Use the ladder separately for each claim. A source can be `OBSERVED` while the fusion remains `CLAIMED`; a reproduced lane dossier can coexist with an `INCONCLUSIVE` countersign. Never promote the whole phase to its strongest member.

## Bounded research-module evidence

`KNOWLEDGE_RESEARCH_DOSSIER_READY` proves only its named materials, topic, four stages, source/capture chain, dossier citations, separate authority records, and create-once outcome. Reproduce the light/deep source delta and the exact material bytes. Without download authority require `DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY` and zero raw acquisitions. Its terminal `STOP` does not prove intake, a well, team independence, a realization program, Mode, sentinels, autonomy, or project completion.

## Fail-closed states

- `PASS`: all enumerated checks satisfied.
- `BLOCK`: founded mismatch or hard stop.
- `INCONCLUSIVE`: verifier or evidence path interrupted.
- `ABORTED`: legal terminal transition before ownership transfer.

An error message, missing UI response, or timeout never proves that work did not land. Read back authoritative state before retrying.

## Transient host errors

Classify a transient failure in this order: `UI_TRANSPORT_ERROR -> SESSION_LIVENESS -> WORKFLOW_LIVENESS -> GOVERNED_DELIVERY`. A UI error is not a failed session, a live session is not a live workflow, and a live workflow is not proof that the governed record landed. Read back the authoritative channel or artifact before retrying; count a retry only when the intended effect is proved absent. Emit `BLOCKED_PENDING_INFRA` when infrastructure prevents a safe decision, and rotate only on an observed rotation condition, never by superstition.

## Oracle integrity

Keep public scenarios/rubrics separate from sealed answers and thresholds. Freeze the candidate before reveal. The builder must not use verifier-private artifacts as an answer key.

## Validate the validator

Run the validator against isolated mutants: missing/corrupt frontmatter, omitted required states, wrong constants, drifted payload/profile/manifest digests, malformed JSON, nonterminal chain prefixes, first-record poisoning, and unexpected files. The expected result is a typed failure without a traceback. A happy-path test alone cannot qualify a gatekeeper.

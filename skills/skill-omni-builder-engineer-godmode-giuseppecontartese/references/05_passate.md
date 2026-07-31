# Cross-attacks, passes, and fusion

## Minimum two-pass loop

1. Builder freezes candidate and self-check evidence.
2. Verifier independently reproduces and derives negative cases from the specification.
3. Builder adjudicates each finding as accepted, refuted with evidence, or deferred with declared debt.
4. Builder repairs accepted findings in a successor artifact.
5. Verifier rechecks the frozen successor.
6. Close only when no founded P0/P1 remains and minimum passes are complete.

Do not use the builder report as the verifier's answer key. Pass attribution is itself a byte-bound claim.

## Fusion

Preserve both inputs, enumerate conflicts, remove false absolutes, normalize terms, map every retained member, and emit a new fused artifact. Distinguish `plan_fusion`, `message_reduction`, and `state_projection`.

### Knowledge fusion pass

Knowledge fusion is serial and role-separated:

1. bind the same project brief, material-join manifest, immutable session pair, and two `LANE_FROZEN` manifests;
2. prove that neither lane consumed the peer synthesis before freeze (`NO_ORACLE_CONTAMINATION_BEFORE_LANE_FREEZE`);
3. PM opens the reserved `KNOWLEDGE_FUSION` gate;
4. builder authors a create-once fused artifact without altering either lane dossier;
5. the artifact maps every retained claim to provenance, enumerates conflicts and dissent, records exclusions and unresolved gaps, and never collapses disagreement into false consensus;
6. the distinct verifier session reproduces source identities and fusion rules, then emits `COUNTERSIGN`, `BLOCK`, or `INCONCLUSIVE`;
7. only an accepted countersign yields `KNOWLEDGE_FUSION_PASS`.

Builder authorship and verifier countersign cannot be the same identity or session. PM relay can transport exact bytes but cannot replace the governed channel, open the gate implicitly, or count as the countersign. A plan may be drafted privately only as non-canonical scratch; no realization plan, fused program, or Mode gate may be claimed before `KNOWLEDGE_FUSION_PASS`. After that pass, builder and verifier may develop separate plan proposals and apply the same freeze-then-fuse discipline to produce the canonical program.

## Quantitative discipline

Write a quantitative claim together with its enumeration or derivation. If the list is not materialized, do not publish the number. Never reconstruct an old unenumerated claim retroactively as if it had been proven then.

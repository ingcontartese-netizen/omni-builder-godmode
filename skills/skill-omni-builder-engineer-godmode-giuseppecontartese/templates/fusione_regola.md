# FUSION RULE

- Rule ID: `REPLACE_ME`
- Fusion kind: `KNOWLEDGE_FUSION | PLAN_FUSION | MESSAGE_REDUCTION | STATE_PROJECTION`
- PM-reserved gate and gate receipt:
- Shared research brief path / bytes / SHA-256:
- Material-join manifest path / bytes / SHA-256:
- Locked session-pair ID / SHA-256:
- Builder lane-freeze manifest path / bytes / SHA-256 / `LANE_FROZEN`:
- Verifier lane-freeze manifest path / bytes / SHA-256 / `LANE_FROZEN`:
- Same brief/material/session-pair check:
- `NO_ORACLE_CONTAMINATION_BEFORE_LANE_FREEZE` evidence:
- Builder claim and byte-bound source:
- Verifier attack and independently derived evidence:
- Claim-to-source provenance map:
- Conflicts retained and resolution status:
- Dissent retained:
- Exclusions and reasons:
- Unresolved gaps / confidence / freshness limits:
- Resolution: `ABSORB | REJECT | MODIFY | ESCALATE`
- Canonical wording:
- Deterministic control:
- Regression fixture:
- Does not prove:
- Fused artifact path / bytes / SHA-256 / record digest:
- Signed by builder role / native session ID:
- Independent countersign path / bytes / SHA-256 / record digest:
- Countersigned by distinct verifier role / native session ID:
- Status: `FUSION_PENDING | KNOWLEDGE_FUSION_PASS | BLOCK | INCONCLUSIVE`

For `KNOWLEDGE_FUSION`, both lanes must already be frozen and the builder/verifier identities must be distinct. The builder never signs the verifier receipt. A PM relay, marker, matching prose, or one lane's self-check cannot substitute for physical countersignature. No realization plan becomes canonical before `KNOWLEDGE_FUSION_PASS`.

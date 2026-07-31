"""Fail-closed state-chain validator for make-before-break session rotation."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from io_safe import canonical_json, sha256_path, strict_json

ORDER = [
    "ROTATION_REQUESTED", "HANDOFF_FROZEN", "SUCCESSOR_CREATED", "SESSION_BOUND",
    "ATTACH_PASS", "RESTORE_PASS", "AUTHORITY_ENVELOPE_BOUND", "VISIBLE_SESSION_SELECTED",
    "PREDECESSOR_FENCE_STARTED", "PREDECESSOR_AUTHORITY_REVOKED", "PREDECESSOR_QUIESCENT",
    "LEASE_GRANTED", "RESUME_PASS", "WORK_ACKED", "WORK_STARTED_PROBE",
    "WORK_RESUMED_NOTIFIED", "PEER_COUNTERSIGN", "SUBSTANTIVE_WORK_RELEASED",
]
TERMINAL = {"SUBSTANTIVE_WORK_RELEASED", "ROTATION_ABORTED"}
SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "rotation_state.schema.json"
SHA_FIELDS = {"profile_sha256", "manifest_sha256", "payload_sha256"}
STABLE_FIELDS = {
    "schema", "request_id", "rotation_id", "generation", "nonce", "project_root",
    "predecessor_session_id", "profile_sha256", "manifest_sha256", "payload_sha256",
    "channel_baseline", "max_spawn", "recurrence", "scope", "authority_source",
    "operator_kind", "operator_authorized", "authority_inherited", "external_effects_allowed",
}
MILESTONES = ("revoked_at", "released_at", "granted_at")


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789ABCDEF" for char in value)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def load_contract(path: Path = SCHEMA_PATH) -> tuple[dict[str, Any], list[str]]:
    try:
        value = strict_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {}, [f"SCHEMA_CONTRACT_UNREADABLE:{type(error).__name__}:{error}"]
    if not isinstance(value, dict):
        return {}, ["SCHEMA_CONTRACT_NOT_OBJECT"]
    errors: list[str] = []
    properties = value.get("properties")
    required = value.get("required")
    state_enum = properties.get("state", {}).get("enum") if isinstance(properties, dict) else None
    if value.get("additionalProperties") is not False:
        errors.append("SCHEMA_CONTRACT_NOT_CLOSED")
    if value.get("$id") != "urn:omni-builder:rotation-state:2":
        errors.append("SCHEMA_CONTRACT_ID_DRIFT")
    if not isinstance(properties, dict) or not isinstance(required, list):
        errors.append("SCHEMA_CONTRACT_SHAPE_INVALID")
    elif set(required) != set(properties):
        errors.append("SCHEMA_REQUIRED_PROPERTIES_DRIFT")
    if state_enum != [*ORDER, "ROTATION_ABORTED"]:
        errors.append("SCHEMA_STATE_ENUM_DRIFT")
    if isinstance(properties, dict) and properties.get("schema", {}).get("const") != "omni-rotation-state-v2":
        errors.append("SCHEMA_VERSION_CONST_DRIFT")
    return value, errors


def _validate_record(record: Any, index: int, contract: dict[str, Any]) -> list[str]:
    label = f"RECORD_{index}"
    if not isinstance(record, dict):
        return [f"{label}:NOT_OBJECT"]
    properties = contract["properties"]
    required = set(contract["required"])
    errors = [f"{label}:MISSING:{field}" for field in sorted(required - set(record))]
    errors += [f"{label}:UNEXPECTED:{field}" for field in sorted(set(record) - set(properties))]
    if errors:
        return errors

    state = record.get("state")
    if record.get("schema") != "omni-rotation-state-v2":
        errors.append(f"{label}:SCHEMA_VERSION_INVALID")
    for field in ("request_id", "rotation_id", "nonce", "project_root", "predecessor_session_id", "authority_source"):
        if not isinstance(record.get(field), str) or not record[field]:
            errors.append(f"{label}:{field.upper()}_INVALID")
    if not _is_integer(record.get("generation")) or record["generation"] < 1:
        errors.append(f"{label}:GENERATION_INVALID")
    if not _is_integer(record.get("channel_baseline")) or record["channel_baseline"] < -1:
        errors.append(f"{label}:CHANNEL_BASELINE_INVALID")
    if record.get("max_spawn") != 1:
        errors.append(f"{label}:MAX_SPAWN_MUST_BE_ONE")
    if record.get("recurrence") is not False:
        errors.append(f"{label}:RECURRENCE_FORBIDDEN")
    if record.get("scope") != "F3_F4_ONLY":
        errors.append(f"{label}:SCOPE_INVALID")
    if record.get("operator_kind") not in {"NATIVE_HOST_CARRIER", "EXTERNALLY_AUTHORIZED_PER_ACTION"}:
        errors.append(f"{label}:OPERATOR_KIND_INVALID")
    if record.get("operator_authorized") is not True:
        errors.append(f"{label}:OPERATOR_NOT_AUTHORIZED")
    if state not in {*ORDER, "ROTATION_ABORTED"}:
        errors.append(f"{label}:STATE_INVALID")
    if record.get("lease_owner") not in {"PREDECESSOR", "SUCCESSOR", "NONE"}:
        errors.append(f"{label}:LEASE_OWNER_INVALID")
    if record.get("authority_inherited") is not False:
        errors.append(f"{label}:AUTHORITY_INHERITANCE_FORBIDDEN")
    if record.get("external_effects_allowed") is not False:
        errors.append(f"{label}:EXTERNAL_EFFECTS_FORBIDDEN")
    for field in SHA_FIELDS:
        if not _is_sha256(record.get(field)):
            errors.append(f"{label}:{field.upper()}_INVALID")
    sentinels = record.get("sentinels")
    if not isinstance(sentinels, dict) or set(sentinels) != {"agentic", "script", "context"} or any(
        not isinstance(value, bool) for value in sentinels.values()
    ):
        errors.append(f"{label}:SENTINELS_INVALID")
    created = _parse_time(record.get("created_at"))
    if created is None:
        errors.append(f"{label}:CREATED_AT_INVALID")
    for field in MILESTONES:
        value = record.get(field)
        if value is not None and _parse_time(value) is None:
            errors.append(f"{label}:{field.upper()}_INVALID")

    if state in ORDER:
        position = ORDER.index(state)
        created_successor = ORDER.index("SUCCESSOR_CREATED")
        successor = record.get("successor_session_id")
        if position < created_successor and successor is not None:
            errors.append(f"{label}:SUCCESSOR_PREDECLARED")
        if position >= created_successor:
            if not isinstance(successor, str) or not successor:
                errors.append(f"{label}:SUCCESSOR_MISSING")
            elif successor == record.get("predecessor_session_id"):
                errors.append(f"{label}:SUCCESSOR_NOT_DISTINCT")

        revoked = ORDER.index("PREDECESSOR_AUTHORITY_REVOKED")
        quiescent = ORDER.index("PREDECESSOR_QUIESCENT")
        granted = ORDER.index("LEASE_GRANTED")
        resumed = ORDER.index("RESUME_PASS")
        if position < revoked and record.get("lease_owner") != "PREDECESSOR":
            errors.append(f"{label}:PREDECESSOR_LEASE_REQUIRED")
        elif revoked <= position < granted and record.get("lease_owner") != "NONE":
            errors.append(f"{label}:LEASE_MUST_BE_NONE_DURING_BREAK")
        elif position >= granted and record.get("lease_owner") != "SUCCESSOR":
            errors.append(f"{label}:SUCCESSOR_LEASE_REQUIRED")

        expected_sentinels = position >= resumed
        if isinstance(sentinels, dict) and any(sentinels.get(name) is not expected_sentinels for name in ("agentic", "script", "context")):
            errors.append(f"{label}:SENTINEL_PHASE_INVALID")

        revoked_at, released_at, granted_at = (record.get(field) for field in MILESTONES)
        if position < revoked and any(value is not None for value in (revoked_at, released_at, granted_at)):
            errors.append(f"{label}:MILESTONE_PREDECLARED")
        if position == revoked and not (revoked_at == record.get("created_at") and released_at is None and granted_at is None):
            errors.append(f"{label}:REVOCATION_EVIDENCE_INVALID")
        if position == quiescent and not (revoked_at is not None and released_at == record.get("created_at") and granted_at is None):
            errors.append(f"{label}:QUIESCENCE_EVIDENCE_INVALID")
        if position >= granted and not all(value is not None for value in (revoked_at, released_at, granted_at)):
            errors.append(f"{label}:LEASE_TIMESTAMPS_INCOMPLETE")
        if position == granted and granted_at != record.get("created_at"):
            errors.append(f"{label}:GRANT_EVIDENCE_INVALID")
        parsed_milestones = [_parse_time(value) for value in (revoked_at, released_at, granted_at)]
        if all(value is not None for value in parsed_milestones) and not (
            parsed_milestones[0] < parsed_milestones[1] < parsed_milestones[2]
        ):
            errors.append(f"{label}:MILESTONE_ORDER_INVALID")
    return errors


def validate_transition(previous: Any, current: Any) -> list[str]:
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return ["TRANSITION_RECORD_NOT_OBJECT"]
    before, after = previous.get("state"), current.get("state")
    errors: list[str] = []
    if before in TERMINAL:
        errors.append("TRANSITION_AFTER_TERMINAL")
    elif after != "ROTATION_ABORTED" and (
        before not in ORDER or after not in ORDER or ORDER.index(after) != ORDER.index(before) + 1
    ):
        errors.append(f"NON_ADJACENT_TRANSITION:{before}->{after}")
    for field in STABLE_FIELDS:
        if previous.get(field) != current.get(field):
            errors.append(f"{field.upper()}_DRIFT")
    previous_successor = previous.get("successor_session_id")
    current_successor = current.get("successor_session_id")
    if previous_successor is not None and previous_successor != current_successor:
        errors.append("SUCCESSOR_SESSION_ID_DRIFT")
    if previous_successor is None and after not in {"HANDOFF_FROZEN", "SUCCESSOR_CREATED", "ROTATION_ABORTED"}:
        errors.append("SUCCESSOR_BINDING_TRANSITION_INVALID")
    previous_created = _parse_time(previous.get("created_at"))
    current_created = _parse_time(current.get("created_at"))
    if previous_created is not None and current_created is not None and current_created <= previous_created:
        errors.append("CREATED_AT_NOT_STRICTLY_INCREASING")
    for field in MILESTONES:
        old, new = previous.get(field), current.get(field)
        if old is not None and new != old:
            errors.append(f"{field.upper()}_DRIFT")
    if after == "ROTATION_ABORTED":
        if current.get("lease_owner") != previous.get("lease_owner"):
            errors.append("ABORT_LEASE_DRIFT")
        if current.get("sentinels") != previous.get("sentinels"):
            errors.append("ABORT_SENTINEL_DRIFT")
    return errors


def validate_chain(records: Any, contract_path: Path = SCHEMA_PATH,
                   artifact_digests: dict[str, str] | None = None) -> list[str]:
    contract, errors = load_contract(contract_path)
    if errors:
        return errors
    if not isinstance(records, list):
        return ["CHAIN_NOT_ARRAY"]
    if not records:
        return ["CHAIN_EMPTY"]
    if artifact_digests is None:
        errors.append("ARTIFACT_DIGEST_EVIDENCE_REQUIRED")
    elif set(artifact_digests) != SHA_FIELDS:
        errors.append("ARTIFACT_DIGEST_EVIDENCE_INCOMPLETE")
    elif isinstance(records[0], dict):
        for field in SHA_FIELDS:
            if records[0].get(field) != artifact_digests.get(field):
                errors.append(f"{field.upper()}_ARTIFACT_MISMATCH")
    for index, record in enumerate(records):
        errors.extend(_validate_record(record, index, contract))
    states = [record.get("state") if isinstance(record, dict) else None for record in records]
    if states[0] != "ROTATION_REQUESTED":
        errors.append("CHAIN_MUST_START_AT_ROTATION_REQUESTED")
    if states[-1] not in TERMINAL:
        errors.append("CHAIN_NOT_TERMINAL")
    for previous, current in zip(records, records[1:]):
        errors.extend(validate_transition(previous, current))
    if states[-1] == "SUBSTANTIVE_WORK_RELEASED" and states != ORDER:
        errors.append("SUCCESS_CHAIN_MUST_MATCH_COMPLETE_ORDER")
    if states[-1] == "ROTATION_ABORTED":
        if states[:-1] != ORDER[: len(states) - 1]:
            errors.append("ABORT_CHAIN_NOT_VALID_PREFIX")
        if any(state == "ROTATION_ABORTED" for state in states[:-1]):
            errors.append("ABORT_NOT_TERMINAL")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("chain", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--payload", type=Path)
    args = parser.parse_args()
    try:
        records = strict_json(args.chain.read_text(encoding="utf-8"))
        if not all((args.profile, args.manifest, args.payload)):
            raise ValueError("PROFILE_MANIFEST_PAYLOAD_PATHS_REQUIRED")
        evidence = {
            "profile_sha256": sha256_path(args.profile),
            "manifest_sha256": sha256_path(args.manifest),
            "payload_sha256": sha256_path(args.payload),
        }
        errors = validate_chain(records, artifact_digests=evidence)
    except (OSError, ValueError) as error:
        print(canonical_json({"schema": "omni-rotation-validation-v2", "status": "BLOCKED", "errors": [f"INPUT_INVALID:{type(error).__name__}:{error}"]}))
        return 2
    status = "PASS" if not errors else "FAIL"
    print(canonical_json({"schema": "omni-rotation-validation-v2", "status": status, "errors": errors}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Governed L3 knowledge pipeline with byte-bound authority and create-once state.

This runtime records effects performed by the two locked knowledge lanes.  It does
not perform web research itself and never treats a boolean or narrative claim as
authority.  Every effect consumes a physical authority artifact and every output
is confined to the authorised well.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SENTRY = Path(__file__).parent / "sentry"
sys.path.insert(0, str(SENTRY))

from emit_state import ProtocolError, validate_instance  # noqa: E402
from io_safe import (  # noqa: E402
    PathSafetyError,
    absolute_physical_path,
    canonical_json,
    confine_path,
    create_once_bytes_bound,
    create_once_text,
    read_bound_bytes,
    sha256_bytes,
    strict_json,
)


SCHEMA_DIR = Path(__file__).parents[1] / "schemas"
SHA256_RE = re.compile(r"^[A-F0-9]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,127}$")
ROLES = ("BUILDER", "VERIFIER")
WORKSPACE_GRANTS = [
    "READ_NAMED_SOURCES",
    "CREATE_DIRECTORIES_IN_PROJECT_ROOT",
    "CREATE_FILES_IN_PROJECT_ROOT",
    "WRITE_OWNED_LANE_FILES",
]
NON_GRANTS = [
    "DELETE",
    "MOVE",
    "RENAME_OUTSIDE_ROOT",
    "OVERWRITE_PREEXISTING_USER_FILE",
    "EXECUTE",
    "INSTALL",
    "PUBLISH",
    "EXTERNAL_EFFECTS",
]
PHASES = (
    "WELL_BOOTSTRAPPING",
    "WELL_READY",
    "MATERIAL_QUARANTINE",
    "MATERIAL_JOINED",
    "LANES_ACTIVE",
    "LANES_FROZEN",
    "FUSION_EMITTED",
    "KNOWLEDGE_FUSION_PASS",
)
LANE_STATES = (
    "MATERIAL_BOUND",
    "LIGHT_MAP_FROZEN",
    "DEEP_PLAN_FROZEN",
    "DEEP_RESEARCH_ACTIVE",
    "LANE_DOSSIER_READY",
    "LANE_FROZEN",
)
AUTHORITY_ACTIONS = {
    "init": "WELL_BOOTSTRAP",
    "bootstrap-well": "WELL_READY",
    "quarantine-material": "MATERIAL_QUARANTINE",
    "join-material": "MATERIAL_JOIN",
    "bind-light-map": "LANE_LIGHT_WEB_RESEARCH",
    "freeze-deep-plan": "LANE_DEEP_PLAN",
    "start-deep-research": "LANE_DEEP_WEB_RESEARCH",
    "bind-deep-dossier": "LANE_DEEP_DOSSIER",
    "freeze-lane": "LANE_FREEZE",
    "emit-fusion": "FUSION_EMIT",
    "countersign-fusion": "FUSION_COUNTERSIGN",
}
ACTION_BY_EVENT = {
    command.replace("-", "_").upper(): action
    for command, action in AUTHORITY_ACTIONS.items()
}
WEB_ACTIONS = {"LANE_LIGHT_WEB_RESEARCH", "LANE_DEEP_WEB_RESEARCH"}
DOWNLOAD_ACTIONS = {"LANE_DEEP_WEB_RESEARCH"}
SCHEMA_FILES = {
    "omni-knowledge-effect-authority-v1": "knowledge_effect_authority.schema.json",
    "omni-knowledge-pipeline-state-v1": "knowledge_pipeline_state.schema.json",
    "omni-material-join-manifest-v1": "material_join_manifest.schema.json",
    "omni-lane-knowledge-manifest-v1": "lane_knowledge_manifest.schema.json",
    "omni-knowledge-fusion-v1": "knowledge_fusion.schema.json",
    "omni-material-metadata-attestation-v1": "material_metadata_attestation.schema.json",
    "omni-light-map-v1": "light_map.schema.json",
    "omni-deep-plan-v1": "deep_plan.schema.json",
    "omni-web-research-receipt-v1": "web_research_receipt.schema.json",
    "omni-source-manifest-v1": "source_manifest.schema.json",
}


class KnowledgePipelineError(RuntimeError):
    """Typed fail-closed L3 error."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise KnowledgePipelineError(f"CLI_ARGUMENT_INVALID:{message}")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise KnowledgePipelineError(reason)


def _sha(value: str, label: str) -> str:
    normalized = value.upper()
    _require(bool(SHA256_RE.fullmatch(normalized)), f"INVALID_SHA256:{label}")
    return normalized


def _identifier(value: str, label: str) -> str:
    normalized = value.strip().upper()
    _require(bool(IDENTIFIER_RE.fullmatch(normalized)), f"INVALID_IDENTIFIER:{label}")
    return normalized


def _projection_digest(value: dict[str, Any]) -> str:
    return sha256_bytes(
        canonical_json({key: item for key, item in value.items() if key != "record_digest"}).encode("utf-8")
    )


def seal(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("record_digest", None)
    result["record_digest"] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def verify_record(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("record_digest"), str)
        and value["record_digest"] == _projection_digest(value)
    )


def _binding(path: Path, data: bytes | None = None) -> dict[str, Any]:
    if data is None:
        data, path = read_bound_bytes(path, label="FILE_BINDING")
    else:
        path = absolute_physical_path(path, "FILE_BINDING", strict=True)
    return {"path": str(path), "bytes": len(data), "sha256": sha256_bytes(data)}


def _load_bound_json(
    path: Path,
    expected_sha256: str,
    label: str,
    *,
    allowed_roots: Iterable[Path] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, physical = read_bound_bytes(
        path,
        expected_sha256=_sha(expected_sha256, label),
        allowed_roots=allowed_roots,
        label=label,
    )
    try:
        value = strict_json(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise KnowledgePipelineError(f"STRICT_JSON_INVALID:{label}") from error
    _require(isinstance(value, dict), f"JSON_OBJECT_REQUIRED:{label}")
    _require(verify_record(value), f"RECORD_DIGEST_MISMATCH:{label}")
    return value, _binding(physical, raw)


def _optional_schema_validate(record: dict[str, Any]) -> None:
    filename = SCHEMA_FILES.get(str(record.get("schema")))
    if filename is None:
        raise KnowledgePipelineError(f"UNSUPPORTED_L3_SCHEMA:{record.get('schema')}")
    schema_path = SCHEMA_DIR / filename
    if not schema_path.exists():
        raise KnowledgePipelineError(f"L3_SCHEMA_MISSING:{filename}")
    try:
        import jsonschema
    except ImportError as error:
        raise KnowledgePipelineError("JSONSCHEMA_RUNTIME_UNAVAILABLE") from error
    try:
        schema = strict_json(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise KnowledgePipelineError(f"L3_SCHEMA_UNREADABLE:{filename}") from error
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        failures = sorted(
            validator.iter_errors(record),
            key=lambda item: list(item.absolute_path),
        )
    except Exception as error:
        raise KnowledgePipelineError(
            f"L3_SCHEMA_INVALID_DEFINITION:{filename}"
        ) from error
    if failures:
        failure = failures[0]
        location = "/".join(str(part) for part in failure.absolute_path) or "$"
        raise KnowledgePipelineError(
            f"L3_SCHEMA_INVALID:{filename}:{location}:{failure.validator}"
        )


def _network_status(authority: dict[str, Any]) -> str:
    value = authority.get("network_research")
    if isinstance(value, dict):
        value = value.get("status")
    return str(value or "NOT_APPLICABLE").upper()


def _download_status(authority: dict[str, Any]) -> str:
    value = authority.get("download")
    if isinstance(value, dict):
        value = value.get("status")
    return str(value or "NOT_APPLICABLE").upper()


def _load_authority(
    path: Path,
    expected_sha256: str,
    *,
    action: str,
    task_id: str,
    pipeline_id: str,
    session_pair_sha256: str,
    role: str,
    session_id: str,
    well_root: Path,
    project_root: Path,
    source_roots: list[Path],
    intake_binding: dict[str, Any],
    workspace_access_binding: dict[str, Any],
    expected_input_bindings: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    authority, binding = _load_bound_json(
        path,
        expected_sha256,
        "EFFECT_AUTHORITY",
        allowed_roots=[project_root],
    )
    _require(
        authority.get("schema") == "omni-knowledge-effect-authority-v1",
        "KNOWLEDGE_EFFECT_AUTHORITY_SCHEMA_INVALID",
    )
    _optional_schema_validate(authority)
    status = str(authority.get("status", "")).upper()
    decision = str(authority.get("decision", "AUTHORIZED")).upper()
    if status in {"EFFECT_DENIED", "DENIED"} or decision == "DENIED":
        raise KnowledgePipelineError("BLOCKED_PENDING_HUMAN:EFFECT_AUTHORITY_DENIED")
    if status in {"EFFECT_UNAVAILABLE", "UNAVAILABLE"} or decision == "UNAVAILABLE":
        raise KnowledgePipelineError("BLOCKED_PENDING_INFRA:EFFECT_AUTHORITY_UNAVAILABLE")
    _require(status in {"EFFECT_AUTHORIZED", "AUTHORIZED"}, "KNOWLEDGE_EFFECT_AUTHORITY_MISSING")
    _require(decision == "AUTHORIZED", "KNOWLEDGE_EFFECT_AUTHORITY_DECISION_MISSING")
    _require(authority.get("action") == action, "KNOWLEDGE_EFFECT_AUTHORITY_ACTION_MISMATCH")
    _require(authority.get("task_id") == task_id, "KNOWLEDGE_EFFECT_AUTHORITY_SCOPE_REPLAY")
    _require(authority.get("pipeline_id") == pipeline_id, "KNOWLEDGE_EFFECT_AUTHORITY_SCOPE_REPLAY")
    _require(
        authority.get("session_pair_sha256") == session_pair_sha256,
        "KNOWLEDGE_EFFECT_AUTHORITY_SCOPE_REPLAY",
    )
    _require(authority.get("subject_role") == role, "KNOWLEDGE_EFFECT_AUTHORITY_SUBJECT_MISMATCH")
    _require(
        authority.get("subject_session_id") == session_id,
        "KNOWLEDGE_EFFECT_AUTHORITY_SUBJECT_MISMATCH",
    )
    _require(authority.get("one_shot") is True, "KNOWLEDGE_EFFECT_AUTHORITY_NOT_ONE_SHOT")
    _identifier(str(authority.get("operation_nonce", "")), "OPERATION_NONCE")
    _require(authority.get("non_grants") == NON_GRANTS, "KNOWLEDGE_EFFECT_AUTHORITY_BROADENED")
    _require(
        authority.get("intake_state_sha256") == intake_binding["sha256"],
        "KNOWLEDGE_EFFECT_AUTHORITY_INTAKE_MISMATCH",
    )
    _require(
        authority.get("workspace_access_envelope_binding") == workspace_access_binding,
        "KNOWLEDGE_EFFECT_AUTHORITY_ACCESS_MISMATCH",
    )
    authority_well = absolute_physical_path(
        str(authority.get("well_root", "")), "AUTHORITY_WELL_ROOT", strict=False
    )
    _require(authority_well == well_root, "KNOWLEDGE_EFFECT_AUTHORITY_SCOPE_REPLAY")
    input_roots = [project_root, *source_roots]
    input_bindings = authority.get("input_bindings")
    _require(isinstance(input_bindings, list) and input_bindings, "KNOWLEDGE_EFFECT_AUTHORITY_INPUT_MISSING")
    _require(
        sorted(canonical_json(item) for item in input_bindings)
        == sorted(canonical_json(item) for item in expected_input_bindings),
        "KNOWLEDGE_EFFECT_AUTHORITY_INPUT_MISMATCH",
    )
    for item in input_bindings:
        _require(isinstance(item, dict), "KNOWLEDGE_EFFECT_AUTHORITY_INPUT_MISSING")
        read_bound_bytes(
            Path(item["path"]),
            expected_bytes=item["bytes"],
            expected_sha256=item["sha256"],
            allowed_roots=input_roots,
            label="AUTHORITY_INPUT_BINDING",
        )
    output_paths = authority.get("output_paths")
    _require(isinstance(output_paths, list) and output_paths, "KNOWLEDGE_EFFECT_AUTHORITY_OUTPUT_MISSING")
    for output_path in output_paths:
        _inside_authority_output = absolute_physical_path(
            output_path, "AUTHORITY_OUTPUT", strict=False
        )
        _require(
            _inside_authority_output == well_root
            or _inside_authority_output.is_relative_to(well_root),
            "KNOWLEDGE_EFFECT_AUTHORITY_OUTPUT_OUTSIDE_WELL",
        )
    for key, effect_name in (
        ("network_research", "NETWORK_RESEARCH"),
        ("download", "DOWNLOAD"),
    ):
        effect = authority.get(key)
        _require(isinstance(effect, dict), f"{effect_name}_AUTHORITY_INVALID")
        _require(effect.get("effect") == effect_name, f"{effect_name}_AUTHORITY_INVALID")
        source = effect.get("authority_source_binding")
        _require(isinstance(source, dict), f"{effect_name}_AUTHORITY_SOURCE_MISSING")
        read_bound_bytes(
            Path(source["path"]),
            expected_bytes=source["bytes"],
            expected_sha256=source["sha256"],
            allowed_roots=[project_root],
            label=f"{effect_name}_AUTHORITY_SOURCE",
        )
        scope_paths = effect.get("scope_paths")
        _require(isinstance(scope_paths, list) and scope_paths, f"{effect_name}_SCOPE_MISSING")
        for scope_path in scope_paths:
            physical_scope = absolute_physical_path(
                scope_path, f"{effect_name}_SCOPE", strict=False
            )
            _require(
                physical_scope == project_root or physical_scope.is_relative_to(project_root),
                f"{effect_name}_SCOPE_OUTSIDE_PROJECT",
            )
    if action in WEB_ACTIONS:
        network = _network_status(authority)
        if network in {"DENIED", "NOT_AUTHORIZED"}:
            raise KnowledgePipelineError("BLOCKED_PENDING_HUMAN:WEB_AUTHORITY_REQUIRED")
        if network == "UNAVAILABLE":
            raise KnowledgePipelineError("BLOCKED_PENDING_INFRA:WEB_UNAVAILABLE")
        _require(network == "AUTHORIZED", "BLOCKED_PENDING_HUMAN:WEB_AUTHORITY_REQUIRED")
        _require(
            authority["network_research"].get("handling_policy") == "CAPTURE_MD_ONLY",
            "WEB_HANDLING_POLICY_INVALID",
        )
    else:
        _require(
            _network_status(authority) == "NOT_APPLICABLE",
            "UNSCOPED_NETWORK_AUTHORITY_FORBIDDEN",
        )
        _require(
            authority["network_research"].get("handling_policy") == "NOT_APPLICABLE",
            "WEB_HANDLING_POLICY_INVALID",
        )
    if action not in DOWNLOAD_ACTIONS:
        _require(
            _download_status(authority) == "NOT_APPLICABLE",
            "UNSCOPED_DOWNLOAD_AUTHORITY_FORBIDDEN",
        )
        _require(
            authority["download"].get("handling_policy") == "NO_RAW_DOWNLOAD",
            "DOWNLOAD_HANDLING_POLICY_INVALID",
        )
    return authority, binding


def _reserve_transition(
    *,
    previous_binding: dict[str, Any],
    authority: dict[str, Any],
    authority_binding: dict[str, Any],
    action: str,
    task_id: str,
    pipeline_id: str,
    role: str,
    session_id: str,
    expected_input_bindings: list[dict[str, Any]],
    well_root: Path,
    storage_root: Path | None = None,
    recovery: bool = False,
    recovery_transaction_sha256: str | None = None,
    recovery_nonce_sha256: str | None = None,
) -> dict[str, Any]:
    """Serialize one transition before any command side effect or nonce use."""
    transaction_path = (
        well_root
        / "control"
        / "transactions"
        / f"{previous_binding['sha256']}.json"
    )
    nonce_path = (
        well_root
        / "control"
        / "nonces"
        / f"{authority['operation_nonce']}.json"
    )
    _require_authorized_output(authority, transaction_path, well_root)
    _require_authorized_output(authority, nonce_path, well_root)
    owner_token = sha256_bytes(
        canonical_json(
            {
                "previous_state_binding": previous_binding,
                "authority_binding": authority_binding,
                "action": action,
                "operation_nonce": authority["operation_nonce"],
                "subject_role": role,
                "subject_session_id": session_id,
                "input_bindings": expected_input_bindings,
            }
        ).encode("utf-8")
    )
    reservation = seal({
        "schema": "omni-knowledge-transition-reservation-v1",
        "status": "RESERVED",
        "owner_token": owner_token,
        "previous_state_binding": copy.deepcopy(previous_binding),
        "authority_binding": copy.deepcopy(authority_binding),
        "action": action,
        "task_id": task_id,
        "pipeline_id": pipeline_id,
        "subject_role": role,
        "subject_session_id": session_id,
        "input_bindings": copy.deepcopy(expected_input_bindings),
        "created_at": authority["created_at"],
    })
    reservation_payload = (
        json.dumps(reservation, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    reservation_sha256 = sha256_bytes(reservation_payload)
    if recovery:
        _require(
            transaction_path.exists()
            and recovery_transaction_sha256 is not None
            and recovery_nonce_sha256 is not None,
            "TRANSITION_RECOVERY_NOT_FOUND",
        )
        _require(
            _sha(recovery_transaction_sha256, "RECOVERY_TRANSACTION")
            == reservation_sha256,
            "TRANSITION_RECOVERY_BINDING_MISMATCH",
        )
    else:
        _require(
            recovery_transaction_sha256 is None and recovery_nonce_sha256 is None,
            "TRANSITION_RECOVERY_ARGUMENT_INVALID",
        )
        if nonce_path.exists() or nonce_path.is_symlink():
            raise KnowledgePipelineError("KNOWLEDGE_EFFECT_AUTHORITY_NONCE_REPLAY")
    try:
        reservation_status = create_once_bytes_bound(
            transaction_path, reservation_payload, storage_root or well_root
        )
    except RuntimeError as error:
        if "CREATE_ONCE_COLLISION" in str(error):
            raise KnowledgePipelineError("TRANSACTION_RESERVATION_CONFLICT") from error
        raise
    if recovery:
        _require(
            reservation_status == "ALREADY_PRESENT_IDENTICAL",
            "TRANSITION_RECOVERY_NOT_FOUND",
        )
    else:
        _require(
            reservation_status == "CREATED", "TRANSACTION_RESERVATION_CONFLICT"
        )
    nonce_receipt = seal({
        "schema": "omni-knowledge-effect-nonce-v1",
        "status": "CONSUMED",
        "owner_token": owner_token,
        "operation_nonce": authority["operation_nonce"],
        "authority_binding": copy.deepcopy(authority_binding),
        "transaction_binding": _binding(transaction_path, reservation_payload),
        "action": action,
        "task_id": task_id,
        "pipeline_id": pipeline_id,
        "subject_role": role,
        "subject_session_id": session_id,
        "input_bindings": copy.deepcopy(expected_input_bindings),
        "created_at": authority["created_at"],
    })
    nonce_payload = (
        json.dumps(nonce_receipt, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    nonce_sha256 = sha256_bytes(nonce_payload)
    if recovery:
        _require(
            _sha(str(recovery_nonce_sha256), "RECOVERY_NONCE") == nonce_sha256,
            "TRANSITION_RECOVERY_BINDING_MISMATCH",
        )
    try:
        nonce_status = create_once_bytes_bound(
            nonce_path, nonce_payload, storage_root or well_root
        )
    except RuntimeError as error:
        if "CREATE_ONCE_COLLISION" in str(error):
            raise KnowledgePipelineError(
                "KNOWLEDGE_EFFECT_AUTHORITY_NONCE_REPLAY"
            ) from error
        raise
    if recovery:
        _require(
            nonce_status in {"CREATED", "ALREADY_PRESENT_IDENTICAL"},
            "TRANSITION_RECOVERY_BINDING_MISMATCH",
        )
    else:
        _require(
            nonce_status == "CREATED",
            "KNOWLEDGE_EFFECT_AUTHORITY_NONCE_REPLAY",
        )
    return {
        "owner_token": owner_token,
        "transaction_binding": _binding(transaction_path, reservation_payload),
        "operation_nonce_binding": _binding(nonce_path, nonce_payload),
        "recovered": recovery,
    }


def _validate_access_envelope(
    envelope: dict[str, Any],
    *,
    intake: dict[str, Any],
    role: str,
    well_root: Path,
) -> dict[str, Any]:
    _require(envelope.get("schema") == "omni-workspace-access-envelope-v1", "ACCESS_SCHEMA_INVALID")
    _require(verify_record(envelope), "ACCESS_RECORD_DIGEST_MISMATCH")
    _require(
        envelope.get("status") == "ACCESS_READY"
        and envelope.get("outcome") == "ACCESS_GRANTED_NON_DESTRUCTIVE"
        and envelope.get("run_kind") == "REAL",
        "AUTONOMY_UNAVAILABLE_NO_ACCESS",
    )
    _require(envelope.get("requested_capabilities") == WORKSPACE_GRANTS, "ACCESS_GRANTS_MISMATCH")
    _require(envelope.get("granted_capabilities") == WORKSPACE_GRANTS, "ACCESS_GRANTS_MISMATCH")
    _require(envelope.get("non_grants") == NON_GRANTS, "ACCESS_DESTRUCTIVE_GRANT")
    _require(
        envelope.get("task_id") == intake["state_id"]
        and envelope.get("activation_receipt_sha256")
        == intake["activation_binding"]["sha256"],
        "ACCESS_TASK_SCOPE_REPLAY",
    )
    _require(
        envelope.get("session_pair_sha256") == intake["session_pair"]["pair_sha256"],
        "ACCESS_SCOPE_REPLAY",
    )
    participant = intake["session_pair"][role.lower()]
    lane = absolute_physical_path(envelope["owned_lane_root"], f"{role}_LANE", strict=True)
    expected_lane = absolute_physical_path(participant["write_lane"], f"{role}_MANDATE_LANE", strict=True)
    _require(lane == expected_lane, "ACCESS_OWNED_LANE_MISMATCH")
    project_root = absolute_physical_path(envelope["project_root"], "PROJECT_ROOT", strict=True)
    source_roots = [
        absolute_physical_path(item, "SOURCE_ROOT", strict=True)
        for item in envelope["source_roots"]
    ]
    _require(all(item.is_dir() for item in [project_root, lane, *source_roots]), "ACCESS_ROOT_MISSING")
    _require(lane.is_relative_to(project_root), "ACCESS_PATH_OUTSIDE_ALLOWLIST")
    protected_roots = [
        well_root,
        *[
            absolute_physical_path(
                intake["session_pair"][participant]["write_lane"],
                f"{participant.upper()}_MANDATE_LANE",
                strict=True,
            )
            for participant in ("builder", "verifier")
        ],
    ]
    for source_root in source_roots:
        _require(
            not any(
                source_root == protected
                or source_root.is_relative_to(protected)
                or protected.is_relative_to(source_root)
                for protected in protected_roots
            ),
            "SOURCE_ROOT_OVERLAPS_PEER_LANE",
        )
    receipt_binding = envelope.get("probe_receipt_binding")
    _require(isinstance(receipt_binding, dict), "ACCESS_PROBE_MISSING")
    receipt_raw, receipt_path = read_bound_bytes(
        Path(receipt_binding["path"]),
        expected_bytes=receipt_binding["bytes"],
        expected_sha256=receipt_binding["sha256"],
        allowed_roots=[project_root / ".omni" / "access-probes"],
        label="ACCESS_PROBE_RECEIPT",
    )
    try:
        receipt = strict_json(receipt_raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise KnowledgePipelineError("ACCESS_PROBE_INVALID") from error
    _require(isinstance(receipt, dict) and verify_record(receipt), "ACCESS_PROBE_INVALID")
    _require(receipt.get("envelope_id") == envelope.get("envelope_id"), "ACCESS_PROBE_SCOPE_REPLAY")
    _require(
        receipt.get("task_id") == envelope.get("task_id")
        and receipt.get("activation_receipt_sha256")
        == envelope.get("activation_receipt_sha256"),
        "ACCESS_PROBE_SCOPE_REPLAY",
    )
    _require(receipt.get("session_pair_sha256") == envelope.get("session_pair_sha256"), "ACCESS_PROBE_SCOPE_REPLAY")
    _require(receipt.get("owned_lane_root") == envelope.get("owned_lane_root"), "ACCESS_PROBE_SCOPE_REPLAY")
    _require(receipt.get("create_once") is True and receipt.get("overwritten") is False and receipt.get("retained") is True, "ACCESS_PROBE_INVALID")
    read_proofs = receipt.get("read_proofs")
    _require(isinstance(read_proofs, list) and len(read_proofs) == len(source_roots), "ACCESS_PROBE_INVALID")
    for source_root, proof in zip(source_roots, read_proofs, strict=True):
        _require(isinstance(proof, dict), "ACCESS_PROBE_INVALID")
        read_bound_bytes(
            Path(proof["path"]), expected_bytes=proof["bytes"], expected_sha256=proof["sha256"],
            allowed_roots=[source_root], label="ACCESS_READ_PROOF",
        )
    return {
        "envelope_id": envelope["envelope_id"],
        "project_root": project_root,
        "source_roots": source_roots,
        "lane_root": lane,
        "receipt_path": receipt_path,
    }


def _load_state(path: Path, expected_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state, binding = _load_bound_json(path, expected_sha256, "PIPELINE_STATE")
    _require(state.get("schema") == "omni-knowledge-pipeline-state-v1", "PIPELINE_STATE_SCHEMA_INVALID")
    _optional_schema_validate(state)
    _validate_state_semantics(state)
    _validate_state_chain(state, binding)
    return state, binding


def _validate_state_semantics(state: dict[str, Any]) -> None:
    _require(state.get("phase") in PHASES, "PIPELINE_PHASE_INVALID")
    _require(isinstance(state.get("generation"), int) and state["generation"] >= 1, "PIPELINE_GENERATION_INVALID")
    _identifier(str(state.get("pipeline_id", "")), "PIPELINE_ID")
    pair = state.get("session_pair")
    _require(isinstance(pair, dict), "SESSION_PAIR_MISSING")
    _require(pair.get("pair_sha256") == state.get("session_pair_sha256"), "SESSION_PAIR_DIGEST_MISMATCH")
    builder = pair.get("builder")
    verifier = pair.get("verifier")
    _require(isinstance(builder, dict) and isinstance(verifier, dict), "SESSION_PAIR_MISSING")
    _require(builder.get("session_id") != verifier.get("session_id"), "SESSION_PAIR_NOT_DISTINCT")
    lanes = state.get("lanes")
    _require(isinstance(lanes, dict) and set(lanes) == set(ROLES), "LANE_PAIR_INVALID")
    roots = []
    for role in ROLES:
        lane = lanes[role]
        _require(lane.get("role") == role, "LANE_ROLE_MISMATCH")
        _require(lane.get("state") in LANE_STATES, "LANE_STATE_INVALID")
        _require(lane.get("session_id") == pair[role.lower()]["session_id"], "LANE_SESSION_MISMATCH")
        roots.append(absolute_physical_path(lane["lane_root"], f"{role}_LANE", strict=True))
    _validate_lane_topology(Path(state["well_root"]), roots[0], roots[1])
    evidence = state.get("evidence_bindings")
    _require(
        isinstance(evidence, list)
        and len(evidence) >= 2
        and isinstance(evidence[0], dict)
        and isinstance(evidence[1], dict),
        "STATE_TRANSITION_BINDINGS_MISSING",
    )
    if state["phase"] == "LANES_FROZEN":
        _require(all(lanes[role]["state"] == "LANE_FROZEN" for role in ROLES), "DUAL_LANE_FREEZE_MISSING")
    if state["phase"] == "KNOWLEDGE_FUSION_PASS":
        _require(state.get("status") == "PASS", "FALSE_KNOWLEDGE_PASS")
        _require(state.get("fusion", {}).get("state") == "KNOWLEDGE_FUSION_PASS", "FALSE_KNOWLEDGE_PASS")


def _validate_state_chain(
    state: dict[str, Any], current_binding: dict[str, Any]
) -> None:
    """Walk the complete physical predecessor chain and reject skips or drift."""
    project_root = absolute_physical_path(state["project_root"], "PROJECT_ROOT", strict=True)
    well_root = absolute_physical_path(state["well_root"], "WELL_ROOT", strict=True)
    evidence_roots = [
        project_root,
        *[
            absolute_physical_path(item, "SOURCE_ROOT", strict=True)
            for item in state["source_roots"]
        ],
    ]
    states_root = well_root / "control" / "states"
    expected_current = (
        states_root
        / f"{state['generation']:06d}_{state['phase']}.json"
    )
    _require(
        absolute_physical_path(current_binding["path"], "PIPELINE_STATE", strict=True)
        == absolute_physical_path(expected_current, "PIPELINE_STATE", strict=True),
        "NON_CANONICAL_STATE_PATH",
    )
    immutable = (
        "pipeline_id",
        "task_id",
        "project_root",
        "well_root",
        "intake_binding",
        "session_pair_sha256",
        "session_pair",
        "access_envelopes",
        "source_roots",
    )
    allowed_predecessor_phases = {
        "BOOTSTRAP_WELL": {"WELL_BOOTSTRAPPING"},
        "QUARANTINE_MATERIAL": {"WELL_READY"},
        "JOIN_MATERIAL": {"MATERIAL_QUARANTINE"},
        "BIND_LIGHT_MAP": {"MATERIAL_JOINED", "LANES_ACTIVE"},
        "FREEZE_DEEP_PLAN": {"LANES_ACTIVE"},
        "START_DEEP_RESEARCH": {"LANES_ACTIVE"},
        "BIND_DEEP_DOSSIER": {"LANES_ACTIVE"},
        "FREEZE_LANE": {"LANES_ACTIVE"},
        "EMIT_FUSION": {"LANES_FROZEN"},
        "COUNTERSIGN_FUSION": {"FUSION_EMITTED"},
    }
    current = state
    seen: set[str] = set()
    while True:
        transaction_binding = current["evidence_bindings"][0]
        operation_nonce_binding = current["evidence_bindings"][1]
        transition_raw, transition_path = read_bound_bytes(
            Path(transaction_binding["path"]),
            expected_bytes=transaction_binding["bytes"],
            expected_sha256=transaction_binding["sha256"],
            allowed_roots=[well_root / "control" / "transactions"],
            label="STATE_CHAIN_TRANSACTION",
        )
        nonce_raw, nonce_path = read_bound_bytes(
            Path(operation_nonce_binding["path"]),
            expected_bytes=operation_nonce_binding["bytes"],
            expected_sha256=operation_nonce_binding["sha256"],
            allowed_roots=[well_root / "control" / "nonces"],
            label="STATE_CHAIN_NONCE",
        )
        try:
            transition = strict_json(transition_raw.decode("utf-8"))
            nonce = strict_json(nonce_raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise KnowledgePipelineError("STATE_TRANSITION_BINDING_INVALID") from error
        expected_predecessor = (
            current["intake_binding"]
            if current["generation"] == 1
            else current["previous_state_binding"]
        )
        _require(
            isinstance(transition, dict)
            and isinstance(nonce, dict)
            and verify_record(transition)
            and verify_record(nonce)
            and transition.get("schema")
            == "omni-knowledge-transition-reservation-v1"
            and transition.get("status") == "RESERVED"
            and transition.get("previous_state_binding") == expected_predecessor
            and transition.get("authority_binding")
            == current["effect_authority_binding"]
            and transition.get("action") == ACTION_BY_EVENT.get(current["event"])
            and transition.get("subject_role") == current["actor"]["role"]
            and transition.get("subject_session_id")
            == current["actor"]["session_id"]
            and nonce.get("schema") == "omni-knowledge-effect-nonce-v1"
            and nonce.get("status") == "CONSUMED"
            and nonce.get("owner_token") == transition.get("owner_token")
            and nonce.get("authority_binding")
            == current["effect_authority_binding"]
            and nonce.get("transaction_binding")
            == transaction_binding,
            "STATE_TRANSITION_BINDING_INVALID",
        )
        expected_transaction_path = (
            well_root
            / "control"
            / "transactions"
            / f"{expected_predecessor['sha256']}.json"
        )
        expected_nonce_path = (
            well_root
            / "control"
            / "nonces"
            / f"{nonce['operation_nonce']}.json"
        )
        _require(
            transition_path
            == absolute_physical_path(
                expected_transaction_path, "STATE_CHAIN_TRANSACTION", strict=True
            )
            and nonce_path
            == absolute_physical_path(
                expected_nonce_path, "STATE_CHAIN_NONCE", strict=True
            ),
            "STATE_TRANSITION_BINDING_INVALID",
        )
        for evidence in [
            current["effect_authority_binding"],
            *current["evidence_bindings"],
        ]:
            read_bound_bytes(
                Path(evidence["path"]),
                expected_bytes=evidence["bytes"],
                expected_sha256=evidence["sha256"],
                allowed_roots=evidence_roots,
                label="STATE_CHAIN_EVIDENCE",
            )
        previous_binding = current["previous_state_binding"]
        if current["generation"] == 1:
            _require(previous_binding is None, "STATE_CHAIN_GENESIS_INVALID")
            _require(
                current["phase"] == "WELL_BOOTSTRAPPING"
                and current["event"] == "INIT",
                "STATE_CHAIN_GENESIS_INVALID",
            )
            return
        _require(isinstance(previous_binding, dict), "STATE_CHAIN_PREDECESSOR_MISSING")
        _require(previous_binding["sha256"] not in seen, "STATE_CHAIN_CYCLE")
        seen.add(previous_binding["sha256"])
        raw, previous_path = read_bound_bytes(
            Path(previous_binding["path"]),
            expected_bytes=previous_binding["bytes"],
            expected_sha256=previous_binding["sha256"],
            allowed_roots=[states_root],
            label="PREVIOUS_PIPELINE_STATE",
        )
        try:
            previous = strict_json(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise KnowledgePipelineError("PREVIOUS_PIPELINE_STATE_INVALID") from error
        _require(
            isinstance(previous, dict)
            and previous.get("schema") == "omni-knowledge-pipeline-state-v1"
            and verify_record(previous),
            "PREVIOUS_PIPELINE_STATE_INVALID",
        )
        _optional_schema_validate(previous)
        _validate_state_semantics(previous)
        expected_previous = (
            states_root
            / f"{previous['generation']:06d}_{previous['phase']}.json"
        )
        _require(
            previous_path
            == absolute_physical_path(
                expected_previous, "PREVIOUS_PIPELINE_STATE", strict=True
            ),
            "NON_CANONICAL_STATE_PATH",
        )
        _require(
            previous["generation"] == current["generation"] - 1,
            "STATE_CHAIN_GENERATION_SKIP",
        )
        _require(
            all(previous[key] == current[key] for key in immutable),
            "STATE_CHAIN_IDENTITY_DRIFT",
        )
        expected_phases = allowed_predecessor_phases.get(current["event"])
        _require(
            expected_phases is not None and previous["phase"] in expected_phases,
            "STATE_CHAIN_ILLEGAL_TRANSITION",
        )
        current = previous


def _actor(state: dict[str, Any], role: str) -> tuple[str, str]:
    _require(role in ROLES, "ACTOR_ROLE_INVALID")
    return role, state["session_pair"][role.lower()]["session_id"]


def _append_binding_once(
    bindings: list[dict[str, Any]], binding: dict[str, Any]
) -> None:
    if binding not in bindings:
        bindings.append(binding)


def _cli_file_binding(
    path: Path,
    expected_sha256: str | None,
    *,
    roots: Iterable[Path],
    label: str,
) -> dict[str, Any]:
    raw, physical = read_bound_bytes(
        path,
        expected_sha256=expected_sha256,
        allowed_roots=roots,
        label=label,
    )
    return _binding(physical, raw)


def _referenced_capture_bindings(
    artifact: dict[str, Any], allowed_roots: Iterable[Path], label: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    roots = list(allowed_roots)
    referenced: list[tuple[str, dict[str, Any]]] = []
    for event in artifact.get("query_events", []):
        if isinstance(event, dict) and isinstance(
            event.get("result_capture_binding"), dict
        ):
            referenced.append(("QUERY_CAPTURE", event["result_capture_binding"]))
    for source in artifact.get("sources", []):
        if isinstance(source, dict) and isinstance(source.get("capture_binding"), dict):
            referenced.append(("SOURCE_CAPTURE", source["capture_binding"]))
    for acquisition in artifact.get("acquisitions", []):
        if not isinstance(acquisition, dict):
            continue
        for key in (
            "content_binding",
            "rights_evidence_binding",
            "scan_receipt_binding",
        ):
            if isinstance(acquisition.get(key), dict):
                referenced.append((key.upper(), acquisition[key]))
    for suffix, capture in referenced:
        raw, physical = read_bound_bytes(
            Path(capture["path"]),
            expected_bytes=capture["bytes"],
            expected_sha256=capture["sha256"],
            allowed_roots=roots,
            label=f"{label}_{suffix}",
        )
        _append_binding_once(result, _binding(physical, raw))
    return result


def _expected_command_inputs(
    args: argparse.Namespace,
    command: str,
    state: dict[str, Any],
    state_binding: dict[str, Any],
    role: str,
) -> list[dict[str, Any]]:
    """Resolve every physical command input before accepting effect authority."""
    bindings = [state_binding]
    project_root = Path(state["project_root"])
    source_roots = [Path(item) for item in state["source_roots"]]
    lane_root = Path(state["lanes"][role]["lane_root"])

    if command == "quarantine-material":
        materials = args.material or []
        metadata = args.material_metadata or []
        _require(len(materials) == len(metadata), "MATERIAL_METADATA_CARDINALITY_MISMATCH")
        for source, metadata_path in zip(materials, metadata, strict=True):
            source_binding = _cli_file_binding(
                source, None, roots=source_roots, label="USER_MATERIAL"
            )
            _append_binding_once(bindings, source_binding)
            _, metadata_binding, attestation_evidence = _metadata(
                metadata_path, source_roots, state, source_binding
            )
            _append_binding_once(bindings, metadata_binding)
            for item in attestation_evidence:
                _append_binding_once(bindings, item)
    elif command == "join-material":
        _append_binding_once(bindings, state["material"]["manifest_binding"])
    elif command in {"bind-light-map", "freeze-deep-plan", "start-deep-research"}:
        lane_artifacts = state["lanes"][role]["artifacts"]
        if command == "bind-light-map":
            _append_binding_once(bindings, state["material"]["manifest_binding"])
        if command in {"freeze-deep-plan", "start-deep-research"}:
            _append_binding_once(bindings, lane_artifacts["light_map"])
        if command == "start-deep-research":
            _append_binding_once(bindings, lane_artifacts["deep_plan"])
        artifact_binding = _cli_file_binding(
            args.artifact,
            args.artifact_sha256,
            roots=[lane_root],
            label=command.upper(),
        )
        # Light/deep receipts bind the effect authority inside their own signed
        # bytes.  Making that same artifact an input of the authority creates an
        # impossible cryptographic cycle (authority -> artifact -> authority).
        # Their independent capture inputs remain authority-bound; the artifact
        # itself is state-bound after semantic validation.  The deep plan has no
        # authority back-reference and therefore remains an ordinary input.
        if command == "freeze-deep-plan":
            _append_binding_once(bindings, artifact_binding)
        if command in {"bind-light-map", "start-deep-research"}:
            artifact, _ = _load_bound_json(
                args.artifact,
                args.artifact_sha256,
                command.upper(),
                allowed_roots=[lane_root],
            )
            for capture in _referenced_capture_bindings(
                artifact, [lane_root], command.upper()
            ):
                _append_binding_once(bindings, capture)
    elif command == "bind-deep-dossier":
        lane_artifacts = state["lanes"][role]["artifacts"]
        _append_binding_once(bindings, state["material"]["manifest_binding"])
        for key in ("light_map", "deep_plan", "deep_research_receipt"):
            _append_binding_once(bindings, lane_artifacts[key])
        _append_binding_once(
            bindings,
            _cli_file_binding(
                args.artifact, args.artifact_sha256,
                roots=[lane_root], label="DEEP_DOSSIER",
            ),
        )
        source_manifest, source_binding = _load_bound_json(
            args.source_manifest,
            args.source_manifest_sha256,
            "SOURCE_MANIFEST",
            allowed_roots=[lane_root],
        )
        _append_binding_once(bindings, source_binding)
        for capture in _referenced_capture_bindings(
            source_manifest,
            [lane_root, Path(state["well_root"]) / "material" / "quarantine"],
            "SOURCE_MANIFEST",
        ):
            _append_binding_once(bindings, capture)
        acquisitions = args.acquisition or []
        digests = args.acquisition_sha256 or []
        _require(len(acquisitions) == len(digests), "ACQUISITION_CARDINALITY_MISMATCH")
        for path, digest in zip(acquisitions, digests, strict=True):
            _append_binding_once(
                bindings,
                _cli_file_binding(path, digest, roots=[lane_root], label="ACQUISITION"),
            )
    elif command == "freeze-lane":
        lane_artifacts = state["lanes"][role]["artifacts"]
        _append_binding_once(bindings, state["material"]["manifest_binding"])
        for key in (
            "light_map",
            "deep_plan",
            "deep_research_receipt",
            "deep_dossier",
            "source_manifest",
        ):
            _append_binding_once(bindings, lane_artifacts[key])
        source_manifest, _ = _load_bound_json(
            Path(lane_artifacts["source_manifest"]["path"]),
            lane_artifacts["source_manifest"]["sha256"],
            "SOURCE_MANIFEST",
            allowed_roots=[lane_root],
        )
        for capture in _referenced_capture_bindings(
            source_manifest,
            [lane_root, Path(state["well_root"]) / "material" / "quarantine"],
            "SOURCE_MANIFEST",
        ):
            _append_binding_once(bindings, capture)
    elif command == "emit-fusion":
        for participant in ROLES:
            _append_binding_once(
                bindings, state["lanes"][participant]["manifest_binding"]
            )
        _append_binding_once(
            bindings,
            _cli_file_binding(
                args.decision_register,
                args.decision_register_sha256,
                roots=[Path(state["lanes"]["BUILDER"]["lane_root"])],
                label="FUSION_DECISIONS",
            ),
        )
    elif command == "countersign-fusion":
        candidate_binding = state["fusion"]["candidate_binding"]
        _append_binding_once(bindings, candidate_binding)
        candidate, _ = _load_bound_json(
            Path(candidate_binding["path"]),
            candidate_binding["sha256"],
            "FUSION_CANDIDATE",
            allowed_roots=[Path(state["well_root"])],
        )
        for key in (
            "builder_manifest_binding",
            "verifier_manifest_binding",
            "decision_register_binding",
            "canonical_knowledge_binding",
        ):
            _append_binding_once(bindings, candidate[key])

    return bindings


def _inside(path: Path, root: Path, label: str, *, strict: bool = True) -> Path:
    try:
        return confine_path(path, root, label=label, strict=strict)
    except PathSafetyError as error:
        raise KnowledgePipelineError(str(error)) from error


def _validate_lane_topology(
    well_root: Path, builder_lane: Path, verifier_lane: Path
) -> tuple[Path, Path]:
    """Reject equal, nested, ancestor, or out-of-well lane roots."""
    try:
        well = absolute_physical_path(well_root, "WELL_ROOT", strict=True)
        builder = absolute_physical_path(
            builder_lane, "BUILDER_LANE", strict=True
        )
        verifier = absolute_physical_path(
            verifier_lane, "VERIFIER_LANE", strict=True
        )
    except (OSError, PathSafetyError, ValueError) as error:
        raise KnowledgePipelineError(str(error)) from error
    _require(
        builder.is_relative_to(well) and verifier.is_relative_to(well),
        "LANE_ROOT_OUTSIDE_WELL",
    )
    _require(builder != verifier, "LANE_ROOTS_OVERLAP")
    _require(
        not builder.is_relative_to(verifier)
        and not verifier.is_relative_to(builder),
        "LANE_ROOTS_OVERLAP",
    )
    return builder, verifier


def _require_authorized_output(
    authority: dict[str, Any], output: Path, well_root: Path
) -> Path:
    target = absolute_physical_path(output, "EFFECT_OUTPUT", strict=False)
    allowed = {
        absolute_physical_path(item, "AUTHORITY_OUTPUT", strict=False)
        for item in authority["output_paths"]
    }
    _require(target in allowed, "KNOWLEDGE_EFFECT_AUTHORITY_OUTPUT_MISMATCH")
    _require(
        target == well_root or target.is_relative_to(well_root),
        "OUTPUT_OUTSIDE_WELL",
    )
    return target


def _write_json_record(
    record: dict[str, Any], output: Path, well_root: Path, *,
    authority: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    sealed = seal(record)
    _optional_schema_validate(sealed)
    payload = (json.dumps(sealed, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    well = absolute_physical_path(well_root, "WELL_ROOT", strict=False)
    target = absolute_physical_path(output, "OUTPUT", strict=False)
    _require(target == well or target.is_relative_to(well), "OUTPUT_OUTSIDE_WELL")
    if authority is not None:
        target = _require_authorized_output(authority, target, well)
    root = project_root if project_root is not None else well
    try:
        status = create_once_bytes_bound(target, payload, root)
        observed_raw, observed_path = read_bound_bytes(
            target, expected_bytes=len(payload), expected_sha256=sha256_bytes(payload),
            allowed_roots=[well], label="OUTPUT_READBACK",
        )
    except (OSError, PathSafetyError, RuntimeError) as error:
        raise KnowledgePipelineError(str(error)) from error
    try:
        observed = strict_json(observed_raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise KnowledgePipelineError("OUTPUT_READBACK_INVALID") from error
    _require(observed == sealed and verify_record(observed), "OUTPUT_READBACK_INVALID")
    return observed, _binding(observed_path, observed_raw), status


def _prospective_binding(path: Path, data: bytes) -> dict[str, Any]:
    target = absolute_physical_path(path, "PROSPECTIVE_BINDING", strict=False)
    return {"path": str(target), "bytes": len(data), "sha256": sha256_bytes(data)}


def _preflight_create_once_target(
    output: Path,
    payload: bytes,
    well_root: Path,
    authority: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Validate scope and any deterministic pre-existing bytes before reserve."""
    target = _require_authorized_output(authority, output, well_root)
    if target.exists() or target.is_symlink():
        try:
            observed, _ = read_bound_bytes(
                target,
                allowed_roots=[well_root],
                label="CREATE_ONCE_PREFLIGHT",
            )
        except (OSError, PathSafetyError) as error:
            raise KnowledgePipelineError(str(error)) from error
        _require(observed == payload, "CREATE_ONCE_COLLISION")
    return target, _prospective_binding(target, payload)


def _preflight_state_output(
    args: argparse.Namespace,
    state: dict[str, Any],
    phase: str,
    authority: dict[str, Any],
    well_root: Path,
) -> Path:
    """Require the deterministic next-generation state slot to be unclaimed."""
    if not bool(getattr(args, "recover_transition", False)):
        nonce_path = (
            well_root
            / "control"
            / "nonces"
            / f"{authority['operation_nonce']}.json"
        )
        if nonce_path.exists() or nonce_path.is_symlink():
            raise KnowledgePipelineError(
                "KNOWLEDGE_EFFECT_AUTHORITY_NONCE_REPLAY"
            )
    target = _require_authorized_output(
        authority, _state_output(args, state, phase), well_root
    )
    _require(
        not target.exists() and not target.is_symlink(),
        "CREATE_ONCE_COLLISION",
    )
    return target


def _preflight_json_record(
    record: dict[str, Any], output: Path, well_root: Path, authority: dict[str, Any]
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    """Validate exact record bytes and output scope without creating anything."""
    sealed = seal(record)
    _optional_schema_validate(sealed)
    payload = (json.dumps(sealed, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    _, prospective = _preflight_create_once_target(
        output, payload, well_root, authority
    )
    return sealed, payload, prospective


def _state_output(args: argparse.Namespace, state: dict[str, Any], phase: str) -> Path:
    canonical = (
        Path(state["well_root"])
        / "control"
        / "states"
        / f"{state['generation'] + 1:06d}_{phase}.json"
    )
    if args.output is not None:
        requested = absolute_physical_path(args.output, "STATE_OUTPUT", strict=False)
        expected = absolute_physical_path(canonical, "STATE_OUTPUT", strict=False)
        _require(requested == expected, "NON_CANONICAL_STATE_OUTPUT_FORBIDDEN")
    return canonical


def _validate_command_preconditions(
    state: dict[str, Any], command: str, role: str
) -> None:
    """Reject illegal transitions before consuming a nonce or reservation."""
    phase = state["phase"]
    required_phases: dict[str, set[str]] = {
        "bootstrap-well": {"WELL_BOOTSTRAPPING"},
        "quarantine-material": {"WELL_READY"},
        "join-material": {"MATERIAL_QUARANTINE"},
        "bind-light-map": {"MATERIAL_JOINED", "LANES_ACTIVE"},
        "freeze-deep-plan": {"LANES_ACTIVE"},
        "start-deep-research": {"LANES_ACTIVE"},
        "bind-deep-dossier": {"LANES_ACTIVE"},
        "freeze-lane": {"LANES_ACTIVE"},
        "emit-fusion": {"LANES_FROZEN"},
        "countersign-fusion": {"FUSION_EMITTED"},
    }
    _require(
        command in required_phases and phase in required_phases[command],
        "ILLEGAL_TRANSITION",
    )
    lane_requirements = {
        "bind-light-map": "MATERIAL_BOUND",
        "freeze-deep-plan": "LIGHT_MAP_FROZEN",
        "start-deep-research": "DEEP_PLAN_FROZEN",
        "bind-deep-dossier": "DEEP_RESEARCH_ACTIVE",
        "freeze-lane": "LANE_DOSSIER_READY",
    }
    if command in lane_requirements:
        _require(
            state["lanes"][role]["state"] == lane_requirements[command],
            "ILLEGAL_LANE_TRANSITION",
        )


def _next_state(
    previous: dict[str, Any], previous_binding: dict[str, Any], *, phase: str,
    event: str, role: str, authority_binding: dict[str, Any], evidence: list[dict[str, Any]],
    created_at: str, transition: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(previous)
    result["generation"] += 1
    result["state_id"] = f"{result['pipeline_id']}-G{result['generation']:06d}"
    result["phase"] = phase
    result["status"] = "PASS" if phase == "KNOWLEDGE_FUSION_PASS" else "ACTIVE"
    result["event"] = event
    result["actor"] = {
        "role": role,
        "session_id": result["session_pair"][role.lower()]["session_id"],
    }
    result["effect_authority_binding"] = authority_binding
    result["evidence_bindings"] = [
        transition["transaction_binding"],
        transition["operation_nonce_binding"],
        *evidence,
    ]
    result["previous_state_binding"] = previous_binding
    result["created_at"] = created_at
    result.pop("record_digest", None)
    return result


def _common(args: argparse.Namespace, command: str, role: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    state, state_binding = _load_state(args.state, args.state_sha256)
    well_root = absolute_physical_path(state["well_root"], "WELL_ROOT", strict=True)
    project_root = absolute_physical_path(state["project_root"], "PROJECT_ROOT", strict=True)
    actor_role, session_id = _actor(state, role)
    _validate_command_preconditions(state, command, actor_role)
    expected_inputs = _expected_command_inputs(
        args, command, state, state_binding, actor_role
    )
    authority, authority_binding = _load_authority(
        args.authority, args.authority_sha256,
        action=AUTHORITY_ACTIONS[command], task_id=state["task_id"],
        pipeline_id=state["pipeline_id"], session_pair_sha256=state["session_pair_sha256"],
        role=actor_role, session_id=session_id, well_root=well_root,
        project_root=project_root,
        source_roots=[Path(item) for item in state["source_roots"]],
        intake_binding=state["intake_binding"],
        workspace_access_binding=state["access_envelopes"][role],
        expected_input_bindings=expected_inputs,
    )
    return state, state_binding, authority, authority_binding, well_root


def _reserve_after_preflight(
    args: argparse.Namespace,
    *,
    state: dict[str, Any],
    state_binding: dict[str, Any],
    authority: dict[str, Any],
    authority_binding: dict[str, Any],
    well_root: Path,
    command: str,
    role: str,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    actor_role, session_id = _actor(state, role)
    return _reserve_transition(
        previous_binding=state_binding,
        authority=authority,
        authority_binding=authority_binding,
        action=AUTHORITY_ACTIONS[command],
        task_id=state["task_id"],
        pipeline_id=state["pipeline_id"],
        role=actor_role,
        session_id=session_id,
        expected_input_bindings=authority["input_bindings"],
        well_root=well_root,
        storage_root=storage_root,
        recovery=bool(getattr(args, "recover_transition", False)),
        recovery_transaction_sha256=getattr(
            args, "recovery_transaction_sha256", None
        ),
        recovery_nonce_sha256=getattr(args, "recovery_nonce_sha256", None),
    )


def _emit_state(args: argparse.Namespace, previous: dict[str, Any], previous_binding: dict[str, Any], *, phase: str, event: str, role: str, authority: dict[str, Any], authority_binding: dict[str, Any], evidence: list[dict[str, Any]], created_at: str, transition: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    state = _next_state(
        previous, previous_binding, phase=phase, event=event, role=role,
        authority_binding=authority_binding, evidence=evidence, created_at=created_at,
        transition=transition,
    )
    _validate_state_semantics(state)
    output = _state_output(args, previous, phase)
    return _write_json_record(
        state,
        output,
        Path(previous["well_root"]),
        authority=authority,
    )


def command_init(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    intake, intake_binding = _load_bound_json(args.intake, args.intake_sha256, "INTAKE_STATE")
    _require(intake.get("schema") == "omni-guided-intake-state-v1", "INTAKE_SCHEMA_INVALID")
    try:
        validate_instance(intake)
    except ProtocolError as error:
        raise KnowledgePipelineError(str(error)) from error
    _require(intake.get("phase") == "INTAKE_READY" and intake.get("status") == "READY", "INTAKE_NOT_READY")
    _require(intake.get("profile") == "GODMODE", "PROFILE_DEGRADED_NOT_GODMODE")
    pipeline_id = _identifier(args.pipeline_id, "PIPELINE_ID")
    builder_envelope, builder_binding = _load_bound_json(args.builder_access, args.builder_access_sha256, "BUILDER_ACCESS")
    verifier_envelope, verifier_binding = _load_bound_json(args.verifier_access, args.verifier_access_sha256, "VERIFIER_ACCESS")
    well_root = absolute_physical_path(args.well_root, "WELL_ROOT", strict=False)
    builder_access = _validate_access_envelope(
        builder_envelope, intake=intake, role="BUILDER", well_root=well_root
    )
    verifier_access = _validate_access_envelope(
        verifier_envelope, intake=intake, role="VERIFIER", well_root=well_root
    )
    _require(builder_envelope["envelope_id"] != verifier_envelope["envelope_id"], "ACCESS_ENVELOPES_NOT_DISTINCT")
    _require(builder_access["project_root"] == verifier_access["project_root"], "ACCESS_ROOT_MISMATCH")
    _require(builder_access["source_roots"] == verifier_access["source_roots"], "ACCESS_ROOT_MISMATCH")
    project_root = builder_access["project_root"]
    _require(well_root.is_relative_to(project_root), "WELL_ROOT_OUTSIDE_PROJECT")
    _validate_lane_topology(
        well_root, builder_access["lane_root"], verifier_access["lane_root"]
    )
    role, session_id = "BUILDER", intake["session_pair"]["builder"]["session_id"]
    authority, authority_binding = _load_authority(
        args.authority, args.authority_sha256,
        action=AUTHORITY_ACTIONS["init"], task_id=intake["state_id"],
        pipeline_id=pipeline_id, session_pair_sha256=intake["session_pair"]["pair_sha256"],
        role=role, session_id=session_id, well_root=well_root,
        project_root=project_root, source_roots=builder_access["source_roots"],
        intake_binding=intake_binding,
        workspace_access_binding=builder_binding,
        expected_input_bindings=[
            intake_binding, builder_binding, verifier_binding
        ],
    )
    output = well_root / "control" / "states" / "000001_WELL_BOOTSTRAPPING.json"
    if args.output is not None:
        requested = absolute_physical_path(args.output, "STATE_OUTPUT", strict=False)
        expected = absolute_physical_path(output, "STATE_OUTPUT", strict=False)
        _require(requested == expected, "NON_CANONICAL_STATE_OUTPUT_FORBIDDEN")
    if not bool(getattr(args, "recover_transition", False)):
        nonce_path = (
            well_root
            / "control"
            / "nonces"
            / f"{authority['operation_nonce']}.json"
        )
        if nonce_path.exists() or nonce_path.is_symlink():
            raise KnowledgePipelineError(
                "KNOWLEDGE_EFFECT_AUTHORITY_NONCE_REPLAY"
            )
    output = _require_authorized_output(authority, output, well_root)
    _require(
        not output.exists() and not output.is_symlink(),
        "CREATE_ONCE_COLLISION",
    )
    transition = _reserve_transition(
        previous_binding=intake_binding,
        authority=authority,
        authority_binding=authority_binding,
        action=AUTHORITY_ACTIONS["init"],
        task_id=intake["state_id"],
        pipeline_id=pipeline_id,
        role=role,
        session_id=session_id,
        expected_input_bindings=[intake_binding, builder_binding, verifier_binding],
        well_root=well_root,
        storage_root=project_root,
        recovery=bool(getattr(args, "recover_transition", False)),
        recovery_transaction_sha256=getattr(
            args, "recovery_transaction_sha256", None
        ),
        recovery_nonce_sha256=getattr(args, "recovery_nonce_sha256", None),
    )
    state = {
        "schema": "omni-knowledge-pipeline-state-v1",
        "state_id": f"{pipeline_id}-G000001",
        "pipeline_id": pipeline_id,
        "generation": 1,
        "phase": "WELL_BOOTSTRAPPING",
        "status": "ACTIVE",
        "task_id": intake["state_id"],
        "project_root": str(project_root),
        "well_root": str(well_root),
        "intake_binding": intake_binding,
        "session_pair_sha256": intake["session_pair"]["pair_sha256"],
        "session_pair": copy.deepcopy(intake["session_pair"]),
        "access_envelopes": {"BUILDER": builder_binding, "VERIFIER": verifier_binding},
        "source_roots": [str(path) for path in builder_access["source_roots"]],
        "material": {"state": "NOT_STARTED", "manifest_binding": None},
        "lanes": {
            role_name: {
                "role": role_name,
                "session_id": intake["session_pair"][role_name.lower()]["session_id"],
                "lane_root": str(access["lane_root"]),
                "state": "MATERIAL_BOUND",
                "artifacts": {},
                "manifest_binding": None,
            }
            for role_name, access in (("BUILDER", builder_access), ("VERIFIER", verifier_access))
        },
        "fusion": {"state": "NOT_STARTED", "candidate_binding": None, "canonical_binding": None, "countersign_binding": None},
        "event": "INIT",
        "actor": {"role": role, "session_id": session_id},
        "effect_authority_binding": authority_binding,
        "evidence_bindings": [
            transition["transaction_binding"],
            transition["operation_nonce_binding"],
            intake_binding,
            builder_binding,
            verifier_binding,
        ],
        "blocking_reason_codes": [],
        "previous_state_binding": None,
        "created_at": authority["created_at"],
    }
    _validate_state_semantics(state)
    return _write_json_record(
        state,
        Path(output),
        well_root,
        authority=authority,
        project_root=project_root,
    )


def command_bootstrap_well(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, binding, authority, authority_binding, well_root = _common(args, "bootstrap-well", "BUILDER")
    _require(state["phase"] == "WELL_BOOTSTRAPPING", "ILLEGAL_TRANSITION")
    descriptor = seal({
        "schema": "omni-well-descriptor-v1", "status": "WELL_READY",
        "pipeline_id": state["pipeline_id"], "task_id": state["task_id"],
        "well_root": str(well_root), "session_pair_sha256": state["session_pair_sha256"],
        "lane_roots": {role: state["lanes"][role]["lane_root"] for role in ROLES},
        "created_at": authority["created_at"],
    })
    descriptor_path = well_root / "control" / "WELL_DESCRIPTOR.json"
    payload = (json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor_path, _ = _preflight_create_once_target(
        descriptor_path, payload, well_root, authority
    )
    _preflight_state_output(args, state, "WELL_READY", authority, well_root)
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command="bootstrap-well",
        role="BUILDER",
    )
    create_once_bytes_bound(descriptor_path, payload, well_root)
    descriptor_binding = _binding(descriptor_path, payload)
    return _emit_state(args, state, binding, phase="WELL_READY", event="BOOTSTRAP_WELL", role="BUILDER", authority=authority, authority_binding=authority_binding, evidence=[descriptor_binding], created_at=authority["created_at"], transition=transition)


INDEPENDENT_EVIDENCE_FIELDS = {
    "schema",
    "status",
    "receipt_id",
    "evidence_kind",
    "decision",
    "subject_binding",
    "issuer_role",
    "issuer_session_id",
    "tool_name",
    "tool_version",
    "created_at",
    "record_digest",
}


def _independent_evidence_receipt(
    binding: dict[str, Any],
    *,
    allowed_roots: Iterable[Path],
    state: dict[str, Any],
    producer_role: str,
    subject_binding: dict[str, Any],
    evidence_kind: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    """Verify a typed receipt issued independently of the producing lane."""
    try:
        raw, physical = read_bound_bytes(
            Path(binding["path"]),
            expected_bytes=binding["bytes"],
            expected_sha256=binding["sha256"],
            allowed_roots=list(allowed_roots),
            label=f"{evidence_kind}_EVIDENCE_RECEIPT",
        )
        receipt = strict_json(raw.decode("utf-8"))
    except (KeyError, TypeError, OSError, UnicodeError, ValueError, PathSafetyError) as error:
        raise KnowledgePipelineError(reason) from error
    _require(
        isinstance(receipt, dict)
        and set(receipt) == INDEPENDENT_EVIDENCE_FIELDS
        and receipt.get("schema") == "omni-independent-evidence-receipt-v1"
        and receipt.get("status") == "EVIDENCE_ATTESTED"
        and verify_record(receipt)
        and receipt.get("evidence_kind") == evidence_kind
        and receipt.get("decision") == decision
        and receipt.get("subject_binding") == subject_binding
        and isinstance(receipt.get("receipt_id"), str)
        and bool(receipt["receipt_id"].strip())
        and isinstance(receipt.get("tool_name"), str)
        and bool(receipt["tool_name"].strip())
        and isinstance(receipt.get("tool_version"), str)
        and bool(receipt["tool_version"].strip())
        and isinstance(receipt.get("created_at"), str)
        and bool(receipt["created_at"].strip()),
        reason,
    )
    producer_session = state["lanes"][producer_role]["session_id"]
    issuer_role = receipt.get("issuer_role")
    issuer_session = receipt.get("issuer_session_id")
    _require(
        issuer_role in {"VERIFIER", "INDEPENDENT_TOOL"}
        and isinstance(issuer_session, str)
        and bool(issuer_session.strip())
        and issuer_session != producer_session,
        reason,
    )
    if issuer_role == "VERIFIER":
        _require(
            producer_role == "BUILDER"
            and issuer_session == state["lanes"]["VERIFIER"]["session_id"],
            reason,
        )
    else:
        _require(
            issuer_session
            not in {
                state["lanes"]["BUILDER"]["session_id"],
                state["lanes"]["VERIFIER"]["session_id"],
            },
            reason,
        )
    return _binding(physical, raw)


def _metadata(
    path: Path,
    allowed_roots: Iterable[Path],
    state: dict[str, Any],
    source_binding: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    raw, physical = read_bound_bytes(
        path, allowed_roots=allowed_roots, label="MATERIAL_METADATA"
    )
    try:
        value = strict_json(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise KnowledgePipelineError("MATERIAL_METADATA_SCHEMA_INVALID") from error
    if not isinstance(value, dict) or not verify_record(value):
        raise KnowledgePipelineError("MATERIAL_METADATA_SCHEMA_INVALID")
    try:
        _require(
            value.get("schema") == "omni-material-metadata-attestation-v1",
            "MATERIAL_METADATA_SCHEMA_INVALID",
        )
        _optional_schema_validate(value)
    except KnowledgePipelineError as error:
        raise KnowledgePipelineError("MATERIAL_METADATA_SCHEMA_INVALID") from error
    _require(
        value.get("pipeline_id") == state["pipeline_id"]
        and value.get("task_id") == state["task_id"]
        and value.get("session_pair_sha256") == state["session_pair_sha256"]
        and value.get("issuer_role") == "BUILDER"
        and value.get("issuer_session_id")
        == state["lanes"]["BUILDER"]["session_id"]
        and value.get("subject_source_binding") == source_binding,
        "MATERIAL_ATTESTATION_UNBOUND",
    )
    roots = list(allowed_roots)
    evidence = [
        _independent_evidence_receipt(
            value[key],
            allowed_roots=roots,
            state=state,
            producer_role="BUILDER",
            subject_binding=source_binding,
            evidence_kind=kind,
            decision=value[status_key],
            reason="MATERIAL_ATTESTATION_UNBOUND",
        )
        for key, kind, status_key in (
            ("rights_evidence_binding", "RIGHTS", "rights_status"),
            ("privacy_evidence_binding", "PRIVACY", "privacy_status"),
            ("acl_evidence_binding", "ACL", "acl_status"),
            ("scan_receipt_binding", "SCAN", "scan_status"),
            ("parse_receipt_binding", "PARSE", "parse_status"),
        )
    ]
    return value, _binding(physical, raw), evidence


def command_quarantine_material(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, binding, authority, authority_binding, well_root = _common(args, "quarantine-material", "BUILDER")
    _require(state["phase"] == "WELL_READY", "ILLEGAL_TRANSITION")
    materials = args.material or []
    metadata_paths = args.material_metadata or []
    _require(bool(args.no_user_material) != bool(materials), "MATERIAL_DECLARATION_REQUIRED")
    _require(len(materials) == len(metadata_paths), "MATERIAL_METADATA_CARDINALITY_MISMATCH")
    items: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    prepared_materials: list[tuple[Path, bytes]] = []
    roots = [Path(item) for item in state["source_roots"]]
    for ordinal, (source, metadata_path) in enumerate(zip(materials, metadata_paths, strict=True), 1):
        raw, source_path = read_bound_bytes(source, allowed_roots=roots, label="USER_MATERIAL")
        source_binding = _binding(source_path, raw)
        metadata, metadata_binding, attestation_evidence = _metadata(
            metadata_path, roots, state, source_binding
        )
        digest = sha256_bytes(raw)
        quarantine_path = well_root / "material" / "quarantine" / f"{digest}.bin"
        quarantine_path = _require_authorized_output(
            authority, quarantine_path, well_root
        )
        quarantine_path, quarantine_binding = _preflight_create_once_target(
            quarantine_path, raw, well_root, authority
        )
        prepared_materials.append((quarantine_path, raw))
        items.append({
            "item_id": f"MAT-{ordinal:04d}-{digest[:12]}",
            "source_binding": source_binding,
            "quarantine_binding": quarantine_binding,
            "metadata_binding": metadata_binding,
            "rights_status": metadata.get("rights_status"),
            "privacy_status": metadata.get("privacy_status"),
            "acl_status": metadata.get("acl_status"),
            "scan_status": metadata.get("scan_status"),
            "parse_status": metadata.get("parse_status"),
            "admission": "PENDING",
            "rejection_reasons": [],
        })
        evidence.extend([
            source_binding,
            quarantine_binding,
            metadata_binding,
            *attestation_evidence,
        ])
    manifest = {
        "schema": "omni-material-join-manifest-v1", "status": "MATERIAL_QUARANTINED",
        "stage": "QUARANTINED", "pipeline_id": state["pipeline_id"],
        "task_id": state["task_id"], "session_pair_sha256": state["session_pair_sha256"],
        "availability": "NONE_DECLARED" if args.no_user_material else "USER_MATERIAL_PRESENT",
        "items": items, "joined_item_ids": [], "rejected_item_ids": [],
        "previous_manifest_binding": None, "created_at": authority["created_at"],
    }
    manifest_path = well_root / "control" / "material" / "MATERIAL_QUARANTINED.json"
    _preflight_json_record(manifest, manifest_path, well_root, authority)
    _preflight_state_output(
        args, state, "MATERIAL_QUARANTINE", authority, well_root
    )
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command="quarantine-material",
        role="BUILDER",
    )
    for quarantine_path, raw in prepared_materials:
        create_once_bytes_bound(quarantine_path, raw, well_root)
    _, manifest_binding, _ = _write_json_record(
        manifest, manifest_path, well_root, authority=authority
    )
    state["material"] = {"state": "MATERIAL_QUARANTINE", "manifest_binding": manifest_binding}
    return _emit_state(args, state, binding, phase="MATERIAL_QUARANTINE", event="QUARANTINE_MATERIAL", role="BUILDER", authority=authority, authority_binding=authority_binding, evidence=[*evidence, manifest_binding], created_at=authority["created_at"], transition=transition)


def command_join_material(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, binding, authority, authority_binding, well_root = _common(args, "join-material", "BUILDER")
    _require(state["phase"] == "MATERIAL_QUARANTINE", "ILLEGAL_TRANSITION")
    source_binding = state["material"]["manifest_binding"]
    source, _ = _load_bound_json(Path(source_binding["path"]), source_binding["sha256"], "QUARANTINE_MANIFEST", allowed_roots=[well_root])
    joined, rejected = [], []
    items = copy.deepcopy(source["items"])
    for item in items:
        reasons = []
        if item.get("rights_status") not in {"AUTHORIZED", "OWNED", "LICENSED", "PUBLIC"}:
            reasons.append("MATERIAL_RIGHTS_DENIED")
        if item.get("privacy_status") not in {"APPROVED", "LOCAL_ONLY"}:
            reasons.append("MATERIAL_PRIVACY_DENIED")
        if item.get("acl_status") != "WITHIN_ENVELOPE":
            reasons.append("MATERIAL_ACL_VIOLATION")
        if item.get("scan_status") != "PASS":
            reasons.append("MATERIAL_SCAN_FAILED")
        if item.get("parse_status") not in {"PASS", "NOT_APPLICABLE"}:
            reasons.append("MATERIAL_PARSE_FAILED")
        read_bound_bytes(
            Path(item["quarantine_binding"]["path"]),
            expected_bytes=item["quarantine_binding"]["bytes"],
            expected_sha256=item["quarantine_binding"]["sha256"],
            allowed_roots=[well_root / "material" / "quarantine"], label="QUARANTINED_MATERIAL",
        )
        item["rejection_reasons"] = reasons
        item["admission"] = "REJECTED" if reasons else "JOINED"
        (rejected if reasons else joined).append(item["item_id"])
    manifest = {
        **{key: copy.deepcopy(value) for key, value in source.items() if key != "record_digest"},
        "status": "MATERIAL_JOINED", "stage": "JOINED", "items": items,
        "joined_item_ids": joined, "rejected_item_ids": rejected,
        "previous_manifest_binding": source_binding, "created_at": authority["created_at"],
    }
    manifest_path = well_root / "control" / "material" / "MATERIAL_JOINED.json"
    _preflight_json_record(manifest, manifest_path, well_root, authority)
    _preflight_state_output(
        args, state, "MATERIAL_JOINED", authority, well_root
    )
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command="join-material",
        role="BUILDER",
    )
    _, manifest_binding, _ = _write_json_record(
        manifest, manifest_path, well_root, authority=authority
    )
    state["material"] = {"state": "MATERIAL_JOINED", "manifest_binding": manifest_binding}
    return _emit_state(args, state, binding, phase="MATERIAL_JOINED", event="JOIN_MATERIAL", role="BUILDER", authority=authority, authority_binding=authority_binding, evidence=[manifest_binding], created_at=authority["created_at"], transition=transition)


def _typed_schema(record: dict[str, Any], schema: str, reason: str) -> None:
    try:
        _require(record.get("schema") == schema and verify_record(record), reason)
        _optional_schema_validate(record)
    except KnowledgePipelineError as error:
        raise KnowledgePipelineError(reason) from error


def _validate_lane_scope(
    record: dict[str, Any],
    state: dict[str, Any],
    role: str,
    lane_root: Path,
    reason: str,
) -> None:
    try:
        recorded_root = absolute_physical_path(
            str(record.get("lane_root", "")), "RECORDED_LANE_ROOT", strict=True
        )
    except (PathSafetyError, OSError, ValueError) as error:
        raise KnowledgePipelineError(reason) from error
    _require(
        record.get("pipeline_id") == state["pipeline_id"]
        and record.get("task_id") == state["task_id"]
        and record.get("session_pair_sha256") == state["session_pair_sha256"]
        and record.get("role") == role
        and record.get("session_id") == state["lanes"][role]["session_id"]
        and recorded_root == absolute_physical_path(
            lane_root, "EXPECTED_LANE_ROOT", strict=True
        ),
        reason,
    )


def _source_ids(records: list[dict[str, Any]], reason: str) -> list[str]:
    identifiers = [
        _identifier(str(item.get("source_id", "")), "SOURCE_ID")
        for item in records
        if isinstance(item, dict)
    ]
    _require(
        len(identifiers) == len(records)
        and len(identifiers) == len(set(identifiers)),
        reason,
    )
    return identifiers


def _validate_web_queries(
    record: dict[str, Any], source_ids: set[str], reason: str
) -> None:
    query_events = record.get("query_events", [])
    query_ids = [
        item.get("query_id") for item in query_events if isinstance(item, dict)
    ]
    _require(
        len(query_ids) == len(query_events)
        and len(query_ids) == len(set(query_ids))
        and bool(query_ids),
        reason,
    )
    returned: set[str] = set()
    for event in query_events:
        returned_ids = set(event.get("returned_source_ids", []))
        _require(returned_ids and returned_ids.issubset(source_ids), reason)
        returned.update(returned_ids)
    _require(returned == source_ids, "NETWORK_RESEARCH_NOT_PROVEN")
    for source in record.get("sources", []):
        locator = str(source.get("locator", ""))
        _require(
            locator.startswith("https://") or locator.startswith("http://"),
            "NETWORK_RESEARCH_NOT_PROVEN",
        )


def _load_lane_record(
    binding: dict[str, Any], lane_root: Path, label: str
) -> dict[str, Any]:
    record, _ = _load_bound_json(
        Path(binding["path"]),
        binding["sha256"],
        label,
        allowed_roots=[lane_root],
    )
    return record


def _validate_light_map(
    record: dict[str, Any],
    state: dict[str, Any],
    role: str,
    lane_root: Path,
    authority_binding: dict[str, Any],
) -> None:
    reason = "LIGHT_WEB_EVIDENCE_INVALID"
    _typed_schema(record, "omni-light-map-v1", reason)
    _validate_lane_scope(record, state, role, lane_root, reason)
    _require(
        record["material_join_binding"] == state["material"]["manifest_binding"]
        and record["effect_authority_binding"] == authority_binding
        and record["network_research_performed"] is True
        and record["cross_read_performed"] is False,
        reason,
    )
    ids = _source_ids(record["sources"], reason)
    id_set = set(ids)
    _require(set(record["light_source_ids"]) == id_set, reason)
    _require(set(record["priority_source_ids"]).issubset(id_set), reason)
    _require(
        all(
            set(cluster["source_ids"]).issubset(id_set)
            for cluster in record["topic_clusters"]
        ),
        reason,
    )
    _validate_web_queries(record, id_set, reason)
    _referenced_capture_bindings(record, [lane_root], "LIGHT_MAP")


def _validate_deep_plan(
    record: dict[str, Any], state: dict[str, Any], role: str, lane_root: Path
) -> None:
    reason = "DEEP_WEB_EVIDENCE_INVALID"
    _typed_schema(record, "omni-deep-plan-v1", reason)
    _validate_lane_scope(record, state, role, lane_root, reason)
    light_binding = state["lanes"][role]["artifacts"]["light_map"]
    light = _load_lane_record(light_binding, lane_root, "LIGHT_MAP")
    _require(
        record["light_map_binding"] == light_binding
        and set(record["light_source_ids"]) == set(light["light_source_ids"])
        and record["web_research_required"] is True
        and record["cross_read_performed"] is False,
        reason,
    )


def _validate_acquisitions(
    record: dict[str, Any],
    *,
    state: dict[str, Any],
    role: str,
    lane_root: Path,
    download_authority_source: dict[str, Any] | None,
    reason: str,
) -> list[dict[str, Any]]:
    acquisitions = record.get("acquisitions", [])
    download_performed = bool(
        record.get("download_performed", record.get("download_mode") == "QUARANTINED_RAW")
    )
    if not download_performed:
        _require(
            not acquisitions and record.get("download_authority_binding") is None,
            reason,
        )
        return []
    _require(
        acquisitions
        and download_authority_source is not None
        and record.get("download_authority_binding") == download_authority_source,
        "DOWNLOAD_ATTESTATION_INVALID",
    )
    quarantine_root = lane_root / "sources" / "quarantine" / role.lower()
    result: list[dict[str, Any]] = []
    ids: list[str] = []
    acquisition_source_ids: list[str] = []
    source_by_id = {
        item["source_id"]: item
        for item in record.get("sources", [])
        if isinstance(item, dict) and "source_id" in item
    }
    for acquisition in acquisitions:
        ids.append(_identifier(acquisition["acquisition_id"], "ACQUISITION_ID"))
        acquisition_source_ids.append(
            _identifier(acquisition["source_id"], "ACQUISITION_SOURCE_ID")
        )
        source = source_by_id.get(acquisition["source_id"])
        _require(
            str(acquisition["origin_locator"]).startswith(("https://", "http://"))
            and acquisition["handling_policy"] == "QUARANTINE_HASH_NEVER_EXECUTE"
            and acquisition["scan_status"] == "PASS",
            "DOWNLOAD_ATTESTATION_INVALID",
        )
        _require(
            source is not None
            and source.get("research_phase") == "DOWNLOADED_PRIMARY"
            and source.get("capture_mode") == "QUARANTINED_RAW"
            and source.get("locator") == acquisition["origin_locator"]
            and source.get("capture_binding") == acquisition["content_binding"],
            "DOWNLOAD_ATTESTATION_INVALID",
        )
        content = acquisition["content_binding"]
        try:
            content_raw, content_path = read_bound_bytes(
                Path(content["path"]),
                expected_bytes=content["bytes"],
                expected_sha256=content["sha256"],
                allowed_roots=[quarantine_root],
                label="DOWNLOADED_CONTENT",
            )
        except (OSError, PathSafetyError) as error:
            raise KnowledgePipelineError("DOWNLOAD_NOT_IN_QUARANTINE") from error
        result.append(_binding(content_path, content_raw))
        for key, kind, status_key in (
            ("rights_evidence_binding", "RIGHTS", "rights_status"),
            ("scan_receipt_binding", "SCAN", "scan_status"),
        ):
            result.append(
                _independent_evidence_receipt(
                    acquisition[key],
                    allowed_roots=[lane_root],
                    state=state,
                    producer_role=role,
                    subject_binding=content,
                    evidence_kind=kind,
                    decision=acquisition[status_key],
                    reason="DOWNLOAD_ATTESTATION_INVALID",
                )
            )
    downloaded_source_ids = {
        item["source_id"]
        for item in record.get("sources", [])
        if isinstance(item, dict)
        and item.get("research_phase") == "DOWNLOADED_PRIMARY"
    }
    _require(
        len(ids) == len(set(ids))
        and len(acquisition_source_ids) == len(set(acquisition_source_ids))
        and set(acquisition_source_ids) == downloaded_source_ids,
        "DOWNLOAD_ATTESTATION_INVALID",
    )
    return result


def _validate_deep_receipt(
    record: dict[str, Any],
    state: dict[str, Any],
    role: str,
    lane_root: Path,
    authority: dict[str, Any],
    authority_binding: dict[str, Any],
) -> None:
    reason = "DEEP_WEB_EVIDENCE_INVALID"
    _typed_schema(record, "omni-web-research-receipt-v1", reason)
    _validate_lane_scope(record, state, role, lane_root, reason)
    lane = state["lanes"][role]
    light_binding = lane["artifacts"]["light_map"]
    plan_binding = lane["artifacts"]["deep_plan"]
    light = _load_lane_record(light_binding, lane_root, "LIGHT_MAP")
    plan = _load_lane_record(plan_binding, lane_root, "DEEP_PLAN")
    _require(
        record["light_map_binding"] == light_binding
        and record["deep_plan_binding"] == plan_binding
        and record["effect_authority_binding"] == authority_binding
        and set(record["light_source_ids"]) == set(light["light_source_ids"])
        and record["network_research_performed"] is True
        and record["cross_read_performed"] is False,
        reason,
    )
    deep_ids = set(_source_ids(record["sources"], reason))
    light_ids = set(record["light_source_ids"])
    expected_new = deep_ids - light_ids
    _require(
        set(record["deep_source_ids"]) == deep_ids
        and set(record["deep_new_source_ids"]) == expected_new
        and len(expected_new)
        >= plan["novelty_requirement"]["minimum_new_sources"],
        "DEEP_WEB_EVIDENCE_INVALID",
    )
    _validate_web_queries(record, deep_ids, reason)
    if record["download_performed"]:
        _require(
            _download_status(authority) == "AUTHORIZED"
            and authority["download"]["handling_policy"]
            == "QUARANTINE_HASH_NEVER_EXECUTE",
            "DOWNLOAD_AUTHORITY_REQUIRED",
        )
        download_source = authority["download"]["authority_source_binding"]
    else:
        _require(
            _download_status(authority) in {"NOT_APPLICABLE", "DENIED", "UNAVAILABLE"}
            and authority["download"]["handling_policy"] == "NO_RAW_DOWNLOAD",
            "DOWNLOAD_ATTESTATION_INVALID",
        )
        download_source = None
    _validate_acquisitions(
        record,
        state=state,
        role=role,
        lane_root=lane_root,
        download_authority_source=download_source,
        reason=reason,
    )
    _referenced_capture_bindings(record, [lane_root], "DEEP_RECEIPT")


def _validate_source_manifest(
    record: dict[str, Any], state: dict[str, Any], role: str, lane_root: Path
) -> None:
    reason = "SOURCE_MANIFEST_SCHEMA_INVALID"
    _typed_schema(record, "omni-source-manifest-v1", reason)
    _validate_lane_scope(record, state, role, lane_root, "LANE_MANIFEST_SCOPE_REPLAY")
    lane = state["lanes"][role]
    light_binding = lane["artifacts"]["light_map"]
    plan_binding = lane["artifacts"]["deep_plan"]
    receipt_binding = lane["artifacts"]["deep_research_receipt"]
    light = _load_lane_record(light_binding, lane_root, "LIGHT_MAP")
    receipt = _load_lane_record(receipt_binding, lane_root, "DEEP_RECEIPT")
    material, _ = _load_bound_json(
        Path(state["material"]["manifest_binding"]["path"]),
        state["material"]["manifest_binding"]["sha256"],
        "MATERIAL_JOIN_MANIFEST",
        allowed_roots=[Path(state["well_root"])],
    )
    material_ids = set(material["joined_item_ids"])
    light_ids = set(light["light_source_ids"])
    deep_ids = set(receipt["deep_source_ids"])
    _require(
        record["material_join_binding"] == state["material"]["manifest_binding"]
        and record["light_map_binding"] == light_binding
        and record["deep_plan_binding"] == plan_binding
        and record["deep_research_receipt_binding"] == receipt_binding
        and set(record["material_source_ids"]) == material_ids
        and set(record["light_source_ids"]) == light_ids
        and set(record["deep_source_ids"]) == deep_ids
        and set(record["deep_new_source_ids"])
        == set(receipt["deep_new_source_ids"])
        and record["cross_read_performed"] is False,
        "LANE_MANIFEST_SCOPE_REPLAY",
    )
    source_ids = set(_source_ids(record["sources"], reason))
    _require(source_ids == material_ids | light_ids | deep_ids, reason)
    records_by_id = {item["source_id"]: item for item in record["sources"]}
    material_by_id = {item["item_id"]: item for item in material["items"]}
    for item_id in material_ids:
        _require(
            records_by_id[item_id]["research_phase"] == "USER_MATERIAL"
            and records_by_id[item_id]["capture_mode"] == "USER_PROVIDED"
            and records_by_id[item_id]["capture_binding"]
            == material_by_id[item_id]["quarantine_binding"],
            reason,
        )
    # A source may be discovered during the light map and then re-captured with
    # stronger evidence during deep research.  The cumulative manifest has one
    # row per source_id, so the deep receipt is authoritative for that overlap;
    # light-only rows must still remain byte-for-byte faithful to the light map.
    for source in light["sources"]:
        if source["source_id"] not in deep_ids:
            _require(records_by_id.get(source["source_id"]) == source, reason)
    for source in receipt["sources"]:
        _require(records_by_id.get(source["source_id"]) == source, reason)
    received_not_used = record["received_not_used"]
    received_not_used_ids = [item["item_id"] for item in received_not_used]
    provenance_received_ids = {
        item_id
        for item in record["provenance"]
        for item_id in item["received_material_not_used"]
    }
    _require(
        len(received_not_used_ids) == len(set(received_not_used_ids))
        and set(received_not_used_ids).issubset(material_ids)
        and provenance_received_ids == set(received_not_used_ids),
        "LANE_PROVENANCE_INVALID",
    )
    _require(
        record["acquisitions"] == receipt["acquisitions"]
        and record["download_authority_binding"]
        == receipt["download_authority_binding"]
        and (
            (receipt["download_performed"] and record["download_mode"] == "QUARANTINED_RAW")
            or (
                not receipt["download_performed"]
                and record["download_mode"] == "CAPTURE_MD_ONLY"
                and record["download_fallback"] == "CAPTURE_MD_ONLY"
            )
        ),
        "DOWNLOAD_ATTESTATION_INVALID",
    )
    _validate_acquisitions(
        record,
        state=state,
        role=role,
        lane_root=lane_root,
        download_authority_source=receipt["download_authority_binding"],
        reason=reason,
    )
    _referenced_capture_bindings(
        record,
        [lane_root, Path(state["well_root"]) / "material" / "quarantine"],
        "SOURCE_MANIFEST",
    )


def _validate_frozen_lane_scope(
    manifest: dict[str, Any], state: dict[str, Any], role: str
) -> None:
    lane = state["lanes"][role]
    try:
        recorded_root = absolute_physical_path(
            manifest.get("lane_root", ""), "LANE_MANIFEST_ROOT", strict=True
        )
        expected_root = absolute_physical_path(
            lane["lane_root"], "EXPECTED_LANE_ROOT", strict=True
        )
    except (OSError, PathSafetyError, ValueError) as error:
        raise KnowledgePipelineError("LANE_MANIFEST_SCOPE_REPLAY") from error
    _require(
        manifest.get("status") == "LANE_FROZEN"
        and manifest.get("pipeline_id") == state["pipeline_id"]
        and manifest.get("task_id") == state["task_id"]
        and manifest.get("session_pair_sha256")
        == state["session_pair_sha256"]
        and manifest.get("role") == role
        and manifest.get("session_id") == lane["session_id"]
        and recorded_root == expected_root
        and manifest.get("material_join_binding")
        == state["material"]["manifest_binding"]
        and manifest.get("light_map_binding") == lane["artifacts"]["light_map"]
        and manifest.get("deep_plan_binding") == lane["artifacts"]["deep_plan"]
        and manifest.get("deep_research_receipt_binding")
        == lane["artifacts"]["deep_research_receipt"]
        and manifest.get("deep_dossier_binding")
        == lane["artifacts"]["deep_dossier"]
        and manifest.get("source_manifest_binding")
        == lane["artifacts"]["source_manifest"]
        and manifest.get("acquisitions")
        == lane["artifacts"].get("acquisitions", []),
        "LANE_MANIFEST_SCOPE_REPLAY",
    )


def _lane_artifact(args: argparse.Namespace, command: str, required_state: str, new_state: str, artifact_name: str, *, second_name: str | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    role = args.role
    state, binding, authority, authority_binding, well_root = _common(args, command, role)
    _require(state["phase"] in {"MATERIAL_JOINED", "LANES_ACTIVE"}, "ILLEGAL_TRANSITION")
    lane = state["lanes"][role]
    _require(lane["state"] == required_state, "ILLEGAL_LANE_TRANSITION")
    lane_root = Path(lane["lane_root"])
    artifact, artifact_binding = _load_bound_json(
        args.artifact,
        args.artifact_sha256,
        artifact_name.upper(),
        allowed_roots=[lane_root],
    )
    if command == "bind-light-map":
        _validate_light_map(
            artifact, state, role, lane_root, authority_binding
        )
    elif command == "freeze-deep-plan":
        _validate_deep_plan(artifact, state, role, lane_root)
    elif command == "start-deep-research":
        _validate_deep_receipt(
            artifact,
            state,
            role,
            lane_root,
            authority,
            authority_binding,
        )
    evidence = [artifact_binding]
    second_binding = None
    if second_name is not None:
        second_path = getattr(args, second_name.replace("-", "_"))
        second_sha = getattr(args, f"{second_name.replace('-', '_')}_sha256")
        second_raw, second_physical = read_bound_bytes(second_path, expected_sha256=second_sha, allowed_roots=[lane_root], label=second_name.upper())
        second_binding = _binding(second_physical, second_raw)
        _require(second_binding["path"] != artifact_binding["path"], "RESEARCH_PHASE_COLLISION")
        evidence.append(second_binding)
    _preflight_state_output(
        args, state, "LANES_ACTIVE", authority, well_root
    )
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command=command,
        role=role,
    )
    lane["artifacts"][artifact_name] = artifact_binding
    if second_name is not None and second_binding is not None:
        lane["artifacts"][second_name.replace("-", "_")] = second_binding
    lane["state"] = new_state
    return _emit_state(args, state, binding, phase="LANES_ACTIVE", event=command.replace("-", "_").upper(), role=role, authority=authority, authority_binding=authority_binding, evidence=evidence, created_at=authority["created_at"], transition=transition)


def command_bind_light_map(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    return _lane_artifact(args, "bind-light-map", "MATERIAL_BOUND", "LIGHT_MAP_FROZEN", "light_map")


def command_freeze_deep_plan(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    return _lane_artifact(args, "freeze-deep-plan", "LIGHT_MAP_FROZEN", "DEEP_PLAN_FROZEN", "deep_plan")


def command_start_deep_research(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    return _lane_artifact(args, "start-deep-research", "DEEP_PLAN_FROZEN", "DEEP_RESEARCH_ACTIVE", "deep_research_receipt")


def command_bind_deep_dossier(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    role = args.role
    state, binding, authority, authority_binding, well_root = _common(args, "bind-deep-dossier", role)
    _require(state["phase"] == "LANES_ACTIVE", "ILLEGAL_TRANSITION")
    lane = state["lanes"][role]
    _require(lane["state"] == "DEEP_RESEARCH_ACTIVE", "ILLEGAL_LANE_TRANSITION")
    lane_root = Path(lane["lane_root"])
    dossier_raw, dossier_path = read_bound_bytes(args.artifact, expected_sha256=args.artifact_sha256, allowed_roots=[lane_root], label="DEEP_DOSSIER")
    sources, sources_binding = _load_bound_json(args.source_manifest, args.source_manifest_sha256, "SOURCE_MANIFEST", allowed_roots=[lane_root])
    _validate_source_manifest(sources, state, role, lane_root)
    _require(isinstance(sources.get("sources"), list) and sources["sources"], "SOURCE_MANIFEST_EMPTY")
    acquisition_paths = args.acquisition or []
    acquisition_digests = args.acquisition_sha256 or []
    _require(
        len(acquisition_paths) == len(acquisition_digests),
        "ACQUISITION_CARDINALITY_MISMATCH",
    )
    expected_acquisitions = [
        item["content_binding"] for item in sources.get("acquisitions", [])
    ]
    acquisitions = []
    for path, digest in zip(acquisition_paths, acquisition_digests, strict=True):
        raw, physical = read_bound_bytes(
            path,
            expected_sha256=digest,
            allowed_roots=[
                lane_root / "sources" / "quarantine" / role.lower()
            ],
            label="ACQUISITION",
        )
        acquisitions.append(_binding(physical, raw))
    _require(
        sorted(canonical_json(item) for item in acquisitions)
        == sorted(canonical_json(item) for item in expected_acquisitions),
        "DOWNLOAD_ATTESTATION_INVALID",
    )
    dossier_binding = _binding(dossier_path, dossier_raw)
    _preflight_state_output(
        args, state, "LANES_ACTIVE", authority, well_root
    )
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command="bind-deep-dossier",
        role=role,
    )
    lane["artifacts"].update(deep_dossier=dossier_binding, source_manifest=sources_binding, acquisitions=acquisitions)
    lane["state"] = "LANE_DOSSIER_READY"
    return _emit_state(args, state, binding, phase="LANES_ACTIVE", event="BIND_DEEP_DOSSIER", role=role, authority=authority, authority_binding=authority_binding, evidence=[dossier_binding, sources_binding, *acquisitions], created_at=authority["created_at"], transition=transition)


def command_freeze_lane(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    role = args.role
    state, binding, authority, authority_binding, well_root = _common(args, "freeze-lane", role)
    _require(state["phase"] == "LANES_ACTIVE", "ILLEGAL_TRANSITION")
    lane = state["lanes"][role]
    _require(lane["state"] == "LANE_DOSSIER_READY", "ILLEGAL_LANE_TRANSITION")
    source_binding = lane["artifacts"]["source_manifest"]
    source_manifest, _ = _load_bound_json(Path(source_binding["path"]), source_binding["sha256"], "SOURCE_MANIFEST", allowed_roots=[Path(lane["lane_root"])])
    _validate_source_manifest(source_manifest, state, role, Path(lane["lane_root"]))
    findings = source_manifest.get("findings", [])
    dissent = source_manifest.get("dissent", [])
    provenance = source_manifest.get("provenance", [])
    source_records = source_manifest.get("sources", [])
    deep_new_source_ids = source_manifest.get("deep_new_source_ids", [])
    conflicts = source_manifest.get("conflicts", [])
    _require(isinstance(findings, list) and findings, "LANE_FINDINGS_EMPTY")
    _require(isinstance(dissent, list) and isinstance(provenance, list), "LANE_PROVENANCE_INVALID")
    _require(isinstance(source_records, list) and source_records, "LANE_SOURCES_EMPTY")
    _require(
        isinstance(deep_new_source_ids, list)
        and bool(deep_new_source_ids)
        and len(deep_new_source_ids) == len(set(deep_new_source_ids)),
        "DEEP_RESEARCH_NEW_SOURCE_REQUIRED",
    )
    _require(isinstance(conflicts, list), "LANE_CONFLICTS_INVALID")
    source_ids = [
        _identifier(str(item.get("source_id", "")), "SOURCE_ID")
        for item in source_records
        if isinstance(item, dict)
    ]
    _require(
        len(source_ids) == len(source_records)
        and len(source_ids) == len(set(source_ids)),
        "LANE_SOURCE_ID_INVALID",
    )
    source_id_set = set(source_ids)
    deep_source_ids = {
        item.get("source_id")
        for item in source_records
        if isinstance(item, dict)
        and item.get("research_phase") in {"DEEP_WEB", "DOWNLOADED_PRIMARY"}
    }
    _require(
        set(deep_new_source_ids).issubset(deep_source_ids),
        "DEEP_RESEARCH_NEW_SOURCE_INVALID",
    )
    ids = [item.get("finding_id") for item in findings if isinstance(item, dict)]
    _require(len(ids) == len(findings) and len(ids) == len(set(ids)), "LANE_FINDING_ID_INVALID")
    for item in findings:
        _require(
            set(item.get("source_ids", [])).issubset(source_id_set),
            "LANE_FINDING_SOURCE_UNKNOWN",
        )
    for item in conflicts:
        _require(
            isinstance(item, dict)
            and set(item.get("source_ids", [])).issubset(source_id_set),
            "LANE_CONFLICT_SOURCE_UNKNOWN",
        )
    for item in dissent:
        _require(
            isinstance(item, dict)
            and set(item.get("source_ids", [])).issubset(source_id_set),
            "LANE_DISSENT_SOURCE_UNKNOWN",
        )
    for item in provenance:
        _require(
            isinstance(item, dict)
            and set(item.get("sources_actually_read", [])).issubset(source_id_set),
            "LANE_PROVENANCE_SOURCE_UNKNOWN",
        )
    manifest = {
        "schema": "omni-lane-knowledge-manifest-v1", "status": "LANE_FROZEN",
        "pipeline_id": state["pipeline_id"], "task_id": state["task_id"],
        "session_pair_sha256": state["session_pair_sha256"], "role": role,
        "session_id": lane["session_id"], "lane_root": lane["lane_root"],
        "material_join_binding": state["material"]["manifest_binding"],
        "light_map_binding": lane["artifacts"]["light_map"],
        "deep_plan_binding": lane["artifacts"]["deep_plan"],
        "deep_research_receipt_binding": lane["artifacts"]["deep_research_receipt"],
        "deep_dossier_binding": lane["artifacts"]["deep_dossier"],
        "source_manifest_binding": source_binding,
        "acquisitions": lane["artifacts"].get("acquisitions", []),
        "web_research_required": True,
        "cross_read_performed": False,
        "deep_new_source_ids": deep_new_source_ids,
        "conflicts": conflicts,
        "findings": findings, "dissent": dissent, "provenance": provenance,
        "received_not_used": source_manifest.get("received_not_used", []),
        "limits": source_manifest.get("limits", []), "created_at": authority["created_at"],
    }
    manifest_path = Path(lane["lane_root"]) / "LANE_KNOWLEDGE_MANIFEST.json"
    _preflight_json_record(manifest, manifest_path, well_root, authority)
    phase = (
        "LANES_FROZEN"
        if all(
            item == role or state["lanes"][item]["state"] == "LANE_FROZEN"
            for item in ROLES
        )
        else "LANES_ACTIVE"
    )
    _preflight_state_output(args, state, phase, authority, well_root)
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command="freeze-lane",
        role=role,
    )
    _, manifest_binding, _ = _write_json_record(
        manifest, manifest_path, well_root, authority=authority
    )
    lane["manifest_binding"] = manifest_binding
    lane["state"] = "LANE_FROZEN"
    return _emit_state(args, state, binding, phase=phase, event="FREEZE_LANE", role=role, authority=authority, authority_binding=authority_binding, evidence=[manifest_binding], created_at=authority["created_at"], transition=transition)


def _validate_fusion_inputs(
    manifests: dict[str, dict[str, Any]], decisions: list[dict[str, Any]]
) -> tuple[set[str], set[str]]:
    findings = [
        item
        for role in ROLES
        for item in manifests[role]["findings"]
    ]
    finding_ids = [item["finding_id"] for item in findings]
    _require(
        len(finding_ids) == len(set(finding_ids)),
        "CROSS_LANE_FINDING_ID_COLLISION",
    )
    source_findings = set(finding_ids)
    findings_by_id = {
        item["finding_id"]: item
        for role in ROLES
        for item in manifests[role]["findings"]
    }
    dissent_by_id = {
        item["dissent_id"]: item
        for role in ROLES
        for item in manifests[role].get("dissent", [])
    }
    decision_ids: list[str] = []
    covered: list[str] = []
    preserved_list: list[str] = []
    allowed_outcomes = {
        "MERGED",
        "BUILDER_PREFERRED",
        "VERIFIER_PREFERRED",
        "UNRESOLVED_DISSENT",
    }
    for decision in decisions:
        _require(isinstance(decision, dict), "FUSION_DECISION_INVALID")
        decision_ids.append(_identifier(str(decision.get("decision_id", "")), "DECISION_ID"))
        _require(decision.get("outcome") in allowed_outcomes, "FUSION_DECISION_INVALID")
        _require(
            isinstance(decision.get("rationale"), str) and bool(decision["rationale"].strip()),
            "FUSION_DECISION_INVALID",
        )
        finding_list = decision.get("finding_ids")
        dissent_list = decision.get("dissent_ids", [])
        _require(isinstance(finding_list, list) and finding_list, "FUSION_DECISION_INVALID")
        _require(isinstance(dissent_list, list), "FUSION_DECISION_INVALID")
        if decision["outcome"] == "UNRESOLVED_DISSENT":
            _require(bool(dissent_list), "DISSENT_OUTCOME_MISMATCH")
        else:
            _require(not dissent_list, "DISSENT_OUTCOME_MISMATCH")
        decision_source_ids = {
            source_id
            for finding_id in finding_list
            for source_id in findings_by_id.get(finding_id, {}).get("source_ids", [])
        }
        for dissent_id in dissent_list:
            dissent = dissent_by_id.get(dissent_id)
            _require(dissent is not None, "DISSENT_SEMANTIC_ERASURE")
            _require(
                bool(decision_source_ids.intersection(dissent["source_ids"])),
                "DISSENT_SEMANTIC_ERASURE",
            )
        covered.extend(finding_list)
        preserved_list.extend(dissent_list)
    _require(len(decision_ids) == len(set(decision_ids)), "FUSION_DECISION_ID_COLLISION")
    _require(
        set(covered) == source_findings and len(covered) == len(set(covered)),
        "FUSION_COVERAGE_MISMATCH",
    )
    dissent_ids = {
        item["dissent_id"]
        for role in ROLES
        for item in manifests[role].get("dissent", [])
    }
    _require(
        set(preserved_list) == dissent_ids
        and len(preserved_list) == len(set(preserved_list)),
        "DISSENT_SEMANTIC_ERASURE",
    )
    _require(
        not any(
            item.get("status") == "BLOCKING"
            for role in ROLES
            for item in manifests[role].get("conflicts", [])
        ),
        "BLOCKING_KNOWLEDGE_CONFLICT",
    )
    _require(
        not any(
            item.get("status") == "ESCALATED_BLOCKING"
            for role in ROLES
            for item in manifests[role].get("dissent", [])
        ),
        "BLOCKING_KNOWLEDGE_DISSENT",
    )
    return source_findings, dissent_ids


def _render_fusion(builder: dict[str, Any], verifier: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
    lines = ["# CONOSCENZA FUSA CANONICA", "", "## Decisioni di fusione", ""]
    findings = {
        item["finding_id"]: (role, item)
        for role, manifest in (("BUILDER", builder), ("VERIFIER", verifier))
        for item in manifest["findings"]
    }
    dissents = {
        item["dissent_id"]: (role, item)
        for role, manifest in (("BUILDER", builder), ("VERIFIER", verifier))
        for item in manifest.get("dissent", [])
    }
    for decision in sorted(decisions, key=lambda item: item["decision_id"]):
        lines.extend([
            f"### {decision['decision_id']} \u2014 {decision['outcome']}",
            "",
            str(decision["rationale"]),
            "",
        ])
        for finding_id in sorted(decision["finding_ids"]):
            role, finding = findings[finding_id]
            lines.append(f"- [{role}] `{finding_id}`: {finding.get('statement', '')}")
        if decision["outcome"] == "UNRESOLVED_DISSENT":
            lines.append("- **DISSENSO NON RISOLTO \u2014 PRESERVATO**")
            for dissent_id in sorted(decision["dissent_ids"]):
                role, dissent = dissents[dissent_id]
                lines.extend([
                    f"  - [{role}] `{dissent_id}` ({dissent['status']}): {dissent['statement']}",
                    f"    Rationale: {dissent['rationale']}",
                ])
        lines.append("")
    lines.extend(["## Provenienza", ""])
    for role, manifest in (("BUILDER", builder), ("VERIFIER", verifier)):
        lines.append(f"- {role}: `{manifest['record_digest']}`")
    lines.extend(["", "## Limiti", ""])
    for role, manifest in (("BUILDER", builder), ("VERIFIER", verifier)):
        for limit in manifest.get("limits", []):
            lines.append(f"- [{role}] {limit}")
    lossless_payload = {
        "builder_lane_manifest": builder,
        "verifier_lane_manifest": verifier,
        "fusion_decisions": decisions,
    }
    lossless_json = canonical_json(lossless_payload)
    lines.extend([
        "",
        "## Registro lossless verificabile",
        "",
        "Il blocco seguente preserva integralmente source set, binding, confidence,",
        "freshness, conflitti, dissenso, provenance, ricevuti-non-usati, acquisizioni",
        "e limiti di entrambe le corsie.",
        "",
        "```json",
        lossless_json,
        "```",
    ])
    rendered = "\n".join(lines).rstrip() + "\n"
    _require(
        all(
            canonical_json(fragment) in rendered
            for fragment in (builder, verifier, decisions)
        ),
        "CANONICAL_FUSION_INFORMATION_LOSS",
    )
    return rendered


def command_emit_fusion(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, binding, authority, authority_binding, well_root = _common(args, "emit-fusion", "BUILDER")
    _require(state["phase"] == "LANES_FROZEN", "FUSION_BEFORE_DUAL_FREEZE")
    manifests = {}
    evidence = []
    for role in ROLES:
        lane_binding = state["lanes"][role]["manifest_binding"]
        manifest, physical_binding = _load_bound_json(Path(lane_binding["path"]), lane_binding["sha256"], f"{role}_LANE_MANIFEST", allowed_roots=[Path(state["lanes"][role]["lane_root"])])
        _require(manifest.get("status") == "LANE_FROZEN" and manifest.get("role") == role, "LANE_NOT_FROZEN")
        _optional_schema_validate(manifest)
        _validate_frozen_lane_scope(manifest, state, role)
        manifests[role] = manifest
        evidence.append(physical_binding)
    decisions, decisions_binding = _load_bound_json(args.decision_register, args.decision_register_sha256, "FUSION_DECISIONS", allowed_roots=[Path(state["lanes"]["BUILDER"]["lane_root"])])
    decision_list = decisions.get("decisions")
    _require(isinstance(decision_list, list) and decision_list, "FUSION_DECISIONS_EMPTY")
    finding_ids, preserved = _validate_fusion_inputs(manifests, decision_list)
    canonical = _render_fusion(manifests["BUILDER"], manifests["VERIFIER"], decision_list)
    canonical_path = args.canonical_output or well_root / "knowledge" / "CONOSCENZA_FUSA_CANONICA.md"
    canonical_raw = canonical.encode("utf-8")
    canonical_path, canonical_binding = _preflight_create_once_target(
        Path(canonical_path), canonical_raw, well_root, authority
    )
    candidate = {
        "schema": "omni-knowledge-fusion-v1", "kind": "FUSION_CANDIDATE",
        "status": "FUSION_EMITTED", "fusion_id": f"{state['pipeline_id']}-FUSION",
        "pipeline_id": state["pipeline_id"], "task_id": state["task_id"],
        "session_pair_sha256": state["session_pair_sha256"],
        "author_role": "BUILDER", "author_session_id": state["lanes"]["BUILDER"]["session_id"],
        "builder_manifest_binding": state["lanes"]["BUILDER"]["manifest_binding"],
        "verifier_manifest_binding": state["lanes"]["VERIFIER"]["manifest_binding"],
        "decision_register_binding": decisions_binding,
        "canonical_knowledge_binding": canonical_binding,
        "finding_ids": sorted(finding_ids), "dissent_ids_preserved": sorted(preserved),
        "countersigner_role": None, "countersigner_session_id": None,
        "candidate_binding": None, "created_at": authority["created_at"],
    }
    candidate_path = Path(args.candidate_output or well_root / "control" / "fusion" / "FUSION_CANDIDATE.json")
    _preflight_json_record(candidate, candidate_path, well_root, authority)
    _preflight_state_output(
        args, state, "FUSION_EMITTED", authority, well_root
    )
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command="emit-fusion",
        role="BUILDER",
    )
    create_once_text(canonical_path, canonical, allowed_root=well_root)
    _, candidate_binding, _ = _write_json_record(
        candidate, candidate_path, well_root, authority=authority
    )
    state["fusion"] = {"state": "FUSION_EMITTED", "candidate_binding": candidate_binding, "canonical_binding": canonical_binding, "countersign_binding": None}
    return _emit_state(args, state, binding, phase="FUSION_EMITTED", event="EMIT_FUSION", role="BUILDER", authority=authority, authority_binding=authority_binding, evidence=[*evidence, decisions_binding, canonical_binding, candidate_binding], created_at=authority["created_at"], transition=transition)


def command_countersign_fusion(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, binding, authority, authority_binding, well_root = _common(args, "countersign-fusion", "VERIFIER")
    _require(state["phase"] == "FUSION_EMITTED", "ILLEGAL_TRANSITION")
    candidate_binding = state["fusion"]["candidate_binding"]
    candidate, observed_candidate = _load_bound_json(Path(candidate_binding["path"]), candidate_binding["sha256"], "FUSION_CANDIDATE", allowed_roots=[well_root])
    _require(candidate.get("kind") == "FUSION_CANDIDATE" and candidate.get("status") == "FUSION_EMITTED", "FUSION_CANDIDATE_INVALID")
    _optional_schema_validate(candidate)
    _require(candidate.get("author_session_id") != state["lanes"]["VERIFIER"]["session_id"], "AUTHOR_AND_SIGN_FORBIDDEN")
    _require(
        candidate.get("author_role") == "BUILDER"
        and candidate.get("author_session_id")
        == state["lanes"]["BUILDER"]["session_id"],
        "FUSION_CANDIDATE_AUTHOR_MISMATCH",
    )
    _require(
        candidate.get("pipeline_id") == state["pipeline_id"]
        and candidate.get("task_id") == state["task_id"]
        and candidate.get("session_pair_sha256") == state["session_pair_sha256"],
        "FUSION_CANDIDATE_SCOPE_REPLAY",
    )
    _require(
        candidate.get("builder_manifest_binding")
        == state["lanes"]["BUILDER"]["manifest_binding"]
        and candidate.get("verifier_manifest_binding")
        == state["lanes"]["VERIFIER"]["manifest_binding"],
        "FUSION_CANDIDATE_LANE_MISMATCH",
    )
    manifests: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        key = f"{role.lower()}_manifest_binding"
        lane_binding = candidate[key]
        manifest, _ = _load_bound_json(
            Path(lane_binding["path"]),
            lane_binding["sha256"],
            f"{role}_LANE_MANIFEST",
            allowed_roots=[Path(state["lanes"][role]["lane_root"])],
        )
        _optional_schema_validate(manifest)
        _require(
            manifest.get("status") == "LANE_FROZEN"
            and manifest.get("role") == role,
            "LANE_NOT_FROZEN",
        )
        _validate_frozen_lane_scope(manifest, state, role)
        manifests[role] = manifest
    decisions_binding = candidate["decision_register_binding"]
    decisions, _ = _load_bound_json(
        Path(decisions_binding["path"]),
        decisions_binding["sha256"],
        "FUSION_DECISIONS",
        allowed_roots=[Path(state["lanes"]["BUILDER"]["lane_root"])],
    )
    decision_list = decisions.get("decisions")
    _require(isinstance(decision_list, list) and decision_list, "FUSION_DECISIONS_EMPTY")
    finding_ids, dissent_ids = _validate_fusion_inputs(manifests, decision_list)
    _require(
        candidate.get("finding_ids") == sorted(finding_ids)
        and candidate.get("dissent_ids_preserved") == sorted(dissent_ids),
        "FUSION_CANDIDATE_COVERAGE_MISMATCH",
    )
    canonical_binding = candidate["canonical_knowledge_binding"]
    canonical_raw, _ = read_bound_bytes(Path(canonical_binding["path"]), expected_bytes=canonical_binding["bytes"], expected_sha256=canonical_binding["sha256"], allowed_roots=[well_root], label="CANONICAL_KNOWLEDGE")
    recomputed_canonical = _render_fusion(
        manifests["BUILDER"], manifests["VERIFIER"], decision_list
    ).encode("utf-8")
    _require(
        canonical_raw == recomputed_canonical,
        "CANONICAL_KNOWLEDGE_RECOMPUTE_MISMATCH",
    )
    receipt = {
        **{key: copy.deepcopy(value) for key, value in candidate.items() if key not in {"record_digest", "kind", "status", "countersigner_role", "countersigner_session_id", "candidate_binding", "created_at"}},
        "schema": "omni-knowledge-fusion-v1", "kind": "FUSION_COUNTERSIGN",
        "status": "KNOWLEDGE_FUSION_PASS", "countersigner_role": "VERIFIER",
        "countersigner_session_id": state["lanes"]["VERIFIER"]["session_id"],
        "candidate_binding": observed_candidate, "created_at": authority["created_at"],
    }
    verifier_lane = Path(state["lanes"]["VERIFIER"]["lane_root"])
    receipt_path = (
        verifier_lane / "KNOWLEDGE_FUSION_COUNTERSIGN.json"
        if args.receipt_output is None
        else Path(args.receipt_output)
    )
    _inside(receipt_path, verifier_lane, "FUSION_COUNTERSIGN_OUTPUT", strict=False)
    _preflight_json_record(receipt, receipt_path, well_root, authority)
    _preflight_state_output(
        args,
        state,
        "KNOWLEDGE_FUSION_PASS",
        authority,
        well_root,
    )
    transition = _reserve_after_preflight(
        args,
        state=state,
        state_binding=binding,
        authority=authority,
        authority_binding=authority_binding,
        well_root=well_root,
        command="countersign-fusion",
        role="VERIFIER",
    )
    _, receipt_binding, _ = _write_json_record(
        receipt, receipt_path, well_root, authority=authority
    )
    state["fusion"]["state"] = "KNOWLEDGE_FUSION_PASS"
    state["fusion"]["countersign_binding"] = receipt_binding
    return _emit_state(args, state, binding, phase="KNOWLEDGE_FUSION_PASS", event="COUNTERSIGN_FUSION", role="VERIFIER", authority=authority, authority_binding=authority_binding, evidence=[observed_candidate, canonical_binding, receipt_binding], created_at=authority["created_at"], transition=transition)


def command_verify(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, binding = _load_state(args.state, args.state_sha256)
    _require(state["phase"] == args.expect, "EXPECTED_PHASE_MISMATCH")
    return state, binding, "VERIFIED"


COMMANDS = {
    "init": command_init,
    "bootstrap-well": command_bootstrap_well,
    "quarantine-material": command_quarantine_material,
    "join-material": command_join_material,
    "bind-light-map": command_bind_light_map,
    "freeze-deep-plan": command_freeze_deep_plan,
    "start-deep-research": command_start_deep_research,
    "bind-deep-dossier": command_bind_deep_dossier,
    "freeze-lane": command_freeze_lane,
    "emit-fusion": command_emit_fusion,
    "countersign-fusion": command_countersign_fusion,
    "verify": command_verify,
}


def _common_parser(subparsers: argparse._SubParsersAction, name: str, *, role: bool = False) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--state-sha256", required=True)
    parser.add_argument("--authority", required=True, type=Path)
    parser.add_argument("--authority-sha256", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--recover-transition", action="store_true")
    parser.add_argument("--recovery-transaction-sha256")
    parser.add_argument("--recovery-nonce-sha256")
    if role:
        parser.add_argument("--role", required=True, choices=ROLES)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--intake", required=True, type=Path)
    init.add_argument("--intake-sha256", required=True)
    init.add_argument("--builder-access", required=True, type=Path)
    init.add_argument("--builder-access-sha256", required=True)
    init.add_argument("--verifier-access", required=True, type=Path)
    init.add_argument("--verifier-access-sha256", required=True)
    init.add_argument("--authority", required=True, type=Path)
    init.add_argument("--authority-sha256", required=True)
    init.add_argument("--pipeline-id", required=True)
    init.add_argument("--well-root", required=True, type=Path)
    init.add_argument("--output", type=Path)
    init.add_argument("--recover-transition", action="store_true")
    init.add_argument("--recovery-transaction-sha256")
    init.add_argument("--recovery-nonce-sha256")
    _common_parser(subparsers, "bootstrap-well")
    quarantine = _common_parser(subparsers, "quarantine-material")
    quarantine.add_argument("--material", action="append", type=Path)
    quarantine.add_argument("--material-metadata", action="append", type=Path)
    quarantine.add_argument("--no-user-material", action="store_true")
    _common_parser(subparsers, "join-material")
    for name in ("bind-light-map", "freeze-deep-plan", "start-deep-research"):
        stage = _common_parser(subparsers, name, role=True)
        stage.add_argument("--artifact", required=True, type=Path)
        stage.add_argument("--artifact-sha256", required=True)
    dossier = _common_parser(subparsers, "bind-deep-dossier", role=True)
    dossier.add_argument("--artifact", required=True, type=Path)
    dossier.add_argument("--artifact-sha256", required=True)
    dossier.add_argument("--source-manifest", required=True, type=Path)
    dossier.add_argument("--source-manifest-sha256", required=True)
    dossier.add_argument("--acquisition", action="append", type=Path)
    dossier.add_argument("--acquisition-sha256", action="append")
    _common_parser(subparsers, "freeze-lane", role=True)
    fusion = _common_parser(subparsers, "emit-fusion")
    fusion.add_argument("--decision-register", required=True, type=Path)
    fusion.add_argument("--decision-register-sha256", required=True)
    fusion.add_argument("--canonical-output", type=Path)
    fusion.add_argument("--candidate-output", type=Path)
    countersign = _common_parser(subparsers, "countersign-fusion")
    countersign.add_argument("--receipt-output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--state", required=True, type=Path)
    verify_parser.add_argument("--state-sha256", required=True)
    verify_parser.add_argument("--expect", required=True, choices=PHASES)
    return parser


def _stable_reason(error: BaseException) -> tuple[str, str]:
    detail = str(error) or type(error).__name__
    if isinstance(
        error,
        (KnowledgePipelineError, PathSafetyError, ValueError, RuntimeError),
    ):
        candidate = detail.split(":", 1)[0]
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", candidate):
            return candidate, detail
    mapping = {
        OSError: "IO_ERROR",
        UnicodeError: "UNICODE_ERROR",
        KeyError: "MISSING_REQUIRED_FIELD",
        TypeError: "TYPE_ERROR",
        RuntimeError: "RUNTIME_GUARD_BLOCKED",
    }
    for error_type, code in mapping.items():
        if isinstance(error, error_type):
            return code, detail
    return "UNEXPECTED_RUNTIME_ERROR", detail


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        record, binding, write_status = COMMANDS[args.command](args)
        print(canonical_json({
            "schema": "omni-knowledge-command-result-v1",
            "status": "PASS",
            "command": args.command,
            "write_status": write_status,
            "phase": record.get("phase", record.get("status")),
            "output_binding": binding,
        }))
        return 0
    except (
        KnowledgePipelineError,
        PathSafetyError,
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
    ) as error:
        reason_code, detail = _stable_reason(error)
        print(canonical_json({
            "schema": "omni-knowledge-command-result-v1",
            "status": "BLOCKED",
            "reason_code": reason_code,
            "detail": detail,
        }))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

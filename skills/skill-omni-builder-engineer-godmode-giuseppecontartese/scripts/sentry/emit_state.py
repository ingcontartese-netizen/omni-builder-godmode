"""Create byte-bound states and receipts with a previous-record chain."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from io_safe import canonical_json, create_once_text, sha256_bytes, sha256_path, strict_json

VALID_OUTCOMES = {
    "PASS", "FAIL", "INCONCLUSIVE", "BLOCKED", "RUNNING", "PENDING",
    "ACTIVE", "READY", "BLOCKED_PENDING_HUMAN", "BLOCKED_PENDING_INFRA",
}
SCHEMA_DIR = Path(__file__).parents[2] / "schemas"
SCHEMA_FILES = {
    "omni-turn-state-v1": "turn_state.schema.json",
    "omni-receipt-v1": "receipt.schema.json",
    "omni-guided-intake-state-v1": "guided_intake_state.schema.json",
}

GUIDED_STATIONS = (
    "Q0_TOPOLOGY", "PARTNER_IDENTITY", "ROLE_BINDING", "FILE_OWNERSHIP",
    "TURN_ORDER", "PROHIBITIONS", "PM_RESERVED_GATES", "PROJECT_DESCRIPTION",
    "OBJECTIVE", "NON_OBJECTIVES", "SUCCESS_EVIDENCE", "BUDGETS",
    "DATA_SENSITIVITY", "REVERSIBILITY", "FORBIDDEN_EFFECTS", "ACCESS_GRANT", "USER_MATERIAL",
    "RESEARCH_LANES", "COMMUNICATION_REGIME",
)
GUIDED_CRITICAL_STATIONS = frozenset(GUIDED_STATIONS)
GUIDED_PROHIBITIONS = (
    "NO_CROSS_WRITE", "NO_AUTHOR_AND_SIGN", "NO_IMPLICIT_AUTHORITY", "NO_F5",
    "NO_INSTALLATION", "NO_PUBLICATION", "NO_EXTERNAL_EFFECTS",
)
GUIDED_PM_GATES = (
    "SCOPE_CHANGE", "AUTHORITY_EXPANSION", "KNOWLEDGE_FUSION",
    "PROGRAM_BAPTISM", "OPERATING_REGIME_BINDING", "EXTERNAL_EFFECTS",
    "INSTALLATION", "PUBLICATION",
)
MANDATE_SCHEMA = "omni-participant-mandate-v1"
WORKSPACE_GRANTS = (
    "READ_NAMED_SOURCES",
    "CREATE_DIRECTORIES_IN_PROJECT_ROOT",
    "CREATE_FILES_IN_PROJECT_ROOT",
    "WRITE_OWNED_LANE_FILES",
)
WORKSPACE_NON_GRANTS = (
    "DELETE", "MOVE", "RENAME_OUTSIDE_ROOT", "OVERWRITE_PREEXISTING_USER_FILE",
    "EXECUTE", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS",
)
FULL_ACTIVATION_AUTHORITY = ("METHOD_USE", "FULL_ORCHESTRATION")
FULL_ACTIVATION_NON_GRANTS = WORKSPACE_NON_GRANTS + (
    "CREATE_FILES", "ARM_AUTOMATION",
)
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


class ProtocolError(RuntimeError):
    pass


def validate_outcome(value: str) -> None:
    if value not in VALID_OUTCOMES:
        raise ProtocolError(f"BLOCKED_VERIFICATION_OUTCOME:{value}")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProtocolError(reason)


def _projected_digest(value: dict[str, Any], *excluded: str) -> str:
    projection = {key: item for key, item in value.items() if key not in excluded}
    return sha256_bytes(canonical_json(projection).encode("utf-8"))


def _absolute_physical_path(
    path_value: str | Path,
    label: str,
    *,
    strict: bool,
) -> Path:
    """Return one native absolute path without CWD or Win32 alias semantics."""
    value = str(path_value)
    if not value or "\x00" in value:
        raise ProtocolError(f"ABSOLUTE_PATH_REQUIRED:{label}")
    normalized = value.replace("/", "\\")
    if normalized.startswith(("\\\\?\\", "\\\\.\\")):
        raise ProtocolError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ProtocolError(f"ABSOLUTE_PATH_REQUIRED:{label}")
    windows = PureWindowsPath(value)
    drive_colon = 1 if len(windows.drive) == 2 and windows.drive[1] == ":" else None
    if any(index != drive_colon for index, char in enumerate(value) if char == ":"):
        raise ProtocolError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    for part in windows.parts[1:]:
        if part in {"\\", "/"}:
            continue
        if part.endswith((" ", ".")):
            raise ProtocolError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise ProtocolError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    try:
        return candidate.resolve(strict=strict)
    except FileNotFoundError as error:
        raise ProtocolError(f"PHYSICAL_PATH_MISSING:{label}") from error
    except OSError as error:
        raise ProtocolError(f"PHYSICAL_PATH_INVALID:{label}") from error


def _read_bound_bytes(
    path_value: str,
    expected_bytes: int,
    expected_sha256: str,
    *,
    missing_reason: str,
    non_file_reason: str,
    size_reason: str,
    hash_reason: str,
) -> tuple[bytes, Path]:
    """Open one immutable binding and reproduce its byte count and digest."""
    path = _absolute_physical_path(path_value, "FILE_BINDING", strict=False)
    _require(path.exists(), missing_reason)
    _require(path.is_file() and not path.is_symlink(), non_file_reason)
    try:
        raw = path.read_bytes()
        resolved = _absolute_physical_path(path, "FILE_BINDING", strict=True)
    except FileNotFoundError as error:
        raise ProtocolError(missing_reason) from error
    except OSError as error:
        raise ProtocolError(non_file_reason) from error
    _require(len(raw) == expected_bytes, size_reason)
    _require(sha256_bytes(raw) == expected_sha256, hash_reason)
    return raw, resolved


def _resolved_owner_lane(path_value: str, reason: str) -> Path:
    path = _absolute_physical_path(path_value, "OWNER_LANE", strict=False)
    _require(path.exists() and path.is_dir() and not path.is_symlink(), reason)
    try:
        return _absolute_physical_path(path, "OWNER_LANE", strict=True)
    except OSError as error:
        raise ProtocolError(reason) from error


def _require_owned_path(path: Path, owner_lane: Path, reason: str) -> None:
    try:
        path.relative_to(owner_lane)
    except ValueError as error:
        raise ProtocolError(reason) from error


def _question_digest(question: dict[str, Any]) -> str:
    fields = (
        "question_id", "ordinal", "station_id", "classification_before",
        "critical", "text", "relay_id",
    )
    return sha256_bytes(
        canonical_json({field: question[field] for field in fields}).encode("utf-8")
    )


def _answer_digest(answer: dict[str, Any]) -> str:
    fields = ("source", "text", "relay_id", "classification_after")
    return sha256_bytes(
        canonical_json({field: answer[field] for field in fields}).encode("utf-8")
    )


def _read_activation_receipt(binding: dict[str, Any]) -> dict[str, Any]:
    path = _absolute_physical_path(
        binding["path"], "ACTIVATION_RECEIPT", strict=False,
    )
    _require(path.is_file(), "ACTIVATION_RECEIPT_MISSING")
    try:
        raw = path.read_bytes()
        receipt = strict_json(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ProtocolError("ACTIVATION_RECEIPT_MISMATCH") from error
    _require(len(raw) == binding["bytes"], "ACTIVATION_RECEIPT_MISMATCH")
    _require(sha256_bytes(raw) == binding["sha256"], "ACTIVATION_RECEIPT_MISMATCH")
    _require(isinstance(receipt, dict), "ACTIVATION_RECEIPT_MISMATCH")
    return receipt


def _validate_guided_activation(record: dict[str, Any]) -> None:
    binding = record["activation_binding"]
    receipt = _read_activation_receipt(binding)
    _require(
        receipt.get("schema") == "omni-invocation-decision-v2"
        and receipt.get("status") == "ACTIVATION_ALLOWED"
        and receipt.get("activation_allowed") is True
        and receipt.get("intake_allowed") is True,
        "ACTIVATION_NOT_ALLOWED",
    )
    _require(binding["receipt_outcome"] == "ACCEPTED", "ACTIVATION_NOT_ALLOWED")
    _require(
        binding["activation_path"] == receipt.get("activation_path"),
        "ACTIVATION_PATH_MISMATCH",
    )
    expected_binding = {
        "decision_schema": receipt.get("schema"),
        "decision_status": receipt.get("status"),
        "task_scope": receipt.get("task_scope"),
        "run_kind": receipt.get("run_kind"),
        "effect_policy": receipt.get("effect_policy"),
        "knowledge_available": receipt.get("knowledge_available"),
        "skill_invoked": receipt.get("skill_invoked"),
        "effect_authorized": receipt.get("effect_authorized"),
        "activation_level": receipt.get("activation_level"),
        "modules_used": receipt.get("modules_used"),
        "authority_grants": receipt.get("authority_grants"),
        "artifact_grants": receipt.get("artifact_grants"),
        "requested_effects": receipt.get("requested_effects"),
        "effect_grants": receipt.get("effect_grants"),
        "non_grants": receipt.get("non_grants"),
        "access_envelope_identity": receipt.get("access_envelope_identity"),
        "activation_grants": receipt.get("activation_grants"),
        "activation_non_grants": receipt.get("activation_non_grants"),
        "intake_allowed": receipt.get("intake_allowed"),
        "mode_selection_allowed": receipt.get("mode_selection_allowed"),
        "mode_gate": receipt.get("mode_gate"),
        "next_gate": receipt.get("next_gate"),
    }
    _require(
        all(binding[key] == value for key, value in expected_binding.items()),
        "ACTIVATION_RECEIPT_MISMATCH",
    )
    _require(
        receipt.get("knowledge_available") is True
        and receipt.get("skill_invoked") is True
        and receipt.get("effect_authorized") is False
        and receipt.get("activation_level") == "OMNI_FULL"
        and receipt.get("modules_used") == []
        and tuple(receipt.get("authority_grants", ())) == FULL_ACTIVATION_AUTHORITY
        and receipt.get("artifact_grants") == []
        and receipt.get("requested_effects") == []
        and receipt.get("effect_grants") == []
        and tuple(receipt.get("non_grants", ())) == FULL_ACTIVATION_NON_GRANTS
        and receipt.get("access_envelope_identity") == "PENDING"
        and receipt.get("next_gate") == "GUIDED_INTAKE",
        "ACTIVATION_LEVEL_INSUFFICIENT",
    )
    expected_policy = (
        "DOWNSTREAM_GATED_REAL"
        if record["run_kind"] == "REAL"
        else "SIMULATE_WITHOUT_MATERIALIZATION"
    )
    if record["run_kind"] == "DRY_RUN" and record["effect_policy"] != expected_policy:
        raise ProtocolError("DRY_RUN_EFFECT_ATTEMPTED")
    _require(binding["run_kind"] == record["run_kind"], "RUN_KIND_BINDING_MISMATCH")
    _require(binding["effect_policy"] == record["effect_policy"], "RUN_KIND_BINDING_MISMATCH")
    _require(record["effect_policy"] == expected_policy, "RUN_KIND_BINDING_MISMATCH")


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_workspace_access(record: dict[str, Any]) -> dict[str, Any]:
    envelope = record["workspace_access_envelope"]
    _require(
        envelope["record_digest"] == _projected_digest(envelope, "record_digest"),
        "WORKSPACE_ACCESS_ENVELOPE_MISMATCH",
    )
    _require(
        envelope["activation_receipt_sha256"] == record["activation_binding"]["sha256"]
        and envelope["task_id"] == record["state_id"]
        and envelope["session_pair_sha256"] == record["session_pair"]["pair_sha256"]
        and envelope["run_kind"] == record["run_kind"],
        "WORKSPACE_ACCESS_SCOPE_REPLAY",
    )
    _require(
        tuple(envelope["requested_capabilities"]) == WORKSPACE_GRANTS
        and tuple(envelope["non_grants"]) == WORKSPACE_NON_GRANTS
        and envelope["separate_authorizations_required"]
        == ["NETWORK_RESEARCH", "DOWNLOAD"],
        "WORKSPACE_ACCESS_INSUFFICIENT_GRANTS",
    )
    _require(
        not set(envelope["granted_capabilities"]).intersection(WORKSPACE_NON_GRANTS),
        "WORKSPACE_ACCESS_DESTRUCTIVE_GRANT",
    )

    if record["run_kind"] == "DRY_RUN":
        _require(
            envelope["status"] == "AUTONOMY_UNAVAILABLE_NO_ACCESS"
            and envelope["outcome"] == "ACCESS_PLANNED_DRY_RUN"
            and envelope["granted_capabilities"] == []
            and envelope["probe_receipt_binding"] is None,
            "DRY_RUN_ACCESS_PASS_FORBIDDEN",
        )
        return {
            "ready": False, "project_root": None, "source_roots": (),
            "owned_lane": None, "excluded_paths": (), "probe_paths": set(),
        }

    if envelope["status"] != "ACCESS_READY":
        _require(
            envelope["outcome"] in {"ACCESS_PARTIAL", "ACCESS_DENIED"}
            and envelope["probe_receipt_binding"] is None,
            "WORKSPACE_ACCESS_ENVELOPE_MISMATCH",
        )
        return {
            "ready": False, "project_root": None, "source_roots": (),
            "owned_lane": None, "excluded_paths": (), "probe_paths": set(),
        }

    _require(
        envelope["outcome"] == "ACCESS_GRANTED_NON_DESTRUCTIVE"
        and tuple(envelope["granted_capabilities"]) == WORKSPACE_GRANTS,
        "WORKSPACE_ACCESS_INSUFFICIENT_GRANTS",
    )
    directory_values = (
        envelope["task_root"], envelope["project_root"],
        envelope["owned_lane_root"], *envelope["source_roots"],
    )
    directories: list[Path] = []
    for ordinal, value in enumerate(directory_values):
        label = (
            "WORKSPACE_TASK_ROOT" if ordinal == 0
            else "WORKSPACE_PROJECT_ROOT" if ordinal == 1
            else "WORKSPACE_OWNED_LANE_ROOT" if ordinal == 2
            else "WORKSPACE_SOURCE_ROOT"
        )
        path = _absolute_physical_path(value, label, strict=False)
        _require(path.exists(), "WORKSPACE_ACCESS_ROOT_MISSING")
        _require(path.is_dir() and not path.is_symlink(), "WORKSPACE_ACCESS_ROOT_NOT_DIRECTORY")
        directories.append(_absolute_physical_path(path, label, strict=True))
    task_root, project_root, owned_lane, *source_roots = directories
    _require(
        _within(project_root, task_root) and _within(owned_lane, project_root),
        "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
    )
    _require(
        len(source_roots) == len(set(source_roots)),
        "WORKSPACE_ACCESS_SCOPE_REPLAY",
    )
    participant_lanes: list[Path] = []
    for role in ("builder", "verifier"):
        participant = record["session_pair"].get(role)
        _require(isinstance(participant, dict), "WORKSPACE_ACCESS_SESSION_PAIR_MISSING")
        lane_value = participant.get("write_lane")
        _require(
            isinstance(lane_value, str) and bool(lane_value.strip()),
            "WORKSPACE_ACCESS_WRITE_LANE_INVALID",
        )
        participant_lanes.append(
            _absolute_physical_path(
                lane_value, f"WORKSPACE_{role.upper()}_LANE", strict=True,
            )
        )
    protected_write_roots = {owned_lane, *participant_lanes}
    _require(
        all(
            not _within(source_root, protected)
            and not _within(protected, source_root)
            for source_root in source_roots
            for protected in protected_write_roots
        ),
        "WORKSPACE_SOURCE_WRITE_SCOPE_OVERLAP",
    )
    excluded_paths: list[Path] = []
    for excluded in envelope["excluded_paths"]:
        excluded_path = _absolute_physical_path(
            excluded, "WORKSPACE_EXCLUDED_PATH", strict=False,
        )
        _require(
            any(_within(excluded_path, root) for root in (project_root, *source_roots)),
            "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
        )
        excluded_paths.append(excluded_path)

    binding = envelope["probe_receipt_binding"]
    _require(binding is not None, "WORKSPACE_ACCESS_PROBE_MISSING")
    control_root = project_root / ".omni" / "access-probes"
    _require(control_root.exists(), "WORKSPACE_ACCESS_PROBE_MISSING")
    _require(
        control_root.is_dir() and not control_root.is_symlink(),
        "WORKSPACE_ACCESS_PROBE_NOT_REGULAR_FILE",
    )
    control_root = control_root.resolve(strict=True)
    raw, receipt_path = _read_bound_bytes(
        binding["path"], binding["bytes"], binding["sha256"],
        missing_reason="WORKSPACE_ACCESS_PROBE_MISSING",
        non_file_reason="WORKSPACE_ACCESS_PROBE_NOT_REGULAR_FILE",
        size_reason="WORKSPACE_ACCESS_PROBE_SIZE_MISMATCH",
        hash_reason="WORKSPACE_ACCESS_PROBE_HASH_MISMATCH",
    )
    _require_owned_path(
        receipt_path, control_root, "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
    )
    try:
        receipt = strict_json(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ProtocolError("WORKSPACE_ACCESS_PROBE_CONTENT_MISMATCH") from error
    _require(
        isinstance(receipt, dict)
        and receipt.get("record_digest")
        == _projected_digest(receipt, "record_digest"),
        "WORKSPACE_ACCESS_PROBE_CONTENT_MISMATCH",
    )
    expected_keys = {
        "schema", "status", "receipt_id", "envelope_id",
        "activation_receipt_sha256", "task_id", "task_root", "project_root",
        "source_roots", "owned_lane_root", "session_pair_sha256", "capabilities",
        "probe_path", "probe_bytes", "probe_sha256", "create_once", "overwritten",
        "retained", "read_proofs", "record_digest",
    }
    _require(set(receipt) == expected_keys, "WORKSPACE_ACCESS_PROBE_CONTENT_MISMATCH")
    expected_receipt = {
        "schema": "omni-workspace-access-probe-receipt-v1",
        "status": "CREATE_ONCE_PROBE_RETAINED",
        "envelope_id": envelope["envelope_id"],
        "activation_receipt_sha256": envelope["activation_receipt_sha256"],
        "task_id": envelope["task_id"],
        "task_root": envelope["task_root"],
        "project_root": envelope["project_root"],
        "source_roots": envelope["source_roots"],
        "owned_lane_root": envelope["owned_lane_root"],
        "session_pair_sha256": envelope["session_pair_sha256"],
        "capabilities": list(WORKSPACE_GRANTS),
        "create_once": True,
        "overwritten": False,
        "retained": True,
    }
    _require(
        all(receipt.get(key) == value for key, value in expected_receipt.items()),
        "WORKSPACE_ACCESS_PROBE_CONTENT_MISMATCH",
    )
    _require(
        isinstance(receipt["receipt_id"], str) and bool(receipt["receipt_id"]),
        "WORKSPACE_ACCESS_PROBE_CONTENT_MISMATCH",
    )
    _, probe_path = _read_bound_bytes(
        receipt["probe_path"], receipt["probe_bytes"], receipt["probe_sha256"],
        missing_reason="WORKSPACE_ACCESS_PROBE_MISSING",
        non_file_reason="WORKSPACE_ACCESS_PROBE_NOT_REGULAR_FILE",
        size_reason="WORKSPACE_ACCESS_PROBE_SIZE_MISMATCH",
        hash_reason="WORKSPACE_ACCESS_PROBE_HASH_MISMATCH",
    )
    _require_owned_path(
        probe_path, control_root, "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
    )
    _require(probe_path != receipt_path, "WORKSPACE_ACCESS_SCOPE_REPLAY")
    read_proofs = receipt.get("read_proofs")
    _require(
        isinstance(read_proofs, list) and len(read_proofs) == len(source_roots),
        "WORKSPACE_ACCESS_PROBE_CONTENT_MISMATCH",
    )
    proof_paths: set[Path] = {receipt_path, probe_path}
    for source_root, proof in zip(source_roots, read_proofs, strict=True):
        _require(
            isinstance(proof, dict)
            and set(proof) == {"path", "bytes", "sha256"},
            "WORKSPACE_ACCESS_PROBE_CONTENT_MISMATCH",
        )
        _, proof_path = _read_bound_bytes(
            proof["path"], proof["bytes"], proof["sha256"],
            missing_reason="WORKSPACE_ACCESS_PROBE_MISSING",
            non_file_reason="WORKSPACE_ACCESS_PROBE_NOT_REGULAR_FILE",
            size_reason="WORKSPACE_ACCESS_PROBE_SIZE_MISMATCH",
            hash_reason="WORKSPACE_ACCESS_PROBE_HASH_MISMATCH",
        )
        _require_owned_path(
            proof_path, source_root, "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
        )
        _require(
            all(not _within(proof_path, protected) for protected in protected_write_roots),
            "WORKSPACE_READ_PROOF_SELF_AUTHORED",
        )
        _require(proof_path not in proof_paths, "WORKSPACE_ACCESS_SCOPE_REPLAY")
        proof_paths.add(proof_path)
    return {
        "ready": True,
        "task_root": task_root,
        "project_root": project_root,
        "source_roots": tuple(source_roots),
        "owned_lane": owned_lane,
        "excluded_paths": tuple(excluded_paths),
        "probe_paths": proof_paths,
    }


def _validate_guided_session_pair(record: dict[str, Any], access: dict[str, Any]) -> None:
    pair = record["session_pair"]
    builder = pair["builder"]
    verifier = pair["verifier"]
    _require(
        pair["pair_sha256"] == _projected_digest(pair, "pair_sha256"),
        "SESSION_PAIR_DRIFT",
    )
    _require(
        builder["role"] == "BUILDER" and verifier["role"] == "VERIFIER",
        "SESSION_PAIR_DRIFT",
    )
    distinct_fields = ("session_id", "mandate_path", "write_lane")
    pair_is_distinct = (
        all(builder[field] != verifier[field] for field in distinct_fields)
        and not set(builder["owned_paths"]).intersection(verifier["owned_paths"])
    )
    identity_key = lambda value: " ".join(value.casefold().split())
    same_identity = identity_key(builder["identity"]) == identity_key(verifier["identity"])
    if record["profile"] == "GODMODE":
        _require(pair_is_distinct, "SESSION_PAIR_NOT_DISTINCT")
        if record["topology"] == "TEAM_DUAL_LANE":
            _require(not same_identity, "IDENTITY_NOT_DISTINCT")
            _require(
                record["independence"] == "PEER_INDEPENDENT",
                "INDEPENDENCE_PROFILE_MISMATCH",
            )
        else:
            _require(same_identity, "INDEPENDENCE_PROFILE_MISMATCH")
            _require(
                record["independence"] == "ADVERSARIAL_SOLO",
                "INDEPENDENCE_PROFILE_MISMATCH",
            )
    else:
        _require(not pair_is_distinct, "PROFILE_DEGRADED_NOT_GODMODE")
        _require(
            record["independence"] == "NOT_QUALIFIED",
            "INDEPENDENCE_PROFILE_MISMATCH",
        )

    mandate_paths: set[Path] = set()
    lane_paths: list[Path] = []
    for participant in (builder, verifier):
        lane = _resolved_owner_lane(
            participant["write_lane"], "MANDATE_OUTSIDE_OWNER_LANE",
        )
        lane_paths.append(lane)
        if access["ready"]:
            _require_owned_path(
                lane, access["owned_lane"], "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
            )
        owned_paths = [
            _absolute_physical_path(value, "PARTICIPANT_OWNED_PATH", strict=False)
            for value in participant["owned_paths"]
        ]
        _require(lane in owned_paths, "MANDATE_OUTSIDE_OWNER_LANE")
        _require(
            all(_within(path, lane) for path in owned_paths),
            "MANDATE_OUTSIDE_OWNER_LANE",
        )
        raw, mandate_path = _read_bound_bytes(
            participant["mandate_path"],
            participant["mandate_bytes"],
            participant["mandate_sha256"],
            missing_reason="MANDATE_ARTIFACT_MISSING",
            non_file_reason="MANDATE_ARTIFACT_NOT_REGULAR_FILE",
            size_reason="MANDATE_ARTIFACT_SIZE_MISMATCH",
            hash_reason="MANDATE_ARTIFACT_HASH_MISMATCH",
        )
        _require_owned_path(mandate_path, lane, "MANDATE_OUTSIDE_OWNER_LANE")
        _require(mandate_path not in mandate_paths, "MANDATE_PATH_DUPLICATE")
        mandate_paths.add(mandate_path)
        try:
            mandate = strict_json(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ProtocolError("MANDATE_CONTENT_MISMATCH") from error
        expected_mandate = {
            "schema": MANDATE_SCHEMA,
            "role": participant["role"],
            "identity": participant["identity"],
            "host": participant["host"],
            "session_id": participant["session_id"],
            "write_lane": participant["write_lane"],
            "owned_paths": participant["owned_paths"],
        }
        _require(mandate == expected_mandate, "MANDATE_CONTENT_MISMATCH")
    if record["profile"] == "GODMODE":
        _require(lane_paths[0] != lane_paths[1], "SESSION_PAIR_NOT_DISTINCT")


def _relay_index(
    record: dict[str, Any], access: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    relay = record["relay"]
    _require(relay["transport"] == "PM_RELAY", "PM_RELAY_MISLABELED_AS_GOVERNED_CHANNEL")
    _require(relay["governed_channel_equivalent"] is False, "PM_RELAY_MISLABELED_AS_GOVERNED_CHANNEL")
    _require(relay["state"] == "ACTIVE", "RELAY_STATE_INVALID")
    _require(
        relay["session_pair_sha256"] == record["session_pair"]["pair_sha256"],
        "SESSION_PAIR_CHANGED_BEFORE_CUTOVER",
    )
    records = relay["records"]
    ids = [item["relay_id"] for item in records]
    ordinals = [item["ordinal"] for item in records]
    _require(len(ids) == len(set(ids)), "RELAY_ID_DUPLICATE")
    _require(
        ordinals == list(range(1, len(records) + 1)),
        "RELAY_SEQUENCE_INVALID",
    )
    _require(
        all(item["relay_id"] == f"RELAY-{item['ordinal']:03d}" for item in records),
        "RELAY_SEQUENCE_INVALID",
    )
    _require(all(item["phase"] == "GUIDED_INTAKE" for item in records), "RELAY_STATE_INVALID")
    pair = record["session_pair"]
    owner_lanes = {
        "PM": _resolved_owner_lane(relay["pm_write_lane"], "RELAY_PAYLOAD_OUTSIDE_OWNER_LANE"),
        "BUILDER": _resolved_owner_lane(
            pair["builder"]["write_lane"], "RELAY_PAYLOAD_OUTSIDE_OWNER_LANE",
        ),
        "VERIFIER": _resolved_owner_lane(
            pair["verifier"]["write_lane"], "RELAY_PAYLOAD_OUTSIDE_OWNER_LANE",
        ),
    }
    if access["ready"]:
        _require(
            all(_within(lane, access["owned_lane"]) for lane in owner_lanes.values()),
            "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
        )
    seen_paths: set[Path] = set()
    for item in records:
        _, payload_path = _read_bound_bytes(
            item["payload_path"], item["payload_bytes"], item["payload_sha256"],
            missing_reason="RELAY_PAYLOAD_MISSING",
            non_file_reason="RELAY_PAYLOAD_NOT_REGULAR_FILE",
            size_reason="RELAY_PAYLOAD_SIZE_MISMATCH",
            hash_reason="RELAY_PAYLOAD_HASH_MISMATCH",
        )
        _require_owned_path(
            payload_path, owner_lanes[item["origin"]],
            "RELAY_PAYLOAD_OUTSIDE_OWNER_LANE",
        )
        _require(payload_path not in seen_paths, "RELAY_PAYLOAD_PATH_DUPLICATE")
        seen_paths.add(payload_path)
    return {item["relay_id"]: item for item in records}


def _validate_team_card(
    record: dict[str, Any],
    relays: dict[str, dict[str, Any]],
) -> bool:
    card = record["team_card"]
    pair = record["session_pair"]
    builder = pair["builder"]
    verifier = pair["verifier"]
    _require(card["session_pair_sha256"] == pair["pair_sha256"], "SESSION_PAIR_DRIFT")
    _require(
        card["card_sha256"] == _projected_digest(card, "card_sha256", "acks"),
        "TEAM_CARD_DIGEST_MISMATCH",
    )
    _require(card["turn_order"] == ["BUILDER", "VERIFIER"], "TEAM_CARD_INCOMPLETE")
    _require(tuple(card["prohibitions"]) == GUIDED_PROHIBITIONS, "TEAM_CARD_INCOMPLETE")
    _require(tuple(card["pm_reserved_gates"]) == GUIDED_PM_GATES, "TEAM_CARD_INCOMPLETE")
    _require(card["sovereign_identity"] == builder["identity"], "TEAM_CARD_INCOMPLETE")
    _require(
        card["card_relay_id"] in relays
        and relays[card["card_relay_id"]]["kind"] == "TEAM_CARD"
        and relays[card["card_relay_id"]]["payload_sha256"] == card["card_sha256"],
        "TEAM_CARD_DIGEST_MISMATCH",
    )
    authorization = card["partner_selection_authorization_relay_id"]
    _require(
        authorization in relays
        and relays[authorization]["kind"] == "PARTNER_SELECTION_AUTHORIZATION"
        and relays[authorization]["origin"] == "PM"
        and relays[authorization]["payload_sha256"]
        == card["partner_selection_authorization_sha256"],
        "PARTNER_SELECTION_AUTHORITY_MISSING",
    )
    if record["topology"] == "TEAM_DUAL_LANE":
        _require(card["partner_identity"] == verifier["identity"], "PARTNER_IDENTITY_REQUIRED")
    else:
        _require(card["partner_identity"] is None, "TEAM_CARD_INCOMPLETE")

    expected = {
        "builder": ("BUILDER", builder["session_id"]),
        "verifier": ("VERIFIER", verifier["session_id"]),
    }
    for lane, (role, session_id) in expected.items():
        ack = card["acks"][lane]
        _require(
            ack["role"] == role and ack["session_id"] == session_id,
            "TEAM_CARD_DIGEST_MISMATCH",
        )
        if ack["relay_id"] is not None:
            _require(ack["relay_id"] in relays, "RELAY_PAYLOAD_MISMATCH")
            if ack["status"] == "ACK":
                _require(
                    relays[ack["relay_id"]]["kind"] == "READBACK"
                    and relays[ack["relay_id"]]["origin"] == role
                    and relays[ack["relay_id"]]["payload_sha256"] == card["card_sha256"],
                    "RELAY_PAYLOAD_MISMATCH",
                )
    dual_ack = (
        card["status"] == "TEAM_CARD_DUAL_ACK"
        and all(
            ack["status"] == "ACK"
            and ack["observed_card_sha256"] == card["card_sha256"]
            and ack["relay_id"] in relays
            for ack in card["acks"].values()
        )
    )
    if card["status"] == "TEAM_CARD_DUAL_ACK":
        _require(dual_ack, "TEAM_CARD_DUAL_ACK_MISSING")
    return dual_ack


def _validate_questions(
    record: dict[str, Any],
    relays: dict[str, dict[str, Any]],
    dual_ack: bool,
    access: dict[str, Any],
) -> list[str]:
    pair = record["session_pair"]
    matrix = record["question_matrix"]
    questions = matrix["questions"]
    _require(
        record["station_matrix_sha256"]
        == sha256_bytes(canonical_json(record["station_matrix"]).encode("utf-8")),
        "STATION_MATRIX_DIGEST_MISMATCH",
    )
    _require(
        matrix["matrix_sha256"] == _projected_digest(matrix, "matrix_sha256"),
        "QUESTION_DIGEST_MISMATCH",
    )
    ids = [question["question_id"] for question in questions]
    _require(len(ids) == len(set(ids)), "QUESTION_ID_DUPLICATE")
    _require(
        [question["ordinal"] for question in questions]
        == list(range(1, len(questions) + 1)),
        "QUESTION_ORDINAL_INVALID",
    )
    station_ids = [station["station_id"] for station in record["station_matrix"]]
    _require(
        tuple(station_ids) == GUIDED_STATIONS,
        "TEAM_CARD_INCOMPLETE",
    )
    stations = {station["station_id"]: station for station in record["station_matrix"]}
    question_by_id = {question["question_id"]: question for question in questions}
    evidence_paths: set[Path] = set()
    for station in record["station_matrix"]:
        _require(
            station["critical"] == (station["station_id"] in GUIDED_CRITICAL_STATIONS),
            "STATION_MATRIX_DIGEST_MISMATCH",
        )
        _require(
            all(
                question_id in question_by_id
                and question_by_id[question_id]["station_id"] == station["station_id"]
                for question_id in station["question_ids"]
            ),
            "QUESTION_DIGEST_MISMATCH",
        )
        for source_ref in station["source_refs"]:
            _, evidence_path = _read_bound_bytes(
                source_ref["path"], source_ref["bytes"], source_ref["sha256"],
                missing_reason="CRITICAL_EVIDENCE_MISSING",
                non_file_reason="CRITICAL_EVIDENCE_NOT_REGULAR_FILE",
                size_reason="CRITICAL_EVIDENCE_SIZE_MISMATCH",
                hash_reason="CRITICAL_EVIDENCE_HASH_MISMATCH",
            )
            if access["ready"]:
                _require(
                    any(
                        _within(evidence_path, root)
                        for root in (access["project_root"], *access["source_roots"])
                    )
                    and not any(
                        _within(evidence_path, excluded)
                        for excluded in access["excluded_paths"]
                    ),
                    "WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST",
                )
            _require(
                evidence_path not in evidence_paths,
                "CRITICAL_EVIDENCE_PATH_DUPLICATE",
            )
            evidence_paths.add(evidence_path)
        if (
            station["critical"]
            and station["classification"] == "KNOWN"
            and not station["question_ids"]
        ):
            _require(bool(station["source_refs"]), "CRITICAL_STATION_EVIDENCE_MISSING")
        elif station["critical"]:
            _require(
                station["classification"] == "KNOWN" or bool(station["question_ids"]),
                "CRITICAL_STATION_WITHOUT_QUESTION",
            )
    for question in questions:
        _require(question["relay_id"] in relays, "RELAY_PAYLOAD_MISMATCH")
        _require(
            question["question_id"] in stations[question["station_id"]]["question_ids"],
            "QUESTION_DIGEST_MISMATCH",
        )
        _require(
            question["critical"] == stations[question["station_id"]]["critical"],
            "QUESTION_DIGEST_MISMATCH",
        )
        _require(
            question["question_sha256"] == _question_digest(question),
            "QUESTION_DIGEST_MISMATCH",
        )
        _require(
            relays[question["relay_id"]]["payload_sha256"] == question["question_sha256"],
            "RELAY_PAYLOAD_MISMATCH",
        )
        expected = {
            "builder": ("BUILDER", pair["builder"]["session_id"]),
            "verifier": ("VERIFIER", pair["verifier"]["session_id"]),
        }
        readback_relay_ids: list[str] = []
        for lane, (role, session_id) in expected.items():
            readback = question["readbacks"][lane]
            _require(
                readback["role"] == role and readback["session_id"] == session_id,
                "QUESTION_NOT_MIRRORED",
            )
            question_relay_id = readback["question_relay_id"]
            _require(question_relay_id in relays, "FOUR_READBACK_CONTENT_MISMATCH")
            readback_relay_ids.append(question_relay_id)
            if readback["question_status"] == "ACK":
                _require(
                    readback["observed_question_sha256"] == question["question_sha256"]
                    and relays[question_relay_id]["kind"] == "READBACK"
                    and relays[question_relay_id]["origin"] == role
                    and relays[question_relay_id]["payload_sha256"]
                    == question["question_sha256"],
                    "FOUR_READBACK_CONTENT_MISMATCH",
                )
        answer = question["answer"]
        if answer is not None:
            _require(answer["relay_id"] in relays, "RELAY_PAYLOAD_MISMATCH")
            _require(
                answer["answer_sha256"] == _answer_digest(answer),
                "ANSWER_DIGEST_MISMATCH",
            )
            _require(
                relays[answer["relay_id"]]["payload_sha256"] == answer["answer_sha256"],
                "RELAY_PAYLOAD_MISMATCH",
            )
            for readback in question["readbacks"].values():
                if readback["answer_status"] == "ACK":
                    answer_relay_id = readback["answer_relay_id"]
                    _require(
                        answer_relay_id in relays
                        and readback["observed_answer_sha256"] == answer["answer_sha256"]
                        and relays[answer_relay_id]["kind"] == "READBACK"
                        and relays[answer_relay_id]["origin"] == readback["role"]
                        and relays[answer_relay_id]["payload_sha256"]
                        == answer["answer_sha256"],
                        "FOUR_READBACK_CONTENT_MISMATCH",
                    )
                    readback_relay_ids.append(answer_relay_id)
        else:
            _require(
                all(
                    readback["answer_status"] == "NOT_YET_AVAILABLE"
                    and readback["observed_answer_sha256"] is None
                    and readback["answer_relay_id"] is None
                    for readback in question["readbacks"].values()
                ),
                "ANSWER_NOT_MIRRORED",
            )
        _require(
            len(readback_relay_ids) == len(set(readback_relay_ids)),
            "FOUR_READBACK_CONTENT_MISMATCH",
        )

    if not dual_ack:
        _require(
            all(question["station_id"] == "Q0_TOPOLOGY" for question in questions),
            "TEAM_CARD_REQUIRED_BEFORE_INTAKE",
        )
        _require(
            all(
                station["station_id"] == "Q0_TOPOLOGY"
                or (
                    station["classification"] != "KNOWN"
                    and not station["source_refs"]
                    and not station["question_ids"]
                )
                for station in record["station_matrix"]
            ),
            "TEAM_CARD_REQUIRED_BEFORE_INTAKE",
        )

    open_questions: set[str] = set()
    for station in record["station_matrix"]:
        if station["critical"] and station["classification"] != "KNOWN":
            open_questions.update(station["question_ids"])
    for question in questions:
        if not question["critical"]:
            continue
        answer = question["answer"]
        mirrored = all(
            readback["question_status"] == "ACK"
            and readback["observed_question_sha256"] == question["question_sha256"]
            and answer is not None
            and readback["answer_status"] == "ACK"
            and readback["observed_answer_sha256"] == answer["answer_sha256"]
            for readback in question["readbacks"].values()
        )
        if answer is None or answer["classification_after"] != "KNOWN" or not mirrored:
            open_questions.add(question["question_id"])
    return sorted(open_questions)


def _validate_proposal(
    record: dict[str, Any],
    relays: dict[str, dict[str, Any]],
) -> bool:
    proposal_state = record["intake_proposal"]
    pair = record["session_pair"]
    _require(
        proposal_state["session_pair_sha256"] == pair["pair_sha256"],
        "SESSION_PAIR_CHANGED_BEFORE_CUTOVER",
    )
    expected = {
        "builder": ("BUILDER", pair["builder"]["session_id"]),
        "verifier": ("VERIFIER", pair["verifier"]["session_id"]),
    }
    proposal = proposal_state["proposal"]
    for lane, (role, session_id) in expected.items():
        ack = proposal_state["acks"][lane]
        _require(
            ack["role"] == role and ack["session_id"] == session_id,
            "INTAKE_PROPOSAL_DUAL_READBACK_MISSING",
        )
        if ack["relay_id"] is not None:
            _require(ack["relay_id"] in relays, "RELAY_PAYLOAD_MISMATCH")
    if proposal_state["status"] == "NOT_EMITTED":
        _require(proposal is None, "INTAKE_PROPOSAL_DUAL_READBACK_MISSING")
        _require(
            all(
                ack["status"] == "NOT_YET_AVAILABLE"
                and ack["observed_proposal_sha256"] is None
                for ack in proposal_state["acks"].values()
            ),
            "INTAKE_PROPOSAL_DUAL_READBACK_MISSING",
        )
        return False
    _require(proposal is not None, "INTAKE_PROPOSAL_DUAL_READBACK_MISSING")
    _read_bound_bytes(
        proposal["path"], proposal["bytes"], proposal["sha256"],
        missing_reason="INTAKE_PROPOSAL_MISSING",
        non_file_reason="INTAKE_PROPOSAL_NOT_REGULAR_FILE",
        size_reason="INTAKE_PROPOSAL_SIZE_MISMATCH",
        hash_reason="INTAKE_PROPOSAL_HASH_MISMATCH",
    )
    for ack in proposal_state["acks"].values():
        if ack["status"] == "ACK":
            _require(
                relays[ack["relay_id"]]["payload_sha256"] == proposal["sha256"],
                "RELAY_PAYLOAD_MISMATCH",
            )
    dual = (
        proposal_state["status"] == "DUAL_READBACK_ACKED"
        and all(
            ack["status"] == "ACK"
            and ack["observed_proposal_sha256"] == proposal["sha256"]
            and ack["relay_id"] in relays
            for ack in proposal_state["acks"].values()
        )
    )
    if proposal_state["status"] == "DUAL_READBACK_ACKED":
        _require(dual, "INTAKE_PROPOSAL_DUAL_READBACK_MISSING")
    return dual


def validate_guided_intake_state(record: dict[str, Any]) -> None:
    """Recompute every L2 closure claim; narrative completeness is never trusted."""
    _validate_guided_activation(record)
    access = _validate_workspace_access(record)
    _validate_guided_session_pair(record, access)
    relays = _relay_index(record, access)
    dual_ack = _validate_team_card(record, relays)
    open_questions = _validate_questions(record, relays, dual_ack, access)
    proposal_dual_ack = _validate_proposal(record, relays)

    downstream_expected = {
        "well": {"state": "WELL_WRITE_SCOPE_PENDING", "artifact_sha256": None},
        "knowledge": {"state": "NOT_STARTED", "fusion_sha256": None},
        "program": {"state": "NOT_STARTED", "program_sha256": None},
        "cutover": {"state": "NOT_STARTED", "receipt_sha256": None},
    }
    _require(
        all(record[key] == value for key, value in downstream_expected.items()),
        "PREMATURE_L3_L5_STATE",
    )

    closure = record["critical_closure"]
    _require(
        closure["station_matrix_sha256"] == record["station_matrix_sha256"],
        "CRITICAL_CLOSURE_MISMATCH",
    )
    _require(
        closure["question_matrix_sha256"] == record["question_matrix"]["matrix_sha256"],
        "CRITICAL_CLOSURE_MISMATCH",
    )
    expected_status = "CLOSED" if not open_questions else "OPEN"
    _require(
        closure["status"] == expected_status
        and closure["open_question_ids"] == open_questions,
        "CRITICAL_CLOSURE_MISMATCH",
    )

    phases_requiring_card = {
        "TEAM_CARD_DUAL_ACK", "QUESTIONS_ACTIVE", "PROPOSAL_READBACK_PENDING",
        "INTAKE_READY",
    }
    if record["phase"] in phases_requiring_card:
        _require(dual_ack, "TEAM_CARD_DUAL_ACK_MISSING")
    if record["phase"] == "INTAKE_READY":
        _require(access["ready"], "AUTONOMY_UNAVAILABLE_NO_ACCESS")
        _require(record["profile"] == "GODMODE", "PROFILE_DEGRADED_NOT_GODMODE")
        _require(record["status"] == "READY", "CRITICAL_CLOSURE_MISMATCH")
        _require(proposal_dual_ack, "INTAKE_PROPOSAL_DUAL_READBACK_MISSING")
        _require(not open_questions, "CRITICAL_QUESTION_OPEN")
        _require(not record["blocking_reason_codes"], "CRITICAL_CLOSURE_MISMATCH")
    elif record["status"] == "READY":
        raise ProtocolError("CRITICAL_CLOSURE_MISMATCH")
    if record["phase"] == "INTAKE_BLOCKED":
        _require(record["status"] == "BLOCKED", "CRITICAL_CLOSURE_MISMATCH")
    if not access["ready"]:
        _require(
            record["phase"] == "INTAKE_BLOCKED"
            and record["status"] == "BLOCKED"
            and "AUTONOMY_UNAVAILABLE_NO_ACCESS" in record["blocking_reason_codes"],
            "AUTONOMY_UNAVAILABLE_NO_ACCESS",
        )
    if record["profile"] == "PROFILE_DEGRADED":
        _require(
            record["phase"] == "INTAKE_BLOCKED"
            and record["status"] == "BLOCKED"
            and "PROFILE_DEGRADED_NOT_GODMODE" in record["blocking_reason_codes"],
            "PROFILE_DEGRADED_NOT_GODMODE",
        )


def claim_evidence(path: Path, work_id: str, evidence_sha256: str) -> dict[str, Any]:
    if len(evidence_sha256) != 64 or any(char not in "0123456789ABCDEF" for char in evidence_sha256):
        raise ProtocolError("INVALID_EVIDENCE_SHA256")
    claim = {"schema": "omni-evidence-claim-v1", "work_id": work_id, "evidence_sha256": evidence_sha256}
    payload = json.dumps(claim, sort_keys=True, indent=2) + "\n"
    try:
        create_once_text(path, payload)
    except RuntimeError as error:
        raise ProtocolError("BLOCKED_EVIDENCE_REPLAY") from error
    observed = strict_json(path.read_text(encoding="utf-8"))
    if observed != claim:
        raise ProtocolError("CLAIM_READBACK_MISMATCH")
    return observed


def reconcile_claim(claim_path: Path, record_path: Path, record: dict[str, Any]) -> dict[str, Any]:
    claim = strict_json(claim_path.read_text(encoding="utf-8"))
    if claim.get("work_id") != record.get("work_id") or claim.get("evidence_sha256") != record.get("evidence_sha256"):
        raise ProtocolError("BLOCKED_EVIDENCE_REPLAY")
    create_once_text(record_path, json.dumps(record, sort_keys=True, indent=2) + "\n")
    return strict_json(record_path.read_text(encoding="utf-8"))


def seal(record: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(record)
    sealed.pop("record_digest", None)
    sealed["record_digest"] = sha256_bytes(canonical_json(sealed).encode("utf-8"))
    return sealed


def verify(record: dict[str, Any]) -> bool:
    expected = record.get("record_digest")
    return isinstance(expected, str) and seal(record)["record_digest"] == expected


def validate_instance(record: dict[str, Any]) -> None:
    schema_name = record.get("schema")
    filename = SCHEMA_FILES.get(schema_name)
    if filename is None:
        raise ProtocolError(f"UNSUPPORTED_RECORD_SCHEMA:{schema_name}")
    try:
        import jsonschema
        schema = strict_json((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        failures = sorted(validator.iter_errors(record), key=lambda error: list(error.absolute_path))
    except ImportError as error:
        raise ProtocolError("JSONSCHEMA_RUNTIME_UNAVAILABLE") from error
    except (OSError, ValueError) as error:
        raise ProtocolError(f"RECORD_SCHEMA_UNREADABLE:{type(error).__name__}:{error}") from error
    if failures:
        failure = failures[0]
        location = "/".join(str(part) for part in failure.absolute_path) or "$"
        raise ProtocolError(f"RECORD_SCHEMA_INVALID:{location}:{failure.validator}")
    if schema_name == "omni-guided-intake-state-v1":
        validate_guided_intake_state(record)


def emit(draft: dict[str, Any], output: Path, previous: Path | None = None) -> dict[str, Any]:
    record = dict(draft)
    if "status" in record:
        validate_outcome(record["status"])
    record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    record["previous_record_sha256"] = sha256_path(previous) if previous else None
    record = seal(record)
    validate_instance(record)
    create_once_text(output, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    observed = strict_json(output.read_text(encoding="utf-8"))
    if not verify(observed):
        raise RuntimeError("RECORD_DIGEST_READBACK_FAIL")
    return observed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    try:
        emitted = emit(strict_json(args.draft.read_text(encoding="utf-8")), args.output, args.previous)
        print(canonical_json({"status": "PASS", "record": emitted}))
        return 0
    except (OSError, ValueError, ProtocolError, RuntimeError) as error:
        print(canonical_json({"status": "BLOCKED", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

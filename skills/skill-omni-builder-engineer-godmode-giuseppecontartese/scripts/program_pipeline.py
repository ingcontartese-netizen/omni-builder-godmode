"""Fail-closed L4 dual-lane planning and PROGRAM_BAPTISM corridor.

The runtime does not plan or execute a project.  It freezes two independently
authored plans, serialises a builder-only fusion, records one independent
verifier decision, and binds the PM's explicit baptism to the accepted bytes.
Every mutating command consumes a create-once authority and participates in a
create-once generation claim, so concurrent writers cannot fork the state chain.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

SENTRY = Path(__file__).parent / "sentry"
sys.path.insert(0, str(SENTRY))

from io_safe import (  # noqa: E402
    PathSafetyError,
    absolute_physical_path,
    canonical_json,
    create_once_text,
    read_bound_bytes,
    sha256_bytes,
    strict_json,
)


SCHEMA_DIR = Path(__file__).parents[1] / "schemas"
SHA256_RE = re.compile(r"^[A-F0-9]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,127}$")
ROLES = ("BUILDER", "VERIFIER")
FORBIDDEN_EFFECT_RE = re.compile(
    r"\b(?:F5|INSTALL(?:ATION)?|PUBLISH(?:ING)?|DEPLOY(?:MENT)?|EXTERNAL[_ -]?EFFECTS?|DELIVER(?:Y)?[_ -]?TO)\b",
    re.IGNORECASE,
)
NON_GRANTS = [
    "DELETE",
    "MOVE",
    "RENAME_OUTSIDE_ROOT",
    "OVERWRITE_PREEXISTING_USER_FILE",
    "PROJECT_EXECUTION",
    "AUTONOMY",
    "ARM_AUTOMATION",
    "INSTALL",
    "PUBLISH",
    "EXTERNAL_EFFECTS",
]
ACTION_BY_COMMAND = {
    "init": "INIT_PLANNING",
    "commit-plan-lanes": "COMMIT_PLAN_LANES",
    "freeze-plan-lane": "FREEZE_PLAN_LANE",
    "emit-program-fusion": "FUSE_PROGRAM",
    "countersign-program": "COUNTERSIGN_PROGRAM",
    "baptize-program": "BAPTIZE_PROGRAM",
}
PHASES = (
    "PLANNING_INITIALIZED",
    "PLAN_LANES_COMMITTED",
    "PLAN_LANES_FREEZING",
    "PLAN_LANES_FROZEN",
    "PROGRAM_FUSION_FROZEN",
    "PROGRAM_COUNTERSIGN_ACCEPTED",
    "PROGRAM_COUNTERSIGN_BLOCKED",
    "PROGRAM_COUNTERSIGN_INCONCLUSIVE",
    "PROGRAM_BAPTIZED",
)
SCHEMA_FILES = {
    "omni-planning-effect-authority-v1": "planning_effect_authority.schema.json",
    "omni-planning-state-v1": "planning_state.schema.json",
    "omni-plan-lane-manifest-v1": "plan_lane_manifest.schema.json",
    "omni-fused-program-v2": "fused_program.schema.json",
    "omni-program-countersign-receipt-v2": "program_countersign_receipt.schema.json",
    "omni-program-baptism-decision-v1": "program_baptism_decision.schema.json",
    "omni-program-baptism-receipt-v1": "program_baptism_receipt.schema.json",
    "omni-knowledge-pipeline-state-v1": "knowledge_pipeline_state.schema.json",
    "omni-knowledge-fusion-v1": "knowledge_fusion.schema.json",
    "omni-guided-intake-state-v1": "guided_intake_state.schema.json",
}


class ProgramPipelineError(RuntimeError):
    """One stable L4 failure code plus optional diagnostic detail."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.detail = detail


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProgramPipelineError("CLI_ARGUMENT_INVALID", message)


def _require(condition: bool, reason_code: str, detail: str | None = None) -> None:
    if not condition:
        raise ProgramPipelineError(reason_code, detail)


def _sha(value: object, label: str) -> str:
    normalized = str(value).upper()
    _require(bool(SHA256_RE.fullmatch(normalized)), "INVALID_SHA256", label)
    return normalized


def _identifier(value: object, label: str) -> str:
    normalized = str(value).strip().upper()
    _require(bool(IDENTIFIER_RE.fullmatch(normalized)), "INVALID_IDENTIFIER", label)
    return normalized


def _projection_digest(value: dict[str, Any]) -> str:
    return sha256_bytes(
        canonical_json(
            {key: item for key, item in value.items() if key != "record_digest"}
        ).encode("utf-8")
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


def _inside(path: Path, root: Path, label: str, *, strict: bool) -> Path:
    root = absolute_physical_path(root, f"{label}_ROOT", strict=True)
    target = absolute_physical_path(path, label, strict=strict)
    _require(
        target == root or target.is_relative_to(root),
        "PATH_OUTSIDE_PLANNING_ROOT",
        label,
    )
    return target


def _load_schema(schema_name: str) -> dict[str, Any]:
    filename = SCHEMA_FILES.get(schema_name)
    _require(filename is not None, "L4_SCHEMA_UNRECOGNIZED", schema_name)
    path = SCHEMA_DIR / filename
    _require(path.is_file(), "L4_SCHEMA_MISSING", filename)
    try:
        schema = strict_json(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except Exception as error:  # jsonschema exposes several version-specific subclasses.
        raise ProgramPipelineError(
            "L4_SCHEMA_INVALID_DEFINITION", f"{filename}:{type(error).__name__}"
        ) from error
    _require(isinstance(schema, dict), "L4_SCHEMA_INVALID_DEFINITION", filename)
    return schema


def _validate_schema(value: dict[str, Any], expected_schema: str | None = None) -> None:
    schema_name = value.get("schema")
    _require(isinstance(schema_name, str), "L4_SCHEMA_TAG_MISSING")
    if expected_schema is not None:
        _require(schema_name == expected_schema, "L4_SCHEMA_TAG_MISMATCH")
    schema = _load_schema(schema_name)
    try:
        errors = sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    except Exception as error:
        raise ProgramPipelineError(
            "L4_SCHEMA_VALIDATION_ENGINE_FAILURE", type(error).__name__
        ) from error
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "$"
        raise ProgramPipelineError(
            "L4_SCHEMA_INSTANCE_INVALID", f"{schema_name}:{location}:{first.message}"
        )


def _load_bound_json(
    path: Path,
    expected_sha256: str,
    label: str,
    *,
    allowed_roots: Iterable[Path] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data, physical = read_bound_bytes(
        path,
        expected_sha256=_sha(expected_sha256, label),
        allowed_roots=allowed_roots,
        label=label,
    )
    try:
        value = strict_json(data.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("BOUND_JSON_INVALID", label) from error
    _require(isinstance(value, dict), "BOUND_JSON_OBJECT_REQUIRED", label)
    return value, _binding(physical, data)


def _read_binding(
    binding: dict[str, Any], label: str, *, allowed_roots: Iterable[Path] | None = None
) -> tuple[bytes, Path]:
    _require(
        isinstance(binding, dict)
        and set(binding) == {"path", "bytes", "sha256"}
        and type(binding.get("bytes")) is int
        and binding["bytes"] > 0,
        "FILE_BINDING_SHAPE_INVALID",
        label,
    )
    return read_bound_bytes(
        Path(binding["path"]),
        expected_bytes=binding["bytes"],
        expected_sha256=_sha(binding["sha256"], label),
        allowed_roots=allowed_roots,
        label=label,
    )


def _write_record(
    value: dict[str, Any], path: Path, root: Path, *, schema_validate: bool = True
) -> tuple[dict[str, Any], dict[str, Any], str]:
    result = seal(value)
    if schema_validate:
        _validate_schema(result)
    output = _inside(path, root, "OUTPUT", strict=False)
    text = canonical_json(result) + "\n"
    try:
        write_status = create_once_text(output, text, allowed_root=root)
    except RuntimeError as error:
        raise ProgramPipelineError("CREATE_ONCE_COLLISION", str(output)) from error
    return result, _binding(output, text.encode("utf-8")), write_status


def _prepare_record(
    value: dict[str, Any], path: Path, root: Path, *, schema_validate: bool = True
) -> dict[str, Any]:
    """Seal and validate bytes without publishing any filesystem effect."""
    result = seal(value)
    if schema_validate:
        _validate_schema(result)
    output = _inside(path, root, "OUTPUT", strict=False)
    text = canonical_json(result) + "\n"
    data = text.encode("utf-8")
    return {
        "record": result,
        "binding": {"path": str(output), "bytes": len(data), "sha256": sha256_bytes(data)},
        "path": output,
        "root": absolute_physical_path(root, "OUTPUT_ROOT", strict=True),
        "text": text,
    }


def _preflight_prepared(prepared: dict[str, Any]) -> None:
    """Reject target/staging collisions before consuming authority state."""
    path = prepared["path"]
    expected = prepared["text"].encode("utf-8")
    for candidate in (path, path.parent / f".{path.name}.pending"):
        if candidate.exists() or candidate.is_symlink():
            try:
                observed, _ = read_bound_bytes(
                    candidate,
                    allowed_roots=[prepared["root"]],
                    label="PREPARED_OUTPUT_PREFLIGHT",
                )
            except (OSError, PathSafetyError) as error:
                raise ProgramPipelineError("CREATE_ONCE_PREFLIGHT_INVALID", str(candidate)) from error
            _require(
                observed == expected,
                prepared.get("collision_reason", "CREATE_ONCE_COLLISION"),
                str(candidate),
            )


def _publish_prepared(prepared: dict[str, Any]) -> str:
    try:
        status = create_once_text(
            prepared["path"], prepared["text"], allowed_root=prepared["root"]
        )
        staging = prepared["path"].parent / f".{prepared['path'].name}.pending"
        if staging.exists() or staging.is_symlink():
            staged, _ = read_bound_bytes(
                staging,
                expected_bytes=prepared["binding"]["bytes"],
                expected_sha256=prepared["binding"]["sha256"],
                allowed_roots=[prepared["root"]],
                label="PREPARED_OUTPUT_STAGING_CLEANUP",
            )
            _require(
                staged == prepared["text"].encode("utf-8"),
                "ORPHAN_SIDE_EFFECT_DETECTED",
            )
            try:
                staging.unlink()
            except OSError as error:
                raise ProgramPipelineError(
                    "CREATE_ONCE_STAGING_CLEANUP_FAILED", str(staging)
                ) from error
        return status
    except RuntimeError as error:
        raise ProgramPipelineError(
            prepared.get("collision_reason", "CREATE_ONCE_COLLISION"),
            str(prepared["path"]),
        ) from error


def _finalize_transition(
    prepared_outputs: list[dict[str, Any]],
    reservation: dict[str, Any],
    *,
    result_index: int = -1,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Validate/preflight every byte, then consume authority and publish outputs."""
    for prepared in [*prepared_outputs, reservation["nonce"], reservation["claim"]]:
        _preflight_prepared(prepared)
    _publish_prepared(reservation["nonce"])
    _publish_prepared(reservation["claim"])
    statuses = [_publish_prepared(prepared) for prepared in prepared_outputs]
    selected = prepared_outputs[result_index]
    return selected["record"], selected["binding"], statuses[result_index]


def _canonical_binding_set(values: list[dict[str, Any]]) -> list[str]:
    return sorted(canonical_json(item) for item in values)


def _validate_l3(
    knowledge_state_path: Path, knowledge_state_sha256: str
) -> dict[str, Any]:
    state, state_binding = _load_bound_json(
        knowledge_state_path, knowledge_state_sha256, "KNOWLEDGE_STATE"
    )
    _validate_schema(state, "omni-knowledge-pipeline-state-v1")
    _require(verify_record(state), "KNOWLEDGE_STATE_RECORD_DIGEST_INVALID")
    _require(
        state.get("phase") == "KNOWLEDGE_FUSION_PASS"
        and state.get("status") == "PASS"
        and state.get("fusion", {}).get("state") == "KNOWLEDGE_FUSION_PASS",
        "L3_KNOWLEDGE_FUSION_PASS_REQUIRED",
    )
    pair = state.get("session_pair")
    _require(isinstance(pair, dict), "KNOWLEDGE_SESSION_PAIR_INVALID")
    builder = pair.get("builder")
    verifier = pair.get("verifier")
    _require(
        isinstance(builder, dict)
        and isinstance(verifier, dict)
        and builder.get("session_id")
        and verifier.get("session_id")
        and builder["session_id"] != verifier["session_id"]
        and state.get("session_pair_sha256") == pair.get("pair_sha256"),
        "KNOWLEDGE_SESSION_PAIR_INVALID",
    )
    well_root = absolute_physical_path(state["well_root"], "WELL_ROOT", strict=True)
    countersign_binding = state["fusion"]["countersign_binding"]
    canonical_binding = state["fusion"]["canonical_binding"]
    countersign_raw, countersign_path = _read_binding(
        countersign_binding, "KNOWLEDGE_FUSION_COUNTERSIGN", allowed_roots=[well_root]
    )
    canonical_raw, canonical_path = _read_binding(
        canonical_binding, "CANONICAL_KNOWLEDGE", allowed_roots=[well_root]
    )
    try:
        countersign = strict_json(countersign_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("KNOWLEDGE_FUSION_COUNTERSIGN_INVALID") from error
    _require(isinstance(countersign, dict), "KNOWLEDGE_FUSION_COUNTERSIGN_INVALID")
    _validate_schema(countersign, "omni-knowledge-fusion-v1")
    _require(verify_record(countersign), "KNOWLEDGE_FUSION_RECORD_DIGEST_INVALID")
    _require(
        countersign.get("kind") == "FUSION_COUNTERSIGN"
        and countersign.get("status") == "KNOWLEDGE_FUSION_PASS"
        and countersign.get("pipeline_id") == state.get("pipeline_id")
        and countersign.get("task_id") == state.get("task_id")
        and countersign.get("session_pair_sha256") == state.get("session_pair_sha256")
        and countersign.get("canonical_knowledge_binding") == canonical_binding,
        "KNOWLEDGE_FUSION_BINDING_MISMATCH",
    )
    candidate_binding = countersign.get("candidate_binding")
    _require(
        candidate_binding == state.get("fusion", {}).get("candidate_binding"),
        "KNOWLEDGE_FUSION_BINDING_MISMATCH",
    )
    candidate_raw, _ = _read_binding(
        candidate_binding, "KNOWLEDGE_FUSION_CANDIDATE", allowed_roots=[well_root]
    )
    try:
        candidate = strict_json(candidate_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("KNOWLEDGE_FUSION_CANDIDATE_INVALID") from error
    _validate_schema(candidate, "omni-knowledge-fusion-v1")
    _require(
        verify_record(candidate)
        and candidate.get("kind") == "FUSION_CANDIDATE"
        and candidate.get("status") == "FUSION_EMITTED"
        and candidate.get("author_role") == "BUILDER"
        and candidate.get("author_session_id") == builder["session_id"]
        and countersign.get("countersigner_role") == "VERIFIER"
        and countersign.get("countersigner_session_id") == verifier["session_id"]
        and candidate.get("author_session_id")
        != countersign.get("countersigner_session_id")
        and candidate.get("canonical_knowledge_binding") == canonical_binding,
        "KNOWLEDGE_FUSION_CANDIDATE_INVALID",
    )
    expected_countersign = copy.deepcopy(candidate)
    expected_countersign.pop("record_digest", None)
    expected_countersign.update(
        {
            "kind": "FUSION_COUNTERSIGN",
            "status": "KNOWLEDGE_FUSION_PASS",
            "countersigner_role": "VERIFIER",
            "countersigner_session_id": verifier["session_id"],
            "candidate_binding": candidate_binding,
            "created_at": countersign.get("created_at"),
        }
    )
    _require(
        countersign == seal(expected_countersign),
        "KNOWLEDGE_FUSION_COUNTERSIGN_RECOMPUTE_MISMATCH",
    )
    intake_binding = state.get("intake_binding")
    intake_raw, _ = _read_binding(intake_binding, "GUIDED_INTAKE")
    try:
        intake = strict_json(intake_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("GUIDED_INTAKE_INVALID") from error
    _require(isinstance(intake, dict), "GUIDED_INTAKE_INVALID")
    _validate_schema(intake, "omni-guided-intake-state-v1")
    _require(verify_record(intake), "GUIDED_INTAKE_RECORD_DIGEST_INVALID")
    _require(
        intake.get("phase") == "INTAKE_READY"
        and intake.get("status") == "READY"
        and intake.get("profile") == "GODMODE"
        and intake.get("session_pair", {}).get("pair_sha256")
        == state.get("session_pair_sha256"),
        "GUIDED_INTAKE_SCOPE_MISMATCH",
    )
    return {
        "state": state,
        "state_binding": state_binding,
        "well_root": well_root,
        "countersign_binding": _binding(countersign_path, countersign_raw),
        "canonical_binding": _binding(canonical_path, canonical_raw),
        "topology": intake["topology"],
        "profile": intake["profile"],
        "run_kind": intake["run_kind"],
        "sovereign_id": intake["team_card"]["sovereign_identity"],
    }


EVENT_TO_ACTION = {
    "INIT": "INIT_PLANNING",
    "COMMIT_PLAN_LANES": "COMMIT_PLAN_LANES",
    "FREEZE_PLAN_LANE": "FREEZE_PLAN_LANE",
    "EMIT_PROGRAM_FUSION": "FUSE_PROGRAM",
    "COUNTERSIGN_PROGRAM": "COUNTERSIGN_PROGRAM",
    "BAPTIZE_PROGRAM": "BAPTIZE_PROGRAM",
}


def _strict_control_record(raw: bytes, label: str, keys: set[str]) -> dict[str, Any]:
    try:
        value = strict_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PLANNING_CONTROL_RECORD_INVALID", label) from error
    _require(
        isinstance(value, dict) and set(value) == keys and verify_record(value),
        "PLANNING_CONTROL_RECORD_INVALID",
        label,
    )
    return value


def _validate_state_chain(
    state: dict[str, Any], binding: dict[str, Any], seen: set[str]
) -> None:
    _validate_schema(state, "omni-planning-state-v1")
    _require(verify_record(state), "PLANNING_STATE_RECORD_DIGEST_INVALID")
    _require(state.get("phase") in PHASES, "PLANNING_STATE_PHASE_INVALID")
    _require(binding["sha256"] not in seen, "PLANNING_STATE_CHAIN_CYCLE")
    seen.add(binding["sha256"])
    root = Path(state["planning_root"])

    l3 = _validate_l3(
        Path(state["knowledge_state_binding"]["path"]),
        state["knowledge_state_binding"]["sha256"],
    )
    _require(
        l3["state_binding"] == state["knowledge_state_binding"]
        and l3["countersign_binding"] == state["knowledge_fusion_countersign_binding"]
        and l3["canonical_binding"] == state["canonical_knowledge_binding"]
        and l3["state"]["pipeline_id"] == state["knowledge_pipeline_id"]
        and l3["state"]["task_id"] == state["task_id"]
        and l3["state"]["session_pair_sha256"] == state["session_pair_sha256"]
        and l3["sovereign_id"] == state["sovereign_id"],
        "PLANNING_L3_EVIDENCE_DRIFT",
    )

    authority_raw, _ = _read_binding(
        state["effect_authority_binding"], "PLANNING_STATE_AUTHORITY", allowed_roots=[root]
    )
    authority = _strict_control_record(
        authority_raw,
        "PLANNING_STATE_AUTHORITY",
        {
            "schema", "status", "decision", "authority_id", "action", "task_id",
            "program_id", "knowledge_pipeline_id", "knowledge_state_binding",
            "knowledge_fusion_countersign_binding", "session_pair_sha256",
            "subject_role", "subject_session_id", "planning_root",
            "expected_previous_state_binding", "input_bindings", "output_paths",
            "one_shot", "operation_nonce", "non_grants", "created_at", "record_digest",
        },
    )
    _validate_schema(authority, "omni-planning-effect-authority-v1")
    expected_action = EVENT_TO_ACTION[state["event"]]
    _require(
        authority["action"] == expected_action
        and authority["program_id"] == state["program_id"]
        and authority["task_id"] == state["task_id"]
        and authority["knowledge_pipeline_id"] == state["knowledge_pipeline_id"]
        and authority["knowledge_state_binding"] == state["knowledge_state_binding"]
        and authority["knowledge_fusion_countersign_binding"]
        == state["knowledge_fusion_countersign_binding"]
        and authority["session_pair_sha256"] == state["session_pair_sha256"]
        and authority["subject_role"] == state["actor"]["role"]
        and authority["subject_session_id"] == state["actor"]["session_id"]
        and authority["expected_previous_state_binding"] == state["previous_state_binding"]
        and authority["non_grants"] == NON_GRANTS,
        "PLANNING_STATE_AUTHORITY_MISMATCH",
    )

    nonce_raw, _ = _read_binding(
        state["operation_nonce_binding"], "OPERATION_NONCE", allowed_roots=[root]
    )
    nonce = _strict_control_record(
        nonce_raw,
        "OPERATION_NONCE",
        {
            "schema", "status", "program_id", "operation_nonce", "action",
            "authority_binding", "previous_state_binding", "created_at", "record_digest",
        },
    )
    _require(
        nonce["schema"] == "omni-planning-nonce-consumption-v1"
        and nonce["status"] == "NONCE_CONSUMED"
        and nonce["program_id"] == state["program_id"]
        and nonce["operation_nonce"] == authority["operation_nonce"]
        and nonce["action"] == expected_action
        and nonce["authority_binding"] == state["effect_authority_binding"]
        and nonce["previous_state_binding"] == state["previous_state_binding"],
        "PLANNING_NONCE_CHAIN_MISMATCH",
    )

    claim_raw, _ = _read_binding(
        state["generation_claim_binding"], "GENERATION_CLAIM", allowed_roots=[root]
    )
    claim = _strict_control_record(
        claim_raw,
        "GENERATION_CLAIM",
        {
            "schema", "status", "program_id", "generation", "previous_state_binding",
            "state_output_path", "authority_binding", "operation_nonce_binding",
            "created_at", "record_digest",
        },
    )
    _require(
        claim["schema"] == "omni-planning-generation-claim-v1"
        and claim["status"] == "GENERATION_CLAIMED"
        and claim["program_id"] == state["program_id"]
        and claim["generation"] == state["generation"]
        and claim["previous_state_binding"] == state["previous_state_binding"]
        and claim["state_output_path"] == binding["path"]
        and claim["authority_binding"] == state["effect_authority_binding"]
        and claim["operation_nonce_binding"] == state["operation_nonce_binding"],
        "PLANNING_GENERATION_CHAIN_MISMATCH",
    )
    output_paths = {
        str(absolute_physical_path(item, "AUTHORITY_OUTPUT", strict=False))
        for item in authority["output_paths"]
    }
    _require(
        binding["path"] in output_paths
        and state["operation_nonce_binding"]["path"] in output_paths
        and state["generation_claim_binding"]["path"] in output_paths,
        "PLANNING_STATE_OUTPUT_AUTHORITY_MISMATCH",
    )

    previous = state.get("previous_state_binding")
    if state["generation"] == 1:
        _require(previous is None, "PLANNING_STATE_CHAIN_INVALID")
        return
    _require(isinstance(previous, dict), "PLANNING_STATE_CHAIN_INVALID")
    previous_raw, previous_path = _read_binding(
        previous, "PREVIOUS_PLANNING_STATE", allowed_roots=[root]
    )
    try:
        previous_state = strict_json(previous_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PLANNING_STATE_CHAIN_INVALID") from error
    _require(isinstance(previous_state, dict), "PLANNING_STATE_CHAIN_INVALID")
    immutable = (
        "program_id", "task_id", "knowledge_pipeline_id", "planning_root",
        "knowledge_state_binding", "knowledge_fusion_countersign_binding",
        "canonical_knowledge_binding", "session_pair_sha256", "session_pair",
        "topology", "profile", "run_kind", "sovereign_id",
    )
    _require(
        state["generation"] == previous_state.get("generation", 0) + 1
        and all(state[key] == previous_state.get(key) for key in immutable),
        "PLANNING_STATE_CHAIN_INVALID",
    )
    _validate_state_chain(previous_state, _binding(previous_path, previous_raw), seen)


def _load_state(path: Path, expected_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state, binding = _load_bound_json(path, expected_sha256, "PLANNING_STATE")
    _validate_state_chain(state, binding, set())
    return state, binding


def _authority_context(
    authority_path: Path,
    authority_sha256: str,
    *,
    command: str,
    program_id: str,
    task_id: str,
    knowledge_pipeline_id: str,
    knowledge_state_binding: dict[str, Any],
    knowledge_fusion_binding: dict[str, Any],
    session_pair_sha256: str,
    subject_role: str,
    subject_session_id: str,
    planning_root: Path,
    previous_binding: dict[str, Any] | None,
    required_inputs: list[dict[str, Any]],
    required_outputs: list[Path],
    next_generation: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority, authority_binding = _load_bound_json(
        authority_path, authority_sha256, "PLANNING_AUTHORITY"
    )
    _validate_schema(authority, "omni-planning-effect-authority-v1")
    _require(verify_record(authority), "PLANNING_AUTHORITY_RECORD_DIGEST_INVALID")
    expected_action = ACTION_BY_COMMAND[command]
    _require(authority.get("action") == expected_action, "PLANNING_AUTHORITY_ACTION_MISMATCH")
    _require(
        authority.get("program_id") == program_id
        and authority.get("task_id") == task_id
        and authority.get("knowledge_pipeline_id") == knowledge_pipeline_id
        and authority.get("knowledge_state_binding") == knowledge_state_binding
        and authority.get("knowledge_fusion_countersign_binding")
        == knowledge_fusion_binding
        and authority.get("session_pair_sha256") == session_pair_sha256,
        "PLANNING_AUTHORITY_SCOPE_REPLAY",
    )
    _require(
        authority.get("subject_role") == subject_role
        and authority.get("subject_session_id") == subject_session_id,
        "PLANNING_AUTHORITY_SUBJECT_MISMATCH",
    )
    root = absolute_physical_path(planning_root, "PLANNING_ROOT", strict=True)
    _require(
        absolute_physical_path(authority["planning_root"], "AUTHORITY_PLANNING_ROOT", strict=True)
        == root,
        "PLANNING_AUTHORITY_ROOT_MISMATCH",
    )
    _require(
        authority.get("expected_previous_state_binding") == previous_binding,
        "PLANNING_CAS_PRECONDITION_MISMATCH",
    )
    _require(
        _canonical_binding_set(authority.get("input_bindings", []))
        == _canonical_binding_set(required_inputs),
        "PLANNING_AUTHORITY_INPUT_MISMATCH",
    )
    nonce = _identifier(authority["operation_nonce"], "OPERATION_NONCE")
    nonce_path = root / "control" / "nonces" / f"{nonce}.json"
    claim_path = root / "control" / "generation_claims" / f"GEN_{next_generation:04d}.json"
    all_outputs = [*required_outputs, nonce_path, claim_path]
    observed_outputs = sorted(
        str(absolute_physical_path(item, "AUTHORITY_OUTPUT", strict=False))
        for item in authority.get("output_paths", [])
    )
    expected_outputs = sorted(
        str(_inside(item, root, "EXPECTED_OUTPUT", strict=False)) for item in all_outputs
    )
    _require(observed_outputs == expected_outputs, "PLANNING_AUTHORITY_OUTPUT_MISMATCH")
    _require(authority.get("non_grants") == NON_GRANTS, "PLANNING_AUTHORITY_NON_GRANTS_DRIFT")
    nonce_prepared = _prepare_record(
        {
            "schema": "omni-planning-nonce-consumption-v1",
            "status": "NONCE_CONSUMED",
            "program_id": program_id,
            "operation_nonce": nonce,
            "action": expected_action,
            "authority_binding": authority_binding,
            "previous_state_binding": previous_binding,
            "created_at": authority["created_at"],
        },
        nonce_path,
        root,
        schema_validate=False,
    )
    nonce_binding = nonce_prepared["binding"]
    nonce_prepared["collision_reason"] = "PLANNING_EFFECT_AUTHORITY_NONCE_REPLAY"
    claim_prepared = _prepare_record(
        {
            "schema": "omni-planning-generation-claim-v1",
            "status": "GENERATION_CLAIMED",
            "program_id": program_id,
            "generation": next_generation,
            "previous_state_binding": previous_binding,
            "state_output_path": str(_inside(required_outputs[0], root, "STATE_OUTPUT", strict=False)),
            "authority_binding": authority_binding,
            "operation_nonce_binding": nonce_binding,
            "created_at": authority["created_at"],
        },
        claim_path,
        root,
        schema_validate=False,
    )
    claim_binding = claim_prepared["binding"]
    claim_prepared["collision_reason"] = "PLANNING_GENERATION_FORK_DETECTED"
    reservation = {"nonce": nonce_prepared, "claim": claim_prepared}
    return authority, authority_binding, nonce_binding, claim_binding, reservation


WORK_ITEM_KEYS = {
    "work_id", "ordinal", "title", "result", "persistent_artifact", "owner_role",
    "depends_on", "preconditions", "required_capabilities", "budget",
    "acceptance_evidence", "verifier_role", "rollback", "failure_states",
    "next_gate", "scope", "origin_refs",
}


def _validate_work_items(
    work_items: object,
    *,
    lane_role: str | None = None,
    lane_roots: dict[str, Path] | None = None,
) -> list[dict[str, Any]]:
    _require(isinstance(work_items, list) and 1 <= len(work_items) <= 64, "PROGRAM_WORK_ITEMS_INVALID")
    known: list[str] = []
    evidence_ids: set[str] = set()
    for ordinal, item in enumerate(work_items, start=1):
        _require(isinstance(item, dict) and set(item) == WORK_ITEM_KEYS, "PROGRAM_WORK_ITEM_SHAPE_INVALID")
        work_id = _identifier(item["work_id"], "WORK_ID")
        _require(work_id not in known, "PROGRAM_WORK_ID_DUPLICATE")
        _require(type(item["ordinal"]) is int and item["ordinal"] == ordinal, "PROGRAM_WORK_ORDINAL_INVALID")
        _require(item["owner_role"] in ROLES, "PROGRAM_SHARED_WRITER_FORBIDDEN")
        _require(item["verifier_role"] in ROLES and item["verifier_role"] != item["owner_role"], "PROGRAM_AUTHOR_AND_SIGN_FORBIDDEN")
        artifact = item["persistent_artifact"]
        _require(isinstance(artifact, dict) and artifact.get("owner_role") == item["owner_role"], "PROGRAM_ARTIFACT_OWNER_MISMATCH")
        artifact_path = absolute_physical_path(
            artifact.get("path", ""), "PROGRAM_ARTIFACT_PATH", strict=False
        )
        if lane_roots is not None:
            owner_root = lane_roots[item["owner_role"]]
            _inside(artifact_path, owner_root, "PROGRAM_ARTIFACT_PATH", strict=False)
        effect_projection = canonical_json(
            {
                "title": item.get("title"),
                "result": item.get("result"),
                "path": str(artifact_path),
                "next_gate": item.get("next_gate"),
                "required_capabilities": item.get("required_capabilities"),
            }
        )
        _require(
            FORBIDDEN_EFFECT_RE.search(effect_projection) is None,
            "PROGRAM_FORBIDDEN_EFFECT",
            work_id,
        )
        dependencies = item["depends_on"]
        _require(
            isinstance(dependencies, list)
            and len(dependencies) == len(set(dependencies))
            and len(dependencies) <= 16
            and all(dependency in known for dependency in dependencies),
            "PROGRAM_DAG_FORWARD_OR_UNKNOWN_DEPENDENCY",
        )
        _require(
            isinstance(item["preconditions"], list)
            and item["preconditions"]
            and "KNOWLEDGE_FUSION_PASS" in item["preconditions"],
            "PROGRAM_KNOWLEDGE_PRECONDITION_MISSING",
        )
        _require(
            isinstance(item["required_capabilities"], list)
            and item["required_capabilities"],
            "PROGRAM_CAPABILITY_CONTRACT_MISSING",
        )
        budget = item["budget"]
        _require(
            isinstance(budget, dict)
            and type(budget.get("max_turns")) is int
            and budget["max_turns"] > 0
            and type(budget.get("max_tool_calls")) is int
            and budget["max_tool_calls"] >= 0
            and type(budget.get("max_elapsed_seconds")) is int
            and budget["max_elapsed_seconds"] > 0,
            "PROGRAM_BUDGET_INVALID",
        )
        evidence = item["acceptance_evidence"]
        _require(isinstance(evidence, list) and evidence, "PROGRAM_ACCEPTANCE_EVIDENCE_MISSING")
        for entry in evidence:
            _require(isinstance(entry, dict), "PROGRAM_ACCEPTANCE_EVIDENCE_INVALID")
            evidence_id = _identifier(entry.get("evidence_id", ""), "EVIDENCE_ID")
            _require(evidence_id not in evidence_ids, "PROGRAM_EVIDENCE_ID_DUPLICATE")
            evidence_ids.add(evidence_id)
        _require(isinstance(item["rollback"], dict) and item["rollback"].get("steps"), "PROGRAM_ROLLBACK_MISSING")
        _require(isinstance(item["failure_states"], list) and item["failure_states"], "PROGRAM_FAILURE_STATES_MISSING")
        _identifier(item["next_gate"], "NEXT_GATE")
        _require(
            isinstance(item["scope"], list)
            and item["scope"]
            and set(item["scope"]).issubset({"F3_BUILD", "F4_TEST"}),
            "PROGRAM_SCOPE_INVALID",
        )
        origins = item["origin_refs"]
        _require(isinstance(origins, list) and origins, "PROGRAM_ORIGIN_MISSING")
        origin_pairs = []
        for origin in origins:
            _require(isinstance(origin, dict) and set(origin) == {"role", "work_id"}, "PROGRAM_ORIGIN_INVALID")
            _require(origin["role"] in ROLES, "PROGRAM_ORIGIN_INVALID")
            origin_pairs.append((origin["role"], _identifier(origin["work_id"], "ORIGIN_WORK_ID")))
        _require(len(origin_pairs) == len(set(origin_pairs)), "PROGRAM_ORIGIN_DUPLICATE")
        if lane_role is not None:
            _require(origin_pairs == [(lane_role, work_id)], "PLAN_LANE_ORIGIN_INVALID")
        known.append(work_id)
    return work_items


PLAN_DRAFT_KEYS = {
    "schema", "status", "program_id", "task_id", "knowledge_pipeline_id",
    "knowledge_state_binding", "knowledge_fusion_countersign_binding",
    "canonical_knowledge_binding", "session_pair_sha256", "role", "session_id",
    "lane_root", "peer_lane_read_before_dual_freeze", "work_items", "alternatives",
    "risks", "dissent", "created_at", "record_digest",
}


def _validate_plan_draft(draft: dict[str, Any], state: dict[str, Any], role: str) -> None:
    _require(set(draft) == PLAN_DRAFT_KEYS, "PLAN_DRAFT_SHAPE_INVALID")
    _require(verify_record(draft), "PLAN_DRAFT_RECORD_DIGEST_INVALID")
    lane = state["lanes"][role]
    _require(
        draft.get("schema") == "omni-plan-lane-draft-v1"
        and draft.get("status") == "PLAN_DRAFT_READY"
        and draft.get("program_id") == state["program_id"]
        and draft.get("task_id") == state["task_id"]
        and draft.get("knowledge_pipeline_id") == state["knowledge_pipeline_id"]
        and draft.get("knowledge_state_binding") == state["knowledge_state_binding"]
        and draft.get("knowledge_fusion_countersign_binding")
        == state["knowledge_fusion_countersign_binding"]
        and draft.get("canonical_knowledge_binding") == state["canonical_knowledge_binding"]
        and draft.get("session_pair_sha256") == state["session_pair_sha256"]
        and draft.get("role") == role
        and draft.get("session_id") == lane["session_id"]
        and draft.get("lane_root") == lane["lane_root"],
        "PLAN_DRAFT_SCOPE_REPLAY",
    )
    _require(draft.get("peer_lane_read_before_dual_freeze") is False, "PLAN_ORACLE_CONTAMINATION")
    _validate_work_items(
        draft["work_items"],
        lane_role=role,
        lane_roots={item: Path(state["lanes"][item]["lane_root"]) for item in ROLES},
    )
    collection_contracts = {
        "alternatives": ({"alternative_id", "statement", "rationale"}, "alternative_id"),
        "risks": ({"risk_id", "statement", "mitigation", "severity"}, "risk_id"),
        "dissent": ({"dissent_id", "statement", "rationale", "status"}, "dissent_id"),
    }
    for key, (required_keys, identifier_key) in collection_contracts.items():
        values = draft[key]
        _require(isinstance(values, list), "PLAN_DRAFT_COLLECTION_INVALID", key)
        _require(
            all(
                isinstance(item, dict)
                and set(item) == required_keys
                and all(
                    isinstance(value, str) and bool(value.strip())
                    for field, value in item.items()
                    if field != "severity" and field != "status"
                )
                for item in values
            ),
            "PLAN_DRAFT_COLLECTION_INVALID",
            key,
        )
        identifiers = [_identifier(item[identifier_key], identifier_key) for item in values]
        _require(len(identifiers) == len(values) == len(set(identifiers)), "PLAN_DRAFT_IDENTIFIER_COLLISION", key)
    _require(
        all(item["severity"] in {"P0", "P1", "P2"} for item in draft["risks"])
        and all(
            item["status"] in {"PRESERVED_NONBLOCKING", "ESCALATED_BLOCKING"}
            for item in draft["dissent"]
        ),
        "PLAN_DRAFT_COLLECTION_INVALID",
    )


def _plan_core_digest(draft: dict[str, Any]) -> str:
    """Compare substantive proposals while ignoring lane IDs, paths and actors."""
    projection = {
        "work": [
            {"title": item["title"], "result": item["result"]}
            for item in draft["work_items"]
        ],
        "alternatives": [
            {"statement": item["statement"], "rationale": item["rationale"]}
            for item in draft["alternatives"]
        ],
    }
    return sha256_bytes(canonical_json(projection).encode("utf-8"))


def _load_manifest(state: dict[str, Any], role: str) -> dict[str, Any]:
    lane = state["lanes"][role]
    raw, _ = _read_binding(lane["manifest_binding"], f"{role}_PLAN_MANIFEST", allowed_roots=[Path(lane["lane_root"])])
    try:
        manifest = strict_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PLAN_MANIFEST_INVALID", role) from error
    _require(isinstance(manifest, dict), "PLAN_MANIFEST_INVALID", role)
    _validate_schema(manifest, "omni-plan-lane-manifest-v1")
    _require(verify_record(manifest), "PLAN_MANIFEST_RECORD_DIGEST_INVALID", role)
    _require(
        manifest.get("program_id") == state["program_id"]
        and manifest.get("task_id") == state["task_id"]
        and manifest.get("knowledge_pipeline_id") == state["knowledge_pipeline_id"]
        and manifest.get("knowledge_state_binding") == state["knowledge_state_binding"]
        and manifest.get("knowledge_fusion_countersign_binding")
        == state["knowledge_fusion_countersign_binding"]
        and manifest.get("canonical_knowledge_binding") == state["canonical_knowledge_binding"]
        and manifest.get("session_pair_sha256") == state["session_pair_sha256"]
        and manifest.get("role") == role
        and manifest.get("session_id") == lane["session_id"]
        and manifest.get("lane_root") == lane["lane_root"]
        and manifest.get("peer_lane_read_before_dual_freeze") is False,
        "PLAN_MANIFEST_SCOPE_REPLAY",
        role,
    )
    _validate_work_items(
        manifest["work_items"],
        lane_role=role,
        lane_roots={item: Path(state["lanes"][item]["lane_root"]) for item in ROLES},
    )
    return manifest


def _build_state(
    state: dict[str, Any],
    previous_binding: dict[str, Any] | None,
    *,
    output: Path,
    phase: str,
    status: str,
    event: str,
    actor_role: str,
    actor_session_id: str,
    authority_binding: dict[str, Any],
    nonce_binding: dict[str, Any],
    claim_binding: dict[str, Any],
    evidence: list[dict[str, Any]],
    blocking_codes: list[str],
    created_at: str,
) -> dict[str, Any]:
    result = copy.deepcopy(state)
    result["generation"] = 1 if previous_binding is None else state["generation"] + 1
    result["state_id"] = f"{result['program_id']}-STATE-{result['generation']:04d}"
    result["phase"] = phase
    result["status"] = status
    result["event"] = event
    result["actor"] = {"role": actor_role, "session_id": actor_session_id}
    result["effect_authority_binding"] = authority_binding
    result["operation_nonce_binding"] = nonce_binding
    result["generation_claim_binding"] = claim_binding
    result["evidence_bindings"] = evidence
    result["blocking_reason_codes"] = sorted(set(blocking_codes))
    result["previous_state_binding"] = previous_binding
    result["created_at"] = created_at
    return result


def command_init(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    l3 = _validate_l3(args.knowledge_state, args.knowledge_state_sha256)
    knowledge = l3["state"]
    program_id = _identifier(args.program_id, "PROGRAM_ID")
    planning_root = absolute_physical_path(args.planning_root, "PLANNING_ROOT", strict=True)
    _inside(planning_root, l3["well_root"], "PLANNING_ROOT", strict=True)
    output = _inside(args.output, planning_root, "STATE_OUTPUT", strict=False)
    subject_session = knowledge["session_pair"]["builder"]["session_id"]
    authority, authority_binding, nonce_binding, claim_binding, reservation = _authority_context(
        args.authority,
        args.authority_sha256,
        command="init",
        program_id=program_id,
        task_id=knowledge["task_id"],
        knowledge_pipeline_id=knowledge["pipeline_id"],
        knowledge_state_binding=l3["state_binding"],
        knowledge_fusion_binding=l3["countersign_binding"],
        session_pair_sha256=knowledge["session_pair_sha256"],
        subject_role="BUILDER",
        subject_session_id=subject_session,
        planning_root=planning_root,
        previous_binding=None,
        required_inputs=[l3["state_binding"]],
        required_outputs=[output],
        next_generation=1,
    )
    state = {
        "schema": "omni-planning-state-v1",
        "state_id": f"{program_id}-STATE-0001",
        "program_id": program_id,
        "generation": 1,
        "phase": "PLANNING_INITIALIZED",
        "status": "ACTIVE",
        "task_id": knowledge["task_id"],
        "knowledge_pipeline_id": knowledge["pipeline_id"],
        "planning_root": str(planning_root),
        "knowledge_state_binding": l3["state_binding"],
        "knowledge_fusion_countersign_binding": l3["countersign_binding"],
        "canonical_knowledge_binding": l3["canonical_binding"],
        "session_pair_sha256": knowledge["session_pair_sha256"],
        "session_pair": {
            "pair_sha256": knowledge["session_pair_sha256"],
            "builder": {"role": "BUILDER", "session_id": subject_session},
            "verifier": {
                "role": "VERIFIER",
                "session_id": knowledge["session_pair"]["verifier"]["session_id"],
            },
        },
        "topology": l3["topology"],
        "profile": l3["profile"],
        "run_kind": l3["run_kind"],
        "sovereign_id": l3["sovereign_id"],
        "lanes": {
            role: {
                "role": role,
                "session_id": knowledge["session_pair"][role.lower()]["session_id"],
                "lane_root": str(planning_root / "lanes" / role.lower()),
                "state": "DRAFTING",
                "draft_binding": None,
                "manifest_binding": None,
                "manifest_commitment": None,
            }
            for role in ROLES
        },
        "fusion": {"state": "NOT_STARTED", "candidate_binding": None, "countersign_binding": None},
        "baptism": {"state": "NOT_STARTED", "receipt_binding": None},
        "event": "INIT",
        "actor": {"role": "BUILDER", "session_id": subject_session},
        "effect_authority_binding": authority_binding,
        "operation_nonce_binding": nonce_binding,
        "generation_claim_binding": claim_binding,
        "evidence_bindings": [l3["state_binding"], l3["countersign_binding"], l3["canonical_binding"]],
        "blocking_reason_codes": [],
        "previous_state_binding": None,
        "created_at": authority["created_at"],
    }
    return _finalize_transition([_prepare_record(state, output, planning_root)], reservation)


def command_commit_plan_lanes(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, state_binding = _load_state(args.state, args.state_sha256)
    _require(state["phase"] == "PLANNING_INITIALIZED", "ILLEGAL_PLANNING_TRANSITION")
    drafts: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for role, path, digest in (
        ("BUILDER", args.builder_plan_draft, args.builder_plan_draft_sha256),
        ("VERIFIER", args.verifier_plan_draft, args.verifier_plan_draft_sha256),
    ):
        lane = state["lanes"][role]
        draft, draft_binding = _load_bound_json(
            path,
            digest,
            f"{role}_PLAN_DRAFT_COMMITMENT",
            allowed_roots=[Path(lane["lane_root"])],
        )
        _validate_plan_draft(draft, state, role)
        drafts[role] = draft
        bindings[role] = draft_binding
    _require(
        _plan_core_digest(drafts["BUILDER"]) != _plan_core_digest(drafts["VERIFIER"]),
        "PLAN_ORACLE_CONTAMINATION",
        "substantive plan copy",
    )
    output = _inside(args.output, Path(state["planning_root"]), "STATE_OUTPUT", strict=False)
    builder_session = state["session_pair"]["builder"]["session_id"]
    authority, authority_binding, nonce_binding, claim_binding, reservation = _authority_context(
        args.authority,
        args.authority_sha256,
        command="commit-plan-lanes",
        program_id=state["program_id"],
        task_id=state["task_id"],
        knowledge_pipeline_id=state["knowledge_pipeline_id"],
        knowledge_state_binding=state["knowledge_state_binding"],
        knowledge_fusion_binding=state["knowledge_fusion_countersign_binding"],
        session_pair_sha256=state["session_pair_sha256"],
        subject_role="BUILDER",
        subject_session_id=builder_session,
        planning_root=Path(state["planning_root"]),
        previous_binding=state_binding,
        required_inputs=[state_binding, bindings["BUILDER"], bindings["VERIFIER"]],
        required_outputs=[output],
        next_generation=state["generation"] + 1,
    )
    for role in ROLES:
        state["lanes"][role]["state"] = "PLAN_LANE_COMMITTED"
        state["lanes"][role]["draft_binding"] = bindings[role]
    next_state = _build_state(
        state,
        state_binding,
        output=output,
        phase="PLAN_LANES_COMMITTED",
        status="ACTIVE",
        event="COMMIT_PLAN_LANES",
        actor_role="BUILDER",
        actor_session_id=builder_session,
        authority_binding=authority_binding,
        nonce_binding=nonce_binding,
        claim_binding=claim_binding,
        evidence=[bindings["BUILDER"], bindings["VERIFIER"]],
        blocking_codes=[],
        created_at=authority["created_at"],
    )
    return _finalize_transition(
        [_prepare_record(next_state, output, Path(state["planning_root"]))], reservation
    )


def command_freeze_plan_lane(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, state_binding = _load_state(args.state, args.state_sha256)
    _require(
        state["phase"] in {"PLAN_LANES_COMMITTED", "PLAN_LANES_FREEZING"},
        "ILLEGAL_PLANNING_TRANSITION",
    )
    role = args.role
    lane = state["lanes"][role]
    _require(lane["state"] == "PLAN_LANE_COMMITTED", "PLAN_LANE_ALREADY_FROZEN", role)
    draft, draft_binding = _load_bound_json(
        args.plan_draft,
        args.plan_draft_sha256,
        f"{role}_PLAN_DRAFT",
        allowed_roots=[Path(lane["lane_root"])],
    )
    _validate_plan_draft(draft, state, role)
    _require(draft_binding == lane["draft_binding"], "PLAN_DRAFT_COMMITMENT_MISMATCH", role)
    output = _inside(args.output, Path(state["planning_root"]), "STATE_OUTPUT", strict=False)
    manifest_output = _inside(args.manifest_output, Path(lane["lane_root"]), "PLAN_MANIFEST_OUTPUT", strict=False)
    _require(
        manifest_output
        == _inside(Path(lane["lane_root"]) / "plan-manifest.json", Path(lane["lane_root"]), "PLAN_MANIFEST_CANONICAL", strict=False),
        "PLAN_MANIFEST_PATH_NONCANONICAL",
        role,
    )
    authority, authority_binding, nonce_binding, claim_binding, reservation = _authority_context(
        args.authority,
        args.authority_sha256,
        command="freeze-plan-lane",
        program_id=state["program_id"],
        task_id=state["task_id"],
        knowledge_pipeline_id=state["knowledge_pipeline_id"],
        knowledge_state_binding=state["knowledge_state_binding"],
        knowledge_fusion_binding=state["knowledge_fusion_countersign_binding"],
        session_pair_sha256=state["session_pair_sha256"],
        subject_role=role,
        subject_session_id=lane["session_id"],
        planning_root=Path(state["planning_root"]),
        previous_binding=state_binding,
        required_inputs=[state_binding, draft_binding],
        required_outputs=[output, manifest_output],
        next_generation=state["generation"] + 1,
    )
    manifest = {
        "schema": "omni-plan-lane-manifest-v1",
        "status": "PLAN_LANE_FROZEN",
        **{key: copy.deepcopy(draft[key]) for key in (
            "program_id", "task_id", "knowledge_pipeline_id", "knowledge_state_binding",
            "knowledge_fusion_countersign_binding", "canonical_knowledge_binding",
            "session_pair_sha256", "role", "session_id", "lane_root",
            "peer_lane_read_before_dual_freeze", "work_items", "alternatives", "risks",
            "dissent", "created_at",
        )},
        "plan_draft_binding": draft_binding,
    }
    prepared_manifest = _prepare_record(manifest, manifest_output, Path(lane["lane_root"]))
    manifest_binding = prepared_manifest["binding"]
    peer_role = "VERIFIER" if role == "BUILDER" else "BUILDER"
    peer_lane = state["lanes"][peer_role]
    evidence = [draft_binding]
    if peer_lane["state"] == "PLAN_LANE_COMMITTED":
        state["lanes"][role]["state"] = "PLAN_LANE_FROZEN_PRIVATE"
        state["lanes"][role]["manifest_commitment"] = {
            "bytes": manifest_binding["bytes"],
            "sha256": manifest_binding["sha256"],
        }
        phase = "PLAN_LANES_FREEZING"
    else:
        _require(
            peer_lane["state"] == "PLAN_LANE_FROZEN_PRIVATE"
            and isinstance(peer_lane.get("manifest_commitment"), dict),
            "PLAN_LANE_FREEZE_ORDER_INVALID",
        )
        peer_manifest_path = Path(peer_lane["lane_root"]) / "plan-manifest.json"
        peer_raw, peer_physical = read_bound_bytes(
            peer_manifest_path,
            expected_bytes=peer_lane["manifest_commitment"]["bytes"],
            expected_sha256=peer_lane["manifest_commitment"]["sha256"],
            allowed_roots=[Path(peer_lane["lane_root"])],
            label="PEER_PRIVATE_PLAN_MANIFEST",
        )
        peer_binding = _binding(peer_physical, peer_raw)
        state["lanes"][peer_role]["state"] = "PLAN_LANE_FROZEN"
        state["lanes"][peer_role]["manifest_binding"] = peer_binding
        state["lanes"][role]["state"] = "PLAN_LANE_FROZEN"
        state["lanes"][role]["manifest_binding"] = manifest_binding
        state["lanes"][role]["manifest_commitment"] = {
            "bytes": manifest_binding["bytes"],
            "sha256": manifest_binding["sha256"],
        }
        phase = "PLAN_LANES_FROZEN"
        evidence.extend([peer_binding, manifest_binding])
    next_state = _build_state(
        state,
        state_binding,
        output=output,
        phase=phase,
        status="ACTIVE",
        event="FREEZE_PLAN_LANE",
        actor_role=role,
        actor_session_id=lane["session_id"],
        authority_binding=authority_binding,
        nonce_binding=nonce_binding,
        claim_binding=claim_binding,
        evidence=evidence,
        blocking_codes=[],
        created_at=authority["created_at"],
    )
    prepared_state = _prepare_record(next_state, output, Path(state["planning_root"]))
    return _finalize_transition([prepared_manifest, prepared_state], reservation)


FUSED_DRAFT_KEYS = {
    "schema", "status", "program_id", "task_id", "knowledge_pipeline_id",
    "knowledge_state_binding", "knowledge_fusion_countersign_binding",
    "canonical_knowledge_binding", "session_pair_sha256", "topology", "profile",
    "run_kind", "work_items", "preserved_alternative_ids", "preserved_dissent_ids",
    "created_at", "record_digest",
}


def _validate_fusion_inputs(
    state: dict[str, Any],
    manifests: dict[str, dict[str, Any]],
    fused: dict[str, Any],
    decisions: dict[str, Any],
) -> None:
    _require(set(fused) == FUSED_DRAFT_KEYS and verify_record(fused), "FUSED_PLAN_DRAFT_INVALID")
    _require(
        fused.get("schema") == "omni-fused-program-draft-v2"
        and fused.get("status") == "FUSED_PLAN_DRAFT_READY"
        and fused.get("program_id") == state["program_id"]
        and fused.get("task_id") == state["task_id"]
        and fused.get("knowledge_pipeline_id") == state["knowledge_pipeline_id"]
        and fused.get("knowledge_state_binding") == state["knowledge_state_binding"]
        and fused.get("knowledge_fusion_countersign_binding")
        == state["knowledge_fusion_countersign_binding"]
        and fused.get("canonical_knowledge_binding") == state["canonical_knowledge_binding"]
        and fused.get("session_pair_sha256") == state["session_pair_sha256"]
        and fused.get("topology") == state["topology"]
        and fused.get("profile") == "GODMODE"
        and fused.get("run_kind") == state["run_kind"],
        "FUSED_PLAN_SCOPE_REPLAY",
    )
    _validate_work_items(
        fused["work_items"],
        lane_roots={item: Path(state["lanes"][item]["lane_root"]) for item in ROLES},
    )
    source_origins = {
        (role, item["work_id"])
        for role in ROLES
        for item in manifests[role]["work_items"]
    }
    fused_origins = [
        (origin["role"], origin["work_id"])
        for item in fused["work_items"]
        for origin in item["origin_refs"]
    ]
    _require(
        set(fused_origins) == source_origins and len(fused_origins) == len(set(fused_origins)),
        "PROGRAM_ORIGIN_COVERAGE_MISMATCH",
    )
    alternatives = {
        item["alternative_id"] for role in ROLES for item in manifests[role]["alternatives"]
    }
    dissent = {item["dissent_id"] for role in ROLES for item in manifests[role]["dissent"]}
    _require(set(fused["preserved_alternative_ids"]) == alternatives, "PROGRAM_ALTERNATIVE_ERASURE")
    _require(set(fused["preserved_dissent_ids"]) == dissent, "PROGRAM_DISSENT_ERASURE")
    _require(
        not any(item.get("status") == "ESCALATED_BLOCKING" for role in ROLES for item in manifests[role]["dissent"]),
        "BLOCKING_PLAN_DISSENT",
    )
    expected_decision_keys = {
        "schema", "status", "program_id", "task_id", "knowledge_pipeline_id",
        "session_pair_sha256", "decisions", "created_at", "record_digest",
    }
    _require(set(decisions) == expected_decision_keys and verify_record(decisions), "PROGRAM_FUSION_DECISIONS_INVALID")
    _require(
        decisions.get("schema") == "omni-program-fusion-decisions-v1"
        and decisions.get("status") == "FUSION_DECISIONS_FROZEN"
        and decisions.get("program_id") == state["program_id"]
        and decisions.get("task_id") == state["task_id"]
        and decisions.get("knowledge_pipeline_id") == state["knowledge_pipeline_id"]
        and decisions.get("session_pair_sha256") == state["session_pair_sha256"],
        "PROGRAM_FUSION_DECISIONS_SCOPE_REPLAY",
    )
    source_coverage: list[tuple[str, str]] = []
    fused_coverage: list[str] = []
    decision_ids: set[str] = set()
    fused_ids = {item["work_id"] for item in fused["work_items"]}
    for decision in decisions["decisions"]:
        _require(
            isinstance(decision, dict)
            and set(decision)
            == {"decision_id", "outcome", "source_refs", "fused_work_ids", "alternative_ids", "dissent_ids", "rationale"},
            "PROGRAM_FUSION_DECISION_INVALID",
        )
        decision_id = _identifier(decision["decision_id"], "DECISION_ID")
        _require(decision_id not in decision_ids, "PROGRAM_FUSION_DECISION_ID_DUPLICATE")
        decision_ids.add(decision_id)
        _require(
            decision["outcome"] in {"MERGE", "BUILDER_PREFERRED", "VERIFIER_PREFERRED", "PRESERVE_BOTH", "UNRESOLVED_DISSENT"}
            and isinstance(decision["rationale"], str)
            and bool(decision["rationale"].strip()),
            "PROGRAM_FUSION_DECISION_INVALID",
        )
        refs = [(ref.get("role"), ref.get("work_id")) for ref in decision["source_refs"] if isinstance(ref, dict)]
        _require(refs and set(refs).issubset(source_origins), "PROGRAM_FUSION_DECISION_SOURCE_INVALID")
        final_ids = decision["fused_work_ids"]
        _require(final_ids and set(final_ids).issubset(fused_ids), "PROGRAM_FUSION_DECISION_TARGET_INVALID")
        _require(set(decision["alternative_ids"]).issubset(alternatives), "PROGRAM_FUSION_DECISION_ALTERNATIVE_INVALID")
        _require(set(decision["dissent_ids"]).issubset(dissent), "PROGRAM_FUSION_DECISION_DISSENT_INVALID")
        source_coverage.extend(refs)
        fused_coverage.extend(final_ids)
    _require(
        set(source_coverage) == source_origins and len(source_coverage) == len(set(source_coverage)),
        "PROGRAM_FUSION_SOURCE_COVERAGE_MISMATCH",
    )
    _require(set(fused_coverage) == fused_ids, "PROGRAM_FUSION_TARGET_COVERAGE_MISMATCH")


def _load_and_validate_candidate(
    state: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    candidate_binding = state["fusion"]["candidate_binding"]
    raw, _ = _read_binding(candidate_binding, "FUSED_PROGRAM", allowed_roots=[Path(state["planning_root"])])
    try:
        candidate = strict_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("FUSED_PROGRAM_INVALID") from error
    _require(isinstance(candidate, dict), "FUSED_PROGRAM_INVALID")
    _validate_schema(candidate, "omni-fused-program-v2")
    _require(verify_record(candidate), "FUSED_PROGRAM_RECORD_DIGEST_INVALID")
    manifests = {role: _load_manifest(state, role) for role in ROLES}
    fused_binding = candidate["fused_plan_draft_binding"]
    fused_raw, _ = _read_binding(fused_binding, "FUSED_PLAN_DRAFT", allowed_roots=[Path(state["lanes"]["BUILDER"]["lane_root"])])
    decisions_binding = candidate["fusion_decision_register_binding"]
    decisions_raw, _ = _read_binding(decisions_binding, "PROGRAM_FUSION_DECISIONS", allowed_roots=[Path(state["lanes"]["BUILDER"]["lane_root"])])
    try:
        fused = strict_json(fused_raw.decode("utf-8"))
        decisions = strict_json(decisions_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PROGRAM_FUSION_INPUT_INVALID") from error
    _require(isinstance(fused, dict) and isinstance(decisions, dict), "PROGRAM_FUSION_INPUT_INVALID")
    _validate_fusion_inputs(state, manifests, fused, decisions)
    expected = {
        "schema": "omni-fused-program-v2",
        "kind": "PROGRAM_FUSION_CANDIDATE",
        "status": "PROGRAM_FUSION_FROZEN",
        "program_id": state["program_id"],
        "task_id": state["task_id"],
        "knowledge_pipeline_id": state["knowledge_pipeline_id"],
        "knowledge_state_binding": state["knowledge_state_binding"],
        "knowledge_fusion_countersign_binding": state["knowledge_fusion_countersign_binding"],
        "canonical_knowledge_binding": state["canonical_knowledge_binding"],
        "session_pair_sha256": state["session_pair_sha256"],
        "author_role": "BUILDER",
        "author_session_id": state["session_pair"]["builder"]["session_id"],
        "topology": state["topology"],
        "profile": state["profile"],
        "run_kind": state["run_kind"],
        "fused_from_lanes": ["BUILDER", "VERIFIER"],
        "builder_plan_manifest_binding": state["lanes"]["BUILDER"]["manifest_binding"],
        "verifier_plan_manifest_binding": state["lanes"]["VERIFIER"]["manifest_binding"],
        "fusion_decision_register_binding": decisions_binding,
        "fused_plan_draft_binding": fused_binding,
        "work_items": fused["work_items"],
        "preserved_alternative_ids": fused["preserved_alternative_ids"],
        "preserved_dissent_ids": fused["preserved_dissent_ids"],
        "created_at": candidate["created_at"],
    }
    _require(candidate == seal(expected), "FUSED_PROGRAM_RECOMPUTE_MISMATCH")
    return candidate, manifests, fused, decisions


def command_emit_program_fusion(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, state_binding = _load_state(args.state, args.state_sha256)
    _require(state["phase"] == "PLAN_LANES_FROZEN", "FUSION_BEFORE_DUAL_PLAN_FREEZE")
    manifests = {role: _load_manifest(state, role) for role in ROLES}
    builder_lane = Path(state["lanes"]["BUILDER"]["lane_root"])
    fused, fused_binding = _load_bound_json(args.fused_plan, args.fused_plan_sha256, "FUSED_PLAN_DRAFT", allowed_roots=[builder_lane])
    decisions, decisions_binding = _load_bound_json(args.decision_register, args.decision_register_sha256, "PROGRAM_FUSION_DECISIONS", allowed_roots=[builder_lane])
    _validate_fusion_inputs(state, manifests, fused, decisions)
    output = _inside(args.output, Path(state["planning_root"]), "STATE_OUTPUT", strict=False)
    candidate_output = _inside(args.candidate_output, Path(state["planning_root"]), "FUSED_PROGRAM_OUTPUT", strict=False)
    builder_session = state["session_pair"]["builder"]["session_id"]
    authority, authority_binding, nonce_binding, claim_binding, reservation = _authority_context(
        args.authority,
        args.authority_sha256,
        command="emit-program-fusion",
        program_id=state["program_id"], task_id=state["task_id"],
        knowledge_pipeline_id=state["knowledge_pipeline_id"],
        knowledge_state_binding=state["knowledge_state_binding"],
        knowledge_fusion_binding=state["knowledge_fusion_countersign_binding"],
        session_pair_sha256=state["session_pair_sha256"],
        subject_role="BUILDER", subject_session_id=builder_session,
        planning_root=Path(state["planning_root"]), previous_binding=state_binding,
        required_inputs=[state_binding, fused_binding, decisions_binding],
        required_outputs=[output, candidate_output], next_generation=state["generation"] + 1,
    )
    candidate = {
        "schema": "omni-fused-program-v2", "kind": "PROGRAM_FUSION_CANDIDATE",
        "status": "PROGRAM_FUSION_FROZEN", "program_id": state["program_id"],
        "task_id": state["task_id"], "knowledge_pipeline_id": state["knowledge_pipeline_id"],
        "knowledge_state_binding": state["knowledge_state_binding"],
        "knowledge_fusion_countersign_binding": state["knowledge_fusion_countersign_binding"],
        "canonical_knowledge_binding": state["canonical_knowledge_binding"],
        "session_pair_sha256": state["session_pair_sha256"], "author_role": "BUILDER",
        "author_session_id": builder_session, "topology": state["topology"],
        "profile": "GODMODE", "run_kind": state["run_kind"],
        "fused_from_lanes": ["BUILDER", "VERIFIER"],
        "builder_plan_manifest_binding": state["lanes"]["BUILDER"]["manifest_binding"],
        "verifier_plan_manifest_binding": state["lanes"]["VERIFIER"]["manifest_binding"],
        "fusion_decision_register_binding": decisions_binding,
        "fused_plan_draft_binding": fused_binding, "work_items": fused["work_items"],
        "preserved_alternative_ids": fused["preserved_alternative_ids"],
        "preserved_dissent_ids": fused["preserved_dissent_ids"],
        "created_at": authority["created_at"],
    }
    prepared_candidate = _prepare_record(candidate, candidate_output, Path(state["planning_root"]))
    candidate_binding = prepared_candidate["binding"]
    state["fusion"] = {"state": "PROGRAM_FUSION_FROZEN", "candidate_binding": candidate_binding, "countersign_binding": None}
    next_state = _build_state(
        state, state_binding, output=output, phase="PROGRAM_FUSION_FROZEN", status="ACTIVE",
        event="EMIT_PROGRAM_FUSION", actor_role="BUILDER", actor_session_id=builder_session,
        authority_binding=authority_binding, nonce_binding=nonce_binding, claim_binding=claim_binding,
        evidence=[state["lanes"]["BUILDER"]["manifest_binding"], state["lanes"]["VERIFIER"]["manifest_binding"], fused_binding, decisions_binding, candidate_binding],
        blocking_codes=[], created_at=authority["created_at"],
    )
    prepared_state = _prepare_record(next_state, output, Path(state["planning_root"]))
    return _finalize_transition([prepared_candidate, prepared_state], reservation)


REPORT_KEYS = {
    "schema", "status", "program_id", "task_id", "knowledge_pipeline_id",
    "session_pair_sha256", "candidate_binding", "decision", "reproduction",
    "findings", "created_at", "record_digest",
}
REPRODUCTION_KEYS = {
    "schema_valid", "dag_valid", "full_wbs_valid", "origin_coverage_complete",
    "alternatives_preserved", "dissent_preserved", "no_shared_writer",
    "no_oracle_before_dual_freeze", "exact_bindings",
}


def _validate_verifier_report(report: dict[str, Any], state: dict[str, Any]) -> tuple[str, list[str]]:
    _require(set(report) == REPORT_KEYS and verify_record(report), "PROGRAM_VERIFIER_REPORT_INVALID")
    decision = report.get("decision")
    _require(
        report.get("schema") == "omni-program-verifier-report-v1"
        and report.get("status") == "VERIFICATION_COMPLETE"
        and report.get("program_id") == state["program_id"]
        and report.get("task_id") == state["task_id"]
        and report.get("knowledge_pipeline_id") == state["knowledge_pipeline_id"]
        and report.get("session_pair_sha256") == state["session_pair_sha256"]
        and report.get("candidate_binding") == state["fusion"]["candidate_binding"]
        and decision in {"ACCEPTED", "BLOCK", "INCONCLUSIVE"},
        "PROGRAM_VERIFIER_REPORT_SCOPE_REPLAY",
    )
    reproduction = report.get("reproduction")
    _require(isinstance(reproduction, dict) and set(reproduction) == REPRODUCTION_KEYS, "PROGRAM_VERIFIER_REPRODUCTION_INVALID")
    findings = report.get("findings")
    _require(isinstance(findings, list), "PROGRAM_VERIFIER_FINDINGS_INVALID")
    codes = []
    for finding in findings:
        _require(isinstance(finding, dict) and set(finding) == {"code", "detail"}, "PROGRAM_VERIFIER_FINDING_INVALID")
        codes.append(_identifier(finding["code"], "FINDING_CODE"))
        _require(isinstance(finding["detail"], str) and bool(finding["detail"].strip()), "PROGRAM_VERIFIER_FINDING_INVALID")
    _require(len(codes) == len(set(codes)), "PROGRAM_VERIFIER_FINDING_DUPLICATE")
    if decision == "ACCEPTED":
        _require(all(value is True for value in reproduction.values()) and not codes, "FALSE_PROGRAM_COUNTERSIGN_ACCEPTED")
    else:
        _require(bool(codes), "PROGRAM_COUNTERSIGN_FINDING_REQUIRED")
    return decision, codes


def _load_and_validate_program_countersign(
    state: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    raw, _ = _read_binding(
        state["fusion"]["countersign_binding"],
        "PROGRAM_COUNTERSIGN",
        allowed_roots=[Path(state["planning_root"])],
    )
    try:
        receipt = strict_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PROGRAM_COUNTERSIGN_INVALID") from error
    _require(isinstance(receipt, dict), "PROGRAM_COUNTERSIGN_INVALID")
    _validate_schema(receipt, "omni-program-countersign-receipt-v2")
    _require(verify_record(receipt), "PROGRAM_COUNTERSIGN_RECORD_DIGEST_INVALID")
    report_raw, _ = _read_binding(
        receipt["verifier_report_binding"],
        "PROGRAM_VERIFIER_REPORT",
        allowed_roots=[Path(state["lanes"]["VERIFIER"]["lane_root"])],
    )
    try:
        report = strict_json(report_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PROGRAM_VERIFIER_REPORT_INVALID") from error
    _require(isinstance(report, dict), "PROGRAM_VERIFIER_REPORT_INVALID")
    decision, codes = _validate_verifier_report(report, state)
    status_by_decision = {
        "ACCEPTED": "PROGRAM_COUNTERSIGN_ACCEPTED",
        "BLOCK": "PROGRAM_COUNTERSIGN_BLOCKED",
        "INCONCLUSIVE": "PROGRAM_COUNTERSIGN_INCONCLUSIVE",
    }
    expected = {
        "schema": "omni-program-countersign-receipt-v2",
        "status": status_by_decision[decision],
        "decision": decision,
        "receipt_id": f"{state['program_id']}-COUNTERSIGN",
        "program_id": state["program_id"],
        "task_id": state["task_id"],
        "knowledge_pipeline_id": state["knowledge_pipeline_id"],
        "program_binding": state["fusion"]["candidate_binding"],
        "program_record_digest": candidate["record_digest"],
        "knowledge_state_binding": state["knowledge_state_binding"],
        "knowledge_fusion_countersign_binding": state["knowledge_fusion_countersign_binding"],
        "session_pair_sha256": state["session_pair_sha256"],
        "program_author_session_id": candidate["author_session_id"],
        "signer_role": "VERIFIER",
        "signer_session_id": state["session_pair"]["verifier"]["session_id"],
        "verifier_report_binding": receipt["verifier_report_binding"],
        "reproduction": report["reproduction"],
        "finding_codes": codes,
        "evidence_bindings": [
            state["fusion"]["candidate_binding"],
            receipt["verifier_report_binding"],
            state["lanes"]["BUILDER"]["manifest_binding"],
            state["lanes"]["VERIFIER"]["manifest_binding"],
        ],
        "created_at": receipt["created_at"],
    }
    _require(receipt == seal(expected), "PROGRAM_COUNTERSIGN_RECOMPUTE_MISMATCH")
    _require(
        state["fusion"]["state"]
        in (
            {status_by_decision[decision], "PROGRAM_BAPTIZED"}
            if decision == "ACCEPTED"
            else {status_by_decision[decision]}
        )
        and (
            state["phase"] == status_by_decision[decision]
            or state["phase"] == "PROGRAM_BAPTIZED" and decision == "ACCEPTED"
        ),
        "PROGRAM_COUNTERSIGN_STATE_MISMATCH",
    )
    return receipt


def _load_and_validate_baptism(
    state: dict[str, Any], candidate: dict[str, Any], countersign: dict[str, Any]
) -> dict[str, Any]:
    _require(
        state["baptism"]["state"] == "PROGRAM_BAPTIZED"
        and isinstance(state["baptism"]["receipt_binding"], dict),
        "PROGRAM_BAPTISM_RECEIPT_REQUIRED",
    )
    raw, _ = _read_binding(
        state["baptism"]["receipt_binding"],
        "PROGRAM_BAPTISM_RECEIPT",
        allowed_roots=[Path(state["planning_root"])],
    )
    try:
        receipt = strict_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PROGRAM_BAPTISM_RECEIPT_INVALID") from error
    _require(isinstance(receipt, dict), "PROGRAM_BAPTISM_RECEIPT_INVALID")
    _validate_schema(receipt, "omni-program-baptism-receipt-v1")
    _require(verify_record(receipt), "PROGRAM_BAPTISM_RECEIPT_INVALID")
    pm_raw, _ = _read_binding(
        receipt["pm_decision_binding"],
        "PROGRAM_BAPTISM_DECISION",
        allowed_roots=[Path(state["planning_root"])],
    )
    try:
        pm = strict_json(pm_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ProgramPipelineError("PROGRAM_BAPTISM_DECISION_INVALID") from error
    _require(isinstance(pm, dict), "PROGRAM_BAPTISM_DECISION_INVALID")
    _validate_schema(pm, "omni-program-baptism-decision-v1")
    _require(verify_record(pm), "PROGRAM_BAPTISM_DECISION_INVALID")
    expected_pm = {
        "schema": "omni-program-baptism-decision-v1",
        "status": "PROGRAM_BAPTISM_AUTHORIZED",
        "decision": "ACCEPTED",
        "program_id": state["program_id"],
        "task_id": state["task_id"],
        "knowledge_pipeline_id": state["knowledge_pipeline_id"],
        "session_pair_sha256": state["session_pair_sha256"],
        "program_binding": state["fusion"]["candidate_binding"],
        "program_record_digest": candidate["record_digest"],
        "program_countersign_binding": state["fusion"]["countersign_binding"],
        "program_countersign_record_digest": countersign["record_digest"],
        "sovereign_id": state["sovereign_id"],
        "created_at": pm["created_at"],
    }
    _require(pm == seal(expected_pm), "PROGRAM_BAPTISM_DECISION_RECOMPUTE_MISMATCH")
    expected_receipt = {
        **{key: value for key, value in expected_pm.items() if key not in {"schema", "status"}},
        "schema": "omni-program-baptism-receipt-v1",
        "status": "PROGRAM_BAPTIZED",
        "pm_decision_binding": receipt["pm_decision_binding"],
        "created_at": receipt["created_at"],
    }
    _require(receipt == seal(expected_receipt), "PROGRAM_BAPTISM_RECEIPT_RECOMPUTE_MISMATCH")
    return receipt


def command_countersign_program(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, state_binding = _load_state(args.state, args.state_sha256)
    _require(state["phase"] == "PROGRAM_FUSION_FROZEN", "ILLEGAL_PLANNING_TRANSITION")
    candidate, manifests, _, _ = _load_and_validate_candidate(state)
    verifier_lane = Path(state["lanes"]["VERIFIER"]["lane_root"])
    report, report_binding = _load_bound_json(args.verifier_report, args.verifier_report_sha256, "PROGRAM_VERIFIER_REPORT", allowed_roots=[verifier_lane])
    decision, codes = _validate_verifier_report(report, state)
    output = _inside(args.output, Path(state["planning_root"]), "STATE_OUTPUT", strict=False)
    receipt_output = _inside(args.receipt_output, verifier_lane, "PROGRAM_COUNTERSIGN_OUTPUT", strict=False)
    verifier_session = state["session_pair"]["verifier"]["session_id"]
    authority, authority_binding, nonce_binding, claim_binding, reservation = _authority_context(
        args.authority, args.authority_sha256, command="countersign-program",
        program_id=state["program_id"], task_id=state["task_id"],
        knowledge_pipeline_id=state["knowledge_pipeline_id"],
        knowledge_state_binding=state["knowledge_state_binding"],
        knowledge_fusion_binding=state["knowledge_fusion_countersign_binding"],
        session_pair_sha256=state["session_pair_sha256"], subject_role="VERIFIER",
        subject_session_id=verifier_session, planning_root=Path(state["planning_root"]),
        previous_binding=state_binding, required_inputs=[state_binding, report_binding],
        required_outputs=[output, receipt_output], next_generation=state["generation"] + 1,
    )
    status_by_decision = {
        "ACCEPTED": "PROGRAM_COUNTERSIGN_ACCEPTED",
        "BLOCK": "PROGRAM_COUNTERSIGN_BLOCKED",
        "INCONCLUSIVE": "PROGRAM_COUNTERSIGN_INCONCLUSIVE",
    }
    receipt = {
        "schema": "omni-program-countersign-receipt-v2",
        "status": status_by_decision[decision], "decision": decision,
        "receipt_id": f"{state['program_id']}-COUNTERSIGN",
        "program_id": state["program_id"], "task_id": state["task_id"],
        "knowledge_pipeline_id": state["knowledge_pipeline_id"],
        "program_binding": state["fusion"]["candidate_binding"],
        "program_record_digest": candidate["record_digest"],
        "knowledge_state_binding": state["knowledge_state_binding"],
        "knowledge_fusion_countersign_binding": state["knowledge_fusion_countersign_binding"],
        "session_pair_sha256": state["session_pair_sha256"],
        "program_author_session_id": candidate["author_session_id"],
        "signer_role": "VERIFIER", "signer_session_id": verifier_session,
        "verifier_report_binding": report_binding,
        "reproduction": report["reproduction"], "finding_codes": codes,
        "evidence_bindings": [
            state["fusion"]["candidate_binding"], report_binding,
            state["lanes"]["BUILDER"]["manifest_binding"],
            state["lanes"]["VERIFIER"]["manifest_binding"],
        ],
        "created_at": authority["created_at"],
    }
    prepared_receipt = _prepare_record(receipt, receipt_output, verifier_lane)
    receipt_binding = prepared_receipt["binding"]
    state["fusion"]["state"] = status_by_decision[decision]
    state["fusion"]["countersign_binding"] = receipt_binding
    state_status = "ACTIVE" if decision == "ACCEPTED" else ("BLOCKED" if decision == "BLOCK" else "INCONCLUSIVE")
    next_state = _build_state(
        state, state_binding, output=output, phase=status_by_decision[decision],
        status=state_status, event="COUNTERSIGN_PROGRAM", actor_role="VERIFIER",
        actor_session_id=verifier_session, authority_binding=authority_binding,
        nonce_binding=nonce_binding, claim_binding=claim_binding,
        evidence=[state["fusion"]["candidate_binding"], report_binding, receipt_binding],
        blocking_codes=codes, created_at=authority["created_at"],
    )
    prepared_state = _prepare_record(next_state, output, Path(state["planning_root"]))
    return _finalize_transition([prepared_receipt, prepared_state], reservation)


PM_DECISION_KEYS = {
    "schema", "status", "decision", "program_id", "task_id",
    "knowledge_pipeline_id", "session_pair_sha256", "program_binding",
    "program_record_digest", "program_countersign_binding",
    "program_countersign_record_digest", "sovereign_id", "created_at", "record_digest",
}


def command_baptize_program(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, state_binding = _load_state(args.state, args.state_sha256)
    _require(state["phase"] == "PROGRAM_COUNTERSIGN_ACCEPTED", "PROGRAM_COUNTERSIGN_ACCEPTED_REQUIRED")
    candidate, _, _, _ = _load_and_validate_candidate(state)
    countersign = _load_and_validate_program_countersign(state, candidate)
    _require(countersign.get("decision") == "ACCEPTED", "PROGRAM_COUNTERSIGN_ACCEPTED_REQUIRED")
    pm_decision, pm_binding = _load_bound_json(args.pm_decision, args.pm_decision_sha256, "PROGRAM_BAPTISM_DECISION")
    _validate_schema(pm_decision, "omni-program-baptism-decision-v1")
    _require(set(pm_decision) == PM_DECISION_KEYS and verify_record(pm_decision), "PROGRAM_BAPTISM_DECISION_INVALID")
    _require(
        pm_decision.get("schema") == "omni-program-baptism-decision-v1"
        and pm_decision.get("status") == "PROGRAM_BAPTISM_AUTHORIZED"
        and pm_decision.get("decision") == "ACCEPTED"
        and pm_decision.get("program_id") == state["program_id"]
        and pm_decision.get("task_id") == state["task_id"]
        and pm_decision.get("knowledge_pipeline_id") == state["knowledge_pipeline_id"]
        and pm_decision.get("session_pair_sha256") == state["session_pair_sha256"]
        and pm_decision.get("program_binding") == state["fusion"]["candidate_binding"]
        and pm_decision.get("program_record_digest") == candidate["record_digest"]
        and pm_decision.get("program_countersign_binding") == state["fusion"]["countersign_binding"]
        and pm_decision.get("program_countersign_record_digest") == countersign["record_digest"]
        and isinstance(pm_decision.get("sovereign_id"), str)
        and bool(pm_decision["sovereign_id"].strip()),
        "PROGRAM_BAPTISM_DIGEST_MISMATCH",
    )
    _require(
        pm_decision["sovereign_id"] == state["sovereign_id"],
        "PROGRAM_BAPTISM_SOVEREIGN_MISMATCH",
    )
    output = _inside(args.output, Path(state["planning_root"]), "STATE_OUTPUT", strict=False)
    baptism_output = _inside(args.baptism_output, Path(state["planning_root"]), "PROGRAM_BAPTISM_OUTPUT", strict=False)
    authority, authority_binding, nonce_binding, claim_binding, reservation = _authority_context(
        args.authority, args.authority_sha256, command="baptize-program",
        program_id=state["program_id"], task_id=state["task_id"],
        knowledge_pipeline_id=state["knowledge_pipeline_id"],
        knowledge_state_binding=state["knowledge_state_binding"],
        knowledge_fusion_binding=state["knowledge_fusion_countersign_binding"],
        session_pair_sha256=state["session_pair_sha256"], subject_role="PM",
        subject_session_id=pm_decision["sovereign_id"], planning_root=Path(state["planning_root"]),
        previous_binding=state_binding, required_inputs=[state_binding, pm_binding],
        required_outputs=[output, baptism_output], next_generation=state["generation"] + 1,
    )
    receipt = {
        "schema": "omni-program-baptism-receipt-v1", "status": "PROGRAM_BAPTIZED",
        "decision": "ACCEPTED", "program_id": state["program_id"],
        "task_id": state["task_id"], "knowledge_pipeline_id": state["knowledge_pipeline_id"],
        "session_pair_sha256": state["session_pair_sha256"],
        "program_binding": state["fusion"]["candidate_binding"],
        "program_record_digest": candidate["record_digest"],
        "program_countersign_binding": state["fusion"]["countersign_binding"],
        "program_countersign_record_digest": countersign["record_digest"],
        "pm_decision_binding": pm_binding, "sovereign_id": pm_decision["sovereign_id"],
        "created_at": authority["created_at"],
    }
    prepared_baptism = _prepare_record(receipt, baptism_output, Path(state["planning_root"]))
    baptism_binding = prepared_baptism["binding"]
    state["fusion"]["state"] = "PROGRAM_BAPTIZED"
    state["baptism"] = {"state": "PROGRAM_BAPTIZED", "receipt_binding": baptism_binding}
    next_state = _build_state(
        state, state_binding, output=output, phase="PROGRAM_BAPTIZED", status="PASS",
        event="BAPTIZE_PROGRAM", actor_role="PM", actor_session_id=pm_decision["sovereign_id"],
        authority_binding=authority_binding, nonce_binding=nonce_binding, claim_binding=claim_binding,
        evidence=[state["fusion"]["candidate_binding"], state["fusion"]["countersign_binding"], pm_binding, baptism_binding],
        blocking_codes=[], created_at=authority["created_at"],
    )
    prepared_state = _prepare_record(next_state, output, Path(state["planning_root"]))
    return _finalize_transition([prepared_baptism, prepared_state], reservation)


def command_verify(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str]:
    state, binding = _load_state(args.state, args.state_sha256)
    if args.expect != "ANY_VALID":
        _require(
            state["phase"] == args.expect,
            "PROGRAM_STATE_EXPECTED_PHASE_MISMATCH",
            f"expected={args.expect};observed={state['phase']}",
        )
    candidate: dict[str, Any] | None = None
    if state["phase"] in {"PROGRAM_FUSION_FROZEN", "PROGRAM_COUNTERSIGN_ACCEPTED", "PROGRAM_COUNTERSIGN_BLOCKED", "PROGRAM_COUNTERSIGN_INCONCLUSIVE", "PROGRAM_BAPTIZED"}:
        candidate, _, _, _ = _load_and_validate_candidate(state)
    if state["phase"] in {"PROGRAM_COUNTERSIGN_ACCEPTED", "PROGRAM_COUNTERSIGN_BLOCKED", "PROGRAM_COUNTERSIGN_INCONCLUSIVE", "PROGRAM_BAPTIZED"}:
        _require(candidate is not None, "FUSED_PROGRAM_INVALID")
        receipt = _load_and_validate_program_countersign(state, candidate)
        if state["phase"] == "PROGRAM_BAPTIZED":
            _load_and_validate_baptism(state, candidate, receipt)
    return state, binding, "EXPECTED_PHASE_MATCH" if args.expect != "ANY_VALID" else "VALID_INTERMEDIATE"


COMMANDS = {
    "init": command_init,
    "commit-plan-lanes": command_commit_plan_lanes,
    "freeze-plan-lane": command_freeze_plan_lane,
    "emit-program-fusion": command_emit_program_fusion,
    "countersign-program": command_countersign_program,
    "baptize-program": command_baptize_program,
    "verify": command_verify,
}


def _common(subparsers: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--state-sha256", required=True)
    parser.add_argument("--authority", required=True, type=Path)
    parser.add_argument("--authority-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--knowledge-state", required=True, type=Path)
    init.add_argument("--knowledge-state-sha256", required=True)
    init.add_argument("--authority", required=True, type=Path)
    init.add_argument("--authority-sha256", required=True)
    init.add_argument("--program-id", required=True)
    init.add_argument("--planning-root", required=True, type=Path)
    init.add_argument("--output", required=True, type=Path)
    commit = _common(subparsers, "commit-plan-lanes")
    commit.add_argument("--builder-plan-draft", required=True, type=Path)
    commit.add_argument("--builder-plan-draft-sha256", required=True)
    commit.add_argument("--verifier-plan-draft", required=True, type=Path)
    commit.add_argument("--verifier-plan-draft-sha256", required=True)
    lane = _common(subparsers, "freeze-plan-lane")
    lane.add_argument("--role", required=True, choices=ROLES)
    lane.add_argument("--plan-draft", required=True, type=Path)
    lane.add_argument("--plan-draft-sha256", required=True)
    lane.add_argument("--manifest-output", required=True, type=Path)
    fusion = _common(subparsers, "emit-program-fusion")
    fusion.add_argument("--fused-plan", required=True, type=Path)
    fusion.add_argument("--fused-plan-sha256", required=True)
    fusion.add_argument("--decision-register", required=True, type=Path)
    fusion.add_argument("--decision-register-sha256", required=True)
    fusion.add_argument("--candidate-output", required=True, type=Path)
    countersign = _common(subparsers, "countersign-program")
    countersign.add_argument("--verifier-report", required=True, type=Path)
    countersign.add_argument("--verifier-report-sha256", required=True)
    countersign.add_argument("--receipt-output", required=True, type=Path)
    baptism = _common(subparsers, "baptize-program")
    baptism.add_argument("--pm-decision", required=True, type=Path)
    baptism.add_argument("--pm-decision-sha256", required=True)
    baptism.add_argument("--baptism-output", required=True, type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--state", required=True, type=Path)
    verify.add_argument("--state-sha256", required=True)
    verify.add_argument("--expect", required=True, choices=[*PHASES, "ANY_VALID"])
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        record, binding, write_status = COMMANDS[args.command](args)
        print(
            canonical_json(
                {
                    "schema": "omni-program-command-result-v1",
                    "status": "PASS",
                    "command": args.command,
                    "write_status": write_status,
                    "phase": record["phase"],
                    "output_binding": binding,
                }
            )
        )
        return 0
    except ProgramPipelineError as error:
        result = {
            "schema": "omni-program-command-result-v1",
            "status": "BLOCKED",
            "reason_code": error.reason_code,
        }
        if error.detail:
            result["detail"] = error.detail
        print(canonical_json(result))
        return 2
    except PathSafetyError as error:
        detail = str(error)
        print(canonical_json({
            "schema": "omni-program-command-result-v1", "status": "BLOCKED",
            "reason_code": detail.split(":", 1)[0] or "PATH_SAFETY_ERROR", "detail": detail,
        }))
        return 2
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(canonical_json({
            "schema": "omni-program-command-result-v1", "status": "BLOCKED",
            "reason_code": "L4_INTERNAL_INPUT_ERROR", "detail": type(error).__name__,
        }))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Fail-closed L5 operating-regime controller.

This module records regime selection and proves bounded execution authority.  It
never executes project work, starts an agent, arms a host process, installs,
publishes, or performs an external effect.  Selection, autonomy, automation,
sentinel health, and execution lease are deliberately separate facts.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

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
SCHEMA_FILES = {
    "omni-operating-regime-binding-v1": "operating_regime_binding.schema.json",
    "omni-guided-pm-turn-authority-v1": "operating_regime_binding.schema.json",
    "omni-persistent-objective-v1": "persistent_objective.schema.json",
    "omni-autonomy-authority-v1": "autonomy_authority.schema.json",
    "omni-automation-arm-authority-v1": "automation_arm_authority.schema.json",
    "omni-sentinel-bundle-receipt-v1": "sentinel_bundle_receipt.schema.json",
    "omni-execution-lease-v1": "execution_lease.schema.json",
    "omni-operating-state-v1": "operating_state.schema.json",
    "omni-fused-program-v2": "fused_program.schema.json",
    "omni-program-countersign-receipt-v2": "program_countersign_receipt.schema.json",
}
FORBIDDEN_EFFECTS = frozenset(
    {"F5", "F5_DELIVERY", "INSTALL", "INSTALLATION", "PUBLISH", "PUBLICATION", "EXTERNAL_EFFECTS"}
)
FENCED_CLASSES = [
    "OBJECTIVE", "HEARTBEAT", "RETRY", "SCHEDULE", "BACKGROUND_JOB",
    "AUTOMATION", "ARCHIVED_TASK_WAKEUP",
]
PM_AUTHORITY_SCHEMA = "omni-pm-authority-record-v1"
EFFECT_WRITE_CLASSES = frozenset(
    {"PROJECT_WRITE", "OFFICIAL_CHANNEL_WRITE", "STATE_CHECKPOINT", "HANDOFF_FREEZE"}
)
MAX_STATE_CHAIN = 100_000


class OperatingError(RuntimeError):
    """A stable, typed BLOCK or INCONCLUSIVE L5 result."""

    def __init__(self, reason_code: str, *, decision: str = "BLOCK", detail: str = "") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.decision = decision
        self.detail = detail


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise OperatingError("OPERATING_REGIME_INVALID", detail=message)


def _fail(code: str, *, decision: str = "BLOCK", detail: str = "") -> None:
    raise OperatingError(code, decision=decision, detail=detail)


def _require(condition: bool, code: str, *, decision: str = "BLOCK", detail: str = "") -> None:
    if not condition:
        _fail(code, decision=decision, detail=detail)


def _sha(value: str, code: str) -> str:
    normalized = str(value).upper()
    _require(bool(SHA256_RE.fullmatch(normalized)), code)
    return normalized


def _identifier(value: str, code: str) -> str:
    normalized = str(value).strip().upper()
    _require(bool(IDENTIFIER_RE.fullmatch(normalized)), code)
    return normalized


def _projection_digest(record: dict[str, Any]) -> str:
    return sha256_bytes(
        canonical_json({key: value for key, value in record.items() if key != "record_digest"}).encode("utf-8")
    )


def seal(record: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(record)
    result.pop("record_digest", None)
    result["record_digest"] = sha256_bytes(canonical_json(result).encode("utf-8"))
    return result


def verify_record(record: object) -> bool:
    return (
        isinstance(record, dict)
        and isinstance(record.get("record_digest"), str)
        and record["record_digest"] == _projection_digest(record)
    )


def _binding(path: Path, data: bytes | None = None) -> dict[str, Any]:
    if data is None:
        data, physical = read_bound_bytes(path, label="L5_BINDING")
    else:
        physical = absolute_physical_path(path, "L5_BINDING", strict=True)
    return {"path": str(physical), "bytes": len(data), "sha256": sha256_bytes(data)}


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_datetime(value: object, code: str) -> dt.datetime:
    _require(isinstance(value, str), code)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _fail(code)
    _require(parsed.tzinfo is not None, code)
    return parsed.astimezone(dt.timezone.utc)


def _authority_payload_digest(record: dict[str, Any]) -> str:
    """Hash the exact authority subject without its PM receipt or self seal."""
    return sha256_bytes(
        canonical_json(
            {
                key: value
                for key, value in record.items()
                if key not in {"record_digest", "pm_authority_record_binding"}
            }
        ).encode("utf-8")
    )


def _same_binding(left: object, right: object) -> bool:
    return isinstance(left, dict) and isinstance(right, dict) and left == right


def _schema_validate(record: dict[str, Any], code: str) -> None:
    filename = SCHEMA_FILES.get(str(record.get("schema")))
    _require(filename is not None, code)
    path = SCHEMA_DIR / str(filename)
    _require(path.is_file(), code, decision="INCONCLUSIVE", detail=f"missing schema {filename}")
    try:
        import jsonschema
        schema = strict_json(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        failures = sorted(validator.iter_errors(record), key=lambda item: list(item.absolute_path))
    except Exception as error:
        _fail(code, decision="INCONCLUSIVE", detail=f"schema runtime: {type(error).__name__}")
    if failures:
        location = "/".join(str(part) for part in failures[0].absolute_path) or "$"
        _fail(code, detail=f"schema mismatch at {location}")


def _read_record(
    path: str | Path,
    expected_sha256: str,
    *,
    code: str,
    expected_schema: str | None = None,
    allowed_roots: Iterable[str | Path] | None = None,
    schema_validate: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw, physical = read_bound_bytes(
            path,
            expected_sha256=_sha(expected_sha256, code),
            allowed_roots=allowed_roots,
            label=code,
        )
        value = strict_json(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, PathSafetyError) as error:
        _fail(code, decision="INCONCLUSIVE", detail=type(error).__name__)
    _require(isinstance(value, dict), code)
    _require(verify_record(value), code)
    if expected_schema is not None:
        _require(value.get("schema") == expected_schema, code)
    if schema_validate:
        _schema_validate(value, code)
    return value, _binding(physical, raw)


def _read_untyped_binding(binding: dict[str, Any], code: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(isinstance(binding, dict) and set(binding) == {"path", "bytes", "sha256"}, code)
    try:
        raw, physical = read_bound_bytes(
            binding["path"], expected_bytes=binding["bytes"], expected_sha256=binding["sha256"], label=code
        )
        value = strict_json(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, PathSafetyError) as error:
        _fail(code, decision="INCONCLUSIVE", detail=type(error).__name__)
    _require(isinstance(value, dict) and verify_record(value), code)
    return value, _binding(physical, raw)


def _state_root(value: str | Path) -> Path:
    try:
        root = absolute_physical_path(value, "L5_STATE_ROOT", strict=True)
    except PathSafetyError as error:
        _fail("OPERATING_REGIME_SCOPE_REPLAY", decision="INCONCLUSIVE", detail=str(error))
    _require(root.is_dir(), "OPERATING_REGIME_SCOPE_REPLAY")
    return root


def _trusted_pm_context(
    value: str | Path, issuer_id: str, *, state_root: Path | None = None
) -> tuple[Path, str]:
    """Resolve the trust anchor supplied by the host, never by an authority record."""
    try:
        root = absolute_physical_path(value, "TRUSTED_PM_ROOT", strict=True)
    except PathSafetyError as error:
        _fail("TRUSTED_PM_ROOT_REQUIRED", decision="INCONCLUSIVE", detail=str(error))
    _require(root.is_dir(), "TRUSTED_PM_ROOT_REQUIRED")
    issuer = _identifier(issuer_id, "TRUSTED_PM_ISSUER_REQUIRED")
    if state_root is not None:
        try:
            root.relative_to(state_root)
            _fail("TRUSTED_PM_ROOT_NOT_SEPARATE")
        except ValueError:
            pass
        try:
            state_root.relative_to(root)
            _fail("TRUSTED_PM_ROOT_NOT_SEPARATE")
        except ValueError:
            pass
    return root, issuer


def _require_external_trust(
    state: dict[str, Any], trusted_pm_root: str | Path, trusted_pm_issuer_id: str,
    state_root: Path,
) -> tuple[Path, str]:
    root, issuer = _trusted_pm_context(
        trusted_pm_root, trusted_pm_issuer_id, state_root=state_root
    )
    _require(str(root) == state.get("trusted_pm_root"), "TRUSTED_PM_ROOT_REQUIRED")
    _require(issuer == state.get("trusted_pm_issuer_id"), "TRUSTED_PM_ISSUER_REQUIRED")
    return root, issuer


def _read_trusted_record(
    binding: object, *, trusted_root: Path, issuer_id: str, code: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(isinstance(binding, dict), code)
    value, observed = _read_untyped_binding(binding, code)
    try:
        Path(observed["path"]).relative_to(trusted_root)
    except ValueError:
        _fail("TRUSTED_PM_ROOT_REQUIRED")
    _require(value.get("issuer_id") == issuer_id, "TRUSTED_PM_ISSUER_REQUIRED")
    return value, observed


def _validate_pm_authority(
    subject: dict[str, Any], *, trusted_root: Path, issuer_id: str,
    authority_kind: str, subject_id: str, code: str,
) -> dict[str, Any]:
    binding = subject.get("pm_authority_record_binding")
    value, observed = _read_trusted_record(
        binding, trusted_root=trusted_root, issuer_id=issuer_id, code=code
    )
    expected = {
        "schema": PM_AUTHORITY_SCHEMA,
        "status": "AUTHORIZED",
        "decision": "AUTHORIZED",
        "issuer_id": issuer_id,
        "authority_kind": authority_kind,
        "task_id": subject.get("task_id"),
        "program_id": subject.get("program_id"),
        "session_pair_sha256": subject.get("session_pair_sha256"),
        "subject_schema": subject.get("schema"),
        "subject_id": subject_id,
        "subject_payload_sha256": _authority_payload_digest(subject),
        "one_shot": True,
    }
    _require(set(value) == set(expected) | {"record_digest"}, code)
    for field, expected_value in expected.items():
        _require(value.get(field) == expected_value, code, detail=field)
    _require(observed == binding, code)
    return observed


def _state_path(root: Path, seq: int) -> Path:
    return root / ".omni-operating" / "states" / f"STATE_{seq:06d}.json"


def _lease_path(root: Path, generation: int) -> Path:
    return root / ".omni-operating" / "leases" / f"LEASE_{generation:06d}.json"


def _nonce_path(root: Path, nonce: str) -> Path:
    return root / ".omni-operating" / "nonces" / f"{_identifier(nonce, 'OPERATING_AUTHORITY_REPLAY')}.json"


def _supervisor_path(root: Path, namespace: str) -> Path:
    return root / ".omni-operating" / "supervisors" / f"{_identifier(namespace, 'SUPERVISOR_NAMESPACE_COLLISION')}.json"


def _prepare_operating_dirs(root: Path) -> None:
    """Create the fixed L5 namespace before any concurrent create-once CAS.

    ``io_safe.create_once_*`` deliberately validates every ancestor.  On
    Windows, two threads creating different children of the same previously
    absent directory can transiently disagree about the extended-path spelling
    returned by ``Path.resolve``.  Pre-creating the bounded namespace removes
    that directory-creation race without weakening the per-record create-once
    CAS that decides the actual writer.
    """
    operating = root / ".omni-operating"
    try:
        for directory in (
            operating,
            operating / "states",
            operating / "leases",
            operating / "nonces",
            operating / "supervisors",
        ):
            directory.mkdir(parents=True, exist_ok=True)
            physical = absolute_physical_path(directory, "L5_OPERATING_NAMESPACE", strict=True)
            physical.relative_to(root)
            _require(physical.is_dir(), "OPERATING_REGIME_SCOPE_REPLAY")
    except (OSError, ValueError, PathSafetyError) as error:
        _fail("OPERATING_REGIME_SCOPE_REPLAY", decision="INCONCLUSIVE", detail=type(error).__name__)


def _write_create_once(
    path: Path, record: dict[str, Any], root: Path, collision_code: str,
    *, with_status: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], str]:
    sealed = seal(record)
    text = canonical_json(sealed) + "\n"
    try:
        write_status = create_once_text(path, text, allowed_root=root)
    except RuntimeError as error:
        _fail(collision_code, detail=str(error).split(":", 1)[0])
    except (OSError, ValueError, PathSafetyError) as error:
        _fail(collision_code, decision="INCONCLUSIVE", detail=type(error).__name__)
    observed, binding = _read_record(
        path, sha256_bytes(text.encode("utf-8")), code=collision_code,
        expected_schema=str(sealed["schema"]), schema_validate=str(sealed["schema"]) in SCHEMA_FILES,
    )
    _require(observed == sealed, collision_code)
    if with_status:
        return binding, write_status
    return binding


def _consume_nonce(root: Path, nonce: str, action: str, fingerprint: str) -> None:
    record = {
        "schema": "omni-operating-nonce-consumption-v1",
        "status": "CONSUMED",
        "nonce": _identifier(nonce, "OPERATING_AUTHORITY_REPLAY"),
        "action": _identifier(action, "OPERATING_AUTHORITY_REPLAY"),
        "fingerprint": _sha(fingerprint, "OPERATING_AUTHORITY_REPLAY"),
    }
    sealed = seal(record)
    text = canonical_json(sealed) + "\n"
    path = _nonce_path(root, nonce)
    try:
        create_once_text(path, text, allowed_root=root)
    except RuntimeError as error:
        _fail("OPERATING_AUTHORITY_REPLAY", detail=str(error).split(":", 1)[0])
    except (OSError, ValueError, PathSafetyError) as error:
        _fail("OPERATING_AUTHORITY_REPLAY", decision="INCONCLUSIVE", detail=type(error).__name__)


def _fingerprint(*records: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json([record.get("record_digest") for record in records]).encode("utf-8"))


def _check_scope(reference: dict[str, Any], *records: dict[str, Any], code: str) -> None:
    for record in records:
        for field in ("task_id", "program_id", "session_pair_sha256"):
            if field in record:
                _require(record.get(field) == reference.get(field), code, detail=field)


def _validate_program_chain(
    binding: dict[str, Any], program: dict[str, Any], program_binding: dict[str, Any],
    countersign: dict[str, Any], countersign_binding: dict[str, Any],
) -> None:
    _require(binding.get("regime") in {"GUIDED_PM", "AUTONOMOUS"}, "OPERATING_REGIME_INVALID")
    _require(_same_binding(binding.get("fused_program_binding"), program_binding), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(_same_binding(binding.get("program_countersign_binding"), countersign_binding), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(binding.get("program_record_digest") == program.get("record_digest"), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(binding.get("countersign_record_digest") == countersign.get("record_digest"), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(countersign.get("status") == "PROGRAM_COUNTERSIGN_ACCEPTED" and countersign.get("decision") == "ACCEPTED", "OPERATING_REGIME_BINDING_REQUIRED")
    _require(_same_binding(countersign.get("program_binding"), program_binding), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(countersign.get("program_record_digest") == program.get("record_digest"), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(countersign.get("program_author_session_id") == program.get("author_session_id"), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(countersign.get("signer_session_id") != program.get("author_session_id"), "OPERATING_REGIME_INVALID")
    _check_scope(binding, program, countersign, code="OPERATING_REGIME_SCOPE_REPLAY")
    _require(binding.get("knowledge_pipeline_id") == program.get("knowledge_pipeline_id"), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(binding.get("subject_session_id") == program.get("author_session_id"), "OPERATING_REGIME_SCOPE_REPLAY")


def _validate_channel_record(
    binding: dict[str, Any], channel_binding: dict[str, Any], *,
    trusted_root: Path, issuer_id: str,
    guided_turn: dict[str, Any] | None = None,
) -> None:
    code = "GUIDED_PM_TURN_AUTHORITY_REQUIRED" if guided_turn is not None else "OPERATING_REGIME_BINDING_REQUIRED"
    value, observed = _read_trusted_record(
        channel_binding, trusted_root=trusted_root, issuer_id=issuer_id, code=code
    )
    if guided_turn is None:
        try:
            declared = absolute_physical_path(
                binding.get("official_channel_root", ""), "OFFICIAL_CHANNEL_ROOT", strict=True
            )
        except PathSafetyError as error:
            _fail("OFFICIAL_CHANNEL_BINDING_REQUIRED", detail=type(error).__name__)
        _require(declared == trusted_root, "TRUSTED_PM_ROOT_REQUIRED")
    if guided_turn is None:
        expected = {
            "schema": "omni-operating-regime-pm-binding-v1",
            "status": "AUTHORIZED", "decision": "AUTHORIZED",
            "issuer_id": issuer_id,
            "binding_id": binding["binding_id"], "task_id": binding["task_id"],
            "program_id": binding["program_id"], "regime": binding["regime"],
            "session_pair_sha256": binding["session_pair_sha256"],
            "selection_nonce": binding["selection_nonce"],
            "reserved_gate": "OPERATING_REGIME_BINDING", "effects_authorized": False,
        }
    else:
        expected = {
            "schema": "omni-guided-pm-channel-authority-v1",
            "status": "AUTHORIZED", "decision": "AUTHORIZED",
            "issuer_id": issuer_id,
            "binding_id": guided_turn["binding_id"], "task_id": guided_turn["task_id"],
            "program_id": guided_turn["program_id"], "action_id": guided_turn["action_id"],
            "idempotency_key": guided_turn["idempotency_key"],
            "operation_nonce": guided_turn["operation_nonce"],
            "session_pair_sha256": guided_turn["session_pair_sha256"],
            "subject_session_id": guided_turn["subject_session_id"],
            "authorized_effects": guided_turn["authorized_effects"],
            "target_paths": guided_turn["target_paths"],
            "output_paths": guided_turn["output_paths"],
            "automation_authorized": False,
        }
    _require(set(value) == set(expected) | {"record_digest"}, code)
    for field, expected_value in expected.items():
        _require(value.get(field) == expected_value, code, detail=field)
    _require(observed == channel_binding, code)


def _load_state(path: str | Path, sha256: str, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state, binding = _read_record(
        path, sha256, code="OPERATING_REGIME_BINDING_REQUIRED",
        expected_schema="omni-operating-state-v1", allowed_roots=[root],
    )
    expected_path = _state_path(root, int(state["state_seq"]))
    _require(Path(binding["path"]) == expected_path.resolve(strict=True), "OPERATING_REGIME_SCOPE_REPLAY")
    return state, binding


def _ensure_latest(state: dict[str, Any], root: Path, code: str) -> None:
    _require(not _state_path(root, int(state["state_seq"]) + 1).exists(), code)


def bind_regime(
    *, binding_path: str | Path, binding_sha256: str, program_path: str | Path,
    program_sha256: str, countersign_path: str | Path, countersign_sha256: str,
    state_root: str | Path, trusted_pm_root: str | Path,
    trusted_pm_issuer_id: str,
) -> dict[str, Any]:
    root = _state_root(state_root)
    pm_root, pm_issuer = _trusted_pm_context(
        trusted_pm_root, trusted_pm_issuer_id, state_root=root
    )
    _prepare_operating_dirs(root)
    binding, binding_file = _read_record(
        binding_path, binding_sha256, code="OPERATING_REGIME_BINDING_REQUIRED",
        expected_schema="omni-operating-regime-binding-v1", schema_validate=False,
    )
    program, program_file = _read_record(
        program_path, program_sha256, code="OPERATING_REGIME_BINDING_REQUIRED",
        expected_schema="omni-fused-program-v2",
    )
    countersign, countersign_file = _read_record(
        countersign_path, countersign_sha256, code="OPERATING_REGIME_BINDING_REQUIRED",
        expected_schema="omni-program-countersign-receipt-v2",
    )
    _require(binding.get("effects_authorized") is False and binding.get("automation_armed") is False, "MODE_SELECTION_DOES_NOT_AUTHORIZE_EFFECTS")
    _schema_validate(binding, "OPERATING_REGIME_INVALID")
    _validate_program_chain(binding, program, program_file, countersign, countersign_file)
    _validate_channel_record(
        binding, binding["pm_channel_record_binding"],
        trusted_root=pm_root, issuer_id=pm_issuer,
    )
    _consume_nonce(root, binding["selection_nonce"], "BIND_REGIME", _fingerprint(binding, program, countersign))
    state = {
        "schema": "omni-operating-state-v1", "status": "REGIME_BOUND",
        "state_id": f"{binding['binding_id']}.STATE.0", "state_seq": 0,
        "previous_state_binding": None, "task_id": binding["task_id"],
        "program_id": binding["program_id"], "knowledge_pipeline_id": binding["knowledge_pipeline_id"],
        "regime": binding["regime"], "regime_binding": binding_file,
        "fused_program_binding": program_file, "program_countersign_binding": countersign_file,
        "session_pair_sha256": binding["session_pair_sha256"], "owner_role": "BUILDER",
        "owner_session_id": binding["subject_session_id"], "guided_turn_authority_binding": None,
        "objective_binding": None, "autonomy_authority_binding": None,
        "arm_authority_binding": None, "sentinel_bundle_binding": None,
        "execution_lease_binding": None, "authorized_effects": [], "effects_authorized": False,
        "automation_armed": False, "single_writer": False, "budget_snapshot": None,
        "kill_switch_path": None, "kill_switch_generation": None,
        "official_channel_binding": binding["pm_channel_record_binding"],
        "trusted_pm_root": str(pm_root), "trusted_pm_issuer_id": pm_issuer,
        "last_effect": None, "finding_codes": [], "created_at": binding["created_at"],
    }
    state_binding = _write_create_once(_state_path(root, 0), state, root, "DUAL_WRITER")
    return {"status": "REGIME_BOUND", "state_binding": state_binding, "effects_authorized": False, "automation_armed": False}


def activate_guided_turn(
    *, state_path: str | Path, state_sha256: str, turn_authority_path: str | Path,
    turn_authority_sha256: str, state_root: str | Path,
    trusted_pm_root: str | Path, trusted_pm_issuer_id: str,
) -> dict[str, Any]:
    root = _state_root(state_root)
    _prepare_operating_dirs(root)
    state, state_file = _load_state(state_path, state_sha256, root)
    pm_root, pm_issuer = _require_external_trust(
        state, trusted_pm_root, trusted_pm_issuer_id, root
    )
    _ensure_latest(state, root, "GUIDED_PM_TURN_AUTHORITY_REQUIRED")
    _require(state.get("regime") == "GUIDED_PM", "OPERATING_REGIME_INVALID")
    authority, authority_file = _read_record(
        turn_authority_path, turn_authority_sha256, code="GUIDED_PM_TURN_AUTHORITY_REQUIRED",
        expected_schema="omni-guided-pm-turn-authority-v1", schema_validate=False,
    )
    regime, _ = _read_untyped_binding(state["regime_binding"], "OPERATING_REGIME_BINDING_REQUIRED")
    _check_scope(state, authority, code="OPERATING_REGIME_SCOPE_REPLAY")
    _require(authority.get("binding_id") == regime.get("binding_id"), "OPERATING_REGIME_SCOPE_REPLAY")
    _require(authority.get("subject_session_id") == state.get("owner_session_id"), "GUIDED_PM_TURN_AUTHORITY_REQUIRED")
    _require(_same_binding(authority.get("expected_previous_state_binding"), state_file), "GUIDED_PM_TURN_AUTHORITY_REQUIRED")
    _require(authority.get("automation_authorized") is False, "GUIDED_PM_AUTOMATION_UNAUTHORIZED")
    _require("ARM_AUTOMATION" not in authority.get("authorized_effects", []), "GUIDED_PM_AUTOMATION_UNAUTHORIZED")
    _schema_validate(authority, "GUIDED_PM_TURN_AUTHORITY_REQUIRED")
    for item in authority.get("input_bindings", []):
        _read_untyped_binding(item, "GUIDED_PM_TURN_AUTHORITY_REQUIRED")
    _validate_channel_record(
        regime, authority["official_channel_record_binding"],
        trusted_root=pm_root, issuer_id=pm_issuer, guided_turn=authority,
    )
    _consume_nonce(root, authority["operation_nonce"], "GUIDED_TURN", _fingerprint(state, authority))
    seq = int(state["state_seq"]) + 1
    next_state = {
        **{key: value for key, value in state.items() if key not in {"record_digest"}},
        "status": "GUIDED_TURN_READY", "state_id": f"{regime['binding_id']}.STATE.{seq}",
        "state_seq": seq, "previous_state_binding": state_file,
        "guided_turn_authority_binding": authority_file,
        "authorized_effects": authority["authorized_effects"], "effects_authorized": True,
        "automation_armed": False, "single_writer": True,
        "official_channel_binding": authority["official_channel_record_binding"],
        "created_at": authority["created_at"],
    }
    state_binding = _write_create_once(_state_path(root, seq), next_state, root, "DUAL_WRITER")
    return {"status": "GUIDED_TURN_READY", "state_binding": state_binding, "effects_authorized": True, "automation_armed": False}


def _validate_objective(objective: dict[str, Any], objective_binding: dict[str, Any]) -> None:
    satisfiability = objective.get("satisfiability", {})
    if satisfiability.get("status") == "UNSATISFIABLE":
        _fail("OBJECTIVE_UNSATISFIABLE")
    _require(satisfiability.get("status") == "PROVEN_SATISFIABLE", "OBJECTIVE_UNSATISFIABLE", decision="INCONCLUSIVE")
    _require(not satisfiability.get("blocking_assumptions"), "OBJECTIVE_UNSATISFIABLE")
    for proof in satisfiability.get("proof_bindings", []):
        _read_untyped_binding(proof, "OBJECTIVE_UNSATISFIABLE")
    conditions = objective.get("terminal_conditions", [])
    _require(bool(conditions), "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
    for condition in conditions:
        _require(condition.get("observable") is True and condition.get("proof_required") is True, "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
        subject, observed = _read_untyped_binding(
            condition.get("subject_binding"), "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE"
        )
        evaluator = condition.get("evaluator")
        expected = condition.get("expected_value")
        if evaluator == "FILE_SHA256_EQUALS":
            _require(expected == observed["sha256"], "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
        elif evaluator == "CHANNEL_RECORD_EXISTS":
            _require(observed["bytes"] > 0, "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
        else:
            pointer = condition.get("json_pointer")
            _require(isinstance(pointer, str) and pointer.startswith("/"), "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
            current: Any = subject
            try:
                for part in pointer[1:].split("/"):
                    token = part.replace("~1", "/").replace("~0", "~")
                    current = current[int(token)] if isinstance(current, list) else current[token]
            except (KeyError, IndexError, TypeError, ValueError):
                _fail("OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
            _require(current == expected, "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
            if evaluator == "TEST_REPORT_PASS":
                _require(expected == "PASS", "OBJECTIVE_TERMINAL_CONDITION_UNPROVABLE")
    _require(objective_binding.get("sha256") is not None, "OBJECTIVE_BINDING_REQUIRED")


def _validate_autonomy_operations(autonomy: dict[str, Any]) -> list[dict[str, Any]]:
    operations = autonomy.get("authorized_operations")
    _require(isinstance(operations, list) and operations, "AUTONOMY_OPERATION_BINDING_REQUIRED")
    action_ids = [item.get("action_id") for item in operations if isinstance(item, dict)]
    idempotency_keys = [item.get("idempotency_key") for item in operations if isinstance(item, dict)]
    _require(len(action_ids) == len(operations), "AUTONOMY_OPERATION_BINDING_REQUIRED")
    _require(len(set(action_ids)) == len(action_ids), "AUTONOMY_OPERATION_BINDING_REQUIRED")
    _require(len(set(idempotency_keys)) == len(idempotency_keys), "AUTONOMY_OPERATION_BINDING_REQUIRED")
    _require(set(action_ids) == set(autonomy.get("authorized_action_ids", [])), "AUTONOMY_OPERATION_BINDING_REQUIRED")
    _require(
        {item["effect"] for item in operations} == set(autonomy.get("authorized_actions", [])),
        "AUTONOMY_OPERATION_BINDING_REQUIRED",
    )
    operation_targets = {
        _canonical_effect_path(item["target_path"], "EXECUTION_TARGET_UNAUTHORIZED")
        for item in operations
    }
    operation_outputs = {
        _canonical_effect_path(item["output_path"], "EXECUTION_OUTPUT_UNAUTHORIZED")
        for item in operations
    }
    authority_targets = {
        _canonical_effect_path(item, "EXECUTION_TARGET_UNAUTHORIZED")
        for item in autonomy.get("authorized_target_paths", [])
    }
    authority_outputs = {
        _canonical_effect_path(item, "EXECUTION_OUTPUT_UNAUTHORIZED")
        for item in autonomy.get("authorized_output_paths", [])
    }
    _require(operation_targets == authority_targets, "AUTONOMY_OPERATION_BINDING_REQUIRED")
    _require(operation_outputs == authority_outputs, "AUTONOMY_OPERATION_BINDING_REQUIRED")
    return operations


def _read_kill_switch(
    arm: dict[str, Any], *, trusted_root: Path, issuer_id: str,
    require_initial_binding: bool = False,
) -> dict[str, Any]:
    switch = arm.get("kill_switch")
    _require(isinstance(switch, dict), "KILL_SWITCH_BINDING_REQUIRED")
    binding = switch.get("initial_binding")
    _require(isinstance(binding, dict) and binding.get("path") == switch.get("path"), "KILL_SWITCH_BINDING_REQUIRED")
    try:
        raw, physical = read_bound_bytes(switch["path"], label="KILL_SWITCH")
        value = strict_json(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, PathSafetyError) as error:
        _fail("KILL_SWITCH_BINDING_REQUIRED", decision="INCONCLUSIVE", detail=type(error).__name__)
    _require(isinstance(value, dict) and verify_record(value), "KILL_SWITCH_BINDING_REQUIRED")
    observed_binding = _binding(physical, raw)
    try:
        physical.relative_to(trusted_root)
    except ValueError:
        _fail("KILL_SWITCH_BINDING_REQUIRED")
    initial_generation = switch.get("initial_generation")
    _require(
        isinstance(initial_generation, int) and not isinstance(initial_generation, bool)
        and initial_generation >= 1,
        "KILL_SWITCH_BINDING_REQUIRED",
    )
    if require_initial_binding:
        _require(_same_binding(binding, observed_binding), "KILL_SWITCH_BINDING_REQUIRED")
    _require(value.get("schema") == "omni-kill-switch-v1", "KILL_SWITCH_BINDING_REQUIRED")
    _require(value.get("task_id") == arm.get("task_id") and value.get("program_id") == arm.get("program_id"), "KILL_SWITCH_BINDING_REQUIRED")
    if value.get("state") == switch.get("open_token"):
        _fail("KILL_SWITCH_OPEN")
    _require(value.get("state") == switch.get("closed_token"), "KILL_SWITCH_BINDING_REQUIRED")
    generation = value.get("generation")
    _require(
        isinstance(generation, int) and not isinstance(generation, bool),
        "KILL_SWITCH_BINDING_REQUIRED",
    )
    if _same_binding(binding, observed_binding):
        _require(generation == initial_generation, "KILL_SWITCH_BINDING_REQUIRED")
    else:
        _require(generation > initial_generation, "KILL_SWITCH_RECLOSE_AUTHORITY_REQUIRED")
        receipt, receipt_binding = _read_trusted_record(
            value.get("reclose_authority_binding"), trusted_root=trusted_root,
            issuer_id=issuer_id, code="KILL_SWITCH_RECLOSE_AUTHORITY_REQUIRED",
        )
        expected = {
            "schema": "omni-kill-switch-reclose-pm-authority-v1",
            "status": "AUTHORIZED", "decision": "AUTHORIZED",
            "issuer_id": issuer_id, "task_id": arm.get("task_id"),
            "program_id": arm.get("program_id"),
            "subject_session_id": arm.get("subject_session_id"),
            "kill_switch_path": str(physical),
            "initial_binding": binding,
            "previous_generation": generation - 1,
            "authorized_generation": generation,
            "one_shot": True,
        }
        _require(set(receipt) == set(expected) | {"record_digest"}, "KILL_SWITCH_RECLOSE_AUTHORITY_REQUIRED")
        for field, expected_value in expected.items():
            _require(receipt.get(field) == expected_value, "KILL_SWITCH_RECLOSE_AUTHORITY_REQUIRED", detail=field)
        _require(receipt_binding == value.get("reclose_authority_binding"), "KILL_SWITCH_RECLOSE_AUTHORITY_REQUIRED")
    return value


def _validate_physical_sentinels(
    bundle: dict[str, Any], arm: dict[str, Any], objective: dict[str, Any],
    arm_binding: dict[str, Any], *, create_registry: bool = False, root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    _require(bundle.get("decision") == "PASS" and bundle.get("status") == "SENTINEL_BUNDLE_PASS", "SENTINEL_REHYDRATION_FAIL")
    _require(bundle.get("all_physical") is True and bundle.get("rehydration_complete") is True, "SENTINEL_REHYDRATION_FAIL")
    _require(bundle.get("grants_authority") is False, "AUTONOMY_SCOPE_MISMATCH")
    _require(_same_binding(bundle.get("arm_authority_binding"), arm_binding), "ARM_AUTOMATION_SCOPE_MISMATCH")
    now = _utc_now()
    bundle_observed = _parse_datetime(bundle.get("observed_at"), "SENTINEL_FRESHNESS_EXPIRED")
    bundle_expires = _parse_datetime(bundle.get("expires_at"), "SENTINEL_FRESHNESS_EXPIRED")
    _require(bundle_observed <= now < bundle_expires, "SENTINEL_FRESHNESS_EXPIRED")
    expected = {"agentic": "AGENTIC", "script": "SCRIPT", "context": "CONTEXT"}
    physical_values: dict[str, dict[str, Any]] = {}
    for key, kind in expected.items():
        item = bundle.get("sentinels", {}).get(key, {})
        code = {"agentic": "SENTINEL_AGENTIC_NOT_READY", "script": "SENTINEL_SCRIPT_NOT_READY", "context": "SENTINEL_CONTEXT_NOT_READY"}[key]
        _require(item.get("kind") == kind and item.get("rehydrated") is True, code)
        _require(item.get("owner_session_id") == arm.get("subject_session_id"), code)
        _require(item.get("grants_authority") is False, "AUTONOMY_SCOPE_MISMATCH")
        _require(_same_binding(item.get("arm_authority_binding"), arm_binding), "ARM_AUTOMATION_SCOPE_MISMATCH")
        physical, _ = _read_untyped_binding(item.get("physical_receipt_binding"), code)
        _require(physical.get("task_id") == arm.get("task_id") and physical.get("program_id") == arm.get("program_id"), code)
        _require(physical.get("owner_session_id") == arm.get("subject_session_id"), code)
        _require(physical.get("grants_authority") is False, "AUTONOMY_SCOPE_MISMATCH")
        _require(physical.get("sentinel_id") == item.get("sentinel_id") and physical.get("generation") == item.get("generation"), code)
        heartbeat_seq = physical.get("heartbeat_seq")
        _require(
            isinstance(heartbeat_seq, int) and not isinstance(heartbeat_seq, bool)
            and heartbeat_seq >= 1 and heartbeat_seq == item.get("heartbeat_seq"),
            "SENTINEL_HEARTBEAT_STALE",
        )
        observed = _parse_datetime(physical.get("observed_at"), "SENTINEL_FRESHNESS_EXPIRED")
        expires = _parse_datetime(physical.get("expires_at"), "SENTINEL_FRESHNESS_EXPIRED")
        _require(
            item.get("observed_at") == physical.get("observed_at")
            and item.get("expires_at") == physical.get("expires_at"),
            "SENTINEL_FRESHNESS_EXPIRED",
        )
        _require(observed <= now < expires <= bundle_expires, "SENTINEL_FRESHNESS_EXPIRED")
        _require(physical.get("dead_man_state") == "ARMED", "SENTINEL_DEAD_MAN_NOT_ARMED")
        physical_values[key] = physical
    agentic = physical_values["agentic"]
    expected_agentic = arm["agentic_sentinel"]
    _require(agentic.get("schema") == "omni-agentic-sentinel-physical-receipt-v1" and agentic.get("state") == "ARMED", "SENTINEL_AGENTIC_NOT_READY")
    _require(agentic.get("sentinel_id") == expected_agentic["sentinel_id"] and agentic.get("generation") == expected_agentic["generation"], "SENTINEL_AGENTIC_NOT_READY")
    _require(agentic.get("objective_id") == objective.get("objective_id") == expected_agentic["objective_id"], "SENTINEL_AGENTIC_NOT_READY")
    script = physical_values["script"]
    supervisor = arm["script_supervisor"]
    _require(script.get("schema") == "omni-script-sentinel-physical-receipt-v1" and script.get("state") == "CHILD_RUNNING", "SENTINEL_SCRIPT_NOT_READY")
    _require(script.get("namespace") == supervisor["namespace"], "SUPERVISOR_NAMESPACE_COLLISION")
    _require(script.get("generation") == supervisor["generation"], "SUPERVISOR_GENERATION_STALE")
    _require(script.get("arm_authority_id") == arm.get("authority_id"), "SUPERVISOR_ARM_AUTHORITY_MISSING")
    remaining = script.get("rearm_budget_remaining")
    _require(
        isinstance(remaining, int) and not isinstance(remaining, bool)
        and 0 < remaining <= supervisor["rearm_budget"],
        "SUPERVISOR_BUDGET_EXHAUSTED",
    )
    _require(
        script.get("heartbeat_interval_seconds") == supervisor["heartbeat_interval_seconds"]
        and script.get("max_missed_heartbeats") == supervisor["max_missed_heartbeats"],
        "SENTINEL_HEARTBEAT_STALE",
    )
    last_heartbeat = _parse_datetime(script.get("last_heartbeat_at"), "SENTINEL_HEARTBEAT_STALE")
    deadline = last_heartbeat + dt.timedelta(
        seconds=supervisor["heartbeat_interval_seconds"] * supervisor["max_missed_heartbeats"]
    )
    _require(last_heartbeat <= now < deadline, "SENTINEL_HEARTBEAT_STALE")
    _require(_parse_datetime(script["expires_at"], "SENTINEL_FRESHNESS_EXPIRED") <= deadline, "SENTINEL_HEARTBEAT_STALE")
    context = physical_values["context"]
    expected_context = arm["context_sentinel"]
    _require(context.get("schema") == "omni-context-sentinel-physical-receipt-v1" and context.get("state") == "HEALTHY", "SENTINEL_CONTEXT_NOT_READY")
    _require(context.get("sentinel_id") == expected_context["sentinel_id"] and context.get("generation") == expected_context["generation"], "SENTINEL_CONTEXT_NOT_READY")
    denominator = context.get("denominator")
    _require(isinstance(denominator, int) and denominator > 0 and denominator == expected_context["denominator"], "HOST_CONTEXT_DENOMINATOR_UNKNOWN")
    _require(0 < expected_context["warn_threshold"] < expected_context["rotate_threshold"] <= denominator, "HOST_CONTEXT_DENOMINATOR_UNKNOWN")
    _require(
        context.get("warn_threshold") == expected_context["warn_threshold"]
        and context.get("rotate_threshold") == expected_context["rotate_threshold"],
        "HOST_CONTEXT_THRESHOLD_MISMATCH",
    )
    if create_registry:
        _require(root is not None, "SUPERVISOR_NAMESPACE_COLLISION", decision="INCONCLUSIVE")
        registry = {
            "schema": "omni-supervisor-namespace-registration-v1", "status": "REGISTERED",
            "task_id": arm["task_id"], "program_id": arm["program_id"],
            "namespace": supervisor["namespace"], "generation": supervisor["generation"],
            "owner_session_id": arm["subject_session_id"], "arm_authority_id": arm["authority_id"],
        }
        _write_create_once(_supervisor_path(root, supervisor["namespace"]), registry, root, "SUPERVISOR_NAMESPACE_COLLISION")
    return physical_values


def _validate_fencing(
    binding: dict[str, Any], *, task_id: str, program_id: str,
    predecessor_session_id: str, successor_session_id: str,
) -> None:
    value, _ = _read_untyped_binding(binding, "PREDECESSOR_WAKEUP_UNFENCED")
    _require(value.get("schema") == "omni-predecessor-fencing-receipt-v1" and value.get("status") == "QUIESCENT", "PREDECESSOR_WAKEUP_UNFENCED")
    _require(value.get("task_id") == task_id and value.get("program_id") == program_id, "PREDECESSOR_WAKEUP_UNFENCED")
    _require(value.get("predecessor_session_id") == predecessor_session_id and value.get("successor_session_id") == successor_session_id, "PREDECESSOR_WAKEUP_UNFENCED")
    classes = value.get("fenced_control_classes")
    _require(
        isinstance(classes, dict)
        and set(classes) == set(FENCED_CLASSES)
        and all(classes.get(item) is True for item in FENCED_CLASSES),
        "PREDECESSOR_WAKEUP_UNFENCED",
    )


def activate_autonomous(
    *, state_path: str | Path, state_sha256: str, objective_path: str | Path,
    objective_sha256: str, autonomy_authority_path: str | Path,
    autonomy_authority_sha256: str, arm_authority_path: str | Path,
    arm_authority_sha256: str, sentinel_bundle_path: str | Path,
    sentinel_bundle_sha256: str, predecessor_fencing_path: str | Path,
    predecessor_fencing_sha256: str, predecessor_session_id: str,
    state_root: str | Path, trusted_pm_root: str | Path,
    trusted_pm_issuer_id: str,
) -> dict[str, Any]:
    root = _state_root(state_root)
    _prepare_operating_dirs(root)
    state, state_file = _load_state(state_path, state_sha256, root)
    pm_root, pm_issuer = _require_external_trust(
        state, trusted_pm_root, trusted_pm_issuer_id, root
    )
    _ensure_latest(state, root, "EXECUTION_LEASE_GENERATION_STALE")
    _require(state.get("status") == "REGIME_BOUND" and state.get("regime") == "AUTONOMOUS", "OPERATING_REGIME_INVALID")
    objective, objective_file = _read_record(
        objective_path, objective_sha256, code="OBJECTIVE_BINDING_REQUIRED",
        expected_schema="omni-persistent-objective-v1", schema_validate=False,
    )
    autonomy, autonomy_file = _read_record(
        autonomy_authority_path, autonomy_authority_sha256,
        code="AUTONOMY_AUTHORITY_REQUIRED", expected_schema="omni-autonomy-authority-v1",
        schema_validate=False,
    )
    arm, arm_file = _read_record(
        arm_authority_path, arm_authority_sha256,
        code="ARM_AUTOMATION_AUTHORITY_REQUIRED", expected_schema="omni-automation-arm-authority-v1",
        schema_validate=False,
    )
    bundle, bundle_file = _read_record(
        sentinel_bundle_path, sentinel_bundle_sha256,
        code="SENTINEL_REHYDRATION_FAIL", expected_schema="omni-sentinel-bundle-receipt-v1",
        schema_validate=False,
    )
    fencing, fencing_file = _read_record(
        predecessor_fencing_path, predecessor_fencing_sha256,
        code="PREDECESSOR_WAKEUP_UNFENCED", schema_validate=False,
    )
    regime, regime_file = _read_untyped_binding(state["regime_binding"], "OPERATING_REGIME_BINDING_REQUIRED")
    _require(autonomy.get("automation_authorized") is False, "AUTONOMY_DOES_NOT_IMPLY_ARM_AUTOMATION")
    _schema_validate(autonomy, "AUTONOMY_AUTHORITY_REQUIRED")
    _validate_autonomy_operations(autonomy)
    context_authority = arm.get("context_sentinel", {})
    denominator = context_authority.get("denominator")
    _require(isinstance(denominator, int) and not isinstance(denominator, bool) and denominator > 0, "HOST_CONTEXT_DENOMINATOR_UNKNOWN")
    _require(
        isinstance(context_authority.get("warn_threshold"), int)
        and isinstance(context_authority.get("rotate_threshold"), int)
        and 0 < context_authority["warn_threshold"] < context_authority["rotate_threshold"] <= denominator,
        "HOST_CONTEXT_DENOMINATOR_UNKNOWN",
    )
    _schema_validate(arm, "ARM_AUTOMATION_AUTHORITY_REQUIRED")
    _validate_objective(objective, objective_file)
    _schema_validate(objective, "OBJECTIVE_BINDING_REQUIRED")
    _validate_pm_authority(
        objective, trusted_root=pm_root, issuer_id=pm_issuer,
        authority_kind="OBJECTIVE", subject_id=objective["objective_id"],
        code="OBJECTIVE_PM_AUTHORITY_REQUIRED",
    )
    _validate_pm_authority(
        autonomy, trusted_root=pm_root, issuer_id=pm_issuer,
        authority_kind="AUTONOMY", subject_id=autonomy["authority_id"],
        code="AUTONOMY_AUTHORITY_REQUIRED",
    )
    _validate_pm_authority(
        arm, trusted_root=pm_root, issuer_id=pm_issuer,
        authority_kind="ARM_AUTOMATION", subject_id=arm["authority_id"],
        code="ARM_AUTOMATION_AUTHORITY_REQUIRED",
    )
    _require(bundle.get("decision") == "PASS" and bundle.get("status") == "SENTINEL_BUNDLE_PASS", "SENTINEL_REHYDRATION_FAIL")
    _schema_validate(bundle, "SENTINEL_REHYDRATION_FAIL")
    _check_scope(state, objective, autonomy, arm, bundle, code="AUTONOMY_SCOPE_MISMATCH")
    _require(_same_binding(objective.get("program_countersign_binding"), state["program_countersign_binding"]), "OBJECTIVE_BINDING_REQUIRED")
    _require(_same_binding(autonomy.get("operating_binding"), regime_file), "AUTONOMY_SCOPE_MISMATCH")
    _require(_same_binding(autonomy.get("fused_program_binding"), state["fused_program_binding"]), "AUTONOMY_SCOPE_MISMATCH")
    _require(_same_binding(autonomy.get("program_countersign_binding"), state["program_countersign_binding"]), "AUTONOMY_SCOPE_MISMATCH")
    _require(_same_binding(autonomy.get("objective_binding"), objective_file), "AUTONOMY_SCOPE_MISMATCH")
    _require(autonomy.get("subject_session_id") == state.get("owner_session_id"), "AUTONOMY_SCOPE_MISMATCH")
    _require(_same_binding(arm.get("operating_binding"), regime_file), "ARM_AUTOMATION_SCOPE_MISMATCH")
    _require(_same_binding(arm.get("autonomy_authority_binding"), autonomy_file), "ARM_AUTOMATION_SCOPE_MISMATCH")
    _require(_same_binding(arm.get("objective_binding"), objective_file), "ARM_AUTOMATION_SCOPE_MISMATCH")
    _require(arm.get("subject_session_id") == state.get("owner_session_id"), "ARM_AUTOMATION_SCOPE_MISMATCH")
    objective_budget = objective["budgets"]
    autonomy_budget = autonomy["budgets"]
    for key in ("max_turns", "max_tool_calls", "max_writes", "max_elapsed_seconds"):
        _require(autonomy_budget[key] <= objective_budget[key], "AUTONOMY_SCOPE_MISMATCH", detail=key)
    _require(arm["script_supervisor"]["rearm_budget"] <= objective_budget["max_rearms"], "SUPERVISOR_BUDGET_EXHAUSTED")
    kill_switch = _read_kill_switch(
        arm, trusted_root=pm_root, issuer_id=pm_issuer,
        require_initial_binding=True,
    )
    physical = _validate_physical_sentinels(
        bundle, arm, objective, arm_file, create_registry=False
    )
    _validate_fencing(
        fencing_file, task_id=state["task_id"], program_id=state["program_id"],
        predecessor_session_id=predecessor_session_id,
        successor_session_id=state["owner_session_id"],
    )
    # Consume both distinct authorities before publishing any lease. Identical
    # retries are idempotent; a nonce with different bytes is a replay.
    _consume_nonce(root, autonomy["activation_nonce"], "ACTIVATE_AUTONOMY", _fingerprint(state, objective, autonomy))
    _consume_nonce(root, arm["arm_nonce"], "ARM_AUTOMATION", _fingerprint(state, objective, autonomy, arm, bundle))
    _validate_physical_sentinels(bundle, arm, objective, arm_file, create_registry=True, root=root)
    seq = int(state["state_seq"]) + 1
    generation = int(autonomy["authority_generation"])
    expected_lease_path = _lease_path(root, generation)
    expected_state_path = _state_path(root, seq)
    lease = {
        "schema": "omni-execution-lease-v1", "status": "EXECUTION_LEASE_PREPARED",
        "lease_id": f"{state['task_id']}.LEASE.{generation}", "task_id": state["task_id"],
        "program_id": state["program_id"], "regime_binding": regime_file,
        "objective_binding": objective_file, "autonomy_authority_binding": autonomy_file,
        "arm_authority_binding": arm_file, "sentinel_bundle_binding": bundle_file,
        "owner_role": "BUILDER", "owner_session_id": state["owner_session_id"],
        "predecessor_session_id": predecessor_session_id,
        "predecessor_fencing_receipt_binding": fencing_file,
        "fenced_control_classes": FENCED_CLASSES, "generation": generation,
        "fencing_token": sha256_bytes(canonical_json([state["task_id"], generation, autonomy["activation_nonce"]]).encode("utf-8")),
        "previous_lease_binding": None, "single_writer": True,
        "scope": ["F3_BUILD", "F4_TEST"], "grants": ["F3_BUILD", "F4_TEST"],
        "authorized_operations": autonomy["authorized_operations"],
        "authorized_target_paths": autonomy["authorized_target_paths"],
        "authorized_output_paths": autonomy["authorized_output_paths"],
        "trusted_pm_root": str(pm_root), "trusted_pm_issuer_id": pm_issuer,
        "non_grants": ["SENTINEL_AUTHORITY", "F5_DELIVERY", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS"],
        "activation_state_path": str(expected_state_path.resolve(strict=False)),
        "created_at": autonomy["created_at"],
    }
    lease_binding = _write_create_once(expected_lease_path, lease, root, "DUAL_WRITER")
    started_ms = int(time.time() * 1000)
    initial_rearms = arm["script_supervisor"]["rearm_budget"] - physical["script"]["rearm_budget_remaining"]
    budget = {
        "max_turns": autonomy_budget["max_turns"], "max_tool_calls": autonomy_budget["max_tool_calls"],
        "max_writes": autonomy_budget["max_writes"], "max_elapsed_seconds": autonomy_budget["max_elapsed_seconds"],
        "max_rearms": arm["script_supervisor"]["rearm_budget"], "used_turns": 0,
        "used_tool_calls": 0, "used_writes": 0, "used_elapsed_seconds": 0,
        "used_rearms": initial_rearms, "started_at_unix_ms": started_ms,
        "last_checked_at_unix_ms": started_ms,
    }
    next_state = {
        **{key: value for key, value in state.items() if key != "record_digest"},
        "status": "AUTONOMY_ACTIVE", "state_id": f"{regime['binding_id']}.STATE.{seq}",
        "state_seq": seq, "previous_state_binding": state_file,
        "objective_binding": objective_file, "autonomy_authority_binding": autonomy_file,
        "arm_authority_binding": arm_file, "sentinel_bundle_binding": bundle_file,
        "execution_lease_binding": lease_binding,
        "authorized_effects": autonomy["authorized_actions"], "effects_authorized": True,
        "automation_armed": True, "single_writer": True, "budget_snapshot": budget,
        "kill_switch_path": arm["kill_switch"]["path"],
        "kill_switch_generation": kill_switch["generation"],
        "official_channel_binding": regime["pm_channel_record_binding"],
        "last_effect": None,
        "created_at": autonomy["created_at"],
    }
    state_binding = _write_create_once(expected_state_path, next_state, root, "DUAL_WRITER")
    return {"status": "AUTONOMY_ACTIVE", "state_binding": state_binding, "lease_binding": lease_binding, "effects_authorized": True, "automation_armed": True}


def _walk_state_chain(
    state: dict[str, Any], state_binding: dict[str, Any], root: Path,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    chain: list[tuple[dict[str, Any], dict[str, Any]]] = []
    current, current_binding = state, state_binding
    for _ in range(MAX_STATE_CHAIN + 1):
        seq = int(current["state_seq"])
        _require(
            Path(current_binding["path"]) == _state_path(root, seq).resolve(strict=True),
            "OPERATING_STATE_CHAIN_INVALID",
        )
        chain.append((current, current_binding))
        previous_binding = current.get("previous_state_binding")
        if seq == 0:
            _require(previous_binding is None, "OPERATING_STATE_CHAIN_INVALID")
            return chain
        _require(isinstance(previous_binding, dict), "OPERATING_STATE_CHAIN_INVALID")
        previous, observed = _read_untyped_binding(previous_binding, "OPERATING_STATE_CHAIN_INVALID")
        _require(observed == previous_binding, "OPERATING_STATE_CHAIN_INVALID")
        _schema_validate(previous, "OPERATING_STATE_CHAIN_INVALID")
        _require(int(previous.get("state_seq", -1)) == seq - 1, "OPERATING_STATE_CHAIN_INVALID")
        for field in (
            "task_id", "program_id", "knowledge_pipeline_id", "regime",
            "owner_session_id", "session_pair_sha256", "trusted_pm_root",
            "trusted_pm_issuer_id",
        ):
            _require(previous.get(field) == state.get(field), "OPERATING_STATE_CHAIN_INVALID", detail=field)
        current, current_binding = previous, observed
    _fail("OPERATING_STATE_CHAIN_INVALID", detail="chain bound exceeded")


def _validate_budget_snapshot(budget: object) -> dict[str, int]:
    _require(isinstance(budget, dict), "OPERATING_BUDGET_INVALID")
    pairs = (
        ("turns", "max_turns", "used_turns"),
        ("tool_calls", "max_tool_calls", "used_tool_calls"),
        ("writes", "max_writes", "used_writes"),
        ("elapsed_seconds", "max_elapsed_seconds", "used_elapsed_seconds"),
        ("rearms", "max_rearms", "used_rearms"),
    )
    for _name, maximum, used in pairs:
        _require(
            isinstance(budget.get(maximum), int) and not isinstance(budget.get(maximum), bool)
            and isinstance(budget.get(used), int) and not isinstance(budget.get(used), bool)
            and 0 <= budget[used] <= budget[maximum],
            "OPERATING_BUDGET_INVALID",
            detail=used,
        )
    started = budget.get("started_at_unix_ms")
    checked = budget.get("last_checked_at_unix_ms")
    _require(
        isinstance(started, int) and not isinstance(started, bool)
        and isinstance(checked, int) and not isinstance(checked, bool)
        and 0 < started <= checked,
        "OPERATING_BUDGET_INVALID",
    )
    return budget


def _validate_active_state_chain(
    chain: list[tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    """Prove that every autonomous checkpoint advances one immutable budget."""
    _require(bool(chain), "OPERATING_STATE_CHAIN_INVALID")
    oldest = chain[-1][0]
    _require(
        oldest.get("status") == "REGIME_BOUND"
        and oldest.get("state_seq") == 0
        and oldest.get("last_effect") is None,
        "OPERATING_STATE_CHAIN_INVALID",
    )
    previous: dict[str, Any] | None = None
    seen_idempotency: set[str] = set()
    maximums = (
        "max_turns", "max_tool_calls", "max_writes",
        "max_elapsed_seconds", "max_rearms", "started_at_unix_ms",
    )
    for record, _binding_value in reversed(chain):
        if record.get("status") == "REGIME_BOUND":
            _require(previous is None, "OPERATING_STATE_CHAIN_INVALID")
            continue
        _require(record.get("status") == "AUTONOMY_ACTIVE", "OPERATING_STATE_CHAIN_INVALID")
        budget = _validate_budget_snapshot(record.get("budget_snapshot"))
        generation = record.get("kill_switch_generation")
        _require(
            isinstance(generation, int) and not isinstance(generation, bool)
            and generation >= 1,
            "KILL_SWITCH_GENERATION_ROLLBACK",
        )
        if previous is None:
            _require(
                budget["used_turns"] == 0
                and budget["used_tool_calls"] == 0
                and budget["used_writes"] == 0
                and budget["used_elapsed_seconds"] == 0
                and record.get("last_effect") is None,
                "OPERATING_BUDGET_ROLLBACK",
            )
        else:
            older_budget = _validate_budget_snapshot(previous.get("budget_snapshot"))
            for field in maximums:
                _require(budget[field] == older_budget[field], "OPERATING_BUDGET_ROLLBACK", detail=field)
            _require(budget["used_turns"] == older_budget["used_turns"] + 1, "OPERATING_BUDGET_ROLLBACK", detail="used_turns")
            _require(budget["used_tool_calls"] == older_budget["used_tool_calls"] + 1, "OPERATING_BUDGET_ROLLBACK", detail="used_tool_calls")
            effect = record.get("last_effect")
            _require(isinstance(effect, dict), "OPERATING_STATE_CHAIN_INVALID")
            write_delta = 1 if effect.get("effect") in EFFECT_WRITE_CLASSES else 0
            _require(budget["used_writes"] == older_budget["used_writes"] + write_delta, "OPERATING_BUDGET_ROLLBACK", detail="used_writes")
            _require(budget["used_elapsed_seconds"] >= older_budget["used_elapsed_seconds"], "OPERATING_BUDGET_ROLLBACK", detail="used_elapsed_seconds")
            _require(budget["used_rearms"] >= older_budget["used_rearms"], "OPERATING_BUDGET_ROLLBACK", detail="used_rearms")
            _require(budget["last_checked_at_unix_ms"] >= older_budget["last_checked_at_unix_ms"], "BUDGET_CLOCK_ROLLBACK")
            _require(generation >= previous.get("kill_switch_generation", 0), "KILL_SWITCH_GENERATION_ROLLBACK")
            key = effect.get("idempotency_key")
            _require(isinstance(key, str) and key not in seen_idempotency, "OPERATING_AUTHORITY_REPLAY")
            seen_idempotency.add(key)
        previous = record


def _verify_active_state(
    state: dict[str, Any], state_binding: dict[str, Any], root: Path,
    *, trusted_pm_root: str | Path, trusted_pm_issuer_id: str,
) -> dict[str, Any]:
    pm_root, pm_issuer = _require_external_trust(
        state, trusted_pm_root, trusted_pm_issuer_id, root
    )
    _ensure_latest(state, root, "EXECUTION_LEASE_GENERATION_STALE")
    chain = _walk_state_chain(state, state_binding, root)
    _validate_active_state_chain(chain)
    lease_binding = state.get("execution_lease_binding")
    _require(isinstance(lease_binding, dict), "EXECUTION_LEASE_REQUIRED")
    lease, observed_lease = _read_untyped_binding(lease_binding, "EXECUTION_LEASE_REQUIRED")
    _require(observed_lease == lease_binding and lease.get("schema") == "omni-execution-lease-v1", "EXECUTION_LEASE_REQUIRED")
    _schema_validate(lease, "EXECUTION_LEASE_REQUIRED")
    _require(lease.get("owner_session_id") == state.get("owner_session_id"), "EXECUTION_LEASE_OWNER_MISMATCH")
    _require(
        lease.get("activation_state_path") in {item[1]["path"] for item in chain},
        "EXECUTION_LEASE_GENERATION_STALE",
    )
    _require(Path(lease_binding["path"]) == _lease_path(root, int(lease["generation"])).resolve(strict=True), "EXECUTION_LEASE_GENERATION_STALE")
    _validate_fencing(
        lease["predecessor_fencing_receipt_binding"], task_id=state["task_id"],
        program_id=state["program_id"], predecessor_session_id=lease["predecessor_session_id"],
        successor_session_id=state["owner_session_id"],
    )
    arm, arm_binding = _read_untyped_binding(state["arm_authority_binding"], "ARM_AUTOMATION_AUTHORITY_REQUIRED")
    autonomy, autonomy_binding = _read_untyped_binding(state["autonomy_authority_binding"], "AUTONOMY_AUTHORITY_REQUIRED")
    objective, objective_binding = _read_untyped_binding(state["objective_binding"], "OBJECTIVE_BINDING_REQUIRED")
    bundle, _ = _read_untyped_binding(state["sentinel_bundle_binding"], "SENTINEL_REHYDRATION_FAIL")
    _validate_pm_authority(
        objective, trusted_root=pm_root, issuer_id=pm_issuer,
        authority_kind="OBJECTIVE", subject_id=objective["objective_id"],
        code="OBJECTIVE_PM_AUTHORITY_REQUIRED",
    )
    _validate_pm_authority(
        autonomy, trusted_root=pm_root, issuer_id=pm_issuer,
        authority_kind="AUTONOMY", subject_id=autonomy["authority_id"],
        code="AUTONOMY_AUTHORITY_REQUIRED",
    )
    _validate_pm_authority(
        arm, trusted_root=pm_root, issuer_id=pm_issuer,
        authority_kind="ARM_AUTOMATION", subject_id=arm["authority_id"],
        code="ARM_AUTOMATION_AUTHORITY_REQUIRED",
    )
    _require(_same_binding(autonomy.get("objective_binding"), objective_binding), "AUTONOMY_SCOPE_MISMATCH")
    _require(_same_binding(arm.get("autonomy_authority_binding"), autonomy_binding), "ARM_AUTOMATION_SCOPE_MISMATCH")
    _schema_validate(autonomy, "AUTONOMY_AUTHORITY_REQUIRED")
    _validate_autonomy_operations(autonomy)
    _require(state.get("authorized_effects") == autonomy.get("authorized_actions"), "AUTONOMY_SCOPE_MISMATCH")
    _require(
        state.get("effects_authorized") is True
        and state.get("automation_armed") is True
        and state.get("single_writer") is True,
        "AUTONOMY_SCOPE_MISMATCH",
    )
    _require(_same_binding(lease.get("regime_binding"), state["regime_binding"]), "EXECUTION_LEASE_GENERATION_STALE")
    _require(_same_binding(lease.get("objective_binding"), objective_binding), "EXECUTION_LEASE_GENERATION_STALE")
    _require(_same_binding(lease.get("autonomy_authority_binding"), autonomy_binding), "EXECUTION_LEASE_GENERATION_STALE")
    _require(_same_binding(lease.get("arm_authority_binding"), arm_binding), "EXECUTION_LEASE_GENERATION_STALE")
    _require(_same_binding(lease.get("sentinel_bundle_binding"), state["sentinel_bundle_binding"]), "EXECUTION_LEASE_GENERATION_STALE")
    _require(lease.get("generation") == autonomy.get("authority_generation"), "EXECUTION_LEASE_GENERATION_STALE")
    kill_switch = _read_kill_switch(arm, trusted_root=pm_root, issuer_id=pm_issuer)
    _require(
        kill_switch.get("generation") >= state.get("kill_switch_generation", 0),
        "KILL_SWITCH_GENERATION_ROLLBACK",
    )
    physical = _validate_physical_sentinels(bundle, arm, objective, arm_binding)
    budget = _validate_budget_snapshot(state.get("budget_snapshot"))
    for field in ("max_turns", "max_tool_calls", "max_writes", "max_elapsed_seconds"):
        _require(budget[field] == autonomy["budgets"][field], "OPERATING_BUDGET_INVALID", detail=field)
    _require(budget["max_rearms"] == arm["script_supervisor"]["rearm_budget"], "OPERATING_BUDGET_INVALID", detail="max_rearms")
    now_ms = int(time.time() * 1000)
    _require(now_ms >= budget["last_checked_at_unix_ms"], "BUDGET_CLOCK_ROLLBACK")
    elapsed = math.ceil((now_ms - budget["started_at_unix_ms"]) / 1000)
    _require(elapsed <= budget["max_elapsed_seconds"], "OPERATING_BUDGET_EXHAUSTED")
    physical_used_rearms = budget["max_rearms"] - physical["script"]["rearm_budget_remaining"]
    _require(
        budget["used_rearms"] <= physical_used_rearms <= budget["max_rearms"],
        "SUPERVISOR_BUDGET_ROLLBACK",
    )
    _require(lease.get("trusted_pm_root") == str(pm_root), "TRUSTED_PM_ROOT_REQUIRED")
    _require(lease.get("trusted_pm_issuer_id") == pm_issuer, "TRUSTED_PM_ISSUER_REQUIRED")
    _require(lease.get("authorized_target_paths") == autonomy.get("authorized_target_paths"), "AUTONOMY_SCOPE_MISMATCH")
    _require(lease.get("authorized_output_paths") == autonomy.get("authorized_output_paths"), "AUTONOMY_SCOPE_MISMATCH")
    _require(lease.get("authorized_operations") == autonomy.get("authorized_operations"), "AUTONOMY_SCOPE_MISMATCH")
    return {
        "pm_root": pm_root, "pm_issuer": pm_issuer, "arm": arm,
        "autonomy": autonomy, "objective": objective, "physical": physical,
        "kill_switch": kill_switch,
        "budget": budget, "now_ms": now_ms, "elapsed": elapsed,
    }


def _canonical_effect_path(value: object, code: str) -> str:
    _require(isinstance(value, (str, Path)), code)
    try:
        return str(absolute_physical_path(value, code, strict=False))
    except PathSafetyError as error:
        _fail(code, detail=str(error))


def _effect_fingerprint(
    *, effect: str, actor_session_id: str, action_id: str,
    target_path: str, output_path: str, idempotency_key: str,
) -> str:
    return sha256_bytes(
        canonical_json({
            "effect": effect, "actor_session_id": actor_session_id,
            "action_id": action_id, "target_path": target_path,
            "output_path": output_path, "idempotency_key": idempotency_key,
        }).encode("utf-8")
    )


def _scan_effect_consumption(
    root: Path, *, idempotency_key: str, fingerprint: str,
) -> dict[str, Any] | None:
    states = root / ".omni-operating" / "states"
    for path in sorted(states.glob("STATE_*.json")):
        try:
            raw, physical = read_bound_bytes(path, allowed_roots=[root], label="EFFECT_CONSUMPTION")
            value = strict_json(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, PathSafetyError) as error:
            _fail("OPERATING_STATE_CHAIN_INVALID", decision="INCONCLUSIVE", detail=type(error).__name__)
        _require(isinstance(value, dict) and verify_record(value), "OPERATING_STATE_CHAIN_INVALID")
        last = value.get("last_effect")
        if isinstance(last, dict) and last.get("idempotency_key") == idempotency_key:
            _require(last.get("fingerprint") == fingerprint, "OPERATING_AUTHORITY_REPLAY")
            return {
                "status": "IDEMPOTENT_REPLAY", "decision": "PASS",
                "effect": last.get("effect"), "execute_effect": False,
                "state_binding": _binding(physical, raw), "grants_lease": False,
            }
    return None


def _write_effect_checkpoint(
    root: Path, *, seq: int, record: dict[str, Any],
    idempotency_key: str, fingerprint: str,
) -> dict[str, Any]:
    """Commit one effect or recover the exact winner of a concurrent CAS.

    The state file is the physical consumption record.  A competing writer may
    win after our preflight scan but before our create-once write.  In that
    narrow window, an exact duplicate is an idempotent replay; any different
    winner remains a fail-closed DUAL_WRITER collision.
    """
    try:
        committed = _write_create_once(
            _state_path(root, seq), record, root, "DUAL_WRITER", with_status=True,
        )
        _require(isinstance(committed, tuple), "DUAL_WRITER")
        binding, write_status = committed
        if write_status == "CREATED":
            return binding
        _require(write_status == "ALREADY_PRESENT_IDENTICAL", "DUAL_WRITER")
        replay = _scan_effect_consumption(
            root, idempotency_key=idempotency_key, fingerprint=fingerprint,
        )
        _require(replay is not None, "DUAL_WRITER")
        return replay
    except OperatingError as error:
        if error.reason_code != "DUAL_WRITER":
            raise
        replay = _scan_effect_consumption(
            root, idempotency_key=idempotency_key, fingerprint=fingerprint,
        )
        if replay is not None:
            return replay
        raise


def verify_state(
    *, state_path: str | Path, state_sha256: str, state_root: str | Path,
    trusted_pm_root: str | Path, trusted_pm_issuer_id: str,
    expect: str | None = None,
) -> dict[str, Any]:
    root = _state_root(state_root)
    state, state_binding = _load_state(state_path, state_sha256, root)
    if expect is not None:
        _require(state.get("status") == expect, "OPERATING_REGIME_INVALID", detail="expected status")
    if state["status"] == "AUTONOMY_ACTIVE":
        _verify_active_state(
            state, state_binding, root, trusted_pm_root=trusted_pm_root,
            trusted_pm_issuer_id=trusted_pm_issuer_id,
        )
        return {"status": "PASS", "decision": "PASS", "phase": state["status"], "state_binding": state_binding}
    return {"status": "VALID_INTERMEDIATE", "decision": "PASS", "phase": state["status"], "state_binding": state_binding}


def check_effect(
    *, state_path: str | Path, state_sha256: str, state_root: str | Path,
    effect: str, actor_session_id: str, trusted_pm_root: str | Path,
    trusted_pm_issuer_id: str, action_id: str, target_path: str | Path,
    output_path: str | Path, idempotency_key: str,
) -> dict[str, Any]:
    root = _state_root(state_root)
    state, state_binding = _load_state(state_path, state_sha256, root)
    normalized = effect.strip().upper()
    if normalized in FORBIDDEN_EFFECTS or normalized.startswith("F5"):
        _fail("F5_AUTHORITY_FORBIDDEN" if normalized.startswith("F5") else "EXECUTION_EFFECT_UNAUTHORIZED")
    action = _identifier(action_id, "EXECUTION_ACTION_BINDING_REQUIRED")
    idempotency = _identifier(idempotency_key, "EXECUTION_IDEMPOTENCY_REQUIRED")
    target = _canonical_effect_path(target_path, "EXECUTION_TARGET_UNAUTHORIZED")
    output = _canonical_effect_path(output_path, "EXECUTION_OUTPUT_UNAUTHORIZED")
    fingerprint = _effect_fingerprint(
        effect=normalized, actor_session_id=actor_session_id, action_id=action,
        target_path=target, output_path=output, idempotency_key=idempotency,
    )
    replay = _scan_effect_consumption(root, idempotency_key=idempotency, fingerprint=fingerprint)
    if replay is not None:
        return replay
    _require(state.get("owner_session_id") == actor_session_id, "EXECUTION_LEASE_OWNER_MISMATCH")
    _require(state.get("effects_authorized") is True and normalized in state.get("authorized_effects", []), "EXECUTION_EFFECT_UNAUTHORIZED")
    if state.get("regime") == "GUIDED_PM":
        pm_root, pm_issuer = _require_external_trust(
            state, trusted_pm_root, trusted_pm_issuer_id, root
        )
        _ensure_latest(state, root, "GUIDED_PM_TURN_AUTHORITY_REQUIRED")
        _require(state.get("automation_armed") is False, "GUIDED_PM_AUTOMATION_UNAUTHORIZED")
        authority, _ = _read_untyped_binding(state["guided_turn_authority_binding"], "GUIDED_PM_TURN_AUTHORITY_REQUIRED")
        _require(normalized in authority.get("authorized_effects", []), "EXECUTION_EFFECT_UNAUTHORIZED")
        _require(action == authority.get("action_id"), "EXECUTION_ACTION_BINDING_REQUIRED")
        _require(idempotency == authority.get("idempotency_key"), "EXECUTION_IDEMPOTENCY_REQUIRED")
        allowed_targets = {
            _canonical_effect_path(item, "EXECUTION_TARGET_UNAUTHORIZED")
            for item in authority.get("target_paths", [])
        }
        allowed_outputs = {
            _canonical_effect_path(item, "EXECUTION_OUTPUT_UNAUTHORIZED")
            for item in authority.get("output_paths", [])
        }
        _require(target in allowed_targets, "EXECUTION_TARGET_UNAUTHORIZED")
        _require(output in allowed_outputs, "EXECUTION_OUTPUT_UNAUTHORIZED")
        regime, _ = _read_untyped_binding(state["regime_binding"], "OPERATING_REGIME_BINDING_REQUIRED")
        _validate_channel_record(
            regime, authority["official_channel_record_binding"],
            trusted_root=pm_root, issuer_id=pm_issuer, guided_turn=authority,
        )
        consumed = {
            "effect": normalized, "action_id": action, "target_path": target,
            "output_path": output, "idempotency_key": idempotency,
            "fingerprint": fingerprint, "consumed_at": _iso_now(),
        }
        seq = int(state["state_seq"]) + 1
        terminal = {
            **{key: value for key, value in state.items() if key != "record_digest"},
            "status": "OPERATING_STOPPED", "state_id": f"{regime['binding_id']}.STATE.{seq}",
            "state_seq": seq, "previous_state_binding": state_binding,
            "authorized_effects": [], "effects_authorized": False,
            "automation_armed": False, "single_writer": False,
            "last_effect": consumed, "finding_codes": ["GUIDED_ONE_SHOT_CONSUMED"],
            "created_at": consumed["consumed_at"],
        }
        committed = _write_effect_checkpoint(
            root, seq=seq, record=terminal,
            idempotency_key=idempotency, fingerprint=fingerprint,
        )
        if committed.get("status") == "IDEMPOTENT_REPLAY":
            return committed
    elif state.get("regime") == "AUTONOMOUS":
        verified = _verify_active_state(
            state, state_binding, root, trusted_pm_root=trusted_pm_root,
            trusted_pm_issuer_id=trusted_pm_issuer_id,
        )
        autonomy = verified["autonomy"]
        operations = _validate_autonomy_operations(autonomy)
        _require(action in autonomy.get("authorized_action_ids", []), "EXECUTION_ACTION_BINDING_REQUIRED")
        allowed_targets = {
            _canonical_effect_path(item, "EXECUTION_TARGET_UNAUTHORIZED")
            for item in autonomy.get("authorized_target_paths", [])
        }
        allowed_outputs = {
            _canonical_effect_path(item, "EXECUTION_OUTPUT_UNAUTHORIZED")
            for item in autonomy.get("authorized_output_paths", [])
        }
        _require(target in allowed_targets, "EXECUTION_TARGET_UNAUTHORIZED")
        _require(output in allowed_outputs, "EXECUTION_OUTPUT_UNAUTHORIZED")
        _require(
            idempotency in {item["idempotency_key"] for item in operations},
            "EXECUTION_IDEMPOTENCY_REQUIRED",
        )
        exact_operations = [
            item for item in operations
            if item["effect"] == normalized
            and item["action_id"] == action
            and _canonical_effect_path(item["target_path"], "EXECUTION_TARGET_UNAUTHORIZED") == target
            and _canonical_effect_path(item["output_path"], "EXECUTION_OUTPUT_UNAUTHORIZED") == output
            and item["idempotency_key"] == idempotency
            and item.get("one_shot") is True
        ]
        _require(len(exact_operations) == 1, "AUTONOMY_OPERATION_BINDING_REQUIRED")
        budget = dict(verified["budget"])
        budget["used_turns"] += 1
        budget["used_tool_calls"] += 1
        if normalized in EFFECT_WRITE_CLASSES:
            budget["used_writes"] += 1
        budget["used_elapsed_seconds"] = verified["elapsed"]
        budget["used_rearms"] = budget["max_rearms"] - verified["physical"]["script"]["rearm_budget_remaining"]
        budget["last_checked_at_unix_ms"] = verified["now_ms"]
        for maximum, used in (
            ("max_turns", "used_turns"), ("max_tool_calls", "used_tool_calls"),
            ("max_writes", "used_writes"),
            ("max_elapsed_seconds", "used_elapsed_seconds"),
            ("max_rearms", "used_rearms"),
        ):
            _require(budget[used] <= budget[maximum], "OPERATING_BUDGET_EXHAUSTED", detail=used)
        _validate_budget_snapshot(budget)
        consumed = {
            "effect": normalized, "action_id": action, "target_path": target,
            "output_path": output, "idempotency_key": idempotency,
            "fingerprint": fingerprint, "consumed_at": _iso_now(),
        }
        seq = int(state["state_seq"]) + 1
        checkpoint = {
            **{key: value for key, value in state.items() if key != "record_digest"},
            "state_id": f"{state['task_id']}.AUTONOMY.STATE.{seq}",
            "state_seq": seq, "previous_state_binding": state_binding,
            "budget_snapshot": budget, "last_effect": consumed,
            "kill_switch_generation": verified["kill_switch"]["generation"],
            "created_at": consumed["consumed_at"],
        }
        committed = _write_effect_checkpoint(
            root, seq=seq, record=checkpoint,
            idempotency_key=idempotency, fingerprint=fingerprint,
        )
        if committed.get("status") == "IDEMPOTENT_REPLAY":
            return committed
    else:
        _fail("OPERATING_REGIME_INVALID")
    return {
        "status": "PASS", "decision": "PASS", "effect": normalized,
        "execute_effect": True, "state_binding": committed, "grants_lease": False,
    }


def _result_error(error: OperatingError) -> dict[str, Any]:
    status = "BLOCKED" if error.decision == "BLOCK" else "INCONCLUSIVE"
    result: dict[str, Any] = {
        "schema": "omni-operating-regime-result-v1", "status": status,
        "decision": error.decision, "reason_code": error.reason_code,
    }
    if error.detail:
        result["detail"] = error.detail
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description="Omni-Builder L5 operating-regime controller")
    sub = parser.add_subparsers(dest="command", required=True)
    bind = sub.add_parser("bind")
    bind.add_argument("--binding", required=True); bind.add_argument("--binding-sha256", required=True)
    bind.add_argument("--program", required=True); bind.add_argument("--program-sha256", required=True)
    bind.add_argument("--countersign", required=True); bind.add_argument("--countersign-sha256", required=True)
    bind.add_argument("--state-root", required=True)
    bind.add_argument("--trusted-pm-root", required=True); bind.add_argument("--trusted-pm-issuer-id", required=True)
    guided = sub.add_parser("guided-turn")
    guided.add_argument("--state", required=True); guided.add_argument("--state-sha256", required=True)
    guided.add_argument("--turn-authority", required=True); guided.add_argument("--turn-authority-sha256", required=True)
    guided.add_argument("--state-root", required=True)
    guided.add_argument("--trusted-pm-root", required=True); guided.add_argument("--trusted-pm-issuer-id", required=True)
    autonomous = sub.add_parser("activate-autonomous")
    autonomous.add_argument("--state", required=True); autonomous.add_argument("--state-sha256", required=True)
    autonomous.add_argument("--objective", required=True); autonomous.add_argument("--objective-sha256", required=True)
    autonomous.add_argument("--autonomy-authority", required=True); autonomous.add_argument("--autonomy-authority-sha256", required=True)
    autonomous.add_argument("--arm-authority", required=True); autonomous.add_argument("--arm-authority-sha256", required=True)
    autonomous.add_argument("--sentinel-bundle", required=True); autonomous.add_argument("--sentinel-bundle-sha256", required=True)
    autonomous.add_argument("--predecessor-fencing", required=True); autonomous.add_argument("--predecessor-fencing-sha256", required=True)
    autonomous.add_argument("--predecessor-session-id", required=True); autonomous.add_argument("--state-root", required=True)
    autonomous.add_argument("--trusted-pm-root", required=True); autonomous.add_argument("--trusted-pm-issuer-id", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--state", required=True); verify.add_argument("--state-sha256", required=True)
    verify.add_argument("--state-root", required=True); verify.add_argument("--expect")
    verify.add_argument("--trusted-pm-root", required=True); verify.add_argument("--trusted-pm-issuer-id", required=True)
    effect = sub.add_parser("check-effect")
    effect.add_argument("--state", required=True); effect.add_argument("--state-sha256", required=True)
    effect.add_argument("--state-root", required=True); effect.add_argument("--effect", required=True)
    effect.add_argument("--actor-session-id", required=True)
    effect.add_argument("--trusted-pm-root", required=True); effect.add_argument("--trusted-pm-issuer-id", required=True)
    effect.add_argument("--action-id", required=True); effect.add_argument("--target-path", required=True)
    effect.add_argument("--output-path", required=True); effect.add_argument("--idempotency-key", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "bind":
            result = bind_regime(
                binding_path=args.binding, binding_sha256=args.binding_sha256,
                program_path=args.program, program_sha256=args.program_sha256,
                countersign_path=args.countersign, countersign_sha256=args.countersign_sha256,
                state_root=args.state_root, trusted_pm_root=args.trusted_pm_root,
                trusted_pm_issuer_id=args.trusted_pm_issuer_id,
            )
        elif args.command == "guided-turn":
            result = activate_guided_turn(
                state_path=args.state, state_sha256=args.state_sha256,
                turn_authority_path=args.turn_authority,
                turn_authority_sha256=args.turn_authority_sha256, state_root=args.state_root,
                trusted_pm_root=args.trusted_pm_root,
                trusted_pm_issuer_id=args.trusted_pm_issuer_id,
            )
        elif args.command == "activate-autonomous":
            result = activate_autonomous(
                state_path=args.state, state_sha256=args.state_sha256,
                objective_path=args.objective, objective_sha256=args.objective_sha256,
                autonomy_authority_path=args.autonomy_authority,
                autonomy_authority_sha256=args.autonomy_authority_sha256,
                arm_authority_path=args.arm_authority,
                arm_authority_sha256=args.arm_authority_sha256,
                sentinel_bundle_path=args.sentinel_bundle,
                sentinel_bundle_sha256=args.sentinel_bundle_sha256,
                predecessor_fencing_path=args.predecessor_fencing,
                predecessor_fencing_sha256=args.predecessor_fencing_sha256,
                predecessor_session_id=args.predecessor_session_id, state_root=args.state_root,
                trusted_pm_root=args.trusted_pm_root,
                trusted_pm_issuer_id=args.trusted_pm_issuer_id,
            )
        elif args.command == "verify":
            result = verify_state(
                state_path=args.state, state_sha256=args.state_sha256,
                state_root=args.state_root, expect=args.expect,
                trusted_pm_root=args.trusted_pm_root,
                trusted_pm_issuer_id=args.trusted_pm_issuer_id,
            )
        else:
            result = check_effect(
                state_path=args.state, state_sha256=args.state_sha256,
                state_root=args.state_root, effect=args.effect,
                actor_session_id=args.actor_session_id,
                trusted_pm_root=args.trusted_pm_root,
                trusted_pm_issuer_id=args.trusted_pm_issuer_id,
                action_id=args.action_id, target_path=args.target_path,
                output_path=args.output_path, idempotency_key=args.idempotency_key,
            )
        print(canonical_json(result))
        return 0
    except OperatingError as error:
        print(canonical_json(_result_error(error)))
        return 2 if error.decision == "BLOCK" else 3
    except Exception as error:  # No traceback/oracle leakage at the CLI boundary.
        fallback = OperatingError("OPERATING_REGIME_INVALID", decision="INCONCLUSIVE", detail=type(error).__name__)
        print(canonical_json(_result_error(fallback)))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

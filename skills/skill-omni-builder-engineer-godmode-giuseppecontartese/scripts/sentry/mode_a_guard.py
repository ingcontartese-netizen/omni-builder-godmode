"""Station-zero guard: activate the method, then bind Mode only to a fused program."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from emit_state import ProtocolError, validate_instance, verify
from io_safe import sha256_path, strict_json


VALID_GROUNDS = {
    "DURABLE_KNOWLEDGE": "durable knowledge",
    "MULTI_PHASE_WORK": "multi-phase work",
    "GOVERNED_VERIFICATION": "governed verification",
    "MULTIPLE_ACTORS": "multiple actors",
}
RUN_KINDS = {"REAL", "DRY_RUN"}
CONSENT_STATES = {"ABSENT", "ACCEPTED", "DECLINED", "AMBIGUOUS"}
ACTIVATION_LEVELS = {"OMNI_AWARE", "OMNI_MODULE", "OMNI_FULL"}
# Station 0 never grants the dossier's read/network/download effects. Those
# remain separate create-once authority records inside the named module.
MODULE_EFFECTS = ("CREATE_FILES", "ARM_AUTOMATION")
BASE_NON_GRANTS = (
    "DELETE",
    "MOVE",
    "RENAME_OUTSIDE_ROOT",
    "OVERWRITE_PREEXISTING_USER_FILE",
    "EXECUTE",
    "INSTALL",
    "PUBLISH",
    "EXTERNAL_EFFECTS",
)
ACTIVATION_NON_GRANTS = [
    "PARTNER_SELECTION",
    "WEB_ACCESS",
    "DOWNLOAD",
    "PROJECT_WRITE",
    "EXECUTION",
    "AUTONOMY",
]
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,127}$")
SKILL_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
FUSED_PROGRAM_KEYS = frozenset(
    {
        "schema",
        "kind",
        "status",
        "program_id",
        "task_id",
        "knowledge_pipeline_id",
        "knowledge_state_binding",
        "knowledge_fusion_countersign_binding",
        "canonical_knowledge_binding",
        "session_pair_sha256",
        "author_role",
        "author_session_id",
        "topology",
        "profile",
        "run_kind",
        "fused_from_lanes",
        "builder_plan_manifest_binding",
        "verifier_plan_manifest_binding",
        "fusion_decision_register_binding",
        "fused_plan_draft_binding",
        "work_items",
        "preserved_alternative_ids",
        "preserved_dissent_ids",
        "created_at",
        "record_digest",
    }
)
WORK_ITEM_KEYS = frozenset(
    {
        "work_id",
        "ordinal",
        "title",
        "result",
        "persistent_artifact",
        "owner_role",
        "depends_on",
        "preconditions",
        "required_capabilities",
        "budget",
        "acceptance_evidence",
        "verifier_role",
        "rollback",
        "failure_states",
        "next_gate",
        "scope",
        "origin_refs",
    }
)
PROGRAM_ARTIFACT_KEYS = frozenset({"path", "create_policy", "owner_role"})
PROGRAM_BUDGET_KEYS = frozenset(
    {"max_turns", "max_tool_calls", "max_elapsed_seconds"}
)
PROGRAM_ACCEPTANCE_EVIDENCE_KEYS = frozenset(
    {"evidence_id", "description", "kind"}
)
PROGRAM_ROLLBACK_KEYS = frozenset({"strategy", "steps"})
PROGRAM_ORIGIN_REF_KEYS = frozenset({"role", "work_id"})
PROGRAM_COUNTERSIGN_KEYS = frozenset(
    {
        "schema",
        "status",
        "decision",
        "receipt_id",
        "program_id",
        "task_id",
        "knowledge_pipeline_id",
        "program_binding",
        "program_record_digest",
        "knowledge_state_binding",
        "knowledge_fusion_countersign_binding",
        "session_pair_sha256",
        "program_author_session_id",
        "signer_role",
        "signer_session_id",
        "verifier_report_binding",
        "reproduction",
        "finding_codes",
        "evidence_bindings",
        "created_at",
        "record_digest",
    }
)
PROGRAM_REPRODUCTION_KEYS = frozenset(
    {
        "schema_valid", "dag_valid", "full_wbs_valid",
        "origin_coverage_complete", "alternatives_preserved",
        "dissent_preserved", "no_shared_writer",
        "no_oracle_before_dual_freeze", "exact_bindings",
    }
)
PROGRAM_BAPTISM_DECISION_KEYS = frozenset(
    {
        "schema", "status", "decision", "program_id", "task_id",
        "knowledge_pipeline_id", "session_pair_sha256", "program_binding",
        "program_record_digest", "program_countersign_binding",
        "program_countersign_record_digest", "sovereign_id", "created_at",
        "record_digest",
    }
)
PROGRAM_BAPTISM_RECEIPT_KEYS = frozenset(
    set(PROGRAM_BAPTISM_DECISION_KEYS) | {"pm_decision_binding"}
)
WORKSPACE_CAPABILITIES = (
    "READ_NAMED_SOURCES",
    "CREATE_DIRECTORIES_IN_PROJECT_ROOT",
    "CREATE_FILES_IN_PROJECT_ROOT",
    "WRITE_OWNED_LANE_FILES",
)
WORKSPACE_NON_GRANTS = (
    "DELETE",
    "MOVE",
    "RENAME_OUTSIDE_ROOT",
    "OVERWRITE_PREEXISTING_USER_FILE",
    "EXECUTE",
    "INSTALL",
    "PUBLISH",
    "EXTERNAL_EFFECTS",
)
SEPARATE_AUTHORIZATIONS = ("NETWORK_RESEARCH", "DOWNLOAD")
FILE_BINDING_KEYS = frozenset({"path", "bytes", "sha256"})
WORKSPACE_ACCESS_KEYS = frozenset(
    {
        "schema",
        "status",
        "outcome",
        "envelope_id",
        "activation_receipt_sha256",
        "task_id",
        "task_root",
        "project_root",
        "source_roots",
        "owned_lane_root",
        "session_pair_sha256",
        "run_kind",
        "requested_capabilities",
        "granted_capabilities",
        "non_grants",
        "separate_authorizations_required",
        "excluded_paths",
        "probe_receipt_binding",
        "record_digest",
    }
)
WORKSPACE_PROBE_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "receipt_id",
        "envelope_id",
        "activation_receipt_sha256",
        "task_id",
        "task_root",
        "project_root",
        "source_roots",
        "owned_lane_root",
        "session_pair_sha256",
        "capabilities",
        "probe_path",
        "probe_bytes",
        "probe_sha256",
        "create_once",
        "overwritten",
        "retained",
        "read_proofs",
        "record_digest",
    }
)


class ModeBindingError(ValueError):
    """A byte-bound prerequisite for Mode selection was not reproduced."""


def _absolute_physical_path(
    path_value: str | Path,
    label: str,
    *,
    strict: bool,
) -> Path:
    """Return one native absolute path without CWD or Win32 alias semantics."""
    value = str(path_value)
    if not value or "\x00" in value:
        raise ModeBindingError(f"ABSOLUTE_PATH_REQUIRED:{label}")
    normalized = value.replace("/", "\\")
    if normalized.startswith(("\\\\?\\", "\\\\.\\")):
        raise ModeBindingError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ModeBindingError(f"ABSOLUTE_PATH_REQUIRED:{label}")
    windows = PureWindowsPath(value)
    drive_colon = 1 if len(windows.drive) == 2 and windows.drive[1] == ":" else None
    if any(index != drive_colon for index, char in enumerate(value) if char == ":"):
        raise ModeBindingError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    for part in windows.parts[1:]:
        if part in {"\\", "/"}:
            continue
        if part.endswith((" ", ".")):
            raise ModeBindingError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            raise ModeBindingError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    try:
        return candidate.resolve(strict=strict)
    except FileNotFoundError as exc:
        raise ModeBindingError(f"PHYSICAL_PATH_MISSING:{label}") from exc
    except OSError as exc:
        raise ModeBindingError(f"PHYSICAL_PATH_INVALID:{label}") from exc


@dataclass(frozen=True)
class ModeEvidence:
    intake_state_sha256: str
    intake_record_digest: str
    activation_receipt_sha256: str
    program_sha256: str
    program_bytes: int
    program_record_digest: str
    program_countersign_sha256: str
    program_countersign_bytes: int
    program_countersign_record_digest: str
    program_baptism_decision_sha256: str
    program_baptism_decision_bytes: int
    program_baptism_decision_record_digest: str
    program_baptism_receipt_sha256: str
    program_baptism_receipt_bytes: int
    program_baptism_receipt_record_digest: str
    sovereign_id: str
    workspace_access_ready: bool
    workspace_access_envelope_id: str | None
    workspace_access_envelope_sha256: str | None
    workspace_access_envelope_record_digest: str | None
    workspace_probe_receipt_sha256: str | None
    workspace_probe_receipt_record_digest: str | None
    workspace_probe_sha256: str | None


@dataclass(frozen=True)
class WorkspaceEvidence:
    envelope_id: str
    envelope_sha256: str
    envelope_record_digest: str
    probe_receipt_sha256: str
    probe_receipt_record_digest: str
    probe_sha256: str


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"CLI_ARGUMENT_INVALID:{message}")


def _require_bool(name: str, value: object) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name.upper()}_MUST_BE_BOOL")


def _grounds(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        raise TypeError("GROUNDS_MUST_BE_A_SEQUENCE")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("GROUND_MUST_BE_STRING")
        normalized = value.strip().upper()
        if normalized not in VALID_GROUNDS:
            raise ValueError(f"MOTIVATION_GROUND_UNKNOWN:{normalized or 'EMPTY'}")
        if normalized not in result:
            result.append(normalized)
    return result


def _activation_level(value: str | None) -> str:
    level = "OMNI_AWARE" if value is None else value.strip().upper()
    if level not in ACTIVATION_LEVELS:
        raise ValueError("ACTIVATION_LEVEL_INVALID")
    return level


def _is_reparse_surface(path: Path) -> bool:
    """Return True for a symlink or junction without following it."""
    try:
        return path.is_symlink() or (
            hasattr(path, "is_junction") and path.is_junction()
        )
    except OSError as exc:
        raise ValueError("UNKNOWN_MODULE_REQUESTED") from exc


def _read_module_manifest(module_dir: Path) -> str:
    """Resolve one packaged manifest to its canonical, drift-free MODULE_ID."""
    manifest_path = module_dir / "module.json"
    if (
        not manifest_path.is_file()
        or _is_reparse_surface(module_dir)
        or _is_reparse_surface(manifest_path)
    ):
        raise ValueError("MODULE_MANIFEST_MISSING")
    try:
        before = manifest_path.stat()
        payload = manifest_path.read_bytes()
        middle = manifest_path.stat()
        readback = manifest_path.read_bytes()
        after = manifest_path.stat()
    except OSError as exc:
        raise ValueError("MODULE_MANIFEST_UNREADABLE") from exc
    identities = {
        (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        for item in (before, middle, after)
    }
    if len(identities) != 1 or payload != readback or len(payload) != after.st_size:
        raise ValueError("MODULE_MANIFEST_DRIFT")
    try:
        manifest = strict_json(payload.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("MODULE_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict):
        raise ValueError("MODULE_MANIFEST_INVALID")
    if (
        manifest.get("schema") != "omni-module-manifest-v1"
        or manifest.get("activation_level") != "OMNI_MODULE"
        or not isinstance(manifest.get("version"), str)
        or not manifest["version"].strip()
        or not isinstance(manifest.get("summary"), str)
        or not manifest["summary"].strip()
    ):
        raise ValueError("MODULE_MANIFEST_INVALID")
    module_id = manifest.get("module_id")
    if not isinstance(module_id, str) or IDENTIFIER_RE.fullmatch(module_id) is None:
        raise ValueError("MODULE_MANIFEST_INVALID")
    if module_id.casefold() != module_dir.name.casefold():
        raise ValueError("MODULE_MANIFEST_ID_DRIFT")
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint.strip():
        raise ValueError("MODULE_MANIFEST_INVALID")
    entry_parts = PureWindowsPath(entrypoint)
    if (
        entrypoint != entrypoint.strip()
        or bool(entry_parts.drive)
        or bool(entry_parts.root)
        or len(entry_parts.parts) != 1
        or entrypoint in {".", ".."}
        or ":" in entrypoint
    ):
        raise ValueError("MODULE_MANIFEST_ENTRYPOINT_INVALID")
    entrypoint_path = module_dir / entrypoint
    if (
        not entrypoint_path.is_file()
        or _is_reparse_surface(entrypoint_path)
    ):
        raise ValueError("MODULE_MANIFEST_ENTRYPOINT_INVALID")
    try:
        if manifest_path.read_bytes() != payload:
            raise ValueError("MODULE_MANIFEST_DRIFT")
    except OSError as exc:
        raise ValueError("MODULE_MANIFEST_UNREADABLE") from exc
    return module_id


def _module_surfaces(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        raise TypeError("MODULES_MUST_BE_A_SEQUENCE")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise TypeError("MODULE_MUST_BE_NONEMPTY_STRING")
        normalized = value.replace("/", "\\")
        windows = PureWindowsPath(value)
        if (
            normalized.startswith(("\\\\?\\", "\\\\.\\"))
            or bool(windows.drive)
            or bool(windows.root)
            or ":" in value
            or any(part.endswith((" ", ".")) for part in windows.parts)
            or any(
                part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
                for part in windows.parts
            )
        ):
            raise ValueError("UNKNOWN_MODULE_REQUESTED")
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("UNKNOWN_MODULE_REQUESTED")
        if candidate.as_posix() in {".", "SKILL.md"}:
            raise ValueError("MODULE_SCOPE_TOO_BROAD")
        modules_root = SKILL_ROOT / "modules"
        requested = SKILL_ROOT / candidate
        if not requested.exists() and len(candidate.parts) == 1:
            requested = modules_root / candidate.name
        if not requested.exists() or _is_reparse_surface(requested):
            raise ValueError("UNKNOWN_MODULE_REQUESTED")
        try:
            target = requested.resolve(strict=True)
            packaged_root = modules_root.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ValueError("UNKNOWN_MODULE_REQUESTED") from exc
        module_dir = target.parent if target.is_file() else target
        try:
            relative = module_dir.relative_to(packaged_root)
        except ValueError as exc:
            raise ValueError("UNKNOWN_MODULE_REQUESTED") from exc
        if (
            len(relative.parts) != 1
            or not module_dir.is_dir()
            or (target.is_file() and target.name != "module.json")
            or "__pycache__" in module_dir.parts
        ):
            raise ValueError("UNKNOWN_MODULE_REQUESTED")
        module_id = _read_module_manifest(module_dir)
        if module_id not in result:
            result.append(module_id)
    return result


def _effect_grants(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        raise TypeError("EFFECT_GRANTS_MUST_BE_A_SEQUENCE")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("EFFECT_GRANT_MUST_BE_STRING")
        effect = value.strip().upper()
        if effect not in MODULE_EFFECTS:
            raise ValueError(f"EFFECT_GRANT_UNKNOWN:{effect or 'EMPTY'}")
        if effect not in result:
            result.append(effect)
    if "ARM_AUTOMATION" in result and "CREATE_FILES" not in result:
        raise ValueError("ARM_AUTOMATION_REQUIRES_CREATE_FILES")
    return result


def _progressive_non_grants(effect_grants: Iterable[str]) -> list[str]:
    granted = set(effect_grants)
    return [*BASE_NON_GRANTS, *(effect for effect in MODULE_EFFECTS if effect not in granted)]


def _normalize_consent(*, user_consent: bool | None, consent_state: str | None) -> str:
    if user_consent is not None:
        if type(user_consent) is not bool:
            raise TypeError("USER_CONSENT_MUST_BE_BOOL_OR_NONE")
        if consent_state is not None:
            raise ValueError("CONSENT_INPUTS_MUST_NOT_BE_COMBINED")
        return "ACCEPTED" if user_consent else "DECLINED"
    state = "ABSENT" if consent_state is None else consent_state
    if not isinstance(state, str) or state not in CONSENT_STATES:
        raise ValueError("CONSENT_STATE_INVALID")
    return state


def _base(
    status: str,
    *,
    reason_code: str,
    classification: str,
    grounds: list[str],
    run_kind: str | None,
) -> dict[str, object]:
    return {
        "schema": "omni-invocation-decision-v2",
        "status": status,
        "reason_code": reason_code,
        "classification": classification,
        "grounds": grounds,
        "run_kind": run_kind or "UNSET",
        "effect_policy": (
            "SIMULATE_WITHOUT_MATERIALIZATION"
            if run_kind == "DRY_RUN"
            else "DOWNSTREAM_GATED_REAL" if run_kind == "REAL" else "NO_EFFECTS"
        ),
        "task_scope": "CURRENT_TASK_ONLY",
        "activation_allowed": False,
        "activation_grants": [],
        "activation_non_grants": ACTIVATION_NON_GRANTS,
        "knowledge_available": True,
        "skill_invoked": False,
        "effect_authorized": False,
        "activation_level": "OMNI_AWARE",
        "modules_used": [],
        "authority_grants": [],
        "artifact_grants": [],
        "requested_effects": [],
        "effect_grants": [],
        "non_grants": _progressive_non_grants(()),
        "access_envelope_identity": "NONE",
        "intake_allowed": False,
        "mode_selection_allowed": False,
        "mode_gate": "BLOCKED_BEFORE_MODE_SELECTION",
        "next_gate": "NONE",
    }


def decide_invocation(
    *,
    explicit_user_request: bool,
    complexity_warrants_omni: bool,
    user_consent: bool | None = None,
    consent_state: str | None = None,
    grounds: Iterable[str] | None = None,
    run_kind: str | None = None,
    activation_level: str | None = None,
    modules: Iterable[str] | None = None,
    effect_grants: Iterable[str] | None = None,
) -> dict[str, object]:
    """Return a task-scoped, zero-write activation decision."""
    _require_bool("explicit_user_request", explicit_user_request)
    _require_bool("complexity_warrants_omni", complexity_warrants_omni)
    consent = _normalize_consent(user_consent=user_consent, consent_state=consent_state)
    normalized_grounds = _grounds(grounds)
    level = _activation_level(activation_level)
    if isinstance(modules, (str, bytes)):
        raise TypeError("MODULES_MUST_BE_A_SEQUENCE")
    module_values = list(modules) if modules is not None else []
    if level == "OMNI_MODULE" and len(module_values) != 1:
        raise ValueError("OMNI_MODULE_REQUIRES_ONE_REAL_MODULE")
    normalized_modules = _module_surfaces(module_values)
    normalized_effects = _effect_grants(effect_grants)
    if level == "OMNI_AWARE" and (normalized_modules or normalized_effects):
        raise ValueError("AWARE_CANNOT_DECLARE_MODULE_OR_EFFECT")
    if level == "OMNI_FULL" and normalized_modules:
        raise ValueError("MODULE_CANNOT_ESCALATE_TO_FULL")
    if level == "OMNI_FULL" and normalized_effects:
        raise ValueError("FULL_EFFECTS_REQUIRE_SEPARATE_ACCESS_ENVELOPE")
    if explicit_user_request and consent != "ABSENT":
        raise ValueError("ACTIVATION_PATHS_MUST_NOT_BE_COMBINED")
    if not complexity_warrants_omni and normalized_grounds:
        raise ValueError("GROUND_WITHOUT_OMNI_CANDIDATE")
    if run_kind is not None and run_kind not in RUN_KINDS:
        return _base(
            "BLOCKED",
            reason_code="RUN_KIND_INVALID",
            classification="OMNI_CANDIDATE" if complexity_warrants_omni else "ONE_OFF",
            grounds=normalized_grounds,
            run_kind=None,
        )

    activation_path: str | None = None
    if level == "OMNI_AWARE" and (explicit_user_request or consent == "ACCEPTED"):
        return _base(
            "BLOCKED",
            reason_code="EXPLICIT_ACTIVATION_LEVEL_REQUIRED",
            classification="OMNI_CANDIDATE" if complexity_warrants_omni else "ONE_OFF",
            grounds=normalized_grounds,
            run_kind=run_kind,
        )
    if explicit_user_request:
        activation_path = "EXPLICIT_USER_OPT_IN"
    elif complexity_warrants_omni:
        if not normalized_grounds:
            return _base(
                "BLOCKED",
                reason_code="INVOCATION_GROUNDS_REQUIRED",
                classification="OMNI_CANDIDATE",
                grounds=[],
                run_kind=run_kind,
            )
        if consent in {"ABSENT", "AMBIGUOUS"}:
            result = _base(
                "PROPOSAL_EMITTED_AWAITING_CONSENT",
                reason_code="CONSENT_ABSENT" if consent == "ABSENT" else "CONSENT_AMBIGUOUS",
                classification="OMNI_CANDIDATE",
                grounds=normalized_grounds,
                run_kind=run_kind,
            )
            reasons = ", ".join(VALID_GROUNDS[ground] for ground in normalized_grounds)
            result["proposal_question"] = (
                f"This project would benefit from Omni-Builder because it needs {reasons}. "
                "Do you want to proceed?"
            )
            result["proposed_activation_level"] = (
                level if level != "OMNI_AWARE" else "OMNI_FULL"
            )
            result["next_gate"] = "EXPLICIT_CONSENT"
            return result
        if consent == "DECLINED":
            result = _base(
                "DECLINED_USE_ORDINARY_TOOLS",
                reason_code="CONSENT_NEGATIVE",
                classification="OMNI_CANDIDATE",
                grounds=normalized_grounds,
                run_kind=run_kind,
            )
            result["next_gate"] = "ORDINARY_TOOLS_OR_STOP"
            return result
        activation_path = "PROPOSAL_ACCEPTED"
    elif consent == "ACCEPTED":
        return _base(
            "NO_SKILL_REQUIRED",
            reason_code="MOTIVATED_RECOMMENDATION_NOT_ESTABLISHED",
            classification="ONE_OFF",
            grounds=[],
            run_kind=run_kind,
        )
    else:
        return _base(
            "NO_SKILL_REQUIRED",
            reason_code="ONE_OFF_TASK",
            classification="ONE_OFF",
            grounds=[],
            run_kind=run_kind,
        )

    if run_kind is None:
        result = _base(
            "BLOCKED",
            reason_code="RUN_KIND_REQUIRED",
            classification="OMNI_CANDIDATE",
            grounds=normalized_grounds,
            run_kind=None,
        )
        result["activation_path"] = activation_path
        return result

    if level == "OMNI_MODULE":
        result = _base(
            "MODULE_ACTIVATION_ALLOWED",
            reason_code=activation_path,
            classification="OMNI_MODULE_ACTIVATED",
            grounds=normalized_grounds,
            run_kind=run_kind,
        )
        result.update(
            {
                "activation_path": activation_path,
                "activation_allowed": True,
                "activation_grants": ["NAMED_MODULE_USE"],
                "skill_invoked": True,
                "activation_level": "OMNI_MODULE",
                "modules_used": normalized_modules,
                "authority_grants": ["NAMED_MODULE_USE"],
                "artifact_grants": [],
                "requested_effects": normalized_effects,
                "effect_grants": [],
                "effect_authorized": False,
                "non_grants": _progressive_non_grants(()),
                "access_envelope_identity": (
                    "PENDING" if normalized_effects else "NONE"
                ),
                "intake_allowed": False,
                "mode_gate": "MODULE_SCOPE_ONLY",
                "next_gate": (
                    "WORKSPACE_ACCESS_ENVELOPE"
                    if normalized_effects
                    else "NAMED_MODULE_EXECUTION"
                ),
            }
        )
        return result

    result = _base(
        "ACTIVATION_ALLOWED",
        reason_code=activation_path,
        classification="OMNI_ACTIVATED",
        grounds=normalized_grounds,
        run_kind=run_kind,
    )
    result.update(
        {
            "activation_path": activation_path,
            "activation_allowed": True,
            "activation_grants": ["METHOD_USE"],
            "skill_invoked": True,
            "activation_level": "OMNI_FULL",
            "authority_grants": ["METHOD_USE", "FULL_ORCHESTRATION"],
            "artifact_grants": [],
            "requested_effects": [],
            "access_envelope_identity": "PENDING",
            "intake_allowed": True,
            "mode_gate": "MODE_BEFORE_PROGRAM",
            "next_gate": "GUIDED_INTAKE",
        }
    )
    return result


def _require_sha(name: str, value: str | None) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ModeBindingError(f"{name}_SHA256_INVALID")
    return value.upper()


def _read_bound_json(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    path = _absolute_physical_path(path, f"{label}_PATH", strict=False)
    if not path.is_file():
        raise ModeBindingError(f"{label}_FILE_MISSING")
    observed_sha256 = sha256_path(path)
    if observed_sha256 != _require_sha(label, expected_sha256):
        raise ModeBindingError(f"{label}_FILE_SHA256_MISMATCH")
    try:
        value = strict_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModeBindingError(f"{label}_JSON_INVALID:{type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ModeBindingError(f"{label}_JSON_OBJECT_REQUIRED")
    return value


def _resolve_binding_path(label: str, state_path: Path) -> Path:
    del state_path  # Relative-to-container resolution is forbidden by contract.
    return _absolute_physical_path(label, "BOUND_ARTIFACT", strict=False)


def _require_exact_keys(label: str, value: dict[str, object], expected: frozenset[str]) -> None:
    observed = frozenset(value)
    if observed != expected:
        missing = ",".join(sorted(expected - observed)) or "NONE"
        extra = ",".join(sorted(observed - expected)) or "NONE"
        raise ModeBindingError(f"{label}_SHAPE_INVALID:MISSING={missing}:EXTRA={extra}")


def _require_identifier(label: str, value: object) -> str:
    if not isinstance(value, str) or IDENTIFIER_RE.fullmatch(value) is None:
        raise ModeBindingError(f"{label}_INVALID")
    return value


def _require_nonempty_string(label: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModeBindingError(f"{label}_INVALID")
    return value


def _require_record_digest(label: str, value: dict[str, object]) -> str:
    digest = _require_sha(f"{label}_RECORD_DIGEST", value.get("record_digest"))
    if not verify(value):
        raise ModeBindingError(f"{label}_RECORD_DIGEST_INVALID")
    return digest


def _validate_file_binding(label: str, value: object) -> tuple[dict[str, object], Path]:
    if not isinstance(value, dict):
        raise ModeBindingError(f"{label}_BINDING_OBJECT_REQUIRED")
    _require_exact_keys(f"{label}_BINDING", value, FILE_BINDING_KEYS)
    path = _absolute_physical_path(str(value.get("path", "")), label, strict=False)
    if not path.is_file():
        raise ModeBindingError(f"{label}_FILE_MISSING")
    if type(value.get("bytes")) is not int or value["bytes"] != path.stat().st_size:
        raise ModeBindingError(f"{label}_BYTES_MISMATCH")
    if value.get("sha256") != sha256_path(path):
        raise ModeBindingError(f"{label}_SHA256_MISMATCH")
    return value, path


def _require_exact_file_binding(
    label: str, value: object, *, path: Path, sha256: str, size: int,
) -> None:
    binding, observed_path = _validate_file_binding(label, value)
    if (
        observed_path != path
        or binding.get("sha256") != sha256
        or binding.get("bytes") != size
    ):
        raise ModeBindingError(f"{label}_MISMATCH")


def _validate_work_items(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise ModeBindingError("PROGRAM_WORK_ITEMS_INVALID")
    known: list[str] = []
    for expected_ordinal, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ModeBindingError("PROGRAM_WORK_ITEM_OBJECT_REQUIRED")
        _require_exact_keys("PROGRAM_WORK_ITEM", item, WORK_ITEM_KEYS)
        work_id = _require_identifier("PROGRAM_WORK_ID", item["work_id"])
        if work_id in known:
            raise ModeBindingError("PROGRAM_WORK_ID_DUPLICATE")
        if type(item["ordinal"]) is not int or item["ordinal"] != expected_ordinal:
            raise ModeBindingError("PROGRAM_WORK_ORDINAL_INVALID")
        _require_nonempty_string("PROGRAM_WORK_TITLE", item["title"])
        _require_nonempty_string("PROGRAM_WORK_RESULT", item["result"])
        if item["owner_role"] not in {"BUILDER", "VERIFIER"}:
            raise ModeBindingError("PROGRAM_WORK_OWNER_ROLE_INVALID")
        artifact = item["persistent_artifact"]
        if not isinstance(artifact, dict):
            raise ModeBindingError("PROGRAM_WORK_ARTIFACT_OBJECT_REQUIRED")
        _require_exact_keys("PROGRAM_WORK_ARTIFACT", artifact, PROGRAM_ARTIFACT_KEYS)
        _absolute_physical_path(str(artifact.get("path", "")), "PROGRAM_WORK_ARTIFACT", strict=False)
        if artifact.get("create_policy") not in {
            "CREATE_ONCE", "MUTABLE_OWNED", "SUPERSEDE_CREATE_ONCE",
        } or artifact.get("owner_role") not in {"BUILDER", "VERIFIER"}:
            raise ModeBindingError("PROGRAM_WORK_ARTIFACT_INVALID")
        depends_on = item["depends_on"]
        if (
            not isinstance(depends_on, list)
            or any(not isinstance(dependency, str) for dependency in depends_on)
            or len(depends_on) != len(set(depends_on))
            or any(dependency not in known for dependency in depends_on)
        ):
            raise ModeBindingError("PROGRAM_WORK_DEPENDENCY_INVALID")
        for label, values in (
            ("PRECONDITIONS", item["preconditions"]),
            ("REQUIRED_CAPABILITIES", item["required_capabilities"]),
        ):
            if (
                not isinstance(values, list) or not values
                or any(not isinstance(entry, str) or not entry.strip() for entry in values)
                or len(values) != len(set(values))
            ):
                raise ModeBindingError(f"PROGRAM_WORK_{label}_INVALID")
        budget = item["budget"]
        if not isinstance(budget, dict):
            raise ModeBindingError("PROGRAM_WORK_BUDGET_OBJECT_REQUIRED")
        _require_exact_keys("PROGRAM_WORK_BUDGET", budget, PROGRAM_BUDGET_KEYS)
        limits = {
            "max_turns": (1, 10_000),
            "max_tool_calls": (0, 100_000),
            "max_elapsed_seconds": (1, 31_536_000),
        }
        for field, (minimum, maximum) in limits.items():
            number = budget.get(field)
            if type(number) is not int or not minimum <= number <= maximum:
                raise ModeBindingError(f"PROGRAM_WORK_BUDGET_INVALID:{field}")
        evidence = item["acceptance_evidence"]
        if (
            not isinstance(evidence, list) or not evidence
            or any(not isinstance(entry, dict) for entry in evidence)
        ):
            raise ModeBindingError("PROGRAM_WORK_ACCEPTANCE_EVIDENCE_INVALID")
        for entry in evidence:
            _require_exact_keys(
                "PROGRAM_WORK_ACCEPTANCE_EVIDENCE", entry,
                PROGRAM_ACCEPTANCE_EVIDENCE_KEYS,
            )
            _require_identifier("PROGRAM_EVIDENCE_ID", entry["evidence_id"])
            _require_nonempty_string("PROGRAM_EVIDENCE_DESCRIPTION", entry["description"])
            if entry["kind"] not in {
                "FILE_BINDING", "RECEIPT", "TEST_REPORT", "CHANNEL_RECORD",
                "REPRODUCTION_LOG",
            }:
                raise ModeBindingError("PROGRAM_WORK_ACCEPTANCE_EVIDENCE_INVALID")
        if item["verifier_role"] not in {"BUILDER", "VERIFIER"}:
            raise ModeBindingError("PROGRAM_WORK_VERIFIER_ROLE_INVALID")
        rollback = item["rollback"]
        if not isinstance(rollback, dict):
            raise ModeBindingError("PROGRAM_WORK_ROLLBACK_OBJECT_REQUIRED")
        _require_exact_keys("PROGRAM_WORK_ROLLBACK", rollback, PROGRAM_ROLLBACK_KEYS)
        if rollback.get("strategy") not in {
            "REVERT_CANDIDATE", "SUPERSEDE_CREATE_ONCE", "SAFE_PARK",
            "NOT_APPLICABLE",
        } or (
            not isinstance(rollback.get("steps"), list) or not rollback["steps"]
            or any(not isinstance(step, str) or not step.strip() for step in rollback["steps"])
        ):
            raise ModeBindingError("PROGRAM_WORK_ROLLBACK_INVALID")
        failure_states = item["failure_states"]
        if (
            not isinstance(failure_states, list) or not failure_states
            or len(failure_states) != len(set(failure_states))
            or any(state not in {
                "BLOCKED_PENDING_HUMAN", "BLOCKED_PENDING_INFRA", "INCONCLUSIVE",
                "ABORTED", "SUPERSEDED",
            } for state in failure_states)
        ):
            raise ModeBindingError("PROGRAM_WORK_FAILURE_STATES_INVALID")
        _require_identifier("PROGRAM_WORK_NEXT_GATE", item["next_gate"])
        scope = item["scope"]
        if (
            not isinstance(scope, list) or not scope or len(scope) != len(set(scope))
            or any(entry not in {"F3_BUILD", "F4_TEST"} for entry in scope)
        ):
            raise ModeBindingError("PROGRAM_WORK_SCOPE_INVALID")
        origins = item["origin_refs"]
        if not isinstance(origins, list) or not origins:
            raise ModeBindingError("PROGRAM_WORK_ORIGIN_REFS_INVALID")
        seen_origins: set[tuple[str, str]] = set()
        for origin in origins:
            if not isinstance(origin, dict):
                raise ModeBindingError("PROGRAM_WORK_ORIGIN_REFS_INVALID")
            _require_exact_keys("PROGRAM_WORK_ORIGIN_REF", origin, PROGRAM_ORIGIN_REF_KEYS)
            if origin["role"] not in {"BUILDER", "VERIFIER"}:
                raise ModeBindingError("PROGRAM_WORK_ORIGIN_REFS_INVALID")
            origin_id = _require_identifier("PROGRAM_WORK_ORIGIN_ID", origin["work_id"])
            origin_key = (str(origin["role"]), origin_id)
            if origin_key in seen_origins:
                raise ModeBindingError("PROGRAM_WORK_ORIGIN_REFS_INVALID")
            seen_origins.add(origin_key)
        known.append(work_id)


def _validate_fused_program(
    program: dict[str, object],
    state: dict[str, object],
) -> tuple[str, str, str, str]:
    _require_exact_keys("PROGRAM", program, FUSED_PROGRAM_KEYS)
    if program["schema"] != "omni-fused-program-v2":
        raise ModeBindingError("PROGRAM_SCHEMA_INVALID")
    if (
        program["kind"] != "PROGRAM_FUSION_CANDIDATE"
        or program["status"] != "PROGRAM_FUSION_FROZEN"
    ):
        raise ModeBindingError("PROGRAM_STATUS_INVALID")
    program_id = _require_identifier("PROGRAM_ID", program["program_id"])
    task_id = _require_identifier("PROGRAM_TASK_ID", program["task_id"])
    knowledge_pipeline_id = _require_identifier(
        "PROGRAM_KNOWLEDGE_PIPELINE_ID", program["knowledge_pipeline_id"],
    )
    program_digest = _require_record_digest("PROGRAM", program)
    pair = state.get("session_pair")
    if not isinstance(pair, dict):
        raise ModeBindingError("PROGRAM_SESSION_PAIR_MISSING")
    builder = pair.get("builder")
    if not isinstance(builder, dict):
        raise ModeBindingError("PROGRAM_BUILDER_SESSION_MISSING")
    workspace = state.get("workspace_access_envelope")
    if not isinstance(workspace, dict):
        raise ModeBindingError("PROGRAM_TASK_BINDING_MISMATCH")
    if (
        task_id != workspace.get("task_id")
        or program["session_pair_sha256"] != pair.get("pair_sha256")
        or program["topology"] != state.get("topology")
        or program["profile"] != state.get("profile")
        or program["run_kind"] != state.get("run_kind")
    ):
        raise ModeBindingError("PROGRAM_INTAKE_BINDING_MISMATCH")
    if (
        program["author_role"] != "BUILDER"
        or program["author_session_id"] != builder.get("session_id")
    ):
        raise ModeBindingError("PROGRAM_AUTHOR_BINDING_MISMATCH")
    if program["fused_from_lanes"] != ["BUILDER", "VERIFIER"]:
        raise ModeBindingError("PROGRAM_FUSION_LANES_INVALID")
    for label in (
        "knowledge_state_binding", "knowledge_fusion_countersign_binding",
        "canonical_knowledge_binding", "builder_plan_manifest_binding",
        "verifier_plan_manifest_binding", "fusion_decision_register_binding",
        "fused_plan_draft_binding",
    ):
        _validate_file_binding(f"PROGRAM_{label.upper()}", program[label])
    _validate_work_items(program["work_items"])
    for label in ("preserved_alternative_ids", "preserved_dissent_ids"):
        values = program[label]
        if (
            not isinstance(values, list) or len(values) != len(set(values))
            or any(not isinstance(value, str) or IDENTIFIER_RE.fullmatch(value) is None for value in values)
        ):
            raise ModeBindingError(f"PROGRAM_{label.upper()}_INVALID")
    _require_nonempty_string("PROGRAM_CREATED_AT", program["created_at"])
    return program_id, task_id, knowledge_pipeline_id, program_digest


def _validate_program_countersign(
    receipt: dict[str, object],
    *,
    receipt_path: Path,
    program_path: Path,
    program: dict[str, object],
    program_sha256: str,
    program_bytes: int,
    program_id: str,
    program_record_digest: str,
    task_id: str,
    knowledge_pipeline_id: str,
    state: dict[str, object],
) -> str:
    _require_exact_keys("PROGRAM_COUNTERSIGN", receipt, PROGRAM_COUNTERSIGN_KEYS)
    if receipt["schema"] != "omni-program-countersign-receipt-v2":
        raise ModeBindingError("PROGRAM_COUNTERSIGN_SCHEMA_INVALID")
    if receipt["status"] != "PROGRAM_COUNTERSIGN_ACCEPTED":
        raise ModeBindingError("PROGRAM_COUNTERSIGN_STATUS_INVALID")
    if receipt["decision"] != "ACCEPTED":
        raise ModeBindingError("PROGRAM_COUNTERSIGN_DECISION_INVALID")
    _require_identifier("PROGRAM_COUNTERSIGN_RECEIPT_ID", receipt["receipt_id"])
    receipt_digest = _require_record_digest("PROGRAM_COUNTERSIGN", receipt)
    pair = state.get("session_pair")
    if not isinstance(pair, dict):
        raise ModeBindingError("PROGRAM_COUNTERSIGN_SESSION_PAIR_MISSING")
    builder = pair.get("builder")
    verifier = pair.get("verifier")
    if not isinstance(builder, dict) or not isinstance(verifier, dict):
        raise ModeBindingError("PROGRAM_COUNTERSIGN_SESSION_PAIR_MISSING")
    if builder.get("session_id") == verifier.get("session_id"):
        raise ModeBindingError("PROGRAM_COUNTERSIGN_NOT_INDEPENDENT")
    if (
        receipt["signer_role"] != "VERIFIER"
        or receipt["signer_session_id"] != verifier.get("session_id")
    ):
        raise ModeBindingError("PROGRAM_COUNTERSIGN_SIGNER_INVALID")
    _require_exact_file_binding(
        "PROGRAM_COUNTERSIGN_PROGRAM_BINDING", receipt["program_binding"],
        path=program_path, sha256=program_sha256, size=program_bytes,
    )
    if (
        receipt["program_id"] != program_id
        or receipt["task_id"] != task_id
        or receipt["knowledge_pipeline_id"] != knowledge_pipeline_id
        or receipt["program_record_digest"] != program_record_digest
        or receipt["session_pair_sha256"] != pair.get("pair_sha256")
        or receipt["program_author_session_id"] != program["author_session_id"]
        or receipt["knowledge_state_binding"] != program["knowledge_state_binding"]
        or receipt["knowledge_fusion_countersign_binding"]
        != program["knowledge_fusion_countersign_binding"]
    ):
        raise ModeBindingError("PROGRAM_COUNTERSIGN_BINDING_MISMATCH")
    _validate_file_binding("PROGRAM_COUNTERSIGN_VERIFIER_REPORT", receipt["verifier_report_binding"])
    reproduction = receipt["reproduction"]
    if not isinstance(reproduction, dict):
        raise ModeBindingError("PROGRAM_COUNTERSIGN_REPRODUCTION_INVALID")
    _require_exact_keys(
        "PROGRAM_COUNTERSIGN_REPRODUCTION", reproduction, PROGRAM_REPRODUCTION_KEYS,
    )
    if any(value is not True for value in reproduction.values()):
        raise ModeBindingError("PROGRAM_COUNTERSIGN_REPRODUCTION_INVALID")
    if receipt["finding_codes"] != []:
        raise ModeBindingError("PROGRAM_COUNTERSIGN_FINDINGS_PRESENT")
    evidence_bindings = receipt["evidence_bindings"]
    if not isinstance(evidence_bindings, list) or not evidence_bindings:
        raise ModeBindingError("PROGRAM_COUNTERSIGN_EVIDENCE_REQUIRED")
    for index, binding in enumerate(evidence_bindings):
        _validate_file_binding(f"PROGRAM_COUNTERSIGN_EVIDENCE_{index}", binding)
    _require_nonempty_string("PROGRAM_COUNTERSIGN_CREATED_AT", receipt["created_at"])
    return receipt_digest


def _validate_program_baptism(
    *,
    decision: dict[str, object], decision_path: Path,
    receipt: dict[str, object], receipt_path: Path,
    program_path: Path, program_sha256: str, program_bytes: int,
    program_id: str, program_record_digest: str,
    countersign_path: Path, countersign_sha256: str, countersign_bytes: int,
    countersign_record_digest: str, task_id: str, knowledge_pipeline_id: str,
    session_pair_sha256: str, expected_sovereign_id: str, state: dict[str, object],
) -> tuple[str, str, str]:
    _require_exact_keys(
        "PROGRAM_BAPTISM_DECISION", decision, PROGRAM_BAPTISM_DECISION_KEYS,
    )
    if (
        decision.get("schema") != "omni-program-baptism-decision-v1"
        or decision.get("status") != "PROGRAM_BAPTISM_AUTHORIZED"
        or decision.get("decision") != "ACCEPTED"
    ):
        raise ModeBindingError("PROGRAM_BAPTISM_DECISION_INVALID")
    decision_digest = _require_record_digest("PROGRAM_BAPTISM_DECISION", decision)
    sovereign_id = _require_nonempty_string(
        "PROGRAM_BAPTISM_SOVEREIGN", decision.get("sovereign_id"),
    )
    if sovereign_id != _require_nonempty_string(
        "EXPECTED_SOVEREIGN", expected_sovereign_id,
    ):
        raise ModeBindingError("PROGRAM_BAPTISM_SOVEREIGN_MISMATCH")
    team_card = state.get("team_card")
    if not isinstance(team_card, dict) or team_card.get("sovereign_identity") != sovereign_id:
        raise ModeBindingError("PROGRAM_BAPTISM_SOVEREIGN_MISMATCH")
    _require_exact_file_binding(
        "PROGRAM_BAPTISM_DECISION_PROGRAM_BINDING", decision["program_binding"],
        path=program_path, sha256=program_sha256, size=program_bytes,
    )
    _require_exact_file_binding(
        "PROGRAM_BAPTISM_DECISION_COUNTERSIGN_BINDING",
        decision["program_countersign_binding"], path=countersign_path,
        sha256=countersign_sha256, size=countersign_bytes,
    )
    expected_common = {
        "program_id": program_id, "task_id": task_id,
        "knowledge_pipeline_id": knowledge_pipeline_id,
        "session_pair_sha256": session_pair_sha256,
        "program_record_digest": program_record_digest,
        "program_countersign_record_digest": countersign_record_digest,
        "sovereign_id": sovereign_id,
    }
    if any(decision.get(field) != value for field, value in expected_common.items()):
        raise ModeBindingError("PROGRAM_BAPTISM_BINDING_MISMATCH")
    _require_nonempty_string("PROGRAM_BAPTISM_DECISION_CREATED_AT", decision["created_at"])

    _require_exact_keys(
        "PROGRAM_BAPTISM_RECEIPT", receipt, PROGRAM_BAPTISM_RECEIPT_KEYS,
    )
    if (
        receipt.get("schema") != "omni-program-baptism-receipt-v1"
        or receipt.get("status") != "PROGRAM_BAPTIZED"
        or receipt.get("decision") != "ACCEPTED"
    ):
        raise ModeBindingError("PROGRAM_BAPTISM_RECEIPT_INVALID")
    receipt_digest = _require_record_digest("PROGRAM_BAPTISM_RECEIPT", receipt)
    _require_exact_file_binding(
        "PROGRAM_BAPTISM_RECEIPT_PROGRAM_BINDING", receipt["program_binding"],
        path=program_path, sha256=program_sha256, size=program_bytes,
    )
    _require_exact_file_binding(
        "PROGRAM_BAPTISM_RECEIPT_COUNTERSIGN_BINDING",
        receipt["program_countersign_binding"], path=countersign_path,
        sha256=countersign_sha256, size=countersign_bytes,
    )
    _require_exact_file_binding(
        "PROGRAM_BAPTISM_RECEIPT_PM_DECISION_BINDING",
        receipt["pm_decision_binding"], path=decision_path,
        sha256=sha256_path(decision_path), size=decision_path.stat().st_size,
    )
    if any(receipt.get(field) != value for field, value in expected_common.items()):
        raise ModeBindingError("PROGRAM_BAPTISM_BINDING_MISMATCH")
    _require_nonempty_string("PROGRAM_BAPTISM_RECEIPT_CREATED_AT", receipt["created_at"])
    return decision_digest, receipt_digest, sovereign_id


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolved_list(
    label: str,
    values: object,
    *,
    binding_path: Path,
    require_directories: bool,
) -> list[Path]:
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(values) != len(set(values))
    ):
        raise ModeBindingError(f"{label}_INVALID")
    result = [
        _absolute_physical_path(value, label, strict=False) for value in values
    ]
    if len(result) != len(set(result)):
        raise ModeBindingError(f"{label}_INVALID")
    if require_directories and any(not path.is_dir() for path in result):
        raise ModeBindingError(f"{label}_DIRECTORY_MISSING")
    return result


def _validate_workspace_access(
    *,
    envelope_path: Path,
    envelope_sha256: str,
    activation_receipt_sha256: str,
    expected_task_id: str,
    expected_task_root: Path,
    expected_project_root: Path,
    expected_source_roots: list[Path],
    state: dict[str, object],
) -> WorkspaceEvidence:
    """Reproduce the non-destructive workspace grant and its retained probe."""
    bound_envelope_path = _absolute_physical_path(
        envelope_path, "WORKSPACE_ACCESS_ENVELOPE", strict=False,
    )
    envelope = _read_bound_json(
        bound_envelope_path,
        envelope_sha256,
        "WORKSPACE_ACCESS_ENVELOPE",
    )
    _require_exact_keys("WORKSPACE_ACCESS_ENVELOPE", envelope, WORKSPACE_ACCESS_KEYS)
    if envelope["schema"] != "omni-workspace-access-envelope-v1":
        raise ModeBindingError("WORKSPACE_ACCESS_SCHEMA_INVALID")
    if envelope["run_kind"] == "DRY_RUN":
        raise ModeBindingError("WORKSPACE_ACCESS_DRY_RUN_NOT_READY")
    if envelope["run_kind"] != "REAL":
        raise ModeBindingError("WORKSPACE_ACCESS_RUN_KIND_INVALID")
    if (
        envelope["status"] != "ACCESS_READY"
        or envelope["outcome"] != "ACCESS_GRANTED_NON_DESTRUCTIVE"
    ):
        raise ModeBindingError("AUTONOMY_UNAVAILABLE_NO_ACCESS")
    envelope_id = _require_identifier("WORKSPACE_ACCESS_ENVELOPE_ID", envelope["envelope_id"])
    _require_identifier("WORKSPACE_ACCESS_TASK_ID", expected_task_id)
    _require_identifier("WORKSPACE_ACCESS_ENVELOPE_TASK_ID", envelope["task_id"])
    envelope_digest = _require_record_digest("WORKSPACE_ACCESS_ENVELOPE", envelope)
    pair = state.get("session_pair")
    if not isinstance(pair, dict):
        raise ModeBindingError("WORKSPACE_ACCESS_SESSION_PAIR_MISSING")
    builder = pair.get("builder")
    verifier = pair.get("verifier")
    if not isinstance(builder, dict):
        raise ModeBindingError("WORKSPACE_ACCESS_BUILDER_MISSING")
    if not isinstance(verifier, dict):
        raise ModeBindingError("WORKSPACE_ACCESS_VERIFIER_MISSING")
    task_root = _absolute_physical_path(
        expected_task_root, "EXPECTED_TASK_ROOT", strict=False,
    )
    project_root = _absolute_physical_path(
        expected_project_root, "EXPECTED_PROJECT_ROOT", strict=False,
    )
    source_roots = [
        _absolute_physical_path(path, "EXPECTED_SOURCE_ROOT", strict=False)
        for path in expected_source_roots
    ]
    if not task_root.is_dir() or not project_root.is_dir():
        raise ModeBindingError("WORKSPACE_ACCESS_ROOT_MISSING")
    if not _is_within(project_root, task_root):
        raise ModeBindingError("WORKSPACE_ACCESS_SCOPE_ESCAPE")
    if not source_roots or any(not path.is_dir() for path in source_roots):
        raise ModeBindingError("WORKSPACE_ACCESS_SOURCE_ROOT_MISSING")
    observed_task_root = _resolve_binding_path(str(envelope["task_root"]), bound_envelope_path)
    observed_project_root = _resolve_binding_path(
        str(envelope["project_root"]), bound_envelope_path
    )
    observed_source_roots = _resolved_list(
        "WORKSPACE_ACCESS_SOURCE_ROOTS",
        envelope["source_roots"],
        binding_path=bound_envelope_path,
        require_directories=True,
    )
    participant_lanes: list[Path] = []
    for participant in (builder, verifier):
        write_lane = participant.get("write_lane")
        if not isinstance(write_lane, str) or not write_lane.strip():
            raise ModeBindingError("WORKSPACE_ACCESS_WRITE_LANE_INVALID")
        participant_lanes.append(
            _resolve_binding_path(write_lane, bound_envelope_path)
        )
    builder_lane, verifier_lane = participant_lanes
    observed_owned_lane = _resolve_binding_path(
        str(envelope["owned_lane_root"]), bound_envelope_path
    )
    if (
        envelope["activation_receipt_sha256"] != activation_receipt_sha256
        or envelope["task_id"] != expected_task_id
        or envelope["session_pair_sha256"] != pair.get("pair_sha256")
        or observed_task_root != task_root
        or observed_project_root != project_root
        or observed_source_roots != source_roots
    ):
        raise ModeBindingError("WORKSPACE_ACCESS_BINDING_MISMATCH")
    if (
        not _is_within(observed_owned_lane, project_root)
        or not _is_within(builder_lane, observed_owned_lane)
    ):
        raise ModeBindingError("WORKSPACE_ACCESS_SCOPE_ESCAPE")
    protected_write_roots = {observed_owned_lane, builder_lane, verifier_lane}
    if any(
        _is_within(source_root, protected)
        or _is_within(protected, source_root)
        for source_root in source_roots
        for protected in protected_write_roots
    ):
        raise ModeBindingError("WORKSPACE_SOURCE_WRITE_SCOPE_OVERLAP")
    if envelope["requested_capabilities"] != list(WORKSPACE_CAPABILITIES):
        raise ModeBindingError("WORKSPACE_ACCESS_CAPABILITY_REQUEST_INVALID")
    if envelope["granted_capabilities"] != list(WORKSPACE_CAPABILITIES):
        raise ModeBindingError("WORKSPACE_ACCESS_CAPABILITY_SHORTFALL")
    if envelope["non_grants"] != list(WORKSPACE_NON_GRANTS):
        raise ModeBindingError("WORKSPACE_ACCESS_NON_GRANTS_INVALID")
    if envelope["separate_authorizations_required"] != list(SEPARATE_AUTHORIZATIONS):
        raise ModeBindingError("WORKSPACE_ACCESS_SEPARATE_AUTH_INVALID")
    excluded = envelope["excluded_paths"]
    if (
        not isinstance(excluded, list)
        or any(not isinstance(path, str) or not path.strip() for path in excluded)
        or len(excluded) != len(set(excluded))
    ):
        raise ModeBindingError("WORKSPACE_ACCESS_EXCLUDED_PATHS_INVALID")
    resolved_excluded = [
        _resolve_binding_path(path, bound_envelope_path) for path in excluded
    ]
    if len(resolved_excluded) != len(set(resolved_excluded)):
        raise ModeBindingError("WORKSPACE_ACCESS_EXCLUDED_PATHS_INVALID")
    if any(
        not any(_is_within(path, root) for root in (project_root, *source_roots))
        for path in resolved_excluded
    ):
        raise ModeBindingError("WORKSPACE_ACCESS_SCOPE_ESCAPE")

    receipt_binding = envelope["probe_receipt_binding"]
    if not isinstance(receipt_binding, dict):
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_BINDING_INVALID")
    _require_exact_keys("WORKSPACE_PROBE_RECEIPT_BINDING", receipt_binding, FILE_BINDING_KEYS)
    receipt_path = _resolve_binding_path(
        str(receipt_binding["path"]), bound_envelope_path
    )
    if not receipt_path.is_file():
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_FILE_MISSING")
    if receipt_binding["bytes"] != receipt_path.stat().st_size:
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_BYTES_MISMATCH")
    receipt_sha256 = sha256_path(receipt_path)
    if receipt_binding["sha256"] != receipt_sha256:
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_SHA256_MISMATCH")
    probe_control_root = project_root / ".omni" / "access-probes"
    if not probe_control_root.is_dir() or probe_control_root.is_symlink():
        raise ModeBindingError("WORKSPACE_PROBE_CONTROL_ROOT_INVALID")
    probe_root = probe_control_root.resolve()
    if not _is_within(receipt_path, probe_root):
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_SCOPE_ESCAPE")
    receipt = _read_bound_json(
        receipt_path,
        receipt_sha256,
        "WORKSPACE_PROBE_RECEIPT",
    )
    _require_exact_keys("WORKSPACE_PROBE_RECEIPT", receipt, WORKSPACE_PROBE_RECEIPT_KEYS)
    if receipt["schema"] != "omni-workspace-access-probe-receipt-v1":
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_SCHEMA_INVALID")
    if receipt["status"] != "CREATE_ONCE_PROBE_RETAINED":
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_STATUS_INVALID")
    _require_identifier("WORKSPACE_PROBE_RECEIPT_ID", receipt["receipt_id"])
    receipt_digest = _require_record_digest("WORKSPACE_PROBE_RECEIPT", receipt)
    if (
        receipt["envelope_id"] != envelope_id
        or receipt["activation_receipt_sha256"] != activation_receipt_sha256
        or receipt["task_id"] != expected_task_id
        or receipt["session_pair_sha256"] != pair.get("pair_sha256")
        or _resolve_binding_path(str(receipt["task_root"]), receipt_path) != task_root
        or _resolve_binding_path(str(receipt["project_root"]), receipt_path) != project_root
        or _resolved_list(
            "WORKSPACE_PROBE_SOURCE_ROOTS",
            receipt["source_roots"],
            binding_path=receipt_path,
            require_directories=True,
        ) != source_roots
        or _resolve_binding_path(str(receipt["owned_lane_root"]), receipt_path)
        != observed_owned_lane
        or receipt["capabilities"] != list(WORKSPACE_CAPABILITIES)
        or receipt["create_once"] is not True
        or receipt["overwritten"] is not False
        or receipt["retained"] is not True
    ):
        raise ModeBindingError("WORKSPACE_PROBE_RECEIPT_BINDING_MISMATCH")
    probe_path = _resolve_binding_path(str(receipt["probe_path"]), receipt_path)
    if not _is_within(probe_path, probe_root):
        raise ModeBindingError("WORKSPACE_PROBE_SCOPE_ESCAPE")
    if not probe_path.is_file():
        raise ModeBindingError("WORKSPACE_PROBE_FILE_MISSING")
    if receipt["probe_bytes"] != probe_path.stat().st_size:
        raise ModeBindingError("WORKSPACE_PROBE_BYTES_MISMATCH")
    probe_sha256 = sha256_path(probe_path)
    if receipt["probe_sha256"] != probe_sha256:
        raise ModeBindingError("WORKSPACE_PROBE_SHA256_MISMATCH")
    read_proofs = receipt["read_proofs"]
    if not isinstance(read_proofs, list) or len(read_proofs) != len(source_roots):
        raise ModeBindingError("WORKSPACE_READ_PROOFS_INVALID")
    proof_paths = {receipt_path, probe_path}
    for source_root, proof in zip(source_roots, read_proofs, strict=True):
        if not isinstance(proof, dict):
            raise ModeBindingError("WORKSPACE_READ_PROOF_BINDING_INVALID")
        _require_exact_keys("WORKSPACE_READ_PROOF", proof, FILE_BINDING_KEYS)
        proof_path = _resolve_binding_path(str(proof["path"]), receipt_path)
        if not _is_within(proof_path, source_root):
            raise ModeBindingError("WORKSPACE_READ_PROOF_SCOPE_ESCAPE")
        if any(_is_within(proof_path, protected) for protected in protected_write_roots):
            raise ModeBindingError("WORKSPACE_READ_PROOF_SELF_AUTHORED")
        if proof_path in proof_paths:
            raise ModeBindingError("WORKSPACE_ACCESS_SCOPE_REPLAY")
        proof_paths.add(proof_path)
        if not proof_path.is_file():
            raise ModeBindingError("WORKSPACE_READ_PROOF_FILE_MISSING")
        if proof["bytes"] != proof_path.stat().st_size:
            raise ModeBindingError("WORKSPACE_READ_PROOF_BYTES_MISMATCH")
        if proof["sha256"] != sha256_path(proof_path):
            raise ModeBindingError("WORKSPACE_READ_PROOF_SHA256_MISMATCH")
    if state.get("workspace_access_envelope") != envelope:
        raise ModeBindingError("WORKSPACE_ACCESS_STATE_BINDING_MISMATCH")
    return WorkspaceEvidence(
        envelope_id=envelope_id,
        envelope_sha256=sha256_path(bound_envelope_path),
        envelope_record_digest=envelope_digest,
        probe_receipt_sha256=receipt_sha256,
        probe_receipt_record_digest=receipt_digest,
        probe_sha256=probe_sha256,
    )


def _activation_projection(value: dict[str, object]) -> dict[str, object]:
    fields = (
        "schema", "status", "activation_path", "task_scope", "run_kind",
        "effect_policy", "activation_grants", "activation_non_grants",
        "knowledge_available", "skill_invoked", "effect_authorized",
        "activation_level", "modules_used", "authority_grants",
        "artifact_grants", "requested_effects", "effect_grants", "non_grants",
        "access_envelope_identity",
        "intake_allowed", "mode_selection_allowed", "mode_gate",
        "next_gate",
    )
    try:
        return {field: value[field] for field in fields}
    except KeyError as exc:
        raise ModeBindingError(f"ACTIVATION_RECEIPT_FIELD_MISSING:{exc.args[0]}") from exc


def verify_mode_evidence(
    *,
    activation_decision: dict[str, object],
    activation_receipt_path: Path,
    intake_state_path: Path,
    intake_state_sha256: str,
    program_path: Path,
    program_sha256: str,
    program_countersign_path: Path,
    program_countersign_sha256: str,
    program_baptism_decision_path: Path,
    program_baptism_decision_sha256: str,
    program_baptism_receipt_path: Path,
    program_baptism_receipt_sha256: str,
    expected_sovereign_id: str,
    workspace_access_envelope_path: Path | None = None,
    workspace_access_envelope_sha256: str | None = None,
    expected_task_id: str | None = None,
    expected_task_root: Path | None = None,
    expected_project_root: Path | None = None,
    expected_source_roots: list[Path] | None = None,
) -> ModeEvidence:
    """Reproduce every Mode prerequisite from bytes, never narrative flags."""
    if (
        activation_decision.get("status") != "ACTIVATION_ALLOWED"
        or activation_decision.get("activation_level") != "OMNI_FULL"
        or activation_decision.get("skill_invoked") is not True
        or activation_decision.get("authority_grants")
        != ["METHOD_USE", "FULL_ORCHESTRATION"]
        or activation_decision.get("effect_authorized") is not False
        or activation_decision.get("effect_grants") != []
    ):
        raise ModeBindingError("FULL_ACTIVATION_RECEIPT_REQUIRED")
    state_path = _absolute_physical_path(
        intake_state_path, "INTAKE_STATE", strict=False,
    )
    state = _read_bound_json(state_path, intake_state_sha256, "INTAKE_STATE")
    if not verify(state):
        raise ModeBindingError("INTAKE_STATE_RECORD_DIGEST_INVALID")
    if state.get("phase") != "INTAKE_READY" or state.get("status") != "READY":
        raise ModeBindingError("INTAKE_STATE_NOT_READY")
    try:
        validate_instance(state)
    except ProtocolError as exc:
        raise ModeBindingError(f"INTAKE_STATE_SEMANTIC_INVALID:{exc}") from exc
    if state.get("profile") != "GODMODE":
        raise ModeBindingError("INTAKE_PROFILE_NOT_QUALIFIED")
    closure = state.get("critical_closure")
    if not isinstance(closure, dict) or closure.get("status") != "CLOSED":
        raise ModeBindingError("INTAKE_CRITICAL_CLOSURE_NOT_CLOSED")
    proposal = state.get("intake_proposal")
    if not isinstance(proposal, dict) or proposal.get("status") != "DUAL_READBACK_ACKED":
        raise ModeBindingError("INTAKE_PROPOSAL_NOT_DUAL_ACKED")

    binding = state.get("activation_binding")
    if not isinstance(binding, dict):
        raise ModeBindingError("ACTIVATION_BINDING_MISSING")
    receipt_path = _absolute_physical_path(
        activation_receipt_path, "ACTIVATION_RECEIPT", strict=False,
    )
    if _resolve_binding_path(str(binding.get("path", "")), state_path) != receipt_path:
        raise ModeBindingError("ACTIVATION_BINDING_PATH_MISMATCH")
    if not receipt_path.is_file():
        raise ModeBindingError("ACTIVATION_RECEIPT_FILE_MISSING")
    if binding.get("bytes") != receipt_path.stat().st_size:
        raise ModeBindingError("ACTIVATION_BINDING_BYTES_MISMATCH")
    receipt_sha256 = sha256_path(receipt_path)
    if binding.get("sha256") != receipt_sha256:
        raise ModeBindingError("ACTIVATION_BINDING_SHA256_MISMATCH")
    if binding.get("receipt_outcome") != "ACCEPTED":
        raise ModeBindingError("ACTIVATION_BINDING_OUTCOME_INVALID")
    try:
        receipt = strict_json(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModeBindingError(f"ACTIVATION_RECEIPT_JSON_INVALID:{type(exc).__name__}") from exc
    if not isinstance(receipt, dict):
        raise ModeBindingError("ACTIVATION_RECEIPT_JSON_OBJECT_REQUIRED")
    if receipt.get("status") != "ACTIVATION_ALLOWED" or receipt.get("activation_allowed") is not True:
        raise ModeBindingError("ACTIVATION_RECEIPT_NOT_ALLOWED")

    expected_binding = {
        "schema": binding.get("decision_schema"),
        "status": binding.get("decision_status"),
        "activation_path": binding.get("activation_path"),
        "task_scope": binding.get("task_scope"),
        "run_kind": binding.get("run_kind"),
        "effect_policy": binding.get("effect_policy"),
        "activation_grants": binding.get("activation_grants"),
        "activation_non_grants": binding.get("activation_non_grants"),
        "knowledge_available": binding.get("knowledge_available"),
        "skill_invoked": binding.get("skill_invoked"),
        "effect_authorized": binding.get("effect_authorized"),
        "activation_level": binding.get("activation_level"),
        "modules_used": binding.get("modules_used"),
        "authority_grants": binding.get("authority_grants"),
        "artifact_grants": binding.get("artifact_grants"),
        "requested_effects": binding.get("requested_effects"),
        "effect_grants": binding.get("effect_grants"),
        "non_grants": binding.get("non_grants"),
        "access_envelope_identity": binding.get("access_envelope_identity"),
        "intake_allowed": binding.get("intake_allowed"),
        "mode_selection_allowed": binding.get("mode_selection_allowed"),
        "mode_gate": binding.get("mode_gate"),
        "next_gate": binding.get("next_gate"),
    }
    receipt_projection = _activation_projection(receipt)
    if receipt_projection != expected_binding:
        raise ModeBindingError("ACTIVATION_RECEIPT_BINDING_MISMATCH")
    if receipt_projection != _activation_projection(activation_decision):
        raise ModeBindingError("ACTIVATION_DECISION_REPLAY_MISMATCH")
    if state.get("run_kind") != activation_decision.get("run_kind"):
        raise ModeBindingError("ACTIVATION_DECISION_REPLAY_MISMATCH")

    if state.get("topology") == "SOLO_DUAL_HAT":
        pair = state.get("session_pair")
        if not isinstance(pair, dict):
            raise ModeBindingError("SOLO_SESSION_PAIR_MISSING")
        builder = pair.get("builder")
        verifier = pair.get("verifier")
        if (
            not isinstance(builder, dict)
            or not isinstance(verifier, dict)
            or builder.get("identity") != verifier.get("identity")
        ):
            raise ModeBindingError("SOLO_SOVEREIGN_IDENTITY_MISMATCH")

    program_path = _absolute_physical_path(program_path, "PROGRAM", strict=False)
    program = _read_bound_json(program_path, program_sha256, "PROGRAM")
    program_bytes = program_path.stat().st_size
    (
        program_id, task_id, knowledge_pipeline_id, program_record_digest,
    ) = _validate_fused_program(program, state)

    countersign_path = _absolute_physical_path(
        program_countersign_path, "PROGRAM_COUNTERSIGN", strict=False,
    )
    countersign = _read_bound_json(
        countersign_path,
        program_countersign_sha256,
        "PROGRAM_COUNTERSIGN",
    )
    countersign_record_digest = _validate_program_countersign(
        countersign,
        receipt_path=countersign_path,
        program_path=program_path,
        program=program,
        program_sha256=sha256_path(program_path),
        program_bytes=program_bytes,
        program_id=program_id,
        program_record_digest=program_record_digest,
        task_id=task_id,
        knowledge_pipeline_id=knowledge_pipeline_id,
        state=state,
    )
    baptism_decision_path = _absolute_physical_path(
        program_baptism_decision_path, "PROGRAM_BAPTISM_DECISION", strict=False,
    )
    baptism_decision = _read_bound_json(
        baptism_decision_path, program_baptism_decision_sha256,
        "PROGRAM_BAPTISM_DECISION",
    )
    baptism_receipt_path = _absolute_physical_path(
        program_baptism_receipt_path, "PROGRAM_BAPTISM_RECEIPT", strict=False,
    )
    baptism_receipt = _read_bound_json(
        baptism_receipt_path, program_baptism_receipt_sha256,
        "PROGRAM_BAPTISM_RECEIPT",
    )
    (
        baptism_decision_record_digest,
        baptism_receipt_record_digest,
        sovereign_id,
    ) = _validate_program_baptism(
        decision=baptism_decision, decision_path=baptism_decision_path,
        receipt=baptism_receipt, receipt_path=baptism_receipt_path,
        program_path=program_path, program_sha256=sha256_path(program_path),
        program_bytes=program_bytes, program_id=program_id,
        program_record_digest=program_record_digest,
        countersign_path=countersign_path,
        countersign_sha256=sha256_path(countersign_path),
        countersign_bytes=countersign_path.stat().st_size,
        countersign_record_digest=countersign_record_digest,
        task_id=task_id, knowledge_pipeline_id=knowledge_pipeline_id,
        session_pair_sha256=str(state["session_pair"]["pair_sha256"]),
        expected_sovereign_id=expected_sovereign_id, state=state,
    )
    workspace = None
    if workspace_access_envelope_path is not None:
        if (
            workspace_access_envelope_sha256 is None
            or expected_task_id is None
            or expected_task_root is None
            or expected_project_root is None
            or not expected_source_roots
        ):
            raise ModeBindingError("WORKSPACE_ACCESS_BINDING_ARGUMENTS_INCOMPLETE")
        workspace = _validate_workspace_access(
            envelope_path=workspace_access_envelope_path,
            envelope_sha256=workspace_access_envelope_sha256,
            activation_receipt_sha256=receipt_sha256,
            expected_task_id=expected_task_id,
            expected_task_root=expected_task_root,
            expected_project_root=expected_project_root,
            expected_source_roots=expected_source_roots,
            state=state,
        )

    return ModeEvidence(
        intake_state_sha256=sha256_path(state_path),
        intake_record_digest=str(state["record_digest"]),
        activation_receipt_sha256=receipt_sha256,
        program_sha256=sha256_path(program_path),
        program_bytes=program_bytes,
        program_record_digest=program_record_digest,
        program_countersign_sha256=sha256_path(countersign_path),
        program_countersign_bytes=countersign_path.stat().st_size,
        program_countersign_record_digest=countersign_record_digest,
        program_baptism_decision_sha256=sha256_path(baptism_decision_path),
        program_baptism_decision_bytes=baptism_decision_path.stat().st_size,
        program_baptism_decision_record_digest=baptism_decision_record_digest,
        program_baptism_receipt_sha256=sha256_path(baptism_receipt_path),
        program_baptism_receipt_bytes=baptism_receipt_path.stat().st_size,
        program_baptism_receipt_record_digest=baptism_receipt_record_digest,
        sovereign_id=sovereign_id,
        workspace_access_ready=workspace is not None,
        workspace_access_envelope_id=workspace.envelope_id if workspace else None,
        workspace_access_envelope_sha256=workspace.envelope_sha256 if workspace else None,
        workspace_access_envelope_record_digest=(
            workspace.envelope_record_digest if workspace else None
        ),
        workspace_probe_receipt_sha256=(
            workspace.probe_receipt_sha256 if workspace else None
        ),
        workspace_probe_receipt_record_digest=(
            workspace.probe_receipt_record_digest if workspace else None
        ),
        workspace_probe_sha256=workspace.probe_sha256 if workspace else None,
    )


def select(
    *,
    turns: int,
    durable_state: bool,
    midstream_judgment: bool,
    parallel_value: bool,
    independent_verifier: bool,
    invocation_allowed: bool,
    evidence: ModeEvidence | None,
) -> str:
    _require_bool("invocation_allowed", invocation_allowed)
    if not invocation_allowed:
        return "BLOCKED_BEFORE_MODE_SELECTION"
    if evidence is None:
        return "MODE_BEFORE_PROGRAM"
    if not evidence.workspace_access_ready:
        return "MODE_BEFORE_ACCESS"
    if turns <= 1 and not durable_state and not midstream_judgment:
        return "MODE_A_DIRECT"
    if not midstream_judgment and not parallel_value and not independent_verifier:
        return "MODE_B_DETERMINISTIC_WORKFLOW"
    return "MODE_C_GOVERNED_AGENTIC"


def _print(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main() -> int:
    parser = JsonArgumentParser()
    parser.add_argument("--turns", type=int, default=1)
    parser.add_argument("--durable-state", action="store_true")
    parser.add_argument("--midstream-judgment", action="store_true")
    parser.add_argument("--parallel-value", action="store_true")
    parser.add_argument("--independent-verifier", action="store_true")
    parser.add_argument("--explicit-user-request", action="store_true")
    parser.add_argument("--complexity-warrants-omni", action="store_true")
    parser.add_argument("--consent", default="absent")
    parser.add_argument("--ground", action="append", default=[])
    parser.add_argument("--run-kind")
    parser.add_argument("--activation-level")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--effect-grant", action="append", default=[])
    parser.add_argument("--activation-receipt", type=Path)
    parser.add_argument("--intake-state", type=Path)
    parser.add_argument("--intake-state-sha256")
    parser.add_argument("--program", type=Path)
    parser.add_argument("--program-sha256")
    parser.add_argument("--program-countersign", type=Path)
    parser.add_argument("--program-countersign-sha256")
    parser.add_argument("--program-baptism-decision", type=Path)
    parser.add_argument("--program-baptism-decision-sha256")
    parser.add_argument("--program-baptism-receipt", type=Path)
    parser.add_argument("--program-baptism-receipt-sha256")
    parser.add_argument("--expected-sovereign-id")
    parser.add_argument("--workspace-access-envelope", type=Path)
    parser.add_argument("--workspace-access-envelope-sha256")
    parser.add_argument("--task-id")
    parser.add_argument("--task-root", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--source-root", action="append", type=Path, default=[])
    try:
        args = parser.parse_args()
        if args.turns < 1:
            _print({"status": "BLOCKED", "reason_code": "TURNS_MUST_BE_POSITIVE"})
            return 2
        decision = decide_invocation(
            explicit_user_request=args.explicit_user_request,
            complexity_warrants_omni=args.complexity_warrants_omni,
            consent_state=args.consent.upper(),
            grounds=args.ground,
            run_kind=args.run_kind,
            activation_level=args.activation_level,
            modules=args.module,
            effect_grants=args.effect_grant,
        )
        output = dict(decision)
        if decision["status"] == "ACTIVATION_ALLOWED":
            core_binding_values = (
                args.activation_receipt,
                args.intake_state,
                args.intake_state_sha256,
                args.program,
                args.program_sha256,
                args.program_countersign,
                args.program_countersign_sha256,
                args.program_baptism_decision,
                args.program_baptism_decision_sha256,
                args.program_baptism_receipt,
                args.program_baptism_receipt_sha256,
                args.expected_sovereign_id,
            )
            access_binding_values = (
                args.workspace_access_envelope,
                args.workspace_access_envelope_sha256,
                args.task_id,
                args.task_root,
                args.project_root,
            )
            access_requested = any(value is not None for value in access_binding_values) or bool(
                args.source_root
            )
            if access_requested and not all(
                value is not None for value in access_binding_values
            ):
                raise ModeBindingError("WORKSPACE_ACCESS_BINDING_ARGUMENTS_INCOMPLETE")
            if access_requested and not args.source_root:
                raise ModeBindingError("WORKSPACE_ACCESS_BINDING_ARGUMENTS_INCOMPLETE")
            if any(value is not None for value in core_binding_values) and not all(
                value is not None for value in core_binding_values
            ):
                raise ModeBindingError("MODE_BINDING_ARGUMENTS_INCOMPLETE")
            if access_requested and not all(
                value is not None for value in core_binding_values
            ):
                raise ModeBindingError("MODE_BINDING_ARGUMENTS_INCOMPLETE")
            evidence = None
            if all(value is not None for value in core_binding_values):
                evidence = verify_mode_evidence(
                    activation_decision=decision,
                    activation_receipt_path=args.activation_receipt,
                    intake_state_path=args.intake_state,
                    intake_state_sha256=args.intake_state_sha256,
                    program_path=args.program,
                    program_sha256=args.program_sha256,
                    program_countersign_path=args.program_countersign,
                    program_countersign_sha256=args.program_countersign_sha256,
                    program_baptism_decision_path=args.program_baptism_decision,
                    program_baptism_decision_sha256=args.program_baptism_decision_sha256,
                    program_baptism_receipt_path=args.program_baptism_receipt,
                    program_baptism_receipt_sha256=args.program_baptism_receipt_sha256,
                    expected_sovereign_id=args.expected_sovereign_id,
                    workspace_access_envelope_path=(
                        args.workspace_access_envelope if access_requested else None
                    ),
                    workspace_access_envelope_sha256=(
                        args.workspace_access_envelope_sha256 if access_requested else None
                    ),
                    expected_task_id=args.task_id if access_requested else None,
                    expected_task_root=args.task_root if access_requested else None,
                    expected_project_root=args.project_root if access_requested else None,
                    expected_source_roots=args.source_root if access_requested else None,
                )
            mode = select(
                turns=args.turns,
                durable_state=args.durable_state,
                midstream_judgment=args.midstream_judgment,
                parallel_value=args.parallel_value,
                independent_verifier=args.independent_verifier,
                invocation_allowed=True,
                evidence=evidence,
            )
            if mode == "MODE_BEFORE_PROGRAM":
                output["mode_gate"] = mode
                output["next_gate"] = "GUIDED_INTAKE"
            elif mode == "MODE_BEFORE_ACCESS":
                output["mode_gate"] = mode
                output["next_gate"] = "WORKSPACE_ACCESS_ENVELOPE"
                output["intake_state_sha256"] = evidence.intake_state_sha256
                output["intake_record_digest"] = evidence.intake_record_digest
                output["activation_receipt_sha256"] = evidence.activation_receipt_sha256
                output["program_sha256"] = evidence.program_sha256
                output["program_bytes"] = evidence.program_bytes
                output["program_record_digest"] = evidence.program_record_digest
                output["program_countersign_sha256"] = evidence.program_countersign_sha256
                output["program_countersign_bytes"] = evidence.program_countersign_bytes
                output["program_countersign_record_digest"] = (
                    evidence.program_countersign_record_digest
                )
                output["program_baptism_decision_sha256"] = (
                    evidence.program_baptism_decision_sha256
                )
                output["program_baptism_decision_bytes"] = (
                    evidence.program_baptism_decision_bytes
                )
                output["program_baptism_decision_record_digest"] = (
                    evidence.program_baptism_decision_record_digest
                )
                output["program_baptism_receipt_sha256"] = (
                    evidence.program_baptism_receipt_sha256
                )
                output["program_baptism_receipt_bytes"] = (
                    evidence.program_baptism_receipt_bytes
                )
                output["program_baptism_receipt_record_digest"] = (
                    evidence.program_baptism_receipt_record_digest
                )
                output["program_baptism_status"] = "PROGRAM_BAPTIZED"
                output["sovereign_id"] = evidence.sovereign_id
            else:
                output["mode"] = mode
                output["mode_gate"] = "MODE_SELECTED"
                output["mode_selection_allowed"] = True
                output["intake_state_sha256"] = evidence.intake_state_sha256
                output["intake_record_digest"] = evidence.intake_record_digest
                output["activation_receipt_sha256"] = evidence.activation_receipt_sha256
                output["program_sha256"] = evidence.program_sha256
                output["program_bytes"] = evidence.program_bytes
                output["program_record_digest"] = evidence.program_record_digest
                output["program_countersign_sha256"] = evidence.program_countersign_sha256
                output["program_countersign_bytes"] = evidence.program_countersign_bytes
                output["program_countersign_record_digest"] = (
                    evidence.program_countersign_record_digest
                )
                output["program_baptism_decision_sha256"] = (
                    evidence.program_baptism_decision_sha256
                )
                output["program_baptism_decision_bytes"] = (
                    evidence.program_baptism_decision_bytes
                )
                output["program_baptism_decision_record_digest"] = (
                    evidence.program_baptism_decision_record_digest
                )
                output["program_baptism_receipt_sha256"] = (
                    evidence.program_baptism_receipt_sha256
                )
                output["program_baptism_receipt_bytes"] = (
                    evidence.program_baptism_receipt_bytes
                )
                output["program_baptism_receipt_record_digest"] = (
                    evidence.program_baptism_receipt_record_digest
                )
                output["program_baptism_status"] = "PROGRAM_BAPTIZED"
                output["sovereign_id"] = evidence.sovereign_id
                output["workspace_access_envelope_id"] = (
                    evidence.workspace_access_envelope_id
                )
                output["workspace_access_envelope_sha256"] = (
                    evidence.workspace_access_envelope_sha256
                )
                output["workspace_access_envelope_record_digest"] = (
                    evidence.workspace_access_envelope_record_digest
                )
                output["workspace_probe_receipt_sha256"] = (
                    evidence.workspace_probe_receipt_sha256
                )
                output["workspace_probe_receipt_record_digest"] = (
                    evidence.workspace_probe_receipt_record_digest
                )
                output["workspace_probe_sha256"] = evidence.workspace_probe_sha256
                output["access_envelope_identity"] = (
                    evidence.workspace_access_envelope_id
                )
                output["artifact_grants"] = list(WORKSPACE_CAPABILITIES)
                output["effect_authorized"] = True
                output["effect_grants"] = ["CREATE_FILES"]
                output["non_grants"] = [*BASE_NON_GRANTS, "ARM_AUTOMATION"]
                output["next_gate"] = "MODE_SELECTED"
        elif decision["status"] != "MODULE_ACTIVATION_ALLOWED":
            output["mode_gate"] = "BLOCKED_BEFORE_MODE_SELECTION"
        _print(output)
        return 2 if decision["status"] == "BLOCKED" else 0
    except (OSError, TypeError, ValueError) as exc:
        _print({"status": "BLOCKED", "reason_code": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

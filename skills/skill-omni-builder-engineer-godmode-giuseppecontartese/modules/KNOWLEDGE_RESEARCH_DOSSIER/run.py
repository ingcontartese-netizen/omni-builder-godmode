"""Deterministic boundary for the KNOWLEDGE_RESEARCH_DOSSIER module.

The host performs material interpretation and web research.  This runtime
checks activation, separate authorities, physical file bindings, the
light/deep research delta, cumulative provenance, and the terminal outcome.
It never opens a network connection.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


MODULE_ID = "KNOWLEDGE_RESEARCH_DOSSIER"
MODULE_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = MODULE_DIR.parents[1]
AUTHORITY_SCHEMA_PATH = MODULE_DIR / "authority.schema.json"
RECORDS_SCHEMA_PATH = MODULE_DIR / "records.schema.json"
FIXED_OUTPUTS = (
    "MATERIAL_STUDY.json",
    "LIGHT_MAP.json",
    "DEEP_RESEARCH_RECEIPT.json",
    "SOURCE_MANIFEST.json",
    "DOSSIER.md",
    "MODULE_OUTCOME.json",
)
ACTIONS = (
    "READ_NAMED_SOURCES",
    "CREATE_FILES",
    "NETWORK_RESEARCH",
    "DOWNLOAD",
)


def _load_io_safe():
    path = PACKAGE_ROOT / "scripts" / "sentry" / "io_safe.py"
    spec = importlib.util.spec_from_file_location(
        "knowledge_research_dossier_io_safe", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("IO_SAFE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


IO = _load_io_safe()
PathSafetyError = IO.PathSafetyError


class ModuleContractError(ValueError):
    """One typed, fail-closed module contract violation."""


class StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ModuleContractError(f"CLI_ARGUMENT_INVALID:{message}")


def _topic_sha256(topic: str) -> str:
    if not topic or topic != topic.strip():
        raise ModuleContractError("TOPIC_REQUIRED")
    return IO.sha256_bytes(topic.encode("utf-8"))


def _record_digest(record: dict[str, Any]) -> str:
    unsigned = copy.deepcopy(record)
    unsigned.pop("record_digest", None)
    return IO.sha256_bytes(IO.canonical_json(unsigned).encode("utf-8"))


def seal_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with its canonical record digest populated."""
    sealed = copy.deepcopy(record)
    sealed["record_digest"] = _record_digest(sealed)
    return sealed


def _require_record_digest(record: dict[str, Any], code: str) -> None:
    if record.get("record_digest") != _record_digest(record):
        raise ModuleContractError(code)


def _schema(path: Path) -> dict[str, Any]:
    data, _ = IO.read_bound_bytes(path, label="MODULE_SCHEMA")
    value = IO.strict_json(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ModuleContractError("MODULE_SCHEMA_INVALID")
    Draft202012Validator.check_schema(value)
    return value


AUTHORITY_SCHEMA = _schema(AUTHORITY_SCHEMA_PATH)
RECORDS_SCHEMA = _schema(RECORDS_SCHEMA_PATH)
FORMAT_CHECKER = FormatChecker()


def _validate_schema(
    value: dict[str, Any], schema: dict[str, Any], code: str
) -> None:
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FORMAT_CHECKER
        ).iter_errors(value),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        raise ModuleContractError(f"{code}:{location}:{error.message}")


def _load_json(
    path: str | Path, label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    data, physical = IO.read_bound_bytes(path, label=label)
    try:
        value = IO.strict_json(data.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ModuleContractError(f"{label}_INVALID_JSON:{error}") from error
    if not isinstance(value, dict):
        raise ModuleContractError(f"{label}_OBJECT_REQUIRED")
    return value, {
        "path": str(physical),
        "bytes": len(data),
        "sha256": IO.sha256_bytes(data),
    }


def _path_key(value: str | Path) -> str:
    resolved = str(Path(value).resolve(strict=False))
    return resolved.casefold() if sys.platform == "win32" else resolved


def _same_binding(left: dict[str, Any], right: dict[str, Any]) -> bool:
    try:
        return (
            _path_key(left["path"]) == _path_key(right["path"])
            and left["bytes"] == right["bytes"]
            and left["sha256"] == right["sha256"]
        )
    except (KeyError, TypeError):
        return False


def _require_binding(
    observed: dict[str, Any], expected: dict[str, Any], code: str
) -> None:
    if not _same_binding(observed, expected):
        raise ModuleContractError(code)


def _live_binding(
    binding: dict[str, Any],
    *,
    allowed_roots: list[str | Path] | None = None,
    code: str,
) -> dict[str, Any]:
    try:
        data, physical = IO.read_bound_bytes(
            binding["path"],
            expected_bytes=binding["bytes"],
            expected_sha256=binding["sha256"],
            allowed_roots=allowed_roots,
            label=code,
        )
    except (KeyError, OSError, ValueError, PathSafetyError) as error:
        raise ModuleContractError(f"{code}:{error}") from error
    return {
        "path": str(physical),
        "bytes": len(data),
        "sha256": IO.sha256_bytes(data),
    }


def _parse_timestamp(value: str, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ModuleContractError(code) from error
    if parsed.tzinfo is None:
        raise ModuleContractError(code)
    return parsed.astimezone(timezone.utc)


def validate_activation(
    activation_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    activation, binding = _load_json(activation_path, "MODULE_ACTIVATION")
    expected = {
        "schema": "omni-invocation-decision-v2",
        "status": "MODULE_ACTIVATION_ALLOWED",
        "activation_level": "OMNI_MODULE",
        "run_kind": "REAL",
        "activation_allowed": True,
        "modules_used": [MODULE_ID],
        "intake_allowed": False,
        "effect_authorized": False,
        "effect_grants": [],
    }
    if any(activation.get(key) != value for key, value in expected.items()):
        raise ModuleContractError("MODULE_ACTIVATION_REQUIRED")
    return activation, binding


def validate_authority(
    authority_path: str | Path,
    *,
    action: str,
    activation_binding: dict[str, Any],
    run_id: str,
    topic_sha256: str,
    output_root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if action not in ACTIONS:
        raise ModuleContractError("UNKNOWN_AUTHORITY_ACTION")
    authority, binding = _load_json(authority_path, f"{action}_AUTHORITY")
    _validate_schema(authority, AUTHORITY_SCHEMA, "AUTHORITY_SCHEMA_INVALID")
    _require_record_digest(authority, "AUTHORITY_RECORD_DIGEST_INVALID")
    if authority["action"] != action:
        raise ModuleContractError(f"{action}_NOT_AUTHORIZED")
    if authority["run_id"] != run_id:
        raise ModuleContractError("AUTHORITY_RUN_BINDING_MISMATCH")
    if authority["topic_sha256"] != topic_sha256:
        raise ModuleContractError("AUTHORITY_TOPIC_BINDING_MISMATCH")
    _require_binding(
        authority["activation_binding"],
        activation_binding,
        "MODULE_ACTIVATION_BINDING_MISMATCH",
    )
    issued = _parse_timestamp(authority["issued_at"], "AUTHORITY_TIME_INVALID")
    expires = _parse_timestamp(authority["expires_at"], "AUTHORITY_TIME_INVALID")
    if issued >= expires:
        raise ModuleContractError("AUTHORITY_TIME_INVALID")
    if datetime.now(timezone.utc) > expires:
        raise ModuleContractError("AUTHORITY_EXPIRED")

    if action == "READ_NAMED_SOURCES":
        seen: set[str] = set()
        for source in authority["named_sources"]:
            key = _path_key(source["path"])
            if key in seen:
                raise ModuleContractError("NAMED_MATERIAL_IDENTITY_DUPLICATE")
            seen.add(key)
            _live_binding(source, code="MATERIAL_IDENTITY_DRIFT")
    elif action == "CREATE_FILES":
        if output_root is None:
            raise ModuleContractError("OUTPUT_ROOT_REQUIRED")
        root = IO.absolute_physical_path(output_root, "MODULE_OUTPUT_ROOT", strict=True)
        if not root.is_dir():
            raise ModuleContractError("OUTPUT_ROOT_REQUIRED")
        if _path_key(authority["output_root"]) != _path_key(root):
            raise ModuleContractError("CREATE_FILES_ROOT_MISMATCH")
        seen = set()
        for output in authority["output_paths"]:
            physical = IO.confine_path(
                output, root, label="AUTHORIZED_OUTPUT", strict=False
            )
            key = _path_key(physical)
            if key in seen:
                raise ModuleContractError("AUTHORIZED_OUTPUT_DUPLICATE")
            seen.add(key)
    elif action == "NETWORK_RESEARCH":
        if authority["capture_policy"] != "CAPTURE_MD_ONLY":
            raise ModuleContractError("NETWORK_CAPTURE_POLICY_INVALID")
    elif action == "DOWNLOAD":
        if output_root is None:
            raise ModuleContractError("OUTPUT_ROOT_REQUIRED")
        root = IO.absolute_physical_path(output_root, "MODULE_OUTPUT_ROOT", strict=True)
        quarantine = IO.confine_path(
            authority["quarantine_root"],
            root,
            label="DOWNLOAD_QUARANTINE",
            strict=True,
        )
        if not quarantine.is_dir():
            raise ModuleContractError("DOWNLOAD_QUARANTINE_INVALID")
    return authority, binding


def gate_effect(
    *,
    activation_path: str | Path,
    authority_path: str | Path,
    action: str,
    topic: str,
    run_id: str,
    output_root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, activation_binding = validate_activation(activation_path)
    return validate_authority(
        authority_path,
        action=action,
        activation_binding=activation_binding,
        run_id=run_id,
        topic_sha256=_topic_sha256(topic),
        output_root=output_root,
    )


def _load_stage(
    path: Path, expected_schema: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    record, binding = _load_json(path, expected_schema.upper())
    _validate_schema(record, RECORDS_SCHEMA, "MODULE_RECORD_SCHEMA_INVALID")
    if record.get("schema") != expected_schema:
        raise ModuleContractError("MODULE_RECORD_TYPE_MISMATCH")
    _require_record_digest(record, "MODULE_RECORD_DIGEST_INVALID")
    return record, binding


def _require_common(
    record: dict[str, Any],
    *,
    run_id: str,
    topic: str,
    topic_sha256: str,
    activation_sha256: str,
) -> None:
    expected = {
        "module_id": MODULE_ID,
        "run_id": run_id,
        "topic": topic,
        "topic_sha256": topic_sha256,
        "activation_sha256": activation_sha256,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ModuleContractError("MODULE_RECORD_BINDING_MISMATCH")


def _unique_map(
    values: list[dict[str, Any]], key_name: str, code: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        key = value[key_name]
        if key in result:
            raise ModuleContractError(code)
        result[key] = value
    return result


def _authorized_output_keys(authority: dict[str, Any]) -> set[str]:
    return {_path_key(path) for path in authority["output_paths"]}


def _require_output_authorized(
    binding: dict[str, Any], authorized: set[str]
) -> None:
    if _path_key(binding["path"]) not in authorized:
        raise ModuleContractError("CREATE_FILES_PATH_NOT_AUTHORIZED")


def _validate_capture_bindings(
    record: dict[str, Any],
    *,
    output_root: Path,
    authorized_outputs: set[str],
) -> None:
    for item in [*record["queries"], *record["sources"]]:
        binding = item["capture_binding"]
        if Path(binding["path"]).suffix.lower() != ".md":
            raise ModuleContractError("WEB_CAPTURE_MARKDOWN_REQUIRED")
        observed = _live_binding(
            binding,
            allowed_roots=[output_root],
            code="WEB_CAPTURE_READBACK_FAILED",
        )
        _require_output_authorized(observed, authorized_outputs)


def _canonical_records(
    values: list[dict[str, Any]], key_name: str
) -> dict[str, str]:
    return {
        value[key_name]: IO.canonical_json(value)
        for value in values
    }


def _validate_acquisitions(
    acquisitions: list[dict[str, Any]],
    *,
    download_authority: dict[str, Any],
    output_root: Path,
    authorized_outputs: set[str],
    known_source_ids: set[str],
) -> None:
    allowed_locators = set(download_authority["allowed_locators"])
    quarantine_root = IO.absolute_physical_path(
        download_authority["quarantine_root"],
        "DOWNLOAD_QUARANTINE",
        strict=True,
    )
    seen: set[str] = set()
    for acquisition in acquisitions:
        if acquisition["acquisition_id"] in seen:
            raise ModuleContractError("DOWNLOAD_ACQUISITION_DUPLICATE")
        seen.add(acquisition["acquisition_id"])
        if acquisition["source_id"] not in known_source_ids:
            raise ModuleContractError("DOWNLOAD_SOURCE_UNKNOWN")
        if acquisition["origin_locator"] not in allowed_locators:
            raise ModuleContractError("DOWNLOAD_LOCATOR_NOT_AUTHORIZED")
        for field, roots in (
            ("content_binding", [quarantine_root]),
            ("rights_evidence_binding", [output_root]),
            ("scan_receipt_binding", [output_root]),
        ):
            observed = _live_binding(
                acquisition[field],
                allowed_roots=roots,
                code="DOWNLOAD_QUARANTINE_INVALID",
            )
            _require_output_authorized(observed, authorized_outputs)


def _validate_run(
    *,
    activation_path: str | Path,
    read_authority_path: str | Path,
    write_authority_path: str | Path,
    network_authority_path: str | Path,
    topic: str,
    run_id: str,
    output_root: str | Path,
    download_authority_path: str | Path | None = None,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    topic_sha256 = _topic_sha256(topic)
    _, activation_binding = validate_activation(activation_path)
    root = IO.absolute_physical_path(
        output_root, "MODULE_OUTPUT_ROOT", strict=True
    )
    if not root.is_dir():
        raise ModuleContractError("OUTPUT_ROOT_REQUIRED")

    read_authority, read_binding = validate_authority(
        read_authority_path,
        action="READ_NAMED_SOURCES",
        activation_binding=activation_binding,
        run_id=run_id,
        topic_sha256=topic_sha256,
    )
    write_authority, write_binding = validate_authority(
        write_authority_path,
        action="CREATE_FILES",
        activation_binding=activation_binding,
        run_id=run_id,
        topic_sha256=topic_sha256,
        output_root=root,
    )
    network_authority, network_binding = validate_authority(
        network_authority_path,
        action="NETWORK_RESEARCH",
        activation_binding=activation_binding,
        run_id=run_id,
        topic_sha256=topic_sha256,
    )
    authority_ids = {
        read_authority["authority_id"],
        write_authority["authority_id"],
        network_authority["authority_id"],
    }
    if len(authority_ids) != 3:
        raise ModuleContractError("SEPARATE_AUTHORITY_RECORDS_REQUIRED")

    download_authority: dict[str, Any] | None = None
    download_binding: dict[str, Any] | None = None
    if download_authority_path is not None:
        download_authority, download_binding = validate_authority(
            download_authority_path,
            action="DOWNLOAD",
            activation_binding=activation_binding,
            run_id=run_id,
            topic_sha256=topic_sha256,
            output_root=root,
        )
        if download_authority["authority_id"] in authority_ids:
            raise ModuleContractError("SEPARATE_AUTHORITY_RECORDS_REQUIRED")

    authorized_outputs = _authorized_output_keys(write_authority)
    for name in FIXED_OUTPUTS:
        if _path_key(root / name) not in authorized_outputs:
            raise ModuleContractError("CREATE_FILES_PATH_NOT_AUTHORIZED")

    material, material_binding = _load_stage(
        root / "MATERIAL_STUDY.json", "omni-module-material-study-v1"
    )
    light, light_binding = _load_stage(
        root / "LIGHT_MAP.json", "omni-module-light-map-v1"
    )
    deep, deep_binding = _load_stage(
        root / "DEEP_RESEARCH_RECEIPT.json",
        "omni-module-deep-research-receipt-v1",
    )
    manifest, manifest_binding = _load_stage(
        root / "SOURCE_MANIFEST.json", "omni-module-source-manifest-v1"
    )
    for binding in (
        material_binding,
        light_binding,
        deep_binding,
        manifest_binding,
    ):
        _require_output_authorized(binding, authorized_outputs)
    for record in (material, light, deep, manifest):
        _require_common(
            record,
            run_id=run_id,
            topic=topic,
            topic_sha256=topic_sha256,
            activation_sha256=activation_binding["sha256"],
        )

    material_map = _unique_map(
        material["named_materials"],
        "material_id",
        "NAMED_MATERIAL_IDENTITY_DUPLICATE",
    )
    recorded_material_bindings = {
        (
            _path_key(item["binding"]["path"]),
            item["binding"]["bytes"],
            item["binding"]["sha256"],
        )
        for item in material_map.values()
    }
    authorized_material_bindings = {
        (
            _path_key(item["path"]),
            item["bytes"],
            item["sha256"],
        )
        for item in read_authority["named_sources"]
    }
    if recorded_material_bindings != authorized_material_bindings:
        raise ModuleContractError("READ_NAMED_SOURCES_SCOPE_MISMATCH")
    for item in material_map.values():
        _live_binding(item["binding"], code="MATERIAL_IDENTITY_DRIFT")

    _require_binding(
        light["material_study_binding"],
        material_binding,
        "LIGHT_MAP_ARTIFACT_CHAIN_MISMATCH",
    )
    _require_binding(
        deep["material_study_binding"],
        material_binding,
        "DEEP_RESEARCH_ARTIFACT_CHAIN_MISMATCH",
    )
    _require_binding(
        deep["light_map_binding"],
        light_binding,
        "DEEP_RESEARCH_ARTIFACT_CHAIN_MISMATCH",
    )
    _require_binding(
        manifest["material_study_binding"],
        material_binding,
        "SOURCE_MANIFEST_ARTIFACT_CHAIN_MISMATCH",
    )
    _require_binding(
        manifest["light_map_binding"],
        light_binding,
        "SOURCE_MANIFEST_ARTIFACT_CHAIN_MISMATCH",
    )
    _require_binding(
        manifest["deep_research_receipt_binding"],
        deep_binding,
        "SOURCE_MANIFEST_ARTIFACT_CHAIN_MISMATCH",
    )

    _validate_capture_bindings(
        light, output_root=root, authorized_outputs=authorized_outputs
    )
    _validate_capture_bindings(
        deep, output_root=root, authorized_outputs=authorized_outputs
    )
    all_queries = [*light["queries"], *deep["queries"]]
    if len(all_queries) > network_authority["query_limit"]:
        raise ModuleContractError("NETWORK_QUERY_LIMIT_EXCEEDED")
    if len(light["sources"]) + len(deep["sources"]) > network_authority["source_limit"]:
        raise ModuleContractError("NETWORK_SOURCE_LIMIT_EXCEEDED")
    _unique_map(all_queries, "query_id", "WEB_QUERY_ID_DUPLICATE")

    material_ids = set(material_map)
    light_sources = _unique_map(
        light["sources"], "source_id", "WEB_SOURCE_ID_DUPLICATE"
    )
    deep_sources = _unique_map(
        deep["sources"], "source_id", "WEB_SOURCE_ID_DUPLICATE"
    )
    light_ids = set(light_sources)
    deep_ids = set(deep_sources)
    if material_ids & (light_ids | deep_ids) or light_ids & deep_ids:
        raise ModuleContractError("SOURCE_ID_COLLISION")
    light_locators = {source["locator"] for source in light_sources.values()}
    deep_new_ids = {
        source_id
        for source_id, source in deep_sources.items()
        if source["locator"] not in light_locators
    }
    if not deep_new_ids:
        raise ModuleContractError("DEEP_RESEARCH_NEW_SOURCE_REQUIRED")

    if manifest["material_source_ids"] != list(material_map):
        raise ModuleContractError("SOURCE_MANIFEST_SOURCE_SET_MISMATCH")
    if manifest["light_source_ids"] != list(light_sources):
        raise ModuleContractError("SOURCE_MANIFEST_SOURCE_SET_MISMATCH")
    if manifest["deep_source_ids"] != list(deep_sources):
        raise ModuleContractError("SOURCE_MANIFEST_SOURCE_SET_MISMATCH")
    if set(manifest["deep_new_source_ids"]) != deep_new_ids:
        raise ModuleContractError("SOURCE_MANIFEST_SOURCE_SET_MISMATCH")
    expected_sources = {**light_sources, **deep_sources}
    if _canonical_records(manifest["sources"], "source_id") != {
        key: IO.canonical_json(value) for key, value in expected_sources.items()
    }:
        raise ModuleContractError("SOURCE_MANIFEST_SOURCE_SET_MISMATCH")

    material_findings = _unique_map(
        material["findings"], "finding_id", "FINDING_ID_DUPLICATE"
    )
    light_findings = _unique_map(
        light["findings"], "finding_id", "FINDING_ID_DUPLICATE"
    )
    deep_findings = _unique_map(
        deep["findings"], "finding_id", "FINDING_ID_DUPLICATE"
    )
    if (
        set(material_findings) & set(light_findings)
        or set(material_findings) & set(deep_findings)
        or set(light_findings) & set(deep_findings)
    ):
        raise ModuleContractError("FINDING_ID_DUPLICATE")
    expected_findings = {
        **material_findings,
        **light_findings,
        **deep_findings,
    }
    if _canonical_records(manifest["findings"], "finding_id") != {
        key: IO.canonical_json(value) for key, value in expected_findings.items()
    }:
        raise ModuleContractError("SOURCE_MANIFEST_FINDING_SET_MISMATCH")
    if IO.canonical_json(manifest["conflicts"]) != IO.canonical_json(
        deep["conflicts"]
    ):
        raise ModuleContractError("SOURCE_MANIFEST_CONFLICT_SET_MISMATCH")
    if set(manifest["received_not_used"]) != set(material["received_not_used"]):
        raise ModuleContractError("SOURCE_MANIFEST_UNUSED_SET_MISMATCH")

    known_source_ids = material_ids | light_ids | deep_ids
    for finding in expected_findings.values():
        if not set(finding["source_ids"]).issubset(known_source_ids):
            raise ModuleContractError("FINDING_SOURCE_UNKNOWN")
    for conflict in manifest["conflicts"]:
        if not set(conflict["source_ids"]).issubset(known_source_ids):
            raise ModuleContractError("CONFLICT_SOURCE_UNKNOWN")
    provenance = _unique_map(
        manifest["provenance"], "provenance_id", "PROVENANCE_ID_DUPLICATE"
    )
    actually_read = {
        source_id
        for item in provenance.values()
        for source_id in item["sources_actually_read"]
    }
    if actually_read != known_source_ids:
        raise ModuleContractError("DOSSIER_PROVENANCE_INCOMPLETE")

    if download_authority is None:
        if (
            deep["download_outcome"]
            != "DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY"
            or manifest["download_mode"] != "CAPTURE_MD_ONLY"
            or deep["download_authority_binding"] is not None
            or manifest["download_authority_binding"] is not None
            or deep["acquisitions"]
            or manifest["acquisitions"]
        ):
            raise ModuleContractError("RAW_DOWNLOAD_WITHOUT_AUTHORITY")
        quarantine = root / "quarantine"
        if quarantine.exists() and any(path.is_file() for path in quarantine.rglob("*")):
            raise ModuleContractError("RAW_DOWNLOAD_WITHOUT_AUTHORITY")
        download_outcome = "DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY"
    else:
        if (
            deep["download_outcome"] != "DOWNLOAD_AUTHORIZED_QUARANTINED_RAW"
            or manifest["download_mode"] != "QUARANTINED_RAW"
            or download_binding is None
        ):
            raise ModuleContractError("DOWNLOAD_QUARANTINE_INVALID")
        _require_binding(
            deep["download_authority_binding"],
            download_binding,
            "DOWNLOAD_AUTHORITY_BINDING_MISMATCH",
        )
        _require_binding(
            manifest["download_authority_binding"],
            download_binding,
            "DOWNLOAD_AUTHORITY_BINDING_MISMATCH",
        )
        if IO.canonical_json(manifest["acquisitions"]) != IO.canonical_json(
            deep["acquisitions"]
        ):
            raise ModuleContractError("DOWNLOAD_ACQUISITION_SET_MISMATCH")
        _validate_acquisitions(
            manifest["acquisitions"],
            download_authority=download_authority,
            output_root=root,
            authorized_outputs=authorized_outputs,
            known_source_ids=known_source_ids,
        )
        download_outcome = "DOWNLOAD_AUTHORIZED_QUARANTINED_RAW"

    dossier_data, dossier_path = IO.read_bound_bytes(
        root / "DOSSIER.md",
        allowed_roots=[root],
        label="DOSSIER",
    )
    dossier_binding = {
        "path": str(dossier_path),
        "bytes": len(dossier_data),
        "sha256": IO.sha256_bytes(dossier_data),
    }
    _require_output_authorized(dossier_binding, authorized_outputs)
    try:
        dossier_text = dossier_data.decode("utf-8")
    except UnicodeError as error:
        raise ModuleContractError("DOSSIER_UTF8_REQUIRED") from error
    if "## Provenance" not in dossier_text:
        raise ModuleContractError("DOSSIER_PROVENANCE_INCOMPLETE")
    for source_id in known_source_ids:
        if f"[{source_id}]" not in dossier_text:
            raise ModuleContractError("DOSSIER_PROVENANCE_INCOMPLETE")
    for finding_id in expected_findings:
        if f"[{finding_id}]" not in dossier_text:
            raise ModuleContractError("DOSSIER_FINDING_CITATION_MISSING")

    outcome = seal_record(
        {
            "schema": "omni-knowledge-research-dossier-outcome-v1",
            "status": "KNOWLEDGE_RESEARCH_DOSSIER_READY",
            "module_id": MODULE_ID,
            "run_id": run_id,
            "topic": topic,
            "topic_sha256": topic_sha256,
            "activation_sha256": activation_binding["sha256"],
            "material_study_binding": material_binding,
            "light_map_binding": light_binding,
            "deep_research_receipt_binding": deep_binding,
            "source_manifest_binding": manifest_binding,
            "dossier_binding": dossier_binding,
            "download_outcome": download_outcome,
            "next_gate": "STOP",
            "created_at": manifest["created_at"],
        }
    )
    _validate_schema(outcome, RECORDS_SCHEMA, "MODULE_OUTCOME_SCHEMA_INVALID")
    return outcome, root, write_authority


def finalize_run(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    outcome, root, _ = _validate_run(**kwargs)
    target = root / "MODULE_OUTCOME.json"
    payload = f"{IO.canonical_json(outcome)}\n"
    write_status = IO.create_once_text(target, payload, allowed_root=root)
    data, physical = IO.read_bound_bytes(
        target,
        expected_bytes=len(payload.encode("utf-8")),
        expected_sha256=IO.sha256_bytes(payload.encode("utf-8")),
        allowed_roots=[root],
        label="MODULE_OUTCOME_READBACK",
    )
    binding = {
        "path": str(physical),
        "bytes": len(data),
        "sha256": IO.sha256_bytes(data),
    }
    return outcome, binding, write_status


def verify_run(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    expected, root, _ = _validate_run(**kwargs)
    observed, binding = _load_stage(
        root / "MODULE_OUTCOME.json",
        "omni-knowledge-research-dossier-outcome-v1",
    )
    if IO.canonical_json(observed) != IO.canonical_json(expected):
        raise ModuleContractError("MODULE_OUTCOME_MISMATCH")
    return observed, binding


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--activation", required=True, type=Path)
    parser.add_argument("--read-authority", required=True, type=Path)
    parser.add_argument("--write-authority", required=True, type=Path)
    parser.add_argument("--network-authority", required=True, type=Path)
    parser.add_argument("--download-authority", type=Path)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = StrictArgumentParser(description=__doc__)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=StrictArgumentParser
    )
    gate = commands.add_parser("gate")
    gate.add_argument("--activation", required=True, type=Path)
    gate.add_argument("--authority", required=True, type=Path)
    gate.add_argument("--action", required=True, choices=ACTIONS)
    gate.add_argument("--topic", required=True)
    gate.add_argument("--run-id", required=True)
    gate.add_argument("--output-root", type=Path)
    finalize = commands.add_parser("finalize")
    _add_run_arguments(finalize)
    verify = commands.add_parser("verify")
    _add_run_arguments(verify)
    return parser


def _stable_reason(error: BaseException) -> tuple[str, str]:
    detail = str(error) or type(error).__name__
    candidate = detail.split(":", 1)[0]
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", candidate):
        return candidate, detail
    if isinstance(error, OSError):
        return "IO_ERROR", detail
    return "MODULE_RUNTIME_BLOCKED", detail


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command == "gate":
            authority, binding = gate_effect(
                activation_path=args.activation,
                authority_path=args.authority,
                action=args.action,
                topic=args.topic,
                run_id=args.run_id,
                output_root=args.output_root,
            )
            result = {
                "schema": "omni-module-command-result-v1",
                "status": "PASS",
                "command": "gate",
                "module_id": MODULE_ID,
                "authorized_action": authority["action"],
                "authority_binding": binding,
                "next_gate": "PERFORM_ONLY_AUTHORIZED_ACTION",
            }
        else:
            kwargs = {
                "activation_path": args.activation,
                "read_authority_path": args.read_authority,
                "write_authority_path": args.write_authority,
                "network_authority_path": args.network_authority,
                "download_authority_path": args.download_authority,
                "topic": args.topic,
                "run_id": args.run_id,
                "output_root": args.output_root,
            }
            if args.command == "finalize":
                outcome, binding, write_status = finalize_run(**kwargs)
                result = {
                    "schema": "omni-module-command-result-v1",
                    "status": "PASS",
                    "command": "finalize",
                    "module_id": MODULE_ID,
                    "module_status": outcome["status"],
                    "write_status": write_status,
                    "output_binding": binding,
                    "next_gate": "STOP",
                }
            else:
                outcome, binding = verify_run(**kwargs)
                result = {
                    "schema": "omni-module-command-result-v1",
                    "status": "PASS",
                    "command": "verify",
                    "module_id": MODULE_ID,
                    "module_status": outcome["status"],
                    "output_binding": binding,
                    "next_gate": "STOP",
                }
        print(IO.canonical_json(result))
        return 0
    except (
        ModuleContractError,
        PathSafetyError,
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
    ) as error:
        reason_code, detail = _stable_reason(error)
        print(
            IO.canonical_json(
                {
                    "schema": "omni-module-command-result-v1",
                    "status": "BLOCKED",
                    "reason_code": reason_code,
                    "detail": detail,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

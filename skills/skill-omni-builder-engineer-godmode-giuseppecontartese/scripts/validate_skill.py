"""Fail-closed package validator. It never installs, publishes, or writes the package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_references import validate as validate_references
from count_tokens import measure

try:
    import yaml
except ImportError:  # pragma: no cover - reported as a typed package failure
    yaml = None

try:
    import jsonschema
except ImportError:  # pragma: no cover - reported as a typed package failure
    jsonschema = None

NAME = "skill-omni-builder-engineer-godmode-giuseppecontartese"
PACKAGE_FILE_SHA256 = {
    "requirements.txt": "CB9847A40524F90598D605607AEB86B47B11E5652709202E2473E65A236CDD68",
    "LICENSE": "C71D239DF91726FC519C6EB72D318EC65820627232B2F796219E87DCF35D0AB4",
    "NOTICE": "3D42529E0786D55EBBF6C84EDECCFABB82941FAA7E1622CA0D621C20F1BCF79C",
}
ROTATION_ORDER = [
    "ROTATION_REQUESTED", "HANDOFF_FROZEN", "SUCCESSOR_CREATED", "SESSION_BOUND",
    "ATTACH_PASS", "RESTORE_PASS", "AUTHORITY_ENVELOPE_BOUND", "VISIBLE_SESSION_SELECTED",
    "PREDECESSOR_FENCE_STARTED", "PREDECESSOR_AUTHORITY_REVOKED", "PREDECESSOR_QUIESCENT",
    "LEASE_GRANTED", "RESUME_PASS", "WORK_ACKED", "WORK_STARTED_PROBE",
    "WORK_RESUMED_NOTIFIED", "PEER_COUNTERSIGN", "SUBSTANTIVE_WORK_RELEASED", "ROTATION_ABORTED",
]
ADAPTERS = ["codex", "claude-code", "cowork", "antigravity", "cursor"]
EVIDENCE_CLASSES = ["documented", "observed", "authorized", "live_proven"]
CAPABILITY_LAYERS = ["session_carrier", "host_supervisor", "ui_navigation"]
TURN_STATUSES = ["PENDING", "RUNNING", "PASS", "FAIL", "INCONCLUSIVE", "BLOCKED_PENDING_HUMAN", "BLOCKED_PENDING_INFRA"]
RECEIPT_STATUSES = ["PASS", "FAIL", "INCONCLUSIVE", "BLOCKED"]
GUIDED_INTAKE_PHASES = [
    "TOPOLOGY_BOUND", "TEAM_CARD_PENDING", "TEAM_CARD_DUAL_ACK", "QUESTIONS_ACTIVE",
    "PROPOSAL_READBACK_PENDING", "INTAKE_READY", "INTAKE_BLOCKED",
]
GUIDED_INTAKE_STATUSES = ["PENDING", "ACTIVE", "READY", "BLOCKED"]
GUIDED_ACTIVATION_PATHS = ["EXPLICIT_USER_OPT_IN", "PROPOSAL_ACCEPTED"]
GUIDED_ACTIVATION_NON_GRANTS = [
    "PARTNER_SELECTION", "WEB_ACCESS", "DOWNLOAD", "PROJECT_WRITE", "EXECUTION", "AUTONOMY",
]
ACTIVATION_LEVELS = ["OMNI_AWARE", "OMNI_MODULE", "OMNI_FULL"]
WORKSPACE_GRANTS = [
    "READ_NAMED_SOURCES", "CREATE_DIRECTORIES_IN_PROJECT_ROOT",
    "CREATE_FILES_IN_PROJECT_ROOT", "WRITE_OWNED_LANE_FILES",
]
WORKSPACE_NON_GRANTS = [
    "DELETE", "MOVE", "RENAME_OUTSIDE_ROOT", "OVERWRITE_PREEXISTING_USER_FILE",
    "EXECUTE", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS",
]
WORKSPACE_SEPARATE_AUTHORIZATIONS = ["NETWORK_RESEARCH", "DOWNLOAD"]
KNOWLEDGE_ACTIONS = [
    "WELL_BOOTSTRAP", "WELL_READY", "MATERIAL_QUARANTINE", "MATERIAL_JOIN",
    "LANE_LIGHT_WEB_RESEARCH", "LANE_DEEP_PLAN", "LANE_DEEP_WEB_RESEARCH",
    "LANE_DEEP_DOSSIER", "LANE_FREEZE", "FUSION_EMIT", "FUSION_COUNTERSIGN",
]
KNOWLEDGE_PHASES = [
    "WELL_BOOTSTRAPPING", "WELL_READY", "MATERIAL_QUARANTINE", "MATERIAL_JOINED",
    "LANES_ACTIVE", "LANES_FROZEN", "FUSION_EMITTED", "KNOWLEDGE_FUSION_PASS",
]
FULL_ACTIVATION_AUTHORITY_GRANTS = ["METHOD_USE", "FULL_ORCHESTRATION"]
FULL_ACTIVATION_NON_GRANTS = [
    *WORKSPACE_NON_GRANTS, "CREATE_FILES", "ARM_AUTOMATION",
]
PRE_DUAL_ACK_EFFECTS = [
    "USER_MATERIAL_INGESTION", "WEB_RESEARCH", "DOWNLOAD", "WELL_WRITE",
    "KNOWLEDGE_CONSTRUCTION", "PROGRAM_DRAFTING", "PROJECT_EXECUTION",
]
PM_RELAY_NEGATIONS = [
    "not a governed channel", "not authority", "not consent", "not a lease",
    "not a write grant", "not an independent counter-signature",
]
GUIDED_GLOSSARY_TERMS = [
    "activation receipt", "activation path", "activation non-grant", "run kind", "effect policy",
    "activation level", "omni module", "effect authorization",
    "guided intake", "topology", "brain", "lane", "session pair", "team card",
    "team card dual ack", "question id", "four-readback", "critical closure", "pm relay",
    "evidenceref", "workspace access envelope", "access-ready", "intake proposal",
    "fused program", "program countersign receipt", "program digest", "declaration-only verification",
    "adversarial solo independence", "profile degraded", "arm automation", "mode before access",
]
MIN_TEST_COUNT = 226
GUIDED_INTAKE_ROOT_FIELDS = {
    "schema", "state_id", "run_id", "generation", "phase", "status",
    "activation_binding", "run_kind", "effect_policy", "profile", "independence",
    "workspace_access_envelope",
    "topology", "session_pair", "station_matrix_sha256",
    "team_card", "station_matrix", "question_matrix", "intake_proposal", "relay",
    "critical_closure", "well", "knowledge", "program", "cutover",
    "blocking_reason_codes", "previous_record_sha256", "created_at", "record_digest",
}
SAFETY_NOTE_MARKERS = {
    "codex": ["successful navigation call requires visual or state readback", "reset model or reasoning effort"],
    "claude-code": ["does not prove supervisor or ui", "compacted conversation is continuity"],
    "cowork": ["do not inherit claude code carrier claims", "human or qualified external carrier"],
    "antigravity": ["host_version proves only binary presence", "does not isolate the git checkout", "require separate evidence"],
    "cursor": ["never pass an ide chat id", "bind model explicitly"],
}
TEMPLATES = [
    "contratto_fase.yaml", "fusione_regola.md", "handoff.md", "invarianti.md",
    "mandato_costruttore.md", "mandato_demolitore.md", "obiettivo_persistente.yaml",
    "prompt_A_riaggancio.md", "prompt_B_ripristino.md", "prompt_C_ripresa.md",
    "stele_zero.md", "ownership_handover.json",
]
CORE = [
    "count_tokens", "check_references", "seed_well", "fuse_lanes",
    "knowledge_pipeline", "program_pipeline", "operating_regime",
    "validate_wbs", "check_handoff", "validate_skill",
]
SENTRY = ["io_safe", "emit_state", "progress", "windows", "loop", "decide", "budgets", "brake", "cycle", "wakeup", "rotate", "mode_a_guard", "supervisor", "context"]
EXPECTED = {
    "SKILL.md", "LICENSE", "NOTICE", "requirements.txt", "agents/openai.yaml",
    *{f"references/{i:02d}_{name}.md" for i, name in enumerate([
        "triage", "cappelli", "pozzo", "conoscenza", "wbs_stele", "passate",
        "prove", "autonomia", "host", "glossario", "rotazione_e_sentinelle",
    ])},
    "references/11_relay_ledger.md",
    "schemas/turn_state.schema.json", "schemas/rotation_state.schema.json",
    "schemas/receipt.schema.json", "schemas/host_adapter.schema.json",
    "schemas/guided_intake_state.schema.json",
    "schemas/fused_program.schema.json", "schemas/program_countersign_receipt.schema.json",
    "schemas/workspace_access_envelope.schema.json", "schemas/workspace_access_probe_receipt.schema.json",
    "schemas/knowledge_effect_authority.schema.json", "schemas/knowledge_pipeline_state.schema.json",
    "schemas/material_join_manifest.schema.json", "schemas/lane_knowledge_manifest.schema.json",
    "schemas/knowledge_fusion.schema.json", "schemas/material_metadata_attestation.schema.json",
    "schemas/light_map.schema.json", "schemas/deep_plan.schema.json",
    "schemas/web_research_receipt.schema.json", "schemas/source_manifest.schema.json",
    "schemas/planning_effect_authority.schema.json", "schemas/planning_state.schema.json",
    "schemas/plan_lane_manifest.schema.json",
    "schemas/program_baptism_decision.schema.json", "schemas/program_baptism_receipt.schema.json",
    "schemas/operating_regime_binding.schema.json", "schemas/persistent_objective.schema.json",
    "schemas/autonomy_authority.schema.json", "schemas/automation_arm_authority.schema.json",
    "schemas/sentinel_bundle_receipt.schema.json", "schemas/execution_lease.schema.json",
    "schemas/operating_state.schema.json", "schemas/relay_ledger_entry.schema.json",
    *{f"scripts/{name}.py" for name in CORE},
    "scripts/relay_ledger.py",
    *{f"scripts/sentry/{name}.py" for name in SENTRY},
    "scripts/coordinator/run.py", "adapters/host_generation.yaml",
    *{f"adapters/{name}/adapter.yaml" for name in ADAPTERS},
    *{f"templates/{name}" for name in TEMPLATES},
    *{f"fixtures/{name}.json" for name in [
        "incident_echo_unsatisfiable_goal", "incident_flaky_fixed_timeout", "incident_unicode_query_trap",
        "incident_unincised_lesson", "incident_blind_retry_create_once", "incident_rotation_missing_resume",
        "incident_untyped_watcher_takeover", "incident_shared_tmp_wildcard", "incident_large_artifact_main_context",
        "incident_moving_input_or_ordinal_collision",
    ]},
    *{f"tests/{name}.py" for name in [
        "test_structure_and_references", "test_governance_scripts",
        "test_rotation_and_sentinels", "test_incident_regressions",
        "test_l2_binding_and_mode", "test_l3_doctrine_mutants",
        "test_l3_schema_mutants", "test_l3_knowledge_pipeline",
        "test_l4_program_pipeline", "test_l5_operating_regime",
        "test_l6_package_contracts", "test_l7_forward_campaign",
        "test_knowledge_research_dossier_module", "test_r3_relay_ledger",
    ]},
    *{f"modules/KNOWLEDGE_RESEARCH_DOSSIER/{name}" for name in [
        "authority.schema.json", "module.json", "MODULE.md", "records.schema.json", "run.py",
    ]},
}

DELIVERY_HOSTS = ("codex", "claude-code", "antigravity")
DELIVERY_ROOT_FIELDS = {
    "schema", "status", "source_freeze_sha256", "target", "does_not_prove",
    "installation_status", "discovery_status", "publication_status",
}
DELIVERY_TARGET_FIELDS = {"host", "host_version", "adapter_sha256", "classification"}
DELIVERY_DOES_NOT_PROVE = [
    "INSTALLATION", "DISCOVERY", "BEHAVIOR_ON_TARGET", "PUBLICATION",
    "SESSION_ROTATION_ON_TARGET",
]

INTEGRATED_SCHEMA_CONTRACTS = {
    "planning_effect_authority.schema.json": (
        "urn:omni-builder:planning-effect-authority:1",
        {"omni-planning-effect-authority-v1"},
    ),
    "planning_state.schema.json": (
        "urn:omni-builder:planning-state:1",
        {"omni-planning-state-v1"},
    ),
    "plan_lane_manifest.schema.json": (
        "urn:omni-builder:plan-lane-manifest:1",
        {"omni-plan-lane-manifest-v1"},
    ),
    "fused_program.schema.json": (
        "urn:omni-builder:fused-program:2",
        {"omni-fused-program-v2"},
    ),
    "program_countersign_receipt.schema.json": (
        "urn:omni-builder:program-countersign-receipt:2",
        {"omni-program-countersign-receipt-v2"},
    ),
    "program_baptism_decision.schema.json": (
        "urn:omni-builder:program-baptism-decision:1",
        {"omni-program-baptism-decision-v1"},
    ),
    "program_baptism_receipt.schema.json": (
        "urn:omni-builder:program-baptism-receipt:1",
        {"omni-program-baptism-receipt-v1"},
    ),
    "operating_regime_binding.schema.json": (
        "urn:omni-builder:operating-regime-binding:1",
        {"omni-operating-regime-binding-v1", "omni-guided-pm-turn-authority-v1"},
    ),
    "persistent_objective.schema.json": (
        "urn:omni-builder:persistent-objective:1",
        {"omni-persistent-objective-v1"},
    ),
    "autonomy_authority.schema.json": (
        "urn:omni-builder:autonomy-authority:1",
        {"omni-autonomy-authority-v1"},
    ),
    "automation_arm_authority.schema.json": (
        "urn:omni-builder:automation-arm-authority:1",
        {"omni-automation-arm-authority-v1"},
    ),
    "sentinel_bundle_receipt.schema.json": (
        "urn:omni-builder:sentinel-bundle-receipt:1",
        {"omni-sentinel-bundle-receipt-v1"},
    ),
    "execution_lease.schema.json": (
        "urn:omni-builder:execution-lease:1",
        {"omni-execution-lease-v1"},
    ),
    "operating_state.schema.json": (
        "urn:omni-builder:operating-state:1",
        {"omni-operating-state-v1"},
    ),
}


def _load_yaml(path: Path, errors: list[str]) -> Any:
    if yaml is None:
        errors.append("YAML_RUNTIME_UNAVAILABLE")
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        errors.append(f"YAML_INVALID:{path.name}:{type(error).__name__}:{error}")
        return None


def _delivery_expected(host: str | None) -> set[str]:
    if host is None:
        return set(EXPECTED)
    expected = set(EXPECTED)
    for adapter in ADAPTERS:
        if adapter != host:
            expected.discard(f"adapters/{adapter}/adapter.yaml")
    if host != "codex":
        expected.discard("agents/openai.yaml")
    expected.add("DELIVERY_CANDIDATE.json")
    return expected


def _delivery_projection(
    root: Path, files: set[str], errors: list[str], requested_host: str | None
) -> str | None:
    """Validate a generated host projection without pretending it is canonical source."""
    if requested_host is None:
        if "DELIVERY_CANDIDATE.json" in files:
            errors.append("DELIVERY_PROJECTION_FLAG_REQUIRED")
        return None
    if requested_host not in DELIVERY_HOSTS:
        errors.append("DELIVERY_PROJECTION_HOST_INVALID")
        return None
    host = requested_host
    if "DELIVERY_CANDIDATE.json" not in files:
        errors.append("DELIVERY_CANDIDATE_MISSING")
        return host
    present = [
        adapter for adapter in ADAPTERS
        if f"adapters/{adapter}/adapter.yaml" in files
    ]
    if present != [host]:
        errors.append("DELIVERY_PROJECTION_ADAPTER_SET_INVALID")
    path = root / "DELIVERY_CANDIDATE.json"
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"DELIVERY_CANDIDATE_INVALID:{type(error).__name__}")
        return host
    if not isinstance(value, dict):
        errors.append("DELIVERY_CANDIDATE_NOT_OBJECT")
        return host
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if raw != canonical:
        errors.append("DELIVERY_CANDIDATE_NOT_CANONICAL_JSON")
    if set(value) != DELIVERY_ROOT_FIELDS:
        errors.append("DELIVERY_CANDIDATE_KEYS_INVALID")
    if value.get("schema") != "omni-v7-delivery-candidate-v1":
        errors.append("DELIVERY_CANDIDATE_SCHEMA_INVALID")
    if value.get("status") != "READY_FOR_INSTALLATION_CANDIDATE":
        errors.append("DELIVERY_CANDIDATE_STATUS_INVALID")
    source_freeze = value.get("source_freeze_sha256")
    if not isinstance(source_freeze, str) or re.fullmatch(r"[0-9A-F]{64}", source_freeze) is None:
        errors.append("DELIVERY_SOURCE_FREEZE_INVALID")
    if value.get("does_not_prove") != DELIVERY_DOES_NOT_PROVE:
        errors.append("DELIVERY_NON_PROOFS_INVALID")
    for field in ("installation_status", "discovery_status", "publication_status"):
        if value.get(field) != "NOT_RUN":
            errors.append(f"DELIVERY_EXTERNAL_STATUS_INVALID:{field}")

    target = value.get("target")
    if not isinstance(target, dict) or set(target) != DELIVERY_TARGET_FIELDS:
        errors.append("DELIVERY_TARGET_INVALID")
        return host
    adapter_path = root / "adapters" / host / "adapter.yaml"
    adapter = _load_yaml(adapter_path, errors)
    if not isinstance(adapter, dict):
        errors.append(f"DELIVERY_TARGET_ADAPTER_INVALID:{host}")
        return host
    try:
        adapter_sha256 = hashlib.sha256(adapter_path.read_bytes()).hexdigest().upper()
    except OSError as error:
        errors.append(f"DELIVERY_TARGET_ADAPTER_UNREADABLE:{host}:{type(error).__name__}")
        return host
    if target.get("adapter_sha256") != adapter_sha256:
        errors.append("DELIVERY_TARGET_ADAPTER_SHA256_DRIFT")
    if target.get("host") != adapter.get("host"):
        errors.append("DELIVERY_TARGET_HOST_DRIFT")
    if target.get("host_version") != adapter.get("host_version"):
        errors.append("DELIVERY_TARGET_VERSION_DRIFT")
    if target.get("classification") != adapter.get("classification"):
        errors.append("DELIVERY_TARGET_CLASSIFICATION_DRIFT")
    return host


def _frontmatter(text: str, errors: list[str], projection_host: str | None = None) -> None:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        errors.append("FRONTMATTER_OPEN_MISSING")
        return
    try:
        close = lines.index("---", 1)
    except ValueError:
        errors.append("FRONTMATTER_CLOSE_MISSING")
        return
    expected_close = 3
    if close != expected_close:
        if (
            projection_host == "claude-code"
            and "disable-model-invocation: true" in lines[1:close]
        ):
            errors.append("CLAUDE_MODEL_LOADING_BLOCKED")
        errors.append("FRONTMATTER_SHAPE_INVALID")
        return
    seen: set[str] = set()
    for line in lines[1:close]:
        if ":" not in line:
            errors.append("FRONTMATTER_LINE_INVALID")
            continue
        key = line.split(":", 1)[0]
        if key in seen:
            errors.append(f"FRONTMATTER_DUPLICATE:{key}")
        seen.add(key)
    if yaml is None:
        errors.append("YAML_RUNTIME_UNAVAILABLE")
        return
    try:
        values = yaml.safe_load("\n".join(lines[1:close]))
    except yaml.YAMLError as error:
        errors.append(f"FRONTMATTER_YAML_INVALID:{type(error).__name__}:{error}")
        return
    if not isinstance(values, dict):
        errors.append("FRONTMATTER_YAML_NOT_MAPPING")
        return
    expected_keys = {"name", "description"}
    if set(values) != expected_keys:
        errors.append("FRONTMATTER_KEYS_INVALID")
    if projection_host == "claude-code" and values.get("disable-model-invocation") is True:
        errors.append("CLAUDE_MODEL_LOADING_BLOCKED")
    if values.get("name") != NAME:
        errors.append("FRONTMATTER_NAME_INVALID")
    description = values.get("description", "")
    if not isinstance(description, str):
        errors.append("FRONTMATTER_DESCRIPTION_NOT_STRING")
        description = ""
    if not 1 <= len(description) <= 200:
        errors.append(f"FRONTMATTER_DESCRIPTION_LENGTH:{len(description)}")
    description_markers = (
        "explicit Omni/GodMode/module request",
        "motivated proposal",
        "Loading is not activation",
        "Complexity controls recommendations, not eligibility",
    )
    for marker in description_markers:
        if marker not in description:
            errors.append(f"FRONTMATTER_LOADING_DOCTRINE_MISSING:{marker}")


def _invocation_contract(
    text_by_path: dict[str, str], errors: list[str], *, require_openai_metadata: bool = True
) -> None:
    head = text_by_path.get("SKILL.md", "")
    triage = text_by_path.get("references/00_triage.md", "")
    head_marker = "## Invocation manifesto - station zero"
    triage_marker = "## Station 0 - invocation legitimacy"
    if head_marker not in head:
        errors.append("INVOCATION_STATION_ZERO_MISSING:SKILL.md")
    elif "## Permanent maxims" in head and head.index(head_marker) > head.index("## Permanent maxims"):
        errors.append("INVOCATION_STATION_ZERO_ORDER_INVALID:SKILL.md")
    if triage_marker not in triage:
        errors.append("INVOCATION_STATION_ZERO_MISSING:references/00_triage.md")
    elif "## Required full-orchestration intake" in triage and triage.index(triage_marker) > triage.index("## Required full-orchestration intake"):
        errors.append("INVOCATION_STATION_ZERO_ORDER_INVALID:references/00_triage.md")
    required_head = {
        "EXPLICIT_USER_OPT_IN", "PROPOSAL_ACCEPTED", "ACTIVATION_ALLOWED",
        "PROPOSAL_EMITTED_AWAITING_CONSENT",
    }
    for marker in sorted(required_head):
        if marker not in head:
            errors.append(f"INVOCATION_STATE_CONTRACT_MISSING:SKILL.md:{marker}")
    required_triage = {
        "EXPLICIT_USER_OPT_IN", "PROPOSAL_ACCEPTED", "ACTIVATION_ALLOWED",
        "CONSENT_ABSENT", "CONSENT_NEGATIVE", "BLOCKED_BEFORE_MODE_SELECTION",
        "PROPOSAL_EMITTED_AWAITING_CONSENT",
    }
    for marker in sorted(required_triage):
        if marker not in triage:
            errors.append(f"INVOCATION_STATE_CONTRACT_MISSING:references/00_triage.md:{marker}")
    if not {"ONE_OFF_PDF_REPORT", "ONE_OFF_BICYCLE_MANUAL"}.issubset(set(re.findall(r"ONE_OFF_[A-Z_]+", triage))):
        errors.append("INVOCATION_ONE_OFF_CASE_MISSING")
    if "COMPLEX_COOKBOOK" not in triage or "never auto-activate" not in triage:
        errors.append("INVOCATION_CONSENT_CASE_MISSING")
    if (
        "LITE_EXPLICIT_GODMODE" not in triage
        or "Complexity controls recommendation, never user eligibility" not in triage
        or "Complexity controls recommendations, never user eligibility" not in head
    ):
        errors.append("INVOCATION_COMPLEXITY_ELIGIBILITY_DRIFT")
    for reason in ("durable knowledge", "multi-phase", "governed verification", "multiple actors"):
        if reason not in (head + "\n" + triage):
            errors.append(f"INVOCATION_MOTIVATION_MISSING:{reason}")
    if require_openai_metadata:
        metadata_text = text_by_path.get("agents/openai.yaml", "")
        if yaml is None:
            errors.append("YAML_RUNTIME_UNAVAILABLE:agents/openai.yaml")
        else:
            try:
                metadata = yaml.safe_load(metadata_text)
            except yaml.YAMLError as error:
                errors.append(f"HOST_METADATA_YAML_INVALID:{type(error).__name__}")
            else:
                if (
                    not isinstance(metadata, dict)
                    or not isinstance(metadata.get("policy"), dict)
                    or metadata["policy"].get("allow_implicit_invocation") is not True
                ):
                    errors.append("HOST_MODEL_LOADING_DISABLED")
                default_prompt = (
                    metadata.get("interface", {}).get("default_prompt", "")
                    if isinstance(metadata, dict)
                    and isinstance(metadata.get("interface"), dict)
                    else ""
                )
                if "$skill-omni-builder-engineer-godmode-giuseppecontartese" not in default_prompt:
                    errors.append("HOST_DEFAULT_PROMPT_SKILL_TOKEN_MISSING")
                for marker in (
                    "Loading grants nothing",
                    "Complexity controls recommendations, not eligibility",
                    "explicit natural-language",
                ):
                    if marker not in default_prompt:
                        errors.append(f"HOST_LOADING_DOCTRINE_MISSING:{marker}")


def _l2_doctrine_contract(text_by_path: dict[str, str], errors: list[str]) -> None:
    paths = {
        relative: text_by_path.get(relative, "").lower()
        for relative in (
            "SKILL.md", "references/00_triage.md", "references/01_cappelli.md",
            "references/02_pozzo.md", "references/09_glossario.md", "agents/openai.yaml",
            "templates/mandato_costruttore.md", "templates/mandato_demolitore.md",
        )
    }
    activation_markers = (
        "task_scope=current_task_only", "activation_grants=[method_use]",
        "activation_non_grants=[partner_selection, web_access, download, project_write, execution, autonomy]",
        "explicit_user_opt_in", "proposal_accepted",
    )
    for relative in ("SKILL.md", "references/00_triage.md"):
        for marker in activation_markers:
            if marker not in paths[relative]:
                errors.append(f"L2_ACTIVATION_VOCABULARY_MISSING:{relative}:{marker}")

    progressive_markers = (
        "knowledge_available != skill_invoked != effect_authorized",
        "omni_aware", "omni_module", "omni_full", "activation_level", "modules_used",
        "authority_grants", "artifact_grants", "effect_grants", "unknown_module_requested", "arm_automation",
        "never silently upgrade", "knowledge_available", "skill_invoked", "requested_effects", "effect_authorized",
    )
    for relative in ("SKILL.md", "references/00_triage.md"):
        for marker in progressive_markers:
            if marker not in paths[relative]:
                errors.append(f"L2_PROGRESSIVE_ACTIVATION_MISSING:{relative}:{marker}")

    progressive_trace_markers = (
        "`knowledge_available`, `skill_invoked`, `activation_level`",
        "`artifact_grants`, `requested_effects`, `effect_authorized`, `effect_grants`",
    )
    for relative in ("SKILL.md", "references/00_triage.md"):
        for marker in progressive_trace_markers:
            if marker not in paths[relative]:
                errors.append(f"L2_PROGRESSIVE_TRACE_MISSING:{relative}:{marker}")

    branch_markers = {
        "SKILL.md": (
            "module_activation_allowed", "module-specific mini-contract", "typed module outcome",
            "never require q0", "new, explicit `omni_full` consent", "without an activation receipt",
            "exactly one real packaged module", "modules_used=[the_one_module]",
            "adding or replacing that module requires a new `module_activation_allowed` receipt",
        ),
        "references/00_triage.md": (
            "module_activation_allowed", "named module mini-contract", "typed module outcome",
            "never requires q0", "new explicit `omni_full` consent", "without an activation receipt",
            "exactly one real packaged module", "modules_used=[the_one_module]",
            "adding or replacing the module requires a new `module_activation_allowed` receipt",
        ),
        "references/09_glossario.md": (
            "module_activation_allowed", "module-specific mini-contract", "typed module outcome",
            "never enters full guided intake", "no redundant prompt", "exactly one real packaged module",
            "modules_used=[the_one_module]", "adding or replacing it requires a new receipt",
        ),
        "agents/openai.yaml": (
            "named packaged-module request is already module consent",
            "bind exactly one module per module_activation_allowed receipt",
            "changing it requires a new receipt", "enter q0 only after omni_full consent",
        ),
        "templates/mandato_costruttore.md": (
            "omni_full only", "omni_module", "typed module outcome", "must never be forced through this mandate",
        ),
        "templates/mandato_demolitore.md": (
            "omni_full only", "omni_module", "typed module outcome", "must never be forced through this mandate",
        ),
    }
    for relative, markers in branch_markers.items():
        if relative == "agents/openai.yaml" and relative not in text_by_path:
            continue
        for marker in markers:
            if marker not in paths[relative]:
                errors.append(f"L2_PROGRESSIVE_BRANCH_MISSING:{relative}:{marker}")

    access_markers = (
        "workspace_access_envelope", "access_grant", "access_granted_non_destructive",
        "access_ready", "autonomy_unavailable_no_access", "read_named_sources",
        "create_directories_in_project_root", "create_files_in_project_root",
        "write_owned_lane_files", "rename_outside_root", "overwrite_preexisting_user_file",
        "separate", "omni-workspace-access-probe-receipt-v1", "create_once=true",
        "overwritten=false", "retained=true", "read_proofs", "path + bytes + sha-256",
    )
    for relative in ("SKILL.md", "references/00_triage.md"):
        for marker in access_markers:
            if marker not in paths[relative]:
                errors.append(f"L2_WORKSPACE_ACCESS_DOCTRINE_MISSING:{relative}:{marker}")

    canonical_path_markers = (
        "canonical_absolute_path_required", "reject_cwd_relative", "reject_drive_relative",
        "reject_ntfs_ads", "reject_device_alias", "nul_family_not_module_surface",
    )
    for relative in ("SKILL.md", "references/00_triage.md"):
        for marker in canonical_path_markers:
            if marker not in paths[relative]:
                errors.append(f"L2_CANONICAL_PATH_DOCTRINE_MISSING:{relative}:{marker}")

    for relative in ("SKILL.md", "references/00_triage.md", "references/01_cappelli.md"):
        text = paths[relative]
        for effect in PRE_DUAL_ACK_EFFECTS:
            if effect.lower() not in text:
                errors.append(f"L2_PRE_DUAL_ACK_EFFECT_MISSING:{relative}:{effect}")
        for negation in PM_RELAY_NEGATIONS:
            if negation not in text:
                errors.append(f"L2_PM_RELAY_NEGATION_MISSING:{relative}:{negation}")

    doctrine_markers = {
        "SKILL.md": [
            "two distinct native sessions", "team_card_dual_ack", "acks.builder", "acks.verifier",
            "builder.question", "verifier.question", "builder.answer", "verifier.answer",
            "`known` without physical `source_refs` does not close a critical station",
            "intake proposal has matching dual readback", "one project well folder",
            "never create two project wells", "never co-write a lane file", "mode_before_program",
        ],
        "references/00_triage.md": [
            "q0 binds topology", "immutable pair of distinct native sessions", "team_card_dual_ack",
            "acks.builder", "acks.verifier", "builder.question", "verifier.question",
            "builder.answer", "verifier.answer", "without physical `source_refs` remains open",
            "intake proposal", "matching readback from both sessions", "mode_before_program",
            "cannot emit `team_card_dual_ack` or close l2",
        ],
        "references/01_cappelli.md": [
            "two distinct native sessions", "session_pair", "team_card_dual_ack", "acks.builder",
            "acks.verifier", "builder.question", "verifier.question", "builder.answer",
            "verifier.answer", "critical `known` station without physical `source_refs` objects",
            "dual-read intake proposal", "one project well folder", "never create two project wells",
            "never co-write one lane file",
        ],
        "references/02_pozzo.md": [
            "well.state=well_write_scope_pending", "one project well folder", "never two project wells",
            "separate lane-owned files", "no file is co-written", "later governed fusion gate",
        ],
    }
    for relative, markers in doctrine_markers.items():
        for marker in markers:
            if marker not in paths[relative]:
                errors.append(f"L2_DOCTRINE_MARKER_MISSING:{relative}:{marker}")

    physical_markers = {
        "SKILL.md": [
            "every evidenceref is a real file binding", "open and reproduce every relay payload",
            "both mandate artifacts", "omni-fused-program-v2", "program_fusion_frozen",
            "omni-program-countersign-receipt-v2", "program_countersign_accepted",
            "omni-program-baptism-decision-v1", "omni-program-baptism-receipt-v1",
            "program_baptized", "v1 artifacts fail closed",
        ],
        "references/00_triage.md": [
            "each evidenceref", "payload_path", "payload_bytes", "payload_sha256",
            "both strict mandate files", "declaration is not verification",
            "omni-fused-program-v2", "program_fusion_frozen",
            "omni-program-countersign-receipt-v2", "program_countersign_accepted",
            "omni-program-baptism-decision-v1", "omni-program-baptism-receipt-v1",
            "program_baptized", "v1 artifacts fail closed",
        ],
        "references/01_cappelli.md": [
            "physical `payload_path`", "`payload_bytes`", "`payload_sha256`",
            "physical `source_refs` objects", "both mandate artifacts",
        ],
        "references/09_glossario.md": [
            "omni-fused-program-v2", "program_fusion_frozen",
            "omni-program-countersign-receipt-v2", "program_countersign_accepted",
            "omni-program-baptism-decision-v1", "omni-program-baptism-receipt-v1",
            "program_baptized", "v1 artifacts fail closed",
        ],
    }
    for relative, markers in physical_markers.items():
        for marker in markers:
            if marker not in paths[relative]:
                errors.append(f"L2_PHYSICAL_BINDING_DOCTRINE_MISSING:{relative}:{marker}")

    glossary = paths["references/09_glossario.md"]
    for term in GUIDED_GLOSSARY_TERMS:
        if f"**{term}:**" not in glossary:
            errors.append(f"L2_GLOSSARY_TERM_MISSING:{term}")


def _l3_doctrine_contract(text_by_path: dict[str, str], errors: list[str]) -> None:
    """Pin the L3 laws so prose inversions cannot silently weaken the runtime."""
    required = {
        "SKILL.md": (
            "existing user material never replaces independent web research",
            "a distinct verifier reproduces both lane bindings",
        ),
        "references/00_triage.md": (
            "mandatory research is a completion requirement, not a grant",
            "`download` remains a separate optional authority and is never implied by `network_research`",
        ),
        "references/02_pozzo.md": (
            "create exactly one project well, never one well per agent",
            "separate brains and non-overlapping write lanes",
        ),
        "references/01_cappelli.md": (
            "before both lane freezes, neither brain may read the other's synthesis",
            "in `guided_pm`, the pm explicitly transfers the turn and continuous autonomy sentinels remain unarmed",
            "existing material never exempts either lane from web research",
        ),
        "references/03_conoscenza.md": (
            "no separate or fused realization plan is canonical before it",
        ),
    }
    for relative, markers in required.items():
        text = text_by_path.get(relative, "").lower()
        for marker in markers:
            if marker not in text:
                errors.append(f"L3_DOCTRINE_MARKER_MISSING:{relative}:{marker}")


def _l3_schema_contract(root: Path, errors: list[str]) -> None:
    """Pin all L3 contracts, including their evidence and non-authority laws."""
    contracts = {
        "knowledge_effect_authority.schema.json": {
            "code": "L3_SCHEMA_AUTHORITY_CONTRACT_DRIFT",
            "id": "urn:omni-builder:knowledge-effect-authority:1",
            "const": "omni-knowledge-effect-authority-v1",
            "fields": {
                "schema", "status", "decision", "authority_id", "action", "task_id",
                "pipeline_id", "intake_state_sha256", "session_pair_sha256", "subject_role",
                "subject_session_id", "workspace_access_envelope_binding", "well_root",
                "input_bindings", "output_paths", "network_research", "download", "one_shot",
                "operation_nonce", "non_grants", "created_at", "record_digest",
            },
        },
        "knowledge_pipeline_state.schema.json": {
            "code": "L3_SCHEMA_STATE_CONTRACT_DRIFT",
            "id": "urn:omni-builder:knowledge-pipeline-state:1",
            "const": "omni-knowledge-pipeline-state-v1",
            "fields": {
                "schema", "state_id", "pipeline_id", "generation", "phase", "status", "task_id",
                "project_root", "well_root", "intake_binding", "session_pair_sha256", "session_pair",
                "access_envelopes", "source_roots", "material", "lanes", "fusion", "event", "actor",
                "effect_authority_binding", "evidence_bindings", "blocking_reason_codes",
                "previous_state_binding", "created_at", "record_digest",
            },
        },
        "material_join_manifest.schema.json": {
            "code": "L3_SCHEMA_MATERIAL_CONTRACT_DRIFT",
            "id": "urn:omni-builder:material-join-manifest:1",
            "const": "omni-material-join-manifest-v1",
            "fields": {
                "schema", "status", "stage", "pipeline_id", "task_id", "session_pair_sha256",
                "availability", "items", "joined_item_ids", "rejected_item_ids",
                "previous_manifest_binding", "created_at", "record_digest",
            },
        },
        "lane_knowledge_manifest.schema.json": {
            "code": "L3_SCHEMA_LANE_CONTRACT_DRIFT",
            "id": "urn:omni-builder:lane-knowledge-manifest:1",
            "const": "omni-lane-knowledge-manifest-v1",
            "fields": {
                "schema", "status", "pipeline_id", "task_id", "session_pair_sha256", "role",
                "session_id", "lane_root", "material_join_binding", "light_map_binding",
                "deep_plan_binding", "deep_research_receipt_binding", "deep_dossier_binding",
                "source_manifest_binding", "acquisitions", "web_research_required",
                "cross_read_performed", "deep_new_source_ids", "findings", "conflicts", "dissent",
                "provenance", "received_not_used", "limits", "created_at", "record_digest",
            },
        },
        "knowledge_fusion.schema.json": {
            "code": "L3_SCHEMA_FUSION_CONTRACT_DRIFT",
            "id": "urn:omni-builder:knowledge-fusion:1",
            "const": "omni-knowledge-fusion-v1",
            "fields": {
                "schema", "kind", "status", "fusion_id", "pipeline_id", "task_id",
                "session_pair_sha256", "author_role", "author_session_id",
                "builder_manifest_binding", "verifier_manifest_binding", "decision_register_binding",
                "canonical_knowledge_binding", "finding_ids", "dissent_ids_preserved",
                "countersigner_role", "countersigner_session_id", "candidate_binding", "created_at",
                "record_digest",
            },
        },
        "material_metadata_attestation.schema.json": {
            "code": "L3_SCHEMA_MATERIAL_METADATA_ATTESTATION_CONTRACT_DRIFT",
            "id": "urn:omni-builder:material-metadata-attestation:1",
            "const": "omni-material-metadata-attestation-v1",
            "fields": {
                "schema", "status", "attestation_id", "pipeline_id", "task_id",
                "session_pair_sha256", "subject_source_binding", "issuer_role",
                "issuer_session_id", "rights_status", "rights_evidence_binding",
                "privacy_status", "privacy_evidence_binding", "acl_status",
                "acl_evidence_binding", "scan_status", "scan_receipt_binding",
                "parse_status", "parse_receipt_binding", "admission_recommendation",
                "rejection_reason_codes", "created_at", "record_digest",
            },
        },
        "light_map.schema.json": {
            "code": "L3_SCHEMA_LIGHT_MAP_CONTRACT_DRIFT",
            "id": "urn:omni-builder:light-map:1",
            "const": "omni-light-map-v1",
            "fields": {
                "schema", "status", "map_id", "pipeline_id", "task_id",
                "session_pair_sha256", "role", "session_id", "lane_root",
                "material_join_binding", "effect_authority_binding",
                "network_research_performed", "cross_read_performed", "query_events",
                "sources", "light_source_ids", "topic_clusters", "priority_source_ids",
                "gaps", "created_at", "record_digest",
            },
        },
        "deep_plan.schema.json": {
            "code": "L3_SCHEMA_DEEP_PLAN_CONTRACT_DRIFT",
            "id": "urn:omni-builder:deep-plan:1",
            "const": "omni-deep-plan-v1",
            "fields": {
                "schema", "status", "plan_id", "pipeline_id", "task_id",
                "session_pair_sha256", "role", "session_id", "lane_root",
                "light_map_binding", "light_source_ids", "web_research_required",
                "cross_read_performed", "research_questions", "planned_queries",
                "target_source_classes", "novelty_requirement", "download_strategy",
                "created_at", "record_digest",
            },
        },
        "web_research_receipt.schema.json": {
            "code": "L3_SCHEMA_WEB_RESEARCH_RECEIPT_CONTRACT_DRIFT",
            "id": "urn:omni-builder:web-research-receipt:1",
            "const": "omni-web-research-receipt-v1",
            "fields": {
                "schema", "status", "receipt_id", "pipeline_id", "task_id",
                "session_pair_sha256", "role", "session_id", "lane_root",
                "research_phase", "light_map_binding", "deep_plan_binding",
                "effect_authority_binding", "network_research_performed",
                "cross_read_performed", "query_events", "sources", "light_source_ids",
                "deep_source_ids", "deep_new_source_ids", "download_performed",
                "download_authority_binding", "acquisitions", "created_at", "record_digest",
            },
        },
        "source_manifest.schema.json": {
            "code": "L3_SCHEMA_SOURCE_MANIFEST_CONTRACT_DRIFT",
            "id": "urn:omni-builder:source-manifest:1",
            "const": "omni-source-manifest-v1",
            "fields": {
                "schema", "status", "manifest_id", "pipeline_id", "task_id",
                "session_pair_sha256", "role", "session_id", "lane_root",
                "material_join_binding", "light_map_binding", "deep_plan_binding",
                "deep_research_receipt_binding", "material_source_ids", "light_source_ids",
                "deep_source_ids", "deep_new_source_ids", "sources", "findings", "conflicts",
                "dissent", "provenance", "received_not_used", "download_mode",
                "download_authority_binding", "acquisitions", "download_fallback", "limits",
                "cross_read_performed", "created_at", "record_digest",
            },
        },
    }

    loaded: dict[str, dict[str, Any]] = {}

    def file_binding_is_exact(schema: dict[str, Any]) -> bool:
        binding = schema.get("$defs", {}).get("file_binding")
        if not isinstance(binding, dict):
            return False
        properties = binding.get("properties")
        expected = {"path", "bytes", "sha256"}
        return (
            binding.get("type") == "object"
            and binding.get("additionalProperties") is False
            and isinstance(properties, dict)
            and set(binding.get("required", [])) == expected
            and set(properties) == expected
            and properties.get("path") == {"$ref": "#/$defs/absolute_path"}
            and properties.get("bytes") == {"type": "integer", "minimum": 1}
            and properties.get("sha256") == {"$ref": "#/$defs/sha256"}
        )

    def object_shape_is_exact(node: Any, fields: set[str]) -> bool:
        if not isinstance(node, dict):
            return False
        properties = node.get("properties")
        return (
            node.get("type") == "object"
            and node.get("additionalProperties") is False
            and isinstance(properties, dict)
            and set(node.get("required", [])) == fields
            and set(properties) == fields
        )

    def binding_or_null_is_exact(node: Any) -> bool:
        return isinstance(node, dict) and node.get("oneOf") == [
            {"$ref": "#/$defs/file_binding"}, {"type": "null"},
        ]

    for filename, expected in contracts.items():
        failed = False
        try:
            schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            schema = {}
            failed = True
        if not failed:
            properties = schema.get("properties")
            failed = (
                schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
                or schema.get("$id") != expected["id"]
                or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or not isinstance(properties, dict)
                or set(properties) != expected["fields"]
                or set(schema.get("required", [])) != expected["fields"]
                or properties.get("schema", {}).get("const") != expected["const"]
                or schema.get("$defs", {}).get("sha256")
                != {"type": "string", "pattern": "^[A-F0-9]{64}$"}
                or not file_binding_is_exact(schema)
            )
        if not failed and jsonschema is None:
            failed = True
        elif not failed:
            try:
                jsonschema.Draft202012Validator.check_schema(schema)
            except jsonschema.exceptions.SchemaError:
                failed = True
        if failed:
            errors.append(str(expected["code"]))
        else:
            loaded[filename] = schema

    authority = loaded.get("knowledge_effect_authority.schema.json")
    if authority is not None:
        properties = authority["properties"]
        policy = json.dumps(authority.get("allOf", []), ensure_ascii=True, sort_keys=True)
        web_gate_present = any(
            isinstance(branch, dict)
            and branch.get("if", {}).get("properties", {}).get("action", {}).get("enum")
            == ["LANE_LIGHT_WEB_RESEARCH", "LANE_DEEP_WEB_RESEARCH"]
            and branch.get("if", {}).get("properties", {}).get("decision", {}).get("const")
            == "AUTHORIZED"
            and branch.get("then", {}).get("properties", {}).get("network_research", {})
            .get("properties", {}).get("status", {}).get("const") == "AUTHORIZED"
            for branch in authority.get("allOf", [])
        )
        if (
            properties.get("action", {}).get("enum") != KNOWLEDGE_ACTIONS
            or properties.get("one_shot", {}).get("const") is not True
            or properties.get("non_grants", {}).get("const") != WORKSPACE_NON_GRANTS
            or properties.get("subject_role", {}).get("enum") != ["BUILDER", "VERIFIER"]
            or not web_gate_present
            or "LANE_LIGHT_WEB_RESEARCH" not in policy
            or "LANE_DEEP_WEB_RESEARCH" not in policy
            or "QUARANTINE_HASH_NEVER_EXECUTE" not in policy
            or "NO_RAW_DOWNLOAD" not in policy
            or policy.count('"const": "AUTHORIZED"') < 2
        ):
            errors.append("L3_SCHEMA_AUTHORITY_CONTRACT_DRIFT")

    state = loaded.get("knowledge_pipeline_state.schema.json")
    if state is not None:
        properties = state["properties"]
        policy = json.dumps(state.get("allOf", []), ensure_ascii=True, sort_keys=True)
        forbidden = {"plan", "program", "execution", "plan_authority", "execution_authority"}
        required_policy = {
            "WELL_BOOTSTRAPPING", "MATERIAL_QUARANTINE", "MATERIAL_JOINED", "LANES_FROZEN",
            "FUSION_EMITTED", "KNOWLEDGE_FUSION_PASS", "LANE_FROZEN",
        }
        if (
            properties.get("phase", {}).get("enum") != KNOWLEDGE_PHASES
            or properties.get("status", {}).get("enum") != ["ACTIVE", "PASS"]
            or properties.get("event", {}).get("enum") != [
                "INIT", "BOOTSTRAP_WELL", "QUARANTINE_MATERIAL", "JOIN_MATERIAL",
                "BIND_LIGHT_MAP", "FREEZE_DEEP_PLAN", "START_DEEP_RESEARCH",
                "BIND_DEEP_DOSSIER", "FREEZE_LANE", "EMIT_FUSION", "COUNTERSIGN_FUSION",
            ]
            or forbidden.intersection(properties)
            or not required_policy.issubset(set(re.findall(r'[A-Z][A-Z_]+', policy)))
            or '"const": "PASS"' not in policy
            or '"const": "ACTIVE"' not in policy
        ):
            errors.append("L3_SCHEMA_STATE_CONTRACT_DRIFT")

    material = loaded.get("material_join_manifest.schema.json")
    if material is not None:
        properties = material["properties"]
        policy = json.dumps(material.get("allOf", []), ensure_ascii=True, sort_keys=True)
        if (
            properties.get("status", {}).get("enum") != ["MATERIAL_QUARANTINED", "MATERIAL_JOINED"]
            or properties.get("stage", {}).get("enum") != ["QUARANTINED", "JOINED"]
            or properties.get("availability", {}).get("enum") != ["NONE_DECLARED", "USER_MATERIAL_PRESENT"]
            or "MATERIAL_QUARANTINED" not in policy
            or "MATERIAL_JOINED" not in policy
            or "PENDING" not in policy
            or "REJECTED" not in policy
        ):
            errors.append("L3_SCHEMA_MATERIAL_CONTRACT_DRIFT")

    lane = loaded.get("lane_knowledge_manifest.schema.json")
    if lane is not None:
        properties = lane["properties"]
        if (
            properties.get("status", {}).get("const") != "LANE_FROZEN"
            or properties.get("role", {}).get("enum") != ["BUILDER", "VERIFIER"]
            or properties.get("web_research_required", {}).get("const") is not True
            or properties.get("cross_read_performed", {}).get("const") is not False
            or properties.get("deep_new_source_ids", {}).get("minItems") != 1
            or properties.get("findings", {}).get("minItems") != 1
            or properties.get("provenance", {}).get("minItems") != 1
            or properties.get("deep_new_source_ids", {}).get("uniqueItems") is not True
            or properties.get("conflicts", {}).get("type") != "array"
            or properties.get("dissent", {}).get("type") != "array"
        ):
            errors.append("L3_SCHEMA_LANE_CONTRACT_DRIFT")

    fusion = loaded.get("knowledge_fusion.schema.json")
    if fusion is not None:
        properties = fusion["properties"]
        policy = json.dumps(fusion.get("allOf", []), ensure_ascii=True, sort_keys=True)
        forbidden = {"plan", "program", "execution", "plan_authority", "execution_authority"}
        if (
            properties.get("kind", {}).get("enum") != ["FUSION_CANDIDATE", "FUSION_COUNTERSIGN"]
            or properties.get("status", {}).get("enum") != ["FUSION_EMITTED", "KNOWLEDGE_FUSION_PASS"]
            or properties.get("author_role", {}).get("const") != "BUILDER"
            or forbidden.intersection(properties)
            or "FUSION_CANDIDATE" not in policy
            or "FUSION_COUNTERSIGN" not in policy
            or "KNOWLEDGE_FUSION_PASS" not in policy
            or '"const": "VERIFIER"' not in policy
            or '"$ref": "#/$defs/file_binding"' not in policy
        ):
            errors.append("L3_SCHEMA_FUSION_CONTRACT_DRIFT")

    metadata = loaded.get("material_metadata_attestation.schema.json")
    if metadata is not None:
        properties = metadata["properties"]
        rules = metadata.get("allOf", [])
        rule = rules[0] if len(rules) == 1 and isinstance(rules[0], dict) else {}
        condition = rule.get("if", {})
        condition_properties = condition.get("properties", {}) if isinstance(condition, dict) else {}
        then_properties = rule.get("then", {}).get("properties", {})
        else_properties = rule.get("else", {}).get("properties", {})
        binding_fields = {
            "subject_source_binding", "rights_evidence_binding", "privacy_evidence_binding",
            "acl_evidence_binding", "scan_receipt_binding", "parse_receipt_binding",
        }
        rejection_codes = [
            "MATERIAL_RIGHTS_DENIED", "MATERIAL_PRIVACY_DENIED", "MATERIAL_ACL_VIOLATION",
            "MATERIAL_SCAN_FAILED", "MATERIAL_PARSE_FAILED",
        ]
        if (
            properties.get("status", {}).get("const") != "MATERIAL_METADATA_ATTESTED"
            or properties.get("task_id") != {"$ref": "#/$defs/identifier"}
            or properties.get("issuer_role", {}).get("const") != "BUILDER"
            or properties.get("rights_status", {}).get("enum")
            != ["AUTHORIZED", "OWNED", "LICENSED", "PUBLIC", "DENIED", "UNKNOWN"]
            or properties.get("privacy_status", {}).get("enum")
            != ["APPROVED", "LOCAL_ONLY", "DENIED", "UNKNOWN"]
            or properties.get("acl_status", {}).get("enum")
            != ["WITHIN_ENVELOPE", "OUTSIDE_ENVELOPE", "UNKNOWN"]
            or properties.get("scan_status", {}).get("enum") != ["PASS", "FAIL", "NOT_RUN"]
            or properties.get("parse_status", {}).get("enum")
            != ["PASS", "FAIL", "NOT_APPLICABLE", "NOT_RUN"]
            or properties.get("admission_recommendation", {}).get("enum") != ["ELIGIBLE", "REJECTED"]
            or properties.get("rejection_reason_codes", {}).get("type") != "array"
            or properties.get("rejection_reason_codes", {}).get("uniqueItems") is not True
            or properties.get("rejection_reason_codes", {}).get("items", {}).get("enum") != rejection_codes
            or any(properties.get(name) != {"$ref": "#/$defs/file_binding"} for name in binding_fields)
            or set(condition.get("required", []))
            != {"rights_status", "privacy_status", "acl_status", "scan_status", "parse_status"}
            or condition_properties.get("rights_status", {}).get("enum")
            != ["AUTHORIZED", "OWNED", "LICENSED", "PUBLIC"]
            or condition_properties.get("privacy_status", {}).get("enum") != ["APPROVED", "LOCAL_ONLY"]
            or condition_properties.get("acl_status", {}).get("const") != "WITHIN_ENVELOPE"
            or condition_properties.get("scan_status", {}).get("const") != "PASS"
            or condition_properties.get("parse_status", {}).get("enum") != ["PASS", "NOT_APPLICABLE"]
            or then_properties.get("admission_recommendation", {}).get("const") != "ELIGIBLE"
            or then_properties.get("rejection_reason_codes", {}).get("maxItems") != 0
            or else_properties.get("admission_recommendation", {}).get("const") != "REJECTED"
            or else_properties.get("rejection_reason_codes", {}).get("minItems") != 1
        ):
            errors.append("L3_SCHEMA_MATERIAL_METADATA_ATTESTATION_CONTRACT_DRIFT")

    light_map = loaded.get("light_map.schema.json")
    if light_map is not None:
        properties = light_map["properties"]
        definitions = light_map.get("$defs", {})
        query_event = definitions.get("query_event", {})
        query_fields = {
            "query_id", "query_text", "executed_at", "tool", "result_capture_binding",
            "returned_source_ids",
        }
        source = definitions.get("source", {})
        source_fields = {
            "source_id", "research_phase", "locator", "title", "publisher", "accessed_at",
            "capture_mode", "capture_binding", "sections_consulted",
        }
        cluster = properties.get("topic_clusters", {}).get("items", {})
        cluster_fields = {"cluster_id", "label", "source_ids"}
        source_properties = source.get("properties", {}) if isinstance(source, dict) else {}
        query_properties = query_event.get("properties", {}) if isinstance(query_event, dict) else {}
        cluster_properties = cluster.get("properties", {}) if isinstance(cluster, dict) else {}
        if (
            properties.get("status", {}).get("const") != "LIGHT_MAP_FROZEN"
            or properties.get("task_id") != {"$ref": "#/$defs/identifier"}
            or properties.get("role", {}).get("enum") != ["BUILDER", "VERIFIER"]
            or properties.get("network_research_performed", {}).get("const") is not True
            or properties.get("cross_read_performed", {}).get("const") is not False
            or properties.get("query_events")
            != {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/query_event"}}
            or properties.get("sources")
            != {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/source"}}
            or properties.get("light_source_ids") != {"$ref": "#/$defs/nonempty_identifiers"}
            or properties.get("priority_source_ids") != {"$ref": "#/$defs/nonempty_identifiers"}
            or properties.get("topic_clusters", {}).get("type") != "array"
            or properties.get("topic_clusters", {}).get("minItems") != 1
            or not object_shape_is_exact(cluster, cluster_fields)
            or cluster_properties.get("cluster_id") != {"$ref": "#/$defs/identifier"}
            or cluster_properties.get("source_ids") != {"$ref": "#/$defs/nonempty_identifiers"}
            or not object_shape_is_exact(query_event, query_fields)
            or query_properties.get("result_capture_binding") != {"$ref": "#/$defs/file_binding"}
            or query_properties.get("returned_source_ids") != {"$ref": "#/$defs/nonempty_identifiers"}
            or not object_shape_is_exact(source, source_fields)
            or source_properties.get("research_phase", {}).get("const") != "LIGHT_WEB"
            or source_properties.get("capture_mode", {}).get("const") != "CAPTURE_MD_ONLY"
            or source_properties.get("capture_binding") != {"$ref": "#/$defs/file_binding"}
            or source_properties.get("sections_consulted", {}).get("minItems") != 1
            or source_properties.get("sections_consulted", {}).get("uniqueItems") is not True
        ):
            errors.append("L3_SCHEMA_LIGHT_MAP_CONTRACT_DRIFT")

    deep_plan = loaded.get("deep_plan.schema.json")
    if deep_plan is not None:
        properties = deep_plan["properties"]
        novelty = properties.get("novelty_requirement", {})
        novelty_properties = novelty.get("properties", {}) if isinstance(novelty, dict) else {}
        novelty_fields = {"basis", "require_set_difference", "minimum_new_sources"}
        required_array_fields = ("research_questions", "planned_queries", "target_source_classes")
        if (
            properties.get("status", {}).get("const") != "DEEP_PLAN_FROZEN"
            or properties.get("task_id") != {"$ref": "#/$defs/identifier"}
            or properties.get("role", {}).get("enum") != ["BUILDER", "VERIFIER"]
            or properties.get("light_map_binding") != {"$ref": "#/$defs/file_binding"}
            or properties.get("light_source_ids") != {"$ref": "#/$defs/nonempty_identifiers"}
            or properties.get("web_research_required", {}).get("const") is not True
            or properties.get("cross_read_performed", {}).get("const") is not False
            or any(
                properties.get(name, {}).get("type") != "array"
                or properties.get(name, {}).get("minItems") != 1
                or properties.get(name, {}).get("uniqueItems") is not True
                for name in required_array_fields
            )
            or not object_shape_is_exact(novelty, novelty_fields)
            or novelty_properties.get("basis", {}).get("const") != "LIGHT_MAP_SOURCE_IDS"
            or novelty_properties.get("require_set_difference", {}).get("const") is not True
            or novelty_properties.get("minimum_new_sources") != {"type": "integer", "minimum": 1}
            or properties.get("download_strategy", {}).get("const")
            != "CAPTURE_MD_ONLY_UNLESS_SEPARATELY_AUTHORIZED"
        ):
            errors.append("L3_SCHEMA_DEEP_PLAN_CONTRACT_DRIFT")

    web_receipt = loaded.get("web_research_receipt.schema.json")
    if web_receipt is not None:
        properties = web_receipt["properties"]
        definitions = web_receipt.get("$defs", {})
        query_event = definitions.get("query_event", {})
        query_fields = {
            "query_id", "query_text", "executed_at", "tool", "result_capture_binding",
            "returned_source_ids",
        }
        source = definitions.get("source", {})
        source_fields = {
            "source_id", "research_phase", "locator", "title", "publisher", "accessed_at",
            "capture_mode", "capture_binding", "sections_consulted",
        }
        acquisition = definitions.get("acquisition", {})
        acquisition_fields = {
            "acquisition_id", "source_id", "origin_locator", "media_type", "retrieved_at",
            "content_binding", "rights_status", "rights_evidence_binding", "scan_status",
            "scan_receipt_binding", "handling_policy",
        }
        query_properties = query_event.get("properties", {}) if isinstance(query_event, dict) else {}
        source_properties = source.get("properties", {}) if isinstance(source, dict) else {}
        acquisition_properties = acquisition.get("properties", {}) if isinstance(acquisition, dict) else {}
        rules = web_receipt.get("allOf", [])
        rule = rules[0] if len(rules) == 1 and isinstance(rules[0], dict) else {}
        then_properties = rule.get("then", {}).get("properties", {})
        else_properties = rule.get("else", {}).get("properties", {})
        then_source = then_properties.get("sources", {}).get("items", {}).get("allOf", [])
        else_contains = else_properties.get("sources", {}).get("contains", {})
        id_fields = ("light_source_ids", "deep_source_ids", "deep_new_source_ids")
        binding_fields = ("light_map_binding", "deep_plan_binding", "effect_authority_binding")
        if (
            properties.get("status", {}).get("const") != "DEEP_WEB_RESEARCH_PASS"
            or properties.get("task_id") != {"$ref": "#/$defs/identifier"}
            or properties.get("role", {}).get("enum") != ["BUILDER", "VERIFIER"]
            or properties.get("research_phase", {}).get("const") != "DEEP_WEB"
            or properties.get("network_research_performed", {}).get("const") is not True
            or properties.get("cross_read_performed", {}).get("const") is not False
            or any(properties.get(name) != {"$ref": "#/$defs/file_binding"} for name in binding_fields)
            or any(properties.get(name) != {"$ref": "#/$defs/nonempty_identifiers"} for name in id_fields)
            or properties.get("query_events")
            != {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/query_event"}}
            or properties.get("sources")
            != {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/source"}}
            or not binding_or_null_is_exact(properties.get("download_authority_binding"))
            or properties.get("acquisitions")
            != {"type": "array", "items": {"$ref": "#/$defs/acquisition"}}
            or not object_shape_is_exact(query_event, query_fields)
            or query_properties.get("result_capture_binding") != {"$ref": "#/$defs/file_binding"}
            or query_properties.get("returned_source_ids") != {"$ref": "#/$defs/nonempty_identifiers"}
            or not object_shape_is_exact(source, source_fields)
            or source_properties.get("research_phase", {}).get("enum")
            != ["DEEP_WEB", "DOWNLOADED_PRIMARY"]
            or source_properties.get("capture_mode", {}).get("enum")
            != ["CAPTURE_MD_ONLY", "QUARANTINED_RAW"]
            or source_properties.get("capture_binding") != {"$ref": "#/$defs/file_binding"}
            or not object_shape_is_exact(acquisition, acquisition_fields)
            or acquisition_properties.get("rights_status", {}).get("enum")
            != ["AUTHORIZED", "OWNED", "LICENSED", "PUBLIC"]
            or acquisition_properties.get("scan_status", {}).get("const") != "PASS"
            or acquisition_properties.get("handling_policy", {}).get("const")
            != "QUARANTINE_HASH_NEVER_EXECUTE"
            or rule.get("if", {}).get("properties", {}).get("download_performed", {}).get("const") is not False
            or set(rule.get("if", {}).get("required", [])) != {"download_performed"}
            or then_properties.get("download_authority_binding") != {"type": "null"}
            or then_properties.get("acquisitions", {}).get("maxItems") != 0
            or len(then_source) != 2
            or {"$ref": "#/$defs/source"} not in then_source
            or not any(
                item.get("properties", {}).get("capture_mode", {}).get("const") == "CAPTURE_MD_ONLY"
                and item.get("properties", {}).get("research_phase", {}).get("const") == "DEEP_WEB"
                for item in then_source if isinstance(item, dict)
            )
            or else_properties.get("download_authority_binding") != {"$ref": "#/$defs/file_binding"}
            or else_properties.get("acquisitions", {}).get("minItems") != 1
            or else_contains.get("properties", {}).get("research_phase", {}).get("const")
            != "DOWNLOADED_PRIMARY"
            or else_contains.get("properties", {}).get("capture_mode", {}).get("const")
            != "QUARANTINED_RAW"
            or set(else_contains.get("required", [])) != {"research_phase", "capture_mode"}
            or else_properties.get("sources", {}).get("minContains") != 1
        ):
            errors.append("L3_SCHEMA_WEB_RESEARCH_RECEIPT_CONTRACT_DRIFT")

    source_manifest = loaded.get("source_manifest.schema.json")
    if source_manifest is not None:
        properties = source_manifest["properties"]
        definitions = source_manifest.get("$defs", {})
        expected_shapes = {
            "source": {
                "source_id", "research_phase", "locator", "title", "publisher", "accessed_at",
                "capture_mode", "capture_binding", "sections_consulted",
            },
            "finding": {"finding_id", "statement", "source_ids", "confidence", "freshness"},
            "conflict": {"conflict_id", "source_ids", "statement", "status", "analysis"},
            "dissent_item": {"dissent_id", "statement", "source_ids", "status", "rationale"},
            "provenance_item": {
                "provenance_id", "sources_actually_read", "version_hash_access_date",
                "sections_consulted", "received_material_not_used", "facts_extracted",
                "model_synthesis_or_inference", "conflicts_gaps_and_limits",
            },
            "received_not_used_item": {"item_id", "reason_code", "rationale"},
            "acquisition": {
                "acquisition_id", "source_id", "origin_locator", "media_type", "retrieved_at",
                "content_binding", "rights_status", "rights_evidence_binding", "scan_status",
                "scan_receipt_binding", "handling_policy",
            },
        }
        source_properties = definitions.get("source", {}).get("properties", {})
        finding_properties = definitions.get("finding", {}).get("properties", {})
        conflict_properties = definitions.get("conflict", {}).get("properties", {})
        dissent_properties = definitions.get("dissent_item", {}).get("properties", {})
        provenance_properties = definitions.get("provenance_item", {}).get("properties", {})
        received_properties = definitions.get("received_not_used_item", {}).get("properties", {})
        acquisition_properties = definitions.get("acquisition", {}).get("properties", {})
        rules = source_manifest.get("allOf", [])
        rule = rules[0] if len(rules) == 1 and isinstance(rules[0], dict) else {}
        then_properties = rule.get("then", {}).get("properties", {})
        else_properties = rule.get("else", {}).get("properties", {})
        else_contains = else_properties.get("sources", {}).get("contains", {})
        binding_fields = (
            "material_join_binding", "light_map_binding", "deep_plan_binding",
            "deep_research_receipt_binding",
        )
        identifier_fields = ("light_source_ids", "deep_source_ids", "deep_new_source_ids")
        array_ref_fields = {
            "conflicts": "#/$defs/conflict", "dissent": "#/$defs/dissent_item",
            "received_not_used": "#/$defs/received_not_used_item",
            "acquisitions": "#/$defs/acquisition",
        }
        if (
            properties.get("status", {}).get("const") != "SOURCE_MANIFEST_FROZEN"
            or properties.get("task_id") != {"$ref": "#/$defs/identifier"}
            or properties.get("role", {}).get("enum") != ["BUILDER", "VERIFIER"]
            or any(properties.get(name) != {"$ref": "#/$defs/file_binding"} for name in binding_fields)
            or any(properties.get(name) != {"$ref": "#/$defs/nonempty_identifiers"} for name in identifier_fields)
            or properties.get("material_source_ids", {}).get("type") != "array"
            or properties.get("material_source_ids", {}).get("uniqueItems") is not True
            or properties.get("sources")
            != {"type": "array", "minItems": 2, "items": {"$ref": "#/$defs/source"}}
            or properties.get("findings")
            != {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/finding"}}
            or properties.get("provenance")
            != {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/provenance_item"}}
            or any(
                properties.get(name) != {"type": "array", "items": {"$ref": reference}}
                for name, reference in array_ref_fields.items()
            )
            or properties.get("download_mode", {}).get("enum")
            != ["CAPTURE_MD_ONLY", "QUARANTINED_RAW"]
            or not binding_or_null_is_exact(properties.get("download_authority_binding"))
            or properties.get("download_fallback", {}).get("enum")
            != ["CAPTURE_MD_ONLY", "NOT_APPLICABLE"]
            or properties.get("cross_read_performed", {}).get("const") is not False
            or any(
                not object_shape_is_exact(definitions.get(name), fields)
                for name, fields in expected_shapes.items()
            )
            or source_properties.get("research_phase", {}).get("enum")
            != ["USER_MATERIAL", "LIGHT_WEB", "DEEP_WEB", "DOWNLOADED_PRIMARY"]
            or source_properties.get("capture_mode", {}).get("enum")
            != ["CAPTURE_MD_ONLY", "QUARANTINED_RAW", "USER_PROVIDED"]
            or source_properties.get("capture_binding") != {"$ref": "#/$defs/file_binding"}
            or finding_properties.get("confidence", {}).get("enum")
            != ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
            or finding_properties.get("freshness", {}).get("enum")
            != ["CURRENT_PRIMARY", "CURRENT_SECONDARY", "HISTORICAL", "UNKNOWN"]
            or conflict_properties.get("source_ids", {}).get("minItems") != 2
            or conflict_properties.get("source_ids", {}).get("uniqueItems") is not True
            or conflict_properties.get("status", {}).get("enum")
            != ["RESOLVED", "UNRESOLVED_NONBLOCKING", "BLOCKING"]
            or dissent_properties.get("status", {}).get("enum")
            != ["OPEN", "PRESERVED_NONBLOCKING", "ESCALATED_BLOCKING"]
            or provenance_properties.get("sources_actually_read")
            != {"$ref": "#/$defs/nonempty_identifiers"}
            or provenance_properties.get("version_hash_access_date", {}).get("minItems") != 1
            or provenance_properties.get("sections_consulted", {}).get("minItems") != 1
            or received_properties.get("item_id") != {"$ref": "#/$defs/identifier"}
            or received_properties.get("reason_code") != {"$ref": "#/$defs/identifier"}
            or acquisition_properties.get("rights_status", {}).get("enum")
            != ["AUTHORIZED", "OWNED", "LICENSED", "PUBLIC"]
            or acquisition_properties.get("scan_status", {}).get("const") != "PASS"
            or acquisition_properties.get("handling_policy", {}).get("const")
            != "QUARANTINE_HASH_NEVER_EXECUTE"
            or rule.get("if", {}).get("properties", {}).get("download_mode", {}).get("const")
            != "CAPTURE_MD_ONLY"
            or set(rule.get("if", {}).get("required", [])) != {"download_mode"}
            or then_properties.get("download_authority_binding") != {"type": "null"}
            or then_properties.get("acquisitions", {}).get("maxItems") != 0
            or then_properties.get("download_fallback", {}).get("const") != "CAPTURE_MD_ONLY"
            or else_properties.get("download_authority_binding") != {"$ref": "#/$defs/file_binding"}
            or else_properties.get("acquisitions", {}).get("minItems") != 1
            or else_properties.get("download_fallback", {}).get("const") != "NOT_APPLICABLE"
            or else_contains.get("properties", {}).get("research_phase", {}).get("const")
            != "DOWNLOADED_PRIMARY"
            or else_contains.get("properties", {}).get("capture_mode", {}).get("const")
            != "QUARANTINED_RAW"
            or set(else_contains.get("required", [])) != {"research_phase", "capture_mode"}
            or else_properties.get("sources", {}).get("minContains") != 1
        ):
            errors.append("L3_SCHEMA_SOURCE_MANIFEST_CONTRACT_DRIFT")


def _rotation_contract(root: Path, errors: list[str]) -> None:
    path = root / "schemas" / "rotation_state.schema.json"
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"ROTATION_SCHEMA_INVALID:{type(error).__name__}:{error}")
        return
    properties = contract.get("properties")
    required = contract.get("required")
    if contract.get("$id") != "urn:omni-builder:rotation-state:2" or contract.get("additionalProperties") is not False:
        errors.append("ROTATION_SCHEMA_ENVELOPE_DRIFT")
    if not isinstance(properties, dict) or not isinstance(required, list) or set(required) != set(properties):
        errors.append("ROTATION_SCHEMA_REQUIRED_DRIFT")
        return
    if properties.get("schema", {}).get("const") != "omni-rotation-state-v2":
        errors.append("ROTATION_SCHEMA_CONST_DRIFT")
    if properties.get("state", {}).get("enum") != ROTATION_ORDER:
        errors.append("ROTATION_SCHEMA_STATE_MACHINE_DRIFT")
    for name, value in (("max_spawn", 1), ("recurrence", False), ("scope", "F3_F4_ONLY")):
        if properties.get(name, {}).get("const") != value:
            errors.append(f"ROTATION_SCHEMA_{name.upper()}_CONST_DRIFT")
    sentinels = properties.get("sentinels", {})
    sentinel_properties = sentinels.get("properties", {}) if isinstance(sentinels, dict) else {}
    if (
        sentinels.get("type") != "object"
        or sentinels.get("additionalProperties") is not False
        or set(sentinels.get("required", [])) != {"agentic", "script", "context"}
        or set(sentinel_properties) != {"agentic", "script", "context"}
        or any(sentinel_properties.get(name) != {"type": "boolean"} for name in ("agentic", "script", "context"))
    ):
        errors.append("ROTATION_SCHEMA_SENTINELS_DRIFT")


def _state_and_receipt_contract(root: Path, errors: list[str]) -> None:
    contracts = (
        ("turn_state.schema.json", "urn:omni-builder:turn-state:1", "omni-turn-state-v1", TURN_STATUSES),
        ("receipt.schema.json", "urn:omni-builder:receipt:1", "omni-receipt-v1", RECEIPT_STATUSES),
    )
    for filename, identifier, schema_const, statuses in contracts:
        try:
            schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors.append(f"STATE_SCHEMA_INVALID:{filename}:{type(error).__name__}:{error}")
            continue
        properties = schema.get("properties")
        required = schema.get("required")
        if schema.get("$id") != identifier or schema.get("additionalProperties") is not False:
            errors.append(f"STATE_SCHEMA_ENVELOPE_DRIFT:{filename}")
        if not isinstance(properties, dict) or not isinstance(required, list) or set(required) != set(properties):
            errors.append(f"STATE_SCHEMA_REQUIRED_DRIFT:{filename}")
            continue
        if properties.get("schema", {}).get("const") != schema_const:
            errors.append(f"STATE_SCHEMA_CONST_DRIFT:{filename}")
        if properties.get("status", {}).get("enum") != statuses:
            errors.append(f"STATE_SCHEMA_STATUS_DRIFT:{filename}")
        sha = schema.get("$defs", {}).get("sha256")
        if sha != {"type": "string", "pattern": "^[A-F0-9]{64}$"}:
            errors.append(f"STATE_SCHEMA_SHA256_DRIFT:{filename}")


def _guided_intake_contract(root: Path, errors: list[str]) -> None:
    filename = "guided_intake_state.schema.json"
    try:
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"GUIDED_INTAKE_SCHEMA_INVALID:{type(error).__name__}:{error}")
        return
    properties = schema.get("properties")
    required = schema.get("required")
    if schema.get("$id") != "urn:omni-builder:guided-intake-state:1" or schema.get("additionalProperties") is not False:
        errors.append("GUIDED_INTAKE_SCHEMA_ENVELOPE_DRIFT")
    if (
        not isinstance(properties, dict)
        or not isinstance(required, list)
        or set(required) != GUIDED_INTAKE_ROOT_FIELDS
        or set(properties) != GUIDED_INTAKE_ROOT_FIELDS
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_REQUIRED_DRIFT")
        return
    if properties.get("schema", {}).get("const") != "omni-guided-intake-state-v1":
        errors.append("GUIDED_INTAKE_SCHEMA_CONST_DRIFT")
    if properties.get("phase", {}).get("enum") != GUIDED_INTAKE_PHASES:
        errors.append("GUIDED_INTAKE_SCHEMA_PHASE_DRIFT")
    if properties.get("status", {}).get("enum") != GUIDED_INTAKE_STATUSES:
        errors.append("GUIDED_INTAKE_SCHEMA_STATUS_DRIFT")
    definitions = schema.get("$defs", {})
    if definitions.get("run_kind", {}).get("enum") != ["REAL", "DRY_RUN"] or properties.get("run_kind") != {"$ref": "#/$defs/run_kind"}:
        errors.append("GUIDED_INTAKE_SCHEMA_RUN_KIND_DRIFT")
    if (
        definitions.get("effect_policy", {}).get("enum") != ["DOWNSTREAM_GATED_REAL", "SIMULATE_WITHOUT_MATERIALIZATION"]
        or properties.get("effect_policy") != {"$ref": "#/$defs/effect_policy"}
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_EFFECT_POLICY_DRIFT")
    if properties.get("topology", {}).get("enum") != ["SOLO_DUAL_HAT", "TEAM_DUAL_LANE"]:
        errors.append("GUIDED_INTAKE_SCHEMA_TOPOLOGY_DRIFT")

    activation = definitions.get("activation_binding", {})
    activation_fields = activation.get("properties", {}) if isinstance(activation, dict) else {}
    if (
        properties.get("activation_binding") != {"$ref": "#/$defs/activation_binding"}
        or
        activation.get("type") != "object"
        or activation.get("additionalProperties") is not False
        or activation_fields.get("decision_schema", {}).get("const") != "omni-invocation-decision-v2"
        or activation_fields.get("decision_status", {}).get("const") != "ACTIVATION_ALLOWED"
        or activation_fields.get("activation_grants", {}).get("const") != ["METHOD_USE"]
        or activation_fields.get("intake_allowed", {}).get("const") is not True
        or activation_fields.get("mode_selection_allowed", {}).get("const") is not False
        or activation_fields.get("mode_gate", {}).get("const") != "MODE_BEFORE_PROGRAM"
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_ACTIVATION_BINDING_DRIFT")
    if activation_fields.get("activation_path", {}).get("enum") != GUIDED_ACTIVATION_PATHS:
        errors.append("GUIDED_INTAKE_SCHEMA_ACTIVATION_PATH_DRIFT")
    if activation_fields.get("task_scope", {}).get("const") != "CURRENT_TASK_ONLY":
        errors.append("GUIDED_INTAKE_SCHEMA_TASK_SCOPE_DRIFT")
    if activation_fields.get("activation_non_grants", {}).get("const") != GUIDED_ACTIVATION_NON_GRANTS:
        errors.append("GUIDED_INTAKE_SCHEMA_ACTIVATION_NON_GRANTS_DRIFT")
    progressive_activation_fields = {
        "path", "bytes", "sha256", "receipt_outcome", "decision_schema", "decision_status",
        "activation_path", "task_scope", "run_kind", "effect_policy", "knowledge_available",
        "skill_invoked", "effect_authorized", "activation_level", "modules_used",
        "authority_grants", "artifact_grants", "requested_effects", "effect_grants", "non_grants",
        "access_envelope_identity", "activation_grants", "activation_non_grants", "intake_allowed",
        "mode_selection_allowed", "mode_gate", "next_gate",
    }
    if (
        set(activation.get("required", [])) != progressive_activation_fields
        or set(activation_fields) != progressive_activation_fields
        or activation_fields.get("knowledge_available", {}).get("const") is not True
        or activation_fields.get("skill_invoked", {}).get("const") is not True
        or activation_fields.get("effect_authorized", {}).get("const") is not False
        or activation_fields.get("activation_level", {}).get("const") != "OMNI_FULL"
        or activation_fields.get("modules_used", {}).get("const") != []
        or activation_fields.get("authority_grants", {}).get("const") != FULL_ACTIVATION_AUTHORITY_GRANTS
        or activation_fields.get("artifact_grants", {}).get("const") != []
        or activation_fields.get("requested_effects", {}).get("const") != []
        or activation_fields.get("effect_grants", {}).get("const") != []
        or activation_fields.get("non_grants", {}).get("const") != FULL_ACTIVATION_NON_GRANTS
        or activation_fields.get("access_envelope_identity", {}).get("const") != "PENDING"
        or activation_fields.get("next_gate", {}).get("const") != "GUIDED_INTAKE"
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_PROGRESSIVE_ACTIVATION_DRIFT")

    file_binding = definitions.get("file_binding", {})
    file_fields = file_binding.get("properties", {}) if isinstance(file_binding, dict) else {}
    file_all_of = file_binding.get("allOf", []) if isinstance(file_binding, dict) else []
    file_path_overlay = (
        file_all_of[0].get("properties", {}).get("path")
        if len(file_all_of) == 1 and isinstance(file_all_of[0], dict)
        else None
    )
    if (
        file_binding.get("type") != "object"
        or file_binding.get("additionalProperties") is not False
        or set(file_binding.get("required", [])) != {"path", "bytes", "sha256"}
        or set(file_fields) != {"path", "bytes", "sha256"}
        or file_fields.get("path") != {"type": "string", "minLength": 1}
        or file_path_overlay != {"$ref": "#/$defs/absolute_path"}
        or file_fields.get("bytes") != {"type": "integer", "minimum": 1}
        or file_fields.get("sha256") != {"$ref": "#/$defs/sha256"}
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_FILE_BINDING_DRIFT")

    station = definitions.get("station", {})
    station_fields = station.get("properties", {}) if isinstance(station, dict) else {}
    source_refs = station_fields.get("source_refs", {}) if isinstance(station_fields, dict) else {}
    station_ids = definitions.get("station_id", {}).get("enum", [])
    if (
        source_refs.get("type") != "array"
        or source_refs.get("uniqueItems") is not True
        or source_refs.get("items") != {"$ref": "#/$defs/file_binding"}
        or "ACCESS_GRANT" not in station_ids
        or "USER_MATERIAL" not in station_ids
        or station_ids.index("ACCESS_GRANT") > station_ids.index("USER_MATERIAL")
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_EVIDENCE_BINDING_DRIFT")

    session_pair = definitions.get("session_pair", {})
    pair_fields = session_pair.get("properties", {}) if isinstance(session_pair, dict) else {}
    if (
        properties.get("session_pair") != {"$ref": "#/$defs/session_pair"}
        or
        session_pair.get("type") != "object"
        or session_pair.get("additionalProperties") is not False
        or pair_fields.get("lock_status", {}).get("const") != "LOCKED_UNTIL_CUTOVER"
        or not {"builder", "verifier"}.issubset(pair_fields)
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_SESSION_PAIR_DRIFT")

    participant = definitions.get("participant", {})
    participant_fields = participant.get("properties", {}) if isinstance(participant, dict) else {}
    participant_all_of = participant.get("allOf", []) if isinstance(participant, dict) else []
    participant_path_overlay = (
        participant_all_of[0].get("properties", {})
        if len(participant_all_of) == 1 and isinstance(participant_all_of[0], dict)
        else {}
    )
    if (
        participant.get("type") != "object"
        or participant.get("additionalProperties") is not False
        or not {"mandate_path", "mandate_bytes", "mandate_sha256"}.issubset(set(participant.get("required", [])))
        or participant_fields.get("mandate_path") != {"type": "string", "minLength": 1}
        or participant_path_overlay.get("mandate_path") != {"$ref": "#/$defs/absolute_path"}
        or participant_path_overlay.get("write_lane") != {"$ref": "#/$defs/absolute_path"}
        or participant_path_overlay.get("owned_paths") != {"items": {"$ref": "#/$defs/absolute_path"}}
        or participant_fields.get("mandate_bytes") != {"type": "integer", "minimum": 1}
        or participant_fields.get("mandate_sha256") != {"$ref": "#/$defs/sha256"}
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_MANDATE_BINDING_DRIFT")

    team_card = definitions.get("team_card", {})
    team_fields = team_card.get("properties", {}) if isinstance(team_card, dict) else {}
    team_statuses = team_fields.get("status", {}).get("enum", [])
    if (
        properties.get("team_card") != {"$ref": "#/$defs/team_card"}
        or
        team_card.get("type") != "object"
        or team_card.get("additionalProperties") is not False
        or team_statuses != ["DRAFT", "AWAITING_DUAL_ACK", "TEAM_CARD_DUAL_ACK", "BLOCKED"]
        or team_fields.get("acks", {}).get("properties", {}).get("builder") != {"$ref": "#/$defs/team_ack"}
        or team_fields.get("acks", {}).get("properties", {}).get("verifier") != {"$ref": "#/$defs/team_ack"}
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_TEAM_CARD_DRIFT")

    relay = definitions.get("relay", {})
    relay_fields = relay.get("properties", {}) if isinstance(relay, dict) else {}
    relay_all_of = relay.get("allOf", []) if isinstance(relay, dict) else []
    relay_path_overlay = (
        relay_all_of[0].get("properties", {}).get("pm_write_lane")
        if len(relay_all_of) == 1 and isinstance(relay_all_of[0], dict)
        else None
    )
    if (
        properties.get("relay") != {"$ref": "#/$defs/relay"}
        or
        relay.get("type") != "object"
        or relay.get("additionalProperties") is not False
        or relay_fields.get("transport", {}).get("const") != "PM_RELAY"
        or relay_fields.get("same_pair_required", {}).get("const") is not True
        or relay_fields.get("governed_channel_equivalent", {}).get("const") is not False
        or relay_fields.get("pm_write_lane") != {"type": "string", "minLength": 1}
        or relay_path_overlay != {"$ref": "#/$defs/absolute_path"}
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_RELAY_DRIFT")

    relay_record = definitions.get("relay_record", {})
    relay_record_fields = relay_record.get("properties", {}) if isinstance(relay_record, dict) else {}
    relay_record_all_of = relay_record.get("allOf", []) if isinstance(relay_record, dict) else []
    relay_payload_path_overlay = (
        relay_record_all_of[0].get("properties", {}).get("payload_path")
        if len(relay_record_all_of) == 1 and isinstance(relay_record_all_of[0], dict)
        else None
    )
    if (
        relay_record.get("type") != "object"
        or relay_record.get("additionalProperties") is not False
        or not {"payload_path", "payload_bytes", "payload_sha256"}.issubset(set(relay_record.get("required", [])))
        or relay_record_fields.get("payload_path") != {"type": "string", "minLength": 1}
        or relay_payload_path_overlay != {"$ref": "#/$defs/absolute_path"}
        or relay_record_fields.get("payload_bytes") != {"type": "integer", "minimum": 1}
        or relay_record_fields.get("payload_sha256") != {"$ref": "#/$defs/sha256"}
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_RELAY_PHYSICAL_BINDING_DRIFT")

    workspace = definitions.get("workspace_access_envelope_contract", {})
    workspace_fields = workspace.get("properties", {}) if isinstance(workspace, dict) else {}
    expected_workspace_fields = {
        "schema", "status", "outcome", "envelope_id", "activation_receipt_sha256",
        "task_id", "task_root", "project_root", "source_roots", "owned_lane_root",
        "session_pair_sha256", "run_kind", "requested_capabilities", "granted_capabilities",
        "non_grants", "separate_authorizations_required", "excluded_paths",
        "probe_receipt_binding", "record_digest",
    }
    workspace_all_of = workspace.get("allOf", []) if isinstance(workspace, dict) else []
    access_ready_then = workspace_all_of[0].get("then", {}).get("properties", {}) if len(workspace_all_of) > 0 else {}
    dry_run_then = workspace_all_of[1].get("then", {}).get("properties", {}) if len(workspace_all_of) > 1 else {}
    granted_rule = next(
        (
            rule for rule in workspace_all_of
            if rule.get("if") == {
                "properties": {"outcome": {"const": "ACCESS_GRANTED_NON_DESTRUCTIVE"}},
                "required": ["outcome"],
            }
        ),
        {},
    )
    unavailable_real_rule = next(
        (
            rule for rule in workspace_all_of
            if rule.get("if") == {
                "properties": {
                    "status": {"const": "AUTONOMY_UNAVAILABLE_NO_ACCESS"},
                    "run_kind": {"const": "REAL"},
                },
                "required": ["status", "run_kind"],
            }
        ),
        {},
    )
    partial_rule = next(
        (
            rule for rule in workspace_all_of
            if rule.get("if") == {
                "properties": {"outcome": {"const": "ACCESS_PARTIAL"}},
                "required": ["outcome"],
            }
        ),
        {},
    )
    denied_rule = next(
        (
            rule for rule in workspace_all_of
            if rule.get("if") == {
                "properties": {"outcome": {"const": "ACCESS_DENIED"}},
                "required": ["outcome"],
            }
        ),
        {},
    )
    granted_then = granted_rule.get("then", {}).get("properties", {})
    unavailable_real_then = unavailable_real_rule.get("then", {}).get("properties", {})
    partial_then = partial_rule.get("then", {}).get("properties", {})
    denied_then = denied_rule.get("then", {}).get("properties", {})
    if (
        properties.get("workspace_access_envelope") != {"$ref": "#/$defs/workspace_access_envelope_contract"}
        or workspace.get("type") != "object"
        or workspace.get("additionalProperties") is not False
        or set(workspace.get("required", [])) != expected_workspace_fields
        or set(workspace_fields) != expected_workspace_fields
        or workspace_fields.get("schema", {}).get("const") != "omni-workspace-access-envelope-v1"
        or workspace_fields.get("status", {}).get("enum") != ["ACCESS_READY", "AUTONOMY_UNAVAILABLE_NO_ACCESS"]
        or workspace_fields.get("outcome", {}).get("enum") != ["ACCESS_GRANTED_NON_DESTRUCTIVE", "ACCESS_PARTIAL", "ACCESS_DENIED", "ACCESS_PLANNED_DRY_RUN"]
        or workspace_fields.get("requested_capabilities", {}).get("const") != WORKSPACE_GRANTS
        or workspace_fields.get("non_grants", {}).get("const") != WORKSPACE_NON_GRANTS
        or workspace_fields.get("separate_authorizations_required", {}).get("const") != WORKSPACE_SEPARATE_AUTHORIZATIONS
        or workspace_fields.get("probe_receipt_binding", {}).get("anyOf") != [
            {"$ref": "#/$defs/file_binding"}, {"type": "null"},
        ]
        or len(workspace_all_of) != 6
        or access_ready_then.get("outcome", {}).get("const") != "ACCESS_GRANTED_NON_DESTRUCTIVE"
        or access_ready_then.get("run_kind", {}).get("const") != "REAL"
        or access_ready_then.get("granted_capabilities", {}).get("const") != WORKSPACE_GRANTS
        or access_ready_then.get("probe_receipt_binding") != {"$ref": "#/$defs/file_binding"}
        or dry_run_then.get("status", {}).get("const") != "AUTONOMY_UNAVAILABLE_NO_ACCESS"
        or dry_run_then.get("outcome", {}).get("const") != "ACCESS_PLANNED_DRY_RUN"
        or dry_run_then.get("granted_capabilities", {}).get("maxItems") != 0
        or dry_run_then.get("probe_receipt_binding") != {"type": "null"}
        or granted_then != {
            "status": {"const": "ACCESS_READY"},
            "run_kind": {"const": "REAL"},
            "granted_capabilities": {"const": WORKSPACE_GRANTS},
            "probe_receipt_binding": {"$ref": "#/$defs/file_binding"},
        }
        or unavailable_real_then != {
            "outcome": {"enum": ["ACCESS_PARTIAL", "ACCESS_DENIED"]},
            "probe_receipt_binding": {"type": "null"},
        }
        or partial_then != {
            "status": {"const": "AUTONOMY_UNAVAILABLE_NO_ACCESS"},
            "run_kind": {"const": "REAL"},
            "granted_capabilities": {"minItems": 1, "maxItems": 3},
            "probe_receipt_binding": {"type": "null"},
        }
        or denied_then != {
            "status": {"const": "AUTONOMY_UNAVAILABLE_NO_ACCESS"},
            "run_kind": {"const": "REAL"},
            "granted_capabilities": {"maxItems": 0},
            "probe_receipt_binding": {"type": "null"},
        }
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_WORKSPACE_ACCESS_DRIFT")

    closure = definitions.get("critical_closure", {})
    closure_fields = closure.get("properties", {}) if isinstance(closure, dict) else {}
    if (
        properties.get("critical_closure") != {"$ref": "#/$defs/critical_closure"}
        or
        closure.get("type") != "object"
        or closure.get("additionalProperties") is not False
        or properties.get("station_matrix_sha256") != {"$ref": "#/$defs/sha256"}
        or closure_fields.get("derivation", {}).get("const") != "RECOMPUTED_FROM_EVIDENCE_AND_FOUR_READBACK_V2"
        or closure_fields.get("station_matrix_sha256") != {"$ref": "#/$defs/sha256"}
        or closure_fields.get("question_matrix_sha256") != {"$ref": "#/$defs/sha256"}
        or set(closure.get("required", [])) != {
            "derivation", "station_matrix_sha256", "question_matrix_sha256",
            "status", "open_question_ids", "computed_at",
        }
        or closure_fields.get("status", {}).get("enum") != ["OPEN", "CLOSED"]
    ):
        errors.append("GUIDED_INTAKE_SCHEMA_CRITICAL_CLOSURE_DRIFT")

    sha = definitions.get("sha256")
    if sha != {"type": "string", "pattern": "^[A-F0-9]{64}$"}:
        errors.append("GUIDED_INTAKE_SCHEMA_SHA256_DRIFT")
    if jsonschema is None:
        errors.append("JSONSCHEMA_RUNTIME_UNAVAILABLE:guided_intake")
    else:
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as error:
            errors.append(f"GUIDED_INTAKE_SCHEMA_INVALID:{error.message}")


def _closed_l2_artifact_contract(root: Path, errors: list[str]) -> None:
    filenames = (
        "fused_program.schema.json",
        "program_countersign_receipt.schema.json",
        "workspace_access_envelope.schema.json",
        "workspace_access_probe_receipt.schema.json",
    )
    schemas: dict[str, dict[str, Any]] = {}
    for filename in filenames:
        try:
            schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors.append(f"L2_ARTIFACT_SCHEMA_INVALID:{filename}:{type(error).__name__}:{error}")
            continue
        schemas[filename] = schema
        properties = schema.get("properties")
        if (
            schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
            or not isinstance(properties, dict)
            or set(schema.get("required", [])) != set(properties)
        ):
            errors.append(f"L2_ARTIFACT_SCHEMA_ENVELOPE_DRIFT:{filename}")
        if jsonschema is None:
            errors.append(f"JSONSCHEMA_RUNTIME_UNAVAILABLE:{filename}")
        else:
            try:
                jsonschema.Draft202012Validator.check_schema(schema)
            except jsonschema.exceptions.SchemaError as error:
                errors.append(f"L2_ARTIFACT_SCHEMA_INVALID:{filename}:{error.message}")

    program = schemas.get("fused_program.schema.json", {})
    program_fields = program.get("properties", {}) if isinstance(program, dict) else {}
    work_item = program.get("$defs", {}).get("work_item", {}) if isinstance(program, dict) else {}
    work_fields = work_item.get("properties", {}) if isinstance(work_item, dict) else {}
    if (
        program.get("$id") != "urn:omni-builder:fused-program:2"
        or program_fields.get("schema", {}).get("const") != "omni-fused-program-v2"
        or program_fields.get("kind", {}).get("const") != "PROGRAM_FUSION_CANDIDATE"
        or program_fields.get("status", {}).get("const") != "PROGRAM_FUSION_FROZEN"
        or program_fields.get("author_role", {}).get("const") != "BUILDER"
        or program_fields.get("profile", {}).get("const") != "GODMODE"
        or program_fields.get("fused_from_lanes", {}).get("const") != ["BUILDER", "VERIFIER"]
        or program_fields.get("work_items", {}).get("items") != {"$ref": "#/$defs/work_item"}
        or work_item.get("additionalProperties") is not False
        or set(work_item.get("required", [])) != set(work_fields)
        or set(work_fields) != {
            "work_id", "ordinal", "title", "result", "persistent_artifact", "owner_role",
            "depends_on", "preconditions", "required_capabilities", "budget",
            "acceptance_evidence", "verifier_role", "rollback", "failure_states",
            "next_gate", "scope", "origin_refs",
        }
        or work_fields.get("preconditions", {}).get("minItems") != 1
        or work_fields.get("required_capabilities", {}).get("minItems") != 1
        or work_fields.get("acceptance_evidence", {}).get("minItems") != 1
        or work_fields.get("origin_refs", {}).get("minItems") != 1
    ):
        errors.append("FUSED_PROGRAM_SCHEMA_CONTRACT_DRIFT")

    receipt = schemas.get("program_countersign_receipt.schema.json", {})
    receipt_fields = receipt.get("properties", {}) if isinstance(receipt, dict) else {}
    if (
        receipt.get("$id") != "urn:omni-builder:program-countersign-receipt:2"
        or receipt_fields.get("schema", {}).get("const") != "omni-program-countersign-receipt-v2"
        or receipt_fields.get("status", {}).get("enum") != [
            "PROGRAM_COUNTERSIGN_ACCEPTED", "PROGRAM_COUNTERSIGN_BLOCKED",
            "PROGRAM_COUNTERSIGN_INCONCLUSIVE",
        ]
        or receipt_fields.get("decision", {}).get("enum") != ["ACCEPTED", "BLOCK", "INCONCLUSIVE"]
        or receipt_fields.get("signer_role", {}).get("const") != "VERIFIER"
        or not {
            "program_binding", "program_record_digest", "knowledge_state_binding",
            "knowledge_fusion_countersign_binding", "session_pair_sha256",
            "program_author_session_id", "verifier_report_binding", "reproduction",
            "finding_codes", "evidence_bindings",
        }.issubset(receipt_fields)
    ):
        errors.append("PROGRAM_COUNTERSIGN_SCHEMA_CONTRACT_DRIFT")

    access = schemas.get("workspace_access_envelope.schema.json", {})
    access_fields = access.get("properties", {}) if isinstance(access, dict) else {}
    access_all_of = access.get("allOf", []) if isinstance(access, dict) else []
    access_ready_rule = next(
        (
            rule for rule in access_all_of
            if rule.get("if", {}).get("properties", {}).get("status", {}).get("const") == "ACCESS_READY"
        ),
        {},
    )
    dry_run_rule = next(
        (
            rule for rule in access_all_of
            if rule.get("if", {}).get("properties", {}).get("run_kind", {}).get("const") == "DRY_RUN"
        ),
        {},
    )
    granted_rule = next(
        (
            rule for rule in access_all_of
            if rule.get("if") == {
                "properties": {"outcome": {"const": "ACCESS_GRANTED_NON_DESTRUCTIVE"}},
                "required": ["outcome"],
            }
        ),
        {},
    )
    unavailable_real_rule = next(
        (
            rule for rule in access_all_of
            if rule.get("if") == {
                "properties": {
                    "status": {"const": "AUTONOMY_UNAVAILABLE_NO_ACCESS"},
                    "run_kind": {"const": "REAL"},
                },
                "required": ["status", "run_kind"],
            }
        ),
        {},
    )
    partial_rule = next(
        (
            rule for rule in access_all_of
            if rule.get("if") == {
                "properties": {"outcome": {"const": "ACCESS_PARTIAL"}},
                "required": ["outcome"],
            }
        ),
        {},
    )
    denied_rule = next(
        (
            rule for rule in access_all_of
            if rule.get("if") == {
                "properties": {"outcome": {"const": "ACCESS_DENIED"}},
                "required": ["outcome"],
            }
        ),
        {},
    )
    access_ready_then = access_ready_rule.get("then", {}).get("properties", {})
    dry_run_then = dry_run_rule.get("then", {}).get("properties", {})
    granted_then = granted_rule.get("then", {}).get("properties", {})
    unavailable_real_then = unavailable_real_rule.get("then", {}).get("properties", {})
    partial_then = partial_rule.get("then", {}).get("properties", {})
    denied_then = denied_rule.get("then", {}).get("properties", {})
    if (
        access.get("$id") != "urn:omni-builder:workspace-access-envelope:1"
        or access_fields.get("schema", {}).get("const") != "omni-workspace-access-envelope-v1"
        or access_fields.get("requested_capabilities", {}).get("const") != WORKSPACE_GRANTS
        or access_fields.get("non_grants", {}).get("const") != WORKSPACE_NON_GRANTS
        or access_fields.get("separate_authorizations_required", {}).get("const") != WORKSPACE_SEPARATE_AUTHORIZATIONS
        or "ACCESS_READY" not in access_fields.get("status", {}).get("enum", [])
        or "AUTONOMY_UNAVAILABLE_NO_ACCESS" not in access_fields.get("status", {}).get("enum", [])
        or "ACCESS_PLANNED_DRY_RUN" not in access_fields.get("outcome", {}).get("enum", [])
        or "probe_receipt_binding" not in access_fields
        or len(access_all_of) != 6
        or access_ready_rule.get("if") != {
            "properties": {"status": {"const": "ACCESS_READY"}},
            "required": ["status"],
        }
        or set(access_ready_then) != {
            "outcome", "run_kind", "granted_capabilities", "probe_receipt_binding",
        }
        or access_ready_then.get("outcome", {}).get("const") != "ACCESS_GRANTED_NON_DESTRUCTIVE"
        or access_ready_then.get("run_kind", {}).get("const") != "REAL"
        or access_ready_then.get("granted_capabilities", {}).get("const") != WORKSPACE_GRANTS
        or access_ready_then.get("probe_receipt_binding") != {"$ref": "#/$defs/file_binding"}
        or dry_run_rule.get("if") != {
            "properties": {"run_kind": {"const": "DRY_RUN"}},
            "required": ["run_kind"],
        }
        or set(dry_run_then) != {
            "status", "outcome", "granted_capabilities", "probe_receipt_binding",
        }
        or dry_run_then.get("status", {}).get("const") != "AUTONOMY_UNAVAILABLE_NO_ACCESS"
        or dry_run_then.get("outcome", {}).get("const") != "ACCESS_PLANNED_DRY_RUN"
        or dry_run_then.get("granted_capabilities", {}).get("maxItems") != 0
        or dry_run_then.get("probe_receipt_binding") != {"type": "null"}
        or granted_then != {
            "status": {"const": "ACCESS_READY"},
            "run_kind": {"const": "REAL"},
            "granted_capabilities": {"const": WORKSPACE_GRANTS},
            "probe_receipt_binding": {"$ref": "#/$defs/file_binding"},
        }
        or unavailable_real_then != {
            "outcome": {"enum": ["ACCESS_PARTIAL", "ACCESS_DENIED"]},
            "probe_receipt_binding": {"type": "null"},
        }
        or partial_then != {
            "status": {"const": "AUTONOMY_UNAVAILABLE_NO_ACCESS"},
            "run_kind": {"const": "REAL"},
            "granted_capabilities": {"minItems": 1, "maxItems": 3},
            "probe_receipt_binding": {"type": "null"},
        }
        or denied_then != {
            "status": {"const": "AUTONOMY_UNAVAILABLE_NO_ACCESS"},
            "run_kind": {"const": "REAL"},
            "granted_capabilities": {"maxItems": 0},
            "probe_receipt_binding": {"type": "null"},
        }
    ):
        errors.append("WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT")

    probe = schemas.get("workspace_access_probe_receipt.schema.json", {})
    probe_fields = probe.get("properties", {}) if isinstance(probe, dict) else {}
    read_proofs = probe_fields.get("read_proofs", {}) if isinstance(probe_fields, dict) else {}
    proof_binding = probe.get("$defs", {}).get("file_binding", {}) if isinstance(probe, dict) else {}
    proof_fields = proof_binding.get("properties", {}) if isinstance(proof_binding, dict) else {}
    expected_probe_fields = {
        "schema", "status", "receipt_id", "envelope_id", "activation_receipt_sha256",
        "task_id", "task_root", "project_root", "source_roots", "owned_lane_root",
        "session_pair_sha256", "capabilities", "probe_path", "probe_bytes", "probe_sha256",
        "create_once", "overwritten", "retained", "read_proofs", "record_digest",
    }
    if (
        probe.get("$id") != "urn:omni-builder:workspace-access-probe-receipt:1"
        or set(probe_fields) != expected_probe_fields
        or set(probe.get("required", [])) != expected_probe_fields
        or probe_fields.get("schema", {}).get("const") != "omni-workspace-access-probe-receipt-v1"
        or probe_fields.get("status", {}).get("const") != "CREATE_ONCE_PROBE_RETAINED"
        or probe_fields.get("capabilities", {}).get("const") != WORKSPACE_GRANTS
        or probe_fields.get("create_once", {}).get("const") is not True
        or probe_fields.get("overwritten", {}).get("const") is not False
        or probe_fields.get("retained", {}).get("const") is not True
        or read_proofs.get("type") != "array"
        or read_proofs.get("minItems") != 1
        or read_proofs.get("items") != {"$ref": "#/$defs/file_binding"}
        or proof_binding.get("type") != "object"
        or proof_binding.get("additionalProperties") is not False
        or set(proof_binding.get("required", [])) != {"path", "bytes", "sha256"}
        or set(proof_fields) != {"path", "bytes", "sha256"}
    ):
        errors.append("WORKSPACE_PROBE_SCHEMA_CONTRACT_DRIFT")


def _template_contract(root: Path, errors: list[str]) -> None:
    handoff = (root / "templates" / "handoff.md").read_text(encoding="utf-8").lower()
    invariants = (root / "templates" / "invarianti.md").read_text(encoding="utf-8").lower()
    phase = (root / "templates" / "contratto_fase.yaml").read_text(encoding="utf-8").lower()
    stele = (root / "templates" / "stele_zero.md").read_text(encoding="utf-8").lower()
    builder = (root / "templates" / "mandato_costruttore.md").read_text(encoding="utf-8").lower()
    verifier = (root / "templates" / "mandato_demolitore.md").read_text(encoding="utf-8").lower()
    phase_data = _load_yaml(root / "templates" / "contratto_fase.yaml", errors)
    if not isinstance(phase_data, dict):
        errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_INVALID:contratto_fase.yaml")
    else:
        scope_data = phase_data.get("template_scope", {})
        relay_data = phase_data.get("topology_selection_relay", {})
        mandates_data = phase_data.get("mandates", {})
        def unwrap_artifact(key: str) -> dict[str, Any]:
            wrapper = phase_data.get(key, {})
            if not isinstance(wrapper, dict) or set(wrapper) != {"binding", "artifact"}:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_WRAPPER_DRIFT:{key}")
                return {}
            binding = wrapper.get("binding", {})
            if (
                not isinstance(binding, dict)
                or set(binding) != {"path", "bytes", "sha256"}
                or not isinstance(binding.get("path"), str)
                or not binding.get("path")
                or not isinstance(binding.get("bytes"), int)
                or isinstance(binding.get("bytes"), bool)
                or binding.get("bytes", 0) < 1
                or not isinstance(binding.get("sha256"), str)
                or re.fullmatch(r"[A-F0-9]{64}", binding.get("sha256", "")) is None
            ):
                errors.append(f"GUIDED_INTAKE_TEMPLATE_BINDING_OBJECT_DRIFT:{key}")
            artifact = wrapper.get("artifact", {})
            return artifact if isinstance(artifact, dict) else {}

        access_data = unwrap_artifact("workspace_access_envelope")
        probe_data = unwrap_artifact("workspace_access_probe_receipt")
        program_data = unwrap_artifact("program")
        countersign_data = unwrap_artifact("program_countersign_receipt")
        baptism_decision_data = unwrap_artifact("program_baptism_decision")
        baptism_receipt_data = unwrap_artifact("program_baptism_receipt")
        mode_data = phase_data.get("mode_selection", {})
        level_data = phase_data.get("activation_level", {})
        portable_path_values = {
            "activation_receipt.path": phase_data.get("activation_receipt", {}).get("path"),
            "guided_intake_state.path": phase_data.get("guided_intake_state", {}).get("path"),
            "team_card.path": phase_data.get("team_card", {}).get("path"),
            "topology_selection_relay.payload_path": phase_data.get("topology_selection_relay", {}).get("payload_path"),
            "brains.builder": phase_data.get("brains", {}).get("builder"),
            "brains.verifier": phase_data.get("brains", {}).get("verifier"),
            "mandates.builder_path": phase_data.get("mandates", {}).get("builder_path"),
            "mandates.verifier_path": phase_data.get("mandates", {}).get("verifier_path"),
            "write_lanes.builder": phase_data.get("write_lanes", {}).get("builder"),
            "write_lanes.verifier": phase_data.get("write_lanes", {}).get("verifier"),
            "message_lane.relay_ledger_path": phase_data.get("message_lane", {}).get("relay_ledger_path"),
            "workspace_access_envelope.binding.path": phase_data.get("workspace_access_envelope", {}).get("binding", {}).get("path"),
            "workspace_access_envelope.artifact.task_root": access_data.get("task_root"),
            "workspace_access_envelope.artifact.project_root": access_data.get("project_root"),
            "workspace_access_envelope.artifact.owned_lane_root": access_data.get("owned_lane_root"),
            "workspace_access_envelope.artifact.probe_receipt_binding.path": access_data.get("probe_receipt_binding", {}).get("path"),
            "workspace_access_probe_receipt.binding.path": phase_data.get("workspace_access_probe_receipt", {}).get("binding", {}).get("path"),
            "workspace_access_probe_receipt.artifact.task_root": probe_data.get("task_root"),
            "workspace_access_probe_receipt.artifact.project_root": probe_data.get("project_root"),
            "workspace_access_probe_receipt.artifact.owned_lane_root": probe_data.get("owned_lane_root"),
            "workspace_access_probe_receipt.artifact.probe_path": probe_data.get("probe_path"),
            "program.binding.path": phase_data.get("program", {}).get("binding", {}).get("path"),
            "program_countersign_receipt.binding.path": phase_data.get("program_countersign_receipt", {}).get("binding", {}).get("path"),
            "program.artifact.knowledge_state_binding.path": program_data.get("knowledge_state_binding", {}).get("path"),
            "program.artifact.knowledge_fusion_countersign_binding.path": program_data.get("knowledge_fusion_countersign_binding", {}).get("path"),
            "program.artifact.canonical_knowledge_binding.path": program_data.get("canonical_knowledge_binding", {}).get("path"),
            "program.artifact.builder_plan_manifest_binding.path": program_data.get("builder_plan_manifest_binding", {}).get("path"),
            "program.artifact.verifier_plan_manifest_binding.path": program_data.get("verifier_plan_manifest_binding", {}).get("path"),
            "program.artifact.fusion_decision_register_binding.path": program_data.get("fusion_decision_register_binding", {}).get("path"),
            "program.artifact.fused_plan_draft_binding.path": program_data.get("fused_plan_draft_binding", {}).get("path"),
            "program_countersign_receipt.artifact.program_binding.path": countersign_data.get("program_binding", {}).get("path"),
            "program_countersign_receipt.artifact.knowledge_state_binding.path": countersign_data.get("knowledge_state_binding", {}).get("path"),
            "program_countersign_receipt.artifact.knowledge_fusion_countersign_binding.path": countersign_data.get("knowledge_fusion_countersign_binding", {}).get("path"),
            "program_countersign_receipt.artifact.verifier_report_binding.path": countersign_data.get("verifier_report_binding", {}).get("path"),
            "program_baptism_decision.binding.path": phase_data.get("program_baptism_decision", {}).get("binding", {}).get("path"),
            "program_baptism_decision.artifact.program_binding.path": baptism_decision_data.get("program_binding", {}).get("path"),
            "program_baptism_decision.artifact.program_countersign_binding.path": baptism_decision_data.get("program_countersign_binding", {}).get("path"),
            "program_baptism_receipt.binding.path": phase_data.get("program_baptism_receipt", {}).get("binding", {}).get("path"),
            "program_baptism_receipt.artifact.program_binding.path": baptism_receipt_data.get("program_binding", {}).get("path"),
            "program_baptism_receipt.artifact.program_countersign_binding.path": baptism_receipt_data.get("program_countersign_binding", {}).get("path"),
            "program_baptism_receipt.artifact.pm_decision_binding.path": baptism_receipt_data.get("pm_decision_binding", {}).get("path"),
        }
        for index, value in enumerate(access_data.get("source_roots", [])):
            portable_path_values[f"workspace_access_envelope.artifact.source_roots.{index}"] = value
        for index, value in enumerate(probe_data.get("source_roots", [])):
            portable_path_values[f"workspace_access_probe_receipt.artifact.source_roots.{index}"] = value
        for index, proof in enumerate(probe_data.get("read_proofs", [])):
            if isinstance(proof, dict):
                portable_path_values[f"workspace_access_probe_receipt.artifact.read_proofs.{index}.path"] = proof.get("path")
        for index, item in enumerate(program_data.get("work_items", [])):
            if isinstance(item, dict):
                portable_path_values[f"program.artifact.work_items.{index}.persistent_artifact.path"] = item.get("persistent_artifact", {}).get("path")
        for index, item in enumerate(countersign_data.get("evidence_bindings", [])):
            if isinstance(item, dict):
                portable_path_values[f"program_countersign_receipt.artifact.evidence_bindings.{index}.path"] = item.get("path")
        for label, value in portable_path_values.items():
            if not isinstance(value, str) or not value.startswith("C:/OMNI/") or "\\" in value or value.endswith((".", " ")):
                errors.append(f"GUIDED_INTAKE_TEMPLATE_ABSOLUTE_PATH_PLACEHOLDER_DRIFT:{label}")
        if (
            not isinstance(scope_data, dict)
            or scope_data != {
                "applicability": "OMNI_FULL_ONLY",
                "activation_level": "OMNI_FULL",
                "module_instantiation_allowed": False,
                "forbidden_activation_levels": ["OMNI_AWARE", "OMNI_MODULE"],
                "full_only_sections": ["Q0", "GUIDED_INTAKE", "FUSED_PROGRAM", "MODE_SELECTION"],
            }
        ):
            errors.append("GUIDED_INTAKE_TEMPLATE_FULL_ONLY_SCOPE_DRIFT:contratto_fase.yaml")
        if not isinstance(relay_data, dict) or not {"payload_path", "payload_bytes", "payload_sha256"}.issubset(relay_data):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_RELAY_BINDING_DRIFT")
        if not isinstance(mandates_data, dict) or not {
            "builder_path", "builder_bytes", "builder_sha256",
            "verifier_path", "verifier_bytes", "verifier_sha256",
        }.issubset(mandates_data):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_MANDATE_BINDING_DRIFT")
        if (
            not isinstance(level_data, dict)
            or not {
                "knowledge_available", "skill_invoked", "requested_effects", "effect_authorized",
                "level", "modules_used", "authority_grants", "artifact_grants", "effect_grants",
                "non_grants", "access_envelope_id", "next_gate", "invariant",
            }.issubset(level_data)
            or level_data.get("level") != "OMNI_FULL"
            or level_data.get("knowledge_available") is not True
            or level_data.get("skill_invoked") is not True
            or not isinstance(level_data.get("requested_effects"), list)
            or level_data.get("effect_authorized") is not False
            or level_data.get("modules_used") != []
            or level_data.get("authority_grants") != FULL_ACTIVATION_AUTHORITY_GRANTS
            or level_data.get("artifact_grants") != []
            or level_data.get("effect_grants") != []
            or level_data.get("non_grants") != FULL_ACTIVATION_NON_GRANTS
            or level_data.get("invariant") != "KNOWLEDGE_AVAILABLE != SKILL_INVOKED != EFFECT_AUTHORIZED"
        ):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_ACTIVATION_LEVEL_DRIFT")
        if (
            not isinstance(access_data, dict)
            or access_data.get("schema") != "omni-workspace-access-envelope-v1"
            or access_data.get("status") != "ACCESS_READY"
            or access_data.get("outcome") != "ACCESS_GRANTED_NON_DESTRUCTIVE"
            or access_data.get("requested_capabilities") != WORKSPACE_GRANTS
            or access_data.get("granted_capabilities") != WORKSPACE_GRANTS
            or access_data.get("non_grants") != WORKSPACE_NON_GRANTS
            or access_data.get("separate_authorizations_required") != WORKSPACE_SEPARATE_AUTHORIZATIONS
            or access_data.get("run_kind") != "REAL"
            or not {"record_digest", "envelope_id", "activation_receipt_sha256", "task_id", "task_root", "project_root", "source_roots", "owned_lane_root", "session_pair_sha256", "excluded_paths"}.issubset(access_data)
            or not isinstance(access_data.get("probe_receipt_binding"), dict)
            or not {"path", "bytes", "sha256"}.issubset(access_data.get("probe_receipt_binding", {}))
            or not isinstance(probe_data, dict)
            or probe_data.get("schema") != "omni-workspace-access-probe-receipt-v1"
            or probe_data.get("status") != "CREATE_ONCE_PROBE_RETAINED"
            or probe_data.get("capabilities") != WORKSPACE_GRANTS
            or probe_data.get("create_once") is not True
            or probe_data.get("overwritten") is not False
            or probe_data.get("retained") is not True
            or not {"record_digest", "receipt_id", "envelope_id", "activation_receipt_sha256", "task_id", "task_root", "project_root", "source_roots", "owned_lane_root", "session_pair_sha256", "probe_path", "probe_bytes", "probe_sha256"}.issubset(probe_data)
            or not isinstance(probe_data.get("read_proofs"), list)
            or not probe_data.get("read_proofs")
            or any(not isinstance(item, dict) or not {"path", "bytes", "sha256"}.issubset(item) for item in probe_data.get("read_proofs", []))
        ):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_WORKSPACE_ACCESS_DRIFT")
        if (
            not isinstance(program_data, dict)
            or program_data.get("schema") != "omni-fused-program-v2"
            or program_data.get("kind") != "PROGRAM_FUSION_CANDIDATE"
            or program_data.get("status") != "PROGRAM_FUSION_FROZEN"
            or not {
                "program_id", "task_id", "knowledge_pipeline_id", "record_digest",
                "knowledge_state_binding", "knowledge_fusion_countersign_binding",
                "canonical_knowledge_binding", "session_pair_sha256",
                "author_role", "author_session_id", "topology", "profile", "run_kind",
                "fused_from_lanes", "builder_plan_manifest_binding",
                "verifier_plan_manifest_binding", "fusion_decision_register_binding",
                "fused_plan_draft_binding", "work_items", "preserved_alternative_ids",
                "preserved_dissent_ids", "created_at",
            }.issubset(program_data)
        ):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_PROGRAM_DRIFT")
        if (
            not isinstance(countersign_data, dict)
            or countersign_data.get("schema") != "omni-program-countersign-receipt-v2"
            or countersign_data.get("status") != "PROGRAM_COUNTERSIGN_ACCEPTED"
            or countersign_data.get("decision") != "ACCEPTED"
            or not {
                "receipt_id", "program_id", "task_id", "knowledge_pipeline_id",
                "program_binding", "record_digest", "program_record_digest",
                "knowledge_state_binding", "knowledge_fusion_countersign_binding",
                "session_pair_sha256", "program_author_session_id", "signer_role",
                "signer_session_id", "verifier_report_binding", "reproduction",
                "finding_codes", "evidence_bindings", "created_at",
            }.issubset(countersign_data)
        ):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_COUNTERSIGN_DRIFT")
        if (
            not isinstance(baptism_decision_data, dict)
            or baptism_decision_data.get("schema") != "omni-program-baptism-decision-v1"
            or baptism_decision_data.get("status") != "PROGRAM_BAPTISM_AUTHORIZED"
            or baptism_decision_data.get("decision") != "ACCEPTED"
            or not {
                "program_id", "task_id", "knowledge_pipeline_id", "session_pair_sha256",
                "program_binding", "program_record_digest", "program_countersign_binding",
                "program_countersign_record_digest", "sovereign_id", "created_at", "record_digest",
            }.issubset(baptism_decision_data)
            or not isinstance(baptism_receipt_data, dict)
            or baptism_receipt_data.get("schema") != "omni-program-baptism-receipt-v1"
            or baptism_receipt_data.get("status") != "PROGRAM_BAPTIZED"
            or baptism_receipt_data.get("decision") != "ACCEPTED"
            or not {
                "program_id", "task_id", "knowledge_pipeline_id", "session_pair_sha256",
                "program_binding", "program_record_digest", "program_countersign_binding",
                "program_countersign_record_digest", "pm_decision_binding", "sovereign_id",
                "created_at", "record_digest",
            }.issubset(baptism_receipt_data)
        ):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_PROGRAM_BAPTISM_DRIFT")
        artifact_schemas = {
            "workspace_access_envelope": "workspace_access_envelope.schema.json",
            "workspace_access_probe_receipt": "workspace_access_probe_receipt.schema.json",
            "program": "fused_program.schema.json",
            "program_countersign_receipt": "program_countersign_receipt.schema.json",
            "program_baptism_decision": "program_baptism_decision.schema.json",
            "program_baptism_receipt": "program_baptism_receipt.schema.json",
        }
        artifact_objects = {
            "workspace_access_envelope": access_data,
            "workspace_access_probe_receipt": probe_data,
            "program": program_data,
            "program_countersign_receipt": countersign_data,
            "program_baptism_decision": baptism_decision_data,
            "program_baptism_receipt": baptism_receipt_data,
        }
        if jsonschema is None:
            errors.append("JSONSCHEMA_RUNTIME_UNAVAILABLE:contratto_fase.yaml")
        else:
            for key, filename in artifact_schemas.items():
                try:
                    standalone_schema = json.loads(
                        (root / "schemas" / filename).read_text(encoding="utf-8")
                    )
                    standalone_errors = sorted(
                        jsonschema.Draft202012Validator(standalone_schema).iter_errors(
                            artifact_objects[key]
                        ),
                        key=lambda error: tuple(str(part) for part in error.absolute_path),
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as error:
                    errors.append(
                        f"GUIDED_INTAKE_TEMPLATE_STANDALONE_SCHEMA_INVALID:{key}:{type(error).__name__}"
                    )
                    continue
                for error in standalone_errors:
                    location = ".".join(str(part) for part in error.absolute_path) or "$"
                    errors.append(
                        f"GUIDED_INTAKE_TEMPLATE_STANDALONE_SCHEMA_REJECTED:{key}:{location}:{error.validator}"
                    )
        if (
            not isinstance(mode_data, dict)
            or not {
                "intake_record_digest", "program_record_digest",
                "program_countersign_receipt_sha256", "program_countersign_record_digest",
                "program_baptism_receipt_sha256", "program_baptism_record_digest",
                "workspace_access_record_digest", "session_pair_sha256",
            }.issubset(mode_data)
        ):
            errors.append("GUIDED_INTAKE_TEMPLATE_STRUCTURED_MODE_BINDING_DRIFT")
    for marker in ("host runtime version tuple", "surface id:", "model:", "effort ui label:", "effort runtime key:", "effort mapping evidence:", "host-context sentinel:"):
        if marker not in handoff:
            errors.append(f"HANDOFF_PROFILE_FIELD_MISSING:{marker}")
    for marker in ("host version", "surface id", "exactly one script supervisor", "alternate state directories"):
        if marker not in invariants:
            errors.append(f"INVARIANT_MISSING:{marker}")
    guided_markers = (
        "activation receipt", "guided-intake state", "team_card", "session pair", "builder brain",
        "verifier brain", "write lane", "pm_relay", "question_id", "four-readback",
        "open critical question", "program", "mode",
    )
    for relative, text in (
        ("handoff.md", handoff),
        ("stele_zero.md", stele),
        ("mandato_costruttore.md", builder),
        ("mandato_demolitore.md", verifier),
    ):
        for marker in guided_markers:
            if relative.startswith("mandato_") and marker in {"activation receipt", "guided-intake state", "session pair"}:
                continue
            if marker not in text:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:{relative}:{marker}")
    for marker in (
        "activation_receipt:", "guided_intake_state:", "team_card:", "session_pair:",
        "brains:", "write_lanes:", "message_lane:", "four_readback:",
        "open_critical_question_ids:", "program:", "program_countersign_receipt:",
        "program_baptism_decision:", "program_baptism_receipt:", "mode_selection:",
    ):
        if marker not in phase:
            errors.append(f"GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:contratto_fase.yaml:{marker}")
    for relative, text in (("stele_zero.md", stele), ("handoff.md", handoff)):
        for marker in (
            "fused program schema", "program_fusion_frozen", "program countersign", "program_baptized",
            "workspace_access_envelope", "omni-workspace-access-probe-receipt-v1",
            "knowledge_available != skill_invoked != effect_authorized", "knowledge_available",
            "skill_invoked", "requested_effects", "effect_authorized",
        ):
            if marker not in text:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:{relative}:{marker}")
    trace_sequences = {
        "stele_zero.md": (
            "`knowledge_available` / `skill_invoked` / activation level",
            "`requested_effects` / `effect_authorized` / effect grants",
        ),
        "handoff.md": (
            "`knowledge_available` / `skill_invoked` / activation level",
            "`requested_effects` / `effect_authorized` / effect grants",
        ),
    }
    for relative, sequences in trace_sequences.items():
        text = {"stele_zero.md": stele, "handoff.md": handoff}[relative]
        for sequence in sequences:
            if sequence not in text:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_TRACE_FIELD_MISSING:{relative}:{sequence}")
    for relative, text in (("mandato_costruttore.md", builder), ("mandato_demolitore.md", verifier)):
        for marker in (
            "omni-fused-program-v2", "program_fusion_frozen",
            "omni-program-countersign-receipt-v2", "program_countersign_accepted",
            "omni-program-baptism-receipt-v1", "program_baptized",
            "workspace_access_envelope", "access_ready", "source_refs",
        ):
            if marker not in text:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:{relative}:{marker}")
    for relative, text in (
        ("handoff.md", handoff), ("stele_zero.md", stele),
        ("mandato_costruttore.md", builder), ("mandato_demolitore.md", verifier),
    ):
        for marker in (
            "canonical_absolute_path_required", "reject_cwd_relative", "reject_drive_relative",
            "reject_ntfs_ads", "reject_device_alias", "nul_family_not_module_surface",
        ):
            if marker not in text:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_CANONICAL_PATH_MISSING:{relative}:{marker}")
    for relative, text in (("handoff.md", handoff), ("stele_zero.md", stele)):
        for marker in (
            "omni_full only", "applicability=omni_full_only", "activation_level=omni_full",
            "module_instantiation_forbidden", "contains q0, guided intake, fused program, and mode fields",
            "must never instantiate for `omni_aware` or `omni_module`",
        ):
            if marker not in text:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_FULL_ONLY_MARKER_MISSING:{relative}:{marker}")
    binding_markers = {
        "contratto_fase.yaml": (
            "decision: activation_allowed", "activation_path:", "task_scope: current_task_only",
            "non_grants: [partner_selection, web_access, download, project_write, execution, autonomy]",
            "record_digest:", "status: intake_ready", "topology_selection_relay:",
            "pm_authorization: accepted", "builder_bytes:", "builder_sha256:",
            "verifier_bytes:", "verifier_sha256:", "relay_ledger_path:",
            "relay_ledger_bytes:", "relay_ledger_sha256:", "intake_state_sha256:",
            "intake_record_digest:", "program_sha256:", "payload_path:", "payload_bytes:",
            "workspace_access_envelope:", "program_fusion_frozen",
            "program_countersign_receipt:", "program_countersign_accepted",
            "program_baptism_decision:", "program_baptism_receipt:", "program_baptized",
        ),
        "handoff.md": (
            "activation receipt path / bytes / sha-256 / `activation_allowed` decision",
            "activation path / `current_task_only` / run kind / effect policy",
            "activation level `omni_full`",
            "guided-intake state path / bytes / sha-256 / record digest / `intake_ready`",
            "pm topology-selection `relay-nnn` / payload path / bytes / sha-256 / authorization",
            "builder mandate path / bytes / sha-256", "verifier mandate path / bytes / sha-256",
            "relay ledger path / bytes / sha-256", "workspace_access_envelope",
            "independent program countersign receipt",
        ),
        "mandato_costruttore.md": (
            "reread and byte-bind", "pm topology-selection relay payload path + bytes + sha-256",
            "both physical mandate paths + bytes + sha-256", "relay-ledger digest",
            "separate `omni-program-countersign-receipt-v2`",
            "open the program, countersign, baptism decision, and baptism receipt at their exact paths",
            "reproduce bytes, sha-256, and record digests",
        ),
        "mandato_demolitore.md": (
            "reread and byte-bind", "pm topology-selection relay payload path + bytes + sha-256",
            "both physical mandate paths + bytes + sha-256", "relay-ledger digest",
            "separate `omni-program-countersign-receipt-v2`",
            "open the program, countersign, baptism decision, and baptism receipt at their exact paths",
            "reproduce bytes, sha-256, and record digests",
        ),
        "stele_zero.md": (
            "activation receipt path / bytes / sha-256 / `activation_allowed` decision",
            "guided-intake state path / bytes / sha-256 / record digest / `intake_ready`",
            "pm topology-selection relay / payload path / bytes / sha-256 / authorization",
            "builder mandate / verifier mandate paths, bytes, and sha-256",
            "relay ledger path / bytes / sha-256", "workspace_access_envelope",
            "independent countersign receipt",
        ),
    }
    template_texts = {
        "contratto_fase.yaml": phase,
        "handoff.md": handoff,
        "mandato_costruttore.md": builder,
        "mandato_demolitore.md": verifier,
        "stele_zero.md": stele,
    }
    for relative, markers in binding_markers.items():
        for marker in markers:
            if marker not in template_texts[relative]:
                errors.append(f"GUIDED_INTAKE_TEMPLATE_BINDING_MISSING:{relative}:{marker}")
    stele_program = stele.find("fused program schema")
    stele_mode = stele.find("mode, autonomy, and risk")
    if stele_program >= 0 and stele_mode >= 0 and stele_program > stele_mode:
        errors.append("GUIDED_INTAKE_MODE_BEFORE_PROGRAM:stele_zero.md")
    phase_program = phase.find("program:")
    phase_mode = phase.find("mode_selection:")
    if phase_program >= 0 and phase_mode >= 0 and phase_program > phase_mode:
        errors.append("GUIDED_INTAKE_MODE_BEFORE_PROGRAM:contratto_fase.yaml")


def _adapter_contract(root: Path, errors: list[str], hosts: list[str] | None = None) -> None:
    schema_path = root / "schemas" / "host_adapter.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"HOST_ADAPTER_SCHEMA_INVALID:{type(error).__name__}:{error}")
        return
    required = {"schema", "host", "host_version", "surface_id", "accessed", "official_sources", "capability_layers", "profile", "rotation", "notes"}
    if schema.get("$id") != "urn:omni-builder:host-adapter:1" or schema.get("additionalProperties") is not False or set(schema.get("required", [])) != required:
        errors.append("HOST_ADAPTER_SCHEMA_DRIFT")
    properties = schema.get("properties", {})
    layers_contract = properties.get("capability_layers", {}) if isinstance(properties, dict) else {}
    layer_properties = layers_contract.get("properties", {}) if isinstance(layers_contract, dict) else {}
    if (
        layers_contract.get("type") != "object"
        or layers_contract.get("additionalProperties") is not False
        or set(layers_contract.get("required", [])) != set(CAPABILITY_LAYERS)
        or set(layer_properties) != set(CAPABILITY_LAYERS)
        or any(layer_properties.get(name) != {"$ref": "#/$defs/layer"} for name in CAPABILITY_LAYERS)
    ):
        errors.append("HOST_ADAPTER_SCHEMA_CAPABILITY_LAYERS_DRIFT")
    layer = schema.get("$defs", {}).get("layer")
    layer_fields = layer.get("properties", {}) if isinstance(layer, dict) else {}
    if (
        not isinstance(layer, dict)
        or layer.get("type") != "object"
        or layer.get("additionalProperties") is not False
        or set(layer.get("required", [])) != set(EVIDENCE_CLASSES)
        or set(layer_fields) != set(EVIDENCE_CLASSES)
        or any(layer_fields.get(name) != {"type": "array", "items": {"type": "string"}, "uniqueItems": True} for name in EVIDENCE_CLASSES)
    ):
        errors.append("HOST_ADAPTER_SCHEMA_LAYER_DRIFT")
    rotation_contract = properties.get("rotation", {}) if isinstance(properties, dict) else {}
    rotation_properties = rotation_contract.get("properties", {}) if isinstance(rotation_contract, dict) else {}
    if (
        rotation_contract.get("type") != "object"
        or rotation_contract.get("additionalProperties") is not False
        or set(rotation_contract.get("required", [])) != {"carrier", "self_spawn", "state_chain"}
        or rotation_properties.get("state_chain", {}).get("const") != ROTATION_ORDER[:-1]
    ):
        errors.append("HOST_ADAPTER_SCHEMA_ROTATION_DRIFT")
    if jsonschema is None:
        errors.append("JSONSCHEMA_RUNTIME_UNAVAILABLE:host_adapter")
        adapter_validator = None
    else:
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
            adapter_validator = jsonschema.Draft202012Validator(schema)
        except jsonschema.exceptions.SchemaError as error:
            errors.append(f"HOST_ADAPTER_SCHEMA_INVALID:{error.message}")
            adapter_validator = None
    for host in (ADAPTERS if hosts is None else hosts):
        data = _load_yaml(root / "adapters" / host / "adapter.yaml", errors)
        if not isinstance(data, dict):
            errors.append(f"HOST_ADAPTER_NOT_OBJECT:{host}")
            continue
        if adapter_validator is not None:
            schema_instance = dict(data)
            accessed = schema_instance.get("accessed")
            if hasattr(accessed, "isoformat"):
                schema_instance["accessed"] = accessed.isoformat()
            for failure in sorted(adapter_validator.iter_errors(schema_instance), key=lambda item: list(item.absolute_path)):
                location = "/".join(str(part) for part in failure.absolute_path) or "$"
                errors.append(f"HOST_ADAPTER_SCHEMA_REJECTED:{host}:{location}:{failure.message}")
        if set(data) != required or data.get("schema") != "omni-host-adapter-v1":
            errors.append(f"HOST_ADAPTER_ENVELOPE_INVALID:{host}")
        if not all(isinstance(data.get(key), str) and data.get(key) for key in ("host", "host_version", "surface_id")):
            errors.append(f"HOST_ADAPTER_IDENTITY_INVALID:{host}")
        layers = data.get("capability_layers")
        if not isinstance(layers, dict) or set(layers) != set(CAPABILITY_LAYERS):
            errors.append(f"HOST_ADAPTER_LAYERS_INVALID:{host}")
            continue
        for layer_name, layer in layers.items():
            if not isinstance(layer, dict) or set(layer) != set(EVIDENCE_CLASSES):
                errors.append(f"HOST_ADAPTER_CLASSIFICATION_INVALID:{host}:{layer_name}")
                continue
            for field, values in layer.items():
                if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or len(values) != len(set(values)):
                    errors.append(f"HOST_ADAPTER_EVIDENCE_INVALID:{host}:{layer_name}:{field}")
        fields = data.get("profile", {}).get("fields", []) if isinstance(data.get("profile"), dict) else []
        if not {"surface_id", "agentic_sentinel", "script_sentinel", "context_sentinel"}.issubset(set(fields)):
            errors.append(f"HOST_ADAPTER_PROFILE_INCOMPLETE:{host}")
        rotation = data.get("rotation", {})
        allowed_rotation = {"carrier", "self_spawn", "state_chain", "opaque_prompt_mode", "emergency_use", "peer_assistance_allowed"}
        if not isinstance(rotation, dict) or not {"carrier", "self_spawn", "state_chain"}.issubset(rotation) or not set(rotation).issubset(allowed_rotation):
            errors.append(f"HOST_ADAPTER_ROTATION_SHAPE_INVALID:{host}")
            continue
        if rotation.get("self_spawn") not in {False, "forbidden"}:
            errors.append(f"HOST_ADAPTER_SELF_SPAWN_INVALID:{host}")
        if rotation.get("state_chain") != ROTATION_ORDER[:-1]:
            errors.append(f"HOST_ADAPTER_STATE_MACHINE_DRIFT:{host}")
        notes = data.get("notes")
        note_text = " ".join(notes).lower() if isinstance(notes, list) and all(isinstance(note, str) for note in notes) else ""
        for marker in SAFETY_NOTE_MARKERS[host]:
            if marker not in note_text:
                errors.append(f"HOST_ADAPTER_SAFETY_NOTE_MISSING:{host}:{marker}")

    generation = _load_yaml(root / "adapters" / "host_generation.yaml", errors)
    required_profile = set(generation.get("required_profile_fields", [])) if isinstance(generation, dict) else set()
    if not {"surface_id", "context_sentinel", "model", "reasoning_effort"}.issubset(required_profile):
        errors.append("HOST_GENERATION_PROFILE_INCOMPLETE")
    if not isinstance(generation, dict) or generation.get("rotation_state_chain") != ROTATION_ORDER[:-1]:
        errors.append("HOST_GENERATION_STATE_MACHINE_DRIFT")


def _walk_schema_nodes(value: Any):
    """Yield every mapping in a JSON Schema without trusting its layout."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_schema_nodes(child)


def _r3_contract(root: Path, text_by_path: dict[str, str], errors: list[str]) -> None:
    """Pin the bounded R3 module and per-writer relay doctrine without tests."""

    def at(value: Any, *parts: str | int) -> Any:
        current = value
        for part in parts:
            if isinstance(part, int):
                if not isinstance(current, list) or part >= len(current):
                    return None
                current = current[part]
            else:
                if not isinstance(current, dict):
                    return None
                current = current.get(part)
        return current

    def exact_strings(value: Any, expected: set[str]) -> bool:
        return (
            isinstance(value, list)
            and len(value) == len(expected)
            and all(isinstance(item, str) for item in value)
            and set(value) == expected
        )

    json_paths = (
        "modules/KNOWLEDGE_RESEARCH_DOSSIER/module.json",
        "modules/KNOWLEDGE_RESEARCH_DOSSIER/authority.schema.json",
        "modules/KNOWLEDGE_RESEARCH_DOSSIER/records.schema.json",
        "schemas/relay_ledger_entry.schema.json",
    )
    loaded: dict[str, dict[str, Any]] = {}
    for relative in json_paths:
        try:
            value = json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors.append(f"R3_JSON_UNREADABLE:{relative}:{type(error).__name__}")
            continue
        if not isinstance(value, dict):
            errors.append(f"R3_JSON_NOT_OBJECT:{relative}")
            continue
        loaded[relative] = value

    for relative in json_paths[1:]:
        schema = loaded.get(relative)
        if schema is None:
            continue
        if jsonschema is None:
            errors.append(f"JSONSCHEMA_RUNTIME_UNAVAILABLE:{relative}")
            continue
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as error:
            errors.append(f"R3_SCHEMA_INVALID:{relative}:{error.message}")

    manifest = loaded.get(json_paths[0], {})
    authority = loaded.get(json_paths[1], {})
    records = loaded.get(json_paths[2], {})
    ledger = loaded.get(json_paths[3], {})
    module_doc = re.sub(
        r"\s+", " ",
        text_by_path.get("modules/KNOWLEDGE_RESEARCH_DOSSIER/MODULE.md", "").lower(),
    )
    module_runtime = text_by_path.get("modules/KNOWLEDGE_RESEARCH_DOSSIER/run.py", "")
    guard_runtime = text_by_path.get("scripts/sentry/mode_a_guard.py", "")
    module_tests = text_by_path.get(
        "tests/test_knowledge_research_dossier_module.py", ""
    )

    if (
        manifest.get("schema") != "omni-module-manifest-v1"
        or manifest.get("module_id") != "KNOWLEDGE_RESEARCH_DOSSIER"
        or manifest.get("activation_level") != "OMNI_MODULE"
        or manifest.get("entrypoint") != "run.py"
        or authority.get("$id")
        != "urn:omni-builder:module:knowledge-research-dossier:authority:1"
        or at(authority, "properties", "module_id", "const")
        != "KNOWLEDGE_RESEARCH_DOSSIER"
        or records.get("$id")
        != "urn:omni-builder:module:knowledge-research-dossier:records:1"
        or at(records, "$defs", "record_base", "properties", "module_id", "const")
        != "KNOWLEDGE_RESEARCH_DOSSIER"
        or 'MODULE_ID = "KNOWLEDGE_RESEARCH_DOSSIER"' not in module_runtime
    ):
        errors.append("R3_MODULE_IDENTITY_DRIFT")

    outcome = at(records, "$defs", "outcome", "allOf", 1)
    if (
        manifest.get("terminal")
        != {"status": "KNOWLEDGE_RESEARCH_DOSSIER_READY", "next_gate": "STOP"}
        or not exact_strings(
            at(outcome, "required"),
            {
                "material_study_binding", "light_map_binding",
                "deep_research_receipt_binding", "source_manifest_binding",
                "dossier_binding", "download_outcome", "next_gate",
            },
        )
        or at(outcome, "properties", "status", "const")
        != "KNOWLEDGE_RESEARCH_DOSSIER_READY"
        or at(outcome, "properties", "next_gate", "const") != "STOP"
        or "knowledge_research_dossier_ready" not in module_doc
        or "next_gate: stop" not in module_doc
        or not all(
            marker in module_runtime
            for marker in (
                '"status": "BLOCKED"', '"reason_code": reason_code',
                '"next_gate": "STOP"', "return 2",
            )
        )
    ):
        errors.append("R3_MODULE_TYPED_STOP_DRIFT")

    actions = {
        "READ_NAMED_SOURCES", "CREATE_FILES", "NETWORK_RESEARCH", "DOWNLOAD",
    }
    effect_fields = {
        "named_sources", "output_root", "output_paths", "allowed_schemes",
        "query_limit", "source_limit", "capture_policy", "allowed_locators",
        "quarantine_root", "handling_policy",
    }
    branch_required = {
        "READ_NAMED_SOURCES": {"named_sources"},
        "CREATE_FILES": {"output_root", "output_paths"},
        "NETWORK_RESEARCH": {
            "allowed_schemes", "query_limit", "source_limit", "capture_policy",
        },
        "DOWNLOAD": {"allowed_locators", "quarantine_root", "handling_policy"},
    }
    branches: dict[str, Any] = {}
    all_of = authority.get("allOf")
    for branch in all_of if isinstance(all_of, list) else []:
        action = at(branch, "if", "properties", "action", "const")
        if isinstance(action, str):
            branches[action] = branch
    branches_exact = set(branches) == actions
    for action, required_fields in branch_required.items():
        branch = branches.get(action)
        then_properties = at(branch, "then", "properties")
        forbidden_fields = effect_fields - required_fields
        if (
            not exact_strings(at(branch, "then", "required"), required_fields)
            or not isinstance(then_properties, dict)
            or set(then_properties) != forbidden_fields
            or any(value is not False for value in then_properties.values())
        ):
            branches_exact = False
    authorities = manifest.get("authorities")
    network_policy = manifest.get("network_policy")
    if (
        not isinstance(authorities, dict)
        or authorities.get("activation_grants_effects") is not False
        or authorities.get("separate_records") is not True
        or not exact_strings(authorities.get("required"), actions - {"DOWNLOAD"})
        or not exact_strings(authorities.get("optional"), {"DOWNLOAD"})
        or authority.get("type") != "object"
        or authority.get("additionalProperties") is not False
        or not exact_strings(at(authority, "properties", "action", "enum"), actions)
        or at(authority, "properties", "one_shot", "const") is not True
        or not branches_exact
        or not isinstance(network_policy, dict)
        or network_policy.get("runtime_opens_network") is not False
        or network_policy.get("host_tool_required") is not True
        or network_policy.get("default_capture_policy") != "CAPTURE_MD_ONLY"
        or network_policy.get("download_fallback")
        != "DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY"
        or network_policy.get("download_handling") != "QUARANTINE_HASH_NEVER_EXECUTE"
        or not all(
            marker in module_doc
            for marker in (
                "activation grants no effects.",
                "an authority record has exactly one action.",
                "network authority never implies download authority.",
            )
        )
    ):
        errors.append("R3_MODULE_EFFECT_SEPARATION_DRIFT")

    forbidden_scope = {
        "ordinary_request_autorun": False,
        "opens_intake": False,
        "opens_project_state": False,
        "opens_multi_agent_topology": False,
        "selects_execution_mode": False,
        "continues_after_terminal_outcome": False,
    }
    if (
        manifest.get("scope") != forbidden_scope
        or not all(
            marker in module_doc
            for marker in (
                "the module is not an intake path.",
                "it does not create q0, a project well, a team card, lanes, a fused program, an omni mode, sentinels, or autonomy.",
                "it does not convert an ordinary request into a module request.",
            )
        )
        or re.search(
            r"(?m)^\s*(?:import|from)\s+(?:socket|requests|httpx|http\.client|aiohttp)\b",
            module_runtime,
        )
    ):
        errors.append("R3_MODULE_FORBIDDEN_SURFACE_DRIFT")

    if not all(
        marker in guard_runtime
        for marker in (
            "def _read_module_manifest(",
            'manifest_path = module_dir / "module.json"',
            'manifest = strict_json(payload.decode("utf-8"))',
            'module_id = manifest.get("module_id")',
            "if module_id.casefold() != module_dir.name.casefold():",
            'raise ValueError("MODULE_MANIFEST_ID_DRIFT")',
            'raise ValueError("MODULE_MANIFEST_DRIFT")',
            'raise ValueError("MODULE_MANIFEST_ENTRYPOINT_INVALID")',
            "module_id = _read_module_manifest(module_dir)",
            "result.append(module_id)",
        )
    ):
        errors.append("R3_1_GUARD_MODULE_BINDING_DRIFT")

    if not all(
        marker in module_tests
        for marker in (
            "def test_real_guard_receipt_drives_real_module_entrypoint",
            'self.assertEqual(receipt["modules_used"], [MOD.MODULE_ID])',
            "activation_path.write_text(guard.stdout",
            'str(MODULE_DIR / "run.py")',
            'self.assertEqual(outcome["module_id"], MOD.MODULE_ID)',
            "def test_guard_blocks_unknown_invalid_and_identity_drifted_modules",
            "MODULE_MANIFEST_INVALID",
            "MODULE_MANIFEST_ID_DRIFT",
        )
    ):
        errors.append("R3_1_GUARD_MODULE_E2E_COVERAGE_DRIFT")

    ledger_fields = {
        "schema", "run_id", "stream_id", "volume_id", "volume_no", "stream_seq",
        "event_id", "writer_id", "writer_instance_id", "lease_id", "fence",
        "topology", "hat", "independent_verifier", "created_at", "kind", "title",
        "body", "body_bytes", "canonicalization_version", "observed_heads",
        "supersedes", "request_hash", "prev_entry_hash",
        "prev_volume_seal_hash", "integrity_scope", "entry_hash",
    }
    ledger_properties = ledger.get("properties")
    if (
        ledger.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        or ledger.get("$id") != "urn:omni-builder:relay-ledger-entry:1"
        or ledger.get("type") != "object"
        or ledger.get("additionalProperties") is not False
        or not exact_strings(ledger.get("required"), ledger_fields)
        or not isinstance(ledger_properties, dict)
        or set(ledger_properties) != ledger_fields
        or at(ledger, "properties", "schema", "const")
        != "omni-relay-ledger-entry-v1"
        or at(ledger, "properties", "stream_seq") != {"type": "integer", "minimum": 1}
        or at(ledger, "properties", "fence") != {"type": "integer", "minimum": 1}
        or at(ledger, "properties", "topology", "enum") != ["TEAM", "SOLO_HATS"]
        or at(ledger, "properties", "independent_verifier") != {"type": "boolean"}
        or at(ledger, "properties", "integrity_scope", "const")
        != "LOCAL_HASH_CHAIN_UNANCHORED"
        or at(ledger, "properties", "entry_hash") != {"$ref": "#/$defs/sha256"}
        or at(ledger, "allOf", 0, "if", "properties", "topology", "const")
        != "SOLO_HATS"
        or at(
            ledger, "allOf", 0, "then", "properties", "independent_verifier", "const"
        ) is not False
    ):
        errors.append("R3_RELAY_SCHEMA_DRIFT")

    causal_head = at(ledger, "$defs", "causal_head")
    causal_fields = {"stream_id", "stream_seq", "entry_hash"}
    causal_properties = at(causal_head, "properties")
    if (
        at(ledger, "properties", "body_bytes", "type") != "integer"
        or at(ledger, "properties", "body_bytes", "minimum") != 0
        or at(ledger, "properties", "canonicalization_version", "const")
        != "OMNI_CANONICAL_JSON_V1"
        or at(ledger, "properties", "observed_heads", "type") != "array"
        or at(ledger, "properties", "observed_heads", "uniqueItems") is not True
        or at(ledger, "properties", "observed_heads", "items")
        != {"$ref": "#/$defs/causal_head"}
        or not isinstance(causal_head, dict)
        or causal_head.get("type") != "object"
        or causal_head.get("additionalProperties") is not False
        or not exact_strings(causal_head.get("required"), causal_fields)
        or not isinstance(causal_properties, dict)
        or set(causal_properties) != causal_fields
        or causal_properties.get("stream_id") != {"$ref": "#/$defs/identifier"}
        or causal_properties.get("stream_seq") != {"type": "integer", "minimum": 1}
        or causal_properties.get("entry_hash") != {"$ref": "#/$defs/sha256"}
    ):
        errors.append("R3_RELAY_430_SCHEMA_DRIFT")

    anchor_record = at(ledger, "$defs", "external_anchor_record")
    anchor_qualification = at(ledger, "$defs", "external_anchor_qualification")
    anchor_trust = at(ledger, "$defs", "external_anchor_trust_domain")
    anchor_head = at(ledger, "$defs", "anchor_head")
    if (
        at(anchor_record, "properties", "schema", "const")
        != "omni-relay-ledger-external-anchor-v1"
        or at(anchor_record, "properties", "anchor_scope", "const")
        != "EXTERNAL_CREATE_ONCE_VECTOR_HEAD_ANCHOR"
        or at(anchor_record, "properties", "trust_domain")
        != {"$ref": "#/$defs/external_anchor_trust_domain"}
        or not exact_strings(
            at(anchor_record, "required"),
            {
                "schema", "anchor_set_id", "run_id", "anchor_seq", "created_at",
                "previous_anchor_hash", "anchor_root_fingerprint",
                "qualification_subject_hash", "heads", "heads_hash", "trust_domain",
                "anchor_scope", "anchor_hash",
            },
        )
        or at(anchor_qualification, "properties", "schema", "const")
        != "omni-relay-ledger-external-anchor-qualification-v1"
        or at(anchor_qualification, "properties", "status", "const")
        != "CALLER_QUALIFIED_UNVERIFIED"
        or at(anchor_trust, "oneOf", 0, "properties", "status", "const")
        != "UNQUALIFIED"
        or at(anchor_trust, "oneOf", 1, "properties", "status", "const")
        != "CALLER_QUALIFIED_UNVERIFIED"
        or at(anchor_head, "properties", "anchored_prefix_sha256")
        != {"$ref": "#/$defs/sha256"}
        or at(anchor_head, "properties", "entry_hash", "oneOf", 0)
        != {"$ref": "#/$defs/sha256"}
    ):
        errors.append("R3_RELAY_ANCHOR_SURFACE_DRIFT")

    relay_runtime = text_by_path.get("scripts/relay_ledger.py", "")
    entry_fields_match = re.search(
        r"ENTRY_FIELDS\s*=\s*frozenset\(\s*\{(?P<body>.*?)\}\s*\)",
        relay_runtime,
        flags=re.DOTALL,
    )
    runtime_entry_fields = (
        set(re.findall(r'"([a-z_]+)"', entry_fields_match.group("body")))
        if entry_fields_match
        else set()
    )
    if (
        runtime_entry_fields != ledger_fields
        or any(relay_runtime.count(f'"{field}"') < 4 for field in (
            "body_bytes", "canonicalization_version", "observed_heads",
        ))
        or not all(
            marker in relay_runtime
            for marker in (
                'ENTRY_SCHEMA = "omni-relay-ledger-entry-v1"',
                'INTEGRITY_SCOPE = "LOCAL_HASH_CHAIN_UNANCHORED"',
                'EXTERNAL_ANCHOR_SCOPE = "EXTERNAL_CREATE_ONCE_VECTOR_HEAD_ANCHOR"',
                'CANONICALIZATION_VERSION = "OMNI_CANONICAL_JSON_V1"',
                'ENTRY_DOMAIN = b"OMNI-RELAY-ENTRY-V1\\0"',
                'REPAIR_AUTHORITY_SCHEMA = "omni-relay-ledger-repair-authority-v1"',
                "def _validate_observed_heads(",
                'raise LedgerError("CANONICALIZATION_VERSION_INVALID")',
                'raise LedgerError("BODY_BYTES_MISMATCH")',
                'raise LedgerError("OBSERVED_HEAD_STREAM_DUPLICATE")',
                'raise LedgerError("OBSERVED_HEADS_NOT_SORTED")',
                'raise LedgerError("OBSERVED_HEADS_NONCANONICAL")',
                '"status": "UNQUALIFIED"',
                '"status": "CALLER_QUALIFIED_UNVERIFIED"',
                'raise LedgerError("SOLO_INDEPENDENCE_FALSE_REQUIRED")',
            )
        )
    ):
        errors.append("R3_RELAY_RUNTIME_DRIFT")

    relay_doctrine = re.sub(
        r"\s+", " ", text_by_path.get("references/11_relay_ledger.md", "").lower()
    )
    doctrine_markers = {
        "STREAM_LOCAL_ORDER": (
            "strict physical order and uniqueness within one stream",
            "there is no `max(all files)+1`",
        ),
        "FULL_ENTRY_HASH": (
            "a full-entry sha-256 chain binding metadata, payload, lease, fence, predecessor, and volume link",
            "canonical_json(entry_without_entry_hash)",
        ),
        "CANONICAL_BODY_AND_CAUSAL_HEADS": (
            "every entry carries `observed_heads`, a causal observation vector",
            "each object is exactly `{stream_id, stream_seq, entry_hash}`",
            "the only accepted canonicalization contract is `omni_canonical_json_v1`",
            "`body_bytes` is the exact byte length of that normalized body encoded as utf-8",
            "`canonicalization_version`, `body_bytes`, and the complete sorted `observed_heads` vector are inside both the request fingerprint and the full entry hash",
            "it does not merge streams, allocate a global number, prove simultaneity, or create a total order",
        ),
        "EXTERNAL_ANCHOR_MARKER": (
            "local_hash_chain_unanchored",
            "a checkpoint is consumer state, not an external anchor",
            "trust-domain status is separate from mechanical integrity",
            "unqualified",
            "caller_qualified_unverified",
            "cannot prove the organizational controls or authenticate the caller",
        ),
        "LEASE_FENCE": (
            "one active lease epoch and physical writer instance",
            "a new writer requires a strictly higher fence",
        ),
        "RECOVERY": (
            "fail-closed torn-tail detection and exact-target repair only under caller-supplied authority",
            "omni-relay-ledger-repair-authority-v1",
        ),
        "SOLO_INDEPENDENCE_FALSE": (
            "independent_verifier=false",
            "a hat change is not independent verification",
        ),
    }
    for doctrine, markers in doctrine_markers.items():
        if any(marker not in relay_doctrine for marker in markers):
            errors.append(f"R3_RELAY_DOCTRINE_MISSING:{doctrine}")

    relay_tests = text_by_path.get("tests/test_r3_relay_ledger.py", "")
    if not all(
        marker in relay_tests
        for marker in (
            "def test_pos_canonical_body_bytes_and_causal_request_binding",
            "def test_malformed_canonicalization_body_bytes_and_causal_heads_block",
            'assert_blocked(wrong_version, "CANONICALIZATION_VERSION_INVALID")',
            'assert_blocked(wrong_length, "BODY_BYTES_MISMATCH")',
            'assert_blocked(duplicate, "OBSERVED_HEAD_STREAM_DUPLICATE")',
            'assert_blocked(unsorted, "OBSERVED_HEADS_NOT_SORTED")',
            'assert_blocked(malformed, "OBSERVED_HEAD_MALFORMED")',
            'self.assertEqual(caught.exception.code, "EVENT_ID_CONFLICT")',
        )
    ):
        errors.append("R3_RELAY_430_TEST_COVERAGE_DRIFT")

    rotation_policy = at(ledger, "$defs", "rotation_policy")
    volume_seal = at(ledger, "$defs", "volume_seal")
    rotation_policy_fields = {
        "schema", "max_entries_per_volume", "max_bytes_per_volume",
    }
    volume_seal_fields = {
        "schema", "run_id", "stream_id", "volume_id", "volume_no",
        "first_seq", "last_seq", "entry_count", "byte_length", "file_sha256",
        "final_entry_hash", "previous_volume_seal_hash", "rotation_policy",
        "rotation_reasons", "phase_gate_id", "sealed_at", "integrity_scope",
        "seal_hash",
    }
    rotation_runtime_markers = (
        'ROTATION_POLICY_SCHEMA = "omni-relay-ledger-rotation-policy-v1"',
        "DEFAULT_MAX_ENTRIES_PER_VOLUME = 1_000",
        "DEFAULT_MAX_BYTES_PER_VOLUME = 8_388_608",
        "ROTATION_REASON_ORDER = (",
        '"ENTRY_THRESHOLD"',
        '"BYTE_THRESHOLD"',
        '"PHASE_GATE"',
        '"MANUAL_REQUEST"',
        "class RotationPolicy:",
        "def _validate_rotation_policy_record(",
        "def _rotation_reasons(",
        "entry_count >= policy.max_entries_per_volume",
        "byte_length >= policy.max_bytes_per_volume",
        "def _apply_rotation_policy_locked(",
        "def rotate_for_phase_gate(",
        '"rotation_policy": self.rotation_policy.as_record()',
        '"rotation_reasons": reasons',
        '"phase_gate_id": phase_gate_id',
        '"rotation": rotation',
    )
    rotation_doctrine_markers = (
        "the defaults are 1,000 entries or 8,388,608 exact ndjson bytes per volume",
        "`append()` evaluates both limits after durable readback while it still owns the stream lock",
        "`rotation_not_triggered`, `rotated`, or `rotation_reconciled`",
        "`rotate_for_phase_gate(lease, \"f3_to_f4\")`",
        "a retry with the same gate reconciles the same create-once seal",
        "rotation is strictly per writer",
        "never allocate a global sequence",
        "never turn causal `observed_heads` into a total order",
    )
    if (
        not isinstance(rotation_policy, dict)
        or rotation_policy.get("type") != "object"
        or rotation_policy.get("additionalProperties") is not False
        or not exact_strings(rotation_policy.get("required"), rotation_policy_fields)
        or not isinstance(rotation_policy.get("properties"), dict)
        or set(rotation_policy["properties"]) != rotation_policy_fields
        or at(rotation_policy, "properties", "schema", "const")
        != "omni-relay-ledger-rotation-policy-v1"
        or at(rotation_policy, "properties", "max_entries_per_volume")
        != {"type": "integer", "minimum": 1}
        or at(rotation_policy, "properties", "max_bytes_per_volume")
        != {"type": "integer", "minimum": 1}
        or not isinstance(volume_seal, dict)
        or volume_seal.get("type") != "object"
        or volume_seal.get("additionalProperties") is not False
        or not exact_strings(volume_seal.get("required"), volume_seal_fields)
        or at(volume_seal, "properties", "rotation_policy")
        != {"$ref": "#/$defs/rotation_policy"}
        or at(volume_seal, "properties", "rotation_reasons", "type") != "array"
        or at(volume_seal, "properties", "rotation_reasons", "minItems") != 1
        or at(volume_seal, "properties", "rotation_reasons", "uniqueItems") is not True
        or not exact_strings(
            at(volume_seal, "properties", "rotation_reasons", "items", "enum"),
            {"ENTRY_THRESHOLD", "BYTE_THRESHOLD", "PHASE_GATE", "MANUAL_REQUEST"},
        )
        or at(volume_seal, "properties", "phase_gate_id", "oneOf")
        != [{"$ref": "#/$defs/identifier"}, {"type": "null"}]
        or not all(marker in relay_runtime for marker in rotation_runtime_markers)
        or not all(marker in relay_doctrine for marker in rotation_doctrine_markers)
    ):
        errors.append("R3_1_RELAY_ROTATION_POLICY_DRIFT")

    if not all(
        marker in relay_tests
        for marker in (
            "def test_rotation_policy_does_not_trigger_below_both_thresholds",
            "def test_rotation_policy_triggers_at_entry_threshold",
            "def test_rotation_policy_triggers_at_exact_byte_threshold",
            "def test_rotation_policy_triggers_phase_gate_create_once_and_per_writer",
        )
    ):
        errors.append("R3_1_RELAY_ROTATION_TEST_COVERAGE_DRIFT")


def _integrated_l4_l5_schema_contract(root: Path, errors: list[str]) -> None:
    """Pin every post-intake contract even when the test runner is disabled.

    L4/L5 runtimes perform the instance-level replay.  The package validator
    independently prevents a release from silently dropping, reopening, or
    renaming one of their schema envelopes.
    """
    for filename, (expected_id, expected_schema_values) in INTEGRATED_SCHEMA_CONTRACTS.items():
        path = root / "schemas" / filename
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors.append(f"INTEGRATED_SCHEMA_UNREADABLE:{filename}:{type(error).__name__}")
            continue
        if not isinstance(schema, dict):
            errors.append(f"INTEGRATED_SCHEMA_NOT_OBJECT:{filename}")
            continue
        if jsonschema is None:
            errors.append(f"JSONSCHEMA_RUNTIME_UNAVAILABLE:{filename}")
        else:
            try:
                jsonschema.Draft202012Validator.check_schema(schema)
            except Exception as error:
                errors.append(f"INTEGRATED_SCHEMA_INVALID:{filename}:{type(error).__name__}")
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"INTEGRATED_SCHEMA_DIALECT_DRIFT:{filename}")
        if schema.get("$id") != expected_id:
            errors.append(f"INTEGRATED_SCHEMA_ID_DRIFT:{filename}")
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            errors.append(f"INTEGRATED_SCHEMA_ENVELOPE_OPEN:{filename}")

        nodes = list(_walk_schema_nodes(schema))
        schema_values = {
            str(properties["schema"]["const"])
            for node in nodes
            if isinstance((properties := node.get("properties")), dict)
            and isinstance(properties.get("schema"), dict)
            and isinstance(properties["schema"].get("const"), str)
        }
        if schema_values != expected_schema_values:
            errors.append(f"INTEGRATED_SCHEMA_NAME_DRIFT:{filename}")
        required_fields = {
            str(field)
            for node in nodes
            if isinstance(node.get("required"), list)
            for field in node["required"]
        }
        if "record_digest" not in required_fields:
            errors.append(f"INTEGRATED_SCHEMA_RECORD_DIGEST_OPTIONAL:{filename}")
        for node in nodes:
            if (
                node.get("type") == "object"
                and isinstance(node.get("properties"), dict)
                and node.get("additionalProperties") is not False
            ):
                errors.append(f"INTEGRATED_SCHEMA_NESTED_OBJECT_OPEN:{filename}")
                break


def validate(
    root: Path, run_tests: bool = True, projection_host: str | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    all_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    cache_files = sorted(path for path in all_files if "__pycache__" in Path(path).parts or path.endswith(".pyc"))
    errors.extend(f"FORBIDDEN_CACHE_ARTIFACT:{path}" for path in cache_files)
    files = all_files - set(cache_files)
    projection_host = _delivery_projection(root, files, errors, projection_host)
    expected = _delivery_expected(projection_host)
    errors.extend(f"MISSING:{path}" for path in sorted(expected - files))
    errors.extend(f"UNEXPECTED:{path}" for path in sorted(files - expected))

    for relative, expected_sha256 in PACKAGE_FILE_SHA256.items():
        try:
            observed_sha256 = hashlib.sha256((root / relative).read_bytes()).hexdigest().upper()
        except OSError as error:
            errors.append(f"PACKAGE_FILE_UNREADABLE:{relative}:{type(error).__name__}:{error}")
            continue
        if observed_sha256 != expected_sha256:
            errors.append(f"PACKAGE_FILE_SHA256_DRIFT:{relative}")

    text_by_path: dict[str, str] = {}
    for relative in sorted(files):
        path = root / relative
        if path.suffix.lower() not in {".md", ".py", ".yaml", ".json"}:
            continue
        try:
            text_by_path[relative] = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as error:
            errors.append(f"TEXT_NOT_UTF8:{relative}:{type(error).__name__}:{error}")

    head = text_by_path.get("SKILL.md")
    tokens = 0
    method = "unavailable"
    if head is None:
        errors.append("SKILL_UNREADABLE")
    else:
        _frontmatter(head, errors, projection_host)
        _invocation_contract(
            text_by_path, errors,
            require_openai_metadata=projection_host in (None, "codex"),
        )
        tokens, method = measure(head)
        if len(head.splitlines()) >= 500:
            errors.append("SKILL_LINES_NOT_UNDER_500")
        if tokens >= 5000:
            errors.append("SKILL_TOKENS_NOT_UNDER_5000")
        routed = ["agents/openai.yaml", "adapters/host_generation.yaml", *TEMPLATES, *[f"{name}.py" for name in CORE + SENTRY]]
        for artifact in routed:
            if artifact not in head:
                errors.append(f"ARTIFACT_NOT_ROUTED:{artifact}")

    if "SKILL.md" in files:
        try:
            errors.extend(validate_references(root))
        except Exception as error:  # validator boundary: typed, never traceback
            errors.append(f"REFERENCE_VALIDATOR_ERROR:{type(error).__name__}:{error}")
    _l2_doctrine_contract(text_by_path, errors)
    _l3_doctrine_contract(text_by_path, errors)
    _l3_schema_contract(root, errors)
    _rotation_contract(root, errors)
    _state_and_receipt_contract(root, errors)
    _guided_intake_contract(root, errors)
    _closed_l2_artifact_contract(root, errors)
    _r3_contract(root, text_by_path, errors)
    _integrated_l4_l5_schema_contract(root, errors)
    _adapter_contract(root, errors, None if projection_host is None else [projection_host])
    try:
        _template_contract(root, errors)
    except (OSError, UnicodeError) as error:
        errors.append(f"TEMPLATE_CONTRACT_UNREADABLE:{type(error).__name__}:{error}")

    for relative, text in text_by_path.items():
        if relative == "scripts/validate_skill.py":
            continue
        for line in text.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("self_spawn:") and stripped.split(":", 1)[1].strip() not in {"false", "forbidden"}:
                errors.append(f"FORBIDDEN_PATTERN:{relative}:SELF_SPAWN_ENABLED")
            if stripped in {"f5_allowed: true", "external_effects_allowed: true"}:
                errors.append(f"FORBIDDEN_PATTERN:{relative}:UNAUTHORIZED_SCOPE_ENABLED")
        if re.search(r"(?i)subprocess\.(?:run|popen).*\b(?:claude|cursor-agent)\b", text):
            errors.append(f"FORBIDDEN_PATTERN:{relative}:OPAQUE_AGENT_LAUNCH")

    test_exit = None
    tests_run = None
    if run_tests and projection_host is not None:
        errors.append("DELIVERY_PROJECTION_REQUIRES_NO_TESTS")
    if run_tests and projection_host is None and not (expected - files):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(root / "tests"), "-p", "test_*.py"],
            cwd=root, env=environment, capture_output=True, text=True, check=False,
        )
        test_exit = completed.returncode
        test_output = completed.stdout + completed.stderr
        match = re.search(r"Ran\s+(\d+)\s+tests?", test_output)
        tests_run = int(match.group(1)) if match else None
        if test_exit == 0 and (tests_run is None or tests_run < MIN_TEST_COUNT):
            errors.append(f"TEST_COUNT_BELOW_MINIMUM:{tests_run if tests_run is not None else 'UNPARSEABLE'}:{MIN_TEST_COUNT}")
        if test_exit:
            tail = test_output[-2000:].replace("\n", " | ")
            errors.append(f"TESTS_FAILED:{test_exit}:{tail}")
    return {
        "schema": "omni-skill-validation-v2", "status": "PASS" if not errors else "FAIL",
        "errors": sorted(set(errors)), "files": len(files), "expected_files": len(expected),
        "package_kind": "HOST_DELIVERY_PROJECTION" if projection_host else "CANONICAL_SOURCE",
        "projection_host": projection_host,
        "tokens": tokens, "token_method": method, "test_exit": test_exit, "tests_run": tests_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--no-tests", action="store_true")
    parser.add_argument("--host-projection", choices=DELIVERY_HOSTS)
    args = parser.parse_args()
    try:
        result = validate(
            args.root.resolve(), not args.no_tests, projection_host=args.host_projection
        )
    except Exception as error:  # final CLI boundary
        result = {"schema": "omni-skill-validation-v2", "status": "BLOCKED", "errors": [f"VALIDATOR_INTERNAL_ERROR:{type(error).__name__}:{error}"]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else (2 if result["status"] == "BLOCKED" else 1)


if __name__ == "__main__":
    raise SystemExit(main())

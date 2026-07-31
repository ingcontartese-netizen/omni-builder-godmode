from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SCHEMA_ROOT = ROOT / "schemas"
SHA_A = "A" * 64
SHA_B = "B" * 64
SHA_C = "C" * 64
CREATED_AT = "2026-07-30T00:00:00Z"
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


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def binding(name: str, digest: str = SHA_A) -> dict[str, Any]:
    return {
        "path": f"/project/well/control/{name}",
        "bytes": 1,
        "sha256": digest,
    }


def effect(
    name: str,
    status: str,
    handling_policy: str,
) -> dict[str, Any]:
    return {
        "effect": name,
        "status": status,
        "authority_source_binding": binding(f"{name.lower()}-authority.json"),
        "scope_paths": ["/project/well"],
        "handling_policy": handling_policy,
    }


def authority_record() -> dict[str, Any]:
    return {
        "schema": "omni-knowledge-effect-authority-v1",
        "status": "EFFECT_AUTHORIZED",
        "decision": "AUTHORIZED",
        "authority_id": "AUTH-1",
        "action": "LANE_LIGHT_WEB_RESEARCH",
        "task_id": "TASK-1",
        "pipeline_id": "PIPE-1",
        "intake_state_sha256": SHA_A,
        "session_pair_sha256": SHA_B,
        "subject_role": "BUILDER",
        "subject_session_id": "builder-session",
        "workspace_access_envelope_binding": binding("workspace-access.json"),
        "well_root": "/project/well",
        "input_bindings": [binding("state.json")],
        "output_paths": ["/project/well/lanes/builder/light-map.md"],
        "network_research": effect(
            "NETWORK_RESEARCH", "AUTHORIZED", "CAPTURE_MD_ONLY"
        ),
        "download": effect("DOWNLOAD", "DENIED", "NO_RAW_DOWNLOAD"),
        "one_shot": True,
        "operation_nonce": "NONCE-1",
        "non_grants": NON_GRANTS,
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def participant(role: str) -> dict[str, Any]:
    lane = role.lower()
    return {
        "role": role,
        "identity": f"{lane}-identity",
        "host": f"{lane}-host",
        "session_id": f"{lane}-session",
        "mandate_path": f"/project/well/control/{lane}-mandate.md",
        "mandate_bytes": 1,
        "mandate_sha256": SHA_A if role == "BUILDER" else SHA_B,
        "write_lane": f"/project/well/lanes/{lane}",
        "owned_paths": [f"/project/well/lanes/{lane}"],
    }


def lane_state(role: str) -> dict[str, Any]:
    return {
        "role": role,
        "session_id": f"{role.lower()}-session",
        "lane_root": f"/project/well/lanes/{role.lower()}",
        "state": "MATERIAL_BOUND",
        "artifacts": {},
        "manifest_binding": None,
    }


def pipeline_state() -> dict[str, Any]:
    return {
        "schema": "omni-knowledge-pipeline-state-v1",
        "state_id": "STATE-1",
        "pipeline_id": "PIPE-1",
        "generation": 1,
        "phase": "WELL_BOOTSTRAPPING",
        "status": "ACTIVE",
        "task_id": "TASK-1",
        "project_root": "/project",
        "well_root": "/project/well",
        "intake_binding": binding("intake.json"),
        "session_pair_sha256": SHA_B,
        "session_pair": {
            "pair_id": "PAIR-1",
            "pair_sha256": SHA_B,
            "lock_status": "LOCKED_UNTIL_CUTOVER",
            "builder": participant("BUILDER"),
            "verifier": participant("VERIFIER"),
        },
        "access_envelopes": {
            "BUILDER": binding("builder-access.json"),
            "VERIFIER": binding("verifier-access.json", SHA_B),
        },
        "source_roots": ["/project/sources"],
        "material": {"state": "NOT_STARTED", "manifest_binding": None},
        "lanes": {
            "BUILDER": lane_state("BUILDER"),
            "VERIFIER": lane_state("VERIFIER"),
        },
        "fusion": {
            "state": "NOT_STARTED",
            "candidate_binding": None,
            "canonical_binding": None,
            "countersign_binding": None,
        },
        "event": "INIT",
        "actor": {"role": "BUILDER", "session_id": "builder-session"},
        "effect_authority_binding": binding("effect-authority.json"),
        "evidence_bindings": [
            binding("transition-reservation.json"),
            binding("operation-nonce.json"),
            binding("evidence.json"),
        ],
        "blocking_reason_codes": [],
        "previous_state_binding": None,
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def material_item(admission: str) -> dict[str, Any]:
    return {
        "item_id": "MAT-0001-ABCDEF123456",
        "source_binding": binding("material-source.bin"),
        "quarantine_binding": binding("material-quarantine.bin"),
        "metadata_binding": binding("material-metadata.json"),
        "rights_status": "CLEARED",
        "privacy_status": "CLEAR",
        "acl_status": "READABLE",
        "scan_status": "PASS",
        "parse_status": "PASS",
        "admission": admission,
        "rejection_reasons": [],
    }


def material_manifest(stage: str = "QUARANTINED") -> dict[str, Any]:
    joined = stage == "JOINED"
    item_id = "MAT-0001-ABCDEF123456"
    return {
        "schema": "omni-material-join-manifest-v1",
        "status": "MATERIAL_JOINED" if joined else "MATERIAL_QUARANTINED",
        "stage": stage,
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "availability": "USER_MATERIAL_PRESENT",
        "items": [material_item("JOINED" if joined else "PENDING")],
        "joined_item_ids": [item_id] if joined else [],
        "rejected_item_ids": [],
        "previous_manifest_binding": binding("quarantined-material.json") if joined else None,
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def metadata_attestation(eligible: bool = True) -> dict[str, Any]:
    return {
        "schema": "omni-material-metadata-attestation-v1",
        "status": "MATERIAL_METADATA_ATTESTED",
        "attestation_id": "ATTEST-1",
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "subject_source_binding": binding("material-source.bin"),
        "issuer_role": "BUILDER",
        "issuer_session_id": "builder-session",
        "rights_status": "AUTHORIZED" if eligible else "DENIED",
        "rights_evidence_binding": binding("rights-evidence.json"),
        "privacy_status": "APPROVED",
        "privacy_evidence_binding": binding("privacy-evidence.json"),
        "acl_status": "WITHIN_ENVELOPE",
        "acl_evidence_binding": binding("acl-evidence.json"),
        "scan_status": "PASS",
        "scan_receipt_binding": binding("scan-receipt.json"),
        "parse_status": "PASS",
        "parse_receipt_binding": binding("parse-receipt.json"),
        "admission_recommendation": "ELIGIBLE" if eligible else "REJECTED",
        "rejection_reason_codes": [] if eligible else ["MATERIAL_RIGHTS_DENIED"],
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def web_source(source_id: str, phase: str, capture_mode: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "research_phase": phase,
        "locator": f"https://example.test/{source_id.lower()}",
        "title": f"Source {source_id}",
        "publisher": "Example publisher",
        "accessed_at": CREATED_AT,
        "capture_mode": capture_mode,
        "capture_binding": binding(f"{source_id.lower()}-capture.md"),
        "sections_consulted": ["section 1"],
    }


def query_event(query_id: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "query_text": "authoritative current guidance",
        "executed_at": CREATED_AT,
        "tool": "official-search",
        "result_capture_binding": binding(f"{query_id.lower()}-results.md"),
        "returned_source_ids": source_ids,
    }


def light_map_record() -> dict[str, Any]:
    return {
        "schema": "omni-light-map-v1",
        "status": "LIGHT_MAP_FROZEN",
        "map_id": "LIGHT-MAP-1",
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "role": "BUILDER",
        "session_id": "builder-session",
        "lane_root": "/project/well/lanes/builder",
        "material_join_binding": binding("material-joined.json"),
        "effect_authority_binding": binding("light-authority.json"),
        "network_research_performed": True,
        "cross_read_performed": False,
        "query_events": [query_event("QUERY-LIGHT-1", ["SRC-LIGHT-1"])],
        "sources": [web_source("SRC-LIGHT-1", "LIGHT_WEB", "CAPTURE_MD_ONLY")],
        "light_source_ids": ["SRC-LIGHT-1"],
        "topic_clusters": [
            {"cluster_id": "CLUSTER-1", "label": "Primary", "source_ids": ["SRC-LIGHT-1"]}
        ],
        "priority_source_ids": ["SRC-LIGHT-1"],
        "gaps": ["Need a distinct deep source"],
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def deep_plan_record() -> dict[str, Any]:
    return {
        "schema": "omni-deep-plan-v1",
        "status": "DEEP_PLAN_FROZEN",
        "plan_id": "DEEP-PLAN-1",
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "role": "BUILDER",
        "session_id": "builder-session",
        "lane_root": "/project/well/lanes/builder",
        "light_map_binding": binding("light-map.json"),
        "light_source_ids": ["SRC-LIGHT-1"],
        "web_research_required": True,
        "cross_read_performed": False,
        "research_questions": ["What changed since the light map?"],
        "planned_queries": ["current primary specification"],
        "target_source_classes": ["PRIMARY_OFFICIAL"],
        "novelty_requirement": {
            "basis": "LIGHT_MAP_SOURCE_IDS",
            "require_set_difference": True,
            "minimum_new_sources": 1,
        },
        "download_strategy": "CAPTURE_MD_ONLY_UNLESS_SEPARATELY_AUTHORIZED",
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def web_research_receipt() -> dict[str, Any]:
    return {
        "schema": "omni-web-research-receipt-v1",
        "status": "DEEP_WEB_RESEARCH_PASS",
        "receipt_id": "WEB-RECEIPT-1",
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "role": "BUILDER",
        "session_id": "builder-session",
        "lane_root": "/project/well/lanes/builder",
        "research_phase": "DEEP_WEB",
        "light_map_binding": binding("light-map.json"),
        "deep_plan_binding": binding("deep-plan.json"),
        "effect_authority_binding": binding("deep-authority.json"),
        "network_research_performed": True,
        "cross_read_performed": False,
        "query_events": [query_event("QUERY-DEEP-1", ["SRC-DEEP-1"])],
        "sources": [web_source("SRC-DEEP-1", "DEEP_WEB", "CAPTURE_MD_ONLY")],
        "light_source_ids": ["SRC-LIGHT-1"],
        "deep_source_ids": ["SRC-DEEP-1"],
        "deep_new_source_ids": ["SRC-DEEP-1"],
        "download_performed": False,
        "download_authority_binding": None,
        "acquisitions": [],
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def source_manifest_record() -> dict[str, Any]:
    return {
        "schema": "omni-source-manifest-v1",
        "status": "SOURCE_MANIFEST_FROZEN",
        "manifest_id": "SOURCE-MANIFEST-1",
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "role": "BUILDER",
        "session_id": "builder-session",
        "lane_root": "/project/well/lanes/builder",
        "material_join_binding": binding("material-joined.json"),
        "light_map_binding": binding("light-map.json"),
        "deep_plan_binding": binding("deep-plan.json"),
        "deep_research_receipt_binding": binding("deep-research.json"),
        "material_source_ids": [],
        "light_source_ids": ["SRC-LIGHT-1"],
        "deep_source_ids": ["SRC-DEEP-1"],
        "deep_new_source_ids": ["SRC-DEEP-1"],
        "sources": [
            web_source("SRC-LIGHT-1", "LIGHT_WEB", "CAPTURE_MD_ONLY"),
            web_source("SRC-DEEP-1", "DEEP_WEB", "CAPTURE_MD_ONLY"),
        ],
        "findings": [
            {
                "finding_id": "FINDING-1",
                "statement": "A byte-bound finding.",
                "source_ids": ["SRC-DEEP-1"],
                "confidence": "HIGH",
                "freshness": "CURRENT_PRIMARY",
            }
        ],
        "conflicts": [],
        "dissent": [],
        "provenance": [
            {
                "provenance_id": "PROV-1",
                "sources_actually_read": ["SRC-DEEP-1"],
                "version_hash_access_date": ["v1 / sha256 / 2026-07-30"],
                "sections_consulted": ["section 1"],
                "received_material_not_used": [],
                "facts_extracted": ["fact"],
                "model_synthesis_or_inference": ["inference"],
                "conflicts_gaps_and_limits": [],
            }
        ],
        "received_not_used": [],
        "download_mode": "CAPTURE_MD_ONLY",
        "download_authority_binding": None,
        "acquisitions": [],
        "download_fallback": "CAPTURE_MD_ONLY",
        "limits": [],
        "cross_read_performed": False,
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def lane_manifest() -> dict[str, Any]:
    return {
        "schema": "omni-lane-knowledge-manifest-v1",
        "status": "LANE_FROZEN",
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "role": "BUILDER",
        "session_id": "builder-session",
        "lane_root": "/project/well/lanes/builder",
        "material_join_binding": binding("material-joined.json"),
        "light_map_binding": binding("light-map.md"),
        "deep_plan_binding": binding("deep-plan.md"),
        "deep_research_receipt_binding": binding("deep-research.json"),
        "deep_dossier_binding": binding("deep-dossier.md"),
        "source_manifest_binding": binding("source-manifest.json"),
        "acquisitions": [],
        "web_research_required": True,
        "cross_read_performed": False,
        "deep_new_source_ids": ["SRC-DEEP-1"],
        "findings": [
            {
                "finding_id": "FINDING-1",
                "statement": "A byte-bound finding.",
                "source_ids": ["SRC-DEEP-1"],
                "confidence": "HIGH",
                "freshness": "CURRENT_PRIMARY",
            }
        ],
        "conflicts": [],
        "dissent": [],
        "provenance": [
            {
                "provenance_id": "PROV-1",
                "sources_actually_read": ["SRC-DEEP-1"],
                "version_hash_access_date": ["v1 / sha256 / 2026-07-30"],
                "sections_consulted": ["section 1"],
                "received_material_not_used": [],
                "facts_extracted": ["fact"],
                "model_synthesis_or_inference": ["inference"],
                "conflicts_gaps_and_limits": [],
            }
        ],
        "received_not_used": [],
        "limits": [],
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def fusion_record(kind: str = "FUSION_CANDIDATE") -> dict[str, Any]:
    countersign = kind == "FUSION_COUNTERSIGN"
    return {
        "schema": "omni-knowledge-fusion-v1",
        "kind": kind,
        "status": "KNOWLEDGE_FUSION_PASS" if countersign else "FUSION_EMITTED",
        "fusion_id": "FUSION-1",
        "pipeline_id": "PIPE-1",
        "task_id": "TASK-1",
        "session_pair_sha256": SHA_B,
        "author_role": "BUILDER",
        "author_session_id": "builder-session",
        "builder_manifest_binding": binding("builder-manifest.json"),
        "verifier_manifest_binding": binding("verifier-manifest.json", SHA_B),
        "decision_register_binding": binding("decision-register.json"),
        "canonical_knowledge_binding": binding("canonical-knowledge.md"),
        "finding_ids": ["FINDING-1"],
        "dissent_ids_preserved": [],
        "countersigner_role": "VERIFIER" if countersign else None,
        "countersigner_session_id": "verifier-session" if countersign else None,
        "candidate_binding": binding("fusion-candidate.json") if countersign else None,
        "created_at": CREATED_AT,
        "record_digest": SHA_C,
    }


def schema_validator(filename: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def assert_invalid(
    testcase: unittest.TestCase,
    validator: Draft202012Validator,
    instance: dict[str, Any],
) -> None:
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    testcase.assertTrue(errors, instance)


class L3RecordSchemaTests(unittest.TestCase):
    def test_all_ten_draft_2020_12_schemas_accept_minimal_valid_records(self):
        cases = {
            "knowledge_effect_authority.schema.json": [authority_record()],
            "knowledge_pipeline_state.schema.json": [pipeline_state()],
            "material_join_manifest.schema.json": [
                material_manifest("QUARANTINED"),
                material_manifest("JOINED"),
            ],
            "lane_knowledge_manifest.schema.json": [lane_manifest()],
            "knowledge_fusion.schema.json": [
                fusion_record("FUSION_CANDIDATE"),
                fusion_record("FUSION_COUNTERSIGN"),
            ],
            "material_metadata_attestation.schema.json": [
                metadata_attestation(True),
                metadata_attestation(False),
            ],
            "light_map.schema.json": [light_map_record()],
            "deep_plan.schema.json": [deep_plan_record()],
            "web_research_receipt.schema.json": [web_research_receipt()],
            "source_manifest.schema.json": [source_manifest_record()],
        }
        self.assertEqual(len(cases), 10)
        for filename, records in cases.items():
            validator = schema_validator(filename)
            for record in records:
                with self.subTest(schema=filename, kind=record.get("kind"), stage=record.get("stage")):
                    validator.validate(record)

    def test_authority_rejects_denied_network_for_research_action(self):
        validator = schema_validator("knowledge_effect_authority.schema.json")
        record = authority_record()
        record["network_research"]["status"] = "DENIED"
        assert_invalid(self, validator, record)

    def test_authority_keeps_download_separate_and_policy_bound(self):
        validator = schema_validator("knowledge_effect_authority.schema.json")
        network_only = authority_record()
        validator.validate(network_only)

        network_and_download = authority_record()
        network_and_download["download"]["status"] = "AUTHORIZED"
        network_and_download["download"]["handling_policy"] = (
            "QUARANTINE_HASH_NEVER_EXECUTE"
        )
        validator.validate(network_and_download)

        unsafe_download = copy.deepcopy(network_and_download)
        unsafe_download["download"]["handling_policy"] = "NO_RAW_DOWNLOAD"
        assert_invalid(self, validator, unsafe_download)

    def test_state_rejects_illegal_phase_shape_and_missing_transition_field(self):
        validator = schema_validator("knowledge_pipeline_state.schema.json")
        illegal_phase = pipeline_state()
        illegal_phase["phase"] = "MATERIAL_JOINED"
        assert_invalid(self, validator, illegal_phase)

        missing_event = pipeline_state()
        missing_event.pop("event")
        assert_invalid(self, validator, missing_event)

    def test_material_quarantined_and_joined_branches_fail_closed(self):
        validator = schema_validator("material_join_manifest.schema.json")
        quarantined_as_joined = material_manifest("QUARANTINED")
        quarantined_as_joined["status"] = "MATERIAL_JOINED"
        assert_invalid(self, validator, quarantined_as_joined)

        joined_without_predecessor = material_manifest("JOINED")
        joined_without_predecessor["previous_manifest_binding"] = None
        assert_invalid(self, validator, joined_without_predecessor)

    def test_lane_rejects_disabled_web_cross_read_empty_deep_delta_and_no_provenance(self):
        validator = schema_validator("lane_knowledge_manifest.schema.json")
        mutations = {
            "web_not_required": ("web_research_required", False),
            "cross_read": ("cross_read_performed", True),
            "no_deep_new_sources": ("deep_new_source_ids", []),
            "no_provenance": ("provenance", []),
        }
        for name, (field, value) in mutations.items():
            with self.subTest(name=name):
                record = lane_manifest()
                record[field] = value
                assert_invalid(self, validator, record)

    def test_fusion_rejects_role_self_sign_wrong_kind_status_and_missing_binding(self):
        validator = schema_validator("knowledge_fusion.schema.json")

        role_self_sign = fusion_record("FUSION_COUNTERSIGN")
        role_self_sign["countersigner_role"] = "BUILDER"
        assert_invalid(self, validator, role_self_sign)

        wrong_status = fusion_record("FUSION_CANDIDATE")
        wrong_status["status"] = "KNOWLEDGE_FUSION_PASS"
        assert_invalid(self, validator, wrong_status)

        missing_binding = fusion_record("FUSION_COUNTERSIGN")
        missing_binding.pop("canonical_knowledge_binding")
        assert_invalid(self, validator, missing_binding)

    def test_metadata_attestation_rejects_false_eligibility_and_unbound_subject(self):
        validator = schema_validator("material_metadata_attestation.schema.json")

        false_eligibility = metadata_attestation(False)
        false_eligibility["admission_recommendation"] = "ELIGIBLE"
        false_eligibility["rejection_reason_codes"] = []
        assert_invalid(self, validator, false_eligibility)

        unbound_subject = metadata_attestation(True)
        unbound_subject["subject_source_binding"].pop("sha256")
        assert_invalid(self, validator, unbound_subject)

    def test_light_map_rejects_unperformed_network_cross_read_and_false_capture(self):
        validator = schema_validator("light_map.schema.json")
        mutations = {
            "network_not_performed": ("network_research_performed", False),
            "cross_read": ("cross_read_performed", True),
            "no_query_events": ("query_events", []),
        }
        for name, (field, value) in mutations.items():
            with self.subTest(name=name):
                record = light_map_record()
                record[field] = value
                assert_invalid(self, validator, record)

        false_capture = light_map_record()
        false_capture["sources"][0]["capture_mode"] = "QUARANTINED_RAW"
        assert_invalid(self, validator, false_capture)

    def test_deep_plan_rejects_cross_read_empty_plan_and_zero_novelty(self):
        validator = schema_validator("deep_plan.schema.json")

        cross_read = deep_plan_record()
        cross_read["cross_read_performed"] = True
        assert_invalid(self, validator, cross_read)

        empty_plan = deep_plan_record()
        empty_plan["planned_queries"] = []
        assert_invalid(self, validator, empty_plan)

        zero_novelty = deep_plan_record()
        zero_novelty["novelty_requirement"]["minimum_new_sources"] = 0
        assert_invalid(self, validator, zero_novelty)

    def test_web_receipt_rejects_false_network_and_unattested_download(self):
        validator = schema_validator("web_research_receipt.schema.json")

        false_network = web_research_receipt()
        false_network["network_research_performed"] = False
        assert_invalid(self, validator, false_network)

        unattested_download = web_research_receipt()
        unattested_download["download_performed"] = True
        assert_invalid(self, validator, unattested_download)

        false_raw_capture = web_research_receipt()
        false_raw_capture["sources"][0]["capture_mode"] = "QUARANTINED_RAW"
        assert_invalid(self, validator, false_raw_capture)

    def test_source_manifest_rejects_missing_evidence_cross_read_and_false_download(self):
        validator = schema_validator("source_manifest.schema.json")

        no_findings = source_manifest_record()
        no_findings["findings"] = []
        assert_invalid(self, validator, no_findings)

        cross_read = source_manifest_record()
        cross_read["cross_read_performed"] = True
        assert_invalid(self, validator, cross_read)

        false_download = source_manifest_record()
        false_download["download_mode"] = "QUARANTINED_RAW"
        false_download["download_fallback"] = "NOT_APPLICABLE"
        assert_invalid(self, validator, false_download)


SchemaMutation = Callable[[dict[str, Any]], None]


SCHEMA_CONTRACT_MUTANTS: tuple[tuple[str, SchemaMutation, str], ...] = (
    (
        "knowledge_effect_authority.schema.json",
        lambda schema: schema["allOf"][3]["then"]["properties"]
        ["network_research"]["properties"]["status"].__setitem__("const", "DENIED"),
        "L3_SCHEMA_AUTHORITY_CONTRACT_DRIFT",
    ),
    (
        "knowledge_pipeline_state.schema.json",
        lambda schema: schema["allOf"][0]["then"]["properties"]["status"].__setitem__(
            "const", "ACTIVE"
        ),
        "L3_SCHEMA_STATE_CONTRACT_DRIFT",
    ),
    (
        "material_join_manifest.schema.json",
        lambda schema: schema["allOf"][1]["then"]["properties"]["status"].__setitem__(
            "const", "MATERIAL_JOINED"
        ),
        "L3_SCHEMA_MATERIAL_CONTRACT_DRIFT",
    ),
    (
        "lane_knowledge_manifest.schema.json",
        lambda schema: schema["properties"]["web_research_required"].__setitem__(
            "const", False
        ),
        "L3_SCHEMA_LANE_CONTRACT_DRIFT",
    ),
    (
        "knowledge_fusion.schema.json",
        lambda schema: schema["allOf"][1]["then"]["properties"]["status"].__setitem__(
            "const", "FUSION_EMITTED"
        ),
        "L3_SCHEMA_FUSION_CONTRACT_DRIFT",
    ),
    (
        "material_metadata_attestation.schema.json",
        lambda schema: schema["allOf"][0]["then"]["properties"]
        ["admission_recommendation"].__setitem__("const", "REJECTED"),
        "L3_SCHEMA_MATERIAL_METADATA_ATTESTATION_CONTRACT_DRIFT",
    ),
    (
        "light_map.schema.json",
        lambda schema: schema["properties"]["network_research_performed"].__setitem__(
            "const", False
        ),
        "L3_SCHEMA_LIGHT_MAP_CONTRACT_DRIFT",
    ),
    (
        "deep_plan.schema.json",
        lambda schema: schema["properties"]["novelty_requirement"]["properties"]
        ["minimum_new_sources"].__setitem__("minimum", 0),
        "L3_SCHEMA_DEEP_PLAN_CONTRACT_DRIFT",
    ),
    (
        "web_research_receipt.schema.json",
        lambda schema: schema["allOf"][0]["then"]["properties"]
        ["acquisitions"].__setitem__("maxItems", 1),
        "L3_SCHEMA_WEB_RESEARCH_RECEIPT_CONTRACT_DRIFT",
    ),
    (
        "source_manifest.schema.json",
        lambda schema: schema["allOf"][0]["then"]["properties"]
        ["acquisitions"].__setitem__("maxItems", 1),
        "L3_SCHEMA_SOURCE_MANIFEST_CONTRACT_DRIFT",
    ),
)


class L3SchemaContractMutantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package_validator = load(
            "validate_skill_l3_schema_mutants",
            ROOT / "scripts" / "validate_skill.py",
        )

    def test_l3_schema_contract_baseline_has_no_l3_schema_drift(self):
        result = self.package_validator.validate(ROOT, run_tests=False)
        errors = [
            error for error in result["errors"] if error.startswith("L3_SCHEMA_")
        ]
        self.assertEqual(errors, [], result)

    def test_each_semantic_schema_mutant_fails_with_stable_code(self):
        self.assertEqual(len(SCHEMA_CONTRACT_MUTANTS), 10)
        for filename, mutate, expected in SCHEMA_CONTRACT_MUTANTS:
            with self.subTest(schema=filename), tempfile.TemporaryDirectory() as directory:
                cold_copy = Path(directory) / "package"
                shutil.copytree(
                    ROOT,
                    cold_copy,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc", ".pytest_cache"
                    ),
                )
                path = cold_copy / "schemas" / filename
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")

                result = self.package_validator.validate(cold_copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)


if __name__ == "__main__":
    unittest.main()

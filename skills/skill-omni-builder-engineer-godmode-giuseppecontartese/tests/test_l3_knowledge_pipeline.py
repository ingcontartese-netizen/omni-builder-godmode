from __future__ import annotations

import copy
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
SENTRY = SCRIPTS / "sentry"
for entry in (str(SCRIPTS), str(SENTRY), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import knowledge_pipeline as pipeline  # noqa: E402
import io_safe as io_safe_module  # noqa: E402
from emit_state import emit  # noqa: E402
from io_safe import (  # noqa: E402
    create_once_bytes,
    recover_create_once_orphans,
    sha256_bytes,
)
from test_governance_scripts import guided_state  # noqa: E402
from test_l3_schema_mutants import (  # noqa: E402
    CREATED_AT,
    authority_record,
    deep_plan_record,
    light_map_record,
    metadata_attestation,
    source_manifest_record,
    web_research_receipt,
    web_source,
)


SHA_A = "A" * 64


def write_bytes(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return pipeline._binding(path, payload)


def write_record(path: Path, record: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    sealed = pipeline.seal(record)
    payload = (json.dumps(sealed, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_bytes(path, payload)
    return sealed, pipeline._binding(path, payload)


def load_record(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class L3Harness:
    """Physical dual-lane harness that exercises the public command parser."""

    def __init__(self) -> None:
        draft = guided_state(topology="TEAM_DUAL_LANE", run_kind="REAL")
        self.project = Path(draft["workspace_access_envelope"]["project_root"])
        self.fixture_root = self.project.parents[1]
        self.source_root = Path(draft["workspace_access_envelope"]["source_roots"][0])
        self.well = self.project / "owned-lanes"
        self.lanes = {
            role: Path(draft["session_pair"][role.lower()]["write_lane"])
            for role in pipeline.ROLES
        }
        self.intake_path = self.project / "INTAKE_READY.json"
        self.intake = emit(draft, self.intake_path)
        self.intake_binding = pipeline._binding(self.intake_path)
        self.pipeline_id = "PIPE-L3-E2E"
        self.sequence = 0
        self.current_path: Path | None = None
        self.current: dict[str, object] | None = None
        self.lane_data: dict[str, dict[str, object]] = {}

        self.network_source = write_bytes(
            self.project / "authorities" / "network-source.txt",
            b"PM authorizes one bounded network evidence transition.",
        )
        self.download_source = write_bytes(
            self.project / "authorities" / "download-source.txt",
            b"No raw download is authorized in this fixture.",
        )
        self.access: dict[str, dict[str, object]] = {}
        self.access_paths: dict[str, Path] = {}
        self._build_access_envelopes()

    def cleanup(self) -> None:
        shutil.rmtree(self.fixture_root, ignore_errors=True)

    @property
    def state_binding(self) -> dict[str, object]:
        assert self.current_path is not None
        return pipeline._binding(self.current_path)

    def _build_access_envelopes(self) -> None:
        probe_root = self.project / ".omni" / "access-probes"
        proof = write_bytes(self.source_root / "l3-readable-proof.txt", b"read-proof")
        for role in pipeline.ROLES:
            envelope_id = f"ACCESS-L3-{role}"
            retained = write_bytes(
                probe_root / f"{role.lower()}-create-once.probe",
                f"retained-{role}".encode("utf-8"),
            )
            receipt = {
                "schema": "omni-workspace-access-probe-receipt-v1",
                "status": "CREATE_ONCE_PROBE_RETAINED",
                "receipt_id": f"PROBE-L3-{role}",
                "envelope_id": envelope_id,
                "activation_receipt_sha256": self.intake["activation_binding"]["sha256"],
                "task_id": self.intake["state_id"],
                "task_root": self.intake["workspace_access_envelope"]["task_root"],
                "project_root": str(self.project),
                "source_roots": [str(self.source_root)],
                "owned_lane_root": str(self.lanes[role]),
                "session_pair_sha256": self.intake["session_pair"]["pair_sha256"],
                "capabilities": list(pipeline.WORKSPACE_GRANTS),
                "probe_path": retained["path"],
                "probe_bytes": retained["bytes"],
                "probe_sha256": retained["sha256"],
                "create_once": True,
                "overwritten": False,
                "retained": True,
                "read_proofs": [proof],
            }
            _, receipt_binding = write_record(
                probe_root / f"{role.lower()}-access.receipt.json", receipt
            )
            envelope = {
                "schema": "omni-workspace-access-envelope-v1",
                "status": "ACCESS_READY",
                "outcome": "ACCESS_GRANTED_NON_DESTRUCTIVE",
                "envelope_id": envelope_id,
                "activation_receipt_sha256": self.intake["activation_binding"]["sha256"],
                "task_id": self.intake["state_id"],
                "task_root": self.intake["workspace_access_envelope"]["task_root"],
                "project_root": str(self.project),
                "source_roots": [str(self.source_root)],
                "owned_lane_root": str(self.lanes[role]),
                "session_pair_sha256": self.intake["session_pair"]["pair_sha256"],
                "run_kind": "REAL",
                "requested_capabilities": list(pipeline.WORKSPACE_GRANTS),
                "granted_capabilities": list(pipeline.WORKSPACE_GRANTS),
                "non_grants": list(pipeline.NON_GRANTS),
                "separate_authorizations_required": ["NETWORK_RESEARCH", "DOWNLOAD"],
                "excluded_paths": [str(self.project / "preexisting-user-files")],
                "probe_receipt_binding": receipt_binding,
            }
            path = self.project / "access" / f"{role.lower()}-access.json"
            sealed, binding = write_record(path, envelope)
            self.access[role] = binding
            self.access_paths[role] = path
            self.access[f"{role}_RECORD"] = sealed

    def invoke(self, argv: list[str], *, expect: str = "PASS") -> dict[str, object]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            exit_code = pipeline.main(argv)
        result = json.loads(stream.getvalue().strip().splitlines()[-1])
        self.last_exit_code = exit_code
        if result["status"] != expect:
            raise AssertionError(f"{argv[0]}: expected {expect}, observed {result}")
        return result

    def _state_output(self, phase: str) -> Path:
        assert self.current is not None
        return (
            self.well
            / "control"
            / "states"
            / f"{self.current['generation'] + 1:06d}_{phase}.json"
        )

    def _reservation_outputs(self, previous: dict[str, object], nonce: str) -> tuple[Path, Path]:
        return (
            self.well / "control" / "transactions" / f"{previous['sha256']}.json",
            self.well / "control" / "nonces" / f"{nonce}.json",
        )

    def authority(
        self,
        *,
        action: str,
        role: str,
        inputs: list[dict[str, object]],
        outputs: list[Path],
        previous: dict[str, object],
    ) -> tuple[Path, dict[str, object], str]:
        self.sequence += 1
        nonce = f"NONCE-L3-{self.sequence:03d}"
        transaction_path, nonce_path = self._reservation_outputs(previous, nonce)
        all_outputs = [*outputs, transaction_path, nonce_path]
        record = authority_record()
        task_id = self.intake["state_id"] if self.current is None else self.current["task_id"]
        pair_sha = self.intake["session_pair"]["pair_sha256"]
        session_id = self.intake["session_pair"][role.lower()]["session_id"]
        web = action in pipeline.WEB_ACTIONS
        deep = action in pipeline.DOWNLOAD_ACTIONS
        record.update(
            {
                "authority_id": f"AUTH-L3-{self.sequence:03d}",
                "action": action,
                "task_id": task_id,
                "pipeline_id": self.pipeline_id,
                "intake_state_sha256": self.intake_binding["sha256"],
                "session_pair_sha256": pair_sha,
                "subject_role": role,
                "subject_session_id": session_id,
                "workspace_access_envelope_binding": self.access[role],
                "well_root": str(self.well),
                "input_bindings": copy.deepcopy(inputs),
                "output_paths": list(dict.fromkeys(str(item) for item in all_outputs)),
                "network_research": {
                    "effect": "NETWORK_RESEARCH",
                    "status": "AUTHORIZED" if web else "NOT_APPLICABLE",
                    "authority_source_binding": self.network_source,
                    "scope_paths": [str(self.well)],
                    "handling_policy": "CAPTURE_MD_ONLY" if web else "NOT_APPLICABLE",
                },
                "download": {
                    "effect": "DOWNLOAD",
                    "status": "DENIED" if deep else "NOT_APPLICABLE",
                    "authority_source_binding": self.download_source,
                    "scope_paths": [str(self.well)],
                    "handling_policy": "NO_RAW_DOWNLOAD",
                },
                "one_shot": True,
                "operation_nonce": nonce,
                "non_grants": list(pipeline.NON_GRANTS),
                "created_at": CREATED_AT,
            }
        )
        path = self.project / "authorities" / f"{self.sequence:03d}-{action}.json"
        _, binding = write_record(path, record)
        return path, binding, nonce

    def _common_cli(
        self, command: str, role: str | None, authority_path: Path, extras: list[str]
    ) -> list[str]:
        assert self.current_path is not None
        args = [
            command,
            "--state",
            str(self.current_path),
            "--state-sha256",
            str(self.state_binding["sha256"]),
            "--authority",
            str(authority_path),
            "--authority-sha256",
            str(pipeline._binding(authority_path)["sha256"]),
        ]
        if role is not None:
            args.extend(["--role", role])
        return [*args, *extras]

    def expected_inputs(
        self, command: str, role: str, extras: list[str]
    ) -> list[dict[str, object]]:
        dummy = self._common_cli(command, role if command in {
            "bind-light-map",
            "freeze-deep-plan",
            "start-deep-research",
            "bind-deep-dossier",
            "freeze-lane",
        } else None, self.project / "authorities" / "network-source.txt", extras)
        parsed = pipeline.build_parser().parse_args(dummy)
        assert self.current is not None
        return pipeline._expected_command_inputs(
            parsed, command, self.current, self.state_binding, role
        )

    def transition(
        self,
        command: str,
        *,
        role: str,
        phase: str,
        extras: list[str],
        side_outputs: list[Path],
        inputs: list[dict[str, object]] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        assert self.current is not None
        inputs = inputs or self.expected_inputs(command, role, extras)
        state_output = self._state_output(phase)
        authority_path, authority_binding, _ = self.authority(
            action=pipeline.AUTHORITY_ACTIONS[command],
            role=role,
            inputs=inputs,
            outputs=[*side_outputs, state_output],
            previous=self.state_binding,
        )
        role_arg = role if command in {
            "bind-light-map",
            "freeze-deep-plan",
            "start-deep-research",
            "bind-deep-dossier",
            "freeze-lane",
        } else None
        result = self.invoke(self._common_cli(command, role_arg, authority_path, extras))
        self.current_path = Path(result["output_binding"]["path"])
        self.current = load_record(self.current_path)
        return result, authority_binding

    def init_only(self) -> None:
        output = self.well / "control" / "states" / "000001_WELL_BOOTSTRAPPING.json"
        tx, nonce_path = self._reservation_outputs(self.intake_binding, "NONCE-L3-001")
        # `authority` chooses the same first nonce and adds transaction/nonce paths.
        authority_path, _, _ = self.authority(
            action=pipeline.AUTHORITY_ACTIONS["init"],
            role="BUILDER",
            inputs=[self.intake_binding, self.access["BUILDER"], self.access["VERIFIER"]],
            outputs=[output],
            previous=self.intake_binding,
        )
        del tx, nonce_path
        result = self.invoke(
            [
                "init",
                "--intake",
                str(self.intake_path),
                "--intake-sha256",
                str(self.intake_binding["sha256"]),
                "--builder-access",
                str(self.access_paths["BUILDER"]),
                "--builder-access-sha256",
                str(self.access["BUILDER"]["sha256"]),
                "--verifier-access",
                str(self.access_paths["VERIFIER"]),
                "--verifier-access-sha256",
                str(self.access["VERIFIER"]["sha256"]),
                "--authority",
                str(authority_path),
                "--authority-sha256",
                str(pipeline._binding(authority_path)["sha256"]),
                "--pipeline-id",
                self.pipeline_id,
                "--well-root",
                str(self.well),
            ]
        )
        self.current_path = Path(result["output_binding"]["path"])
        self.current = load_record(self.current_path)

    def init_and_bootstrap(self) -> None:
        self.init_only()
        descriptor = self.well / "control" / "WELL_DESCRIPTOR.json"
        self.transition(
            "bootstrap-well",
            role="BUILDER",
            phase="WELL_READY",
            extras=[],
            side_outputs=[descriptor],
        )

    def _evidence_receipt(
        self, kind: str, decision: str, subject: dict[str, object]
    ) -> dict[str, object]:
        record = {
            "schema": "omni-independent-evidence-receipt-v1",
            "status": "EVIDENCE_ATTESTED",
            "receipt_id": f"EVIDENCE-{kind}-1",
            "evidence_kind": kind,
            "decision": decision,
            "subject_binding": subject,
            "issuer_role": "VERIFIER",
            "issuer_session_id": self.intake["session_pair"]["verifier"]["session_id"],
            "tool_name": f"independent-{kind.lower()}-probe",
            "tool_version": "1.0.0",
            "created_at": CREATED_AT,
        }
        _, binding = write_record(
            self.source_root / "evidence" / f"{kind.lower()}.receipt.json", record
        )
        return binding

    def quarantine_and_join(self) -> None:
        assert self.current is not None
        material = self.source_root / "user-material.txt"
        source_binding = write_bytes(material, b"User supplied durable source material.\n")
        statuses = {
            "RIGHTS": "AUTHORIZED",
            "PRIVACY": "APPROVED",
            "ACL": "WITHIN_ENVELOPE",
            "SCAN": "PASS",
            "PARSE": "PASS",
        }
        receipts = {
            kind: self._evidence_receipt(kind, decision, source_binding)
            for kind, decision in statuses.items()
        }
        metadata = metadata_attestation(True)
        metadata.update(
            {
                "attestation_id": "ATTEST-L3-1",
                "pipeline_id": self.pipeline_id,
                "task_id": self.current["task_id"],
                "session_pair_sha256": self.current["session_pair_sha256"],
                "subject_source_binding": source_binding,
                "issuer_role": "BUILDER",
                "issuer_session_id": self.current["lanes"]["BUILDER"]["session_id"],
                "rights_status": statuses["RIGHTS"],
                "rights_evidence_binding": receipts["RIGHTS"],
                "privacy_status": statuses["PRIVACY"],
                "privacy_evidence_binding": receipts["PRIVACY"],
                "acl_status": statuses["ACL"],
                "acl_evidence_binding": receipts["ACL"],
                "scan_status": statuses["SCAN"],
                "scan_receipt_binding": receipts["SCAN"],
                "parse_status": statuses["PARSE"],
                "parse_receipt_binding": receipts["PARSE"],
                "admission_recommendation": "ELIGIBLE",
                "rejection_reason_codes": [],
            }
        )
        metadata_path = self.source_root / "material-metadata.json"
        _, metadata_binding = write_record(metadata_path, metadata)
        digest = str(source_binding["sha256"])
        quarantine = self.well / "material" / "quarantine" / f"{digest}.bin"
        quarantined_manifest = (
            self.well / "control" / "material" / "MATERIAL_QUARANTINED.json"
        )
        extras = [
            "--material",
            str(material),
            "--material-metadata",
            str(metadata_path),
        ]
        self.transition(
            "quarantine-material",
            role="BUILDER",
            phase="MATERIAL_QUARANTINE",
            extras=extras,
            side_outputs=[quarantine, quarantined_manifest],
        )
        joined_manifest = self.well / "control" / "material" / "MATERIAL_JOINED.json"
        self.transition(
            "join-material",
            role="BUILDER",
            phase="MATERIAL_JOINED",
            extras=[],
            side_outputs=[joined_manifest],
        )
        self.material_path = material
        self.metadata_path = metadata_path
        self.metadata_binding = metadata_binding

    def _capture(self, role: str, name: str, text: str) -> dict[str, object]:
        return write_bytes(
            self.lanes[role] / "captures" / f"{name}.md", text.encode("utf-8")
        )

    def run_lane(self, role: str) -> None:
        assert self.current is not None
        prefix = "B" if role == "BUILDER" else "V"
        session_id = self.current["lanes"][role]["session_id"]
        lane_root = self.lanes[role]
        light_id = f"{prefix}-LIGHT-1"
        deep_id = f"{prefix}-DEEP-1"
        query_light = self._capture(role, "light-query", f"query results for {role}\n")
        capture_light = self._capture(role, "light-source", f"light source for {role}\n")
        light_source = web_source(light_id, "LIGHT_WEB", "CAPTURE_MD_ONLY")
        light_source.update(
            {
                "locator": f"https://example.test/{role.lower()}/light",
                "capture_binding": capture_light,
            }
        )
        light_inputs = [
            self.state_binding,
            self.current["material"]["manifest_binding"],
            query_light,
            capture_light,
        ]
        light_state_output = self._state_output("LANES_ACTIVE")
        light_authority_path, light_authority_binding, _ = self.authority(
            action=pipeline.AUTHORITY_ACTIONS["bind-light-map"],
            role=role,
            inputs=light_inputs,
            outputs=[light_state_output],
            previous=self.state_binding,
        )
        light = light_map_record()
        light.update(
            {
                "map_id": f"{prefix}-LIGHT-MAP",
                "pipeline_id": self.pipeline_id,
                "task_id": self.current["task_id"],
                "session_pair_sha256": self.current["session_pair_sha256"],
                "role": role,
                "session_id": session_id,
                "lane_root": str(lane_root),
                "material_join_binding": self.current["material"]["manifest_binding"],
                "effect_authority_binding": light_authority_binding,
                "query_events": [
                    {
                        "query_id": f"{prefix}-QUERY-LIGHT-1",
                        "query_text": "current primary guidance",
                        "executed_at": CREATED_AT,
                        "tool": "official-search",
                        "result_capture_binding": query_light,
                        "returned_source_ids": [light_id],
                    }
                ],
                "sources": [light_source],
                "light_source_ids": [light_id],
                "topic_clusters": [
                    {
                        "cluster_id": f"{prefix}-CLUSTER-1",
                        "label": "Primary",
                        "source_ids": [light_id],
                    }
                ],
                "priority_source_ids": [light_id],
                "gaps": ["One distinct deep source is required"],
            }
        )
        light_path = lane_root / "LIGHT_MAP.json"
        _, light_binding = write_record(light_path, light)
        result = self.invoke(
            self._common_cli(
                "bind-light-map",
                role,
                light_authority_path,
                ["--artifact", str(light_path), "--artifact-sha256", str(light_binding["sha256"])],
            )
        )
        self.current_path = Path(result["output_binding"]["path"])
        self.current = load_record(self.current_path)

        plan = deep_plan_record()
        plan.update(
            {
                "plan_id": f"{prefix}-DEEP-PLAN",
                "pipeline_id": self.pipeline_id,
                "task_id": self.current["task_id"],
                "session_pair_sha256": self.current["session_pair_sha256"],
                "role": role,
                "session_id": session_id,
                "lane_root": str(lane_root),
                "light_map_binding": self.current["lanes"][role]["artifacts"]["light_map"],
                "light_source_ids": [light_id],
            }
        )
        plan_path = lane_root / "DEEP_PLAN.json"
        _, plan_binding = write_record(plan_path, plan)
        plan_extras = ["--artifact", str(plan_path), "--artifact-sha256", str(plan_binding["sha256"])]
        self.transition(
            "freeze-deep-plan",
            role=role,
            phase="LANES_ACTIVE",
            extras=plan_extras,
            side_outputs=[],
        )

        query_deep = self._capture(role, "deep-query", f"deep query results for {role}\n")
        capture_deep = self._capture(role, "deep-source", f"deep source for {role}\n")
        deep_source = web_source(deep_id, "DEEP_WEB", "CAPTURE_MD_ONLY")
        deep_source.update(
            {
                "locator": f"https://example.test/{role.lower()}/deep",
                "capture_binding": capture_deep,
            }
        )
        deep_inputs = [
            self.state_binding,
            self.current["lanes"][role]["artifacts"]["light_map"],
            self.current["lanes"][role]["artifacts"]["deep_plan"],
            query_deep,
            capture_deep,
        ]
        deep_state_output = self._state_output("LANES_ACTIVE")
        deep_authority_path, deep_authority_binding, _ = self.authority(
            action=pipeline.AUTHORITY_ACTIONS["start-deep-research"],
            role=role,
            inputs=deep_inputs,
            outputs=[deep_state_output],
            previous=self.state_binding,
        )
        receipt = web_research_receipt()
        receipt.update(
            {
                "receipt_id": f"{prefix}-WEB-RECEIPT",
                "pipeline_id": self.pipeline_id,
                "task_id": self.current["task_id"],
                "session_pair_sha256": self.current["session_pair_sha256"],
                "role": role,
                "session_id": session_id,
                "lane_root": str(lane_root),
                "light_map_binding": self.current["lanes"][role]["artifacts"]["light_map"],
                "deep_plan_binding": self.current["lanes"][role]["artifacts"]["deep_plan"],
                "effect_authority_binding": deep_authority_binding,
                "query_events": [
                    {
                        "query_id": f"{prefix}-QUERY-DEEP-1",
                        "query_text": "distinct current primary source",
                        "executed_at": CREATED_AT,
                        "tool": "official-search",
                        "result_capture_binding": query_deep,
                        "returned_source_ids": [deep_id],
                    }
                ],
                "sources": [deep_source],
                "light_source_ids": [light_id],
                "deep_source_ids": [deep_id],
                "deep_new_source_ids": [deep_id],
                "download_performed": False,
                "download_authority_binding": None,
                "acquisitions": [],
            }
        )
        receipt_path = lane_root / "DEEP_RESEARCH_RECEIPT.json"
        _, receipt_binding = write_record(receipt_path, receipt)
        result = self.invoke(
            self._common_cli(
                "start-deep-research",
                role,
                deep_authority_path,
                [
                    "--artifact",
                    str(receipt_path),
                    "--artifact-sha256",
                    str(receipt_binding["sha256"]),
                ],
            )
        )
        self.current_path = Path(result["output_binding"]["path"])
        self.current = load_record(self.current_path)

        material_manifest = load_record(Path(self.current["material"]["manifest_binding"]["path"]))
        item = next(
            entry for entry in material_manifest["items"] if entry["admission"] == "JOINED"
        )
        material_source = {
            "source_id": item["item_id"],
            "research_phase": "USER_MATERIAL",
            "locator": str(item["source_binding"]["path"]),
            "title": "User material",
            "publisher": "User",
            "accessed_at": CREATED_AT,
            "capture_mode": "USER_PROVIDED",
            "capture_binding": item["quarantine_binding"],
            "sections_consulted": ["complete file"],
        }
        source_manifest = source_manifest_record()
        source_manifest.update(
            {
                "manifest_id": f"{prefix}-SOURCE-MANIFEST",
                "pipeline_id": self.pipeline_id,
                "task_id": self.current["task_id"],
                "session_pair_sha256": self.current["session_pair_sha256"],
                "role": role,
                "session_id": session_id,
                "lane_root": str(lane_root),
                "material_join_binding": self.current["material"]["manifest_binding"],
                "light_map_binding": self.current["lanes"][role]["artifacts"]["light_map"],
                "deep_plan_binding": self.current["lanes"][role]["artifacts"]["deep_plan"],
                "deep_research_receipt_binding": self.current["lanes"][role]["artifacts"]["deep_research_receipt"],
                "material_source_ids": [item["item_id"]],
                "light_source_ids": [light_id],
                "deep_source_ids": [deep_id],
                "deep_new_source_ids": [deep_id],
                "sources": [material_source, light_source, deep_source],
                "findings": [
                    {
                        "finding_id": f"{prefix}-FINDING-1",
                        "statement": f"Independent {role.lower()} finding.",
                        "source_ids": [deep_id],
                        "confidence": "HIGH",
                        "freshness": "CURRENT_PRIMARY",
                    }
                ],
                "conflicts": [],
                "dissent": [],
                "provenance": [
                    {
                        "provenance_id": f"{prefix}-PROV-1",
                        "sources_actually_read": [deep_id],
                        "version_hash_access_date": ["v1 / sha256 / 2026-07-30"],
                        "sections_consulted": ["section 1"],
                        "received_material_not_used": [],
                        "facts_extracted": ["one fact"],
                        "model_synthesis_or_inference": ["one inference"],
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
            }
        )
        source_path = lane_root / "SOURCE_MANIFEST.json"
        _, source_binding = write_record(source_path, source_manifest)
        dossier_path = lane_root / "DEEP_DOSSIER.md"
        dossier_binding = write_bytes(
            dossier_path,
            f"# {role} dossier\n\nByte-bound independent synthesis.\n".encode("utf-8"),
        )
        dossier_extras = [
            "--artifact",
            str(dossier_path),
            "--artifact-sha256",
            str(dossier_binding["sha256"]),
            "--source-manifest",
            str(source_path),
            "--source-manifest-sha256",
            str(source_binding["sha256"]),
        ]
        self.transition(
            "bind-deep-dossier",
            role=role,
            phase="LANES_ACTIVE",
            extras=dossier_extras,
            side_outputs=[],
        )
        manifest_path = lane_root / "LANE_KNOWLEDGE_MANIFEST.json"
        phase = (
            "LANES_FROZEN"
            if any(
                lane["state"] == "LANE_FROZEN"
                for other, lane in self.current["lanes"].items()
                if other != role
            )
            else "LANES_ACTIVE"
        )
        self.transition(
            "freeze-lane",
            role=role,
            phase=phase,
            extras=[],
            side_outputs=[manifest_path],
        )
        self.lane_data[role] = {
            "light_source": light_source,
            "deep_source": deep_source,
            "finding_id": f"{prefix}-FINDING-1",
        }

    def fuse(self) -> None:
        assert self.current is not None
        decisions = {
            "schema": "omni-fusion-decision-register-v1",
            "status": "FUSION_DECISIONS_FROZEN",
            "pipeline_id": self.pipeline_id,
            "decisions": [
                {
                    "decision_id": "DECISION-BUILDER",
                    "outcome": "MERGED",
                    "rationale": "Builder evidence retained losslessly.",
                    "finding_ids": [self.lane_data["BUILDER"]["finding_id"]],
                    "dissent_ids": [],
                },
                {
                    "decision_id": "DECISION-VERIFIER",
                    "outcome": "MERGED",
                    "rationale": "Verifier evidence retained losslessly.",
                    "finding_ids": [self.lane_data["VERIFIER"]["finding_id"]],
                    "dissent_ids": [],
                },
            ],
            "created_at": CREATED_AT,
        }
        decision_path = self.lanes["BUILDER"] / "FUSION_DECISIONS.json"
        _, decision_binding = write_record(decision_path, decisions)
        canonical_path = self.well / "knowledge" / "CONOSCENZA_FUSA_CANONICA.md"
        candidate_path = self.well / "control" / "fusion" / "FUSION_CANDIDATE.json"
        extras = [
            "--decision-register",
            str(decision_path),
            "--decision-register-sha256",
            str(decision_binding["sha256"]),
        ]
        self.transition(
            "emit-fusion",
            role="BUILDER",
            phase="FUSION_EMITTED",
            extras=extras,
            side_outputs=[canonical_path, candidate_path],
        )
        receipt_path = self.lanes["VERIFIER"] / "KNOWLEDGE_FUSION_COUNTERSIGN.json"
        self.transition(
            "countersign-fusion",
            role="VERIFIER",
            phase="KNOWLEDGE_FUSION_PASS",
            extras=[],
            side_outputs=[receipt_path],
        )


class L3KnowledgePipelineE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = L3Harness()
        self.addCleanup(self.harness.cleanup)

    def test_full_dual_lane_e2e_reaches_fusion_pass_and_chain_verifies(self) -> None:
        h = self.harness
        h.init_and_bootstrap()
        h.quarantine_and_join()
        h.run_lane("BUILDER")
        h.run_lane("VERIFIER")
        self.assertEqual(h.current["phase"], "LANES_FROZEN")
        h.fuse()
        self.assertEqual(h.current["phase"], "KNOWLEDGE_FUSION_PASS")
        self.assertEqual(h.current["status"], "PASS")
        self.assertEqual(h.current["generation"], 16)
        self.assertEqual(h.current["lanes"]["BUILDER"]["state"], "LANE_FROZEN")
        self.assertEqual(h.current["lanes"]["VERIFIER"]["state"], "LANE_FROZEN")
        self.assertEqual(len(h.current["evidence_bindings"]), 5)
        result = h.invoke(
            [
                "verify",
                "--state",
                str(h.current_path),
                "--state-sha256",
                str(h.state_binding["sha256"]),
                "--expect",
                "KNOWLEDGE_FUSION_PASS",
            ]
        )
        self.assertEqual(result["phase"], "KNOWLEDGE_FUSION_PASS")
        canonical = Path(h.current["fusion"]["canonical_binding"]["path"])
        rendered = canonical.read_text(encoding="utf-8")
        self.assertIn("B-FINDING-1", rendered)
        self.assertIn("V-FINDING-1", rendered)

    def test_invalid_preflight_does_not_burn_authority_and_normal_replay_blocks(self) -> None:
        h = self.harness
        h.init_and_bootstrap()
        state_binding = h.state_binding
        manifest_path = h.well / "control" / "material" / "MATERIAL_QUARANTINED.json"
        state_output = h._state_output("MATERIAL_QUARANTINE")
        authority_path, _, nonce = h.authority(
            action=pipeline.AUTHORITY_ACTIONS["quarantine-material"],
            role="BUILDER",
            inputs=[state_binding],
            outputs=[manifest_path, state_output],
            previous=state_binding,
        )
        base = h._common_cli("quarantine-material", None, authority_path, [])
        blocked = h.invoke(base, expect="BLOCKED")
        self.assertEqual(blocked["reason_code"], "MATERIAL_DECLARATION_REQUIRED")
        transaction, nonce_path = h._reservation_outputs(state_binding, nonce)
        self.assertFalse(transaction.exists())
        self.assertFalse(nonce_path.exists())

        passed = h.invoke([*base, "--no-user-material"])
        self.assertEqual(passed["phase"], "MATERIAL_QUARANTINE")
        self.assertTrue(transaction.exists())
        self.assertTrue(nonce_path.exists())
        replay = h.invoke([*base, "--no-user-material"], expect="BLOCKED")
        self.assertEqual(
            replay["reason_code"], "KNOWLEDGE_EFFECT_AUTHORITY_NONCE_REPLAY"
        )

    def test_divergent_descriptor_collision_blocks_before_reservation(self) -> None:
        h = self.harness
        h.init_only()
        descriptor = h.well / "control" / "WELL_DESCRIPTOR.json"
        write_bytes(descriptor, b"poison-descriptor\n")
        state_output = h._state_output("WELL_READY")
        previous = h.state_binding
        authority_path, _, nonce = h.authority(
            action=pipeline.AUTHORITY_ACTIONS["bootstrap-well"],
            role="BUILDER",
            inputs=[previous],
            outputs=[descriptor, state_output],
            previous=previous,
        )
        blocked = h.invoke(
            h._common_cli("bootstrap-well", None, authority_path, []),
            expect="BLOCKED",
        )
        self.assertEqual(blocked["reason_code"], "CREATE_ONCE_COLLISION")
        transaction, nonce_path = h._reservation_outputs(previous, nonce)
        self.assertFalse(transaction.exists())
        self.assertFalse(nonce_path.exists())
        self.assertFalse(state_output.exists())
        self.assertEqual(h.current["generation"], 1)

    def test_preexisting_next_state_blocks_before_reservation_or_side_effect(self) -> None:
        h = self.harness
        h.init_only()
        descriptor = h.well / "control" / "WELL_DESCRIPTOR.json"
        state_output = h._state_output("WELL_READY")
        write_bytes(state_output, b"poison-state\n")
        previous = h.state_binding
        authority_path, _, nonce = h.authority(
            action=pipeline.AUTHORITY_ACTIONS["bootstrap-well"],
            role="BUILDER",
            inputs=[previous],
            outputs=[descriptor, state_output],
            previous=previous,
        )
        blocked = h.invoke(
            h._common_cli("bootstrap-well", None, authority_path, []),
            expect="BLOCKED",
        )
        self.assertEqual(blocked["reason_code"], "CREATE_ONCE_COLLISION")
        transaction, nonce_path = h._reservation_outputs(previous, nonce)
        self.assertFalse(transaction.exists())
        self.assertFalse(nonce_path.exists())
        self.assertFalse(descriptor.exists())
        self.assertEqual(state_output.read_bytes(), b"poison-state\n")
        self.assertEqual(h.current["generation"], 1)

    def test_nested_lane_topology_blocks_before_authority_or_generation_claim(self) -> None:
        h = self.harness
        builder_lane = h.well / "nested-builder"
        verifier_lane = builder_lane / "verifier"
        verifier_lane.mkdir(parents=True)
        access_results = [
            {
                "envelope_id": "ACCESS-NESTED-BUILDER",
                "project_root": h.project,
                "source_roots": [h.source_root],
                "lane_root": builder_lane,
                "receipt_path": h.project / "unused-builder.receipt.json",
            },
            {
                "envelope_id": "ACCESS-NESTED-VERIFIER",
                "project_root": h.project,
                "source_roots": [h.source_root],
                "lane_root": verifier_lane,
                "receipt_path": h.project / "unused-verifier.receipt.json",
            },
        ]
        authority_binding = pipeline._binding(
            Path(h.network_source["path"])
        )
        output = (
            h.well
            / "control"
            / "states"
            / "000001_WELL_BOOTSTRAPPING.json"
        )
        argv = [
            "init",
            "--intake",
            str(h.intake_path),
            "--intake-sha256",
            str(h.intake_binding["sha256"]),
            "--builder-access",
            str(h.access_paths["BUILDER"]),
            "--builder-access-sha256",
            str(h.access["BUILDER"]["sha256"]),
            "--verifier-access",
            str(h.access_paths["VERIFIER"]),
            "--verifier-access-sha256",
            str(h.access["VERIFIER"]["sha256"]),
            "--authority",
            str(authority_binding["path"]),
            "--authority-sha256",
            str(authority_binding["sha256"]),
            "--pipeline-id",
            h.pipeline_id,
            "--well-root",
            str(h.well),
        ]
        with mock.patch.object(
            pipeline,
            "_validate_access_envelope",
            side_effect=access_results,
        ):
            blocked = h.invoke(argv, expect="BLOCKED")
        self.assertEqual(blocked["reason_code"], "LANE_ROOTS_OVERLAP")
        self.assertFalse(output.exists())
        self.assertFalse((h.well / "control" / "transactions").exists())
        self.assertFalse((h.well / "control" / "nonces").exists())

    def test_material_receipts_must_be_content_bound_and_independent(self) -> None:
        h = self.harness
        h.init_and_bootstrap()
        material = h.source_root / "bad-evidence-material.txt"
        source_binding = write_bytes(material, b"content")
        receipt_bindings = {
            kind: h._evidence_receipt(kind, decision, source_binding)
            for kind, decision in {
                "RIGHTS": "AUTHORIZED",
                "PRIVACY": "APPROVED",
                "ACL": "WITHIN_ENVELOPE",
                "SCAN": "PASS",
                "PARSE": "PASS",
            }.items()
        }
        bad = metadata_attestation(True)
        bad.update(
            {
                "attestation_id": "ATTEST-BAD-INDEPENDENCE",
                "pipeline_id": h.pipeline_id,
                "task_id": h.current["task_id"],
                "session_pair_sha256": h.current["session_pair_sha256"],
                "subject_source_binding": source_binding,
                "issuer_session_id": h.current["lanes"]["BUILDER"]["session_id"],
                "rights_evidence_binding": receipt_bindings["RIGHTS"],
                "privacy_evidence_binding": receipt_bindings["PRIVACY"],
                "acl_evidence_binding": receipt_bindings["ACL"],
                "scan_receipt_binding": receipt_bindings["SCAN"],
                "parse_receipt_binding": receipt_bindings["PARSE"],
            }
        )
        bad_receipt_path = Path(receipt_bindings["SCAN"]["path"])
        bad_receipt = load_record(bad_receipt_path)
        bad_receipt["issuer_role"] = "VERIFIER"
        bad_receipt["issuer_session_id"] = h.current["lanes"]["BUILDER"]["session_id"]
        write_record(bad_receipt_path, bad_receipt)
        bad["scan_receipt_binding"] = pipeline._binding(bad_receipt_path)
        metadata_path = h.source_root / "bad-independence-metadata.json"
        write_record(metadata_path, bad)
        with self.assertRaisesRegex(
            pipeline.KnowledgePipelineError, "MATERIAL_ATTESTATION_UNBOUND"
        ):
            pipeline._metadata(
                metadata_path, [h.source_root], h.current, source_binding
            )


class L3ReservationAndIOTests(unittest.TestCase):
    def test_explicit_crash_recovery_requires_exact_transaction_and_nonce_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            well = root / "well"
            well.mkdir()
            previous_path = root / "previous.json"
            previous = write_bytes(previous_path, b"previous")
            authority_path = root / "authority.json"
            authority_binding = write_bytes(authority_path, b"authority")
            nonce = "CRASH-NONCE-1"
            transaction_path = (
                well / "control" / "transactions" / f"{previous['sha256']}.json"
            )
            nonce_path = well / "control" / "nonces" / f"{nonce}.json"
            authority = {
                "operation_nonce": nonce,
                "created_at": CREATED_AT,
                "output_paths": [str(transaction_path), str(nonce_path)],
            }
            original = pipeline.create_once_bytes_bound

            def crash_on_nonce(path: Path, data: bytes, allowed_root: Path) -> str:
                if Path(path) == nonce_path:
                    raise OSError("SIMULATED_NONCE_CRASH")
                return original(path, data, allowed_root)

            kwargs = {
                "previous_binding": previous,
                "authority": authority,
                "authority_binding": authority_binding,
                "action": "WELL_READY",
                "task_id": "TASK-CRASH",
                "pipeline_id": "PIPE-CRASH",
                "role": "BUILDER",
                "session_id": "SESSION-BUILDER",
                "expected_input_bindings": [previous],
                "well_root": well,
                "storage_root": root,
            }
            with mock.patch.object(
                pipeline, "create_once_bytes_bound", side_effect=crash_on_nonce
            ):
                with self.assertRaisesRegex(OSError, "SIMULATED_NONCE_CRASH"):
                    pipeline._reserve_transition(**kwargs)
            self.assertTrue(transaction_path.exists())
            self.assertFalse(nonce_path.exists())

            transaction_binding = pipeline._binding(transaction_path)
            transaction = load_record(transaction_path)
            expected_nonce = pipeline.seal(
                {
                    "schema": "omni-knowledge-effect-nonce-v1",
                    "status": "CONSUMED",
                    "owner_token": transaction["owner_token"],
                    "operation_nonce": nonce,
                    "authority_binding": authority_binding,
                    "transaction_binding": transaction_binding,
                    "action": "WELL_READY",
                    "task_id": "TASK-CRASH",
                    "pipeline_id": "PIPE-CRASH",
                    "subject_role": "BUILDER",
                    "subject_session_id": "SESSION-BUILDER",
                    "input_bindings": [previous],
                    "created_at": CREATED_AT,
                }
            )
            nonce_payload = (
                json.dumps(expected_nonce, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            recovered = pipeline._reserve_transition(
                **kwargs,
                recovery=True,
                recovery_transaction_sha256=transaction_binding["sha256"],
                recovery_nonce_sha256=sha256_bytes(nonce_payload),
            )
            self.assertTrue(recovered["recovered"])
            self.assertTrue(nonce_path.exists())
            self.assertEqual(
                pipeline._binding(nonce_path), recovered["operation_nonce_binding"]
            )

    def test_create_once_orphan_recovery_is_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "receipt.json"
            payload = b'{"status":"PASS"}\n'
            orphan = root / ".receipt.json.pending.crash-writer"
            orphan.write_bytes(payload)
            self.assertEqual(
                recover_create_once_orphans(target, payload, allowed_root=root),
                "RECOVERED",
            )
            self.assertEqual(target.read_bytes(), payload)
            self.assertFalse(orphan.exists())

            mismatching = root / ".other.json.pending.bad-writer"
            mismatching.write_bytes(b"partial")
            with self.assertRaisesRegex(RuntimeError, "ORPHAN_SIDE_EFFECT_DETECTED"):
                recover_create_once_orphans(
                    root / "other.json", b"expected", allowed_root=root
                )

    def test_sixteen_identical_writers_have_one_creator_and_no_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "shared.json"
            payload = b'{"stable":true}\n'

            def writer(_: int) -> str:
                return create_once_bytes(target, payload, allowed_root=root)

            with ThreadPoolExecutor(max_workers=16) as executor:
                statuses = list(executor.map(writer, range(16)))
            self.assertEqual(statuses.count("CREATED"), 1)
            self.assertEqual(statuses.count("ALREADY_PRESENT_IDENTICAL"), 15)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(list(root.glob(".shared.json.pending.*")), [])

    def test_divergent_cas_loser_removes_only_its_verified_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "shared.json"
            payloads = (b'{"writer":"A"}\n', b'{"writer":"BBBB"}\n')
            barrier = threading.Barrier(2)
            original_link = io_safe_module.os.link

            def synchronized_link(source: Path, destination: Path) -> None:
                barrier.wait(timeout=5)
                original_link(source, destination)

            def writer(payload: bytes) -> str:
                try:
                    return create_once_bytes(target, payload, allowed_root=root)
                except RuntimeError as error:
                    return str(error).split(":", 1)[0]

            with mock.patch.object(
                io_safe_module.os, "link", side_effect=synchronized_link
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    statuses = list(executor.map(writer, payloads))
            self.assertEqual(statuses.count("CREATED"), 1)
            self.assertEqual(statuses.count("CREATE_ONCE_COLLISION"), 1)
            self.assertIn(target.read_bytes(), payloads)
            self.assertEqual(list(root.glob(".shared.json.pending.*")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

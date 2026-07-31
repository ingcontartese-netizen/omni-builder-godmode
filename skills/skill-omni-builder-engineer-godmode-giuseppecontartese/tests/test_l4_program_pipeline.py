from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jsonschema import Draft202012Validator


os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
SENTRY = SCRIPTS / "sentry"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SENTRY))
sys.path.insert(0, str(TESTS))

import program_pipeline as pipeline
from io_safe import canonical_json, sha256_bytes
from test_governance_scripts import guided_state


CLI = SCRIPTS / "program_pipeline.py"
CREATED_AT = "2026-07-30T12:00:00+00:00"


def binding(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def write_json(path: Path, value: dict[str, object], *, do_seal: bool = True) -> tuple[dict[str, object], dict[str, object]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = pipeline.seal(value) if do_seal else copy.deepcopy(value)
    path.write_text(canonical_json(record) + "\n", encoding="utf-8")
    return record, binding(path)


class Harness:
    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="omni-l4-")
        self.root = Path(self._temporary.name).resolve()
        self.project_root = self.root / "project"
        self.well_root = self.project_root / "well"
        self.planning_root = self.well_root / "planning"
        self.builder_lane = self.planning_root / "lanes" / "builder"
        self.verifier_lane = self.planning_root / "lanes" / "verifier"
        self.sources = self.project_root / "sources"
        for directory in (
            self.well_root / "control",
            self.builder_lane,
            self.verifier_lane,
            self.sources,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.authority_counter = 0
        self.committed_drafts: dict[str, tuple[Path, dict[str, object]]] = {}
        self.program_id = "PROGRAM-001"
        self.task_id = "TASK-001"
        self.pipeline_id = "KNOW-PIPE-001"
        self._build_terminal_l3()

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> "Harness":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def dummy(self, name: str, text: str = "x\n") -> dict[str, object]:
        path = self.well_root / "control" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return binding(path)

    def _build_terminal_l3(self) -> None:
        intake_source = guided_state(topology="TEAM_DUAL_LANE", run_kind="REAL")
        intake_source["previous_record_sha256"] = None
        intake_source["created_at"] = CREATED_AT
        intake = pipeline.seal(intake_source)
        self.intake, self.intake_binding = write_json(
            self.well_root / "control" / "intake-ready.json", intake, do_seal=False
        )
        pair = self.intake["session_pair"]
        self.session_pair_sha256 = pair["pair_sha256"]

        canonical_path = self.well_root / "canonical-knowledge.md"
        canonical_path.write_text("# Canonical knowledge\n\nFrozen L3 evidence.\n", encoding="utf-8")
        self.canonical_binding = binding(canonical_path)
        builder_manifest = self.dummy("knowledge-builder-manifest.json")
        verifier_manifest = self.dummy("knowledge-verifier-manifest.json")
        decisions = self.dummy("knowledge-decisions.json")

        candidate = {
            "schema": "omni-knowledge-fusion-v1",
            "kind": "FUSION_CANDIDATE",
            "status": "FUSION_EMITTED",
            "fusion_id": "KNOW-FUSION-001",
            "pipeline_id": self.pipeline_id,
            "task_id": self.task_id,
            "session_pair_sha256": self.session_pair_sha256,
            "author_role": "BUILDER",
            "author_session_id": pair["builder"]["session_id"],
            "builder_manifest_binding": builder_manifest,
            "verifier_manifest_binding": verifier_manifest,
            "decision_register_binding": decisions,
            "canonical_knowledge_binding": self.canonical_binding,
            "finding_ids": ["KNOW-FINDING-001"],
            "dissent_ids_preserved": [],
            "countersigner_role": None,
            "countersigner_session_id": None,
            "candidate_binding": None,
            "created_at": CREATED_AT,
        }
        self.knowledge_candidate, self.knowledge_candidate_binding = write_json(
            self.well_root / "knowledge-fusion-candidate.json", candidate
        )
        countersign = copy.deepcopy(candidate)
        countersign.update(
            {
                "kind": "FUSION_COUNTERSIGN",
                "status": "KNOWLEDGE_FUSION_PASS",
                "countersigner_role": "VERIFIER",
                "countersigner_session_id": pair["verifier"]["session_id"],
                "candidate_binding": self.knowledge_candidate_binding,
            }
        )
        self.knowledge_countersign, self.knowledge_countersign_binding = write_json(
            self.well_root / "knowledge-fusion-countersign.json", countersign
        )

        material_binding = self.dummy("material-joined.json")
        access_builder = self.dummy("builder-access.json")
        access_verifier = self.dummy("verifier-access.json")
        effect_authority = self.dummy("knowledge-effect-authority.json")
        lane_bindings: dict[str, dict[str, object]] = {}
        lane_artifacts: dict[str, dict[str, object]] = {}
        for role in ("BUILDER", "VERIFIER"):
            slug = role.lower()
            lane_bindings[role] = self.dummy(f"{slug}-knowledge-manifest.json")
            lane_artifacts[role] = {
                "light_map": self.dummy(f"{slug}-light-map.md"),
                "deep_plan": self.dummy(f"{slug}-deep-plan.md"),
                "deep_research_receipt": self.dummy(f"{slug}-deep-research.json"),
                "deep_dossier": self.dummy(f"{slug}-deep-dossier.md"),
                "source_manifest": self.dummy(f"{slug}-source-manifest.json"),
                "acquisitions": [],
            }

        state = {
            "schema": "omni-knowledge-pipeline-state-v1",
            "state_id": "KNOW-STATE-001",
            "pipeline_id": self.pipeline_id,
            "generation": 9,
            "phase": "KNOWLEDGE_FUSION_PASS",
            "status": "PASS",
            "task_id": self.task_id,
            "project_root": str(self.project_root),
            "well_root": str(self.well_root),
            "intake_binding": self.intake_binding,
            "session_pair_sha256": self.session_pair_sha256,
            "session_pair": pair,
            "access_envelopes": {
                "BUILDER": access_builder,
                "VERIFIER": access_verifier,
            },
            "source_roots": [str(self.sources)],
            "material": {"state": "MATERIAL_JOINED", "manifest_binding": material_binding},
            "lanes": {
                role: {
                    "role": role,
                    "session_id": pair[role.lower()]["session_id"],
                    "lane_root": str(self.well_root / "knowledge-lanes" / role.lower()),
                    "state": "LANE_FROZEN",
                    "artifacts": lane_artifacts[role],
                    "manifest_binding": lane_bindings[role],
                }
                for role in ("BUILDER", "VERIFIER")
            },
            "fusion": {
                "state": "KNOWLEDGE_FUSION_PASS",
                "candidate_binding": self.knowledge_candidate_binding,
                "canonical_binding": self.canonical_binding,
                "countersign_binding": self.knowledge_countersign_binding,
            },
            "event": "COUNTERSIGN_FUSION",
            "actor": {
                "role": "VERIFIER",
                "session_id": pair["verifier"]["session_id"],
            },
            "effect_authority_binding": effect_authority,
            "evidence_bindings": [self.knowledge_countersign_binding],
            "blocking_reason_codes": [],
            "previous_state_binding": None,
            "created_at": CREATED_AT,
        }
        self.knowledge_state, self.knowledge_state_binding = write_json(
            self.well_root / "control" / "knowledge-terminal.json", state
        )
        self.knowledge_state_path = Path(self.knowledge_state_binding["path"])

    def cli(self, *arguments: object) -> tuple[int, dict[str, object], str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.run(
            [sys.executable, "-B", str(CLI), *(str(item) for item in arguments)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        output = process.stdout.strip().splitlines()
        if not output:
            raise AssertionError(f"CLI emitted no JSON; stderr={process.stderr!r}")
        return process.returncode, json.loads(output[-1]), process.stderr

    def authority(
        self,
        *,
        action: str,
        role: str,
        session_id: str,
        previous: dict[str, object] | None,
        inputs: list[dict[str, object]],
        outputs: list[Path],
        generation: int,
        nonce: str | None = None,
    ) -> tuple[Path, dict[str, object], dict[str, object]]:
        self.authority_counter += 1
        operation_nonce = nonce or f"NONCE-{self.authority_counter:04d}"
        nonce_path = self.planning_root / "control" / "nonces" / f"{operation_nonce}.json"
        claim_path = self.planning_root / "control" / "generation_claims" / f"GEN_{generation:04d}.json"
        authority = {
            "schema": "omni-planning-effect-authority-v1",
            "status": "PLANNING_ACTION_AUTHORIZED",
            "decision": "AUTHORIZED",
            "authority_id": f"AUTH-{self.authority_counter:04d}",
            "action": action,
            "task_id": self.task_id,
            "program_id": self.program_id,
            "knowledge_pipeline_id": self.pipeline_id,
            "knowledge_state_binding": self.knowledge_state_binding,
            "knowledge_fusion_countersign_binding": self.knowledge_countersign_binding,
            "session_pair_sha256": self.session_pair_sha256,
            "subject_role": role,
            "subject_session_id": session_id,
            "planning_root": str(self.planning_root),
            "expected_previous_state_binding": previous,
            "input_bindings": inputs,
            "output_paths": [str(path.resolve()) for path in [*outputs, nonce_path, claim_path]],
            "one_shot": True,
            "operation_nonce": operation_nonce,
            "non_grants": pipeline.NON_GRANTS,
            "created_at": CREATED_AT,
        }
        path = self.planning_root / "control" / "authorities" / f"authority-{self.authority_counter:04d}.json"
        record, record_binding = write_json(path, authority)
        return path, record, record_binding

    def init(self, *, output: Path | None = None, nonce: str | None = None) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
        output = output or self.planning_root / "states" / "state-0001.json"
        builder_session = self.knowledge_state["session_pair"]["builder"]["session_id"]
        authority_path, _, authority_binding = self.authority(
            action="INIT_PLANNING",
            role="BUILDER",
            session_id=builder_session,
            previous=None,
            inputs=[self.knowledge_state_binding],
            outputs=[output],
            generation=1,
            nonce=nonce,
        )
        code, result, stderr = self.cli(
            "init",
            "--knowledge-state", self.knowledge_state_path,
            "--knowledge-state-sha256", self.knowledge_state_binding["sha256"],
            "--authority", authority_path,
            "--authority-sha256", authority_binding["sha256"],
            "--program-id", self.program_id,
            "--planning-root", self.planning_root,
            "--output", output,
        )
        if code != 0:
            raise AssertionError((result, stderr))
        state = json.loads(output.read_text(encoding="utf-8"))
        return output, state, binding(output), result

    def work_item(
        self,
        role: str,
        work_id: str,
        *,
        ordinal: int = 1,
        depends_on: list[str] | None = None,
        origins: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        other = "VERIFIER" if role == "BUILDER" else "BUILDER"
        lane = self.builder_lane if role == "BUILDER" else self.verifier_lane
        return {
            "work_id": work_id,
            "ordinal": ordinal,
            "title": f"Bounded work {work_id}",
            "result": f"Persistent result for {work_id}",
            "persistent_artifact": {
                "path": str(lane / "artifacts" / f"{work_id}.json"),
                "create_policy": "CREATE_ONCE",
                "owner_role": role,
            },
            "owner_role": role,
            "depends_on": depends_on or [],
            "preconditions": ["KNOWLEDGE_FUSION_PASS"],
            "required_capabilities": ["WRITE_OWNED_LANE_FILES"],
            "budget": {"max_turns": 5, "max_tool_calls": 20, "max_elapsed_seconds": 3600},
            "acceptance_evidence": [
                {
                    "evidence_id": f"EVIDENCE-{work_id}",
                    "description": f"Byte-bound evidence for {work_id}",
                    "kind": "TEST_REPORT",
                }
            ],
            "verifier_role": other,
            "rollback": {"strategy": "SAFE_PARK", "steps": ["Freeze and retain the last valid bytes."]},
            "failure_states": ["BLOCKED_PENDING_HUMAN", "INCONCLUSIVE"],
            "next_gate": f"GATE-{ordinal:03d}",
            "scope": ["F3_BUILD", "F4_TEST"],
            "origin_refs": origins or [{"role": role, "work_id": work_id}],
        }

    def plan_draft(self, state: dict[str, object], role: str, *, mutation=None) -> tuple[Path, dict[str, object], dict[str, object]]:
        slug = role.lower()
        lane = state["lanes"][role]
        work_id = f"WP-{role}-001"
        draft = {
            "schema": "omni-plan-lane-draft-v1",
            "status": "PLAN_DRAFT_READY",
            "program_id": state["program_id"],
            "task_id": state["task_id"],
            "knowledge_pipeline_id": state["knowledge_pipeline_id"],
            "knowledge_state_binding": state["knowledge_state_binding"],
            "knowledge_fusion_countersign_binding": state["knowledge_fusion_countersign_binding"],
            "canonical_knowledge_binding": state["canonical_knowledge_binding"],
            "session_pair_sha256": state["session_pair_sha256"],
            "role": role,
            "session_id": lane["session_id"],
            "lane_root": lane["lane_root"],
            "peer_lane_read_before_dual_freeze": False,
            "work_items": [self.work_item(role, work_id)],
            "alternatives": [
                {
                    "alternative_id": f"ALT-{role}-001",
                    "statement": f"Alternative from {role}",
                    "rationale": "Preserve a viable independent option.",
                }
            ],
            "risks": [
                {
                    "risk_id": f"RISK-{role}-001",
                    "statement": "Evidence may be incomplete.",
                    "mitigation": "Require independent reproduction.",
                    "severity": "P1",
                }
            ],
            "dissent": [
                {
                    "dissent_id": f"DISSENT-{role}-001",
                    "statement": f"Nonblocking dissent from {role}",
                    "rationale": "Retain the alternative for audit.",
                    "status": "PRESERVED_NONBLOCKING",
                }
            ],
            "created_at": CREATED_AT,
        }
        if mutation is not None:
            mutation(draft)
        path = Path(lane["lane_root"]) / f"plan-draft-{slug}.json"
        record, record_binding = write_json(path, draft)
        return path, record, record_binding

    def commit(
        self,
        state_path: Path,
        state: dict[str, object],
        *,
        builder_mutation=None,
        verifier_mutation=None,
    ) -> tuple[Path, dict[str, object]]:
        state_binding = binding(state_path)
        builder_path, _, builder_binding = self.plan_draft(
            state, "BUILDER", mutation=builder_mutation
        )
        verifier_path, _, verifier_binding = self.plan_draft(
            state, "VERIFIER", mutation=verifier_mutation
        )
        generation = state["generation"] + 1
        output = self.planning_root / "states" / f"state-{generation:04d}.json"
        authority_path, _, authority_binding = self.authority(
            action="COMMIT_PLAN_LANES",
            role="BUILDER",
            session_id=state["session_pair"]["builder"]["session_id"],
            previous=state_binding,
            inputs=[state_binding, builder_binding, verifier_binding],
            outputs=[output],
            generation=generation,
        )
        code, result, stderr = self.cli(
            "commit-plan-lanes",
            "--state", state_path,
            "--state-sha256", state_binding["sha256"],
            "--authority", authority_path,
            "--authority-sha256", authority_binding["sha256"],
            "--output", output,
            "--builder-plan-draft", builder_path,
            "--builder-plan-draft-sha256", builder_binding["sha256"],
            "--verifier-plan-draft", verifier_path,
            "--verifier-plan-draft-sha256", verifier_binding["sha256"],
        )
        if code != 0:
            raise AssertionError((result, stderr))
        self.committed_drafts = {
            "BUILDER": (builder_path, builder_binding),
            "VERIFIER": (verifier_path, verifier_binding),
        }
        return output, json.loads(output.read_text(encoding="utf-8"))

    def freeze(
        self,
        state_path: Path,
        state: dict[str, object],
        role: str,
    ) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
        state_binding = binding(state_path)
        draft_path, draft_binding = self.committed_drafts[role]
        generation = state["generation"] + 1
        output = self.planning_root / "states" / f"state-{generation:04d}.json"
        manifest = Path(state["lanes"][role]["lane_root"]) / "plan-manifest.json"
        authority_path, _, authority_binding = self.authority(
            action="FREEZE_PLAN_LANE",
            role=role,
            session_id=state["lanes"][role]["session_id"],
            previous=state_binding,
            inputs=[state_binding, draft_binding],
            outputs=[output, manifest],
            generation=generation,
        )
        code, result, stderr = self.cli(
            "freeze-plan-lane",
            "--state", state_path,
            "--state-sha256", state_binding["sha256"],
            "--authority", authority_path,
            "--authority-sha256", authority_binding["sha256"],
            "--output", output,
            "--role", role,
            "--plan-draft", draft_path,
            "--plan-draft-sha256", draft_binding["sha256"],
            "--manifest-output", manifest,
        )
        if code != 0:
            raise AssertionError((result, stderr))
        result_state = json.loads(output.read_text(encoding="utf-8"))
        return output, result_state, binding(output), result

    def to_dual_freeze(self) -> tuple[Path, dict[str, object]]:
        path, state, _, _ = self.init()
        path, state = self.commit(path, state)
        path, state, _, _ = self.freeze(path, state, "BUILDER")
        path, state, _, _ = self.freeze(path, state, "VERIFIER")
        return path, state

    def fusion_inputs(self, state: dict[str, object], *, mutate_fused=None) -> tuple[Path, dict[str, object], Path, dict[str, object]]:
        manifests = {
            role: json.loads(Path(state["lanes"][role]["manifest_binding"]["path"]).read_text(encoding="utf-8"))
            for role in ("BUILDER", "VERIFIER")
        }
        origins = [
            {"role": role, "work_id": manifests[role]["work_items"][0]["work_id"]}
            for role in ("BUILDER", "VERIFIER")
        ]
        fused = {
            "schema": "omni-fused-program-draft-v2",
            "status": "FUSED_PLAN_DRAFT_READY",
            "program_id": state["program_id"],
            "task_id": state["task_id"],
            "knowledge_pipeline_id": state["knowledge_pipeline_id"],
            "knowledge_state_binding": state["knowledge_state_binding"],
            "knowledge_fusion_countersign_binding": state["knowledge_fusion_countersign_binding"],
            "canonical_knowledge_binding": state["canonical_knowledge_binding"],
            "session_pair_sha256": state["session_pair_sha256"],
            "topology": state["topology"],
            "profile": state["profile"],
            "run_kind": state["run_kind"],
            "work_items": [self.work_item("BUILDER", "WP-FUSED-001", origins=origins)],
            "preserved_alternative_ids": [
                item["alternative_id"]
                for role in ("BUILDER", "VERIFIER")
                for item in manifests[role]["alternatives"]
            ],
            "preserved_dissent_ids": [
                item["dissent_id"]
                for role in ("BUILDER", "VERIFIER")
                for item in manifests[role]["dissent"]
            ],
            "created_at": CREATED_AT,
        }
        if mutate_fused is not None:
            mutate_fused(fused)
        alternatives = list(fused["preserved_alternative_ids"])
        dissents = list(fused["preserved_dissent_ids"])
        decisions = {
            "schema": "omni-program-fusion-decisions-v1",
            "status": "FUSION_DECISIONS_FROZEN",
            "program_id": state["program_id"],
            "task_id": state["task_id"],
            "knowledge_pipeline_id": state["knowledge_pipeline_id"],
            "session_pair_sha256": state["session_pair_sha256"],
            "decisions": [
                {
                    "decision_id": "PROGRAM-DECISION-001",
                    "outcome": "MERGE",
                    "source_refs": origins,
                    "fused_work_ids": ["WP-FUSED-001"],
                    "alternative_ids": alternatives,
                    "dissent_ids": dissents,
                    "rationale": "Merge both independent plans while preserving origins and dissent.",
                }
            ],
            "created_at": CREATED_AT,
        }
        fused_path = self.builder_lane / "fused-plan-draft.json"
        decisions_path = self.builder_lane / "fusion-decisions.json"
        fused_record, fused_binding = write_json(fused_path, fused)
        decisions_record, decisions_binding = write_json(decisions_path, decisions)
        return fused_path, fused_binding, decisions_path, decisions_binding

    def fuse(self, state_path: Path, state: dict[str, object], *, mutate_fused=None) -> tuple[Path, dict[str, object]]:
        state_binding = binding(state_path)
        fused_path, fused_binding, decisions_path, decisions_binding = self.fusion_inputs(
            state, mutate_fused=mutate_fused
        )
        generation = state["generation"] + 1
        output = self.planning_root / "states" / f"state-{generation:04d}.json"
        candidate = self.planning_root / "program-fusion-candidate.json"
        authority_path, _, authority_binding = self.authority(
            action="FUSE_PROGRAM",
            role="BUILDER",
            session_id=state["session_pair"]["builder"]["session_id"],
            previous=state_binding,
            inputs=[state_binding, fused_binding, decisions_binding],
            outputs=[output, candidate],
            generation=generation,
        )
        code, result, stderr = self.cli(
            "emit-program-fusion",
            "--state", state_path,
            "--state-sha256", state_binding["sha256"],
            "--authority", authority_path,
            "--authority-sha256", authority_binding["sha256"],
            "--output", output,
            "--fused-plan", fused_path,
            "--fused-plan-sha256", fused_binding["sha256"],
            "--decision-register", decisions_path,
            "--decision-register-sha256", decisions_binding["sha256"],
            "--candidate-output", candidate,
        )
        if code != 0:
            raise AssertionError((result, stderr))
        return output, json.loads(output.read_text(encoding="utf-8"))

    def to_fusion(self) -> tuple[Path, dict[str, object]]:
        path, state = self.to_dual_freeze()
        return self.fuse(path, state)

    def verifier_report(self, state: dict[str, object], decision: str, *, false_accept: bool = False) -> tuple[Path, dict[str, object]]:
        reproduction = {key: True for key in pipeline.REPRODUCTION_KEYS}
        if false_accept:
            reproduction["dag_valid"] = False
        findings = [] if decision == "ACCEPTED" else [
            {"code": f"PROGRAM-{decision}-001", "detail": "Independent reproduction did not prove the candidate."}
        ]
        report = {
            "schema": "omni-program-verifier-report-v1",
            "status": "VERIFICATION_COMPLETE",
            "program_id": state["program_id"],
            "task_id": state["task_id"],
            "knowledge_pipeline_id": state["knowledge_pipeline_id"],
            "session_pair_sha256": state["session_pair_sha256"],
            "candidate_binding": state["fusion"]["candidate_binding"],
            "decision": decision,
            "reproduction": reproduction,
            "findings": findings,
            "created_at": CREATED_AT,
        }
        path = self.verifier_lane / f"verifier-report-{decision.lower()}.json"
        _, report_binding = write_json(path, report)
        return path, report_binding

    def countersign(self, state_path: Path, state: dict[str, object], decision: str = "ACCEPTED") -> tuple[Path, dict[str, object]]:
        state_binding = binding(state_path)
        report_path, report_binding = self.verifier_report(state, decision)
        generation = state["generation"] + 1
        output = self.planning_root / "states" / f"state-{generation:04d}.json"
        receipt = self.verifier_lane / "program-countersign.json"
        authority_path, _, authority_binding = self.authority(
            action="COUNTERSIGN_PROGRAM",
            role="VERIFIER",
            session_id=state["session_pair"]["verifier"]["session_id"],
            previous=state_binding,
            inputs=[state_binding, report_binding],
            outputs=[output, receipt],
            generation=generation,
        )
        code, result, stderr = self.cli(
            "countersign-program",
            "--state", state_path,
            "--state-sha256", state_binding["sha256"],
            "--authority", authority_path,
            "--authority-sha256", authority_binding["sha256"],
            "--output", output,
            "--verifier-report", report_path,
            "--verifier-report-sha256", report_binding["sha256"],
            "--receipt-output", receipt,
        )
        if code != 0:
            raise AssertionError((result, stderr))
        return output, json.loads(output.read_text(encoding="utf-8"))

    def baptize(
        self,
        state_path: Path,
        state: dict[str, object],
        *,
        corrupt_digest: bool = False,
        sovereign_override: str | None = None,
    ) -> tuple[int, dict[str, object], Path]:
        state_binding = binding(state_path)
        candidate = json.loads(Path(state["fusion"]["candidate_binding"]["path"]).read_text(encoding="utf-8"))
        countersign = json.loads(Path(state["fusion"]["countersign_binding"]["path"]).read_text(encoding="utf-8"))
        pm = {
            "schema": "omni-program-baptism-decision-v1",
            "status": "PROGRAM_BAPTISM_AUTHORIZED",
            "decision": "ACCEPTED",
            "program_id": state["program_id"],
            "task_id": state["task_id"],
            "knowledge_pipeline_id": state["knowledge_pipeline_id"],
            "session_pair_sha256": state["session_pair_sha256"],
            "program_binding": state["fusion"]["candidate_binding"],
            "program_record_digest": ("0" * 64 if corrupt_digest else candidate["record_digest"]),
            "program_countersign_binding": state["fusion"]["countersign_binding"],
            "program_countersign_record_digest": countersign["record_digest"],
            "sovereign_id": sovereign_override or state["sovereign_id"],
            "created_at": CREATED_AT,
        }
        pm_path = self.planning_root / "control" / "program-baptism-decision.json"
        _, pm_binding = write_json(pm_path, pm)
        generation = state["generation"] + 1
        output = self.planning_root / "states" / f"state-{generation:04d}.json"
        receipt = self.planning_root / "program-baptism-receipt.json"
        authority_path, _, authority_binding = self.authority(
            action="BAPTIZE_PROGRAM",
            role="PM",
            session_id=state["sovereign_id"],
            previous=state_binding,
            inputs=[state_binding, pm_binding],
            outputs=[output, receipt],
            generation=generation,
        )
        code, result, _ = self.cli(
            "baptize-program",
            "--state", state_path,
            "--state-sha256", state_binding["sha256"],
            "--authority", authority_path,
            "--authority-sha256", authority_binding["sha256"],
            "--output", output,
            "--pm-decision", pm_path,
            "--pm-decision-sha256", pm_binding["sha256"],
            "--baptism-output", receipt,
        )
        return code, result, output


class L4ProgramPipelineTests(unittest.TestCase):
    def test_schemas_are_self_contained_and_draft_2020_12_valid(self) -> None:
        names = (
            "planning_effect_authority.schema.json",
            "planning_state.schema.json",
            "plan_lane_manifest.schema.json",
            "fused_program.schema.json",
            "program_countersign_receipt.schema.json",
            "program_baptism_decision.schema.json",
            "program_baptism_receipt.schema.json",
        )
        for name in names:
            with self.subTest(name=name):
                schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                external = []
                stack = [schema]
                while stack:
                    value = stack.pop()
                    if isinstance(value, dict):
                        external.extend(
                            item for key, item in value.items()
                            if key == "$ref" and isinstance(item, str) and not item.startswith("#")
                        )
                        stack.extend(value.values())
                    elif isinstance(value, list):
                        stack.extend(value)
                self.assertEqual(external, [])

    def test_complete_l3_to_program_baptism_chain_and_verify_expect(self) -> None:
        with Harness() as harness:
            state_path, state = harness.to_fusion()
            self.assertEqual(state["phase"], "PROGRAM_FUSION_FROZEN")
            state_path, state = harness.countersign(state_path, state, "ACCEPTED")
            self.assertEqual(state["phase"], "PROGRAM_COUNTERSIGN_ACCEPTED")
            code, result, final_path = harness.baptize(state_path, state)
            self.assertEqual((code, result["status"], result["phase"]), (0, "PASS", "PROGRAM_BAPTIZED"))
            final_binding = binding(final_path)
            code, result, _ = harness.cli(
                "verify", "--state", final_path,
                "--state-sha256", final_binding["sha256"],
                "--expect", "PROGRAM_BAPTIZED",
            )
            self.assertEqual((code, result["status"], result["write_status"]), (0, "PASS", "EXPECTED_PHASE_MATCH"))

    def test_l3_knowledge_fusion_pass_is_mandatory(self) -> None:
        with Harness() as harness:
            state = copy.deepcopy(harness.knowledge_state)
            state["phase"] = "FUSION_EMITTED"
            state["status"] = "ACTIVE"
            state["fusion"]["state"] = "FUSION_EMITTED"
            state["fusion"]["countersign_binding"] = None
            path = harness.well_root / "control" / "knowledge-not-terminal.json"
            _, state_binding = write_json(path, state)
            output = harness.planning_root / "states" / "state-0001.json"
            builder_session = state["session_pair"]["builder"]["session_id"]
            authority_path, _, authority_binding = harness.authority(
                action="INIT_PLANNING", role="BUILDER", session_id=builder_session,
                previous=None, inputs=[state_binding], outputs=[output], generation=1,
            )
            code, result, _ = harness.cli(
                "init", "--knowledge-state", path,
                "--knowledge-state-sha256", state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--program-id", harness.program_id,
                "--planning-root", harness.planning_root,
                "--output", output,
            )
            self.assertEqual((code, result["reason_code"]), (2, "L3_KNOWLEDGE_FUSION_PASS_REQUIRED"))

    def test_l3_self_countersign_is_rejected(self) -> None:
        with Harness() as harness:
            countersign = copy.deepcopy(harness.knowledge_countersign)
            countersign["countersigner_session_id"] = countersign["author_session_id"]
            countersign_path = Path(harness.knowledge_countersign_binding["path"])
            _, countersign_binding = write_json(countersign_path, countersign)
            knowledge = copy.deepcopy(harness.knowledge_state)
            knowledge["fusion"]["countersign_binding"] = countersign_binding
            _, knowledge_binding = write_json(harness.knowledge_state_path, knowledge)
            harness.knowledge_countersign_binding = countersign_binding
            harness.knowledge_state_binding = knowledge_binding
            output = harness.planning_root / "states" / "state-0001.json"
            authority_path, _, authority_binding = harness.authority(
                action="INIT_PLANNING",
                role="BUILDER",
                session_id=knowledge["session_pair"]["builder"]["session_id"],
                previous=None,
                inputs=[knowledge_binding],
                outputs=[output],
                generation=1,
            )
            code, result, _ = harness.cli(
                "init", "--knowledge-state", harness.knowledge_state_path,
                "--knowledge-state-sha256", knowledge_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--program-id", harness.program_id,
                "--planning-root", harness.planning_root,
                "--output", output,
            )
            self.assertEqual(code, 2)
            self.assertIn(
                result["reason_code"],
                {"KNOWLEDGE_FUSION_CANDIDATE_INVALID", "KNOWLEDGE_FUSION_COUNTERSIGN_RECOMPUTE_MISMATCH"},
            )

    def test_dual_commit_rejects_substantive_plan_copy(self) -> None:
        with Harness() as harness:
            state_path, state, _, _ = harness.init()
            state_binding = binding(state_path)
            builder_path, builder, builder_binding = harness.plan_draft(state, "BUILDER")
            verifier_path, verifier, _ = harness.plan_draft(state, "VERIFIER")
            verifier["work_items"][0]["title"] = builder["work_items"][0]["title"]
            verifier["work_items"][0]["result"] = builder["work_items"][0]["result"]
            verifier["alternatives"] = copy.deepcopy(builder["alternatives"])
            _, verifier_binding = write_json(verifier_path, verifier)
            output = harness.planning_root / "states" / "state-0002.json"
            authority_path, _, authority_binding = harness.authority(
                action="COMMIT_PLAN_LANES", role="BUILDER",
                session_id=state["session_pair"]["builder"]["session_id"],
                previous=state_binding,
                inputs=[state_binding, builder_binding, verifier_binding],
                outputs=[output], generation=2,
            )
            code, result, _ = harness.cli(
                "commit-plan-lanes", "--state", state_path,
                "--state-sha256", state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--output", output,
                "--builder-plan-draft", builder_path,
                "--builder-plan-draft-sha256", builder_binding["sha256"],
                "--verifier-plan-draft", verifier_path,
                "--verifier-plan-draft-sha256", verifier_binding["sha256"],
            )
            self.assertEqual((code, result["reason_code"]), (2, "PLAN_ORACLE_CONTAMINATION"))

    def test_invalid_plan_does_not_consume_nonce_or_generation(self) -> None:
        with Harness() as harness:
            state_path, state, _, _ = harness.init()
            state_binding = binding(state_path)
            builder_path, _, builder_binding = harness.plan_draft(
                state, "BUILDER", mutation=lambda value: value["alternatives"][0].pop("rationale")
            )
            verifier_path, _, verifier_binding = harness.plan_draft(state, "VERIFIER")
            output = harness.planning_root / "states" / "state-0002.json"
            authority_path, authority, authority_binding = harness.authority(
                action="COMMIT_PLAN_LANES", role="BUILDER",
                session_id=state["session_pair"]["builder"]["session_id"],
                previous=state_binding,
                inputs=[state_binding, builder_binding, verifier_binding],
                outputs=[output], generation=2,
            )
            code, result, _ = harness.cli(
                "commit-plan-lanes", "--state", state_path,
                "--state-sha256", state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--output", output,
                "--builder-plan-draft", builder_path,
                "--builder-plan-draft-sha256", builder_binding["sha256"],
                "--verifier-plan-draft", verifier_path,
                "--verifier-plan-draft-sha256", verifier_binding["sha256"],
            )
            self.assertEqual((code, result["reason_code"]), (2, "PLAN_DRAFT_COLLECTION_INVALID"))
            nonce = harness.planning_root / "control" / "nonces" / f"{authority['operation_nonce']}.json"
            claim = harness.planning_root / "control" / "generation_claims" / "GEN_0002.json"
            self.assertFalse(nonce.exists())
            self.assertFalse(claim.exists())

    def test_artifacts_are_lane_confined_and_forbidden_effects_are_closed(self) -> None:
        mutations = {
            "PATH_OUTSIDE_PLANNING_ROOT": lambda value: value["work_items"][0]["persistent_artifact"].update(path=str(Path("C:/Users/Public/out.bin"))),
            "PROGRAM_FORBIDDEN_EFFECT": lambda value: value["work_items"][0]["persistent_artifact"].update(path=str(Path(value["lane_root"]) / "artifacts" / "publish-release.bin")),
        }
        for expected, mutation in mutations.items():
            with self.subTest(expected=expected), Harness() as harness:
                state_path, state, _, _ = harness.init()
                state_binding = binding(state_path)
                builder_path, _, builder_binding = harness.plan_draft(state, "BUILDER", mutation=mutation)
                verifier_path, _, verifier_binding = harness.plan_draft(state, "VERIFIER")
                output = harness.planning_root / "states" / "state-0002.json"
                authority_path, _, authority_binding = harness.authority(
                    action="COMMIT_PLAN_LANES", role="BUILDER",
                    session_id=state["session_pair"]["builder"]["session_id"],
                    previous=state_binding,
                    inputs=[state_binding, builder_binding, verifier_binding],
                    outputs=[output], generation=2,
                )
                code, result, _ = harness.cli(
                    "commit-plan-lanes", "--state", state_path,
                    "--state-sha256", state_binding["sha256"],
                    "--authority", authority_path,
                    "--authority-sha256", authority_binding["sha256"],
                    "--output", output,
                    "--builder-plan-draft", builder_path,
                    "--builder-plan-draft-sha256", builder_binding["sha256"],
                    "--verifier-plan-draft", verifier_path,
                    "--verifier-plan-draft-sha256", verifier_binding["sha256"],
                )
                self.assertEqual((code, result["reason_code"]), (2, expected))

    def test_plan_lane_rejects_oracle_shared_writer_author_sign_and_forward_dependency(self) -> None:
        mutations = {
            "PLAN_ORACLE_CONTAMINATION": lambda draft: draft.update(peer_lane_read_before_dual_freeze=True),
            "PROGRAM_SHARED_WRITER_FORBIDDEN": lambda draft: draft["work_items"][0].update(owner_role="SHARED"),
            "PROGRAM_AUTHOR_AND_SIGN_FORBIDDEN": lambda draft: draft["work_items"][0].update(verifier_role="BUILDER"),
            "PROGRAM_DAG_FORWARD_OR_UNKNOWN_DEPENDENCY": lambda draft: draft["work_items"][0].update(depends_on=["WP-FUTURE-001"]),
        }
        for expected, mutation in mutations.items():
            with self.subTest(expected=expected), Harness() as harness:
                state_path, state, _, _ = harness.init()
                state_binding = binding(state_path)
                draft_path, _, draft_binding = harness.plan_draft(state, "BUILDER", mutation=mutation)
                verifier_path, _, verifier_binding = harness.plan_draft(state, "VERIFIER")
                output = harness.planning_root / "states" / "state-0002.json"
                authority_path, _, authority_binding = harness.authority(
                    action="COMMIT_PLAN_LANES", role="BUILDER",
                    session_id=state["lanes"]["BUILDER"]["session_id"],
                    previous=state_binding,
                    inputs=[state_binding, draft_binding, verifier_binding],
                    outputs=[output], generation=2,
                )
                code, result, _ = harness.cli(
                    "commit-plan-lanes", "--state", state_path,
                    "--state-sha256", state_binding["sha256"],
                    "--authority", authority_path,
                    "--authority-sha256", authority_binding["sha256"],
                    "--output", output,
                    "--builder-plan-draft", draft_path,
                    "--builder-plan-draft-sha256", draft_binding["sha256"],
                    "--verifier-plan-draft", verifier_path,
                    "--verifier-plan-draft-sha256", verifier_binding["sha256"],
                )
                self.assertEqual((code, result["reason_code"]), (2, expected))

    def test_fusion_requires_both_lane_freezes(self) -> None:
        with Harness() as harness:
            state_path, state, _, _ = harness.init()
            state_path, state = harness.commit(state_path, state)
            state_path, state, _, _ = harness.freeze(state_path, state, "BUILDER")
            state_binding = binding(state_path)
            dummy = harness.builder_lane / "dummy.json"
            _, dummy_binding = write_json(dummy, {"schema": "DUMMY", "value": "x"}, do_seal=False)
            generation = state["generation"] + 1
            output = harness.planning_root / "states" / f"state-{generation:04d}.json"
            candidate = harness.planning_root / "candidate.json"
            authority_path, _, authority_binding = harness.authority(
                action="FUSE_PROGRAM", role="BUILDER",
                session_id=state["session_pair"]["builder"]["session_id"],
                previous=state_binding, inputs=[state_binding, dummy_binding],
                outputs=[output, candidate], generation=generation,
            )
            code, result, _ = harness.cli(
                "emit-program-fusion", "--state", state_path,
                "--state-sha256", state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--output", output,
                "--fused-plan", dummy, "--fused-plan-sha256", dummy_binding["sha256"],
                "--decision-register", dummy, "--decision-register-sha256", dummy_binding["sha256"],
                "--candidate-output", candidate,
            )
            self.assertEqual((code, result["reason_code"]), (2, "FUSION_BEFORE_DUAL_PLAN_FREEZE"))

    def test_fusion_rejects_erased_origins_alternatives_and_dissent(self) -> None:
        mutations = {
            "PROGRAM_ORIGIN_COVERAGE_MISMATCH": lambda fused: fused["work_items"][0].update(origin_refs=[fused["work_items"][0]["origin_refs"][0]]),
            "PROGRAM_ALTERNATIVE_ERASURE": lambda fused: fused.update(preserved_alternative_ids=[]),
            "PROGRAM_DISSENT_ERASURE": lambda fused: fused.update(preserved_dissent_ids=[]),
        }
        for expected, mutation in mutations.items():
            with self.subTest(expected=expected), Harness() as harness:
                state_path, state = harness.to_dual_freeze()
                state_binding = binding(state_path)
                fused_path, fused_binding, decisions_path, decisions_binding = harness.fusion_inputs(
                    state, mutate_fused=mutation
                )
                generation = state["generation"] + 1
                output = harness.planning_root / "states" / f"state-{generation:04d}.json"
                candidate = harness.planning_root / "candidate.json"
                authority_path, _, authority_binding = harness.authority(
                    action="FUSE_PROGRAM", role="BUILDER",
                    session_id=state["session_pair"]["builder"]["session_id"],
                    previous=state_binding,
                    inputs=[state_binding, fused_binding, decisions_binding],
                    outputs=[output, candidate], generation=generation,
                )
                code, result, _ = harness.cli(
                    "emit-program-fusion", "--state", state_path,
                    "--state-sha256", state_binding["sha256"],
                    "--authority", authority_path,
                    "--authority-sha256", authority_binding["sha256"],
                    "--output", output,
                    "--fused-plan", fused_path, "--fused-plan-sha256", fused_binding["sha256"],
                    "--decision-register", decisions_path,
                    "--decision-register-sha256", decisions_binding["sha256"],
                    "--candidate-output", candidate,
                )
                self.assertEqual((code, result["reason_code"]), (2, expected))

    def test_independent_verifier_has_three_terminal_decisions(self) -> None:
        expected = {
            "ACCEPTED": ("PROGRAM_COUNTERSIGN_ACCEPTED", "ACTIVE"),
            "BLOCK": ("PROGRAM_COUNTERSIGN_BLOCKED", "BLOCKED"),
            "INCONCLUSIVE": ("PROGRAM_COUNTERSIGN_INCONCLUSIVE", "INCONCLUSIVE"),
        }
        for decision, outcome in expected.items():
            with self.subTest(decision=decision), Harness() as harness:
                state_path, state = harness.to_fusion()
                _, result = harness.countersign(state_path, state, decision)
                self.assertEqual((result["phase"], result["status"]), outcome)

    def test_false_accept_and_baptism_digest_drift_fail_closed(self) -> None:
        with Harness() as harness:
            state_path, state = harness.to_fusion()
            state_binding = binding(state_path)
            report_path, report_binding = harness.verifier_report(state, "ACCEPTED", false_accept=True)
            generation = state["generation"] + 1
            output = harness.planning_root / "states" / f"state-{generation:04d}.json"
            receipt = harness.verifier_lane / "receipt.json"
            authority_path, _, authority_binding = harness.authority(
                action="COUNTERSIGN_PROGRAM", role="VERIFIER",
                session_id=state["session_pair"]["verifier"]["session_id"],
                previous=state_binding, inputs=[state_binding, report_binding],
                outputs=[output, receipt], generation=generation,
            )
            code, result, _ = harness.cli(
                "countersign-program", "--state", state_path,
                "--state-sha256", state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--output", output,
                "--verifier-report", report_path,
                "--verifier-report-sha256", report_binding["sha256"],
                "--receipt-output", receipt,
            )
            self.assertEqual((code, result["reason_code"]), (2, "FALSE_PROGRAM_COUNTERSIGN_ACCEPTED"))

        with Harness() as harness:
            state_path, state = harness.to_fusion()
            state_path, state = harness.countersign(state_path, state)
            code, result, _ = harness.baptize(state_path, state, corrupt_digest=True)
            self.assertEqual((code, result["reason_code"]), (2, "PROGRAM_BAPTISM_DIGEST_MISMATCH"))

    def test_verify_expect_mismatch_is_stable(self) -> None:
        with Harness() as harness:
            state_path, _, state_binding, _ = harness.init()
            code, result, _ = harness.cli(
                "verify", "--state", state_path,
                "--state-sha256", state_binding["sha256"],
                "--expect", "PROGRAM_BAPTIZED",
            )
            self.assertEqual((code, result["reason_code"]), (2, "PROGRAM_STATE_EXPECTED_PHASE_MISMATCH"))

    def test_terminal_verify_reopens_l3_baptism_and_pm_bytes(self) -> None:
        with Harness() as harness:
            state_path, state = harness.to_fusion()
            state_path, state = harness.countersign(state_path, state)
            code, _, final_path = harness.baptize(state_path, state)
            self.assertEqual(code, 0)
            harness.knowledge_state_path.unlink()
            final_binding = binding(final_path)
            code, result, _ = harness.cli(
                "verify", "--state", final_path,
                "--state-sha256", final_binding["sha256"],
                "--expect", "PROGRAM_BAPTIZED",
            )
            self.assertEqual(code, 2)
            self.assertNotEqual(result["status"], "PASS")

        with Harness() as harness:
            state_path, state = harness.to_fusion()
            state_path, state = harness.countersign(state_path, state)
            code, _, final_path = harness.baptize(state_path, state)
            self.assertEqual(code, 0)
            final = json.loads(final_path.read_text(encoding="utf-8"))
            receipt_path = Path(final["baptism"]["receipt_binding"]["path"])
            receipt_path.write_text("forged\n", encoding="utf-8")
            final["baptism"]["receipt_binding"] = binding(receipt_path)
            _, final_binding = write_json(final_path, final)
            code, result, _ = harness.cli(
                "verify", "--state", final_path,
                "--state-sha256", final_binding["sha256"],
                "--expect", "PROGRAM_BAPTIZED",
            )
            self.assertEqual(code, 2)
            self.assertNotEqual(result["status"], "PASS")

    def test_baptism_rejects_noncanonical_sovereign(self) -> None:
        with Harness() as harness:
            state_path, state = harness.to_fusion()
            state_path, state = harness.countersign(state_path, state)
            code, result, _ = harness.baptize(
                state_path,
                state,
                sovereign_override="IMPOSTOR-SOVEREIGN",
            )
            self.assertEqual((code, result["reason_code"]), (2, "PROGRAM_BAPTISM_SOVEREIGN_MISMATCH"))

    def test_recursive_generation_claim_semantics_are_revalidated(self) -> None:
        with Harness() as harness:
            state_path, state, _, _ = harness.init()
            claim_path = Path(state["generation_claim_binding"]["path"])
            claim = json.loads(claim_path.read_text(encoding="utf-8"))
            claim["generation"] = 99
            _, claim_binding = write_json(claim_path, claim)
            state["generation_claim_binding"] = claim_binding
            _, state_binding = write_json(state_path, state)
            code, result, _ = harness.cli(
                "verify", "--state", state_path,
                "--state-sha256", state_binding["sha256"],
                "--expect", "PLANNING_INITIALIZED",
            )
            self.assertEqual((code, result["reason_code"]), (2, "PLANNING_GENERATION_CHAIN_MISMATCH"))

    def test_create_once_identical_retry_and_orphan_staging_recovery(self) -> None:
        with Harness() as harness:
            output, _, _, first = harness.init(nonce="NONCE-RETRY")
            self.assertEqual(first["write_status"], "CREATED")
            authority_path = harness.planning_root / "control" / "authorities" / "authority-0001.json"
            authority_binding = binding(authority_path)
            code, second, _ = harness.cli(
                "init", "--knowledge-state", harness.knowledge_state_path,
                "--knowledge-state-sha256", harness.knowledge_state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--program-id", harness.program_id,
                "--planning-root", harness.planning_root,
                "--output", output,
            )
            self.assertEqual((code, second["status"], second["write_status"]), (0, "PASS", "ALREADY_PRESENT_IDENTICAL"))

            expected_bytes = output.read_bytes()
            staging = output.parent / f".{output.name}.pending"
            output.unlink()
            staging.write_bytes(expected_bytes)
            code, recovered, _ = harness.cli(
                "init", "--knowledge-state", harness.knowledge_state_path,
                "--knowledge-state-sha256", harness.knowledge_state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--program-id", harness.program_id,
                "--planning-root", harness.planning_root,
                "--output", output,
            )
            self.assertEqual((code, recovered["status"], recovered["write_status"]), (0, "PASS", "CREATED"))
            self.assertEqual(output.read_bytes(), expected_bytes)
            self.assertFalse(staging.exists())

    def test_nonce_replay_and_concurrent_generation_fork_are_blocked(self) -> None:
        with Harness() as harness:
            output, state, state_binding, _ = harness.init(nonce="NONCE-SHARED")
            other_output = harness.planning_root / "states" / "state-replay.json"
            authority_path, _, authority_binding = harness.authority(
                action="INIT_PLANNING", role="BUILDER",
                session_id=state["session_pair"]["builder"]["session_id"],
                previous=None, inputs=[harness.knowledge_state_binding],
                outputs=[other_output], generation=1, nonce="NONCE-SHARED",
            )
            code, result, _ = harness.cli(
                "init", "--knowledge-state", harness.knowledge_state_path,
                "--knowledge-state-sha256", harness.knowledge_state_binding["sha256"],
                "--authority", authority_path,
                "--authority-sha256", authority_binding["sha256"],
                "--program-id", harness.program_id,
                "--planning-root", harness.planning_root,
                "--output", other_output,
            )
            self.assertEqual((code, result["reason_code"]), (2, "PLANNING_EFFECT_AUTHORITY_NONCE_REPLAY"))

        with Harness() as harness:
            output_a = harness.planning_root / "states" / "fork-a.json"
            output_b = harness.planning_root / "states" / "fork-b.json"
            session = harness.knowledge_state["session_pair"]["builder"]["session_id"]
            auth_a, _, bind_a = harness.authority(
                action="INIT_PLANNING", role="BUILDER", session_id=session,
                previous=None, inputs=[harness.knowledge_state_binding],
                outputs=[output_a], generation=1, nonce="NONCE-FORK-A",
            )
            auth_b, _, bind_b = harness.authority(
                action="INIT_PLANNING", role="BUILDER", session_id=session,
                previous=None, inputs=[harness.knowledge_state_binding],
                outputs=[output_b], generation=1, nonce="NONCE-FORK-B",
            )

            def invoke(authority_path: Path, authority_binding: dict[str, object], output_path: Path):
                return harness.cli(
                    "init", "--knowledge-state", harness.knowledge_state_path,
                    "--knowledge-state-sha256", harness.knowledge_state_binding["sha256"],
                    "--authority", authority_path,
                    "--authority-sha256", authority_binding["sha256"],
                    "--program-id", harness.program_id,
                    "--planning-root", harness.planning_root,
                    "--output", output_path,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda item: invoke(*item), [(auth_a, bind_a, output_a), (auth_b, bind_b, output_b)]))
            passes = [result for result in results if result[0] == 0]
            blocked = [result for result in results if result[0] == 2]
            self.assertEqual(len(passes), 1)
            self.assertEqual(len(blocked), 1)
            self.assertEqual(blocked[0][1]["reason_code"], "PLANNING_GENERATION_FORK_DETECTED")


if __name__ == "__main__":
    unittest.main()

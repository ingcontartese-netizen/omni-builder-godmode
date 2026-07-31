from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SENTRY = ROOT / "scripts" / "sentry"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SENTRY))
sys.path.insert(0, str(TESTS))

from emit_state import (
    ProtocolError,
    _absolute_physical_path as state_absolute_physical_path,
    seal,
    validate_instance,
)
from io_safe import canonical_json, sha256_bytes, sha256_path
from mode_a_guard import (
    ModeBindingError,
    _absolute_physical_path as mode_absolute_physical_path,
    _validate_workspace_access,
    decide_invocation,
)
from test_governance_scripts import guided_digest, guided_state


CLI = SENTRY / "mode_a_guard.py"


class L2BindingAndModeTests(unittest.TestCase):
    def _write_fixture(
        self,
        root: Path,
        *,
        topology: str = "TEAM_DUAL_LANE",
        activation_decision: dict[str, object] | None = None,
        validate_state: bool = True,
    ) -> tuple[Path, Path, Path, Path, Path]:
        decision = activation_decision or decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            run_kind="REAL",
            activation_level="OMNI_FULL",
        )
        activation = root / "activation.json"
        activation.write_text(
            json.dumps(decision, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        state = guided_state(topology=topology, run_kind="REAL")
        binding = state["activation_binding"]
        binding.update(
            {
                "path": str(activation.resolve()),
                "bytes": activation.stat().st_size,
                "sha256": sha256_path(activation),
                "receipt_outcome": "ACCEPTED",
                "decision_schema": decision.get("schema", "omni-invocation-decision-v2"),
                "decision_status": "ACTIVATION_ALLOWED",
                "activation_path": "EXPLICIT_USER_OPT_IN",
                "knowledge_available": decision["knowledge_available"],
                "skill_invoked": decision["skill_invoked"],
                "effect_authorized": decision["effect_authorized"],
                "activation_level": decision["activation_level"],
                "modules_used": decision["modules_used"],
                "authority_grants": decision["authority_grants"],
                "artifact_grants": decision["artifact_grants"],
                "requested_effects": decision["requested_effects"],
                "effect_grants": decision["effect_grants"],
                "non_grants": decision["non_grants"],
                "access_envelope_identity": decision["access_envelope_identity"],
                "next_gate": decision["next_gate"],
            }
        )
        state["profile"] = "GODMODE"
        state["independence"] = (
            "PEER_INDEPENDENT" if topology == "TEAM_DUAL_LANE" else "ADVERSARIAL_SOLO"
        )
        state["station_matrix_sha256"] = sha256_bytes(
            canonical_json(state["station_matrix"]).encode("utf-8")
        )
        state["critical_closure"]["derivation"] = (
            "RECOMPUTED_FROM_EVIDENCE_AND_FOUR_READBACK_V2"
        )
        state["critical_closure"]["station_matrix_sha256"] = state[
            "station_matrix_sha256"
        ]
        state["created_at"] = "2026-07-30T08:00:00+00:00"
        state["previous_record_sha256"] = None
        state = seal(state)
        intake = root / "intake-ready.json"
        intake.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        evidence_file = root / "l4-evidence.json"
        evidence_file.write_text('{"status":"PASS"}\n', encoding="utf-8")
        evidence_binding = {
            "path": str(evidence_file.resolve()),
            "bytes": evidence_file.stat().st_size,
            "sha256": sha256_path(evidence_file),
        }
        program_record = seal(
            {
                "schema": "omni-fused-program-v2",
                "kind": "PROGRAM_FUSION_CANDIDATE",
                "status": "PROGRAM_FUSION_FROZEN",
                "program_id": "PROGRAM-001",
                "task_id": state["workspace_access_envelope"]["task_id"],
                "knowledge_pipeline_id": "KNOWLEDGE-001",
                "knowledge_state_binding": evidence_binding,
                "knowledge_fusion_countersign_binding": evidence_binding,
                "canonical_knowledge_binding": evidence_binding,
                "session_pair_sha256": state["session_pair"]["pair_sha256"],
                "author_role": "BUILDER",
                "author_session_id": state["session_pair"]["builder"]["session_id"],
                "topology": state["topology"],
                "profile": state["profile"],
                "run_kind": state["run_kind"],
                "fused_from_lanes": ["BUILDER", "VERIFIER"],
                "builder_plan_manifest_binding": evidence_binding,
                "verifier_plan_manifest_binding": evidence_binding,
                "fusion_decision_register_binding": evidence_binding,
                "fused_plan_draft_binding": evidence_binding,
                "work_items": [
                    {
                        "work_id": "WP-001",
                        "ordinal": 1,
                        "title": "Build and independently verify the bounded deliverable",
                        "result": "One byte-bound verified deliverable",
                        "persistent_artifact": {
                            "path": str((root / "deliverable.json").resolve()),
                            "create_policy": "CREATE_ONCE",
                            "owner_role": "BUILDER",
                        },
                        "owner_role": "BUILDER",
                        "depends_on": [],
                        "preconditions": ["PROGRAM_BAPTIZED"],
                        "required_capabilities": ["CREATE_FILES"],
                        "budget": {
                            "max_turns": 10,
                            "max_tool_calls": 20,
                            "max_elapsed_seconds": 3600,
                        },
                        "acceptance_evidence": [
                            {
                                "evidence_id": "EVIDENCE-001",
                                "description": "Independent reproduction",
                                "kind": "TEST_REPORT",
                            }
                        ],
                        "verifier_role": "VERIFIER",
                        "rollback": {"strategy": "SAFE_PARK", "steps": ["Stop"]},
                        "failure_states": ["BLOCKED_PENDING_HUMAN", "INCONCLUSIVE"],
                        "next_gate": "F4_TEST",
                        "scope": ["F3_BUILD", "F4_TEST"],
                        "origin_refs": [
                            {"role": "BUILDER", "work_id": "BUILDER-WP-001"},
                            {"role": "VERIFIER", "work_id": "VERIFIER-WP-001"},
                        ],
                    }
                ],
                "preserved_alternative_ids": [],
                "preserved_dissent_ids": [],
                "created_at": "2026-07-30T08:00:00+00:00",
            }
        )
        program = root / "fused-program.json"
        program.write_text(
            json.dumps(program_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        countersign_record = seal(
            {
                "schema": "omni-program-countersign-receipt-v2",
                "status": "PROGRAM_COUNTERSIGN_ACCEPTED",
                "decision": "ACCEPTED",
                "receipt_id": "PROGRAM-CS-001",
                "program_id": program_record["program_id"],
                "task_id": program_record["task_id"],
                "knowledge_pipeline_id": program_record["knowledge_pipeline_id"],
                "program_binding": {
                    "path": str(program.resolve()),
                    "bytes": program.stat().st_size,
                    "sha256": sha256_path(program),
                },
                "program_record_digest": program_record["record_digest"],
                "knowledge_state_binding": program_record["knowledge_state_binding"],
                "knowledge_fusion_countersign_binding": program_record[
                    "knowledge_fusion_countersign_binding"
                ],
                "session_pair_sha256": state["session_pair"]["pair_sha256"],
                "program_author_session_id": program_record["author_session_id"],
                "signer_role": "VERIFIER",
                "signer_session_id": state["session_pair"]["verifier"]["session_id"],
                "verifier_report_binding": evidence_binding,
                "reproduction": {
                    "schema_valid": True,
                    "dag_valid": True,
                    "full_wbs_valid": True,
                    "origin_coverage_complete": True,
                    "alternatives_preserved": True,
                    "dissent_preserved": True,
                    "no_shared_writer": True,
                    "no_oracle_before_dual_freeze": True,
                    "exact_bindings": True,
                },
                "finding_codes": [],
                "evidence_bindings": [evidence_binding],
                "created_at": "2026-07-30T08:00:00+00:00",
            }
        )
        countersign = root / "program-countersign.json"
        countersign.write_text(
            json.dumps(countersign_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        workspace_envelope_record = state["workspace_access_envelope"]
        probe_binding = workspace_envelope_record["probe_receipt_binding"]
        self.assertIsInstance(probe_binding, dict)
        probe_receipt = Path(probe_binding["path"])
        probe_receipt_record = json.loads(probe_receipt.read_text(encoding="utf-8"))
        probe_receipt_record["activation_receipt_sha256"] = sha256_path(activation)
        probe_receipt_record = seal(probe_receipt_record)
        probe_receipt.write_text(
            json.dumps(probe_receipt_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        workspace_envelope_record["activation_receipt_sha256"] = sha256_path(activation)
        workspace_envelope_record["probe_receipt_binding"] = {
            "path": str(probe_receipt.resolve()),
            "bytes": probe_receipt.stat().st_size,
            "sha256": sha256_path(probe_receipt),
        }
        workspace_envelope_record = seal(workspace_envelope_record)
        workspace_envelope = root / "workspace-access-envelope.json"
        workspace_envelope.write_text(
            json.dumps(workspace_envelope_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        state["workspace_access_envelope"] = workspace_envelope_record
        state = seal(state)
        if validate_state:
            validate_instance(state)
        intake.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        program_binding = {
            "path": str(program.resolve()),
            "bytes": program.stat().st_size,
            "sha256": sha256_path(program),
        }
        countersign_binding = {
            "path": str(countersign.resolve()),
            "bytes": countersign.stat().st_size,
            "sha256": sha256_path(countersign),
        }
        sovereign_id = state["team_card"]["sovereign_identity"]
        baptism_decision_record = seal(
            {
                "schema": "omni-program-baptism-decision-v1",
                "status": "PROGRAM_BAPTISM_AUTHORIZED",
                "decision": "ACCEPTED",
                "program_id": program_record["program_id"],
                "task_id": program_record["task_id"],
                "knowledge_pipeline_id": program_record["knowledge_pipeline_id"],
                "session_pair_sha256": program_record["session_pair_sha256"],
                "program_binding": program_binding,
                "program_record_digest": program_record["record_digest"],
                "program_countersign_binding": countersign_binding,
                "program_countersign_record_digest": countersign_record["record_digest"],
                "sovereign_id": sovereign_id,
                "created_at": "2026-07-30T08:01:00+00:00",
            }
        )
        baptism_decision = root / "program-baptism-decision.json"
        baptism_decision.write_text(
            json.dumps(baptism_decision_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        baptism_decision_binding = {
            "path": str(baptism_decision.resolve()),
            "bytes": baptism_decision.stat().st_size,
            "sha256": sha256_path(baptism_decision),
        }
        baptism_receipt_record = seal(
            {
                "schema": "omni-program-baptism-receipt-v1",
                "status": "PROGRAM_BAPTIZED",
                "decision": "ACCEPTED",
                "program_id": program_record["program_id"],
                "task_id": program_record["task_id"],
                "knowledge_pipeline_id": program_record["knowledge_pipeline_id"],
                "session_pair_sha256": program_record["session_pair_sha256"],
                "program_binding": program_binding,
                "program_record_digest": program_record["record_digest"],
                "program_countersign_binding": countersign_binding,
                "program_countersign_record_digest": countersign_record["record_digest"],
                "pm_decision_binding": baptism_decision_binding,
                "sovereign_id": sovereign_id,
                "created_at": "2026-07-30T08:02:00+00:00",
            }
        )
        baptism_receipt = root / "program-baptism-receipt.json"
        baptism_receipt.write_text(
            json.dumps(baptism_receipt_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return activation, intake, program, countersign, workspace_envelope

    def _run(
        self,
        *args: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(CLI), *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
        )

    def _bound_args(
        self,
        activation: Path,
        intake: Path,
        program: Path,
        countersign: Path,
        workspace_envelope: Path,
    ) -> list[str]:
        access = json.loads(workspace_envelope.read_text(encoding="utf-8"))
        state = json.loads(intake.read_text(encoding="utf-8"))
        baptism_decision = program.parent / "program-baptism-decision.json"
        baptism_receipt = program.parent / "program-baptism-receipt.json"
        return [
            "--explicit-user-request",
            "--run-kind",
            "REAL",
            "--activation-level",
            "OMNI_FULL",
            "--activation-receipt",
            str(activation),
            "--intake-state",
            str(intake),
            "--intake-state-sha256",
            sha256_path(intake),
            "--program",
            str(program),
            "--program-sha256",
            sha256_path(program),
            "--program-countersign",
            str(countersign),
            "--program-countersign-sha256",
            sha256_path(countersign),
            "--program-baptism-decision",
            str(baptism_decision),
            "--program-baptism-decision-sha256",
            sha256_path(baptism_decision),
            "--program-baptism-receipt",
            str(baptism_receipt),
            "--program-baptism-receipt-sha256",
            sha256_path(baptism_receipt),
            "--expected-sovereign-id",
            state["team_card"]["sovereign_identity"],
            "--workspace-access-envelope",
            str(workspace_envelope),
            "--workspace-access-envelope-sha256",
            sha256_path(workspace_envelope),
            "--task-id",
            access["task_id"],
            "--task-root",
            access["task_root"],
            "--project-root",
            access["project_root"],
            "--source-root",
            access["source_roots"][0],
            "--durable-state",
            "--midstream-judgment",
            "--parallel-value",
            "--independent-verifier",
            "--turns",
            "3",
        ]

    def test_mode_selection_reads_and_reproduces_all_bound_files(self):
        with tempfile.TemporaryDirectory() as directory:
            activation, intake, program, countersign, access = self._write_fixture(Path(directory))
            completed = self._run(*self._bound_args(activation, intake, program, countersign, access))
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["mode"], "MODE_C_GOVERNED_AGENTIC")
            self.assertEqual(output["mode_gate"], "MODE_SELECTED")
            self.assertTrue(output["mode_selection_allowed"])
            self.assertEqual(output["intake_state_sha256"], sha256_path(intake))
            self.assertEqual(output["activation_receipt_sha256"], sha256_path(activation))
            self.assertEqual(output["program_sha256"], sha256_path(program))
            self.assertEqual(output["program_bytes"], program.stat().st_size)
            self.assertEqual(output["program_countersign_sha256"], sha256_path(countersign))
            self.assertEqual(output["program_countersign_bytes"], countersign.stat().st_size)
            baptism_decision = program.parent / "program-baptism-decision.json"
            baptism_receipt = program.parent / "program-baptism-receipt.json"
            self.assertEqual(
                output["program_baptism_decision_sha256"], sha256_path(baptism_decision),
            )
            self.assertEqual(
                output["program_baptism_receipt_sha256"], sha256_path(baptism_receipt),
            )
            self.assertEqual(output["program_baptism_status"], "PROGRAM_BAPTIZED")
            self.assertEqual(output["workspace_access_envelope_id"], "ACCESS-001")
            self.assertEqual(output["workspace_access_envelope_sha256"], sha256_path(access))
            self.assertEqual(output["access_envelope_identity"], "ACCESS-001")
            self.assertTrue(output["effect_authorized"])
            self.assertEqual(output["effect_grants"], ["CREATE_FILES"])
            self.assertNotEqual(output["mode_gate"], "MODE_BEFORE_PROGRAM")

            access_record = json.loads(access.read_text(encoding="utf-8"))
            probe_receipt = Path(access_record["probe_receipt_binding"]["path"])
            probe_record = json.loads(probe_receipt.read_text(encoding="utf-8"))
            for schema_name, record in (
                ("workspace_access_envelope.schema.json", access_record),
                ("workspace_access_probe_receipt.schema.json", probe_record),
                (
                    "fused_program.schema.json",
                    json.loads(program.read_text(encoding="utf-8")),
                ),
                (
                    "program_countersign_receipt.schema.json",
                    json.loads(countersign.read_text(encoding="utf-8")),
                ),
                (
                    "program_baptism_decision.schema.json",
                    json.loads(baptism_decision.read_text(encoding="utf-8")),
                ),
                (
                    "program_baptism_receipt.schema.json",
                    json.loads(baptism_receipt.read_text(encoding="utf-8")),
                ),
            ):
                schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
                Draft202012Validator(schema).validate(record)

    def test_absolute_mode_bindings_are_cwd_independent(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as cwd_a, tempfile.TemporaryDirectory() as cwd_b:
            activation, intake, program, countersign, access = self._write_fixture(
                Path(directory)
            )
            args = self._bound_args(activation, intake, program, countersign, access)
            first = self._run(*args, cwd=Path(cwd_a))
            second = self._run(*args, cwd=Path(cwd_b))
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))

    def test_state_and_mode_path_oracles_reject_same_ambiguous_forms(self):
        cases = (
            ("relative/path", "ABSOLUTE_PATH_REQUIRED"),
            (r"C:drive-relative", "ABSOLUTE_PATH_REQUIRED"),
            (r"C:\physical\file:stream", "AMBIGUOUS_PATH_FORBIDDEN"),
            (r"\\?\C:\physical\file", "AMBIGUOUS_PATH_FORBIDDEN"),
            (r"\\.\NUL", "AMBIGUOUS_PATH_FORBIDDEN"),
            (r"C:\physical\NUL.txt", "AMBIGUOUS_PATH_FORBIDDEN"),
            (r"C:\physical\trailing.", "AMBIGUOUS_PATH_FORBIDDEN"),
            ("C:\\physical\\trailing ", "AMBIGUOUS_PATH_FORBIDDEN"),
        )
        for value, reason in cases:
            for oracle, error_type in (
                (state_absolute_physical_path, ProtocolError),
                (mode_absolute_physical_path, ModeBindingError),
            ):
                with self.subTest(value=value, oracle=oracle.__module__), self.assertRaisesRegex(
                    error_type, reason
                ):
                    oracle(value, "TEST_PATH", strict=False)

    def test_cli_physical_bindings_reject_cwd_relative_paths(self):
        flags = (
            "--activation-receipt",
            "--intake-state",
            "--program",
            "--program-countersign",
            "--program-baptism-decision",
            "--program-baptism-receipt",
            "--workspace-access-envelope",
            "--task-root",
            "--project-root",
            "--source-root",
        )
        with tempfile.TemporaryDirectory() as directory:
            activation, intake, program, countersign, access = self._write_fixture(
                Path(directory)
            )
            baseline = self._bound_args(
                activation, intake, program, countersign, access
            )
            for flag in flags:
                with self.subTest(flag=flag):
                    args = list(baseline)
                    args[args.index(flag) + 1] = "relative-binding"
                    blocked = self._run(*args)
                    self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
                    self.assertIn(
                        "ABSOLUTE_PATH_REQUIRED",
                        json.loads(blocked.stdout)["reason_code"],
                    )

    def test_absolute_path_schema_oracles_reject_relative_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            activation, intake, _program, countersign, access = self._write_fixture(
                Path(directory)
            )
            del activation
            cases = []

            intake_record = json.loads(intake.read_text(encoding="utf-8"))
            intake_record["activation_binding"]["path"] = "activation.json"
            cases.append(("guided_intake_state.schema.json", intake_record))

            envelope = json.loads(access.read_text(encoding="utf-8"))
            envelope["task_root"] = "task"
            cases.append(("workspace_access_envelope.schema.json", envelope))

            probe_path = Path(
                json.loads(access.read_text(encoding="utf-8"))[
                    "probe_receipt_binding"
                ]["path"]
            )
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            probe["probe_path"] = "retained.probe"
            cases.append(("workspace_access_probe_receipt.schema.json", probe))

            countersign_record = json.loads(countersign.read_text(encoding="utf-8"))
            countersign_record["program_binding"]["path"] = "program.json"
            cases.append(("program_countersign_receipt.schema.json", countersign_record))

            for schema_name, instance in cases:
                with self.subTest(schema=schema_name):
                    schema = json.loads(
                        (ROOT / "schemas" / schema_name).read_text(encoding="utf-8")
                    )
                    self.assertTrue(
                        list(Draft202012Validator(schema).iter_errors(instance))
                    )

    def test_complete_program_without_external_access_binding_stops_before_access(self):
        with tempfile.TemporaryDirectory() as directory:
            activation, intake, program, countersign, access = self._write_fixture(
                Path(directory)
            )
            args = self._bound_args(activation, intake, program, countersign, access)
            access_start = args.index("--workspace-access-envelope")
            mode_flags = args.index("--durable-state")
            completed = self._run(*args[:access_start], *args[mode_flags:])
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["mode_gate"], "MODE_BEFORE_ACCESS")
            self.assertEqual(output["next_gate"], "WORKSPACE_ACCESS_ENVELOPE")
            self.assertFalse(output["effect_authorized"])
            self.assertNotIn("mode", output)

    def test_workspace_capability_shortfall_and_scope_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            envelope = json.loads(access.read_text(encoding="utf-8"))
            envelope["granted_capabilities"] = envelope["granted_capabilities"][:-1]
            envelope = seal(envelope)
            access.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "WORKSPACE_ACCESS_CAPABILITY_SHORTFALL",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            envelope = json.loads(access.read_text(encoding="utf-8"))
            outside_project = root / "outside-project"
            outside_lane = outside_project / "lanes" / "builder"
            outside_lane.mkdir(parents=True)
            envelope["project_root"] = str(outside_project.resolve())
            envelope["owned_lane_root"] = str(outside_lane.resolve())
            envelope = seal(envelope)
            access.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "WORKSPACE_ACCESS_SCOPE_ESCAPE",
            )

    def test_read_proof_cannot_be_self_authored_in_builder_write_scope(self):
        cases = (
            ("source_root_is_builder_lane", "WORKSPACE_SOURCE_WRITE_SCOPE_OVERLAP"),
            ("source_root_contains_builder_lane", "WORKSPACE_SOURCE_WRITE_SCOPE_OVERLAP"),
        )
        for case, reason in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                activation, intake, _program, _countersign, access = self._write_fixture(root)
                state = json.loads(intake.read_text(encoding="utf-8"))
                envelope = json.loads(access.read_text(encoding="utf-8"))
                builder_lane = Path(state["session_pair"]["builder"]["write_lane"])
                self_authored = builder_lane / "self-authored-read-proof.txt"
                self_authored.write_text("fabricated by builder\n", encoding="utf-8")
                source_root = (
                    builder_lane
                    if case == "source_root_is_builder_lane"
                    else Path(envelope["project_root"])
                )

                receipt_path = Path(envelope["probe_receipt_binding"]["path"])
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt["source_roots"] = [str(source_root.resolve())]
                receipt["read_proofs"] = [
                    {
                        "path": str(self_authored.resolve()),
                        "bytes": self_authored.stat().st_size,
                        "sha256": sha256_path(self_authored),
                    }
                ]
                receipt = seal(receipt)
                receipt_path.write_text(
                    json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                envelope["source_roots"] = [str(source_root.resolve())]
                envelope["probe_receipt_binding"] = {
                    "path": str(receipt_path.resolve()),
                    "bytes": receipt_path.stat().st_size,
                    "sha256": sha256_path(receipt_path),
                }
                envelope = seal(envelope)
                access.write_text(
                    json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                state["workspace_access_envelope"] = envelope
                state = seal(state)

                with self.assertRaisesRegex(ProtocolError, reason):
                    validate_instance(state)
                with self.assertRaisesRegex(ModeBindingError, reason):
                    _validate_workspace_access(
                        envelope_path=access,
                        envelope_sha256=sha256_path(access),
                        activation_receipt_sha256=sha256_path(activation),
                        expected_task_id=envelope["task_id"],
                        expected_task_root=Path(envelope["task_root"]),
                        expected_project_root=Path(envelope["project_root"]),
                        expected_source_roots=[source_root],
                        state=state,
                    )

    def test_workspace_probe_must_stay_in_project_control_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            envelope = json.loads(access.read_text(encoding="utf-8"))
            receipt_path = Path(envelope["probe_receipt_binding"]["path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            mutant_receipt_path = receipt_path.with_name("probe-scope-mutant.receipt.json")
            sibling_probe = Path(envelope["task_root"]) / ".omni" / "access-probes" / "probe"
            sibling_probe.parent.mkdir(parents=True, exist_ok=True)
            sibling_probe.write_text("wrong control root\n", encoding="utf-8")
            receipt.update(
                {
                    "probe_path": str(sibling_probe.resolve()),
                    "probe_bytes": sibling_probe.stat().st_size,
                    "probe_sha256": sha256_path(sibling_probe),
                }
            )
            receipt = seal(receipt)
            mutant_receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            envelope["probe_receipt_binding"] = {
                "path": str(mutant_receipt_path.resolve()),
                "bytes": mutant_receipt_path.stat().st_size,
                "sha256": sha256_path(mutant_receipt_path),
            }
            envelope = seal(envelope)
            access.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "WORKSPACE_PROBE_SCOPE_ESCAPE",
            )

    def test_probe_name_status_and_field_drift_fail_schema_runtime_and_guard(self):
        mutants = (
            ("schema", "legacy-workspace-probe"),
            ("status", "ACCESS_PROBE_PASS"),
            ("unexpected_field", "forbidden"),
        )
        for field, value in mutants:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                activation, intake, _program, _countersign, access = self._write_fixture(root)
                envelope = json.loads(access.read_text(encoding="utf-8"))
                receipt_path = Path(envelope["probe_receipt_binding"]["path"])
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt[field] = value
                receipt = seal(receipt)
                receipt_path.write_text(
                    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                )
                envelope["probe_receipt_binding"] = {
                    "path": str(receipt_path.resolve()),
                    "bytes": receipt_path.stat().st_size,
                    "sha256": sha256_path(receipt_path),
                }
                envelope = seal(envelope)
                access.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")

                probe_schema = json.loads(
                    (ROOT / "schemas" / "workspace_access_probe_receipt.schema.json")
                    .read_text(encoding="utf-8")
                )
                self.assertTrue(list(Draft202012Validator(probe_schema).iter_errors(receipt)))

                state = json.loads(intake.read_text(encoding="utf-8"))
                state["workspace_access_envelope"] = envelope
                state = seal(state)
                with self.assertRaises(ProtocolError):
                    validate_instance(state)
                with self.assertRaises(ModeBindingError):
                    _validate_workspace_access(
                        envelope_path=access,
                        envelope_sha256=sha256_path(access),
                        activation_receipt_sha256=sha256_path(activation),
                        expected_task_id=envelope["task_id"],
                        expected_task_root=Path(envelope["task_root"]),
                        expected_project_root=Path(envelope["project_root"]),
                        expected_source_roots=[Path(path) for path in envelope["source_roots"]],
                        state=state,
                    )

    def test_progressive_activation_is_bounded_and_effects_remain_pending(self):
        dossier_module = "modules/KNOWLEDGE_RESEARCH_DOSSIER"
        aware = decide_invocation(
            explicit_user_request=False,
            complexity_warrants_omni=False,
        )
        self.assertEqual(aware["activation_level"], "OMNI_AWARE")
        self.assertFalse(aware["skill_invoked"])
        self.assertFalse(aware["effect_authorized"])
        self.assertEqual(aware["access_envelope_identity"], "NONE")
        self.assertEqual(aware["artifact_grants"], [])

        bounded = decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            run_kind="REAL",
            activation_level="OMNI_MODULE",
            modules=[dossier_module],
        )
        self.assertEqual(bounded["status"], "MODULE_ACTIVATION_ALLOWED")
        self.assertEqual(bounded["modules_used"], ["KNOWLEDGE_RESEARCH_DOSSIER"])
        self.assertEqual(bounded["authority_grants"], ["NAMED_MODULE_USE"])
        self.assertEqual(bounded["effect_grants"], [])
        self.assertFalse(bounded["effect_authorized"])
        self.assertEqual(bounded["next_gate"], "NAMED_MODULE_EXECUTION")

        pending_effect = decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            run_kind="REAL",
            activation_level="OMNI_MODULE",
            modules=[dossier_module],
            effect_grants=["CREATE_FILES", "ARM_AUTOMATION"],
        )
        self.assertEqual(
            pending_effect["requested_effects"], ["CREATE_FILES", "ARM_AUTOMATION"]
        )
        self.assertEqual(pending_effect["effect_grants"], [])
        self.assertFalse(pending_effect["effect_authorized"])
        self.assertEqual(pending_effect["access_envelope_identity"], "PENDING")
        self.assertEqual(pending_effect["next_gate"], "WORKSPACE_ACCESS_ENVELOPE")
        self.assertIn("ARM_AUTOMATION", pending_effect["non_grants"])

    def test_module_aliases_unknown_surfaces_and_escalation_fail_closed(self):
        dossier_module = "modules/KNOWLEDGE_RESEARCH_DOSSIER"
        for alias in (".", "SKILL.md"):
            with self.subTest(alias=alias), self.assertRaisesRegex(
                ValueError, "MODULE_SCOPE_TOO_BROAD"
            ):
                decide_invocation(
                    explicit_user_request=True,
                    complexity_warrants_omni=False,
                    run_kind="REAL",
                    activation_level="OMNI_MODULE",
                    modules=[alias],
                )
        with self.assertRaisesRegex(ValueError, "UNKNOWN_MODULE_REQUESTED"):
            decide_invocation(
                explicit_user_request=True,
                complexity_warrants_omni=False,
                run_kind="REAL",
                activation_level="OMNI_MODULE",
                modules=["modules/not-packaged"],
            )
        for reserved in (
            "NUL", "nul", "NUL.", "NUL ", "CON", "PRN", "AUX",
            "COM1", "COM9", "LPT1", "LPT9", "scripts/NUL",
            "NUL:stream", "C:schemas",
        ):
            with self.subTest(reserved=reserved), self.assertRaisesRegex(
                ValueError, "UNKNOWN_MODULE_REQUESTED"
            ):
                decide_invocation(
                    explicit_user_request=True,
                    complexity_warrants_omni=False,
                    run_kind="REAL",
                    activation_level="OMNI_MODULE",
                    modules=[reserved],
                )
        with self.assertRaisesRegex(
            ValueError, "OMNI_MODULE_REQUIRES_ONE_REAL_MODULE"
        ):
            decide_invocation(
                explicit_user_request=True,
                complexity_warrants_omni=False,
                run_kind="REAL",
                activation_level="OMNI_MODULE",
                modules=[dossier_module, f"{dossier_module}/module.json"],
            )
        with self.assertRaisesRegex(ValueError, "MODULE_CANNOT_ESCALATE_TO_FULL"):
            decide_invocation(
                explicit_user_request=True,
                complexity_warrants_omni=False,
                run_kind="REAL",
                activation_level="OMNI_FULL",
                modules=[dossier_module],
            )
        with self.assertRaisesRegex(ValueError, "ARM_AUTOMATION_REQUIRES_CREATE_FILES"):
            decide_invocation(
                explicit_user_request=True,
                complexity_warrants_omni=False,
                run_kind="REAL",
                activation_level="OMNI_MODULE",
                modules=[dossier_module],
                effect_grants=["ARM_AUTOMATION"],
            )

    def test_arbitrary_nonempty_file_cannot_impersonate_fused_program(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            program.write_text(
                "# Narrative only\n\nI claim to be fused and counter-signed.\n",
                encoding="utf-8",
            )
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertTrue(
                json.loads(blocked.stdout)["reason_code"].startswith("PROGRAM_JSON_INVALID")
            )

    def test_program_and_countersign_internal_tamper_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            record = json.loads(program.read_text(encoding="utf-8"))
            record["work_items"][0]["title"] = "Tampered after sealing"
            program.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_RECORD_DIGEST_INVALID",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            receipt = json.loads(countersign.read_text(encoding="utf-8"))
            receipt["program_binding"]["bytes"] += 1
            countersign.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_COUNTERSIGN_RECORD_DIGEST_INVALID",
            )

    def test_uncountersigned_program_and_declined_receipt_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            record = json.loads(program.read_text(encoding="utf-8"))
            record["status"] = "PROGRAM_FUSION_DRAFT"
            record = seal(record)
            program.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(json.loads(blocked.stdout)["reason_code"], "PROGRAM_STATUS_INVALID")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            receipt = json.loads(countersign.read_text(encoding="utf-8"))
            receipt["status"] = "PROGRAM_COUNTERSIGN_BLOCKED"
            receipt["decision"] = "BLOCK"
            receipt["finding_codes"] = ["PROGRAM_REJECTED"]
            receipt = seal(receipt)
            countersign.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_COUNTERSIGN_STATUS_INVALID",
            )

    def test_countersign_must_bind_exact_program_and_independent_verifier_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            program_record = json.loads(program.read_text(encoding="utf-8"))
            program_record["work_items"][0]["title"] = "Mutated candidate"
            program_record = seal(program_record)
            program.write_text(
                json.dumps(program_record, indent=2) + "\n",
                encoding="utf-8",
            )
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_COUNTERSIGN_PROGRAM_BINDING_BYTES_MISMATCH",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            state = json.loads(intake.read_text(encoding="utf-8"))
            receipt = json.loads(countersign.read_text(encoding="utf-8"))
            receipt["signer_session_id"] = state["session_pair"]["builder"]["session_id"]
            receipt = seal(receipt)
            countersign.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_COUNTERSIGN_SIGNER_INVALID",
            )

    def test_v1_program_and_countersign_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            record = json.loads(program.read_text(encoding="utf-8"))
            record["schema"] = "omni-fused-program-v1"
            record = seal(record)
            program.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_SCHEMA_INVALID",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            receipt = json.loads(countersign.read_text(encoding="utf-8"))
            receipt["schema"] = "omni-program-countersign-receipt-v1"
            receipt = seal(receipt)
            countersign.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_COUNTERSIGN_SCHEMA_INVALID",
            )

    def test_mode_requires_complete_baptism_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            args = self._bound_args(activation, intake, program, countersign, access)
            for flag in (
                "--program-baptism-receipt",
                "--program-baptism-receipt-sha256",
            ):
                index = args.index(flag)
                del args[index : index + 2]
            blocked = self._run(*args)
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "MODE_BINDING_ARGUMENTS_INCOMPLETE",
            )

    def test_baptism_must_bind_exact_bytes_and_external_sovereign(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            receipt_path = root / "program-baptism-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["pm_decision_binding"]["bytes"] += 1
            receipt = seal(receipt)
            receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_BAPTISM_RECEIPT_PM_DECISION_BINDING_BYTES_MISMATCH",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            args = self._bound_args(activation, intake, program, countersign, access)
            args[args.index("--expected-sovereign-id") + 1] = "UNTRUSTED-SOVEREIGN"
            blocked = self._run(*args)
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertEqual(
                json.loads(blocked.stdout)["reason_code"],
                "PROGRAM_BAPTISM_SOVEREIGN_MISMATCH",
            )

    def test_legacy_narrative_flags_cannot_cross_mode_gate(self):
        completed = self._run(
            "--explicit-user-request",
            "--run-kind",
            "REAL",
            "--intake-complete",
            "--program-presented",
            "--program-sha256",
            "A" * 64,
        )
        self.assertEqual(completed.returncode, 2)
        output = json.loads(completed.stdout)
        self.assertEqual(output["status"], "BLOCKED")
        self.assertIn("CLI_ARGUMENT_INVALID", output["reason_code"])

    def test_tampered_external_or_internal_intake_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            args = self._bound_args(activation, intake, program, countersign, access)
            args[args.index("--intake-state-sha256") + 1] = "F" * 64
            external = self._run(*args)
            self.assertEqual(external.returncode, 2)
            self.assertEqual(
                json.loads(external.stdout)["reason_code"],
                "INTAKE_STATE_FILE_SHA256_MISMATCH",
            )

            state = json.loads(intake.read_text(encoding="utf-8"))
            state["state_id"] = "TAMPERED"
            intake.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            internal = self._run(*self._bound_args(activation, intake, program, countersign, access))
            self.assertEqual(internal.returncode, 2)
            self.assertEqual(
                json.loads(internal.stdout)["reason_code"],
                "INTAKE_STATE_RECORD_DIGEST_INVALID",
            )

    def test_not_ready_state_and_declined_activation_receipt_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            state = json.loads(intake.read_text(encoding="utf-8"))
            state["phase"] = "QUESTIONS_ACTIVE"
            state["status"] = "ACTIVE"
            state = seal(state)
            intake.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            not_ready = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(not_ready.returncode, 2)
            self.assertEqual(json.loads(not_ready.stdout)["reason_code"], "INTAKE_STATE_NOT_READY")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            declined = decide_invocation(
                explicit_user_request=False,
                complexity_warrants_omni=True,
                consent_state="DECLINED",
                grounds=("MULTI_PHASE_WORK",),
                run_kind="REAL",
            )
            activation, intake, program, countersign, access = self._write_fixture(
                root, activation_decision=declined, validate_state=False,
            )
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn(
                json.loads(blocked.stdout)["reason_code"],
                {
                    "ACTIVATION_RECEIPT_NOT_ALLOWED",
                    "INTAKE_STATE_SEMANTIC_INVALID:ACTIVATION_NOT_ALLOWED",
                    "INTAKE_STATE_SEMANTIC_INVALID:RECORD_SCHEMA_INVALID:activation_binding/access_envelope_identity:const",
                },
            )

    def test_activation_binding_bytes_path_sha_and_replay_are_not_narrative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(root)
            state = json.loads(intake.read_text(encoding="utf-8"))
            state["activation_binding"]["sha256"] = "0" * 64
            state = seal(state)
            intake.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn(
                json.loads(blocked.stdout)["reason_code"],
                {
                    "ACTIVATION_BINDING_SHA256_MISMATCH",
                    "INTAKE_STATE_SEMANTIC_INVALID:ACTIVATION_RECEIPT_MISMATCH",
                },
            )

    def test_solo_dual_hat_requires_one_sovereign_identity_in_two_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activation, intake, program, countersign, access = self._write_fixture(
                root, topology="SOLO_DUAL_HAT",
            )
            state = json.loads(intake.read_text(encoding="utf-8"))
            pair = state["session_pair"]
            pair["verifier"]["identity"] = "Different sovereign"
            pair["pair_sha256"] = guided_digest(pair, "pair_sha256")
            state["relay"]["session_pair_sha256"] = pair["pair_sha256"]
            state["team_card"]["session_pair_sha256"] = pair["pair_sha256"]
            state["intake_proposal"]["session_pair_sha256"] = pair["pair_sha256"]
            envelope = state["workspace_access_envelope"]
            receipt_path = Path(envelope["probe_receipt_binding"]["path"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["session_pair_sha256"] = pair["pair_sha256"]
            receipt = seal(receipt)
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            envelope["session_pair_sha256"] = pair["pair_sha256"]
            envelope["probe_receipt_binding"] = {
                "path": str(receipt_path.resolve()),
                "bytes": receipt_path.stat().st_size,
                "sha256": sha256_path(receipt_path),
            }
            envelope = seal(envelope)
            state["workspace_access_envelope"] = envelope
            access.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
            card = state["team_card"]
            card["card_sha256"] = guided_digest(card, "card_sha256", "acks")
            for ack in card["acks"].values():
                ack["observed_card_sha256"] = card["card_sha256"]
            for relay in state["relay"]["records"]:
                if relay["kind"] == "TEAM_CARD" or (
                    relay["kind"] == "READBACK"
                    and relay["payload_sha256"] != state["intake_proposal"]["proposal"]["sha256"]
                    and relay["ordinal"] <= 3
                ):
                    relay["payload_sha256"] = card["card_sha256"]
            state = seal(state)
            intake.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            blocked = self._run(
                *self._bound_args(activation, intake, program, countersign, access)
            )
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertIn(
                json.loads(blocked.stdout)["reason_code"],
                {
                    "SOLO_SOVEREIGN_IDENTITY_MISMATCH",
                    "INTAKE_STATE_SEMANTIC_INVALID:INDEPENDENCE_PROFILE_MISMATCH",
                },
            )

    def test_activation_tokens_match_guided_intake_vocabulary(self):
        explicit = decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            run_kind="REAL",
            activation_level="OMNI_FULL",
        )
        proposed = decide_invocation(
            explicit_user_request=False,
            complexity_warrants_omni=True,
            consent_state="ACCEPTED",
            grounds=("MULTI_PHASE_WORK",),
            run_kind="REAL",
            activation_level="OMNI_FULL",
        )
        self.assertEqual(explicit["activation_path"], "EXPLICIT_USER_OPT_IN")
        self.assertEqual(proposed["activation_path"], "PROPOSAL_ACCEPTED")


if __name__ == "__main__":
    unittest.main()

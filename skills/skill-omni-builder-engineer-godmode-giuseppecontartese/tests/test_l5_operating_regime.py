from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "operating_regime.py"
SPEC = importlib.util.spec_from_file_location("operating_regime_l5", SCRIPT)
assert SPEC and SPEC.loader
L5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(L5)


NOW = "2026-07-30T12:00:00Z"
PAIR = "A" * 64
PM_ISSUER = "PM.GIUSEPPE"


class L5Fixture:
    def __init__(self, base: Path, regime: str = "AUTONOMOUS", suffix: str = "A") -> None:
        self.base = base
        self.project = base / "project"
        self.channel = base / "channel"
        self.artifacts = base / "artifacts"
        for path in (self.project, self.channel, self.artifacts):
            path.mkdir(parents=True, exist_ok=True)
        self.task_id = "TASK1"
        self.program_id = "PROG1"
        self.pipeline_id = "PIPE1"
        self.builder = "builder-session"
        self.verifier = "verifier-session"
        self.binding_id = f"REGIME.{suffix}"
        self.dummy_path, self.dummy_binding, _ = self.write(
            self.artifacts / "dummy.json",
            {"schema": "omni-test-evidence-v1", "status": "PASS", "id": "EVIDENCE1"},
        )
        self.program_path, self.program_binding, self.program = self._program()
        self.countersign_path, self.countersign_binding, self.countersign = self._countersign()
        self.pm_path, self.pm_binding, self.pm_record = self._pm_selection(regime)
        self.binding_path, self.regime_binding, self.binding = self._regime(regime)

    @staticmethod
    def seal(value: dict) -> dict:
        return L5.seal(value)

    def write(self, path: Path, value: dict) -> tuple[Path, dict, dict]:
        sealed = self.seal(value)
        raw = (L5.canonical_json(sealed) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path, {"path": str(path.resolve()), "bytes": len(raw), "sha256": L5.sha256_bytes(raw)}, sealed

    def rewrite(self, path: Path, value: dict) -> tuple[Path, dict, dict]:
        return self.write(path, {key: item for key, item in value.items() if key != "record_digest"})

    def pm_authorize(
        self, body: dict, *, authority_kind: str, subject_id: str, filename: str,
    ) -> dict:
        receipt = {
            "schema": L5.PM_AUTHORITY_SCHEMA, "status": "AUTHORIZED",
            "decision": "AUTHORIZED", "issuer_id": PM_ISSUER,
            "authority_kind": authority_kind, "task_id": self.task_id,
            "program_id": self.program_id, "session_pair_sha256": PAIR,
            "subject_schema": body["schema"], "subject_id": subject_id,
            "subject_payload_sha256": L5._authority_payload_digest(body),
            "one_shot": True,
        }
        _, binding, _ = self.write(self.channel / filename, receipt)
        body["pm_authority_record_binding"] = binding
        return body

    def _program(self):
        body = {
            "schema": "omni-fused-program-v2", "kind": "PROGRAM_FUSION_CANDIDATE",
            "status": "PROGRAM_FUSION_FROZEN", "program_id": self.program_id,
            "task_id": self.task_id, "knowledge_pipeline_id": self.pipeline_id,
            "knowledge_state_binding": self.dummy_binding,
            "knowledge_fusion_countersign_binding": self.dummy_binding,
            "canonical_knowledge_binding": self.dummy_binding,
            "session_pair_sha256": PAIR, "author_role": "BUILDER",
            "author_session_id": self.builder, "topology": "TEAM_DUAL_LANE",
            "profile": "GODMODE", "run_kind": "REAL",
            "fused_from_lanes": ["BUILDER", "VERIFIER"],
            "builder_plan_manifest_binding": self.dummy_binding,
            "verifier_plan_manifest_binding": self.dummy_binding,
            "fusion_decision_register_binding": self.dummy_binding,
            "fused_plan_draft_binding": self.dummy_binding,
            "work_items": [{
                "work_id": "WORK1", "ordinal": 1, "title": "Build", "result": "Verified artifact",
                "persistent_artifact": {"path": str((self.project / "result.json").resolve()), "create_policy": "CREATE_ONCE", "owner_role": "BUILDER"},
                "owner_role": "BUILDER", "depends_on": [], "preconditions": ["PROGRAM_COUNTERSIGN_ACCEPTED"],
                "required_capabilities": ["FILE_WRITE"],
                "budget": {"max_turns": 10, "max_tool_calls": 20, "max_elapsed_seconds": 3600},
                "acceptance_evidence": [{"evidence_id": "EV1", "description": "Test", "kind": "TEST_REPORT"}],
                "verifier_role": "VERIFIER", "rollback": {"strategy": "SAFE_PARK", "steps": ["Stop"]},
                "failure_states": ["BLOCKED_PENDING_HUMAN", "INCONCLUSIVE"], "next_gate": "F4_TEST",
                "scope": ["F3_BUILD", "F4_TEST"],
                "origin_refs": [{"role": "BUILDER", "work_id": "B1"}, {"role": "VERIFIER", "work_id": "V1"}],
            }],
            "preserved_alternative_ids": [], "preserved_dissent_ids": [], "created_at": NOW,
        }
        return self.write(self.artifacts / "program.json", body)

    def _countersign(self):
        body = {
            "schema": "omni-program-countersign-receipt-v2", "status": "PROGRAM_COUNTERSIGN_ACCEPTED",
            "decision": "ACCEPTED", "receipt_id": "PROGRAM.COUNTERSIGN1", "program_id": self.program_id,
            "task_id": self.task_id, "knowledge_pipeline_id": self.pipeline_id,
            "program_binding": self.program_binding, "program_record_digest": self.program["record_digest"],
            "knowledge_state_binding": self.dummy_binding,
            "knowledge_fusion_countersign_binding": self.dummy_binding,
            "session_pair_sha256": PAIR, "program_author_session_id": self.builder,
            "signer_role": "VERIFIER", "signer_session_id": self.verifier,
            "verifier_report_binding": self.dummy_binding,
            "reproduction": {
                "schema_valid": True, "dag_valid": True, "full_wbs_valid": True,
                "origin_coverage_complete": True, "alternatives_preserved": True,
                "dissent_preserved": True, "no_shared_writer": True,
                "no_oracle_before_dual_freeze": True, "exact_bindings": True,
            },
            "finding_codes": [], "evidence_bindings": [self.dummy_binding], "created_at": NOW,
        }
        return self.write(self.artifacts / "countersign.json", body)

    def _pm_selection(self, regime: str):
        body = {
            "schema": "omni-operating-regime-pm-binding-v1", "status": "AUTHORIZED",
            "decision": "AUTHORIZED", "issuer_id": PM_ISSUER,
            "binding_id": self.binding_id, "task_id": self.task_id,
            "program_id": self.program_id, "regime": regime, "session_pair_sha256": PAIR,
            "selection_nonce": f"SELECT.{self.binding_id}", "reserved_gate": "OPERATING_REGIME_BINDING",
            "effects_authorized": False,
        }
        return self.write(self.channel / f"pm_{self.binding_id}.json", body)

    def _regime(self, regime: str):
        body = {
            "schema": "omni-operating-regime-binding-v1", "status": "OPERATING_REGIME_BOUND",
            "decision": "BOUND", "binding_id": self.binding_id, "task_id": self.task_id,
            "program_id": self.program_id, "knowledge_pipeline_id": self.pipeline_id,
            "regime": regime, "fused_program_binding": self.program_binding,
            "program_countersign_binding": self.countersign_binding,
            "program_record_digest": self.program["record_digest"],
            "countersign_record_digest": self.countersign["record_digest"],
            "session_pair_sha256": PAIR, "subject_role": "BUILDER",
            "subject_session_id": self.builder, "official_channel_root": str(self.channel.resolve()),
            "pm_channel_record_binding": self.pm_binding, "selection_nonce": f"SELECT.{self.binding_id}",
            "effects_authorized": False, "automation_armed": False,
            "non_grants": ["AUTONOMY", "ARM_AUTOMATION", "SENTINEL_AUTHORITY", "F5_DELIVERY", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS"],
            "created_at": NOW,
        }
        return self.write(self.artifacts / f"regime_{self.binding_id}.json", body)

    def bind(self):
        return L5.bind_regime(
            binding_path=self.binding_path, binding_sha256=self.regime_binding["sha256"],
            program_path=self.program_path, program_sha256=self.program_binding["sha256"],
            countersign_path=self.countersign_path, countersign_sha256=self.countersign_binding["sha256"],
            state_root=self.project, trusted_pm_root=self.channel,
            trusted_pm_issuer_id=PM_ISSUER,
        )

    def state0(self):
        path = self.project / ".omni-operating" / "states" / "STATE_000000.json"
        raw = path.read_bytes()
        return path, {"path": str(path.resolve()), "bytes": len(raw), "sha256": L5.sha256_bytes(raw)}, json.loads(raw)

    def guided_authority(
        self, state_binding: dict, automation: bool = False,
        idempotency_key: str = "GUIDED.OP1",
    ):
        action = "BUILD1"
        nonce = "GUIDED.TURN1"
        effects = ["F3_BUILD", "PROJECT_WRITE"]
        channel_body = {
            "schema": "omni-guided-pm-channel-authority-v1", "status": "AUTHORIZED",
            "decision": "AUTHORIZED", "issuer_id": PM_ISSUER,
            "binding_id": self.binding_id, "task_id": self.task_id,
            "program_id": self.program_id, "action_id": action,
            "idempotency_key": idempotency_key, "operation_nonce": nonce,
            "session_pair_sha256": PAIR, "subject_session_id": self.builder,
            "authorized_effects": effects,
            "target_paths": [str(self.dummy_path.resolve())],
            "output_paths": [str((self.project / "result.json").resolve())],
            "automation_authorized": automation,
        }
        _, channel_binding, _ = self.write(self.channel / "guided_turn1.json", channel_body)
        authority = {
            "schema": "omni-guided-pm-turn-authority-v1", "status": "GUIDED_PM_TURN_AUTHORIZED",
            "decision": "AUTHORIZED", "turn_authority_id": "TURN.AUTH1", "binding_id": self.binding_id,
            "task_id": self.task_id, "program_id": self.program_id, "session_pair_sha256": PAIR,
            "subject_role": "BUILDER", "subject_session_id": self.builder,
            "action_id": action, "idempotency_key": idempotency_key,
            "authorized_effects": effects, "official_channel_record_binding": channel_binding,
            "expected_previous_state_binding": state_binding, "input_bindings": [self.dummy_binding],
            "target_paths": [str(self.dummy_path.resolve())],
            "output_paths": [str((self.project / "result.json").resolve())], "operation_nonce": nonce,
            "one_shot": True, "automation_authorized": automation,
            "non_grants": ["AUTONOMY", "ARM_AUTOMATION", "SENTINEL_ARMING", "WAKEUP", "RETRY", "SCHEDULE", "BACKGROUND_JOB", "F5_DELIVERY", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS"],
            "created_at": NOW,
        }
        return self.write(self.artifacts / "guided_authority.json", authority)

    def autonomous_inputs(self, state_binding: dict, *, context_state: str = "HEALTHY", denominator: int = 100):
        objective_body = {
            "schema": "omni-persistent-objective-v1", "status": "OBJECTIVE_BOUND",
            "objective_id": "OBJECTIVE1", "task_id": self.task_id, "program_id": self.program_id,
            "session_pair_sha256": PAIR,
            "program_countersign_binding": self.countersign_binding,
            "description": "Build and verify the program", "completion_definition": "All terminal proofs pass",
            "satisfiability": {"status": "PROVEN_SATISFIABLE", "proof_bindings": [self.dummy_binding], "blocking_assumptions": []},
            "terminal_verification_mode": "ALL_PHYSICAL",
            "terminal_conditions": [{"condition_id": "TC1", "evaluator": "TEST_REPORT_PASS", "subject_binding": self.dummy_binding, "json_pointer": "/status", "expected_value": "PASS", "observable": True, "proof_required": True}],
            "stop_conditions": ["OBJECTIVE_ACHIEVED", "KILL_SWITCH_OPEN", "BUDGET_EXHAUSTED", "AUTHORITY_REVOKED", "BLOCKING_FAILURE"],
            "budgets": {"max_turns": 10, "max_tool_calls": 20, "max_writes": 10, "max_elapsed_seconds": 3600, "max_rearms": 2},
            "scope": ["F3_BUILD", "F4_TEST"], "forbidden_effects": ["F5_DELIVERY", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS"], "created_at": NOW,
        }
        objective_body = self.pm_authorize(
            objective_body, authority_kind="OBJECTIVE", subject_id="OBJECTIVE1",
            filename="pm_objective.json",
        )
        objective_path, objective_binding, objective = self.write(self.artifacts / "objective.json", objective_body)
        autonomy_body = {
            "schema": "omni-autonomy-authority-v1", "status": "AUTONOMY_AUTHORIZED", "decision": "AUTHORIZED",
            "authority_id": "AUTONOMY.AUTH1", "task_id": self.task_id, "program_id": self.program_id,
            "knowledge_pipeline_id": self.pipeline_id, "operating_binding": self.regime_binding,
            "fused_program_binding": self.program_binding, "program_countersign_binding": self.countersign_binding,
            "objective_binding": objective_binding, "session_pair_sha256": PAIR, "subject_role": "BUILDER",
            "subject_session_id": self.builder, "authority_generation": 1, "scope": ["F3_BUILD", "F4_TEST"],
            "authorized_actions": ["PROJECT_WRITE"],
            "authorized_action_ids": ["AUTO.ACTION1", "AUTO.ACTION2", "AUTO.ACTION3", "AUTO.ACTION4", "AUTO.ACTION5", "AUTO.ACTION6", "AUTO.ACTION7", "AUTO.ACTION8", "AUTO.ACTION9", "AUTO.ACTION10", "AUTO.ACTION11", "AUTO.ACTION12"],
            "authorized_operations": [
                {
                    "effect": "PROJECT_WRITE", "action_id": f"AUTO.ACTION{index}",
                    "target_path": str(self.dummy_path.resolve()),
                    "output_path": str((self.project / "result.json").resolve()),
                    "idempotency_key": f"AUTO.OP{index}", "one_shot": True,
                }
                for index in range(1, 13)
            ],
            "authorized_target_paths": [str(self.dummy_path.resolve())],
            "authorized_output_paths": [str((self.project / "result.json").resolve())],
            "budgets": {"max_turns": 10, "max_tool_calls": 20, "max_writes": 10, "max_elapsed_seconds": 3600},
            "activation_nonce": "AUTONOMY.NONCE1", "one_activation": True, "automation_authorized": False,
            "non_grants": ["ARM_AUTOMATION", "SENTINEL_AUTHORITY", "F5_DELIVERY", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS"], "created_at": NOW,
        }
        autonomy_body = self.pm_authorize(
            autonomy_body, authority_kind="AUTONOMY", subject_id="AUTONOMY.AUTH1",
            filename="pm_autonomy.json",
        )
        autonomy_path, autonomy_binding, autonomy = self.write(self.artifacts / "autonomy.json", autonomy_body)
        kill_body = {"schema": "omni-kill-switch-v1", "state": "CLOSED", "task_id": self.task_id, "program_id": self.program_id, "generation": 1}
        kill_path, kill_binding, kill = self.write(self.channel / "kill_switch.json", kill_body)
        arm_body = {
            "schema": "omni-automation-arm-authority-v1", "status": "ARM_AUTOMATION_AUTHORIZED", "decision": "AUTHORIZED",
            "authority_id": "ARM.AUTH1", "task_id": self.task_id, "program_id": self.program_id,
            "operating_binding": self.regime_binding, "autonomy_authority_binding": autonomy_binding,
            "objective_binding": objective_binding, "session_pair_sha256": PAIR, "subject_role": "BUILDER",
            "subject_session_id": self.builder, "sentinel_types": ["AGENTIC", "SCRIPT", "CONTEXT"],
            "script_supervisor": {"namespace": "PROJECT.SUPERVISOR", "generation": 1, "heartbeat_interval_seconds": 30, "max_missed_heartbeats": 3, "rearm_budget": 2},
            "agentic_sentinel": {"sentinel_id": "AGENTIC1", "objective_id": "OBJECTIVE1", "generation": 1},
            "context_sentinel": {"sentinel_id": "CONTEXT1", "generation": 1, "denominator": denominator, "warn_threshold": 70, "rotate_threshold": 90},
            "kill_switch": {"path": str(kill_path.resolve()), "initial_binding": kill_binding, "initial_generation": 1, "closed_token": "CLOSED", "open_token": "OPEN"},
            "arm_nonce": "ARM.NONCE1", "one_activation": True, "project_effects_authorized": False,
            "non_grants": ["PROJECT_EXECUTION", "SENTINEL_AUTHORITY", "F5_DELIVERY", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS"], "created_at": NOW,
        }
        arm_body = self.pm_authorize(
            arm_body, authority_kind="ARM_AUTOMATION", subject_id="ARM.AUTH1",
            filename="pm_arm.json",
        )
        arm_path, arm_binding, arm = self.write(self.artifacts / "arm.json", arm_body)
        observed = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        expires = observed + dt.timedelta(seconds=60)
        observed_at = observed.isoformat().replace("+00:00", "Z")
        expires_at = expires.isoformat().replace("+00:00", "Z")
        physical_bodies = {
            "agentic": {"schema": "omni-agentic-sentinel-physical-receipt-v1", "status": "READY", "state": "ARMED", "task_id": self.task_id, "program_id": self.program_id, "owner_session_id": self.builder, "sentinel_id": "AGENTIC1", "objective_id": "OBJECTIVE1", "generation": 1, "arm_authority_id": "ARM.AUTH1", "heartbeat_seq": 1, "observed_at": observed_at, "expires_at": expires_at, "dead_man_state": "ARMED", "grants_authority": False},
            "script": {"schema": "omni-script-sentinel-physical-receipt-v1", "status": "READY", "state": "CHILD_RUNNING", "task_id": self.task_id, "program_id": self.program_id, "owner_session_id": self.builder, "sentinel_id": "SCRIPT1", "namespace": "PROJECT.SUPERVISOR", "generation": 1, "rearm_budget_remaining": 2, "arm_authority_id": "ARM.AUTH1", "heartbeat_seq": 1, "observed_at": observed_at, "expires_at": expires_at, "last_heartbeat_at": observed_at, "heartbeat_interval_seconds": 30, "max_missed_heartbeats": 3, "dead_man_state": "ARMED", "grants_authority": False},
            "context": {"schema": "omni-context-sentinel-physical-receipt-v1", "status": "READY", "state": context_state, "task_id": self.task_id, "program_id": self.program_id, "owner_session_id": self.builder, "sentinel_id": "CONTEXT1", "generation": 1, "denominator": denominator, "warn_threshold": 70, "rotate_threshold": 90, "arm_authority_id": "ARM.AUTH1", "heartbeat_seq": 1, "observed_at": observed_at, "expires_at": expires_at, "dead_man_state": "ARMED", "grants_authority": False},
        }
        physical = {}
        for name, body in physical_bodies.items():
            _, item_binding, item = self.write(self.artifacts / f"{name}_physical.json", body)
            physical[name] = (item_binding, item)
        bundle_body = {
            "schema": "omni-sentinel-bundle-receipt-v1", "status": "SENTINEL_BUNDLE_PASS", "decision": "PASS",
            "receipt_id": "SENTINELS1", "task_id": self.task_id, "program_id": self.program_id,
            "subject_session_id": self.builder, "objective_binding": objective_binding, "arm_authority_binding": arm_binding,
            "sentinels": {
                "agentic": {"kind": "AGENTIC", "sentinel_id": "AGENTIC1", "namespace": "AGENTIC.NS", "generation": 1, "owner_session_id": self.builder, "state": "ARMED", "heartbeat_seq": 1, "observed_at": observed_at, "expires_at": expires_at, "physical_receipt_binding": physical["agentic"][0], "arm_authority_binding": arm_binding, "rehydrated": True, "grants_authority": False},
                "script": {"kind": "SCRIPT", "sentinel_id": "SCRIPT1", "namespace": "PROJECT.SUPERVISOR", "generation": 1, "owner_session_id": self.builder, "state": "CHILD_RUNNING", "heartbeat_seq": 1, "observed_at": observed_at, "expires_at": expires_at, "physical_receipt_binding": physical["script"][0], "arm_authority_binding": arm_binding, "rehydrated": True, "grants_authority": False},
                "context": {"kind": "CONTEXT", "sentinel_id": "CONTEXT1", "namespace": "CONTEXT.NS", "generation": 1, "owner_session_id": self.builder, "state": context_state, "heartbeat_seq": 1, "observed_at": observed_at, "expires_at": expires_at, "physical_receipt_binding": physical["context"][0], "arm_authority_binding": arm_binding, "rehydrated": True, "grants_authority": False},
            },
            "all_physical": True, "rehydration_complete": True, "grants_authority": False,
            "finding_codes": [], "observed_at": observed_at, "expires_at": expires_at,
            "created_at": NOW,
        }
        bundle_path, bundle_binding, bundle = self.write(self.artifacts / "sentinel_bundle.json", bundle_body)
        fence_body = {
            "schema": "omni-predecessor-fencing-receipt-v1", "status": "QUIESCENT",
            "task_id": self.task_id, "program_id": self.program_id, "predecessor_session_id": "predecessor-session",
            "successor_session_id": self.builder,
            "fenced_control_classes": {name: True for name in L5.FENCED_CLASSES},
        }
        fence_path, fence_binding, fence = self.write(self.artifacts / "fencing.json", fence_body)
        return {
            "objective": (objective_path, objective_binding, objective),
            "autonomy": (autonomy_path, autonomy_binding, autonomy),
            "kill": (kill_path, kill_binding, kill), "arm": (arm_path, arm_binding, arm),
            "bundle": (bundle_path, bundle_binding, bundle), "fence": (fence_path, fence_binding, fence),
        }

    def activate(self, inputs: dict, state_path: Path, state_binding: dict):
        return L5.activate_autonomous(
            state_path=state_path, state_sha256=state_binding["sha256"],
            objective_path=inputs["objective"][0], objective_sha256=inputs["objective"][1]["sha256"],
            autonomy_authority_path=inputs["autonomy"][0], autonomy_authority_sha256=inputs["autonomy"][1]["sha256"],
            arm_authority_path=inputs["arm"][0], arm_authority_sha256=inputs["arm"][1]["sha256"],
            sentinel_bundle_path=inputs["bundle"][0], sentinel_bundle_sha256=inputs["bundle"][1]["sha256"],
            predecessor_fencing_path=inputs["fence"][0], predecessor_fencing_sha256=inputs["fence"][1]["sha256"],
            predecessor_session_id="predecessor-session", state_root=self.project,
            trusted_pm_root=self.channel, trusted_pm_issuer_id=PM_ISSUER,
        )

    def effect_args(
        self, state_binding: dict, *, action_id: str = "AUTO.ACTION1",
        idempotency_key: str = "AUTO.OP1", effect: str = "PROJECT_WRITE",
        actor: str | None = None,
    ) -> dict:
        return {
            "state_path": state_binding["path"], "state_sha256": state_binding["sha256"],
            "state_root": self.project, "effect": effect,
            "actor_session_id": actor or self.builder,
            "trusted_pm_root": self.channel, "trusted_pm_issuer_id": PM_ISSUER,
            "action_id": action_id, "target_path": self.dummy_path,
            "output_path": self.project / "result.json",
            "idempotency_key": idempotency_key,
        }

    def mutate_physical(self, inputs: dict, name: str, mutation) -> None:
        bundle = copy.deepcopy(inputs["bundle"][2])
        physical_binding = bundle["sentinels"][name]["physical_receipt_binding"]
        physical_path = Path(physical_binding["path"])
        physical = json.loads(physical_path.read_text(encoding="utf-8"))
        mutation(physical, bundle["sentinels"][name])
        _, replacement, _ = self.rewrite(physical_path, physical)
        bundle["sentinels"][name]["physical_receipt_binding"] = replacement
        bundle_path, bundle_binding, bundle = self.rewrite(inputs["bundle"][0], bundle)
        inputs["bundle"] = (bundle_path, bundle_binding, bundle)


class OperatingRegimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def assert_code(self, code: str, function, *args, **kwargs):
        with self.assertRaises(L5.OperatingError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.reason_code, code)

    def test_all_seven_schemas_are_strict_and_valid(self):
        import jsonschema
        names = [
            "operating_regime_binding.schema.json", "persistent_objective.schema.json",
            "autonomy_authority.schema.json", "automation_arm_authority.schema.json",
            "sentinel_bundle_receipt.schema.json", "execution_lease.schema.json",
            "operating_state.schema.json",
        ]
        for name in names:
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
            self.assertIs(schema.get("additionalProperties"), False)

    def test_selection_never_authorizes_effects(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        result = fixture.bind()
        self.assertEqual(result["status"], "REGIME_BOUND")
        state_path, state_binding, state = fixture.state0()
        self.assertFalse(state["effects_authorized"])
        self.assertFalse(state["automation_armed"])
        self.assert_code(
            "EXECUTION_EFFECT_UNAUTHORIZED", L5.check_effect,
            **fixture.effect_args(state_binding, effect="F3_BUILD"),
        )

    def test_mutated_selection_effect_is_rejected_with_stable_code(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        mutated = copy.deepcopy(fixture.binding)
        mutated["effects_authorized"] = True
        path, binding, _ = fixture.rewrite(fixture.binding_path, mutated)
        self.assert_code(
            "MODE_SELECTION_DOES_NOT_AUTHORIZE_EFFECTS", L5.bind_regime,
            binding_path=path, binding_sha256=binding["sha256"],
            program_path=fixture.program_path, program_sha256=fixture.program_binding["sha256"],
            countersign_path=fixture.countersign_path, countersign_sha256=fixture.countersign_binding["sha256"],
            state_root=fixture.project, trusted_pm_root=fixture.channel,
            trusted_pm_issuer_id=PM_ISSUER,
        )

    def test_guided_turn_requires_exact_pm_channel_authority_and_no_automation(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        fixture.bind()
        state_path, state_binding, _ = fixture.state0()
        authority_path, authority_binding, _ = fixture.guided_authority(state_binding)
        result = L5.activate_guided_turn(
            state_path=state_path, state_sha256=state_binding["sha256"],
            turn_authority_path=authority_path, turn_authority_sha256=authority_binding["sha256"],
            state_root=fixture.project, trusted_pm_root=fixture.channel,
            trusted_pm_issuer_id=PM_ISSUER,
        )
        self.assertEqual(result["status"], "GUIDED_TURN_READY")
        active_path = Path(result["state_binding"]["path"])
        check = L5.check_effect(**fixture.effect_args(
            result["state_binding"], action_id="BUILD1", idempotency_key="GUIDED.OP1"
        ))
        self.assertEqual(check["status"], "PASS")

        second = L5Fixture(self.root / "second", "GUIDED_PM")
        second.bind()
        state_path2, state_binding2, _ = second.state0()
        authority_path2, authority_binding2, authority2 = second.guided_authority(state_binding2, automation=True)
        self.assert_code(
            "GUIDED_PM_AUTOMATION_UNAUTHORIZED", L5.activate_guided_turn,
            state_path=state_path2, state_sha256=state_binding2["sha256"],
            turn_authority_path=authority_path2, turn_authority_sha256=authority_binding2["sha256"],
            state_root=second.project, trusted_pm_root=second.channel,
            trusted_pm_issuer_id=PM_ISSUER,
        )

    def test_guided_channel_substitution_is_blocked(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        authority_path, authority_binding, authority = fixture.guided_authority(state_binding)
        channel_path = Path(authority["official_channel_record_binding"]["path"])
        channel = json.loads(channel_path.read_text(encoding="utf-8"))
        channel["action_id"] = "OTHER"
        _, new_channel_binding, _ = fixture.rewrite(channel_path, channel)
        authority["official_channel_record_binding"] = new_channel_binding
        authority_path, authority_binding, _ = fixture.rewrite(authority_path, authority)
        self.assert_code(
            "GUIDED_PM_TURN_AUTHORITY_REQUIRED", L5.activate_guided_turn,
            state_path=state_path, state_sha256=state_binding["sha256"],
            turn_authority_path=authority_path, turn_authority_sha256=authority_binding["sha256"],
            state_root=fixture.project, trusted_pm_root=fixture.channel,
            trusted_pm_issuer_id=PM_ISSUER,
        )

    def test_autonomous_activation_requires_every_separate_gate(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        result = fixture.activate(inputs, state_path, state_binding)
        self.assertEqual(result["status"], "AUTONOMY_ACTIVE")
        self.assertTrue(result["automation_armed"])
        verify = L5.verify_state(
            state_path=result["state_binding"]["path"], state_sha256=result["state_binding"]["sha256"],
            state_root=fixture.project, expect="AUTONOMY_ACTIVE",
            trusted_pm_root=fixture.channel, trusted_pm_issuer_id=PM_ISSUER,
        )
        self.assertEqual(verify["status"], "PASS")

    def test_missing_arm_authority_is_not_implied_by_autonomy(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        self.assert_code(
            "ARM_AUTOMATION_AUTHORITY_REQUIRED", L5.activate_autonomous,
            state_path=state_path, state_sha256=state_binding["sha256"],
            objective_path=inputs["objective"][0], objective_sha256=inputs["objective"][1]["sha256"],
            autonomy_authority_path=inputs["autonomy"][0], autonomy_authority_sha256=inputs["autonomy"][1]["sha256"],
            arm_authority_path=self.root / "missing.json", arm_authority_sha256="0" * 64,
            sentinel_bundle_path=inputs["bundle"][0], sentinel_bundle_sha256=inputs["bundle"][1]["sha256"],
            predecessor_fencing_path=inputs["fence"][0], predecessor_fencing_sha256=inputs["fence"][1]["sha256"],
            predecessor_session_id="predecessor-session", state_root=fixture.project,
            trusted_pm_root=fixture.channel, trusted_pm_issuer_id=PM_ISSUER,
        )

    def test_unsatisfiable_objective_blocks(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        objective = copy.deepcopy(inputs["objective"][2])
        objective["satisfiability"]["status"] = "UNSATISFIABLE"
        objective["satisfiability"]["blocking_assumptions"] = ["Impossible dependency"]
        path, binding, _ = fixture.rewrite(inputs["objective"][0], objective)
        inputs["objective"] = (path, binding, objective)
        self.assert_code("OBJECTIVE_UNSATISFIABLE", fixture.activate, inputs, state_path, state_binding)

    def test_context_sentinel_and_unknown_denominator_block(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding, context_state="NOT_READY")
        self.assert_code("SENTINEL_CONTEXT_NOT_READY", fixture.activate, inputs, state_path, state_binding)

        fixture2 = L5Fixture(self.root / "denom", "AUTONOMOUS")
        fixture2.bind(); state_path2, state_binding2, _ = fixture2.state0()
        # Semantic preflight owns the stable denominator code even though the
        # JSON Schema would also reject zero.
        inputs2 = fixture2.autonomous_inputs(state_binding2)
        arm = copy.deepcopy(inputs2["arm"][2]); arm["context_sentinel"]["denominator"] = 0
        arm_path, arm_binding, arm = fixture2.rewrite(inputs2["arm"][0], arm)
        inputs2["arm"] = (arm_path, arm_binding, arm)
        self.assert_code("HOST_CONTEXT_DENOMINATOR_UNKNOWN", fixture2.activate, inputs2, state_path2, state_binding2)

    def test_closed_kill_switch_substitution_before_activation_blocks(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        kill = copy.deepcopy(inputs["kill"][2])
        kill["generation"] = 2
        fixture.rewrite(inputs["kill"][0], kill)
        self.assert_code("KILL_SWITCH_BINDING_REQUIRED", fixture.activate, inputs, state_path, state_binding)

    def test_zero_script_rearm_budget_is_exhausted(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        bundle = copy.deepcopy(inputs["bundle"][2])
        script_binding = bundle["sentinels"]["script"]["physical_receipt_binding"]
        script_path = Path(script_binding["path"])
        script = json.loads(script_path.read_text(encoding="utf-8"))
        script["rearm_budget_remaining"] = 0
        _, replacement_binding, _ = fixture.rewrite(script_path, script)
        bundle["sentinels"]["script"]["physical_receipt_binding"] = replacement_binding
        bundle_path, bundle_binding, bundle = fixture.rewrite(inputs["bundle"][0], bundle)
        inputs["bundle"] = (bundle_path, bundle_binding, bundle)
        self.assert_code("SUPERVISOR_BUDGET_EXHAUSTED", fixture.activate, inputs, state_path, state_binding)

    def test_predecessor_wakeup_must_be_fenced(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        fence = copy.deepcopy(inputs["fence"][2])
        fence["fenced_control_classes"]["AUTOMATION"] = False
        path, binding, fence = fixture.rewrite(inputs["fence"][0], fence)
        inputs["fence"] = (path, binding, fence)
        self.assert_code("PREDECESSOR_WAKEUP_UNFENCED", fixture.activate, inputs, state_path, state_binding)

    def test_effect_guard_enforces_owner_kill_switch_and_forbidden_f5(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        result = fixture.activate(inputs, state_path, state_binding)
        active = result["state_binding"]
        self.assert_code(
            "EXECUTION_LEASE_OWNER_MISMATCH", L5.check_effect,
            **fixture.effect_args(active, effect="F3_BUILD", actor="intruder"),
        )
        self.assert_code(
            "F5_AUTHORITY_FORBIDDEN", L5.check_effect,
            **fixture.effect_args(active, effect="F5_DELIVERY"),
        )
        kill = copy.deepcopy(inputs["kill"][2]); kill["state"] = "OPEN"
        fixture.rewrite(inputs["kill"][0], kill)
        self.assert_code(
            "KILL_SWITCH_OPEN", L5.check_effect,
            **fixture.effect_args(active, effect="PROJECT_WRITE"),
        )

    def test_trusted_pm_root_and_issuer_are_external_non_self_declared_inputs(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        self.assert_code(
            "TRUSTED_PM_ROOT_REQUIRED", L5.bind_regime,
            binding_path=fixture.binding_path, binding_sha256=fixture.regime_binding["sha256"],
            program_path=fixture.program_path, program_sha256=fixture.program_binding["sha256"],
            countersign_path=fixture.countersign_path,
            countersign_sha256=fixture.countersign_binding["sha256"],
            state_root=fixture.project, trusted_pm_root=fixture.artifacts,
            trusted_pm_issuer_id=PM_ISSUER,
        )
        self.assert_code(
            "TRUSTED_PM_ISSUER_REQUIRED", L5.bind_regime,
            binding_path=fixture.binding_path, binding_sha256=fixture.regime_binding["sha256"],
            program_path=fixture.program_path, program_sha256=fixture.program_binding["sha256"],
            countersign_path=fixture.countersign_path,
            countersign_sha256=fixture.countersign_binding["sha256"],
            state_root=fixture.project, trusted_pm_root=fixture.channel,
            trusted_pm_issuer_id="PM.ATTACKER",
        )

    def test_guided_one_shot_is_consumed_and_exact_retry_is_read_only(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        authority_path, authority_binding, _ = fixture.guided_authority(state_binding)
        ready = L5.activate_guided_turn(
            state_path=state_path, state_sha256=state_binding["sha256"],
            turn_authority_path=authority_path,
            turn_authority_sha256=authority_binding["sha256"],
            state_root=fixture.project, trusted_pm_root=fixture.channel,
            trusted_pm_issuer_id=PM_ISSUER,
        )
        args = fixture.effect_args(
            ready["state_binding"], action_id="BUILD1",
            idempotency_key="GUIDED.OP1",
        )
        wrong_key = dict(args); wrong_key["idempotency_key"] = "GUIDED.OTHER1"
        self.assert_code("EXECUTION_IDEMPOTENCY_REQUIRED", L5.check_effect, **wrong_key)
        first = L5.check_effect(**args)
        self.assertTrue(first["execute_effect"])
        replay = L5.check_effect(**args)
        self.assertEqual(replay["status"], "IDEMPOTENT_REPLAY")
        self.assertFalse(replay["execute_effect"])
        different = dict(args); different["idempotency_key"] = "GUIDED.OTHER1"
        self.assert_code("GUIDED_PM_TURN_AUTHORITY_REQUIRED", L5.check_effect, **different)

    def test_effect_requires_exact_action_target_and_output(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        active = fixture.activate(inputs, state_path, state_binding)["state_binding"]
        wrong_action = fixture.effect_args(active, action_id="NOT.AUTHORIZED")
        self.assert_code("EXECUTION_ACTION_BINDING_REQUIRED", L5.check_effect, **wrong_action)
        wrong_target = fixture.effect_args(active); wrong_target["target_path"] = fixture.project / "other.json"
        self.assert_code("EXECUTION_TARGET_UNAUTHORIZED", L5.check_effect, **wrong_target)
        wrong_output = fixture.effect_args(active); wrong_output["output_path"] = fixture.project / "other.json"
        self.assert_code("EXECUTION_OUTPUT_UNAUTHORIZED", L5.check_effect, **wrong_output)
        unknown_key = fixture.effect_args(active); unknown_key["idempotency_key"] = "AUTO.UNKNOWN1"
        self.assert_code("EXECUTION_IDEMPOTENCY_REQUIRED", L5.check_effect, **unknown_key)
        crossed_tuple = fixture.effect_args(
            active, action_id="AUTO.ACTION1", idempotency_key="AUTO.OP2",
        )
        self.assert_code("AUTONOMY_OPERATION_BINDING_REQUIRED", L5.check_effect, **crossed_tuple)

    def test_autonomous_budget_is_monotonic_and_eleventh_write_blocks(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        current = fixture.activate(inputs, state_path, state_binding)["state_binding"]
        for index in range(1, 11):
            result = L5.check_effect(**fixture.effect_args(
                current, action_id=f"AUTO.ACTION{index}",
                idempotency_key=f"AUTO.OP{index}",
            ))
            current = result["state_binding"]
        state = json.loads(Path(current["path"]).read_text(encoding="utf-8"))
        self.assertEqual(state["budget_snapshot"]["used_writes"], 10)
        self.assertEqual(state["budget_snapshot"]["used_turns"], 10)
        self.assert_code(
            "OPERATING_BUDGET_EXHAUSTED", L5.check_effect,
            **fixture.effect_args(
                current, action_id="AUTO.ACTION11", idempotency_key="AUTO.OP11"
            ),
        )

    def test_forged_budget_rollback_checkpoint_is_rejected(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        active = fixture.activate(inputs, state_path, state_binding)["state_binding"]
        first = L5.check_effect(**fixture.effect_args(
            active, action_id="AUTO.ACTION1", idempotency_key="AUTO.OP1",
        ))
        state2_binding = first["state_binding"]
        state2 = json.loads(Path(state2_binding["path"]).read_text(encoding="utf-8"))
        forged = {key: value for key, value in state2.items() if key != "record_digest"}
        forged["state_seq"] = 3
        forged["state_id"] = f"{fixture.task_id}.AUTONOMY.STATE.3"
        forged["previous_state_binding"] = state2_binding
        forged["budget_snapshot"] = dict(forged["budget_snapshot"])
        forged["budget_snapshot"]["used_turns"] = 0
        forged["budget_snapshot"]["used_tool_calls"] = 0
        forged["budget_snapshot"]["used_writes"] = 0
        forged_binding = L5._write_create_once(
            fixture.project / ".omni-operating" / "states" / "STATE_000003.json",
            forged, fixture.project, "DUAL_WRITER",
        )
        self.assert_code(
            "OPERATING_BUDGET_ROLLBACK", L5.verify_state,
            state_path=forged_binding["path"], state_sha256=forged_binding["sha256"],
            state_root=fixture.project, expect="AUTONOMY_ACTIVE",
            trusted_pm_root=fixture.channel, trusted_pm_issuer_id=PM_ISSUER,
        )

    def test_pm_authority_binds_exact_objective_bytes(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        objective = copy.deepcopy(inputs["objective"][2])
        objective["description"] = "Self-expanded objective not signed by PM"
        path, binding, objective = fixture.rewrite(inputs["objective"][0], objective)
        inputs["objective"] = (path, binding, objective)
        self.assert_code(
            "OBJECTIVE_PM_AUTHORITY_REQUIRED", fixture.activate,
            inputs, state_path, state_binding,
        )

    def test_sentinel_freshness_threshold_and_rearm_budget_are_exact(self):
        stale = L5Fixture(self.root / "stale", "AUTONOMOUS")
        stale.bind(); state_path, state_binding, _ = stale.state0()
        inputs = stale.autonomous_inputs(state_binding)
        expired = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        stale.mutate_physical(
            inputs, "agentic",
            lambda physical, item: (physical.__setitem__("expires_at", expired), item.__setitem__("expires_at", expired)),
        )
        self.assert_code("SENTINEL_FRESHNESS_EXPIRED", stale.activate, inputs, state_path, state_binding)

        threshold = L5Fixture(self.root / "threshold", "AUTONOMOUS")
        threshold.bind(); state_path, state_binding, _ = threshold.state0()
        inputs = threshold.autonomous_inputs(state_binding)
        threshold.mutate_physical(
            inputs, "context",
            lambda physical, _item: (physical.__setitem__("warn_threshold", 98), physical.__setitem__("rotate_threshold", 99)),
        )
        self.assert_code("HOST_CONTEXT_THRESHOLD_MISMATCH", threshold.activate, inputs, state_path, state_binding)

        rearm = L5Fixture(self.root / "rearm", "AUTONOMOUS")
        rearm.bind(); state_path, state_binding, _ = rearm.state0()
        inputs = rearm.autonomous_inputs(state_binding)
        rearm.mutate_physical(
            inputs, "script",
            lambda physical, _item: physical.__setitem__("rearm_budget_remaining", 3),
        )
        self.assert_code("SUPERVISOR_BUDGET_EXHAUSTED", rearm.activate, inputs, state_path, state_binding)

    def test_terminal_state_schema_is_fail_closed(self):
        import jsonschema
        fixture = L5Fixture(self.root, "GUIDED_PM")
        fixture.bind(); _path, _binding, state = fixture.state0()
        mutant = {key: value for key, value in state.items() if key != "record_digest"}
        mutant.update({
            "status": "OPERATING_STOPPED", "effects_authorized": True,
            "automation_armed": True, "single_writer": True,
            "authorized_effects": ["PROJECT_WRITE"], "finding_codes": [],
        })
        mutant = L5.seal(mutant)
        schema = json.loads((ROOT / "schemas" / "operating_state.schema.json").read_text(encoding="utf-8"))
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(mutant))
        self.assertTrue(errors)

    def test_kill_switch_reclose_requires_typed_pm_authority(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        active = fixture.activate(inputs, state_path, state_binding)["state_binding"]
        closed2 = copy.deepcopy(inputs["kill"][2]); closed2["generation"] = 2
        fixture.rewrite(inputs["kill"][0], closed2)
        self.assert_code(
            "KILL_SWITCH_RECLOSE_AUTHORITY_REQUIRED", L5.check_effect,
            **fixture.effect_args(active, effect="PROJECT_WRITE"),
        )
        receipt = {
            "schema": "omni-kill-switch-reclose-pm-authority-v1",
            "status": "AUTHORIZED", "decision": "AUTHORIZED",
            "issuer_id": PM_ISSUER, "task_id": fixture.task_id,
            "program_id": fixture.program_id,
            "subject_session_id": fixture.builder,
            "kill_switch_path": str(inputs["kill"][0].resolve()),
            "initial_binding": inputs["kill"][1], "previous_generation": 1,
            "authorized_generation": 2, "one_shot": True,
        }
        _, receipt_binding, _ = fixture.write(fixture.channel / "pm_reclose_2.json", receipt)
        closed2["reclose_authority_binding"] = receipt_binding
        fixture.rewrite(inputs["kill"][0], closed2)
        result = L5.check_effect(**fixture.effect_args(
            active, effect="PROJECT_WRITE", idempotency_key="AUTO.OP1"
        ))
        self.assertEqual(result["status"], "PASS")

    def test_kill_switch_generation_cannot_roll_back_after_checkpoint(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        initial_kill = copy.deepcopy(inputs["kill"][2])
        active = fixture.activate(inputs, state_path, state_binding)["state_binding"]
        receipt = {
            "schema": "omni-kill-switch-reclose-pm-authority-v1",
            "status": "AUTHORIZED", "decision": "AUTHORIZED",
            "issuer_id": PM_ISSUER, "task_id": fixture.task_id,
            "program_id": fixture.program_id,
            "subject_session_id": fixture.builder,
            "kill_switch_path": str(inputs["kill"][0].resolve()),
            "initial_binding": inputs["kill"][1], "previous_generation": 1,
            "authorized_generation": 2, "one_shot": True,
        }
        _, receipt_binding, _ = fixture.write(fixture.channel / "pm_reclose_generation_2.json", receipt)
        closed2 = copy.deepcopy(initial_kill)
        closed2["generation"] = 2
        closed2["reclose_authority_binding"] = receipt_binding
        fixture.rewrite(inputs["kill"][0], closed2)
        first = L5.check_effect(**fixture.effect_args(
            active, action_id="AUTO.ACTION1", idempotency_key="AUTO.OP1",
        ))
        fixture.rewrite(inputs["kill"][0], initial_kill)
        self.assert_code(
            "KILL_SWITCH_GENERATION_ROLLBACK", L5.check_effect,
            **fixture.effect_args(
                first["state_binding"], action_id="AUTO.ACTION2",
                idempotency_key="AUTO.OP2",
            ),
        )

    def test_nonce_replay_with_different_bytes_is_rejected(self):
        fixture = L5Fixture(self.root, "GUIDED_PM", "A")
        fixture.bind()
        second = L5Fixture(self.root / "other", "GUIDED_PM", "A")
        # Share the state root and the same selection nonce, but use different
        # program bytes: nonce consumption must detect substitution before state.
        second.project = fixture.project
        self.assert_code("OPERATING_AUTHORITY_REPLAY", second.bind)

    def test_concurrent_bind_has_exactly_one_writer(self):
        fixture_a = L5Fixture(self.root / "a", "GUIDED_PM", "A")
        fixture_b = L5Fixture(self.root / "b", "GUIDED_PM", "B")
        fixture_b.project = fixture_a.project
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker(fixture):
            barrier.wait()
            try:
                fixture.bind(); value = "PASS"
            except L5.OperatingError as error:
                value = error.reason_code
            with lock:
                outcomes.append(value)

        threads = [threading.Thread(target=worker, args=(fixture_a,)), threading.Thread(target=worker, args=(fixture_b,))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes.count("PASS"), 1, outcomes)
        self.assertEqual(outcomes.count("DUAL_WRITER"), 1, outcomes)

    def test_concurrent_exact_effect_has_one_executor_and_one_replay(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        authority_path, authority_binding, _ = fixture.guided_authority(state_binding)
        ready = L5.activate_guided_turn(
            state_path=state_path, state_sha256=state_binding["sha256"],
            turn_authority_path=authority_path,
            turn_authority_sha256=authority_binding["sha256"],
            state_root=fixture.project, trusted_pm_root=fixture.channel,
            trusted_pm_issuer_id=PM_ISSUER,
        )
        args = fixture.effect_args(
            ready["state_binding"], action_id="BUILD1",
            idempotency_key="GUIDED.OP1",
        )
        original_scan = L5._scan_effect_consumption
        barrier = threading.Barrier(2)
        outcomes: list[dict] = []
        failures: list[str] = []
        lock = threading.Lock()

        def synchronized_scan(root, *, idempotency_key, fingerprint):
            result = original_scan(
                root, idempotency_key=idempotency_key, fingerprint=fingerprint,
            )
            if result is None:
                barrier.wait(timeout=10)
            return result

        def worker():
            try:
                value = L5.check_effect(**args)
                with lock:
                    outcomes.append(value)
            except Exception as error:  # surfaced below with its exact type/code
                with lock:
                    failures.append(getattr(error, "reason_code", type(error).__name__))

        with mock.patch.object(L5, "_scan_effect_consumption", side_effect=synchronized_scan):
            threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=15)
        self.assertEqual(failures, [])
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(sum(item["execute_effect"] is True for item in outcomes), 1, outcomes)
        self.assertEqual(sum(item["status"] == "IDEMPOTENT_REPLAY" for item in outcomes), 1, outcomes)

    def test_crash_after_effect_checkpoint_recovers_as_read_only_replay(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        active = fixture.activate(inputs, state_path, state_binding)["state_binding"]
        args = fixture.effect_args(
            active, action_id="AUTO.ACTION1",
            idempotency_key="AUTO.OP1",
        )
        original = L5._write_create_once
        crashed = {"done": False}

        def crash_after_checkpoint(path, record, root, collision_code, *, with_status=False):
            result = original(
                path, record, root, collision_code, with_status=with_status,
            )
            if path.parent.name == "states" and path.name == "STATE_000002.json" and not crashed["done"]:
                crashed["done"] = True
                raise L5.OperatingError("SIMULATED_CRASH", decision="INCONCLUSIVE")
            return result

        with mock.patch.object(L5, "_write_create_once", side_effect=crash_after_checkpoint):
            self.assert_code("SIMULATED_CRASH", L5.check_effect, **args)
        checkpoint = fixture.project / ".omni-operating" / "states" / "STATE_000002.json"
        self.assertTrue(checkpoint.is_file())
        replay = L5.check_effect(**args)
        self.assertEqual(replay["status"], "IDEMPOTENT_REPLAY")
        self.assertFalse(replay["execute_effect"])

    def test_crash_after_prepared_lease_recovers_idempotently(self):
        fixture = L5Fixture(self.root, "AUTONOMOUS")
        fixture.bind(); state_path, state_binding, _ = fixture.state0()
        inputs = fixture.autonomous_inputs(state_binding)
        original = L5._write_create_once
        crashed = {"done": False}

        def crash_after_lease(path, record, root, collision_code):
            result = original(path, record, root, collision_code)
            if path.parent.name == "leases" and not crashed["done"]:
                crashed["done"] = True
                raise L5.OperatingError("SIMULATED_CRASH", decision="INCONCLUSIVE")
            return result

        with mock.patch.object(L5, "_write_create_once", side_effect=crash_after_lease):
            self.assert_code("SIMULATED_CRASH", fixture.activate, inputs, state_path, state_binding)
        lease = fixture.project / ".omni-operating" / "leases" / "LEASE_000001.json"
        state1 = fixture.project / ".omni-operating" / "states" / "STATE_000001.json"
        self.assertTrue(lease.is_file())
        self.assertFalse(state1.exists())
        result = fixture.activate(inputs, state_path, state_binding)
        self.assertEqual(result["status"], "AUTONOMY_ACTIVE")
        self.assertTrue(state1.is_file())

    def test_cli_returns_typed_block_without_traceback(self):
        fixture = L5Fixture(self.root, "GUIDED_PM")
        code = L5.main([
            "bind", "--binding", str(fixture.binding_path), "--binding-sha256", "0" * 64,
            "--program", str(fixture.program_path), "--program-sha256", fixture.program_binding["sha256"],
            "--countersign", str(fixture.countersign_path), "--countersign-sha256", fixture.countersign_binding["sha256"],
            "--state-root", str(fixture.project), "--trusted-pm-root", str(fixture.channel),
            "--trusted-pm-issuer-id", PM_ISSUER,
        ])
        self.assertIn(code, {2, 3})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
SENTRY = ROOT / "scripts" / "sentry"
sys.path.insert(0, str(SENTRY))

from budgets import Budget
from brake import assert_clear, evaluate
from context import evaluate as evaluate_context
from cycle import ESCALATIONS, escalate
from emit_state import (
    ProtocolError,
    claim_evidence,
    emit,
    reconcile_claim,
    validate_guided_intake_state,
    validate_outcome,
)
from io_safe import (
    canonical_json,
    create_once_text,
    freeze_manifest,
    sha256_bytes,
    sha256_path,
    strict_json,
    verify_manifest,
)
from loop import EchoDetector
from mode_a_guard import decide_invocation, select as select_mode
from progress import has_new_evidence
from windows import classify


GUIDED_STATIONS = (
    "Q0_TOPOLOGY", "PARTNER_IDENTITY", "ROLE_BINDING", "FILE_OWNERSHIP",
    "TURN_ORDER", "PROHIBITIONS", "PM_RESERVED_GATES", "PROJECT_DESCRIPTION",
    "OBJECTIVE", "NON_OBJECTIVES", "SUCCESS_EVIDENCE", "BUDGETS",
    "DATA_SENSITIVITY", "REVERSIBILITY", "FORBIDDEN_EFFECTS", "ACCESS_GRANT",
    "USER_MATERIAL", "RESEARCH_LANES", "COMMUNICATION_REGIME",
)
GUIDED_PROHIBITIONS = [
    "NO_CROSS_WRITE", "NO_AUTHOR_AND_SIGN", "NO_IMPLICIT_AUTHORITY", "NO_F5",
    "NO_INSTALLATION", "NO_PUBLICATION", "NO_EXTERNAL_EFFECTS",
]
GUIDED_PM_GATES = [
    "SCOPE_CHANGE", "AUTHORITY_EXPANSION", "KNOWLEDGE_FUSION",
    "PROGRAM_BAPTISM", "OPERATING_REGIME_BINDING", "EXTERNAL_EFFECTS",
    "INSTALLATION", "PUBLICATION",
]
_GUIDED_RECEIPT_DIR = tempfile.TemporaryDirectory(prefix="omni-guided-receipts-")
WORKSPACE_GRANTS = [
    "READ_NAMED_SOURCES",
    "CREATE_DIRECTORIES_IN_PROJECT_ROOT",
    "CREATE_FILES_IN_PROJECT_ROOT",
    "WRITE_OWNED_LANE_FILES",
]
WORKSPACE_NON_GRANTS = [
    "DELETE", "MOVE", "RENAME_OUTSIDE_ROOT", "OVERWRITE_PREEXISTING_USER_FILE",
    "EXECUTE", "INSTALL", "PUBLISH", "EXTERNAL_EFFECTS",
]


def guided_digest(value, *excluded):
    return sha256_bytes(
        canonical_json({key: item for key, item in value.items() if key not in excluded}).encode("utf-8")
    )


def question_digest(question):
    fields = (
        "question_id", "ordinal", "station_id", "classification_before",
        "critical", "text", "relay_id",
    )
    return sha256_bytes(canonical_json({field: question[field] for field in fields}).encode("utf-8"))


def answer_digest(answer):
    fields = ("source", "text", "relay_id", "classification_after")
    return sha256_bytes(canonical_json({field: answer[field] for field in fields}).encode("utf-8"))


def write_bytes_binding(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def write_json_binding(path, value):
    return write_bytes_binding(path, canonical_json(value).encode("utf-8"))


def rewrite_relay_payload(state, relay_id, raw):
    relay = next(item for item in state["relay"]["records"] if item["relay_id"] == relay_id)
    binding = write_bytes_binding(Path(relay["payload_path"]), raw)
    relay.update(
        payload_path=binding["path"],
        payload_bytes=binding["bytes"],
        payload_sha256=binding["sha256"],
    )
    return relay["payload_sha256"]


def reseal_card(state):
    card = state["team_card"]
    raw = canonical_json(
        {key: item for key, item in card.items() if key not in {"card_sha256", "acks"}}
    ).encode("utf-8")
    card["card_sha256"] = rewrite_relay_payload(state, card["card_relay_id"], raw)
    for ack in card["acks"].values():
        if ack["status"] == "ACK":
            ack["observed_card_sha256"] = card["card_sha256"]
            rewrite_relay_payload(state, ack["relay_id"], raw)


def rewrite_mandate(state, lane_name):
    participant = state["session_pair"][lane_name]
    mandate = {
        "schema": "omni-participant-mandate-v1",
        "role": participant["role"],
        "identity": participant["identity"],
        "host": participant["host"],
        "session_id": participant["session_id"],
        "write_lane": participant["write_lane"],
        "owned_paths": participant["owned_paths"],
    }
    binding = write_json_binding(Path(participant["mandate_path"]), mandate)
    participant["mandate_bytes"] = binding["bytes"]
    participant["mandate_sha256"] = binding["sha256"]


def reseal_workspace_access(state):
    envelope = state["workspace_access_envelope"]
    pair_sha256 = state["session_pair"]["pair_sha256"]
    envelope["session_pair_sha256"] = pair_sha256
    binding = envelope["probe_receipt_binding"]
    if binding is not None:
        receipt_path = Path(binding["path"])
        receipt = strict_json(receipt_path.read_text(encoding="utf-8"))
        receipt["session_pair_sha256"] = pair_sha256
        receipt["record_digest"] = guided_digest(receipt, "record_digest")
        envelope["probe_receipt_binding"] = write_json_binding(receipt_path, receipt)
    envelope["record_digest"] = guided_digest(envelope, "record_digest")


def rewrite_activation_receipt(state, receipt, path):
    binding = state["activation_binding"]
    physical = write_json_binding(path, receipt)
    binding.update(physical)
    binding.update(
        receipt_outcome="ACCEPTED",
        decision_schema=receipt["schema"],
        decision_status=receipt["status"],
        activation_path=receipt.get("activation_path", "EXPLICIT_USER_OPT_IN"),
    )
    for field in (
        "task_scope", "run_kind", "effect_policy", "knowledge_available",
        "skill_invoked", "effect_authorized", "activation_level", "modules_used",
        "authority_grants", "artifact_grants", "requested_effects", "effect_grants",
        "non_grants", "access_envelope_identity", "activation_grants",
        "activation_non_grants", "intake_allowed", "mode_selection_allowed",
        "mode_gate", "next_gate",
    ):
        binding[field] = receipt[field]


def reseal_station_matrix(state):
    digest = sha256_bytes(canonical_json(state["station_matrix"]).encode("utf-8"))
    state["station_matrix_sha256"] = digest
    state["critical_closure"]["station_matrix_sha256"] = digest


def reseal_question_matrix(state):
    digest = guided_digest(state["question_matrix"], "matrix_sha256")
    state["question_matrix"]["matrix_sha256"] = digest
    state["critical_closure"]["question_matrix_sha256"] = digest


def bind_receipt_file(state, receipt, path):
    raw = canonical_json(receipt).encode("utf-8")
    path.write_bytes(raw)
    state["activation_binding"].update(
        {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}
    )


def profile_degraded_state():
    state = guided_state(topology="SOLO_DUAL_HAT")
    pair = state["session_pair"]
    pair["verifier"]["session_id"] = pair["builder"]["session_id"]
    rewrite_mandate(state, "verifier")
    pair["pair_sha256"] = guided_digest(pair, "pair_sha256")
    reseal_workspace_access(state)
    state["profile"] = "PROFILE_DEGRADED"
    state["independence"] = "NOT_QUALIFIED"
    state["phase"] = "INTAKE_BLOCKED"
    state["status"] = "BLOCKED"
    state["blocking_reason_codes"] = ["PROFILE_DEGRADED_NOT_GODMODE"]
    state["team_card"]["session_pair_sha256"] = pair["pair_sha256"]
    state["team_card"]["acks"]["verifier"]["session_id"] = pair["verifier"]["session_id"]
    state["intake_proposal"]["session_pair_sha256"] = pair["pair_sha256"]
    state["intake_proposal"]["acks"]["verifier"]["session_id"] = pair["verifier"]["session_id"]
    state["relay"]["session_pair_sha256"] = pair["pair_sha256"]
    for question in state["question_matrix"]["questions"]:
        question["readbacks"]["verifier"]["session_id"] = pair["verifier"]["session_id"]
    reseal_card(state)
    reseal_question_matrix(state)
    return state


def relay_record(ordinal, kind, origin, destinations, lane_root, raw):
    binding = write_bytes_binding(lane_root / f"relay-{ordinal:03d}.json", raw)
    return {
        "relay_id": f"RELAY-{ordinal:03d}",
        "ordinal": ordinal,
        "kind": kind,
        "origin": origin,
        "destinations": destinations,
        "phase": "GUIDED_INTAKE",
        "payload_path": binding["path"],
        "payload_bytes": binding["bytes"],
        "payload_sha256": binding["sha256"],
        "created_at": "2026-07-30T08:00:00+00:00",
    }


def activation_binding(run_kind="REAL", activation_path="EXPLICIT_USER_OPT_IN"):
    if activation_path == "EXPLICIT_USER_OPT_IN":
        receipt = decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            run_kind=run_kind,
            activation_level="OMNI_FULL",
        )
    else:
        receipt = decide_invocation(
            explicit_user_request=False,
            complexity_warrants_omni=True,
            consent_state="ACCEPTED",
            grounds=("DURABLE_KNOWLEDGE",),
            run_kind=run_kind,
            activation_level="OMNI_FULL",
        )
    raw = canonical_json(receipt).encode("utf-8")
    path = Path(_GUIDED_RECEIPT_DIR.name) / f"{run_kind}-{activation_path}.json"
    path.write_bytes(raw)
    return {
        "path": str(path),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "receipt_outcome": "ACCEPTED",
        "decision_schema": receipt["schema"],
        "decision_status": receipt["status"],
        "activation_path": receipt["activation_path"],
        "task_scope": receipt["task_scope"],
        "run_kind": receipt["run_kind"],
        "effect_policy": receipt["effect_policy"],
        "knowledge_available": receipt["knowledge_available"],
        "skill_invoked": receipt["skill_invoked"],
        "effect_authorized": receipt["effect_authorized"],
        "activation_level": receipt["activation_level"],
        "modules_used": receipt["modules_used"],
        "authority_grants": receipt["authority_grants"],
        "artifact_grants": receipt["artifact_grants"],
        "requested_effects": receipt["requested_effects"],
        "effect_grants": receipt["effect_grants"],
        "non_grants": receipt["non_grants"],
        "access_envelope_identity": receipt["access_envelope_identity"],
        "activation_grants": receipt["activation_grants"],
        "activation_non_grants": receipt["activation_non_grants"],
        "intake_allowed": receipt["intake_allowed"],
        "mode_selection_allowed": receipt["mode_selection_allowed"],
        "mode_gate": receipt["mode_gate"],
        "next_gate": receipt["next_gate"],
    }


def guided_state(topology="TEAM_DUAL_LANE", run_kind="REAL", activation_path="EXPLICIT_USER_OPT_IN"):
    effect_policy = (
        "DOWNSTREAM_GATED_REAL"
        if run_kind == "REAL"
        else "SIMULATE_WITHOUT_MATERIALIZATION"
    )
    builder_identity = "Codex Builder"
    verifier_identity = "Claude Verifier" if topology == "TEAM_DUAL_LANE" else builder_identity
    fixture_root = Path(tempfile.mkdtemp(dir=_GUIDED_RECEIPT_DIR.name, prefix="guided-state-"))
    task_root = fixture_root / "task"
    project_root = task_root / "project"
    source_root = project_root / "sources"
    owned_lane_root = project_root / "owned-lanes"
    lane_roots = {
        "PM": owned_lane_root / "pm",
        "BUILDER": owned_lane_root / "builder",
        "VERIFIER": owned_lane_root / "verifier",
    }
    for directory in (task_root, project_root, source_root, owned_lane_root, *lane_roots.values()):
        directory.mkdir(parents=True, exist_ok=True)
    pair = {
        "pair_id": "PAIR-001",
        "lock_status": "LOCKED_UNTIL_CUTOVER",
        "builder": {
            "role": "BUILDER", "identity": builder_identity, "host": "CODEX",
            "session_id": "SESSION-BUILDER",
            "mandate_path": str(lane_roots["BUILDER"] / "mandate.json"),
            "mandate_bytes": 1, "mandate_sha256": "0" * 64,
            "write_lane": str(lane_roots["BUILDER"]),
            "owned_paths": [str(lane_roots["BUILDER"])],
        },
        "verifier": {
            "role": "VERIFIER", "identity": verifier_identity, "host": "CLAUDE",
            "session_id": "SESSION-VERIFIER",
            "mandate_path": str(lane_roots["VERIFIER"] / "mandate.json"),
            "mandate_bytes": 1, "mandate_sha256": "0" * 64,
            "write_lane": str(lane_roots["VERIFIER"]),
            "owned_paths": [str(lane_roots["VERIFIER"])],
        },
    }
    pair_shell = {"session_pair": pair}
    rewrite_mandate(pair_shell, "builder")
    rewrite_mandate(pair_shell, "verifier")
    pair["pair_sha256"] = guided_digest(pair)
    relays = []

    def add_relay(kind, origin, destinations, raw):
        item = relay_record(
            len(relays) + 1, kind, origin, destinations, lane_roots[origin], raw,
        )
        relays.append(item)
        return item["relay_id"]

    authorization_raw = canonical_json(
        {
            "schema": "omni-partner-selection-authorization-v1",
            "pair_id": pair["pair_id"],
            "authorized_by": "PM",
        }
    ).encode("utf-8")
    authorization_sha256 = sha256_bytes(authorization_raw)
    authorization_relay = add_relay(
        "PARTNER_SELECTION_AUTHORIZATION", "PM", ["BUILDER", "VERIFIER"],
        authorization_raw,
    )
    card_relay_id = f"RELAY-{len(relays) + 1:03d}"
    card = {
        "card_id": "TEAM-CARD-001",
        "card_relay_id": card_relay_id,
        "status": "TEAM_CARD_DUAL_ACK",
        "session_pair_sha256": pair["pair_sha256"],
        "sovereign_identity": builder_identity,
        "partner_identity": verifier_identity if topology == "TEAM_DUAL_LANE" else None,
        "partner_selection_authorization_relay_id": authorization_relay,
        "partner_selection_authorization_sha256": authorization_sha256,
        "turn_order": ["BUILDER", "VERIFIER"],
        "prohibitions": GUIDED_PROHIBITIONS,
        "pm_reserved_gates": GUIDED_PM_GATES,
        "transport": "PM_RELAY",
    }
    card_raw = canonical_json(card).encode("utf-8")
    card["card_sha256"] = sha256_bytes(card_raw)
    card_relay = add_relay("TEAM_CARD", "BUILDER", ["PM", "VERIFIER"], card_raw)
    assert card_relay == card_relay_id
    builder_card_ack = add_relay("READBACK", "BUILDER", ["PM", "VERIFIER"], card_raw)
    verifier_card_ack = add_relay("READBACK", "VERIFIER", ["PM", "BUILDER"], card_raw)
    card["acks"] = {
        "builder": {
            "role": "BUILDER", "session_id": pair["builder"]["session_id"], "status": "ACK",
            "observed_card_sha256": card["card_sha256"], "relay_id": builder_card_ack,
            "created_at": "2026-07-30T08:00:00+00:00",
        },
        "verifier": {
            "role": "VERIFIER", "session_id": pair["verifier"]["session_id"], "status": "ACK",
            "observed_card_sha256": card["card_sha256"], "relay_id": verifier_card_ack,
            "created_at": "2026-07-30T08:00:00+00:00",
        },
    }

    question_specs = (
        ("Q-001", "Q0_TOPOLOGY", "Lavoriamo in team o in doppio cappello?", topology),
        ("Q-002", "USER_MATERIAL", "Quale materiale autorizzi per lo studio?", "Cartella XYZ"),
    )
    questions = []
    for ordinal, (question_id, station_id, text, answer_text) in enumerate(question_specs, 1):
        question_relay = f"RELAY-{len(relays) + 1:03d}"
        question = {
            "question_id": question_id,
            "ordinal": ordinal,
            "station_id": station_id,
            "classification_before": "DECISION_REQUIRED",
            "critical": True,
            "text": text,
            "relay_id": question_relay,
        }
        question_raw = canonical_json(
            {
                field: question[field]
                for field in (
                    "question_id", "ordinal", "station_id", "classification_before",
                    "critical", "text", "relay_id",
                )
            }
        ).encode("utf-8")
        question["question_sha256"] = sha256_bytes(question_raw)
        assert add_relay(
            "QUESTION", "BUILDER", ["PM", "VERIFIER"], question_raw,
        ) == question_relay
        builder_question_readback = add_relay(
            "READBACK", "BUILDER", ["PM", "VERIFIER"], question_raw,
        )
        verifier_question_readback = add_relay(
            "READBACK", "VERIFIER", ["PM", "BUILDER"], question_raw,
        )
        answer_relay = f"RELAY-{len(relays) + 1:03d}"
        answer = {
            "source": "PM", "text": answer_text, "relay_id": answer_relay,
            "classification_after": "KNOWN",
        }
        answer_raw = canonical_json(
            {
                field: answer[field]
                for field in ("source", "text", "relay_id", "classification_after")
            }
        ).encode("utf-8")
        answer["answer_sha256"] = sha256_bytes(answer_raw)
        assert add_relay(
            "ANSWER", "PM", ["BUILDER", "VERIFIER"], answer_raw,
        ) == answer_relay
        builder_answer_readback = add_relay(
            "READBACK", "BUILDER", ["PM", "VERIFIER"], answer_raw,
        )
        verifier_answer_readback = add_relay(
            "READBACK", "VERIFIER", ["PM", "BUILDER"], answer_raw,
        )
        question["answer"] = answer
        question["readbacks"] = {
            "builder": {
                "role": "BUILDER", "session_id": pair["builder"]["session_id"],
                "question_status": "ACK", "observed_question_sha256": question["question_sha256"],
                "answer_status": "ACK", "observed_answer_sha256": answer["answer_sha256"],
                "question_relay_id": builder_question_readback,
                "answer_relay_id": builder_answer_readback,
                "created_at": "2026-07-30T08:00:00+00:00",
            },
            "verifier": {
                "role": "VERIFIER", "session_id": pair["verifier"]["session_id"],
                "question_status": "ACK", "observed_question_sha256": question["question_sha256"],
                "answer_status": "ACK", "observed_answer_sha256": answer["answer_sha256"],
                "question_relay_id": verifier_question_readback,
                "answer_relay_id": verifier_answer_readback,
                "created_at": "2026-07-30T08:00:00+00:00",
            },
        }
        questions.append(question)

    station_questions = {question["station_id"]: [question["question_id"]] for question in questions}
    stations = []
    evidence_root = source_root / "guided-intake-evidence"
    for station_id in GUIDED_STATIONS:
        question_ids = station_questions.get(station_id, [])
        source_refs = []
        if not question_ids:
            source_refs.append(
                write_json_binding(
                    evidence_root / f"{station_id.lower()}.json",
                    {"schema": "omni-guided-intake-evidence-v1", "station_id": station_id},
                )
            )
        stations.append(
            {
                "station_id": station_id,
                "classification": "KNOWN",
                "critical": True,
                "source_refs": source_refs,
                "question_ids": question_ids,
            }
        )
    station_matrix_sha256 = sha256_bytes(canonical_json(stations).encode("utf-8"))
    matrix = {"questions": questions}
    matrix["matrix_sha256"] = guided_digest(matrix)
    proposal_raw = canonical_json(
        {
            "schema": "omni-intake-proposal-v1",
            "proposal_id": "INTAKE-PROPOSAL-001",
            "session_pair_sha256": pair["pair_sha256"],
        }
    ).encode("utf-8")
    proposal_sha256 = sha256_bytes(proposal_raw)
    proposal_relay = add_relay(
        "INTAKE_PROPOSAL", "BUILDER", ["PM", "VERIFIER"], proposal_raw,
    )
    proposal_builder_ack = add_relay(
        "READBACK", "BUILDER", ["PM", "VERIFIER"], proposal_raw,
    )
    proposal_verifier_ack = add_relay(
        "READBACK", "VERIFIER", ["PM", "BUILDER"], proposal_raw,
    )
    proposal_relay_record = next(
        item for item in relays if item["relay_id"] == proposal_relay
    )

    activation = activation_binding(run_kind, activation_path)
    probe_binding = None
    if run_kind == "REAL":
        control_root = project_root / ".omni" / "access-probes"
        control_root.mkdir(parents=True, exist_ok=True)
        source_probe_binding = write_bytes_binding(source_root / "readable-source.txt", b"source-proof")
        retained_probe_binding = write_bytes_binding(
            control_root / "retained-create-once.probe", b"create-once-probe",
        )
        probe_receipt = {
            "schema": "omni-workspace-access-probe-receipt-v1",
            "status": "CREATE_ONCE_PROBE_RETAINED",
            "receipt_id": "ACCESS-PROBE-001",
            "envelope_id": "ACCESS-001",
            "activation_receipt_sha256": activation["sha256"],
            "task_id": "INTAKE-001",
            "task_root": str(task_root),
            "project_root": str(project_root),
            "source_roots": [str(source_root)],
            "owned_lane_root": str(owned_lane_root),
            "session_pair_sha256": pair["pair_sha256"],
            "capabilities": list(WORKSPACE_GRANTS),
            "probe_path": retained_probe_binding["path"],
            "probe_bytes": retained_probe_binding["bytes"],
            "probe_sha256": retained_probe_binding["sha256"],
            "create_once": True,
            "overwritten": False,
            "retained": True,
            "read_proofs": [source_probe_binding],
        }
        probe_receipt["record_digest"] = guided_digest(probe_receipt)
        probe_binding = write_json_binding(
            control_root / "ACCESS-PROBE-001.receipt.json", probe_receipt,
        )
    workspace_access = {
        "schema": "omni-workspace-access-envelope-v1",
        "status": "ACCESS_READY" if run_kind == "REAL" else "AUTONOMY_UNAVAILABLE_NO_ACCESS",
        "outcome": (
            "ACCESS_GRANTED_NON_DESTRUCTIVE"
            if run_kind == "REAL"
            else "ACCESS_PLANNED_DRY_RUN"
        ),
        "envelope_id": "ACCESS-001",
        "activation_receipt_sha256": activation["sha256"],
        "task_id": "INTAKE-001",
        "task_root": str(task_root),
        "project_root": str(project_root),
        "source_roots": [str(source_root)],
        "owned_lane_root": str(owned_lane_root),
        "session_pair_sha256": pair["pair_sha256"],
        "run_kind": run_kind,
        "requested_capabilities": list(WORKSPACE_GRANTS),
        "granted_capabilities": list(WORKSPACE_GRANTS) if run_kind == "REAL" else [],
        "non_grants": list(WORKSPACE_NON_GRANTS),
        "separate_authorizations_required": ["NETWORK_RESEARCH", "DOWNLOAD"],
        "excluded_paths": [str(project_root / "preexisting-user-files")],
        "probe_receipt_binding": probe_binding,
    }
    workspace_access["record_digest"] = guided_digest(workspace_access)
    return {
        "schema": "omni-guided-intake-state-v1",
        "state_id": "INTAKE-001",
        "run_id": "RUN-001",
        "generation": 1,
        "phase": "INTAKE_READY",
        "status": "READY",
        "activation_binding": activation,
        "run_kind": run_kind,
        "effect_policy": effect_policy,
        "workspace_access_envelope": workspace_access,
        "profile": "GODMODE",
        "independence": (
            "PEER_INDEPENDENT" if topology == "TEAM_DUAL_LANE" else "ADVERSARIAL_SOLO"
        ),
        "topology": topology,
        "session_pair": pair,
        "team_card": card,
        "station_matrix": stations,
        "station_matrix_sha256": station_matrix_sha256,
        "question_matrix": matrix,
        "intake_proposal": {
            "status": "DUAL_READBACK_ACKED",
            "session_pair_sha256": pair["pair_sha256"],
            "proposal": {
                "proposal_id": "INTAKE-PROPOSAL-001",
                "path": proposal_relay_record["payload_path"],
                "bytes": proposal_relay_record["payload_bytes"],
                "sha256": proposal_sha256,
            },
            "acks": {
                "builder": {
                    "role": "BUILDER", "session_id": pair["builder"]["session_id"],
                    "status": "ACK", "observed_proposal_sha256": proposal_sha256,
                    "relay_id": proposal_builder_ack, "created_at": "2026-07-30T08:00:00+00:00",
                },
                "verifier": {
                    "role": "VERIFIER", "session_id": pair["verifier"]["session_id"],
                    "status": "ACK", "observed_proposal_sha256": proposal_sha256,
                    "relay_id": proposal_verifier_ack, "created_at": "2026-07-30T08:00:00+00:00",
                },
            },
        },
        "relay": {
            "transport": "PM_RELAY",
            "state": "ACTIVE",
            "session_pair_sha256": pair["pair_sha256"],
            "same_pair_required": True,
            "governed_channel_equivalent": False,
            "pm_write_lane": str(lane_roots["PM"]),
            "records": relays,
        },
        "critical_closure": {
            "derivation": "RECOMPUTED_FROM_EVIDENCE_AND_FOUR_READBACK_V2",
            "station_matrix_sha256": station_matrix_sha256,
            "question_matrix_sha256": matrix["matrix_sha256"],
            "status": "CLOSED",
            "open_question_ids": [],
            "computed_at": "2026-07-30T08:00:00+00:00",
        },
        "well": {"state": "WELL_WRITE_SCOPE_PENDING", "artifact_sha256": None},
        "knowledge": {"state": "NOT_STARTED", "fusion_sha256": None},
        "program": {"state": "NOT_STARTED", "program_sha256": None},
        "cutover": {"state": "NOT_STARTED", "receipt_sha256": None},
        "blocking_reason_codes": [],
    }


class GovernanceTests(unittest.TestCase):
    def test_invocation_matrix_precedes_mode_selection(self):
        cases = (
            ("write this one-off PDF report", False, False, "ABSENT", (), None, "NO_SKILL_REQUIRED", False),
            ("build a PDF bicycle-maintenance manual", False, False, "ABSENT", (), None, "NO_SKILL_REQUIRED", False),
            ("write a cookbook book", False, True, "ABSENT", ("DURABLE_KNOWLEDGE",), None, "PROPOSAL_EMITTED_AWAITING_CONSENT", False),
            ("cookbook proposal accepted", False, True, "ACCEPTED", ("DURABLE_KNOWLEDGE", "MULTI_PHASE_WORK"), "REAL", "ACTIVATION_ALLOWED", True),
            ("lite explicit GodMode builder plus verifier", True, False, "ABSENT", (), "DRY_RUN", "ACTIVATION_ALLOWED", True),
            ("cookbook proposal declined", False, True, "DECLINED", ("DURABLE_KNOWLEDGE",), None, "DECLINED_USE_ORDINARY_TOOLS", False),
        )
        for label, explicit, complex_project, consent, grounds, run_kind, status, allowed in cases:
            with self.subTest(label=label):
                decision = decide_invocation(
                    explicit_user_request=explicit,
                    complexity_warrants_omni=complex_project,
                    consent_state=consent,
                    grounds=grounds,
                    run_kind=run_kind,
                    activation_level="OMNI_FULL" if allowed else None,
                )
                self.assertEqual(decision["status"], status)
                self.assertIs(decision["activation_allowed"], allowed)
                self.assertFalse(decision["mode_selection_allowed"])
                if label == "lite explicit GodMode builder plus verifier":
                    self.assertEqual(decision["activation_path"], "EXPLICIT_USER_OPT_IN")
                    self.assertEqual(decision["activation_grants"], ["METHOD_USE"])
                    self.assertFalse(decision["effect_authorized"])
                selected = select_mode(
                    turns=3, durable_state=True, midstream_judgment=True,
                    parallel_value=True, independent_verifier=True,
                    invocation_allowed=allowed,
                    evidence=None,
                )
                self.assertEqual(selected, "MODE_BEFORE_PROGRAM" if allowed else "BLOCKED_BEFORE_MODE_SELECTION")

    def test_invocation_consent_is_strict_and_task_scoped(self):
        with self.assertRaises(TypeError):
            decide_invocation(explicit_user_request=1, complexity_warrants_omni=False, user_consent=None)
        with self.assertRaises(TypeError):
            decide_invocation(explicit_user_request=False, complexity_warrants_omni=True, user_consent="yes")
        with self.assertRaises(ValueError):
            decide_invocation(explicit_user_request=True, complexity_warrants_omni=True, user_consent=True)
        with self.assertRaises(ValueError):
            decide_invocation(
                explicit_user_request=False, complexity_warrants_omni=True,
                user_consent=True, consent_state="ACCEPTED", grounds=("DURABLE_KNOWLEDGE",),
            )
        unjustified = decide_invocation(
            explicit_user_request=False, complexity_warrants_omni=False, user_consent=True,
            activation_level="OMNI_FULL",
        )
        self.assertEqual(unjustified["status"], "NO_SKILL_REQUIRED")
        self.assertFalse(unjustified["mode_selection_allowed"])

    def test_activation_grants_only_method_use(self):
        for run_kind in ("REAL", "DRY_RUN"):
            with self.subTest(run_kind=run_kind):
                decision = decide_invocation(
                    explicit_user_request=True, complexity_warrants_omni=False,
                    run_kind=run_kind,
                    activation_level="OMNI_FULL",
                )
                self.assertEqual(decision["activation_grants"], ["METHOD_USE"])
                self.assertEqual(
                    decision["activation_non_grants"],
                    ["PARTNER_SELECTION", "WEB_ACCESS", "DOWNLOAD", "PROJECT_WRITE", "EXECUTION", "AUTONOMY"],
                )
                self.assertTrue(decision["intake_allowed"])
                self.assertFalse(decision["mode_selection_allowed"])
                self.assertEqual(decision["mode_gate"], "MODE_BEFORE_PROGRAM")
        dry = decide_invocation(
            explicit_user_request=True, complexity_warrants_omni=False, run_kind="DRY_RUN",
            activation_level="OMNI_FULL",
        )
        self.assertEqual(dry["effect_policy"], "SIMULATE_WITHOUT_MATERIALIZATION")

    def test_ambiguous_missing_grounds_and_run_kind_fail_closed(self):
        ambiguous = decide_invocation(
            explicit_user_request=False, complexity_warrants_omni=True,
            consent_state="AMBIGUOUS", grounds=("MULTI_PHASE_WORK",),
        )
        self.assertEqual(ambiguous["status"], "PROPOSAL_EMITTED_AWAITING_CONSENT")
        self.assertEqual(ambiguous["reason_code"], "CONSENT_AMBIGUOUS")
        self.assertFalse(ambiguous["activation_allowed"])
        missing_ground = decide_invocation(
            explicit_user_request=False, complexity_warrants_omni=True, consent_state="ABSENT",
        )
        self.assertEqual(missing_ground["reason_code"], "INVOCATION_GROUNDS_REQUIRED")
        missing_run_kind = decide_invocation(
            explicit_user_request=True, complexity_warrants_omni=False,
            activation_level="OMNI_FULL",
        )
        self.assertEqual(missing_run_kind["reason_code"], "RUN_KIND_REQUIRED")
        invalid_run_kind = decide_invocation(
            explicit_user_request=True, complexity_warrants_omni=False, run_kind="LIVE",
            activation_level="OMNI_FULL",
        )
        self.assertEqual(invalid_run_kind["reason_code"], "RUN_KIND_INVALID")

    def test_mode_is_blocked_without_verified_evidence_bundle(self):
        common = dict(
            turns=3, durable_state=True, midstream_judgment=True,
            parallel_value=True, independent_verifier=True, invocation_allowed=True,
        )
        self.assertEqual(select_mode(**common, evidence=None), "MODE_BEFORE_PROGRAM")

    def test_create_once_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            self.assertEqual(create_once_text(path, "{}\n"), "CREATED")
            self.assertEqual(create_once_text(path, "{}\n"), "ALREADY_PRESENT_IDENTICAL")
            self.assertEqual(len(sha256_path(path)), 64)
            with self.assertRaises(RuntimeError):
                create_once_text(path, '{"changed":true}\n')

    def test_semantic_progress_ignores_timestamp(self):
        self.assertFalse(has_new_evidence({"value": 1, "created_at": "A"}, {"value": 1, "created_at": "B"}))
        self.assertTrue(has_new_evidence({"value": 1}, {"value": 2}))

    def test_budget_and_brake(self):
        budget = Budget("retry", 1)
        budget.consume()
        with self.assertRaises(RuntimeError):
            budget.consume()
        with self.assertRaises(RuntimeError):
            assert_clear({"DUAL_WRITER": True})
        with self.assertRaises(ValueError):
            budget.consume(-1)
        self.assertEqual(evaluate({"TYPO_NEW_STOP": True}), ["UNKNOWN_HARD_STOP:TYPO_NEW_STOP"])
        self.assertEqual(evaluate({"DUAL_WRITER": "yes"}), ["INVALID_SIGNAL_VALUE:DUAL_WRITER"])

    def test_echo_and_context_sentinels_fail_closed(self):
        with self.assertRaises(ValueError):
            EchoDetector(limit=0)
        with self.assertRaises(ValueError):
            evaluate_context(1, 0)
        self.assertEqual(evaluate_context(69, 100)["state"], "HEALTHY")
        self.assertEqual(evaluate_context(70, 100)["state"], "HANDOFF_FREEZE_REQUIRED")
        self.assertEqual(evaluate_context(85, 100)["state"], "ROTATION_REQUIRED")

    def test_manifest_rejects_extra_files_and_binds_algorithm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked = root / "tracked.txt"
            tracked.write_text("frozen", encoding="utf-8")
            manifest = freeze_manifest([tracked], root)
            self.assertEqual(verify_manifest(manifest), [])
            (root / "extra.txt").write_text("drift", encoding="utf-8")
            self.assertEqual(verify_manifest(manifest), ["EXTRA:extra.txt"])
            manifest["tree_algorithm"] = "OTHER"
            self.assertIn("TREE_ALGORITHM_INVALID", verify_manifest(manifest))

    def test_timeout_is_not_failure(self):
        state = classify(False, True, True, False)
        self.assertEqual(state.state, "WORKFLOW_LIVE_DELIVERY_PENDING")

    def test_four_escalations_are_typed(self):
        self.assertEqual(len(ESCALATIONS), 4)
        for event in ESCALATIONS:
            self.assertEqual(escalate(event), ESCALATIONS[event])

    def test_cli_contract_returns_two_and_canonical_json(self):
        completed = subprocess.run(
            [sys.executable, "-B", str(SENTRY / "mode_a_guard.py"), "--turns", "0"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["status"], "BLOCKED")

    def test_invocation_cli_contract_is_typed_and_late_binds_mode(self):
        cases = (
            (["--complexity-warrants-omni"], 2, "INVOCATION_GROUNDS_REQUIRED"),
            (["--explicit-user-request", "--activation-level", "OMNI_FULL"], 2, "RUN_KIND_REQUIRED"),
            (["--explicit-user-request", "--activation-level", "OMNI_FULL", "--run-kind", "LIVE"], 2, "RUN_KIND_INVALID"),
        )
        for args, returncode, reason in cases:
            with self.subTest(args=args):
                completed = subprocess.run(
                    [sys.executable, "-B", str(SENTRY / "mode_a_guard.py"), *args],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(completed.returncode, returncode)
                self.assertNotIn("Traceback", completed.stdout + completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["reason_code"], reason)
        digest = "A" * 64
        completed = subprocess.run(
            [
                sys.executable, "-B", str(SENTRY / "mode_a_guard.py"),
                "--explicit-user-request", "--activation-level", "OMNI_FULL",
                "--run-kind", "REAL",
                "--intake-complete", "--program-presented", "--program-sha256", digest,
                "--durable-state", "--midstream-judgment", "--parallel-value",
                "--independent-verifier", "--turns", "3",
            ],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(output["status"], "BLOCKED")
        self.assertIn("CLI_ARGUMENT_INVALID", output["reason_code"])

    def test_invalid_outcome_is_prewrite_failure(self):
        with self.assertRaises(ProtocolError):
            validate_outcome("MAYBE")

    def test_emit_validates_turn_and_receipt_instances_against_schemas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            turn = {
                "schema": "omni-turn-state-v1", "run_id": "R", "turn_id": "T",
                "phase": "F3_BUILD", "status": "BLOCKED_PENDING_HUMAN", "producer": "P",
                "objective_sha256": "A" * 64, "preconditions": [], "evidence": [],
                "failures": [], "reason": "bounded request",
            }
            emitted_turn = emit(turn, root / "turn.json")
            self.assertEqual(emitted_turn["status"], "BLOCKED_PENDING_HUMAN")
            receipt = {
                "schema": "omni-receipt-v1", "receipt_id": "Q", "kind": "VERIFY",
                "status": "PASS", "producer": "P", "inputs": [], "checks": ["schema"],
                "mismatches": [],
            }
            self.assertEqual(emit(receipt, root / "receipt.json")["status"], "PASS")
            invalid = dict(turn, unexpected=True)
            with self.assertRaises(ProtocolError):
                emit(invalid, root / "invalid.json")
            self.assertFalse((root / "invalid.json").exists())

    def test_guided_intake_ready_is_valid_for_team_and_solo_real(self):
        cases = (
            ("TEAM_DUAL_LANE", "REAL", "EXPLICIT_USER_OPT_IN"),
            ("TEAM_DUAL_LANE", "REAL", "PROPOSAL_ACCEPTED"),
            ("SOLO_DUAL_HAT", "REAL", "EXPLICIT_USER_OPT_IN"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for topology, run_kind, activation_path in cases:
                with self.subTest(
                    topology=topology, run_kind=run_kind,
                    activation_path=activation_path,
                ):
                    emitted = emit(
                        guided_state(
                            topology=topology, run_kind=run_kind,
                            activation_path=activation_path,
                        ),
                        root / f"{topology}-{run_kind}-{activation_path}.json",
                    )
                    self.assertEqual(emitted["phase"], "INTAKE_READY")
                    self.assertEqual(emitted["status"], "READY")
                    self.assertEqual(emitted["team_card"]["status"], "TEAM_CARD_DUAL_ACK")
                    self.assertEqual(emitted["critical_closure"]["status"], "CLOSED")
                    self.assertFalse(emitted["relay"]["governed_channel_equivalent"])

    def test_guided_intake_dry_run_cannot_claim_ready(self):
        state = guided_state(topology="SOLO_DUAL_HAT", run_kind="DRY_RUN")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dry-run-ready.json"
            with self.assertRaisesRegex(ProtocolError, "AUTONOMY_UNAVAILABLE_NO_ACCESS"):
                emit(state, output)
            self.assertFalse(output.exists())

    def test_guided_physical_evidence_bindings_fail_closed(self):
        mutants = []

        missing = guided_state()
        missing_ref = next(
            station["source_refs"][0] for station in missing["station_matrix"]
            if station["source_refs"]
        )
        Path(missing_ref["path"]).unlink()
        mutants.append(("CRITICAL_EVIDENCE_MISSING", missing))

        non_file = guided_state()
        non_file_ref = next(
            station["source_refs"][0] for station in non_file["station_matrix"]
            if station["source_refs"]
        )
        non_file_path = Path(non_file_ref["path"])
        non_file_path.unlink()
        non_file_path.mkdir()
        mutants.append(("CRITICAL_EVIDENCE_NOT_REGULAR_FILE", non_file))

        size_drift = guided_state()
        size_ref = next(
            station["source_refs"][0] for station in size_drift["station_matrix"]
            if station["source_refs"]
        )
        size_ref["bytes"] += 1
        reseal_station_matrix(size_drift)
        mutants.append(("CRITICAL_EVIDENCE_SIZE_MISMATCH", size_drift))

        hash_drift = guided_state()
        hash_ref = next(
            station["source_refs"][0] for station in hash_drift["station_matrix"]
            if station["source_refs"]
        )
        hash_ref["sha256"] = "0" * 64
        reseal_station_matrix(hash_drift)
        mutants.append(("CRITICAL_EVIDENCE_HASH_MISMATCH", hash_drift))

        duplicate = guided_state()
        bound_stations = [
            station for station in duplicate["station_matrix"] if station["source_refs"]
        ]
        bound_stations[1]["source_refs"] = [dict(bound_stations[0]["source_refs"][0])]
        reseal_station_matrix(duplicate)
        mutants.append(("CRITICAL_EVIDENCE_PATH_DUPLICATE", duplicate))

        outside = guided_state()
        outside_station = next(
            station for station in outside["station_matrix"] if station["source_refs"]
        )
        escape_path = (
            Path(outside["workspace_access_envelope"]["task_root"])
            / "evidence-outside-project.json"
        )
        outside_station["source_refs"] = [
            write_json_binding(escape_path, {"outside": True})
        ]
        reseal_station_matrix(outside)
        mutants.append(("WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST", outside))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (reason, mutant) in enumerate(mutants, 1):
                with self.subTest(reason=reason):
                    output = root / f"evidence-{index}.json"
                    with self.assertRaisesRegex(ProtocolError, reason):
                        emit(mutant, output)
                    self.assertFalse(output.exists())

    def test_guided_all_physical_bindings_reject_cwd_relative_paths(self):
        """Every physical binding has one CWD-independent absolute-path oracle."""
        mutants = []

        activation = guided_state()
        activation["activation_binding"]["path"] = "activation.json"
        mutants.append(("activation", activation))

        workspace_root = guided_state()
        workspace_root["workspace_access_envelope"]["task_root"] = "task"
        workspace_root["workspace_access_envelope"]["record_digest"] = guided_digest(
            workspace_root["workspace_access_envelope"], "record_digest",
        )
        mutants.append(("workspace-root", workspace_root))

        probe_binding = guided_state()
        probe_binding["workspace_access_envelope"]["probe_receipt_binding"][
            "path"
        ] = "access-probe.receipt.json"
        probe_binding["workspace_access_envelope"]["record_digest"] = guided_digest(
            probe_binding["workspace_access_envelope"], "record_digest",
        )
        mutants.append(("probe-receipt-binding", probe_binding))

        for field, value in (
            ("probe_path", "retained.probe"),
            ("read_proofs", [{"path": "source.txt", "bytes": 12, "sha256": "0" * 64}]),
        ):
            state = guided_state()
            envelope = state["workspace_access_envelope"]
            receipt_path = Path(envelope["probe_receipt_binding"]["path"])
            receipt = strict_json(receipt_path.read_text(encoding="utf-8"))
            receipt[field] = value
            receipt["record_digest"] = guided_digest(receipt, "record_digest")
            envelope["probe_receipt_binding"] = write_json_binding(receipt_path, receipt)
            envelope["record_digest"] = guided_digest(envelope, "record_digest")
            mutants.append((field, state))

        for field, value in (
            ("mandate_path", "mandate.json"),
            ("write_lane", "owned-lanes/builder"),
            ("owned_paths", ["owned-lanes/builder"]),
        ):
            state = guided_state()
            state["session_pair"]["builder"][field] = value
            state["session_pair"]["pair_sha256"] = guided_digest(
                state["session_pair"], "pair_sha256",
            )
            reseal_workspace_access(state)
            mutants.append((f"participant-{field}", state))

        relay_payload = guided_state()
        relay_payload["relay"]["records"][0]["payload_path"] = "relay.json"
        mutants.append(("relay-payload", relay_payload))

        relay_lane = guided_state()
        relay_lane["relay"]["pm_write_lane"] = "owned-lanes/pm"
        mutants.append(("relay-owner-lane", relay_lane))

        source_ref = guided_state()
        next(
            station for station in source_ref["station_matrix"] if station["source_refs"]
        )["source_refs"][0]["path"] = "evidence.json"
        reseal_station_matrix(source_ref)
        mutants.append(("station-source-ref", source_ref))

        proposal = guided_state()
        proposal["intake_proposal"]["proposal"]["path"] = "proposal.json"
        mutants.append(("intake-proposal", proposal))

        for label, mutant in mutants:
            with self.subTest(binding=label), self.assertRaisesRegex(
                ProtocolError, "ABSOLUTE_PATH_REQUIRED"
            ):
                validate_guided_intake_state(mutant)

    def test_guided_relay_and_mandate_bindings_fail_closed(self):
        mutants = []

        relay_missing = guided_state()
        Path(relay_missing["relay"]["records"][0]["payload_path"]).unlink()
        mutants.append(("RELAY_PAYLOAD_MISSING", relay_missing))

        relay_tampered = guided_state()
        relay_path = Path(relay_tampered["relay"]["records"][0]["payload_path"])
        raw = relay_path.read_bytes()
        relay_path.write_bytes((b"X" if raw[:1] != b"X" else b"Y") + raw[1:])
        mutants.append(("RELAY_PAYLOAD_HASH_MISMATCH", relay_tampered))

        relay_duplicate = guided_state()
        builder_records = [
            item for item in relay_duplicate["relay"]["records"]
            if item["origin"] == "BUILDER"
        ]
        for field in ("payload_path", "payload_bytes", "payload_sha256"):
            builder_records[1][field] = builder_records[0][field]
        mutants.append(("RELAY_PAYLOAD_PATH_DUPLICATE", relay_duplicate))

        relay_outside = guided_state()
        relay = relay_outside["relay"]["records"][0]
        outside_path = (
            Path(relay_outside["workspace_access_envelope"]["project_root"])
            / "relay-outside-owner.json"
        )
        relay.update(
            **{
                f"payload_{key}": value
                for key, value in write_bytes_binding(
                    outside_path, Path(relay["payload_path"]).read_bytes(),
                ).items()
                if key != "path"
            }
        )
        relay["payload_path"] = str(outside_path)
        mutants.append(("RELAY_PAYLOAD_OUTSIDE_OWNER_LANE", relay_outside))

        mandate_missing = guided_state()
        Path(mandate_missing["session_pair"]["builder"]["mandate_path"]).unlink()
        mutants.append(("MANDATE_ARTIFACT_MISSING", mandate_missing))

        mandate_tampered = guided_state()
        mandate_path = Path(
            mandate_tampered["session_pair"]["builder"]["mandate_path"]
        )
        raw = mandate_path.read_bytes()
        mandate_path.write_bytes((b"X" if raw[:1] != b"X" else b"Y") + raw[1:])
        mutants.append(("MANDATE_ARTIFACT_HASH_MISMATCH", mandate_tampered))

        mandate_content = guided_state()
        participant = mandate_content["session_pair"]["builder"]
        wrong_mandate = strict_json(Path(participant["mandate_path"]).read_text(encoding="utf-8"))
        wrong_mandate["identity"] = "Wrong identity"
        binding = write_json_binding(Path(participant["mandate_path"]), wrong_mandate)
        participant.update(
            mandate_bytes=binding["bytes"], mandate_sha256=binding["sha256"],
        )
        mandate_content["session_pair"]["pair_sha256"] = guided_digest(
            mandate_content["session_pair"], "pair_sha256",
        )
        reseal_workspace_access(mandate_content)
        mutants.append(("MANDATE_CONTENT_MISMATCH", mandate_content))

        mandate_outside = guided_state()
        participant = mandate_outside["session_pair"]["builder"]
        exact_mandate = strict_json(Path(participant["mandate_path"]).read_text(encoding="utf-8"))
        outside_path = (
            Path(mandate_outside["workspace_access_envelope"]["project_root"])
            / "mandate-outside-owner.json"
        )
        binding = write_json_binding(outside_path, exact_mandate)
        participant.update(
            mandate_path=binding["path"], mandate_bytes=binding["bytes"],
            mandate_sha256=binding["sha256"],
        )
        mandate_outside["session_pair"]["pair_sha256"] = guided_digest(
            mandate_outside["session_pair"], "pair_sha256",
        )
        reseal_workspace_access(mandate_outside)
        mutants.append(("MANDATE_OUTSIDE_OWNER_LANE", mandate_outside))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (reason, mutant) in enumerate(mutants, 1):
                with self.subTest(reason=reason):
                    output = root / f"artifact-{index}.json"
                    with self.assertRaisesRegex(ProtocolError, reason):
                        emit(mutant, output)
                    self.assertFalse(output.exists())

    def test_guided_workspace_access_mutants_and_partial_access_fail_closed(self):
        mutants = []

        missing_grant = guided_state()
        missing_grant["workspace_access_envelope"]["granted_capabilities"].pop()
        missing_grant["workspace_access_envelope"]["record_digest"] = guided_digest(
            missing_grant["workspace_access_envelope"], "record_digest",
        )
        mutants.append(("RECORD_SCHEMA_INVALID", missing_grant))

        missing_root = guided_state()
        missing_root["workspace_access_envelope"]["source_roots"] = [
            str(Path(missing_root["workspace_access_envelope"]["task_root"]) / "missing")
        ]
        missing_root["workspace_access_envelope"]["record_digest"] = guided_digest(
            missing_root["workspace_access_envelope"], "record_digest",
        )
        mutants.append(("WORKSPACE_ACCESS_ROOT_MISSING", missing_root))

        escaped_root = guided_state()
        task_root = Path(escaped_root["workspace_access_envelope"]["task_root"])
        escaped_project = task_root.parent / "escaped-project"
        escaped_project.mkdir()
        escaped_root["workspace_access_envelope"]["project_root"] = str(escaped_project)
        escaped_root["workspace_access_envelope"]["record_digest"] = guided_digest(
            escaped_root["workspace_access_envelope"], "record_digest",
        )
        mutants.append(("WORKSPACE_ACCESS_PATH_OUTSIDE_ALLOWLIST", escaped_root))

        replay = guided_state()
        replay["workspace_access_envelope"]["task_id"] = "OTHER-TASK"
        replay["workspace_access_envelope"]["record_digest"] = guided_digest(
            replay["workspace_access_envelope"], "record_digest",
        )
        mutants.append(("WORKSPACE_ACCESS_SCOPE_REPLAY", replay))

        probe_missing = guided_state()
        Path(
            probe_missing["workspace_access_envelope"]["probe_receipt_binding"]["path"]
        ).unlink()
        mutants.append(("WORKSPACE_ACCESS_PROBE_MISSING", probe_missing))

        probe_tampered = guided_state()
        probe_path = Path(
            probe_tampered["workspace_access_envelope"]["probe_receipt_binding"]["path"]
        )
        raw = probe_path.read_bytes()
        probe_path.write_bytes((b"X" if raw[:1] != b"X" else b"Y") + raw[1:])
        mutants.append(("WORKSPACE_ACCESS_PROBE_HASH_MISMATCH", probe_tampered))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (reason, mutant) in enumerate(mutants, 1):
                with self.subTest(reason=reason):
                    output = root / f"access-{index}.json"
                    with self.assertRaisesRegex(ProtocolError, reason):
                        emit(mutant, output)
                    self.assertFalse(output.exists())

            partial = guided_state()
            envelope = partial["workspace_access_envelope"]
            envelope.update(
                status="AUTONOMY_UNAVAILABLE_NO_ACCESS",
                outcome="ACCESS_PARTIAL",
                granted_capabilities=["READ_NAMED_SOURCES"],
                probe_receipt_binding=None,
            )
            envelope["record_digest"] = guided_digest(envelope, "record_digest")
            partial.update(
                phase="INTAKE_BLOCKED", status="BLOCKED",
                blocking_reason_codes=["AUTONOMY_UNAVAILABLE_NO_ACCESS"],
            )
            emitted = emit(partial, root / "partial-access.json")
            self.assertEqual(emitted["status"], "BLOCKED")
            self.assertIn(
                "AUTONOMY_UNAVAILABLE_NO_ACCESS", emitted["blocking_reason_codes"],
            )

    def test_guided_requires_full_activation_and_external_access_schemas_agree(self):
        state = guided_state()
        envelope = state["workspace_access_envelope"]
        probe = strict_json(
            Path(envelope["probe_receipt_binding"]["path"]).read_text(encoding="utf-8")
        )
        for schema_name, instance in (
            ("workspace_access_envelope.schema.json", envelope),
            ("workspace_access_probe_receipt.schema.json", probe),
        ):
            schema = strict_json((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
            self.assertEqual(
                list(Draft202012Validator(schema).iter_errors(instance)), [], schema_name,
            )
        standalone_access_schema = strict_json(
            (ROOT / "schemas" / "workspace_access_envelope.schema.json").read_text(encoding="utf-8")
        )
        guided_schema = strict_json(
            (ROOT / "schemas" / "guided_intake_state.schema.json").read_text(encoding="utf-8")
        )
        embedded_access_schema = {
            "$schema": guided_schema["$schema"],
            "$defs": guided_schema["$defs"],
            "$ref": "#/$defs/workspace_access_envelope_contract",
        }
        access_validators = (
            ("standalone", Draft202012Validator(standalone_access_schema)),
            ("embedded", Draft202012Validator(embedded_access_schema)),
        )
        legal_partial = json.loads(json.dumps(envelope))
        legal_partial.update(
            status="AUTONOMY_UNAVAILABLE_NO_ACCESS",
            outcome="ACCESS_PARTIAL",
            run_kind="REAL",
            granted_capabilities=["READ_NAMED_SOURCES"],
            probe_receipt_binding=None,
        )
        legal_denied = json.loads(json.dumps(envelope))
        legal_denied.update(
            status="AUTONOMY_UNAVAILABLE_NO_ACCESS",
            outcome="ACCESS_DENIED",
            run_kind="REAL",
            granted_capabilities=[],
            probe_receipt_binding=None,
        )
        for label, compiled in access_validators:
            with self.subTest(schema=label, legal="partial"):
                self.assertEqual(list(compiled.iter_errors(legal_partial)), [])
            with self.subTest(schema=label, legal="denied"):
                self.assertEqual(list(compiled.iter_errors(legal_denied)), [])

        impossible_granted = json.loads(json.dumps(envelope))
        impossible_granted["status"] = "AUTONOMY_UNAVAILABLE_NO_ACCESS"
        denied_with_grants = json.loads(json.dumps(legal_denied))
        denied_with_grants["granted_capabilities"] = list(envelope["granted_capabilities"])
        partial_with_full_grants = json.loads(json.dumps(legal_partial))
        partial_with_full_grants["granted_capabilities"] = list(envelope["granted_capabilities"])
        partial_without_grants = json.loads(json.dumps(legal_partial))
        partial_without_grants["granted_capabilities"] = []
        for mutant_name, mutant in (
            ("unavailable_but_granted", impossible_granted),
            ("denied_with_full_grants", denied_with_grants),
            ("partial_with_full_grants", partial_with_full_grants),
            ("partial_without_grants", partial_without_grants),
        ):
            for label, compiled in access_validators:
                with self.subTest(schema=label, mutant=mutant_name):
                    self.assertTrue(list(compiled.iter_errors(mutant)))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                emit(state, Path(directory) / "cross-schema-positive.json")["status"],
                "READY",
            )

        module_state = guided_state()
        module_receipt = decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            run_kind="REAL",
            activation_level="OMNI_MODULE",
            modules=["modules/KNOWLEDGE_RESEARCH_DOSSIER"],
        )
        rewrite_activation_receipt(
            module_state, module_receipt,
            Path(_GUIDED_RECEIPT_DIR.name) / "module-activation.json",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "module-guided.json"
            with self.assertRaises(ProtocolError) as blocked:
                emit(module_state, output)
            self.assertTrue(
                "RECORD_SCHEMA_INVALID" in str(blocked.exception)
                or "ACTIVATION_NOT_ALLOWED" in str(blocked.exception)
                or "ACTIVATION_LEVEL_INSUFFICIENT" in str(blocked.exception)
            )
            self.assertFalse(output.exists())

    def test_guided_critical_known_stations_close_only_from_bound_evidence(self):
        state = guided_state()
        objective = next(
            station for station in state["station_matrix"]
            if station["station_id"] == "OBJECTIVE"
        )
        self.assertTrue(all(station["critical"] for station in state["station_matrix"]))
        self.assertEqual(objective["question_ids"], [])
        self.assertTrue(objective["source_refs"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            emitted = emit(state, root / "positive.json")
            self.assertEqual(emitted["critical_closure"]["status"], "CLOSED")

            no_evidence = guided_state()
            objective = next(
                station for station in no_evidence["station_matrix"]
                if station["station_id"] == "OBJECTIVE"
            )
            objective["source_refs"] = []
            reseal_station_matrix(no_evidence)
            output = root / "no-evidence.json"
            with self.assertRaisesRegex(ProtocolError, "CRITICAL_STATION_EVIDENCE_MISSING"):
                emit(no_evidence, output)
            self.assertFalse(output.exists())

            digest_drift = guided_state()
            bound_station = next(
                station for station in digest_drift["station_matrix"]
                if station["source_refs"]
            )
            bound_station["source_refs"][0]["sha256"] = "0" * 64
            output = root / "digest-drift.json"
            with self.assertRaisesRegex(ProtocolError, "STATION_MATRIX_DIGEST_MISMATCH"):
                emit(digest_drift, output)
            self.assertFalse(output.exists())

    def test_guided_activation_receipt_is_physical_accepted_and_path_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            declined = guided_state()
            declined_receipt = decide_invocation(
                explicit_user_request=False,
                complexity_warrants_omni=True,
                consent_state="DECLINED",
                grounds=("DURABLE_KNOWLEDGE",),
            )
            bind_receipt_file(declined, declined_receipt, root / "declined.json")
            with self.assertRaisesRegex(ProtocolError, "ACTIVATION_NOT_ALLOWED"):
                emit(declined, root / "declined-state.json")

            missing = guided_state()
            missing["activation_binding"]["path"] = str(root / "missing.json")
            with self.assertRaisesRegex(ProtocolError, "ACTIVATION_RECEIPT_MISSING"):
                emit(missing, root / "missing-state.json")

            tampered = guided_state()
            accepted_receipt = strict_json(
                Path(tampered["activation_binding"]["path"]).read_text(encoding="utf-8")
            )
            receipt_path = root / "tampered.json"
            bind_receipt_file(tampered, accepted_receipt, receipt_path)
            receipt_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ProtocolError, "ACTIVATION_RECEIPT_MISMATCH"):
                emit(tampered, root / "tampered-state.json")

            path_drift = guided_state()
            path_drift["activation_binding"]["activation_path"] = "PROPOSAL_ACCEPTED"
            with self.assertRaisesRegex(ProtocolError, "ACTIVATION_PATH_MISMATCH"):
                emit(path_drift, root / "path-drift.json")

    def test_guided_identity_relay_readback_and_solo_authority_mutants(self):
        mutants = []

        identity = guided_state()
        identity["session_pair"]["verifier"]["identity"] = "  codex BUILDER  "
        rewrite_mandate(identity, "verifier")
        identity["session_pair"]["pair_sha256"] = guided_digest(
            identity["session_pair"], "pair_sha256",
        )
        reseal_workspace_access(identity)
        mutants.append(("IDENTITY_NOT_DISTINCT", identity))

        solo_authority = guided_state(topology="SOLO_DUAL_HAT")
        solo_authority["team_card"]["partner_selection_authorization_relay_id"] = "RELAY-999"
        reseal_card(solo_authority)
        mutants.append(("PARTNER_SELECTION_AUTHORITY_MISSING", solo_authority))

        relay_state = guided_state()
        relay_state["relay"]["state"] = "CUTOVER_PENDING"
        mutants.append(("RELAY_STATE_INVALID", relay_state))

        readback = guided_state()
        readback["question_matrix"]["questions"][0]["readbacks"]["builder"][
            "observed_answer_sha256"
        ] = "0" * 64
        reseal_question_matrix(readback)
        mutants.append(("FOUR_READBACK_CONTENT_MISMATCH", readback))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (reason, mutant) in enumerate(mutants, 1):
                with self.subTest(reason=reason):
                    output = root / f"mutant-{index}.json"
                    with self.assertRaisesRegex(ProtocolError, reason):
                        emit(mutant, output)
                    self.assertFalse(output.exists())

    def test_profile_degraded_and_adversarial_solo_are_explicitly_representable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            solo = emit(guided_state(topology="SOLO_DUAL_HAT"), root / "solo.json")
            self.assertEqual(solo["profile"], "GODMODE")
            self.assertEqual(solo["independence"], "ADVERSARIAL_SOLO")

            degraded = emit(profile_degraded_state(), root / "degraded.json")
            self.assertEqual(degraded["profile"], "PROFILE_DEGRADED")
            self.assertEqual(degraded["independence"], "NOT_QUALIFIED")
            self.assertEqual(degraded["phase"], "INTAKE_BLOCKED")
            self.assertEqual(degraded["status"], "BLOCKED")

    def test_guided_intake_mutants_fail_closed_before_write(self):
        mutants = []

        run_kind_drift = guided_state()
        run_kind_drift["activation_binding"]["run_kind"] = "DRY_RUN"
        mutants.append(("ACTIVATION_RECEIPT_MISMATCH", run_kind_drift))

        pair_drift = guided_state()
        pair_drift["session_pair"]["verifier"]["session_id"] = pair_drift["session_pair"]["builder"]["session_id"]
        mutants.append(("SESSION_PAIR_DRIFT", pair_drift))

        missing_partner_authority = guided_state()
        missing_partner_authority["team_card"]["partner_selection_authorization_relay_id"] = "RELAY-999"
        reseal_card(missing_partner_authority)
        mutants.append(("PARTNER_SELECTION_AUTHORITY_MISSING", missing_partner_authority))

        relay_gap = guided_state()
        relay_gap["relay"]["records"][1]["ordinal"] = 99
        mutants.append(("RELAY_SEQUENCE_INVALID", relay_gap))

        relay_duplicate = guided_state()
        relay_duplicate["relay"]["records"][1]["relay_id"] = relay_duplicate["relay"]["records"][0]["relay_id"]
        mutants.append(("RELAY_ID_DUPLICATE", relay_duplicate))

        relay_payload_drift = guided_state()
        relay_payload_drift["relay"]["records"][4]["payload_sha256"] = "0" * 64
        mutants.append(("RELAY_PAYLOAD_HASH_MISMATCH", relay_payload_drift))

        question_digest_drift = guided_state()
        question_digest_drift["question_matrix"]["questions"][0]["text"] = "mutated"
        question_digest_drift["question_matrix"]["matrix_sha256"] = guided_digest(
            question_digest_drift["question_matrix"], "matrix_sha256",
        )
        mutants.append(("QUESTION_DIGEST_MISMATCH", question_digest_drift))

        missing_lane_readback = guided_state()
        del missing_lane_readback["question_matrix"]["questions"][0]["readbacks"]["verifier"]
        missing_lane_readback["question_matrix"]["matrix_sha256"] = guided_digest(
            missing_lane_readback["question_matrix"], "matrix_sha256",
        )
        mutants.append(("RECORD_SCHEMA_INVALID", missing_lane_readback))

        false_closed = guided_state()
        first_answer = false_closed["question_matrix"]["questions"][0]["answer"]
        first_answer["classification_after"] = "UNKNOWN"
        answer_raw = canonical_json(
            {
                field: first_answer[field]
                for field in ("source", "text", "relay_id", "classification_after")
            }
        ).encode("utf-8")
        first_answer["answer_sha256"] = rewrite_relay_payload(
            false_closed, first_answer["relay_id"], answer_raw,
        )
        for readback in false_closed["question_matrix"]["questions"][0]["readbacks"].values():
            readback["observed_answer_sha256"] = first_answer["answer_sha256"]
            rewrite_relay_payload(false_closed, readback["answer_relay_id"], answer_raw)
        false_closed["question_matrix"]["matrix_sha256"] = guided_digest(
            false_closed["question_matrix"], "matrix_sha256",
        )
        false_closed["critical_closure"]["question_matrix_sha256"] = false_closed["question_matrix"]["matrix_sha256"]
        mutants.append(("CRITICAL_CLOSURE_MISMATCH", false_closed))

        proposal_ack_missing = guided_state()
        proposal_ack_missing["intake_proposal"]["acks"]["verifier"]["status"] = "MISSING"
        proposal_ack_missing["intake_proposal"]["acks"]["verifier"]["observed_proposal_sha256"] = None
        mutants.append(("INTAKE_PROPOSAL_DUAL_READBACK_MISSING", proposal_ack_missing))

        premature_well = guided_state()
        premature_well["well"] = {"state": "WELL_ACTIVE", "artifact_sha256": "B" * 64}
        mutants.append(("PREMATURE_L3_L5_STATE", premature_well))

        relay_pair_drift = guided_state()
        relay_pair_drift["relay"]["session_pair_sha256"] = "C" * 64
        mutants.append(("SESSION_PAIR_CHANGED_BEFORE_CUTOVER", relay_pair_drift))

        material_before_team_card = guided_state()
        material_before_team_card["phase"] = "QUESTIONS_ACTIVE"
        material_before_team_card["status"] = "ACTIVE"
        material_before_team_card["team_card"]["status"] = "AWAITING_DUAL_ACK"
        for ack in material_before_team_card["team_card"]["acks"].values():
            ack["status"] = "MISSING"
            ack["observed_card_sha256"] = None
        reseal_card(material_before_team_card)
        mutants.append(("TEAM_CARD_REQUIRED_BEFORE_INTAKE", material_before_team_card))

        dry_effect = guided_state(topology="SOLO_DUAL_HAT", run_kind="DRY_RUN")
        dry_effect["effect_policy"] = "DOWNSTREAM_GATED_REAL"
        mutants.append(("DRY_RUN_EFFECT_ATTEMPTED", dry_effect))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (reason, mutant) in enumerate(mutants, 1):
                with self.subTest(reason=reason):
                    output = root / f"mutant-{index:02d}.json"
                    with self.assertRaisesRegex(ProtocolError, reason):
                        emit(mutant, output)
                    self.assertFalse(output.exists())

    def test_guided_intake_rejects_narrative_completeness_claim(self):
        state = guided_state()
        state["no_open_critical_questions"] = True
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "narrative.json"
            with self.assertRaisesRegex(ProtocolError, "RECORD_SCHEMA_INVALID"):
                emit(state, output)
            self.assertFalse(output.exists())

    def test_boundary_clis_return_typed_block_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "bad.json"
            malformed.write_text("{", encoding="utf-8")
            valid_list = root / "list.json"
            valid_list.write_text("[]", encoding="utf-8")
            cases = [
                [sys.executable, "-B", str(SCRIPTS / "check_handoff.py"), str(malformed)],
                [sys.executable, "-B", str(SCRIPTS / "validate_wbs.py"), str(malformed)],
                [sys.executable, "-B", str(SCRIPTS / "fuse_lanes.py"), str(malformed), str(valid_list), str(root / "fusion.json")],
                [sys.executable, "-B", str(SCRIPTS / "coordinator" / "run.py"), "--previous", str(malformed), "--current", str(valid_list), "--objective-digest", "A"],
                [sys.executable, "-B", str(SENTRY / "wakeup.py"), str(root / "missing-channel"), "--baseline", "0"],
                [sys.executable, "-B", str(SENTRY / "supervisor.py"), "--state-dir", str(root / "state"), "--owner", "O", "--generation", "1", "--baseline", "0", "--max-cycles", "0"],
                [sys.executable, "-B", str(SCRIPTS / "count_tokens.py"), str(root / "missing.md")],
                [sys.executable, "-B", str(SCRIPTS / "check_references.py"), str(root / "missing-root")],
                [sys.executable, "-B", str(SCRIPTS / "seed_well.py"), "--objective", "O", "--authority", "A", "--output", str(root / "well.json"), "--scope", "F5"],
            ]
            for command in cases:
                with self.subTest(script=Path(command[2]).name):
                    completed = subprocess.run(command, capture_output=True, text=True, check=False)
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr + completed.stdout)
                    self.assertEqual(json.loads(completed.stdout)["status"], "BLOCKED")

    def test_strict_json_rejects_bom_float_and_duplicate(self):
        for payload in ("\ufeff{}", '{"x":1.5}', '{"x":1,"x":2}'):
            with self.assertRaises(ValueError):
                strict_json(payload)

    def test_orphan_claim_reconciles_exactly_and_blocks_cross_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claim = root / "claim.json"
            record = root / "record.json"
            digest = "A" * 64
            claim_evidence(claim, "W1", digest)
            observed = reconcile_claim(claim, record, {"work_id": "W1", "evidence_sha256": digest})
            self.assertEqual(observed["work_id"], "W1")
            with self.assertRaises(ProtocolError):
                reconcile_claim(claim, root / "other.json", {"work_id": "W2", "evidence_sha256": digest})


if __name__ == "__main__":
    unittest.main()

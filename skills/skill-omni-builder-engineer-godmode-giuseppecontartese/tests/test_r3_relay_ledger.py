from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from relay_ledger import (  # noqa: E402
    CANONICALIZATION_VERSION,
    ENTRY_DOMAIN,
    EXTERNAL_ANCHOR_QUALIFICATION_SCHEMA,
    LEASE_AUTHORITY_SCHEMA,
    REPAIR_AUTHORITY_SCHEMA,
    REQUEST_DOMAIN,
    SEAL_DOMAIN,
    Lease,
    LedgerError,
    RelayLedger,
    RotationPolicy,
    canonical_json,
    create_external_anchor,
    external_anchor_qualification_subject,
    hash_core,
    read_vector_checkpoint,
    verify_external_anchor,
    verify_vector_checkpoint,
    write_vector_checkpoint,
)


FUTURE = "2099-01-01T00:00:00Z"
AUTHORIZED_AT = "2026-07-31T10:00:00Z"


def event(number: int) -> str:
    return str(uuid.UUID(int=number, version=4))


def lease_authority(
    ledger: RelayLedger,
    lease: Lease,
    *,
    authority_id: str = "AUTH-1",
) -> dict:
    return {
        "schema": LEASE_AUTHORITY_SCHEMA,
        "action": "ACTIVATE_STREAM_LEASE",
        "run_id": ledger.run_id,
        "stream_id": ledger.stream_id,
        "writer_id": lease.writer_id,
        "writer_instance_id": lease.writer_instance_id,
        "lease_id": lease.lease_id,
        "fence": lease.fence,
        "topology": ledger.topology,
        "independent_verifier": ledger.independent_verifier,
        "authorized_by": "PM",
        "authority_id": authority_id,
        "authority_source": "HUMAN_EXPLICIT",
        "authorized_at": AUTHORIZED_AT,
        "expires_at": FUTURE,
    }


def install_lease(
    ledger: RelayLedger,
    *,
    writer: str,
    instance: str,
    lease_id: str,
    fence: int,
) -> Lease:
    lease = Lease(writer, instance, lease_id, fence, FUTURE)
    ledger.activate_lease(
        lease, lease_authority(ledger, lease, authority_id=f"AUTH-{fence}")
    )
    return lease


def external_qualification(subject: dict, *, qualification_id: str = "QUAL-1") -> dict:
    return {
        "schema": EXTERNAL_ANCHOR_QUALIFICATION_SCHEMA,
        "status": "CALLER_QUALIFIED_UNVERIFIED",
        "anchor_set_id": subject["anchor_set_id"],
        "run_id": subject["run_id"],
        "anchor_root_fingerprint": subject["anchor_root_fingerprint"],
        "ledger_roots": subject["ledger_roots"],
        "trust_domain_id": "REMOTE-WORM-1",
        "qualification_id": qualification_id,
        "qualified_by": "PM",
        "basis": "WORM",
        "evidence_sha256": "E" * 64,
        "qualified_at": AUTHORIZED_AT,
        "expires_at": FUTURE,
    }


class RelayLedgerR3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads(
            (ROOT / "schemas" / "relay_ledger_entry.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.schema_validator = Draft202012Validator(
            schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        )
        anchor_schema = {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            **schema["$defs"]["external_anchor_record"],
        }
        cls.anchor_validator = Draft202012Validator(
            anchor_schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        )
        qualification_schema = {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            **schema["$defs"]["external_anchor_qualification"],
        }
        cls.qualification_validator = Draft202012Validator(
            qualification_schema,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        seal_schema = {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            **schema["$defs"]["volume_seal"],
        }
        cls.seal_validator = Draft202012Validator(
            seal_schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        )

    def test_rotation_policy_does_not_trigger_below_both_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = RotationPolicy(
                max_entries_per_volume=2,
                max_bytes_per_volume=10_000_000,
            )
            ledger = RelayLedger(
                root, "RUN-ROTATE-NO", "builder", rotation_policy=policy
            )
            lease = install_lease(
                ledger,
                writer="builder",
                instance="builder-process",
                lease_id="LEASE",
                fence=1,
            )
            result = ledger.append(
                lease, event_id=event(80), title="Below", body="threshold"
            )
            self.assertEqual(
                result["rotation"]["status"], "ROTATION_NOT_TRIGGERED"
            )
            self.assertEqual(result["rotation"]["rotation_reasons"], [])
            self.assertFalse((root / "builder.000001.seal.json").exists())
            self.assertEqual(len(list(root.glob("builder.*.ndjson"))), 1)

    def test_rotation_policy_triggers_at_entry_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = RotationPolicy(
                max_entries_per_volume=2,
                max_bytes_per_volume=10_000_000,
            )
            ledger = RelayLedger(
                root, "RUN-ROTATE-ENTRY", "builder", rotation_policy=policy
            )
            lease = install_lease(
                ledger,
                writer="builder",
                instance="builder-process",
                lease_id="LEASE",
                fence=1,
            )
            ledger.append(lease, event_id=event(81), title="One", body="one")
            triggered = ledger.append(
                lease, event_id=event(82), title="Two", body="two"
            )
            rotation = triggered["rotation"]
            self.assertEqual(rotation["status"], "ROTATED")
            self.assertEqual(
                rotation["seal"]["rotation_reasons"], ["ENTRY_THRESHOLD"]
            )
            self.assertEqual(rotation["seal"]["rotation_policy"], policy.as_record())
            self.seal_validator.validate(rotation["seal"])
            seal_path = root / "builder.000001.seal.json"
            mutated = dict(rotation["seal"])
            mutated["rotation_policy"] = {
                **mutated["rotation_policy"],
                "max_entries_per_volume": 3,
            }
            mutated_core = dict(mutated)
            mutated_core.pop("seal_hash")
            mutated["seal_hash"] = hash_core(SEAL_DOMAIN, mutated_core)
            seal_path.write_text(
                canonical_json(mutated) + "\n", encoding="utf-8", newline="\n"
            )
            with self.assertRaises(LedgerError) as caught:
                ledger.validate()
            self.assertEqual(
                caught.exception.code, "ROTATION_REASON_BINDING_MISMATCH"
            )
            seal_path.write_text(
                canonical_json(rotation["seal"]) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            after = ledger.append(
                lease, event_id=event(83), title="Next volume", body="causal"
            )
            self.assertEqual(after["entry"]["stream_seq"], 3)
            self.assertEqual(after["entry"]["volume_no"], 2)
            self.assertEqual(
                after["entry"]["prev_volume_seal_hash"],
                rotation["seal"]["seal_hash"],
            )

    def test_rotation_policy_triggers_at_exact_byte_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = RotationPolicy(
                max_entries_per_volume=100,
                max_bytes_per_volume=1,
            )
            ledger = RelayLedger(
                root, "RUN-ROTATE-BYTE", "builder", rotation_policy=policy
            )
            lease = install_lease(
                ledger,
                writer="builder",
                instance="builder-process",
                lease_id="LEASE",
                fence=1,
            )
            result = ledger.append(
                lease, event_id=event(84), title="Bytes", body="x"
            )
            seal = result["rotation"]["seal"]
            self.assertEqual(result["rotation"]["status"], "ROTATED")
            self.assertEqual(seal["rotation_reasons"], ["BYTE_THRESHOLD"])
            self.assertGreaterEqual(
                seal["byte_length"], policy.max_bytes_per_volume
            )
            self.seal_validator.validate(seal)

    def test_rotation_policy_triggers_phase_gate_create_once_and_per_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = RotationPolicy(
                max_entries_per_volume=100,
                max_bytes_per_volume=10_000_000,
            )
            builder = RelayLedger(
                root, "RUN-ROTATE-PHASE", "builder", rotation_policy=policy
            )
            verifier = RelayLedger(
                root,
                "RUN-ROTATE-PHASE",
                "verifier",
                independent_verifier=True,
                rotation_policy=policy,
            )
            builder_lease = install_lease(
                builder,
                writer="builder",
                instance="builder-process",
                lease_id="LEASE-B",
                fence=1,
            )
            verifier_lease = install_lease(
                verifier,
                writer="verifier",
                instance="verifier-process",
                lease_id="LEASE-V",
                fence=1,
            )
            builder.append(
                builder_lease, event_id=event(85), title="Builder", body="ready"
            )
            verifier.append(
                verifier_lease,
                event_id=event(86),
                title="Verifier",
                body="independent",
                hat="VERIFIER",
            )
            rotated = builder.rotate_for_phase_gate(builder_lease, "F3_TO_F4")
            self.assertEqual(rotated["status"], "ROTATED")
            self.assertEqual(rotated["seal"]["rotation_reasons"], ["PHASE_GATE"])
            self.assertEqual(rotated["seal"]["phase_gate_id"], "F3_TO_F4")
            self.seal_validator.validate(rotated["seal"])
            retried = builder.rotate_for_phase_gate(builder_lease, "F3_TO_F4")
            self.assertEqual(retried["status"], "ROTATION_RECONCILED")
            self.assertEqual(
                retried["seal"]["seal_hash"], rotated["seal"]["seal_hash"]
            )
            self.assertEqual(len(list(root.glob("builder.*.seal.json"))), 1)
            self.assertFalse((root / "verifier.000001.seal.json").exists())
            self.assertEqual(verifier.validate()["next_seq"], 2)
            after = builder.append(
                builder_lease,
                event_id=event(87),
                title="After gate",
                body="continued",
            )
            self.assertEqual(after["entry"]["stream_seq"], 2)
            self.assertEqual(
                after["entry"]["prev_volume_seal_hash"],
                rotated["seal"]["seal_hash"],
            )

    def test_pos_canonical_hash_reconcile_vector_checkpoint_and_no_global_max(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            builder = RelayLedger(root, "RUN-1", "builder")
            verifier = RelayLedger(
                root, "RUN-1", "verifier", independent_verifier=True
            )
            builder_lease = install_lease(
                builder,
                writer="builder",
                instance="builder-process",
                lease_id="LEASE-B",
                fence=1,
            )
            verifier_lease = install_lease(
                verifier,
                writer="verifier",
                instance="verifier-process",
                lease_id="LEASE-V",
                fence=1,
            )

            first = builder.append(
                builder_lease,
                event_id=event(1),
                title="Build",
                body="line 1\r\nline 2",
            )
            second = builder.append(
                builder_lease,
                event_id=event(2),
                title="Correction",
                body="body",
                kind="CORRECTION",
                supersedes=[first["entry"]["entry_hash"]],
            )
            peer = verifier.append(
                verifier_lease,
                event_id=event(3),
                title="Verify",
                body="independent",
                hat="VERIFIER",
            )

            self.schema_validator.validate(first["entry"])
            self.schema_validator.validate(second["entry"])
            self.schema_validator.validate(peer["entry"])
            self.assertEqual(first["entry"]["stream_seq"], 1)
            self.assertEqual(peer["entry"]["stream_seq"], 1)
            self.assertEqual(second["entry"]["stream_seq"], 2)
            self.assertEqual(
                second["entry"]["prev_entry_hash"], first["entry"]["entry_hash"]
            )
            self.assertEqual(first["entry"]["body"], "line 1\nline 2")
            self.assertEqual(
                first["entry"]["entry_hash"],
                hash_core(
                    ENTRY_DOMAIN,
                    {
                        key: value
                        for key, value in first["entry"].items()
                        if key != "entry_hash"
                    },
                ),
            )

            reconciled = builder.append(
                builder_lease,
                event_id=event(1),
                title="Build",
                body="line 1\nline 2",
            )
            self.assertEqual(reconciled["status"], "RECONCILED")
            self.assertEqual(len(builder.validate()["records"]), 2)

            checkpoint_path = root / "consumer.vector.json"
            checkpoint = write_vector_checkpoint(
                checkpoint_path, "CONSUMER-1", [verifier, builder]
            )
            self.assertEqual(
                [head["stream_id"] for head in checkpoint["heads"]],
                ["builder", "verifier"],
            )
            self.assertEqual(read_vector_checkpoint(checkpoint_path), checkpoint)
            self.assertEqual(
                verify_vector_checkpoint(checkpoint, [builder, verifier]),
                {"builder": [], "verifier": []},
            )

    def test_pos_canonical_body_bytes_and_causal_request_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verifier = RelayLedger(
                root, "RUN-CAUSAL", "verifier", independent_verifier=True
            )
            builder = RelayLedger(root, "RUN-CAUSAL", "builder")
            verifier_lease = install_lease(
                verifier,
                writer="verifier",
                instance="verifier-process",
                lease_id="LEASE-V",
                fence=1,
            )
            builder_lease = install_lease(
                builder,
                writer="builder",
                instance="builder-process",
                lease_id="LEASE-B",
                fence=1,
            )
            peer = verifier.append(
                verifier_lease,
                event_id=event(4),
                title="Peer observation",
                body="ready",
                hat="VERIFIER",
            )["entry"]
            observed = [
                {
                    "stream_id": "verifier",
                    "stream_seq": peer["stream_seq"],
                    "entry_hash": peer["entry_hash"],
                }
            ]
            result = builder.append(
                builder_lease,
                event_id=event(5),
                title="Causal handoff",
                body="caffè\r\nok",
                observed_heads=observed,
            )
            entry = result["entry"]
            self.schema_validator.validate(entry)
            self.assertEqual(
                entry["canonicalization_version"], CANONICALIZATION_VERSION
            )
            self.assertEqual(entry["body"], "caffè\nok")
            self.assertEqual(entry["body_bytes"], len("caffè\nok".encode("utf-8")))
            self.assertEqual(entry["observed_heads"], observed)
            reconciled = builder.append(
                builder_lease,
                event_id=event(5),
                title="Causal handoff",
                body="caffè\nok",
                observed_heads=observed,
            )
            self.assertEqual(reconciled["status"], "RECONCILED")
            changed_observation = [
                {
                    "stream_id": "verifier",
                    "stream_seq": peer["stream_seq"],
                    "entry_hash": "A" * 64,
                }
            ]
            with self.assertRaises(LedgerError) as caught:
                builder.append(
                    builder_lease,
                    event_id=event(5),
                    title="Causal handoff",
                    body="caffè\nok",
                    observed_heads=changed_observation,
                )
            self.assertEqual(caught.exception.code, "EVENT_ID_CONFLICT")

    def test_neg_full_entry_hash_stale_fence_and_event_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = RelayLedger(root, "RUN-2", "builder")
            lease1 = install_lease(
                ledger,
                writer="builder",
                instance="process-1",
                lease_id="LEASE-1",
                fence=1,
            )
            appended = ledger.append(
                lease1, event_id=event(10), title="Original", body="body"
            )
            path = root / "builder.000001.ndjson"
            record = dict(appended["entry"])
            # created_at is outside the retry/request fingerprint but inside the
            # full-entry hash, so this mutation isolates the chain seal.
            record["created_at"] = "2026-07-31T10:00:01.000Z"
            path.write_text(canonical_json(record) + "\n", encoding="utf-8", newline="\n")
            with self.assertRaises(LedgerError) as caught:
                ledger.validate()
            self.assertEqual(caught.exception.code, "ENTRY_HASH_MISMATCH")

            # Restore exact canonical bytes, then fence the original process.
            path.write_text(
                canonical_json(appended["entry"]) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            lease2 = install_lease(
                ledger,
                writer="builder",
                instance="process-2",
                lease_id="LEASE-2",
                fence=2,
            )
            with self.assertRaises(LedgerError) as caught:
                ledger.append(
                    lease1, event_id=event(11), title="Late old writer", body="blocked"
                )
            self.assertEqual(caught.exception.code, "LEASE_MISMATCH")
            self.assertEqual(len(ledger.validate()["records"]), 1)

            with self.assertRaises(LedgerError) as caught:
                ledger.append(
                    lease2,
                    event_id=event(10),
                    title="Different request",
                    body="conflict",
                )
            self.assertEqual(caught.exception.code, "EVENT_ID_CONFLICT")
            self.assertEqual(len(ledger.validate()["records"]), 1)

    def test_malformed_duplicate_keys_noncanonical_and_schema_omission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = RelayLedger(root, "RUN-3", "builder")
            lease = install_lease(
                ledger,
                writer="builder",
                instance="process",
                lease_id="LEASE",
                fence=1,
            )
            result = ledger.append(
                lease, event_id=event(20), title="Valid", body="body"
            )
            malformed = dict(result["entry"])
            malformed.pop("request_hash")
            errors = list(self.schema_validator.iter_errors(malformed))
            self.assertTrue(errors)

            path = root / "builder.000001.ndjson"
            canonical = path.read_text(encoding="utf-8").rstrip("\n")
            duplicate = canonical[:-1] + ',"schema":"omni-relay-ledger-entry-v1"}\n'
            path.write_text(duplicate, encoding="utf-8", newline="\n")
            with self.assertRaises(LedgerError) as caught:
                ledger.validate()
            self.assertEqual(caught.exception.code, "JSON_DUPLICATE_KEY")

            path.write_text(
                json.dumps(result["entry"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaises(LedgerError) as caught:
                ledger.validate()
            self.assertIn(
                caught.exception.code,
                {
                    "CANONICAL_SINGLE_LINE_REQUIRED",
                    "JSON_MALFORMED",
                    "NONCANONICAL_JSON",
                },
            )

    def test_malformed_canonicalization_body_bytes_and_causal_heads_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = RelayLedger(root, "RUN-MALFORMED-430", "builder")
            lease = install_lease(
                ledger,
                writer="builder",
                instance="process",
                lease_id="LEASE",
                fence=1,
            )
            original = ledger.append(
                lease,
                event_id=event(21),
                title="Baseline",
                body="è",
            )["entry"]
            path = root / "builder.000001.ndjson"

            def assert_blocked(mutated: dict, expected: str) -> None:
                path.write_text(
                    canonical_json(mutated) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                with self.assertRaises(LedgerError) as caught:
                    ledger.validate()
                self.assertEqual(caught.exception.code, expected)
                path.write_text(
                    canonical_json(original) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

            for missing in (
                "canonicalization_version",
                "body_bytes",
                "observed_heads",
            ):
                mutated = dict(original)
                mutated.pop(missing)
                with self.subTest(missing=missing):
                    assert_blocked(mutated, "ENTRY_SCHEMA_MALFORMED")
                    self.assertTrue(
                        list(self.schema_validator.iter_errors(mutated))
                    )

            wrong_version = dict(original)
            wrong_version["canonicalization_version"] = "OMNI_CANONICAL_JSON_V2"
            assert_blocked(wrong_version, "CANONICALIZATION_VERSION_INVALID")

            wrong_length = dict(original)
            wrong_length["body_bytes"] = len("è")
            self.assertNotEqual(
                wrong_length["body_bytes"], len("è".encode("utf-8"))
            )
            assert_blocked(wrong_length, "BODY_BYTES_MISMATCH")

            duplicate = dict(original)
            duplicate["observed_heads"] = [
                {"stream_id": "peer", "stream_seq": 1, "entry_hash": "A" * 64},
                {"stream_id": "peer", "stream_seq": 2, "entry_hash": "B" * 64},
            ]
            assert_blocked(duplicate, "OBSERVED_HEAD_STREAM_DUPLICATE")

            unsorted = dict(original)
            unsorted["observed_heads"] = [
                {"stream_id": "zeta", "stream_seq": 1, "entry_hash": "A" * 64},
                {"stream_id": "alpha", "stream_seq": 1, "entry_hash": "B" * 64},
            ]
            assert_blocked(unsorted, "OBSERVED_HEADS_NOT_SORTED")

            malformed = dict(original)
            malformed["observed_heads"] = [
                {"stream_id": "peer", "stream_seq": 1}
            ]
            assert_blocked(malformed, "OBSERVED_HEAD_MALFORMED")

    def test_recovery_torn_tail_exact_authority_then_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = RelayLedger(root, "RUN-4", "builder")
            lease = install_lease(
                ledger,
                writer="builder",
                instance="process",
                lease_id="LEASE",
                fence=1,
            )
            first = ledger.append(
                lease, event_id=event(30), title="Before crash", body="complete"
            )
            self.assertEqual(
                first["entry"]["canonicalization_version"],
                CANONICALIZATION_VERSION,
            )
            self.assertEqual(first["entry"]["body_bytes"], len(b"complete"))
            self.assertEqual(first["entry"]["observed_heads"], [])
            volume = root / "builder.000001.ndjson"
            with volume.open("ab") as handle:
                handle.write(
                    b'{"observed_heads":[{"stream_id":"peer","stream_seq":'
                )
                handle.flush()
                os.fsync(handle.fileno())

            with self.assertRaises(LedgerError) as caught:
                ledger.validate()
            self.assertEqual(caught.exception.code, "TORN_TAIL")
            with self.assertRaises(LedgerError) as caught:
                ledger.append(
                    lease, event_id=event(31), title="Blocked", body="until repair"
                )
            self.assertEqual(caught.exception.code, "TORN_TAIL")

            plan = ledger.inspect_torn_tail()
            authority = {
                "schema": REPAIR_AUTHORITY_SCHEMA,
                "action": "TRUNCATE_UNCOMMITTED_TAIL",
                "run_id": ledger.run_id,
                "stream_id": ledger.stream_id,
                **{
                    key: plan[key]
                    for key in (
                        "volume_id",
                        "expected_file_sha256",
                        "expected_file_bytes",
                        "valid_bytes",
                        "repaired_sha256",
                        "torn_bytes",
                        "torn_sha256",
                        "plan_hash",
                    )
                },
                "authorized_by": "PM",
                "authority_id": "REPAIR-1",
                "authority_source": "HUMAN_EXPLICIT",
                "authorized_at": AUTHORIZED_AT,
                "expires_at": FUTURE,
            }
            wrong = dict(authority)
            wrong["torn_sha256"] = "A" * 64
            with self.assertRaises(LedgerError) as caught:
                ledger.repair_torn_tail(wrong)
            self.assertEqual(caught.exception.code, "REPAIR_AUTHORITY_BINDING_MISMATCH")
            self.assertEqual(volume.stat().st_size, plan["expected_file_bytes"])

            recovery = ledger.repair_torn_tail(authority)
            self.assertEqual(recovery["status"], "RECOVERED")
            self.assertEqual(len(ledger.validate()["records"]), 1)
            self.assertEqual(
                ledger.validate()["records"][0]["entry_hash"],
                first["entry"]["entry_hash"],
            )
            self.assertTrue(list(root.glob("*.repair.REPAIR-1.intent.json")))
            self.assertTrue(list(root.glob("*.repair.REPAIR-1.complete.json")))

            rotation = ledger.seal_and_rotate(lease)
            self.assertEqual(rotation["status"], "ROTATED")
            recovered_causal_head = [
                {
                    "stream_id": "builder",
                    "stream_seq": first["entry"]["stream_seq"],
                    "entry_hash": first["entry"]["entry_hash"],
                }
            ]
            after = ledger.append(
                lease,
                event_id=event(32),
                title="After rotation",
                body="continued",
                observed_heads=recovered_causal_head,
            )
            self.assertEqual(after["entry"]["stream_seq"], 2)
            self.assertEqual(
                after["entry"]["prev_entry_hash"], first["entry"]["entry_hash"]
            )
            self.assertEqual(
                after["entry"]["prev_volume_seal_hash"],
                rotation["seal"]["seal_hash"],
            )
            self.assertEqual(
                after["entry"]["observed_heads"], recovered_causal_head
            )
            self.assertEqual(len(ledger.validate()["records"]), 2)

    def test_external_anchor_pos_monotonic_vector_and_caller_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ledger_root = base / "ledgers"
            anchor_root = base / "external-anchors"
            builder = RelayLedger(ledger_root, "RUN-A", "builder")
            verifier = RelayLedger(
                ledger_root,
                "RUN-A",
                "verifier",
                independent_verifier=True,
            )
            builder_lease = install_lease(
                builder,
                writer="builder",
                instance="builder-process",
                lease_id="LEASE-B",
                fence=1,
            )
            verifier_lease = install_lease(
                verifier,
                writer="verifier",
                instance="verifier-process",
                lease_id="LEASE-V",
                fence=1,
            )
            builder.append(
                builder_lease,
                event_id=event(50),
                title="Build head",
                body="one",
            )
            verifier.append(
                verifier_lease,
                event_id=event(51),
                title="Verifier head",
                body="one",
                hat="VERIFIER",
            )

            first = create_external_anchor(
                anchor_root, "RUN-A-ANCHORS", 1, [verifier, builder]
            )
            self.assertEqual(first["status"], "ANCHOR_CREATED")
            self.assertEqual(first["trust_domain_status"], "UNQUALIFIED")
            self.anchor_validator.validate(first["anchor"])
            self.assertEqual(
                [head["stream_id"] for head in first["anchor"]["heads"]],
                ["builder", "verifier"],
            )
            with self.assertRaises(FileExistsError):
                Path(first["path"]).open("xb")
            unqualified = verify_external_anchor(
                anchor_root, "RUN-A-ANCHORS", [builder, verifier]
            )
            self.assertEqual(unqualified["status"], "ANCHOR_VERIFIED_UNQUALIFIED")
            with self.assertRaises(LedgerError) as caught:
                verify_external_anchor(
                    anchor_root,
                    "RUN-A-ANCHORS",
                    [builder, verifier],
                    require_qualified=True,
                )
            self.assertEqual(caught.exception.code, "ANCHOR_TRUST_DOMAIN_UNQUALIFIED")

            builder.append(
                builder_lease,
                event_id=event(52),
                title="Higher builder head",
                body="two",
            )
            subject = external_anchor_qualification_subject(
                anchor_root, "RUN-A-ANCHORS", [builder, verifier]
            )
            qualification = external_qualification(subject)
            self.qualification_validator.validate(qualification)
            second = create_external_anchor(
                anchor_root,
                "RUN-A-ANCHORS",
                2,
                [builder, verifier],
                qualification=qualification,
            )
            self.anchor_validator.validate(second["anchor"])
            self.assertEqual(second["anchor"]["anchor_seq"], 2)
            self.assertEqual(
                second["anchor"]["previous_anchor_hash"],
                first["anchor"]["anchor_hash"],
            )
            qualified = verify_external_anchor(
                anchor_root,
                "RUN-A-ANCHORS",
                [builder, verifier],
                anchor_seq=2,
                require_qualified=True,
            )
            self.assertEqual(
                qualified["status"],
                "ANCHOR_VERIFIED_CALLER_QUALIFIED_UNVERIFIED",
            )
            with self.assertRaises(LedgerError) as caught:
                create_external_anchor(
                    anchor_root,
                    "RUN-A-ANCHORS",
                    2,
                    [builder, verifier],
                )
            self.assertEqual(
                caught.exception.code, "EXTERNAL_ANCHOR_SEQUENCE_INVALID"
            )

    def test_external_anchor_neg_root_overlap_and_full_local_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ledger_root = base / "ledger"
            anchor_root = base / "anchor"
            ledger = RelayLedger(ledger_root, "RUN-B", "builder")
            lease = install_lease(
                ledger,
                writer="builder",
                instance="process",
                lease_id="LEASE",
                fence=1,
            )
            appended = ledger.append(
                lease,
                event_id=event(60),
                title="Original history",
                body="original body",
            )
            with self.assertRaises(LedgerError) as caught:
                create_external_anchor(
                    ledger_root, "RUN-B-ANCHORS", 1, [ledger]
                )
            self.assertEqual(caught.exception.code, "ANCHOR_ROOT_NOT_DISTINCT")

            create_external_anchor(
                anchor_root, "RUN-B-ANCHORS", 1, [ledger]
            )
            rewritten = dict(appended["entry"])
            rewritten["title"] = "Fully rewritten history"
            intent = {
                key: rewritten[key]
                for key in (
                    "run_id",
                    "stream_id",
                    "event_id",
                    "writer_id",
                    "writer_instance_id",
                    "lease_id",
                    "fence",
                    "topology",
                    "hat",
                    "independent_verifier",
                    "kind",
                    "title",
                    "body",
                    "body_bytes",
                    "canonicalization_version",
                    "observed_heads",
                    "supersedes",
                )
            }
            rewritten["request_hash"] = hash_core(REQUEST_DOMAIN, intent)
            core = dict(rewritten)
            core.pop("entry_hash")
            rewritten["entry_hash"] = hash_core(ENTRY_DOMAIN, core)
            (ledger_root / "builder.000001.ndjson").write_text(
                canonical_json(rewritten) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(
                ledger.validate()["records"][0]["title"],
                "Fully rewritten history",
            )
            with self.assertRaises(LedgerError) as caught:
                verify_external_anchor(
                    anchor_root, "RUN-B-ANCHORS", [ledger]
                )
            self.assertEqual(
                caught.exception.code, "EXTERNAL_ANCHOR_HEAD_DIVERGENCE"
            )

    def test_external_anchor_cli_create_and_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ledger_root = base / "ledger"
            anchor_root = base / "anchor"
            ledger = RelayLedger(ledger_root, "RUN-C", "builder")
            lease = install_lease(
                ledger,
                writer="builder",
                instance="process",
                lease_id="LEASE",
                fence=1,
            )
            ledger.append(
                lease,
                event_id=event(70),
                title="CLI head",
                body="payload",
            )
            spec = base / "ledger-spec.json"
            spec.write_text(
                json.dumps(
                    {
                        "run_id": "RUN-C",
                        "streams": [
                            {
                                "root": str(ledger_root),
                                "stream_id": "builder",
                                "topology": "TEAM",
                                "independent_verifier": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            script = SCRIPTS / "relay_ledger.py"
            create_command = [
                sys.executable,
                "-B",
                str(script),
                "anchor-create",
                str(anchor_root),
                "RUN-C",
                "--ledger-spec",
                str(spec),
                "--anchor-set-id",
                "RUN-C-ANCHORS",
                "--anchor-seq",
                "1",
            ]
            created = subprocess.run(
                create_command, capture_output=True, text=True, check=False
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            self.assertEqual(json.loads(created.stdout)["status"], "ANCHOR_CREATED")
            verified = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(script),
                    "anchor-verify",
                    str(anchor_root),
                    "RUN-C",
                    "--ledger-spec",
                    str(spec),
                    "--anchor-set-id",
                    "RUN-C-ANCHORS",
                    "--anchor-seq",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                verified.returncode, 0, verified.stdout + verified.stderr
            )
            self.assertEqual(
                json.loads(verified.stdout)["status"],
                "ANCHOR_VERIFIED_UNQUALIFIED",
            )

    def test_solo_hats_one_physical_writer_and_no_independence_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(LedgerError) as caught:
                RelayLedger(
                    root,
                    "RUN-5",
                    "solo",
                    topology="SOLO_HATS",
                    independent_verifier=True,
                )
            self.assertEqual(
                caught.exception.code, "SOLO_INDEPENDENCE_FALSE_REQUIRED"
            )

            ledger = RelayLedger(
                root,
                "RUN-5",
                "solo",
                topology="SOLO_HATS",
                independent_verifier=False,
            )
            lease = install_lease(
                ledger,
                writer="solo-agent",
                instance="one-physical-process",
                lease_id="SOLO-LEASE",
                fence=1,
            )
            builder = ledger.append(
                lease,
                event_id=event(40),
                title="Builder hat",
                body="draft",
                hat="BUILDER",
            )
            verifier = ledger.append(
                lease,
                event_id=event(41),
                title="Verifier hat",
                body="self-review",
                hat="VERIFIER",
            )
            self.assertFalse(builder["entry"]["independent_verifier"])
            self.assertFalse(verifier["entry"]["independent_verifier"])
            self.assertEqual(
                {
                    builder["entry"]["writer_instance_id"],
                    verifier["entry"]["writer_instance_id"],
                },
                {"one-physical-process"},
            )
            self.assertEqual(verifier["entry"]["stream_seq"], 2)

            competing = Lease(
                "solo-agent",
                "second-process",
                "SOLO-LEASE-OTHER",
                1,
                FUTURE,
            )
            with self.assertRaises(LedgerError) as caught:
                ledger.activate_lease(
                    competing,
                    lease_authority(
                        ledger, competing, authority_id="AUTH-COMPETING"
                    ),
                )
            self.assertEqual(caught.exception.code, "LEASE_FENCE_COLLISION")


if __name__ == "__main__":
    unittest.main()

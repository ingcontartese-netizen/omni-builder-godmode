from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
SENTRY = ROOT / "scripts" / "sentry"
sys.path.insert(0, str(SENTRY))

from rotate import ORDER, validate_chain
from supervisor import handover
from wakeup import gaps, scan


def chain(terminal: str = "SUBSTANTIVE_WORK_RELEASED") -> list[dict]:
    states = ORDER if terminal == "SUBSTANTIVE_WORK_RELEASED" else [*ORDER[:5], "ROTATION_ABORTED"]
    base = datetime(2026, 7, 30, tzinfo=timezone.utc)
    revoked_at = released_at = granted_at = None
    records: list[dict] = []
    for index, state in enumerate(states):
        created_at = (base + timedelta(seconds=index)).isoformat()
        if state == "PREDECESSOR_AUTHORITY_REVOKED":
            revoked_at = created_at
        elif state == "PREDECESSOR_QUIESCENT":
            released_at = created_at
        elif state == "LEASE_GRANTED":
            granted_at = created_at
        position = ORDER.index(state) if state in ORDER else None
        if state == "ROTATION_ABORTED":
            lease = records[-1]["lease_owner"]
            sentinels = records[-1]["sentinels"]
        else:
            lease = "PREDECESSOR" if position < ORDER.index("PREDECESSOR_AUTHORITY_REVOKED") else (
                "NONE" if position < ORDER.index("LEASE_GRANTED") else "SUCCESSOR"
            )
            active = position >= ORDER.index("RESUME_PASS")
            sentinels = {"agentic": active, "script": active, "context": active}
        records.append({
            "schema": "omni-rotation-state-v2", "request_id": "Q1", "rotation_id": "R1",
            "generation": 1, "nonce": "N1", "state": state, "project_root": "C:/project",
            "predecessor_session_id": "P", "successor_session_id": None if index < 2 else "S",
            "lease_owner": lease, "profile_sha256": "A" * 64, "manifest_sha256": "B" * 64,
            "payload_sha256": "C" * 64, "channel_baseline": 10, "max_spawn": 1,
            "recurrence": False, "scope": "F3_F4_ONLY", "authority_source": "PM_DIRECT",
            "operator_kind": "EXTERNALLY_AUTHORIZED_PER_ACTION", "operator_authorized": True,
            "sentinels": sentinels, "authority_inherited": False, "external_effects_allowed": False,
            "revoked_at": revoked_at, "released_at": released_at, "granted_at": granted_at,
            "created_at": created_at,
        })
    return records


def evidence(records: list[dict]) -> dict[str, str]:
    return {field: records[0][field] for field in ("profile_sha256", "manifest_sha256", "payload_sha256")}


def validate(records: list[dict], contract: Path | None = None) -> list[str]:
    return validate_chain(records, contract or (ROOT / "schemas" / "rotation_state.schema.json"), evidence(records))


class RotationTests(unittest.TestCase):
    def test_complete_chain(self):
        records = chain()
        self.assertEqual(validate(records), [])
        self.assertEqual(set(records[-1]["sentinels"]), {"agentic", "script", "context"})

    def test_legal_abort_is_terminal_and_not_retried(self):
        records = chain("ROTATION_ABORTED")
        self.assertEqual(validate(records), [])
        records.append(dict(records[-1], created_at="2026-07-30T00:00:20+00:00"))
        self.assertIn("TRANSITION_AFTER_TERMINAL", validate(records))

    def test_every_nonterminal_prefix_fails(self):
        records = chain()
        for size in range(1, len(records)):
            with self.subTest(size=size):
                self.assertIn("CHAIN_NOT_TERMINAL", validate(records[:size]))

    def test_first_record_is_validated(self):
        for field, value, marker in (
            ("authority_inherited", True, "AUTHORITY_INHERITANCE_FORBIDDEN"),
            ("external_effects_allowed", True, "EXTERNAL_EFFECTS_FORBIDDEN"),
            ("predecessor_session_id", "", "PREDECESSOR_SESSION_ID_INVALID"),
        ):
            records = chain()
            records[0][field] = value
            self.assertTrue(any(marker in error for error in validate(records)))

    def test_payload_profile_manifest_and_identity_cannot_drift(self):
        for field in ("payload_sha256", "profile_sha256", "manifest_sha256", "request_id", "nonce"):
            records = chain()
            records[6][field] = "D" * 64 if field.endswith("sha256") else "DRIFT"
            with self.subTest(field=field):
                self.assertTrue(any(field.upper() in error for error in validate(records)))

    def test_lease_and_milestone_order_are_enforced(self):
        records = chain()
        records[9]["lease_owner"] = "SUCCESSOR"
        self.assertTrue(any("LEASE" in error for error in validate(records)))
        records = chain()
        records[11]["revoked_at"], records[11]["granted_at"] = records[11]["granted_at"], records[11]["revoked_at"]
        self.assertIn("REVOKED_AT_DRIFT", validate(records))

    def test_missing_or_corrupt_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schema.json"
            path.write_text("{}", encoding="utf-8")
            records = chain()
            self.assertIn("SCHEMA_CONTRACT_NOT_CLOSED", validate(records, path))

    def test_malformed_cli_is_typed_json_rc2(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chain.json"
            path.write_text('[{"state":', encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-B", str(SENTRY / "rotate.py"), str(path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(json.loads(completed.stdout)["status"], "BLOCKED")

    def test_cli_binds_actual_profile_manifest_and_payload_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = {}
            for name, content in (("profile", b"profile"), ("manifest", b"manifest"), ("payload", b"payload")):
                path = root / f"{name}.bin"
                path.write_bytes(content)
                artifacts[name] = path
            records = chain()
            digests = {f"{name}_sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper() for name, path in artifacts.items()}
            for record in records:
                record.update(digests)
            chain_path = root / "chain.json"
            chain_path.write_text(json.dumps(records), encoding="utf-8")
            command = [sys.executable, "-B", str(SENTRY / "rotate.py"), str(chain_path), "--profile", str(artifacts["profile"]), "--manifest", str(artifacts["manifest"]), "--payload", str(artifacts["payload"])]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            artifacts["payload"].write_bytes(b"drift")
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 1)
            self.assertIn("PAYLOAD_SHA256_ARTIFACT_MISMATCH", json.loads(completed.stdout)["errors"])

    def test_channel_wakes_on_max_and_records_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex_to_claude_2_A.md").write_text("A")
            (root / "claude_to_codex_5_B.md").write_text("B")
            records = scan(root)
            self.assertEqual([record.number for record in records], [2, 5])
            self.assertEqual(gaps(records), [3, 4])

    def test_handover_matches_template_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "handover.json"
            result = handover(output, "old", "new", 2, "rotation", "A" * 64)
            self.assertTrue(output.exists())
            template = json.loads((ROOT / "templates" / "ownership_handover.json").read_text(encoding="utf-8"))
            self.assertEqual(set(result), set(template))
            self.assertEqual(result["new_owner"], "new")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class IncidentRegressionTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((ROOT / "fixtures").glob("*.json"))]

    def test_exact_fixture_denominator(self):
        self.assertEqual(len(self.fixtures), 10)
        identifiers = [fixture["id"] for fixture in self.fixtures]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_under_load_positive_control_is_enumerated(self):
        fixture = next(item for item in self.fixtures if item["id"] == "PB-018-FLAKY-FIXED-TIMEOUT")
        control = fixture["input"]["under_load_positive_control"]
        self.assertEqual(control, {"id": "IDP_N05", "passes": 10, "trials": 10})
        self.assertEqual(control["passes"], control["trials"])

    def test_every_fixture_names_control_and_oracle(self):
        for fixture in self.fixtures:
            self.assertEqual(fixture["schema"], "omni-incident-fixture-v1")
            self.assertTrue(fixture["control"])
            self.assertTrue(fixture["input"])
            self.assertTrue(fixture["expected"])

    def test_quantitative_claim_is_enumerated(self):
        fixture = next(item for item in self.fixtures if item["id"] == "PB-CANDIDATE-UNINCISED-LESSON")
        self.assertNotEqual(fixture["input"]["claimed_count"], len(fixture["input"]["enumerated_ids"]))

    def test_profile_parity_is_present_in_host_generation(self):
        text = (ROOT / "adapters" / "host_generation.yaml").read_text(encoding="utf-8")
        for field in ("surface_id", "runtime_version_tuple", "model", "reasoning_effort", "effort_ui_label", "effort_runtime_key", "effort_mapping_evidence", "permission_surface", "agentic_sentinel_id", "script_sentinel_generation", "context_sentinel"):
            self.assertIn(field, text)

    def test_profile_policy_pins_implicit_effort_mapping_forbidden(self):
        text = (ROOT / "adapters" / "host_generation.yaml").read_text(encoding="utf-8")
        self.assertIn("profile_policy:", text)
        self.assertIn("implicit_effort_label_mapping_forbidden: true", text)

    def test_runtime_surfaces_and_effort_labels_are_not_silently_conflated(self):
        host = (ROOT / "references" / "08_host.md").read_text(encoding="utf-8")
        handoff = (ROOT / "templates" / "handoff.md").read_text(encoding="utf-8")
        claude = (ROOT / "adapters" / "claude-code" / "adapter.yaml").read_text(encoding="utf-8")
        codex = (ROOT / "adapters" / "codex" / "adapter.yaml").read_text(encoding="utf-8")
        self.assertIn("UNRESOLVED_MAPPING", host)
        self.assertIn("Effort UI label:", handoff)
        self.assertIn("Effort runtime key:", handoff)
        self.assertIn("embedded Claude Code 2.1.219", claude)
        self.assertIn("PATH Claude CLI 2.1.150", claude)
        self.assertIn("runtime_version_tuple", claude)
        self.assertIn("effort_mapping_evidence", codex)
        self.assertIn("effort_ui_label=Ultra", codex)
        self.assertIn("effort_runtime_key=xhigh", codex)
        self.assertIn("effort_mapping_evidence=UNRESOLVED_MAPPING", codex)

    def test_schema_top_level_keys_are_closed(self):
        for path in sorted((ROOT / "schemas").glob("*.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertIs(schema.get("additionalProperties"), False, path.name)

    def test_unicode_fixture_preserves_the_nonbreaking_hyphen(self):
        fixture = next(item for item in self.fixtures if item["id"] == "PB-024-UNICODE-QUERY-TRAP")
        self.assertIn("‑", fixture["input"]["text"])
        self.assertNotEqual(fixture["input"]["text"], fixture["input"]["query"])
        workaround = fixture["input"]["workaround"]
        self.assertEqual(sum(bool(re.fullmatch(workaround["pattern"], example)) for example in workaround["examples"]), workaround["expected_matches"])


if __name__ == "__main__":
    unittest.main()

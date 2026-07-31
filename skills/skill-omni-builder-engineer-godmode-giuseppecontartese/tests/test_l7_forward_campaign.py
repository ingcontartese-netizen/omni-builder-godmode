from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SENTRY = ROOT / "scripts" / "sentry"
sys.path.insert(0, str(SENTRY))


def load_mode_guard():
    path = ROOT / "scripts" / "sentry" / "mode_a_guard.py"
    spec = importlib.util.spec_from_file_location("obe_l7_mode_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODE_GUARD_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODE = load_mode_guard()


class L7ForwardPreActivationCampaign(unittest.TestCase):
    """Fresh, user-shaped probes that do not depend on frozen answer fixtures."""

    def test_one_off_stays_outside_omni_and_has_no_effect_surface(self):
        decision = MODE.decide_invocation(
            explicit_user_request=False,
            complexity_warrants_omni=False,
            consent_state="ABSENT",
        )
        self.assertEqual(decision["status"], "NO_SKILL_REQUIRED")
        self.assertFalse(decision["activation_allowed"])
        self.assertFalse(decision["skill_invoked"])
        self.assertFalse(decision["effect_authorized"])
        self.assertEqual(decision["effect_grants"], [])

    def test_motivated_proposal_silence_and_ambiguity_do_not_activate(self):
        for consent in ("ABSENT", "AMBIGUOUS"):
            with self.subTest(consent=consent):
                decision = MODE.decide_invocation(
                    explicit_user_request=False,
                    complexity_warrants_omni=True,
                    consent_state=consent,
                    grounds=("DURABLE_KNOWLEDGE", "MULTI_PHASE_WORK"),
                    activation_level="OMNI_FULL",
                )
                self.assertEqual(
                    decision["status"], "PROPOSAL_EMITTED_AWAITING_CONSENT"
                )
                self.assertEqual(decision["next_gate"], "EXPLICIT_CONSENT")
                self.assertFalse(decision["activation_allowed"])
                self.assertFalse(decision["effect_authorized"])

    def test_motivated_proposal_rejection_falls_back_without_effects(self):
        decision = MODE.decide_invocation(
            explicit_user_request=False,
            complexity_warrants_omni=True,
            consent_state="DECLINED",
            grounds=("DURABLE_KNOWLEDGE",),
            activation_level="OMNI_FULL",
        )
        self.assertEqual(decision["status"], "DECLINED_USE_ORDINARY_TOOLS")
        self.assertEqual(decision["next_gate"], "ORDINARY_TOOLS_OR_STOP")
        self.assertFalse(decision["activation_allowed"])
        self.assertFalse(decision["effect_authorized"])

    def test_lite_explicit_godmode_opens_intake_but_not_files_network_or_automation(self):
        decision = MODE.decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            consent_state="ABSENT",
            run_kind="REAL",
            activation_level="OMNI_FULL",
        )
        self.assertEqual(decision["status"], "ACTIVATION_ALLOWED")
        self.assertEqual(decision["mode_gate"], "MODE_BEFORE_PROGRAM")
        self.assertEqual(decision["next_gate"], "GUIDED_INTAKE")
        self.assertTrue(decision["intake_allowed"])
        self.assertEqual(decision["artifact_grants"], [])
        self.assertEqual(decision["requested_effects"], [])
        self.assertFalse(decision["effect_authorized"])
        self.assertEqual(decision["access_envelope_identity"], "PENDING")

    def test_named_module_is_one_receipt_one_module_and_never_enters_q0(self):
        dossier = "KNOWLEDGE_RESEARCH_DOSSIER"
        decision = MODE.decide_invocation(
            explicit_user_request=True,
            complexity_warrants_omni=False,
            consent_state="ABSENT",
            run_kind="REAL",
            activation_level="OMNI_MODULE",
            modules=(dossier,),
        )
        self.assertEqual(decision["status"], "MODULE_ACTIVATION_ALLOWED")
        self.assertEqual(
            decision["modules_used"],
            [dossier],
        )
        self.assertEqual(decision["mode_gate"], "MODULE_SCOPE_ONLY")
        self.assertFalse(decision["intake_allowed"])
        self.assertFalse(decision["effect_authorized"])
        with self.assertRaisesRegex(ValueError, "OMNI_MODULE_REQUIRES_ONE_REAL_MODULE"):
            MODE.decide_invocation(
                explicit_user_request=True,
                complexity_warrants_omni=False,
                consent_state="ABSENT",
                run_kind="REAL",
                activation_level="OMNI_MODULE",
                modules=(dossier, "scripts/sentry"),
            )

    def test_dry_run_and_host_loading_cannot_materialize_or_auto_activate(self):
        with tempfile.TemporaryDirectory(prefix="obe_l7_dry_") as tmp:
            before = tuple(Path(tmp).iterdir())
            decision = MODE.decide_invocation(
                explicit_user_request=True,
                complexity_warrants_omni=True,
                consent_state="ABSENT",
                grounds=("DURABLE_KNOWLEDGE",),
                run_kind="DRY_RUN",
                activation_level="OMNI_FULL",
            )
            after = tuple(Path(tmp).iterdir())
        self.assertEqual(decision["status"], "ACTIVATION_ALLOWED")
        self.assertEqual(decision["run_kind"], "DRY_RUN")
        self.assertEqual(before, after)
        metadata = yaml.safe_load((ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(metadata["policy"]["allow_implicit_invocation"], True)
        self.assertIn(
            "$skill-omni-builder-engineer-godmode-giuseppecontartese",
            metadata["interface"]["default_prompt"],
        )
        self.assertFalse(decision["effect_authorized"])


if __name__ == "__main__":
    unittest.main()

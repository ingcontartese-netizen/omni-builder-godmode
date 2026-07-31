from __future__ import annotations

import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class StructureTests(unittest.TestCase):
    def test_head_limits(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        counter = load("count_tokens", ROOT / "scripts" / "count_tokens.py")
        tokens, _ = counter.measure(text)
        self.assertLess(len(text.splitlines()), 500)
        self.assertLess(tokens, 5000)

    def test_references_are_valid_and_flat(self):
        checker = load("check_references", ROOT / "scripts" / "check_references.py")
        self.assertEqual(checker.validate(ROOT), [])

    def test_single_glossary(self):
        glossaries = [p for p in ROOT.rglob("*") if p.is_file() and "glossar" in p.name.lower()]
        self.assertEqual([p.relative_to(ROOT).as_posix() for p in glossaries], ["references/09_glossario.md"])

    def test_invocation_doctrine_pins_both_gates_and_pm_cases(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        triage = (ROOT / "references" / "00_triage.md").read_text(encoding="utf-8")
        description = skill.splitlines()[2]
        for marker in (
            "explicit Omni/GodMode/module request",
            "motivated proposal",
            "Loading is not activation",
            "Complexity controls recommendations, not eligibility",
        ):
            self.assertIn(marker, description)
        self.assertLess(skill.index("## Invocation manifesto - station zero"), skill.index("## Permanent maxims"))
        self.assertLess(triage.index("## Station 0 - invocation legitimacy"), triage.index("## Required full-orchestration intake"))
        for marker in (
            "EXPLICIT_USER_OPT_IN", "PROPOSAL_ACCEPTED", "ACTIVATION_ALLOWED",
            "CONSENT_ABSENT", "CONSENT_NEGATIVE", "BLOCKED_BEFORE_MODE_SELECTION",
            "PROPOSAL_EMITTED_AWAITING_CONSENT", "ONE_OFF_PDF_REPORT",
            "ONE_OFF_BICYCLE_MANUAL", "COMPLEX_COOKBOOK", "METHOD_USE",
            "RUN_KIND_REQUIRED", "RUN_KIND_INVALID", "MODE_BEFORE_PROGRAM",
            "DURABLE_KNOWLEDGE", "MULTI_PHASE_WORK", "GOVERNED_VERIFICATION",
            "MULTIPLE_ACTORS", "REAL", "DRY_RUN", "PARTNER_SELECTION",
            "WEB_ACCESS", "DOWNLOAD", "PROJECT_WRITE", "EXECUTION", "AUTONOMY",
        ):
            self.assertIn(marker, skill + triage)
        self.assertIn('"write this report as a PDF" -> `NO_SKILL_REQUIRED`', triage)
        self.assertIn('"build a PDF with bicycle-maintenance instructions" -> `NO_SKILL_REQUIRED`', triage)
        self.assertIn('"write a cookbook book"', triage)
        self.assertLess(skill.index("guided intake before selecting"), skill.index("## Select the smallest architecture"))

    def test_host_metadata_allows_loading_but_not_activation(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: true", metadata)
        for marker in (
            "$skill-omni-builder-engineer-godmode-giuseppecontartese",
            "explicit natural-language",
            "Loading grants nothing",
            "Complexity controls recommendations, not eligibility",
        ):
            self.assertIn(marker, metadata)

    def test_package_validator_rejects_invocation_doctrine_mutants(self):
        validator = load("validate_skill_invocation_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            ("SKILL.md", "Loading is not activation", "Loading activates", "FRONTMATTER_LOADING_DOCTRINE_MISSING:Loading is not activation"),
            ("SKILL.md", "Complexity controls recommendations, not eligibility", "Complexity controls eligibility", "FRONTMATTER_LOADING_DOCTRINE_MISSING:Complexity controls recommendations, not eligibility"),
            ("SKILL.md", "## Invocation manifesto - station zero", "## Invocation guidance", "INVOCATION_STATION_ZERO_MISSING:SKILL.md"),
            ("references/00_triage.md", "## Station 0 - invocation legitimacy", "## Invocation guidance", "INVOCATION_STATION_ZERO_MISSING:references/00_triage.md"),
            ("references/00_triage.md", "ONE_OFF_BICYCLE_MANUAL", "BICYCLE_CASE_REMOVED", "INVOCATION_ONE_OFF_CASE_MISSING"),
            ("references/00_triage.md", "COMPLEX_COOKBOOK", "COOKBOOK_CASE_REMOVED", "INVOCATION_CONSENT_CASE_MISSING"),
            ("references/00_triage.md", "LITE_EXPLICIT_GODMODE", "LITE_CASE_REMOVED", "INVOCATION_COMPLEXITY_ELIGIBILITY_DRIFT"),
            ("references/00_triage.md", "PROPOSAL_EMITTED_AWAITING_CONSENT", "PROPOSAL_STATE_REMOVED", "INVOCATION_STATE_CONTRACT_MISSING:references/00_triage.md:PROPOSAL_EMITTED_AWAITING_CONSENT"),
        )
        for relative, old, new, expected in cases:
            with self.subTest(relative=relative, marker=old), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_package_validator_rejects_frontmatter_and_missing_skill(self):
        validator = load("validate_skill", ROOT / "scripts" / "validate_skill.py")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "package"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            skill = copy / "SKILL.md"
            original = skill.read_text(encoding="utf-8")
            skill.write_text(original.replace("---\n", "", 1), encoding="utf-8")
            result = validator.validate(copy, run_tests=False)
            self.assertIn("FRONTMATTER_OPEN_MISSING", result["errors"])
            skill.unlink()
            result = validator.validate(copy, run_tests=False)
            self.assertIn("SKILL_UNREADABLE", result["errors"])
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "package"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            skill = copy / "SKILL.md"
            lines = skill.read_text(encoding="utf-8").splitlines()
            lines[2] = "description: Never auto-invoke: explicit consent."
            skill.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = validator.validate(copy, run_tests=False)
            self.assertTrue(
                any(error.startswith("FRONTMATTER_YAML_INVALID:") for error in result["errors"]),
                result,
            )

    def test_package_validator_rejects_semantic_schema_mutant(self):
        validator = load("validate_skill_mutant", ROOT / "scripts" / "validate_skill.py")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "package"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            path = copy / "schemas" / "rotation_state.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["properties"]["state"]["enum"].remove("PEER_COUNTERSIGN")
            path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(copy, run_tests=False)
            self.assertIn("ROTATION_SCHEMA_STATE_MACHINE_DRIFT", result["errors"])

    def test_guided_intake_schema_is_expected_and_structurally_pinned(self):
        validator = load("validate_skill_guided_intake_contract", ROOT / "scripts" / "validate_skill.py")
        result = validator.validate(ROOT, run_tests=False)
        self.assertNotIn("MISSING:schemas/guided_intake_state.schema.json", result["errors"])
        self.assertFalse(any(error.startswith("GUIDED_INTAKE_SCHEMA_") for error in result["errors"]), result)

    def test_package_validator_rejects_guided_intake_schema_mutant_family(self):
        validator = load("validate_skill_guided_intake_mutants", ROOT / "scripts" / "validate_skill.py")
        mutants = {
            "envelope_reopened": (
                lambda schema: schema.__setitem__("additionalProperties", True),
                "GUIDED_INTAKE_SCHEMA_ENVELOPE_DRIFT",
            ),
            "required_erased": (
                lambda schema: schema["required"].remove("question_matrix"),
                "GUIDED_INTAKE_SCHEMA_REQUIRED_DRIFT",
            ),
            "phase_erased": (
                lambda schema: schema["properties"]["phase"]["enum"].remove("INTAKE_READY"),
                "GUIDED_INTAKE_SCHEMA_PHASE_DRIFT",
            ),
            "activation_grant_expanded": (
                lambda schema: schema["$defs"]["activation_binding"]["properties"]["activation_grants"].__setitem__("const", ["METHOD_USE", "EXECUTION"]),
                "GUIDED_INTAKE_SCHEMA_ACTIVATION_BINDING_DRIFT",
            ),
            "activation_path_reopened": (
                lambda schema: schema["$defs"]["activation_binding"]["properties"]["activation_path"].__setitem__("enum", ["NARRATED"]),
                "GUIDED_INTAKE_SCHEMA_ACTIVATION_PATH_DRIFT",
            ),
            "task_scope_expanded": (
                lambda schema: schema["$defs"]["activation_binding"]["properties"]["task_scope"].__setitem__("const", "ANY_TASK"),
                "GUIDED_INTAKE_SCHEMA_TASK_SCOPE_DRIFT",
            ),
            "activation_non_grant_removed": (
                lambda schema: schema["$defs"]["activation_binding"]["properties"]["activation_non_grants"]["const"].remove("AUTONOMY"),
                "GUIDED_INTAKE_SCHEMA_ACTIVATION_NON_GRANTS_DRIFT",
            ),
            "relay_mislabeled": (
                lambda schema: schema["$defs"]["relay"]["properties"]["governed_channel_equivalent"].__setitem__("const", True),
                "GUIDED_INTAKE_SCHEMA_RELAY_DRIFT",
            ),
            "closure_narrated": (
                lambda schema: schema["$defs"]["critical_closure"]["properties"]["derivation"].__setitem__("const", "NARRATED"),
                "GUIDED_INTAKE_SCHEMA_CRITICAL_CLOSURE_DRIFT",
            ),
        }
        for name, (mutate, expected) in mutants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "schemas" / "guided_intake_state.schema.json"
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_package_validator_rejects_every_l2_doctrine_law_mutant(self):
        validator = load("validate_skill_l2_doctrine_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            ("SKILL.md", "two distinct native sessions", "two sessions", "L2_DOCTRINE_MARKER_MISSING:SKILL.md:two distinct native sessions"),
            ("SKILL.md", "acks.builder", "builder acknowledgement", "L2_DOCTRINE_MARKER_MISSING:SKILL.md:acks.builder"),
            ("SKILL.md", "builder.question", "builder saw question", "L2_DOCTRINE_MARKER_MISSING:SKILL.md:builder.question"),
            ("SKILL.md", "`KNOWN` without physical `source_refs` does not close a critical station", "KNOWN closes a critical station", "L2_DOCTRINE_MARKER_MISSING:SKILL.md:`known` without physical `source_refs` does not close a critical station"),
            ("SKILL.md", "intake proposal has matching dual readback", "intake proposal exists", "L2_DOCTRINE_MARKER_MISSING:SKILL.md:intake proposal has matching dual readback"),
            ("SKILL.md", "USER_MATERIAL_INGESTION", "MATERIAL", "L2_PRE_DUAL_ACK_EFFECT_MISSING:SKILL.md:USER_MATERIAL_INGESTION"),
            ("SKILL.md", "never create two project wells", "two wells allowed", "L2_DOCTRINE_MARKER_MISSING:SKILL.md:never create two project wells"),
            ("SKILL.md", "never co-write a lane file", "co-write allowed", "L2_DOCTRINE_MARKER_MISSING:SKILL.md:never co-write a lane file"),
            ("references/00_triage.md", "task_scope=CURRENT_TASK_ONLY", "task scope is broad", "L2_ACTIVATION_VOCABULARY_MISSING:references/00_triage.md:task_scope=current_task_only"),
            ("references/00_triage.md", "matching readback from both sessions", "one readback", "L2_DOCTRINE_MARKER_MISSING:references/00_triage.md:matching readback from both sessions"),
            ("references/00_triage.md", "cannot emit `TEAM_CARD_DUAL_ACK` or close L2", "may emit `TEAM_CARD_DUAL_ACK` and close L2", "L2_DOCTRINE_MARKER_MISSING:references/00_triage.md:cannot emit `team_card_dual_ack` or close l2"),
            ("references/01_cappelli.md", "one project well folder", "two project well folders", "L2_DOCTRINE_MARKER_MISSING:references/01_cappelli.md:one project well folder"),
            ("references/02_pozzo.md", "well.state=WELL_WRITE_SCOPE_PENDING", "well is active", "L2_DOCTRINE_MARKER_MISSING:references/02_pozzo.md:well.state=well_write_scope_pending"),
            ("references/02_pozzo.md", "separate lane-owned files", "shared files", "L2_DOCTRINE_MARKER_MISSING:references/02_pozzo.md:separate lane-owned files"),
            ("references/02_pozzo.md", "later governed fusion gate", "immediate fusion", "L2_DOCTRINE_MARKER_MISSING:references/02_pozzo.md:later governed fusion gate"),
        )
        for relative, old, new, expected in cases:
            with self.subTest(relative=relative, marker=old), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_package_validator_rejects_each_pm_relay_negation_mutant(self):
        validator = load("validate_skill_pm_relay_mutants", ROOT / "scripts" / "validate_skill.py")
        negations = (
            "not a governed channel", "not authority", "not consent", "not a lease",
            "not a write grant", "not an independent counter-signature",
        )
        for negation in negations:
            with self.subTest(negation=negation), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "references" / "01_cappelli.md"
                original = path.read_text(encoding="utf-8")
                self.assertIn(negation, original)
                path.write_text(original.replace(negation, "REMOVED_NEGATION"), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(f"L2_PM_RELAY_NEGATION_MISSING:references/01_cappelli.md:{negation}", result["errors"], result)

    def test_package_validator_pins_all_l2_glossary_terms(self):
        validator = load("validate_skill_l2_glossary_mutants", ROOT / "scripts" / "validate_skill.py")
        glossary_terms = tuple(validator.GUIDED_GLOSSARY_TERMS)
        self.assertGreaterEqual(len(glossary_terms), 19)
        for term in glossary_terms:
            with self.subTest(term=term), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "references" / "09_glossario.md"
                original = path.read_text(encoding="utf-8")
                marker = f"**{term}:**"
                self.assertIn(marker, original.lower())
                mutated = re.sub(re.escape(marker), f"**REMOVED {term}:**", original, flags=re.IGNORECASE)
                path.write_text(mutated, encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(f"L2_GLOSSARY_TERM_MISSING:{term}", result["errors"], result)

    def test_glossary_program_v2_and_baptism_contract_is_pinned(self):
        validator = load("validate_skill_glossary_program_contract", ROOT / "scripts" / "validate_skill.py")
        markers = (
            "omni-fused-program-v2",
            "program_fusion_frozen",
            "omni-program-countersign-receipt-v2",
            "program_countersign_accepted",
            "omni-program-baptism-decision-v1",
            "omni-program-baptism-receipt-v1",
            "program_baptized",
            "v1 artifacts fail closed",
        )
        for marker in markers:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "references" / "09_glossario.md"
                original = path.read_text(encoding="utf-8")
                self.assertIn(marker, original.lower())
                path.write_text(
                    re.sub(re.escape(marker), "REMOVED_PROGRAM_CONTRACT", original, flags=re.IGNORECASE),
                    encoding="utf-8",
                )
                result = validator.validate(copy, run_tests=False)
                self.assertIn(
                    f"L2_PHYSICAL_BINDING_DOCTRINE_MISSING:references/09_glossario.md:{marker}",
                    result["errors"],
                    result,
                )

    def test_package_validator_rejects_successful_zero_test_run(self):
        validator = load("validate_skill_zero_test_guard", ROOT / "scripts" / "validate_skill.py")
        fake = SimpleNamespace(returncode=0, stdout="", stderr="Ran 0 tests in 0.000s\n\nOK\n")
        with mock.patch.object(validator.subprocess, "run", return_value=fake):
            result = validator.validate(ROOT, run_tests=True)
        self.assertIn("TEST_COUNT_BELOW_MINIMUM:0:226", result["errors"], result)
        self.assertEqual(result["tests_run"], 0)

    def test_package_validator_rejects_guided_intake_template_mutants(self):
        validator = load("validate_skill_guided_intake_template_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            ("templates/handoff.md", "- Open critical question IDs (must be recomputed, never narrated):\n", "", "GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:handoff.md:open critical question"),
            ("templates/mandato_costruttore.md", "four-readback", "readback", "GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:mandato_costruttore.md:four-readback"),
            ("templates/stele_zero.md", "- Fused program schema `omni-fused-program-v2` / canonical `binding` + standalone schema-valid `artifact` / `PROGRAM_FUSION_FROZEN` candidate / ID / author, topology, profile, run-kind, lane origins, complete work-item contract, knowledge, and session-pair fields:\n", "", "GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:stele_zero.md:fused program schema"),
            ("templates/contratto_fase.yaml", "guided_intake_state:\n", "intake_state_removed:\n", "GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:contratto_fase.yaml:guided_intake_state:"),
            ("templates/contratto_fase.yaml", "  decision: ACTIVATION_ALLOWED\n", "", "GUIDED_INTAKE_TEMPLATE_BINDING_MISSING:contratto_fase.yaml:decision: activation_allowed"),
            ("templates/handoff.md", "- Builder mandate path / bytes / SHA-256:\n", "", "GUIDED_INTAKE_TEMPLATE_BINDING_MISSING:handoff.md:builder mandate path / bytes / sha-256"),
            ("templates/mandato_costruttore.md", "the relay-ledger digest", "a relay ledger", "GUIDED_INTAKE_TEMPLATE_BINDING_MISSING:mandato_costruttore.md:relay-ledger digest"),
            ("templates/mandato_demolitore.md", "Open the program, countersign, baptism decision, and baptism receipt at their exact paths", "Trust the program narration", "GUIDED_INTAKE_TEMPLATE_BINDING_MISSING:mandato_demolitore.md:open the program, countersign, baptism decision, and baptism receipt at their exact paths"),
            ("templates/stele_zero.md", "- PM topology-selection relay / payload path / bytes / SHA-256 / authorization:\n", "", "GUIDED_INTAKE_TEMPLATE_BINDING_MISSING:stele_zero.md:pm topology-selection relay / payload path / bytes / sha-256 / authorization"),
        )
        for relative, old, new, expected in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_guided_intake_physical_binding_mutants_fail_closed(self):
        validator = load("validate_skill_physical_binding_mutants", ROOT / "scripts" / "validate_skill.py")
        mutants = {
            "evidence_ref_demoted_to_string": (
                lambda schema: schema["$defs"]["station"]["properties"]["source_refs"].__setitem__("items", {"type": "string"}),
                "GUIDED_INTAKE_SCHEMA_EVIDENCE_BINDING_DRIFT",
            ),
            "mandate_bytes_not_required": (
                lambda schema: schema["$defs"]["participant"]["required"].remove("mandate_bytes"),
                "GUIDED_INTAKE_SCHEMA_MANDATE_BINDING_DRIFT",
            ),
            "relay_payload_hash_not_required": (
                lambda schema: schema["$defs"]["relay_record"]["required"].remove("payload_sha256"),
                "GUIDED_INTAKE_SCHEMA_RELAY_PHYSICAL_BINDING_DRIFT",
            ),
            "pm_lane_removed": (
                lambda schema: schema["$defs"]["relay"]["properties"].pop("pm_write_lane"),
                "GUIDED_INTAKE_SCHEMA_RELAY_DRIFT",
            ),
            "access_before_material_removed": (
                lambda schema: schema["$defs"]["station_id"]["enum"].remove("ACCESS_GRANT"),
                "GUIDED_INTAKE_SCHEMA_EVIDENCE_BINDING_DRIFT",
            ),
            "artifact_grants_removed_from_trace": (
                lambda schema: schema["$defs"]["activation_binding"]["properties"].pop("artifact_grants"),
                "GUIDED_INTAKE_SCHEMA_PROGRESSIVE_ACTIVATION_DRIFT",
            ),
            "full_activation_silently_downgraded": (
                lambda schema: schema["$defs"]["activation_binding"]["properties"]["activation_level"].__setitem__("const", "OMNI_MODULE"),
                "GUIDED_INTAKE_SCHEMA_PROGRESSIVE_ACTIVATION_DRIFT",
            ),
            "workspace_probe_binding_demoted_to_narration": (
                lambda schema: schema["$defs"]["workspace_access_envelope_contract"]["properties"].__setitem__("probe_receipt_binding", {"type": "string"}),
                "GUIDED_INTAKE_SCHEMA_WORKSPACE_ACCESS_DRIFT",
            ),
            "workspace_partial_escalated_to_full_grants": (
                lambda schema: schema["$defs"]["workspace_access_envelope_contract"]["allOf"][4]["then"]["properties"]["granted_capabilities"].__setitem__("maxItems", 4),
                "GUIDED_INTAKE_SCHEMA_WORKSPACE_ACCESS_DRIFT",
            ),
        }
        for name, (mutate, expected) in mutants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "schemas" / "guided_intake_state.schema.json"
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_closed_l2_schemas_reject_arbitrary_files_and_accept_bound_objects(self):
        validator = load("validate_skill_closed_l2_instances", ROOT / "scripts" / "validate_skill.py")
        self.assertIsNotNone(validator.jsonschema)
        sha = "A" * 64
        phase = validator._load_yaml(ROOT / "templates" / "contratto_fase.yaml", [])
        program = phase["program"]["artifact"]
        receipt = phase["program_countersign_receipt"]["artifact"]
        probe = {
            "schema": "omni-workspace-access-probe-receipt-v1", "status": "CREATE_ONCE_PROBE_RETAINED",
            "receipt_id": "PROBE-001", "envelope_id": "ACCESS-001",
            "activation_receipt_sha256": sha, "task_id": "TASK-001", "task_root": "C:/OMNI/task",
            "project_root": "C:/OMNI/project", "source_roots": ["C:/OMNI/sources"], "owned_lane_root": "C:/OMNI/task/builder",
            "session_pair_sha256": sha, "capabilities": validator.WORKSPACE_GRANTS,
            "probe_path": "C:/OMNI/task/control/probe.json", "probe_bytes": 1, "probe_sha256": sha,
            "create_once": True, "overwritten": False, "retained": True,
            "read_proofs": [{"path": "C:/OMNI/sources/input.md", "bytes": 1, "sha256": sha}],
            "record_digest": sha,
        }
        access = {
            "schema": "omni-workspace-access-envelope-v1", "status": "ACCESS_READY",
            "outcome": "ACCESS_GRANTED_NON_DESTRUCTIVE", "envelope_id": "ACCESS-001",
            "activation_receipt_sha256": sha, "task_id": "TASK-001", "task_root": "C:/OMNI/task",
            "project_root": "C:/OMNI/project", "source_roots": ["C:/OMNI/sources"], "owned_lane_root": "C:/OMNI/task/builder",
            "session_pair_sha256": sha, "run_kind": "REAL",
            "requested_capabilities": validator.WORKSPACE_GRANTS,
            "granted_capabilities": validator.WORKSPACE_GRANTS,
            "non_grants": validator.WORKSPACE_NON_GRANTS,
            "separate_authorizations_required": validator.WORKSPACE_SEPARATE_AUTHORIZATIONS,
            "excluded_paths": [], "probe_receipt_binding": {"path": "C:/OMNI/control/probe.json", "bytes": 1, "sha256": sha},
            "record_digest": sha,
        }
        dry_access = dict(access)
        dry_access.update({
            "status": "AUTONOMY_UNAVAILABLE_NO_ACCESS",
            "outcome": "ACCESS_PLANNED_DRY_RUN",
            "run_kind": "DRY_RUN",
            "granted_capabilities": [],
            "probe_receipt_binding": None,
        })
        instances = {
            "fused_program.schema.json": program,
            "program_countersign_receipt.schema.json": receipt,
            "workspace_access_envelope.schema.json": access,
            "workspace_access_probe_receipt.schema.json": probe,
        }
        for filename, instance in instances.items():
            with self.subTest(filename=filename):
                schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
                compiled = validator.jsonschema.Draft202012Validator(schema)
                self.assertEqual(list(compiled.iter_errors(instance)), [])
                self.assertTrue(list(compiled.iter_errors({"notes": "marker-only arbitrary file"})))
        access_schema = json.loads((ROOT / "schemas" / "workspace_access_envelope.schema.json").read_text(encoding="utf-8"))
        access_compiled = validator.jsonschema.Draft202012Validator(access_schema)
        self.assertEqual(list(access_compiled.iter_errors(dry_access)), [])
        relative_mutants = (
            ("program_countersign_receipt.schema.json", receipt, ("program_binding", "path"), "program.json"),
            ("workspace_access_envelope.schema.json", access, ("task_root",), "task"),
            ("workspace_access_probe_receipt.schema.json", probe, ("probe_path",), "control/probe.json"),
        )
        for filename, instance, field_path, relative_value in relative_mutants:
            with self.subTest(filename=filename, relative_field=".".join(field_path)):
                mutated = json.loads(json.dumps(instance))
                cursor = mutated
                for field in field_path[:-1]:
                    cursor = cursor[field]
                cursor[field_path[-1]] = relative_value
                schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
                compiled = validator.jsonschema.Draft202012Validator(schema)
                self.assertTrue(list(compiled.iter_errors(mutated)))

    def test_closed_l2_schema_semantic_mutants_fail_closed(self):
        validator = load("validate_skill_closed_l2_mutants", ROOT / "scripts" / "validate_skill.py")
        mutants = (
            ("fused_program.schema.json", lambda s: s["properties"]["status"].__setitem__("const", "FROZEN"), "FUSED_PROGRAM_SCHEMA_CONTRACT_DRIFT"),
            ("fused_program.schema.json", lambda s: s["$defs"]["work_item"].__setitem__("additionalProperties", True), "FUSED_PROGRAM_SCHEMA_CONTRACT_DRIFT"),
            ("program_countersign_receipt.schema.json", lambda s: s["properties"]["signer_role"].__setitem__("const", "BUILDER"), "PROGRAM_COUNTERSIGN_SCHEMA_CONTRACT_DRIFT"),
            ("program_countersign_receipt.schema.json", lambda s: s["required"].remove("session_pair_sha256"), "L2_ARTIFACT_SCHEMA_ENVELOPE_DRIFT:program_countersign_receipt.schema.json"),
            ("workspace_access_envelope.schema.json", lambda s: s["properties"]["non_grants"]["const"].remove("DELETE"), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][0]["then"]["properties"]["run_kind"].__setitem__("const", "DRY_RUN"), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][0]["then"]["properties"]["granted_capabilities"]["const"].pop(), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][0]["then"]["properties"].__setitem__("probe_receipt_binding", {"type": "null"}), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][1]["then"]["properties"]["granted_capabilities"].__setitem__("maxItems", 1), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][1]["then"]["properties"].__setitem__("probe_receipt_binding", {"$ref": "#/$defs/file_binding"}), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][2]["then"]["properties"]["status"].__setitem__("const", "AUTONOMY_UNAVAILABLE_NO_ACCESS"), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][3]["then"]["properties"]["outcome"]["enum"].append("ACCESS_GRANTED_NON_DESTRUCTIVE"), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][4]["then"]["properties"]["granted_capabilities"].__setitem__("maxItems", 4), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_envelope.schema.json", lambda s: s["allOf"][5]["then"]["properties"]["granted_capabilities"].__setitem__("maxItems", 1), "WORKSPACE_ACCESS_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_probe_receipt.schema.json", lambda s: s["properties"]["retained"].__setitem__("const", False), "WORKSPACE_PROBE_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_probe_receipt.schema.json", lambda s: s["properties"]["schema"].__setitem__("const", "omni-workspace-create-once-probe-receipt-v1"), "WORKSPACE_PROBE_SCHEMA_CONTRACT_DRIFT"),
            ("workspace_access_probe_receipt.schema.json", lambda s: s["required"].remove("activation_receipt_sha256"), "L2_ARTIFACT_SCHEMA_ENVELOPE_DRIFT:workspace_access_probe_receipt.schema.json"),
        )
        for filename, mutate, expected in mutants:
            with self.subTest(filename=filename, expected=expected), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "schemas" / filename
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_structured_template_contract_defeats_marker_only_bypass(self):
        validator = load("validate_skill_structured_template_mutants", ROOT / "scripts" / "validate_skill.py")
        sha = "A" * 64
        cases = (
            ("  payload_path: C:/OMNI/control/topology_selection_relay.json\n", "# payload_path: marker preserved but field absent\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_RELAY_BINDING_DRIFT"),
            ("  builder_bytes: 1\n", "# builder_bytes: 1 marker-only\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_MANDATE_BINDING_DRIFT"),
            ("    status: PROGRAM_FUSION_FROZEN\n", "    status: FROZEN\n# PROGRAM_FUSION_FROZEN marker-only\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_PROGRAM_DRIFT"),
            (f"    program_record_digest: {sha}\n", "# program_record_digest: marker-only\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_COUNTERSIGN_DRIFT"),
            ("    create_once: true\n", "    create_once: false\n# create_once: true marker-only\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_WORKSPACE_ACCESS_DRIFT"),
        )
        for old, new, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "templates" / "contratto_fase.yaml"
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_phase_template_absolute_placeholders_fail_closed(self):
        validator = load("validate_skill_phase_absolute_placeholder_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            ("  path: C:/OMNI/control/activation_receipt.json\n", "  path: activation_receipt.json\n", "GUIDED_INTAKE_TEMPLATE_ABSOLUTE_PATH_PLACEHOLDER_DRIFT:activation_receipt.path"),
            ("    task_root: C:/OMNI/task\n", "    task_root: task\n", "GUIDED_INTAKE_TEMPLATE_ABSOLUTE_PATH_PLACEHOLDER_DRIFT:workspace_access_envelope.artifact.task_root"),
            ("    program_binding:\n      path: C:/OMNI/control/fused_program.json\n", "    program_binding:\n      path: fused_program.json\n", "GUIDED_INTAKE_TEMPLATE_ABSOLUTE_PATH_PLACEHOLDER_DRIFT:program_countersign_receipt.artifact.program_binding.path"),
        )
        for old, new, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "templates" / "contratto_fase.yaml"
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_template_wrappers_and_standalone_artifacts_fail_closed(self):
        validator = load("validate_skill_template_standalone_mutants", ROOT / "scripts" / "validate_skill.py")
        baseline = validator.validate(ROOT, run_tests=False)
        self.assertFalse(
            any(error.startswith("GUIDED_INTAKE_TEMPLATE_STANDALONE_SCHEMA_REJECTED") for error in baseline["errors"]),
            baseline,
        )
        cases = (
            (
                "workspace_access_envelope:\n  binding:\n",
                "workspace_access_envelope:\n  physical_binding:\n",
                "GUIDED_INTAKE_TEMPLATE_WRAPPER_DRIFT:workspace_access_envelope",
            ),
            (
                "    schema: omni-workspace-access-envelope-v1\n",
                "    schema: omni-workspace-access-envelope-v1\n    unexpected_wrapper_field: true\n",
                "GUIDED_INTAKE_TEMPLATE_STANDALONE_SCHEMA_REJECTED:workspace_access_envelope:",
            ),
            (
                "    kind: PROGRAM_FUSION_CANDIDATE\n",
                "",
                "GUIDED_INTAKE_TEMPLATE_STANDALONE_SCHEMA_REJECTED:program:",
            ),
            (
                "    receipt_id: PROBE-REPLACE-ME\n",
                "",
                "GUIDED_INTAKE_TEMPLATE_STANDALONE_SCHEMA_REJECTED:workspace_access_probe_receipt:",
            ),
        )
        for old, new, expected_prefix in cases:
            with self.subTest(expected_prefix=expected_prefix), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "templates" / "contratto_fase.yaml"
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertTrue(any(error.startswith(expected_prefix) for error in result["errors"]), result)

    def test_progressive_branches_are_explicit_and_non_escalating(self):
        validator = load("validate_skill_progressive_branch_mutants", ROOT / "scripts" / "validate_skill.py")
        baseline = validator.validate(ROOT, run_tests=False)
        self.assertFalse(any(error.startswith("L2_PROGRESSIVE_BRANCH_MISSING") for error in baseline["errors"]), baseline)
        cases = (
            ("SKILL.md", "never require Q0", "require Q0", "L2_PROGRESSIVE_BRANCH_MISSING:SKILL.md:never require q0"),
            ("references/00_triage.md", "never requires Q0", "requires Q0", "L2_PROGRESSIVE_BRANCH_MISSING:references/00_triage.md:never requires q0"),
            ("references/09_glossario.md", "no redundant prompt", "another consent prompt", "L2_PROGRESSIVE_BRANCH_MISSING:references/09_glossario.md:no redundant prompt"),
            ("agents/openai.yaml", "Enter Q0 only after OMNI_FULL consent", "Enter Q0 for any module", "L2_PROGRESSIVE_BRANCH_MISSING:agents/openai.yaml:enter q0 only after omni_full consent"),
            ("templates/mandato_costruttore.md", "must never be forced through this mandate", "must enter this mandate", "L2_PROGRESSIVE_BRANCH_MISSING:templates/mandato_costruttore.md:must never be forced through this mandate"),
            ("templates/mandato_demolitore.md", "must never be forced through this mandate", "must enter this mandate", "L2_PROGRESSIVE_BRANCH_MISSING:templates/mandato_demolitore.md:must never be forced through this mandate"),
            ("SKILL.md", "Exactly one real packaged module", "One or more packaged modules", "L2_PROGRESSIVE_BRANCH_MISSING:SKILL.md:exactly one real packaged module"),
            ("references/00_triage.md", "Adding or replacing the module requires a new `MODULE_ACTIVATION_ALLOWED` receipt", "The receipt may be extended", "L2_PROGRESSIVE_BRANCH_MISSING:references/00_triage.md:adding or replacing the module requires a new `module_activation_allowed` receipt"),
            ("references/09_glossario.md", "modules_used=[THE_ONE_MODULE]", "modules_used=[MANY]", "L2_PROGRESSIVE_BRANCH_MISSING:references/09_glossario.md:modules_used=[the_one_module]"),
            ("agents/openai.yaml", "bind exactly one module per MODULE_ACTIVATION_ALLOWED receipt", "bind any modules to one receipt", "L2_PROGRESSIVE_BRANCH_MISSING:agents/openai.yaml:bind exactly one module per module_activation_allowed receipt"),
        )
        for relative, old, new, expected in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_full_orchestration_templates_reject_module_instantiation(self):
        validator = load("validate_skill_full_only_template_mutants", ROOT / "scripts" / "validate_skill.py")
        baseline = validator.validate(ROOT, run_tests=False)
        self.assertFalse(
            any(
                error.startswith("GUIDED_INTAKE_TEMPLATE_FULL_ONLY_")
                or error == "GUIDED_INTAKE_TEMPLATE_STRUCTURED_ACTIVATION_LEVEL_DRIFT"
                for error in baseline["errors"]
            ),
            baseline,
        )
        phase = validator._load_yaml(ROOT / "templates" / "contratto_fase.yaml", [])
        self.assertEqual(phase["template_scope"]["applicability"], "OMNI_FULL_ONLY")
        self.assertEqual(phase["template_scope"]["activation_level"], "OMNI_FULL")
        self.assertIs(phase["template_scope"]["module_instantiation_allowed"], False)
        self.assertEqual(phase["activation_level"]["level"], "OMNI_FULL")
        self.assertEqual(phase["activation_level"]["authority_grants"], validator.FULL_ACTIVATION_AUTHORITY_GRANTS)
        self.assertEqual(phase["activation_level"]["non_grants"], validator.FULL_ACTIVATION_NON_GRANTS)
        for section in ("guided_intake_state", "program", "mode_selection"):
            self.assertIn(section, phase)
        cases = (
            ("templates/contratto_fase.yaml", "  applicability: OMNI_FULL_ONLY\n", "  applicability: OMNI_MODULE\n", "GUIDED_INTAKE_TEMPLATE_FULL_ONLY_SCOPE_DRIFT:contratto_fase.yaml"),
            ("templates/contratto_fase.yaml", "  module_instantiation_allowed: false\n", "  module_instantiation_allowed: true\n", "GUIDED_INTAKE_TEMPLATE_FULL_ONLY_SCOPE_DRIFT:contratto_fase.yaml"),
            ("templates/contratto_fase.yaml", "  level: OMNI_FULL\n", "  level: OMNI_MODULE\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_ACTIVATION_LEVEL_DRIFT"),
            ("templates/contratto_fase.yaml", "  authority_grants: [METHOD_USE, FULL_ORCHESTRATION]\n", "  authority_grants: []\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_ACTIVATION_LEVEL_DRIFT"),
            ("templates/contratto_fase.yaml", "  non_grants: [DELETE, MOVE, RENAME_OUTSIDE_ROOT, OVERWRITE_PREEXISTING_USER_FILE, EXECUTE, INSTALL, PUBLISH, EXTERNAL_EFFECTS, CREATE_FILES, ARM_AUTOMATION]\n", "  non_grants: []\n", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_ACTIVATION_LEVEL_DRIFT"),
            ("templates/handoff.md", "`MODULE_INSTANTIATION_FORBIDDEN`", "`MODULE_INSTANTIATION_ALLOWED`", "GUIDED_INTAKE_TEMPLATE_FULL_ONLY_MARKER_MISSING:handoff.md:module_instantiation_forbidden"),
            ("templates/handoff.md", "activation level `OMNI_FULL`", "activation level (`OMNI_AWARE`, `OMNI_MODULE`, or `OMNI_FULL`)", "GUIDED_INTAKE_TEMPLATE_BINDING_MISSING:handoff.md:activation level `omni_full`"),
            ("templates/stele_zero.md", "must never instantiate for `OMNI_AWARE` or `OMNI_MODULE`", "may instantiate for `OMNI_MODULE`", "GUIDED_INTAKE_TEMPLATE_FULL_ONLY_MARKER_MISSING:stele_zero.md:must never instantiate for `omni_aware` or `omni_module`"),
        )
        for relative, old, new, expected in cases:
            with self.subTest(relative=relative, expected=expected), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_four_activation_trace_facts_are_guarded_across_surfaces(self):
        validator = load("validate_skill_activation_trace_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            ("SKILL.md", "requested_effects", "requested_actions", "L2_PROGRESSIVE_ACTIVATION_MISSING:SKILL.md:requested_effects", True),
            ("references/00_triage.md", "effect_authorized", "effect_assumed", "L2_PROGRESSIVE_TRACE_MISSING:references/00_triage.md:`artifact_grants`, `requested_effects`, `effect_authorized`, `effect_grants`", True),
            ("templates/handoff.md", "`requested_effects`", "`requested_actions`", "GUIDED_INTAKE_TEMPLATE_FIELD_MISSING:handoff.md:requested_effects", False),
            ("templates/stele_zero.md", "`skill_invoked`", "`skill_loaded`", "GUIDED_INTAKE_TEMPLATE_TRACE_FIELD_MISSING:stele_zero.md:`knowledge_available` / `skill_invoked` / activation level", False),
            ("templates/contratto_fase.yaml", "  effect_authorized: false\n", "", "GUIDED_INTAKE_TEMPLATE_STRUCTURED_ACTIVATION_LEVEL_DRIFT", False),
        )
        for relative, old, new, expected, replace_all in cases:
            with self.subTest(relative=relative, expected=expected), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                mutated = original.replace(old, new) if replace_all else original.replace(old, new, 1)
                path.write_text(mutated, encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_canonical_absolute_path_doctrine_is_guarded(self):
        validator = load("validate_skill_canonical_path_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            ("SKILL.md", "CANONICAL_ABSOLUTE_PATH_REQUIRED", "PATH_CAN_BE_RELATIVE", "L2_CANONICAL_PATH_DOCTRINE_MISSING:SKILL.md:canonical_absolute_path_required"),
            ("references/00_triage.md", "NUL_FAMILY_NOT_MODULE_SURFACE", "NUL_IS_A_MODULE", "L2_CANONICAL_PATH_DOCTRINE_MISSING:references/00_triage.md:nul_family_not_module_surface"),
            ("templates/handoff.md", "REJECT_NTFS_ADS", "ALLOW_NTFS_ADS", "GUIDED_INTAKE_TEMPLATE_CANONICAL_PATH_MISSING:handoff.md:reject_ntfs_ads"),
            ("templates/stele_zero.md", "REJECT_DRIVE_RELATIVE", "ALLOW_DRIVE_RELATIVE", "GUIDED_INTAKE_TEMPLATE_CANONICAL_PATH_MISSING:stele_zero.md:reject_drive_relative"),
            ("templates/mandato_costruttore.md", "REJECT_DEVICE_ALIAS", "ALLOW_DEVICE_ALIAS", "GUIDED_INTAKE_TEMPLATE_CANONICAL_PATH_MISSING:mandato_costruttore.md:reject_device_alias"),
            ("templates/mandato_demolitore.md", "REJECT_CWD_RELATIVE", "ALLOW_CWD_RELATIVE", "GUIDED_INTAKE_TEMPLATE_CANONICAL_PATH_MISSING:mandato_demolitore.md:reject_cwd_relative"),
        )
        for relative, old, new, expected in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_progressive_activation_and_access_doctrine_mutants_fail(self):
        validator = load("validate_skill_progressive_doctrine_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            ("SKILL.md", "KNOWLEDGE_AVAILABLE != SKILL_INVOKED != EFFECT_AUTHORIZED", "KNOWLEDGE_EQUALS_INVOCATION", "L2_PROGRESSIVE_ACTIVATION_MISSING:SKILL.md:knowledge_available != skill_invoked != effect_authorized"),
            ("SKILL.md", "UNKNOWN_MODULE_REQUESTED", "UNKNOWN_MODULE_ACCEPTED", "L2_PROGRESSIVE_ACTIVATION_MISSING:SKILL.md:unknown_module_requested"),
            ("SKILL.md", "authority_grants", "authority_claims", "L2_PROGRESSIVE_ACTIVATION_MISSING:SKILL.md:authority_grants"),
            ("references/00_triage.md", "ARM_AUTOMATION", "ARM_IMPLICITLY", "L2_PROGRESSIVE_ACTIVATION_MISSING:references/00_triage.md:arm_automation"),
            ("references/00_triage.md", "READ_NAMED_SOURCES", "READ_ANYWHERE", "L2_WORKSPACE_ACCESS_DOCTRINE_MISSING:references/00_triage.md:read_named_sources"),
            ("references/00_triage.md", "omni-workspace-access-probe-receipt-v1", "omni-workspace-probe-v0", "L2_WORKSPACE_ACCESS_DOCTRINE_MISSING:references/00_triage.md:omni-workspace-access-probe-receipt-v1"),
        )
        for relative, old, new, expected in cases:
            with self.subTest(relative=relative, expected=expected), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(old, original)
                path.write_text(original.replace(old, new), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)

    def test_package_validator_rejects_host_adapter_schema_mutant_family(self):
        validator = load("validate_skill_adapter_mutants", ROOT / "scripts" / "validate_skill.py")
        mutants = {
            "layer_erased": lambda schema: schema["$defs"].__setitem__("layer", {}),
            "layer_class_removed": lambda schema: schema["$defs"]["layer"]["required"].remove("live_proven"),
            "capability_ref_removed": lambda schema: schema["properties"]["capability_layers"]["properties"].__setitem__("session_carrier", {}),
            "rotation_reopened": lambda schema: schema["properties"]["rotation"].__setitem__("additionalProperties", True),
            "state_chain_removed": lambda schema: schema["properties"]["rotation"]["properties"].pop("state_chain"),
        }
        for name, mutate in mutants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory) / "package"
                shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                path = copy / "schemas" / "host_adapter.schema.json"
                schema = json.loads(path.read_text(encoding="utf-8"))
                mutate(schema)
                path.write_text(json.dumps(schema), encoding="utf-8")
                result = validator.validate(copy, run_tests=False)
                self.assertTrue(any(error.startswith("HOST_ADAPTER_SCHEMA_") for error in result["errors"]), result)

    def test_package_validator_consumes_host_adapter_schema_for_instances(self):
        validator = load("validate_skill_adapter_instance_mutant", ROOT / "scripts" / "validate_skill.py")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "package"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            adapter = copy / "adapters" / "codex" / "adapter.yaml"
            adapter.write_text(
                adapter.read_text(encoding="utf-8").replace("    live_proven: [create_thread, send_message_to_thread, wait_threads, navigate_to_thread]\n", "    live_proven: not-an-array\n"),
                encoding="utf-8",
            )
            result = validator.validate(copy, run_tests=False)
            self.assertTrue(any(error.startswith("HOST_ADAPTER_SCHEMA_REJECTED:codex") for error in result["errors"]), result)

    def test_package_validator_rejects_rotation_sentinel_contract_mutant(self):
        validator = load("validate_skill_sentinel_schema_mutant", ROOT / "scripts" / "validate_skill.py")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "package"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            path = copy / "schemas" / "rotation_state.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["properties"]["sentinels"]["required"].remove("context")
            path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(copy, run_tests=False)
            self.assertIn("ROTATION_SCHEMA_SENTINELS_DRIFT", result["errors"])

    def test_package_validator_pins_surface_template_and_adapter_safety_notes(self):
        validator = load("validate_skill_surface_mutants", ROOT / "scripts" / "validate_skill.py")
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "package"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            handoff = copy / "templates" / "handoff.md"
            handoff.write_text(handoff.read_text(encoding="utf-8").replace("- Surface ID:\n", ""), encoding="utf-8")
            cursor = copy / "adapters" / "cursor" / "adapter.yaml"
            cursor.write_text(cursor.read_text(encoding="utf-8").replace("  - Never pass an IDE chat ID to CLI resume without a documented compatibility guarantee; current official documentation does not prove a shared IDE/CLI session store.\n", ""), encoding="utf-8")
            result = validator.validate(copy, run_tests=False)
            self.assertIn("HANDOFF_PROFILE_FIELD_MISSING:surface id:", result["errors"])
            self.assertTrue(any(error.startswith("HOST_ADAPTER_SAFETY_NOTE_MISSING:cursor") for error in result["errors"]), result)

    def test_r3_inventory_and_no_test_contract_are_pinned(self):
        validator = load("validate_skill_r3_inventory", ROOT / "scripts" / "validate_skill.py")
        r3_files = {
            "modules/KNOWLEDGE_RESEARCH_DOSSIER/authority.schema.json",
            "modules/KNOWLEDGE_RESEARCH_DOSSIER/module.json",
            "modules/KNOWLEDGE_RESEARCH_DOSSIER/MODULE.md",
            "modules/KNOWLEDGE_RESEARCH_DOSSIER/records.schema.json",
            "modules/KNOWLEDGE_RESEARCH_DOSSIER/run.py",
            "tests/test_knowledge_research_dossier_module.py",
            "references/11_relay_ledger.md",
            "schemas/relay_ledger_entry.schema.json",
            "scripts/relay_ledger.py",
            "tests/test_r3_relay_ledger.py",
        }
        self.assertEqual(len(validator.EXPECTED), 122)
        self.assertTrue(r3_files.issubset(validator.EXPECTED))
        result = validator.validate(ROOT, run_tests=False)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["files"], 122)

    def test_r3_module_contract_mutants_fail_closed(self):
        validator = load("validate_skill_r3_module_mutants", ROOT / "scripts" / "validate_skill.py")
        cases = (
            (
                "modules/KNOWLEDGE_RESEARCH_DOSSIER/module.json",
                lambda value: value.__setitem__("module_id", "WRONG_MODULE"),
                "R3_MODULE_IDENTITY_DRIFT",
            ),
            (
                "modules/KNOWLEDGE_RESEARCH_DOSSIER/records.schema.json",
                lambda value: value["$defs"]["outcome"]["allOf"][1]["properties"]["next_gate"].__setitem__("const", "CONTINUE"),
                "R3_MODULE_TYPED_STOP_DRIFT",
            ),
            (
                "modules/KNOWLEDGE_RESEARCH_DOSSIER/authority.schema.json",
                lambda value: value["allOf"].pop(),
                "R3_MODULE_EFFECT_SEPARATION_DRIFT",
            ),
            (
                "modules/KNOWLEDGE_RESEARCH_DOSSIER/module.json",
                lambda value: value["scope"].__setitem__("opens_intake", True),
                "R3_MODULE_FORBIDDEN_SURFACE_DRIFT",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for relative, mutate, expected in cases:
                with self.subTest(relative=relative, expected=expected):
                    path = package / relative
                    original = path.read_text(encoding="utf-8")
                    value = json.loads(original)
                    mutate(value)
                    path.write_text(json.dumps(value), encoding="utf-8")
                    result = validator.validate(package, run_tests=False)
                    self.assertIn(expected, result["errors"], result)
                    path.write_text(original, encoding="utf-8")

            guard_path = package / "scripts" / "sentry" / "mode_a_guard.py"
            original_guard = guard_path.read_text(encoding="utf-8")
            guard_path.write_text(
                original_guard.replace(
                    "result.append(module_id)", 'result.append("DRIFTED_MODULE_ID")', 1
                ),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_1_GUARD_MODULE_BINDING_DRIFT", result["errors"], result)
            guard_path.write_text(original_guard, encoding="utf-8")

            module_tests = package / "tests" / "test_knowledge_research_dossier_module.py"
            original_module_tests = module_tests.read_text(encoding="utf-8")
            module_tests.write_text(
                original_module_tests.replace(
                    "test_real_guard_receipt_drives_real_module_entrypoint",
                    "removed_real_guard_module_entrypoint_e2e",
                    1,
                ),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn(
                "R3_1_GUARD_MODULE_E2E_COVERAGE_DRIFT", result["errors"], result
            )
            module_tests.write_text(original_module_tests, encoding="utf-8")

    def test_r3_relay_doctrine_schema_and_runtime_mutants_fail_closed(self):
        validator = load("validate_skill_r3_relay_mutants", ROOT / "scripts" / "validate_skill.py")
        markers = (
            ("strict physical order and uniqueness within one stream", "STREAM_LOCAL_ORDER"),
            ("a full-entry SHA-256 chain binding metadata, payload, lease, fence, predecessor, and volume link", "FULL_ENTRY_HASH"),
            ("OMNI_CANONICAL_JSON_V1", "CANONICAL_BODY_AND_CAUSAL_HEADS"),
            ("complete sorted `observed_heads` vector", "CANONICAL_BODY_AND_CAUSAL_HEADS"),
            ("LOCAL_HASH_CHAIN_UNANCHORED", "EXTERNAL_ANCHOR_MARKER"),
            ("CALLER_QUALIFIED_UNVERIFIED", "EXTERNAL_ANCHOR_MARKER"),
            ("A new writer requires a strictly higher fence.", "LEASE_FENCE"),
            ("fail-closed torn-tail detection and exact-target repair only under caller-supplied authority.", "RECOVERY"),
            ("`independent_verifier=false`", "SOLO_INDEPENDENCE_FALSE"),
        )
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "package"
            shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            reference = package / "references" / "11_relay_ledger.md"
            original_reference = reference.read_text(encoding="utf-8")
            for marker, doctrine in markers:
                with self.subTest(doctrine=doctrine):
                    self.assertIn(marker, original_reference)
                    reference.write_text(
                        original_reference.replace(marker, "REMOVED_R3_DOCTRINE"),
                        encoding="utf-8",
                    )
                    result = validator.validate(package, run_tests=False)
                    self.assertIn(
                        f"R3_RELAY_DOCTRINE_MISSING:{doctrine}", result["errors"], result
                    )
                    reference.write_text(original_reference, encoding="utf-8")

            schema_path = package / "schemas" / "relay_ledger_entry.schema.json"
            original_schema = schema_path.read_text(encoding="utf-8")
            schema = json.loads(original_schema)
            schema["properties"]["integrity_scope"]["const"] = "LOCAL_HASH_CHAIN_ANCHORED"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_RELAY_SCHEMA_DRIFT", result["errors"], result)
            schema_path.write_text(original_schema, encoding="utf-8")

            schema = json.loads(original_schema)
            schema["$defs"]["external_anchor_qualification"]["properties"]["status"]["const"] = "QUALIFIED"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_RELAY_ANCHOR_SURFACE_DRIFT", result["errors"], result)
            schema_path.write_text(original_schema, encoding="utf-8")

            for field in ("canonicalization_version", "body_bytes", "observed_heads"):
                with self.subTest(required_field=field):
                    schema = json.loads(original_schema)
                    schema["required"].remove(field)
                    schema_path.write_text(json.dumps(schema), encoding="utf-8")
                    result = validator.validate(package, run_tests=False)
                    self.assertIn("R3_RELAY_SCHEMA_DRIFT", result["errors"], result)
                    schema_path.write_text(original_schema, encoding="utf-8")

            schema = json.loads(original_schema)
            schema["properties"]["canonicalization_version"]["const"] = "OMNI_CANONICAL_JSON_V2"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_RELAY_430_SCHEMA_DRIFT", result["errors"], result)
            schema_path.write_text(original_schema, encoding="utf-8")

            runtime = package / "scripts" / "relay_ledger.py"
            original_runtime = runtime.read_text(encoding="utf-8")
            runtime.write_text(
                original_runtime.replace("OMNI-RELAY-ENTRY-V1\\0", "DRIFTED-ENTRY-DOMAIN\\0", 1),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_RELAY_RUNTIME_DRIFT", result["errors"], result)
            runtime.write_text(original_runtime, encoding="utf-8")

            runtime.write_text(
                original_runtime.replace("OMNI_CANONICAL_JSON_V1", "OMNI_CANONICAL_JSON_V2", 1),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_RELAY_RUNTIME_DRIFT", result["errors"], result)
            runtime.write_text(original_runtime, encoding="utf-8")

            ledger_tests = package / "tests" / "test_r3_relay_ledger.py"
            original_tests = ledger_tests.read_text(encoding="utf-8")
            ledger_tests.write_text(
                original_tests.replace(
                    "test_pos_canonical_body_bytes_and_causal_request_binding",
                    "removed_canonical_body_and_causal_test",
                    1,
                ),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_RELAY_430_TEST_COVERAGE_DRIFT", result["errors"], result)
            ledger_tests.write_text(original_tests, encoding="utf-8")

            schema = json.loads(original_schema)
            schema["$defs"]["rotation_policy"]["properties"][
                "max_entries_per_volume"
            ]["minimum"] = 2
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_1_RELAY_ROTATION_POLICY_DRIFT", result["errors"], result)
            schema_path.write_text(original_schema, encoding="utf-8")

            runtime.write_text(
                original_runtime.replace(
                    "DEFAULT_MAX_ENTRIES_PER_VOLUME = 1_000",
                    "DEFAULT_MAX_ENTRIES_PER_VOLUME = 1_001",
                    1,
                ),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_1_RELAY_ROTATION_POLICY_DRIFT", result["errors"], result)
            runtime.write_text(original_runtime, encoding="utf-8")

            reference.write_text(
                original_reference.replace(
                    "Rotation is strictly per writer.",
                    "Rotation may be coordinated globally.",
                    1,
                ),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn("R3_1_RELAY_ROTATION_POLICY_DRIFT", result["errors"], result)
            reference.write_text(original_reference, encoding="utf-8")

            ledger_tests.write_text(
                original_tests.replace(
                    "test_rotation_policy_triggers_at_exact_byte_threshold",
                    "removed_exact_byte_rotation_threshold_test",
                    1,
                ),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn(
                "R3_1_RELAY_ROTATION_TEST_COVERAGE_DRIFT",
                result["errors"],
                result,
            )
            ledger_tests.write_text(original_tests, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

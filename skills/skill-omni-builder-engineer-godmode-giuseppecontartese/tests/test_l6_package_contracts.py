from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_validator(name: str):
    path = ROOT / "scripts" / "validate_skill.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def clean_copy(directory: str) -> Path:
    target = Path(directory) / "package"
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return target


def host_projection(directory: str, host: str, validator) -> Path:
    target = clean_copy(directory)
    for adapter in validator.ADAPTERS:
        if adapter != host:
            shutil.rmtree(target / "adapters" / adapter)
    if host != "codex":
        shutil.rmtree(target / "agents")
    adapter_path = target / "adapters" / host / "adapter.yaml"
    adapter = validator.yaml.safe_load(adapter_path.read_text(encoding="utf-8"))
    candidate = {
        "schema": "omni-v7-delivery-candidate-v1",
        "status": "READY_FOR_INSTALLATION_CANDIDATE",
        "source_freeze_sha256": "A" * 64,
        "target": {
            "host": adapter.get("host"),
            "host_version": adapter.get("host_version"),
            "adapter_sha256": hashlib.sha256(adapter_path.read_bytes()).hexdigest().upper(),
            "classification": adapter.get("classification"),
        },
        "does_not_prove": [
            "INSTALLATION", "DISCOVERY", "BEHAVIOR_ON_TARGET", "PUBLICATION",
            "SESSION_ROTATION_ON_TARGET",
        ],
        "installation_status": "NOT_RUN",
        "discovery_status": "NOT_RUN",
        "publication_status": "NOT_RUN",
    }
    (target / "DELIVERY_CANDIDATE.json").write_text(
        json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


class IntegratedPackageContractTests(unittest.TestCase):
    def test_validation_dependencies_are_reproducibly_pinned(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("# Validation baseline: CPython 3.14.3", requirements)
        self.assertIn("PyYAML==6.0.3", requirements)
        self.assertIn("jsonschema==4.26.0", requirements)

    def test_pm_selected_apache_license_and_attribution_are_packaged(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn("END OF TERMS AND CONDITIONS", license_text)
        self.assertIn("Copyright 2026 Giuseppe Contartese", notice)
        self.assertIn("Apache License, Version 2.0", notice)

    def test_dependency_license_and_notice_drift_fail_without_tests(self):
        validator = load_validator("validate_skill_l6_package_bytes")
        mutations = {
            "requirements.txt": b"UnapprovedExtra>=1\n",
            "LICENSE": b"\nforged license exception\n",
            "NOTICE": b"\nunapproved attribution\n",
        }
        for relative, suffix in mutations.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                package = clean_copy(directory)
                path = package / relative
                path.write_bytes(path.read_bytes() + suffix)
                result = validator.validate(package, run_tests=False)
                self.assertIn(
                    f"PACKAGE_FILE_SHA256_DRIFT:{relative}", result["errors"]
                )

    def test_inventory_routes_all_three_runtime_corridors(self):
        validator = load_validator("validate_skill_l6_inventory")
        for script in ("knowledge_pipeline", "program_pipeline", "operating_regime"):
            self.assertIn(script, validator.CORE)
            self.assertIn(f"scripts/{script}.py", validator.EXPECTED)
            self.assertIn(f"{script}.py", (ROOT / "SKILL.md").read_text(encoding="utf-8"))

    def test_l4_schema_reopen_is_a_package_failure_without_running_tests(self):
        validator = load_validator("validate_skill_l6_l4_mutant")
        with tempfile.TemporaryDirectory() as directory:
            package = clean_copy(directory)
            path = package / "schemas" / "fused_program.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["additionalProperties"] = True
            path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(package, run_tests=False)
            self.assertIn(
                "INTEGRATED_SCHEMA_ENVELOPE_OPEN:fused_program.schema.json",
                result["errors"],
            )

    def test_l5_schema_identity_drift_is_a_package_failure_without_running_tests(self):
        validator = load_validator("validate_skill_l6_l5_mutant")
        with tempfile.TemporaryDirectory() as directory:
            package = clean_copy(directory)
            path = package / "schemas" / "execution_lease.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema["$id"] = "urn:omni-builder:execution-lease:forged"
            path.write_text(json.dumps(schema), encoding="utf-8")
            result = validator.validate(package, run_tests=False)
            self.assertIn(
                "INTEGRATED_SCHEMA_ID_DRIFT:execution_lease.schema.json",
                result["errors"],
            )

    def test_unmanifested_expansion_is_rejected(self):
        validator = load_validator("validate_skill_l6_unexpected")
        with tempfile.TemporaryDirectory() as directory:
            package = clean_copy(directory)
            (package / "UNMANIFESTED.txt").write_text("not part of V7\n", encoding="utf-8")
            result = validator.validate(package, run_tests=False)
            self.assertIn("UNEXPECTED:UNMANIFESTED.txt", result["errors"])

    def test_metadata_cannot_disable_model_selected_loading(self):
        validator = load_validator("validate_skill_l6_metadata_mutant")
        with tempfile.TemporaryDirectory() as directory:
            package = clean_copy(directory)
            path = package / "agents" / "openai.yaml"
            text = path.read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: true", text)
            path.write_text(
                text.replace("allow_implicit_invocation: true", "allow_implicit_invocation: false"),
                encoding="utf-8",
            )
            result = validator.validate(package, run_tests=False)
            self.assertIn("HOST_MODEL_LOADING_DISABLED", result["errors"], result)

    def test_each_host_projection_is_explicit_and_self_validating(self):
        validator = load_validator("validate_skill_l6_projection_positive")
        for host, expected_files in (("codex", 119), ("claude-code", 118), ("antigravity", 118)):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as directory:
                package = host_projection(directory, host, validator)
                result = validator.validate(
                    package, run_tests=False, projection_host=host
                )
                self.assertEqual(result["status"], "PASS", result)
                self.assertEqual(result["package_kind"], "HOST_DELIVERY_PROJECTION")
                self.assertEqual(result["projection_host"], host)
                self.assertEqual(result["files"], expected_files)

    def test_projection_never_activates_from_candidate_file_alone(self):
        validator = load_validator("validate_skill_l6_projection_explicit")
        with tempfile.TemporaryDirectory() as directory:
            package = host_projection(directory, "codex", validator)
            result = validator.validate(package, run_tests=False)
            self.assertIn("DELIVERY_PROJECTION_FLAG_REQUIRED", result["errors"])
            self.assertIn("UNEXPECTED:DELIVERY_CANDIDATE.json", result["errors"])

    def test_projection_requires_no_tests_and_rejects_receipt_or_surface_drift(self):
        validator = load_validator("validate_skill_l6_projection_mutants")
        with tempfile.TemporaryDirectory() as directory:
            package = host_projection(directory, "codex", validator)
            result = validator.validate(package, run_tests=True, projection_host="codex")
            self.assertIn("DELIVERY_PROJECTION_REQUIRES_NO_TESTS", result["errors"])

        with tempfile.TemporaryDirectory() as directory:
            package = host_projection(directory, "codex", validator)
            candidate_path = package / "DELIVERY_CANDIDATE.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["target"]["adapter_sha256"] = "0" * 64
            candidate_path.write_text(
                json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            result = validator.validate(package, run_tests=False, projection_host="codex")
            self.assertIn("DELIVERY_TARGET_ADAPTER_SHA256_DRIFT", result["errors"])

        with tempfile.TemporaryDirectory() as directory:
            package = host_projection(directory, "claude-code", validator)
            skill_path = package / "SKILL.md"
            text = skill_path.read_text(encoding="utf-8")
            closing = text.index("\n---\n", 4)
            skill_path.write_text(
                text[:closing] + "\ndisable-model-invocation: true" + text[closing:],
                encoding="utf-8",
                newline="\n",
            )
            result = validator.validate(
                package, run_tests=False, projection_host="claude-code"
            )
            self.assertTrue(
                "CLAUDE_MODEL_LOADING_BLOCKED" in result["errors"],
                result,
            )

        with tempfile.TemporaryDirectory() as directory:
            package = host_projection(directory, "antigravity", validator)
            shutil.copytree(
                ROOT / "adapters" / "cursor", package / "adapters" / "cursor"
            )
            result = validator.validate(
                package, run_tests=False, projection_host="antigravity"
            )
            self.assertIn("DELIVERY_PROJECTION_ADAPTER_SET_INVALID", result["errors"])
            self.assertIn("UNEXPECTED:adapters/cursor/adapter.yaml", result["errors"])


if __name__ == "__main__":
    unittest.main()

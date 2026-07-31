from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "modules" / "KNOWLEDGE_RESEARCH_DOSSIER"
GUARD_PATH = ROOT / "scripts" / "sentry" / "mode_a_guard.py"


def load_module():
    path = MODULE_DIR / "run.py"
    spec = importlib.util.spec_from_file_location(
        "obe_knowledge_research_dossier", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("KNOWLEDGE_MODULE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


def load_guard():
    sentry = ROOT / "scripts" / "sentry"
    sys.path.insert(0, str(sentry))
    try:
        spec = importlib.util.spec_from_file_location(
            "obe_knowledge_research_dossier_guard", GUARD_PATH
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("MODE_A_GUARD_IMPORT_FAILED")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(sentry))


GUARD = load_guard()


class ModuleFixture:
    created_at = "2026-07-31T10:00:00Z"

    def __init__(
        self,
        base: Path,
        *,
        deep_locator: str = "https://deep.example/primary",
        with_download: bool = False,
        activation_path: Path | None = None,
    ) -> None:
        self.base = base
        self.output = base / "output"
        self.output.mkdir()
        (self.output / "captures").mkdir()
        self.topic = "Bounded research topic"
        self.topic_sha256 = MOD._topic_sha256(self.topic)
        self.run_id = "RUN_001"

        self.material_path = base / "named-material.txt"
        self.material_path.write_text(
            "Named material: stable fact and context.\n", encoding="utf-8"
        )
        self.material_binding = MOD.IO.file_record(self.material_path)

        self.activation_path = activation_path or base / "activation.json"
        if activation_path is None:
            self._write_json(
                self.activation_path,
                {
                    "schema": "omni-invocation-decision-v2",
                    "status": "MODULE_ACTIVATION_ALLOWED",
                    "activation_level": "OMNI_MODULE",
                    "run_kind": "REAL",
                    "activation_allowed": True,
                    "modules_used": [MOD.MODULE_ID],
                    "intake_allowed": False,
                    "effect_authorized": False,
                    "effect_grants": [],
                },
            )
        elif not self.activation_path.is_file():
            raise RuntimeError("EXTERNAL_ACTIVATION_RECEIPT_MISSING")
        self.activation_binding = MOD.IO.file_record(self.activation_path)

        self.read_authority_path = base / "read-authority.json"
        self._write_authority(
            self.read_authority_path,
            authority_id="AUTH_READ",
            action="READ_NAMED_SOURCES",
            named_sources=[self.material_binding],
        )
        self.network_authority_path = base / "network-authority.json"
        self._write_authority(
            self.network_authority_path,
            authority_id="AUTH_NETWORK",
            action="NETWORK_RESEARCH",
            allowed_schemes=["https"],
            query_limit=8,
            source_limit=12,
            capture_policy="CAPTURE_MD_ONLY",
        )

        light_query = self._capture(
            "captures/light-query.md", "# Query\nlight discovery query\n"
        )
        light_capture = self._capture(
            "captures/light-source.md",
            "# Light source capture\nRelevant light evidence.\n",
        )
        deep_query = self._capture(
            "captures/deep-query.md", "# Query\nfocused deep question\n"
        )
        deep_capture = self._capture(
            "captures/deep-source.md",
            "# Deep source capture\nPrimary deep evidence.\n",
        )

        self.download_authority_path: Path | None = None
        download_binding = None
        acquisitions: list[dict[str, object]] = []
        extra_output_paths: list[Path] = []
        if with_download:
            quarantine = self.output / "quarantine"
            quarantine.mkdir()
            raw = quarantine / "primary.bin"
            raw.write_bytes(b"safe inert fixture bytes\n")
            rights = quarantine / "rights.md"
            rights.write_text("Public source rights evidence.\n", encoding="utf-8")
            scan = quarantine / "scan.json"
            scan.write_text('{"status":"PASS"}\n', encoding="utf-8")
            extra_output_paths.extend((raw, rights, scan))
            self.download_authority_path = base / "download-authority.json"
            self._write_authority(
                self.download_authority_path,
                authority_id="AUTH_DOWNLOAD",
                action="DOWNLOAD",
                allowed_locators=[deep_locator],
                quarantine_root=str(quarantine),
                handling_policy="QUARANTINE_HASH_NEVER_EXECUTE",
            )
            download_binding = MOD.IO.file_record(self.download_authority_path)
            acquisitions = [
                {
                    "acquisition_id": "ACQ1",
                    "source_id": "DEEP1",
                    "origin_locator": deep_locator,
                    "media_type": "application/octet-stream",
                    "retrieved_at": self.created_at,
                    "content_binding": MOD.IO.file_record(raw),
                    "rights_status": "PUBLIC",
                    "rights_evidence_binding": MOD.IO.file_record(rights),
                    "scan_status": "PASS",
                    "scan_receipt_binding": MOD.IO.file_record(scan),
                    "handling_policy": "QUARANTINE_HASH_NEVER_EXECUTE",
                }
            ]

        common = {
            "module_id": MOD.MODULE_ID,
            "run_id": self.run_id,
            "topic": self.topic,
            "topic_sha256": self.topic_sha256,
            "activation_sha256": self.activation_binding["sha256"],
            "created_at": self.created_at,
        }
        material_finding = {
            "finding_id": "FMAT1",
            "statement": "The named material provides stable context.",
            "source_ids": ["MAT1"],
            "confidence": "HIGH",
            "freshness": "HISTORICAL",
        }
        material = MOD.seal_record(
            {
                **common,
                "schema": "omni-module-material-study-v1",
                "status": "MATERIAL_STUDY_COMPLETE",
                "named_materials": [
                    {
                        "material_id": "MAT1",
                        "binding": self.material_binding,
                    }
                ],
                "study_summary": "The material was read as untrusted evidence.",
                "findings": [material_finding],
                "received_not_used": [],
            }
        )
        self.material_record_path = self.output / "MATERIAL_STUDY.json"
        self._write_json(self.material_record_path, material)
        material_record_binding = MOD.IO.file_record(self.material_record_path)

        light_source = {
            "source_id": "LIGHT1",
            "research_phase": "LIGHT_WEB",
            "locator": "https://light.example/overview",
            "title": "Overview",
            "publisher": "Light Publisher",
            "accessed_at": self.created_at,
            "capture_mode": "CAPTURE_MD_ONLY",
            "capture_binding": light_capture,
            "sections_consulted": ["Overview"],
        }
        light_finding = {
            "finding_id": "FLIGHT1",
            "statement": "The discovery pass identifies the public landscape.",
            "source_ids": ["LIGHT1"],
            "confidence": "MEDIUM",
            "freshness": "CURRENT_SECONDARY",
        }
        light = MOD.seal_record(
            {
                **common,
                "schema": "omni-module-light-map-v1",
                "status": "LIGHT_MAP_COMPLETE",
                "material_study_binding": material_record_binding,
                "queries": [
                    {
                        "query_id": "QLIGHT1",
                        "query": "bounded topic overview",
                        "capture_binding": light_query,
                    }
                ],
                "sources": [light_source],
                "findings": [light_finding],
            }
        )
        self.light_record_path = self.output / "LIGHT_MAP.json"
        self._write_json(self.light_record_path, light)
        light_record_binding = MOD.IO.file_record(self.light_record_path)

        deep_source = {
            "source_id": "DEEP1",
            "research_phase": "DEEP_WEB",
            "locator": deep_locator,
            "title": "Primary evidence",
            "publisher": "Deep Publisher",
            "accessed_at": self.created_at,
            "capture_mode": "CAPTURE_MD_ONLY",
            "capture_binding": deep_capture,
            "sections_consulted": ["Methods", "Results"],
        }
        deep_finding = {
            "finding_id": "FDEEP1",
            "statement": "The deep pass adds focused primary evidence.",
            "source_ids": ["DEEP1"],
            "confidence": "HIGH",
            "freshness": "CURRENT_PRIMARY",
        }
        deep = MOD.seal_record(
            {
                **common,
                "schema": "omni-module-deep-research-receipt-v1",
                "status": "DEEP_RESEARCH_COMPLETE",
                "material_study_binding": material_record_binding,
                "light_map_binding": light_record_binding,
                "research_questions": ["What primary evidence tests the topic?"],
                "priorities": ["Prefer primary and current sources."],
                "stop_conditions": ["Stop after one corroborated primary source."],
                "queries": [
                    {
                        "query_id": "QDEEP1",
                        "query": "bounded topic primary evidence",
                        "capture_binding": deep_query,
                    }
                ],
                "sources": [deep_source],
                "findings": [deep_finding],
                "conflicts": [],
                "download_outcome": (
                    "DOWNLOAD_AUTHORIZED_QUARANTINED_RAW"
                    if with_download
                    else "DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY"
                ),
                "download_authority_binding": download_binding,
                "acquisitions": acquisitions,
            }
        )
        self.deep_record_path = self.output / "DEEP_RESEARCH_RECEIPT.json"
        self._write_json(self.deep_record_path, deep)
        deep_record_binding = MOD.IO.file_record(self.deep_record_path)

        provenance = {
            "provenance_id": "PROV1",
            "sources_actually_read": ["MAT1", "LIGHT1", "DEEP1"],
            "version_hash_access_date": [
                f"MAT1 {self.material_binding['sha256']} {self.created_at}",
                f"LIGHT1 {light_capture['sha256']} {self.created_at}",
                f"DEEP1 {deep_capture['sha256']} {self.created_at}",
            ],
            "sections_consulted": ["Material body", "Overview", "Methods", "Results"],
            "received_material_not_used": [],
            "facts_extracted": [
                "Stable context.",
                "Landscape evidence.",
                "Primary evidence.",
            ],
            "model_synthesis_or_inference": [
                "The combined evidence supports the bounded synthesis."
            ],
            "conflicts_gaps_and_limits": [
                "This fixture represents a deliberately small research budget."
            ],
        }
        manifest = MOD.seal_record(
            {
                **common,
                "schema": "omni-module-source-manifest-v1",
                "status": "SOURCE_MANIFEST_FROZEN",
                "material_study_binding": material_record_binding,
                "light_map_binding": light_record_binding,
                "deep_research_receipt_binding": deep_record_binding,
                "material_source_ids": ["MAT1"],
                "light_source_ids": ["LIGHT1"],
                "deep_source_ids": ["DEEP1"],
                "deep_new_source_ids": ["DEEP1"],
                "sources": [light_source, deep_source],
                "findings": [
                    material_finding,
                    light_finding,
                    deep_finding,
                ],
                "conflicts": [],
                "provenance": [provenance],
                "received_not_used": [],
                "download_mode": (
                    "QUARANTINED_RAW" if with_download else "CAPTURE_MD_ONLY"
                ),
                "download_authority_binding": download_binding,
                "acquisitions": acquisitions,
                "limits": ["Bounded fixture research budget."],
            }
        )
        self.manifest_path = self.output / "SOURCE_MANIFEST.json"
        self._write_json(self.manifest_path, manifest)

        self.dossier_path = self.output / "DOSSIER.md"
        self.dossier_path.write_text(
            "\n".join(
                (
                    "# Bounded research dossier",
                    "",
                    "## Findings",
                    "[FMAT1] Material context [MAT1].",
                    "[FLIGHT1] Landscape evidence [LIGHT1].",
                    "[FDEEP1] Primary evidence [DEEP1].",
                    "",
                    "## Provenance",
                    "Actually read: [MAT1], [LIGHT1], [DEEP1].",
                    "",
                )
            ),
            encoding="utf-8",
        )

        output_paths = [
            *(self.output / name for name in MOD.FIXED_OUTPUTS),
            self.output / "captures" / "light-query.md",
            self.output / "captures" / "light-source.md",
            self.output / "captures" / "deep-query.md",
            self.output / "captures" / "deep-source.md",
            *extra_output_paths,
        ]
        self.write_authority_path = base / "write-authority.json"
        self._write_authority(
            self.write_authority_path,
            authority_id="AUTH_WRITE",
            action="CREATE_FILES",
            output_root=str(self.output),
            output_paths=[str(path) for path in output_paths],
        )

    def _write_json(self, path: Path, value: dict[str, object]) -> None:
        path.write_text(
            f"{MOD.IO.canonical_json(value)}\n",
            encoding="utf-8",
            newline="\n",
        )

    def _write_authority(
        self,
        path: Path,
        *,
        authority_id: str,
        action: str,
        **scope: object,
    ) -> None:
        authority = MOD.seal_record(
            {
                "schema": "omni-module-effect-authority-v1",
                "status": "AUTHORIZED",
                "authority_id": authority_id,
                "module_id": MOD.MODULE_ID,
                "run_id": self.run_id,
                "topic_sha256": self.topic_sha256,
                "activation_binding": self.activation_binding,
                "action": action,
                "one_shot": True,
                "issued_at": self.created_at,
                "expires_at": "2099-01-01T00:00:00Z",
                **scope,
            }
        )
        self._write_json(path, authority)

    def _capture(self, relative: str, text: str) -> dict[str, object]:
        path = self.output / relative
        path.write_text(text, encoding="utf-8", newline="\n")
        return MOD.IO.file_record(path)

    def kwargs(self) -> dict[str, object]:
        return {
            "activation_path": self.activation_path,
            "read_authority_path": self.read_authority_path,
            "write_authority_path": self.write_authority_path,
            "network_authority_path": self.network_authority_path,
            "download_authority_path": self.download_authority_path,
            "topic": self.topic,
            "run_id": self.run_id,
            "output_root": self.output,
        }


def nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for nested in value.values()
            for key in nested_keys(nested)
        }
    if isinstance(value, list):
        return {
            key
            for nested in value
            for key in nested_keys(nested)
        }
    return set()


class KnowledgeResearchDossierModuleTests(unittest.TestCase):
    def test_real_guard_receipt_drives_real_module_entrypoint(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_guard_e2e_") as tmp:
            root = Path(tmp)
            guard = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(GUARD_PATH),
                    "--explicit-user-request",
                    "--run-kind",
                    "REAL",
                    "--activation-level",
                    "OMNI_MODULE",
                    "--module",
                    "modules/KNOWLEDGE_RESEARCH_DOSSIER",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)
            receipt = json.loads(guard.stdout)
            self.assertEqual(receipt["status"], "MODULE_ACTIVATION_ALLOWED")
            self.assertEqual(receipt["modules_used"], [MOD.MODULE_ID])
            activation_path = root / "activation.json"
            activation_path.write_text(guard.stdout, encoding="utf-8", newline="\n")

            fixture = ModuleFixture(root, activation_path=activation_path)
            command = [
                sys.executable,
                "-B",
                str(MODULE_DIR / "run.py"),
                "finalize",
                "--activation",
                str(activation_path),
                "--read-authority",
                str(fixture.read_authority_path),
                "--write-authority",
                str(fixture.write_authority_path),
                "--network-authority",
                str(fixture.network_authority_path),
                "--topic",
                fixture.topic,
                "--run-id",
                fixture.run_id,
                "--output-root",
                str(fixture.output),
            ]
            module = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(module.returncode, 0, module.stdout + module.stderr)
            outcome = json.loads(module.stdout)
            self.assertEqual(outcome["status"], "PASS")
            self.assertEqual(outcome["module_id"], MOD.MODULE_ID)
            self.assertEqual(
                outcome["module_status"], "KNOWLEDGE_RESEARCH_DOSSIER_READY"
            )
            self.assertEqual(outcome["next_gate"], "STOP")

    def test_guard_blocks_unknown_invalid_and_identity_drifted_modules(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_guard_manifest_") as tmp:
            skill_root = Path(tmp)
            modules_root = skill_root / "modules"
            modules_root.mkdir()
            common = {
                "explicit_user_request": True,
                "complexity_warrants_omni": False,
                "run_kind": "REAL",
                "activation_level": "OMNI_MODULE",
            }
            with patch.object(GUARD, "SKILL_ROOT", skill_root):
                with self.assertRaisesRegex(ValueError, "UNKNOWN_MODULE_REQUESTED"):
                    GUARD.decide_invocation(
                        **common, modules=["modules/NOT_PACKAGED"]
                    )

                broken = modules_root / "BROKEN"
                broken.mkdir()
                (broken / "module.json").write_text(
                    '{"schema":"omni-module-manifest-v1",', encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "MODULE_MANIFEST_INVALID"):
                    GUARD.decide_invocation(**common, modules=["modules/BROKEN"])

                (broken / "run.py").write_text("pass\n", encoding="utf-8")
                (broken / "module.json").write_text(
                    json.dumps(
                        {
                            "schema": "omni-module-manifest-v1",
                            "module_id": "DIFFERENT_ID",
                            "version": "1.0.0",
                            "activation_level": "OMNI_MODULE",
                            "entrypoint": "run.py",
                            "summary": "Identity drift fixture.",
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "MODULE_MANIFEST_ID_DRIFT"):
                    GUARD.decide_invocation(**common, modules=["modules/BROKEN"])

    def test_manifest_declares_bounded_typed_stop(self):
        manifest = json.loads(
            (MODULE_DIR / "module.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["module_id"], MOD.MODULE_ID)
        self.assertEqual(
            manifest["authorities"]["required"],
            [
                "READ_NAMED_SOURCES",
                "CREATE_FILES",
                "NETWORK_RESEARCH",
            ],
        )
        self.assertEqual(manifest["authorities"]["optional"], ["DOWNLOAD"])
        self.assertEqual(
            manifest["network_policy"]["download_fallback"],
            "DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY",
        )
        self.assertEqual(
            manifest["terminal"],
            {
                "status": "KNOWLEDGE_RESEARCH_DOSSIER_READY",
                "next_gate": "STOP",
            },
        )

    def test_capture_only_finalize_replay_verify_and_stop(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_capture_") as tmp:
            fixture = ModuleFixture(Path(tmp))
            outcome, binding, write_status = MOD.finalize_run(**fixture.kwargs())
            self.assertEqual(write_status, "CREATED")
            self.assertEqual(
                outcome["status"], "KNOWLEDGE_RESEARCH_DOSSIER_READY"
            )
            self.assertEqual(outcome["next_gate"], "STOP")
            self.assertEqual(
                outcome["download_outcome"],
                "DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY",
            )
            self.assertEqual(
                binding,
                MOD.IO.file_record(fixture.output / "MODULE_OUTCOME.json"),
            )
            forbidden_runtime_keys = {
                "intake_state",
                "well_root",
                "session_pair_sha256",
                "team_card",
                "topology",
                "program",
                "omni_mode",
                "lanes",
                "roles",
            }
            self.assertFalse(nested_keys(outcome) & forbidden_runtime_keys)

            replay, replay_binding, replay_status = MOD.finalize_run(
                **fixture.kwargs()
            )
            self.assertEqual(replay_status, "ALREADY_PRESENT_IDENTICAL")
            self.assertEqual(replay, outcome)
            self.assertEqual(replay_binding, binding)
            verified, verified_binding = MOD.verify_run(**fixture.kwargs())
            self.assertEqual(verified, outcome)
            self.assertEqual(verified_binding, binding)

    def test_download_requires_its_own_authority_and_quarantine_evidence(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_download_") as tmp:
            fixture = ModuleFixture(Path(tmp), with_download=True)
            outcome, _, _ = MOD.finalize_run(**fixture.kwargs())
            self.assertEqual(
                outcome["download_outcome"],
                "DOWNLOAD_AUTHORIZED_QUARANTINED_RAW",
            )
            self.assertEqual(outcome["next_gate"], "STOP")

    def test_raw_bytes_without_download_authority_are_blocked(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_raw_") as tmp:
            fixture = ModuleFixture(Path(tmp))
            quarantine = fixture.output / "quarantine"
            quarantine.mkdir()
            (quarantine / "undeclared.bin").write_bytes(b"raw")
            with self.assertRaisesRegex(
                MOD.ModuleContractError, "RAW_DOWNLOAD_WITHOUT_AUTHORITY"
            ):
                MOD.finalize_run(**fixture.kwargs())

    def test_material_identity_drift_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_drift_") as tmp:
            fixture = ModuleFixture(Path(tmp))
            fixture.material_path.write_text(
                "changed after authority\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                MOD.ModuleContractError, "MATERIAL_IDENTITY_DRIFT"
            ):
                MOD.finalize_run(**fixture.kwargs())

    def test_deep_research_must_add_a_new_locator(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_delta_") as tmp:
            fixture = ModuleFixture(
                Path(tmp), deep_locator="https://light.example/overview"
            )
            with self.assertRaisesRegex(
                MOD.ModuleContractError, "DEEP_RESEARCH_NEW_SOURCE_REQUIRED"
            ):
                MOD.finalize_run(**fixture.kwargs())

    def test_one_authority_cannot_combine_network_and_download(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_authority_") as tmp:
            fixture = ModuleFixture(Path(tmp))
            authority = json.loads(
                fixture.network_authority_path.read_text(encoding="utf-8")
            )
            authority["allowed_locators"] = ["https://deep.example/primary"]
            authority["record_digest"] = MOD._record_digest(authority)
            malformed = fixture.base / "combined-authority.json"
            fixture._write_json(malformed, authority)
            with self.assertRaisesRegex(
                MOD.ModuleContractError, "AUTHORITY_SCHEMA_INVALID"
            ):
                MOD.gate_effect(
                    activation_path=fixture.activation_path,
                    authority_path=malformed,
                    action="NETWORK_RESEARCH",
                    topic=fixture.topic,
                    run_id=fixture.run_id,
                )

    def test_cli_emits_typed_network_authority_stop(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_cli_") as tmp:
            fixture = ModuleFixture(Path(tmp))
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = MOD.main(
                    [
                        "finalize",
                        "--activation",
                        str(fixture.activation_path),
                        "--read-authority",
                        str(fixture.read_authority_path),
                        "--write-authority",
                        str(fixture.write_authority_path),
                        "--network-authority",
                        str(fixture.read_authority_path),
                        "--topic",
                        fixture.topic,
                        "--run-id",
                        fixture.run_id,
                        "--output-root",
                        str(fixture.output),
                    ]
                )
            result = json.loads(stream.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(
                result["reason_code"], "NETWORK_RESEARCH_NOT_AUTHORIZED"
            )

    def test_divergent_terminal_collision_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix="obe_krd_collision_") as tmp:
            fixture = ModuleFixture(Path(tmp))
            target = fixture.output / "MODULE_OUTCOME.json"
            target.write_text('{"divergent":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "CREATE_ONCE_COLLISION"):
                MOD.finalize_run(**fixture.kwargs())


if __name__ == "__main__":
    unittest.main()

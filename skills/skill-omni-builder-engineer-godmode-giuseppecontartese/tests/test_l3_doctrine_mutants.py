from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# Each marker is a positive, fail-closed L3 law. The mutation directly inverts
# that law; validate_skill.py must therefore emit the exact marker error below.
DOCTRINE_MUTANTS = (
    (
        "SKILL.md",
        "Existing user material never replaces independent web research",
        "Existing user material may replace independent web research",
    ),
    (
        "references/00_triage.md",
        "Mandatory research is a completion requirement, not a grant",
        "Mandatory research automatically grants network access",
    ),
    (
        "references/00_triage.md",
        "`DOWNLOAD` remains a separate optional authority and is never implied by `NETWORK_RESEARCH`",
        "`DOWNLOAD` is implied by `NETWORK_RESEARCH`",
    ),
    (
        "references/02_pozzo.md",
        "Create exactly one project well, never one well per agent",
        "Create one project well per agent",
    ),
    (
        "references/02_pozzo.md",
        "separate brains and non-overlapping write lanes",
        "one shared brain and one shared write lane",
    ),
    (
        "references/01_cappelli.md",
        "Before both lane freezes, neither brain may read the other's synthesis",
        "Before both lane freezes, each brain should read the other's synthesis",
    ),
    (
        "references/03_conoscenza.md",
        "no separate or fused realization plan is canonical before it",
        "a separate or fused realization plan may be canonical before it",
    ),
    (
        "SKILL.md",
        "A distinct verifier reproduces both lane bindings",
        "The builder may self-sign without a distinct verifier",
    ),
    (
        "references/01_cappelli.md",
        "In `GUIDED_PM`, the PM explicitly transfers the turn and continuous autonomy sentinels remain unarmed",
        "In `GUIDED_PM`, autonomy and all continuous sentinels arm automatically",
    ),
    (
        "references/01_cappelli.md",
        "Existing material never exempts either lane from web research",
        "Existing material exempts either lane from web research",
    ),
)


class L3DoctrineMutantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load(
            "validate_skill_l3_doctrine_mutants",
            ROOT / "scripts" / "validate_skill.py",
        )

    def test_l3_doctrine_marker_baseline(self):
        for relative, marker, _mutation in DOCTRINE_MUTANTS:
            with self.subTest(relative=relative, marker=marker):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(marker, text)

        result = self.validator.validate(ROOT, run_tests=False)
        l3_errors = [
            error
            for error in result["errors"]
            if error.startswith("L3_DOCTRINE_MARKER_MISSING:")
        ]
        self.assertEqual(l3_errors, [], result)

    def test_every_l3_doctrine_inversion_fails_closed(self):
        for relative, marker, mutation in DOCTRINE_MUTANTS:
            expected = (
                f"L3_DOCTRINE_MARKER_MISSING:{relative}:{marker.lower()}"
            )
            with self.subTest(relative=relative, marker=marker), tempfile.TemporaryDirectory() as directory:
                cold_copy = Path(directory) / "package"
                shutil.copytree(
                    ROOT,
                    cold_copy,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc", ".pytest_cache"
                    ),
                )
                path = cold_copy / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(marker, original)
                path.write_text(
                    original.replace(marker, mutation, 1),
                    encoding="utf-8",
                )

                result = self.validator.validate(cold_copy, run_tests=False)
                self.assertIn(expected, result["errors"], result)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRUSTED_DIR = ROOT / ".github" / "trusted"
PROOF_DIR = ROOT / ".autodev" / "release" / "proof"


def load_prepare_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "v1_8_release_proof_prepare.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_8_release_proof_frozen_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.8 release proof prepare module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class V18ReleaseProofFrozenTests(unittest.TestCase):
    def test_frozen_preapproval_proof_matches_trusted_reconstruction(self) -> None:
        module = load_prepare_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = module.build_release_proof(
                decision_store_path=Path(temp_dir) / "decisions.json",
            )

        immutable_expected = {
            "source-manifest.json": bundle["source_manifest"],
            "readiness.json": bundle["readiness"],
            "candidate.json": bundle["candidate"],
            "transition.json": bundle["transition"],
        }
        for filename, payload in immutable_expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(
                    load_json(PROOF_DIR / filename),
                    payload,
                )

        preapproval_dir = PROOF_DIR / "preapproval"
        lifecycle_expected = {
            "decision-record.json": bundle["decision_record"],
            "approval.json": bundle["approval"],
            "state.json": bundle["proof_state"],
            "mission-control.json": bundle["mission_control"],
        }
        for filename, payload in lifecycle_expected.items():
            with self.subTest(preapproval_filename=filename):
                self.assertEqual(
                    load_json(preapproval_dir / filename),
                    payload,
                )

    def test_frozen_provenance_binds_successful_prepare_run(self) -> None:
        provenance = load_json(
            PROOF_DIR / "preparation-provenance.json"
        )
        self.assertEqual(provenance["schema_version"], 1)
        self.assertEqual(
            provenance["proof_id"],
            "v1.8-autonomous-release-proof-001",
        )
        self.assertEqual(
            provenance["controller_source_sha"],
            "c60e72620986659e0167817ae38ab0d709fe575c",
        )
        self.assertEqual(
            provenance["workflow_name"],
            "ADE v1.8 Release Proof Prepare",
        )
        self.assertEqual(
            provenance["workflow_run_id"],
            36878989307,
        )
        self.assertEqual(
            provenance["artifact_id"],
            11171310220,
        )
        self.assertFalse(
            provenance["external_side_effect_executed"]
        )


if __name__ == "__main__":
    unittest.main()

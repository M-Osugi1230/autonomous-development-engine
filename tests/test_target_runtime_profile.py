from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED = Path(__file__).resolve().parents[1] / ".github" / "trusted"
if str(TRUSTED) not in sys.path:
    sys.path.insert(0, str(TRUSTED))


def load_profile():
    path = TRUSTED / "target_runtime_profile.py"
    spec = importlib.util.spec_from_file_location(
        "target_runtime_profile_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load target_runtime_profile.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_payload() -> dict:
    return {
        "schemaVersion": "plan-detection-candidate-batch-v1",
        "batchId": "ade-batch-002",
        "nonPublic": True,
        "policy": {
            "humanReviewRequired": True,
            "automaticPromotionAllowed": False,
            "publicationAllowed": False,
            "inferNoFormalPlanFromMissingEvidence": False,
            "allowedSuggestedStatuses": [
                "current",
                "expired",
                "found_unstructured",
                "not_checked",
            ],
            "finalRegistryMutationAllowed": False,
        },
        "candidates": [
            {
                "code": "138A",
                "name": "Example Co",
                "source": {
                    "authority": "official_primary",
                    "publishedDate": "2026-02-24",
                    "url": "https://example.com/primary.pdf",
                },
                "observation": {
                    "suggestedStatus": "found_unstructured",
                },
                "provenance": {
                    "repositoryPaths": [
                        "operations/patches/example.json",
                    ],
                },
                "review": {
                    "decision": "needs_review",
                    "status": "pending",
                },
                "publication": {"eligible": False},
                "promotion": {"allowed": False},
            }
        ],
    }


class TargetRuntimeProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_profile()

    def test_chu_candidate_contract_accepts_safe_pending_candidate(self) -> None:
        ok, detail = self.module.validate_chu_kei_candidate_payload(
            valid_payload(),
            expected_batch_id="ade-batch-002",
        )
        self.assertTrue(ok)
        self.assertEqual(
            detail,
            "chu-plan-detection-candidate-contract-pass",
        )

    def test_chu_candidate_contract_rejects_publication(self) -> None:
        payload = valid_payload()
        payload["candidates"][0]["publication"]["eligible"] = True
        ok, detail = self.module.validate_chu_kei_candidate_payload(
            payload,
            expected_batch_id="ade-batch-002",
        )
        self.assertFalse(ok)
        self.assertEqual(
            detail,
            "chu-candidate-publication-must-remain-ineligible",
        )

    def test_chu_candidate_contract_rejects_no_formal_plan(self) -> None:
        payload = valid_payload()
        payload["candidates"][0]["observation"]["suggestedStatus"] = (
            "no_formal_plan"
        )
        ok, detail = self.module.validate_chu_kei_candidate_payload(
            payload,
            expected_batch_id="ade-batch-002",
        )
        self.assertFalse(ok)
        self.assertEqual(detail, "chu-candidate-suggested-status-invalid")

    def test_chu_candidate_contract_rejects_non_primary_source(self) -> None:
        payload = valid_payload()
        payload["candidates"][0]["source"]["authority"] = "secondary"
        ok, detail = self.module.validate_chu_kei_candidate_payload(
            payload,
            expected_batch_id="ade-batch-002",
        )
        self.assertFalse(ok)
        self.assertEqual(
            detail,
            "chu-candidate-source-authority-invalid",
        )

    def test_chu_candidate_path_is_exact_and_bounded(self) -> None:
        self.assertTrue(
            self.module.is_chu_kei_candidate_path(
                "operations/plan-detection/candidates/"
                "ade-batch-002/candidates-v1.json"
            )
        )
        self.assertFalse(
            self.module.is_chu_kei_candidate_path(
                "operations/plan-detection/registry-v1.json"
            )
        )
        self.assertFalse(
            self.module.is_chu_kei_candidate_path(
                "operations/plan-detection/candidates/"
                "manual/candidates-v1.json"
            )
        )

    def test_chu_policy_uses_single_candidate_contract_probe(self) -> None:
        policy = self.module.build_runtime_verification_policy(
            "M-Osugi1230/chu-kei"
        )
        registry = self.module.build_runtime_probe_registry(
            target_repository="M-Osugi1230/chu-kei"
        )
        self.assertEqual(
            policy.required_probe_ids,
            ("chu-plan-detection-candidate-contract",),
        )
        self.assertEqual(
            registry.probe_ids,
            ("chu-plan-detection-candidate-contract",),
        )
        self.assertEqual(policy.timeout_seconds, 120)


if __name__ == "__main__":
    unittest.main()

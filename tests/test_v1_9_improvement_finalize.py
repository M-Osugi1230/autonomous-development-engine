from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_finalizer():
    path = (
        ROOT
        / ".github"
        / "trusted"
        / "v1_9_improvement_finalize.py"
    )
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_9_improvement_finalize_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.9 finalizer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fake_api(url: str):
    if url.endswith("/pulls/23"):
        return {
            "number": 23,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-10-02T11:52:43Z",
            "merge_commit_sha": (
                "fa4f4b3a87f78d2bea596177811247072bca37ce"
            ),
            "title": (
                "Add regression coverage for U+2005 and U+2008 "
                "space normalization"
            ),
            "head": {
                "sha": (
                    "4057ebca5c4405573ae73300d03b208edf95ca62"
                )
            },
            "base": {
                "sha": (
                    "726431b60db8b25cdd4bc15bb1493a0060f36327"
                ),
                "ref": "main",
            },
        }
    if url.endswith("/pulls/23/files?per_page=100"):
        return [
            {
                "filename": "tests/test_models.py",
                "status": "modified",
                "additions": 4,
                "deletions": 0,
                "changes": 4,
            }
        ]
    if url.endswith("/actions/runs/37003361924"):
        return {
            "id": 37003361924,
            "name": "Phase 1 and 2 checks",
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_sha": (
                "4057ebca5c4405573ae73300d03b208edf95ca62"
            ),
            "head_branch": (
                "jules-12498840135613804584-108d7add"
            ),
            "run_attempt": 1,
            "created_at": "2026-10-02T11:51:55Z",
            "updated_at": "2026-10-02T11:52:32Z",
        }
    raise AssertionError(f"unexpected URL: {url}")


class V19ImprovementFinalizerTests(unittest.TestCase):
    def test_real_proof_reconstructs_closed_loop(self) -> None:
        module = load_finalizer()
        bundle = module.build_final_proof(api_get=fake_api)

        evidence = bundle["campaign_evidence"]
        self.assertTrue(evidence["closed_loop_verified"])
        self.assertFalse(
            evidence["human_authored_per_task_work_items"]
        )
        self.assertFalse(
            evidence[
                "manual_campaign_progress_after_goal_submission"
            ]
        )
        self.assertEqual(
            evidence["execution"]["changed_paths"],
            ["tests/test_models.py"],
        )
        self.assertEqual(
            evidence["runtime_verification"]["disposition"],
            "VERIFIED",
        )
        self.assertEqual(
            evidence["closure"]["cycle_state"],
            "VERIFIED_RETIRED",
        )
        self.assertEqual(
            evidence["closure"]["current_signal_count"],
            0,
        )
        self.assertEqual(
            evidence["closure"]["retired_signal_count"],
            1,
        )
        self.assertIsNone(
            bundle["post_backlog_selection"][
                "selected_candidate_id"
            ]
        )
        self.assertEqual(
            bundle["post_backlog_selection"][
                "eligible_candidate_ids"
            ],
            [],
        )

    def test_target_scope_drift_fails_closed(self) -> None:
        module = load_finalizer()

        def drifted(url: str):
            value = fake_api(url)
            if url.endswith("/pulls/23/files?per_page=100"):
                return [
                    *value,
                    {
                        "filename": "src/models.py",
                        "status": "modified",
                    },
                ]
            return value

        with self.assertRaisesRegex(
            ValueError,
            "changed paths outside",
        ):
            module.build_final_proof(api_get=drifted)

    def test_failed_runtime_receipt_cannot_finalize(self) -> None:
        module = load_finalizer()
        receipt = module._load_json(
            module.RUNTIME_RECEIPT_PATH
        )
        receipt["status"] = "FAILED"

        with self.assertRaisesRegex(
            ValueError,
            "Runtime Verification evidence",
        ):
            module.build_final_proof(
                api_get=fake_api,
                runtime_receipt_payload=receipt,
            )


if __name__ == "__main__":
    unittest.main()

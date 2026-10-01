from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "v1_8_release_proof_finalize.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_8_release_proof_finalize_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.8 release finalizer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def preview_ref(sha: str):
    return {
        "ref": "refs/heads/ade-preview",
        "object": {"sha": sha, "type": "commit"},
    }


def run(
    *,
    run_id: int,
    created_at: str,
    conclusion: str = "success",
    head_sha: str = "726431b60db8b25cdd4bc15bb1493a0060f36327",
    head_branch: str = "ade-preview",
    event: str = "push",
):
    return {
        "id": run_id,
        "name": "Phase 1 and 2 checks",
        "event": event,
        "status": "completed",
        "conclusion": conclusion,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "created_at": created_at,
        "updated_at": "2026-10-01T15:12:48Z",
        "run_attempt": 1,
    }


class V18ReleaseProofFinalizeTests(unittest.TestCase):
    def test_selects_only_successful_post_dispatch_preview_ci(self) -> None:
        module = load_module()
        selected = module._select_target_ci_run(
            [
                run(
                    run_id=1,
                    created_at="2026-10-01T15:10:00Z",
                ),
                run(
                    run_id=2,
                    created_at="2026-10-01T15:12:09Z",
                ),
            ],
            dispatch_merged_at="2026-10-01T15:11:44Z",
        )
        self.assertEqual(selected["id"], 2)

    def test_pre_dispatch_ci_cannot_be_reused(self) -> None:
        module = load_module()
        with self.assertRaisesRegex(
            ValueError,
            "no successful post-dispatch preview CI run",
        ):
            module._select_target_ci_run(
                [
                    run(
                        run_id=1,
                        created_at="2026-10-01T15:10:00Z",
                    )
                ],
                dispatch_merged_at="2026-10-01T15:11:44Z",
            )

    def test_build_final_proof_binds_exact_external_deployment(self) -> None:
        module = load_module()

        def fake_api(url: str):
            if "/git/ref/heads/ade-preview" in url:
                return preview_ref(module.SOURCE_SHA)
            if "/actions/runs?" in url:
                return {
                    "workflow_runs": [
                        run(
                            run_id=36882390659,
                            created_at="2026-10-01T15:12:09Z",
                        )
                    ]
                }
            raise AssertionError(f"unexpected URL: {url}")

        bundle = module.build_final_proof(api_get=fake_api)
        self.assertEqual(
            bundle["proof_state"]["state"],
            "VERIFIED",
        )
        self.assertTrue(
            bundle["proof_state"][
                "external_side_effect_executed"
            ]
        )
        self.assertEqual(
            bundle["deployment_receipt"]["status"],
            "DEPLOYED",
        )
        self.assertEqual(
            bundle["deployment_receipt"]["deployment_id"],
            "preview-ref-ade-preview",
        )
        self.assertEqual(
            bundle["external_provenance"]["target_ci_run_id"],
            36882390659,
        )
        self.assertTrue(
            bundle["external_provenance"]["post_dispatch_ci"]
        )
        self.assertFalse(
            bundle["external_provenance"]["force_update_used"]
        )
        self.assertEqual(
            bundle["post_verification_report"]["report"][
                "disposition"
            ],
            "VERIFIED",
        )
        self.assertTrue(
            bundle["post_verification_finalization"][
                "promotion_verified"
            ]
        )
        self.assertTrue(
            bundle["campaign_evidence"][
                "promotion_verified"
            ]
        )
        self.assertFalse(
            bundle["campaign_evidence"][
                "auto_promoted_next_environment"
            ]
        )
        self.assertEqual(
            bundle["mission_control"]["promotion_state"],
            "VERIFIED",
        )
        self.assertEqual(
            bundle["mission_control"]["verification_state"],
            "VERIFIED",
        )

    def test_different_preview_ref_sha_fails_closed(self) -> None:
        module = load_module()

        def fake_api(url: str):
            if "/git/ref/heads/ade-preview" in url:
                return preview_ref("f" * 40)
            if "/actions/runs?" in url:
                return {"workflow_runs": []}
            raise AssertionError(f"unexpected URL: {url}")

        with self.assertRaisesRegex(
            ValueError,
            "preview ref does not bind exact source SHA",
        ):
            module.build_final_proof(api_get=fake_api)

    def test_failed_or_wrong_branch_ci_is_not_runtime_success(self) -> None:
        module = load_module()

        def fake_api(url: str):
            if "/git/ref/heads/ade-preview" in url:
                return preview_ref(module.SOURCE_SHA)
            if "/actions/runs?" in url:
                return {
                    "workflow_runs": [
                        run(
                            run_id=10,
                            created_at="2026-10-01T15:12:09Z",
                            conclusion="failure",
                        ),
                        run(
                            run_id=11,
                            created_at="2026-10-01T15:12:10Z",
                            head_branch="main",
                        ),
                    ]
                }
            raise AssertionError(f"unexpected URL: {url}")

        with self.assertRaisesRegex(
            ValueError,
            "no successful post-dispatch preview CI run",
        ):
            module.build_final_proof(api_get=fake_api)


if __name__ == "__main__":
    unittest.main()

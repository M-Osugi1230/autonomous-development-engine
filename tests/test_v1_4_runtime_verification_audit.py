from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.v1_4_runtime_verification_audit import audit


SHA_A = "a" * 40
SHA_B = "b" * 40
HASH_A = "1" * 64
HASH_B = "2" * 64
HASH_C = "3" * 64
HASH_D = "4" * 64


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _evidence() -> dict:
    return {
        "schema_version": 1,
        "version": "v1.4",
        "request_id": "v1.4-runtime-verification-proof-003",
        "campaign_id": "v1.4-runtime-verification-campaign-003",
        "target_repository": "M-Osugi1230/one-minute-thought-experiments",
        "human_authored_per_task_work_items": False,
        "execution_provenance_clean": True,
        "task": {
            "task_id": "v14rv3-001",
            "planner_workflow_run": 101,
            "zero_touch_run": 102,
            "jules_cycle_run": 103,
            "pull_request": 15,
            "ci_run": 104,
            "remote_gate_run": 105,
            "remote_monitor_run": 106,
            "head_sha": SHA_A,
            "merge_commit": SHA_B,
        },
        "runtime_verification": {
            "workflow_run": 107,
            "trigger_source": "repository_dispatch",
            "manual_workflow_dispatch": False,
            "workspace_source_sha": SHA_B,
            "dependency_fingerprint": HASH_D,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "contract": {
                "schema_version": 1,
                "verification_id": "rv-" + SHA_B,
                "target_repository": "M-Osugi1230/one-minute-thought-experiments",
                "source_sha": SHA_B,
                "environment": "repository",
                "required_probe_ids": [
                    "offline-cli-smoke",
                    "production-import-smoke",
                ],
                "max_attempts": 2,
                "timeout_seconds": 300,
            },
            "receipt": {
                "schema_version": 1,
                "verification_id": "rv-" + SHA_B,
                "task_id": "v14rv3-001",
                "target_repository": "M-Osugi1230/one-minute-thought-experiments",
                "source_sha": SHA_B,
                "contract_fingerprint": HASH_A,
                "registry_fingerprint": HASH_B,
                "policy_fingerprint": HASH_C,
                "status": "VERIFIED",
                "dispatch_count": 1,
            },
            "target": {
                "schema_version": 1,
                "evidence": {
                    "schema_version": 1,
                    "target_id": "repository-runtime",
                    "kind": "repository",
                    "target_repository": "M-Osugi1230/one-minute-thought-experiments",
                    "environment": "repository",
                    "source_sha": SHA_B,
                    "observed_at": "2026-09-30T00:00:00+00:00",
                    "provenance_id": "trusted-merge-sha-v1",
                    "deployment_id": None,
                },
            },
            "report": {
                "schema_version": 1,
                "verification_id": "rv-" + SHA_B,
                "contract_fingerprint": HASH_A,
                "source_sha": SHA_B,
                "disposition": "VERIFIED",
                "results": [
                    {
                        "schema_version": 1,
                        "probe_id": "offline-cli-smoke",
                        "status": "PASS",
                        "source_sha": SHA_B,
                        "attempt": 1,
                        "detail_code": "offline-cli-pass",
                    },
                    {
                        "schema_version": 1,
                        "probe_id": "production-import-smoke",
                        "status": "PASS",
                        "source_sha": SHA_B,
                        "attempt": 1,
                        "detail_code": "production-import-pass",
                    },
                ],
                "missing_probe_ids": [],
            },
        },
        "manual_campaign_progress_after_goal_submission": False,
        "terminal_snapshot": {
            "campaign": {
                "campaign_id": "v1.4-runtime-verification-campaign-003",
                "status": "COMPLETED",
                "task_ids": ["v14rv3-001"],
                "completed_task_ids": ["v14rv3-001"],
            },
            "state": {
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
            },
        },
    }


class V14RuntimeVerificationAuditTests(unittest.TestCase):
    def _fixture(self, root: Path, evidence: dict) -> None:
        _write(
            root,
            ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json",
            json.dumps(evidence, indent=2) + "\n",
        )
        _write(
            root,
            ".github/workflows/ci.yml",
            "\n".join(
                [
                    "Zero-Touch Start proof",
                    "Execution lease duplicate-dispatch proof",
                    "Autonomous Planner proof",
                    "Repository Intelligence proof",
                    "Runtime Verification post-merge trigger proof",
                    "Runtime Verification bounded execution proof",
                    "Runtime Verification real repository probe proof",
                    "Runtime Verification target adapter proof",
                    "Runtime Verification failure containment proof",
                    "Remote Repository Loop proof",
                    "Human decision boundary proof",
                ]
            ),
        )

    def test_complete_verified_evidence_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root, _evidence())
            result = audit(root)
            self.assertTrue(result["v1_4_runtime_verification_graduated"], result)
            self.assertTrue(all(result["checks"].values()))

    def test_unclean_execution_provenance_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["execution_provenance_clean"] = False
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_4_runtime_verification_graduated"])
            self.assertFalse(result["checks"]["execution_provenance_clean"])

    def test_failed_runtime_receipt_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["runtime_verification"]["receipt"]["status"] = "HUMAN_WAIT"
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_4_runtime_verification_graduated"])
            self.assertFalse(result["checks"]["receipt_verified"])

    def test_ci_success_without_runtime_pass_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["runtime_verification"]["report"]["results"][0]["status"] = "FAIL"
            evidence["runtime_verification"]["report"]["disposition"] = "FAILED"
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_4_runtime_verification_graduated"])
            self.assertFalse(result["checks"]["real_runtime_report"])

    def test_runtime_source_drift_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["runtime_verification"]["contract"]["source_sha"] = SHA_A
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_4_runtime_verification_graduated"])
            self.assertFalse(result["checks"]["contract_exact_merge_sha"])

    def test_manual_campaign_progress_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["manual_campaign_progress_after_goal_submission"] = True
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_4_runtime_verification_graduated"])
            self.assertFalse(result["checks"]["no_manual_campaign_progress"])


if __name__ == "__main__":
    unittest.main()

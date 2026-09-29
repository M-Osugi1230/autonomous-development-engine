from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.v1_2_autonomous_planner_audit import audit


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _evidence() -> dict:
    task_ids = ["v12ext5-001", "v12ext5-002"]
    return {
        "schema_version": 1,
        "version": "v1.2",
        "request_id": "v1.2-external-goal-proof-005",
        "campaign_id": "v1.2-external-goal-campaign-005",
        "target_repository": "M-Osugi1230/one-minute-thought-experiments",
        "human_authored_per_task_work_items": False,
        "target_quality_gate": {
            "baseline_sha": SHA_A,
            "baseline_ci_run": 100,
            "runtime_source_hygiene": True,
            "clean_production_import_smoke": True,
        },
        "accepted_plan_fingerprint": "fingerprint-005",
        "planner": {
            "provider": "jules",
            "workflow_run": 101,
            "source_sha": SHA_A,
            "planning_only": True,
            "plan_approved": False,
            "provider_execution_boundary_crossed": False,
            "proposal_mode": "derived-plan-steps",
            "task_count": 2,
        },
        "initial_start": {
            "workflow_run": 102,
            "trigger_source": "repository_dispatch",
            "manual_workflow_dispatch": False,
        },
        "quota_resume": {
            "observed": False,
            "resume_mode": "not-needed",
        },
        "tasks": [
            {
                "task_id": "v12ext5-001",
                "jules_cycle_run": 104,
                "pull_request": 9,
                "ci_run": 105,
                "remote_gate_run": 106,
                "remote_monitor_run": 107,
                "head_sha": SHA_B,
                "merge_commit": SHA_C,
            },
            {
                "task_id": "v12ext5-002",
                "jules_cycle_run": 108,
                "pull_request": 10,
                "ci_run": 109,
                "remote_gate_run": 110,
                "remote_monitor_run": 111,
                "head_sha": SHA_C,
                "merge_commit": SHA_D,
            },
        ],
        "manual_campaign_progress_after_goal_submission": False,
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "terminal_snapshot": {
            "source_sha": SHA_D,
            "accepted_plan": {
                "status": "ACCEPTED",
                "fingerprint": "fingerprint-005",
            },
            "campaign": {
                "campaign_id": "v1.2-external-goal-campaign-005",
                "status": "COMPLETED",
                "task_ids": task_ids,
                "completed_task_ids": task_ids,
            },
            "task_graph": [
                {"task_id": "v12ext5-001", "status": "COMPLETED"},
                {"task_id": "v12ext5-002", "status": "COMPLETED"},
            ],
            "state": {
                "current_task_id": None,
                "failed_task_ids": [],
                "completed_campaign_task_ids": task_ids,
            },
            "remote_execution_receipt": {
                "schema_version": 1,
                "status": "MERGED",
                "task_id": "v12ext5-002",
            },
        },
    }


class V12AutonomousPlannerAuditTests(unittest.TestCase):
    def _fixture(self, root: Path, evidence: dict) -> None:
        _write(
            root,
            ".autodev/campaign-evidence/v1.2-autonomous-planner-proof-005.json",
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
                    "Jules Planner Adapter proof",
                    "Autonomous Planner activation proof",
                    "Autonomous Planner capacity retry proof",
                    "Remote Repository Loop proof",
                    "Mission Control observability proof",
                    "Autonomous recovery fault proof",
                    "Checkpoint restart proof",
                    "Human decision boundary proof",
                ]
            ),
        )
        _write(
            root,
            ".github/workflows/zero-touch-start.yml",
            "repository_dispatch:\n  types:\n    - ade_zero_touch_start\n",
        )
        _write(
            root,
            ".github/workflows/remote-pr-monitor.yml",
            "repository_dispatch:\n  types:\n    - ade_remote_pr_monitor\n",
        )
        _write(
            root,
            ".github/workflows/ade-resume.yml",
            'schedule:\n  - cron: "*/15 * * * *"\n',
        )

        _write(
            root,
            ".github/workflows/autonomous-planner.yml",
            "repository_dispatch:\n  types:\n    - ade_planner_retry\n",
        )
        _write(
            root,
            ".github/workflows/autonomous-planner-retry.yml",
            (
                "repository_dispatch:\n"
                "  types:\n"
                "    - ade_planner_retry_arm\n"
                "concurrency:\n"
                "  cancel-in-progress: true\n"
                "jobs:\n"
                "  retry:\n"
                "    steps:\n"
                "      - run: sleep 900\n"
            ),
        )

    def test_complete_terminal_evidence_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root, _evidence())
            result = audit(root)
            self.assertTrue(result["v1_2_autonomous_planner_graduated"], result)
            self.assertEqual(result["missing_proofs"], [])
            self.assertTrue(all(result["checks"].values()))

    def test_missing_planner_retry_chain_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root, _evidence())
            _write(
                root,
                ".github/workflows/autonomous-planner-retry.yml",
                "repository_dispatch:\n  types:\n    - ade_planner_retry_arm\n",
            )
            result = audit(root)
            self.assertFalse(result["v1_2_autonomous_planner_graduated"])
            self.assertFalse(result["checks"]["planner_capacity_retry_chain"])

    def test_missing_target_quality_gate_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["target_quality_gate"]["clean_production_import_smoke"] = False
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_2_autonomous_planner_graduated"])
            self.assertFalse(result["checks"]["target_quality_gate"])

    def test_nonterminal_campaign_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["terminal_snapshot"]["campaign"]["status"] = "RUNNING"
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_2_autonomous_planner_graduated"])
            self.assertFalse(result["checks"]["campaign_completed"])

    def test_observed_quota_requires_automatic_safe_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["quota_resume"] = {
                "observed": True,
                "task_id": "v12ext5-002",
                "resume_after": "2026-09-29T12:25:49+00:00",
                "manual_resume": True,
                "resume_run": 103,
                "external_target_preserved": True,
                "execution_lease_reclaimed": True,
            }
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_2_autonomous_planner_graduated"])
            self.assertFalse(result["checks"]["quota_resume_safe"])

            evidence["quota_resume"]["manual_resume"] = False
            self._fixture(root, evidence)
            result = audit(root)
            self.assertTrue(result["checks"]["quota_resume_safe"])

    def test_planner_execution_boundary_crossing_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["planner"]["provider_execution_boundary_crossed"] = True
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_2_autonomous_planner_graduated"])
            self.assertFalse(result["checks"]["planner_boundary"])


if __name__ == "__main__":
    unittest.main()

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
    task_ids = ["v12ext4-001", "v12ext4-002"]
    return {
        "schema_version": 1,
        "version": "v1.2",
        "request_id": "v1.2-external-goal-proof-004",
        "campaign_id": "v1.2-external-goal-campaign-004",
        "target_repository": "M-Osugi1230/one-minute-thought-experiments",
        "human_authored_per_task_work_items": False,
        "accepted_plan_fingerprint": "fingerprint-004",
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
            "task_id": "v12ext4-002",
            "paused": True,
            "resume_after": "2026-09-29T12:25:49+00:00",
            "manual_resume": False,
            "resume_run": 103,
            "external_target_preserved": True,
            "execution_lease_reclaimed": True,
        },
        "tasks": [
            {
                "task_id": "v12ext4-001",
                "jules_cycle_run": 104,
                "pull_request": 9,
                "ci_run": 105,
                "remote_gate_run": 106,
                "remote_monitor_run": 107,
                "head_sha": SHA_B,
                "merge_commit": SHA_C,
            },
            {
                "task_id": "v12ext4-002",
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
                "fingerprint": "fingerprint-004",
            },
            "campaign": {
                "campaign_id": "v1.2-external-goal-campaign-004",
                "status": "COMPLETED",
                "task_ids": task_ids,
                "completed_task_ids": task_ids,
            },
            "task_graph": [
                {"task_id": "v12ext4-001", "status": "COMPLETED"},
                {"task_id": "v12ext4-002", "status": "COMPLETED"},
            ],
            "state": {
                "current_task_id": None,
                "failed_task_ids": [],
                "completed_campaign_task_ids": task_ids,
            },
            "remote_execution_receipt": {
                "schema_version": 1,
                "status": "MERGED",
                "task_id": "v12ext4-002",
            },
        },
    }


class V12AutonomousPlannerAuditTests(unittest.TestCase):
    def _fixture(self, root: Path, evidence: dict) -> None:
        _write(
            root,
            ".autodev/campaign-evidence/v1.2-autonomous-planner-proof-004.json",
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

    def test_complete_terminal_evidence_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root, _evidence())
            result = audit(root)
            self.assertTrue(result["v1_2_autonomous_planner_graduated"], result)
            self.assertEqual(result["missing_proofs"], [])
            self.assertTrue(all(result["checks"].values()))

    def test_nonterminal_campaign_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["terminal_snapshot"]["campaign"]["status"] = "RUNNING"
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_2_autonomous_planner_graduated"])
            self.assertFalse(result["checks"]["campaign_completed"])

    def test_manual_resume_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["quota_resume"]["manual_resume"] = True
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_2_autonomous_planner_graduated"])
            self.assertFalse(result["checks"]["automatic_quota_resume"])

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

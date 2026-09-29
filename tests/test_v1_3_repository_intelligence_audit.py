from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.v1_3_repository_intelligence_audit import audit


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
HASH_A = "1" * 64
HASH_B = "2" * 64
HASH_C = "3" * 64
HASH_D = "4" * 64
HASH_E = "5" * 64


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _evidence() -> dict:
    task_ids = ["v13ri1-001", "v13ri1-002"]
    return {
        "schema_version": 1,
        "version": "v1.3",
        "request_id": "v1.3-repository-intelligence-proof-001",
        "campaign_id": "v1.3-repository-intelligence-campaign-001",
        "target_repository": "M-Osugi1230/one-minute-thought-experiments",
        "human_authored_per_task_work_items": False,
        "accepted_plan_fingerprint": "accepted-v13-proof",
        "repository_intelligence": {
            "source_sha": SHA_A,
            "snapshot_fingerprint": HASH_A,
            "context_fingerprint": HASH_B,
            "content_summary_fingerprint": HASH_C,
            "relationship_graph_fingerprint": HASH_D,
            "impact_analysis_fingerprint": HASH_E,
            "raw_source_persisted": False,
            "impact_analysis_advisory_only": True,
            "path_grounding_enforced": True,
            "grounded_task_paths": [
                {
                    "task_id": "v13ri1-001",
                    "path": "src/thought_pipeline/models.py",
                    "exists_in_snapshot": True,
                    "declared_new": False,
                },
                {
                    "task_id": "v13ri1-002",
                    "path": "tests/test_models.py",
                    "exists_in_snapshot": True,
                    "declared_new": False,
                },
            ],
        },
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
        "tasks": [
            {
                "task_id": "v13ri1-001",
                "jules_cycle_run": 103,
                "pull_request": 13,
                "ci_run": 104,
                "remote_gate_run": 105,
                "remote_monitor_run": 106,
                "head_sha": SHA_B,
                "merge_commit": SHA_C,
            },
            {
                "task_id": "v13ri1-002",
                "jules_cycle_run": 107,
                "pull_request": 14,
                "ci_run": 108,
                "remote_gate_run": 109,
                "remote_monitor_run": 110,
                "head_sha": SHA_C,
                "merge_commit": SHA_B,
            },
        ],
        "manual_campaign_progress_after_goal_submission": False,
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "terminal_snapshot": {
            "source_sha": SHA_C,
            "accepted_plan": {
                "status": "ACCEPTED",
                "fingerprint": "accepted-v13-proof",
            },
            "campaign": {
                "campaign_id": "v1.3-repository-intelligence-campaign-001",
                "status": "COMPLETED",
                "task_ids": task_ids,
                "completed_task_ids": task_ids,
            },
            "task_graph": [
                {"task_id": "v13ri1-001", "status": "COMPLETED"},
                {"task_id": "v13ri1-002", "status": "COMPLETED"},
            ],
            "state": {
                "current_task_id": None,
                "failed_task_ids": [],
                "completed_campaign_task_ids": task_ids,
            },
            "remote_execution_receipt": {
                "schema_version": 1,
                "status": "MERGED",
                "task_id": "v13ri1-002",
            },
        },
    }


class V13RepositoryIntelligenceAuditTests(unittest.TestCase):
    def _fixture(self, root: Path, evidence: dict) -> None:
        _write(
            root,
            ".autodev/campaign-evidence/v1.3-repository-intelligence-proof-001.json",
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
                    "Autonomous Planner activation proof",
                    "Autonomous Planner capacity retry proof",
                    "Repository Intelligence proof",
                    "Remote Repository Loop proof",
                    "Mission Control observability proof",
                    "Autonomous recovery fault proof",
                    "Checkpoint restart proof",
                    "Human decision boundary proof",
                ]
            ),
        )

    def test_complete_terminal_evidence_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root, _evidence())
            result = audit(root)
            self.assertTrue(result["v1_3_repository_intelligence_graduated"], result)
            self.assertTrue(all(result["checks"].values()))

    def test_unknown_task_path_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["repository_intelligence"]["grounded_task_paths"][0][
                "exists_in_snapshot"
            ] = False
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_3_repository_intelligence_graduated"])
            self.assertFalse(result["checks"]["path_grounding"])

    def test_persisted_raw_source_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["repository_intelligence"]["raw_source_persisted"] = True
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_3_repository_intelligence_graduated"])
            self.assertFalse(result["checks"]["bounded_content_intelligence"])

    def test_nonterminal_campaign_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["terminal_snapshot"]["campaign"]["status"] = "RUNNING"
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_3_repository_intelligence_graduated"])
            self.assertFalse(result["checks"]["campaign_completed"])

    def test_manual_campaign_progress_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["manual_campaign_progress_after_goal_submission"] = True
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_3_repository_intelligence_graduated"])
            self.assertFalse(result["checks"]["no_manual_campaign_progress"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from ade.development_memory import DevelopmentMemoryError
from ade.development_memory_planning import build_planning_memory_bundle


MERGE_SHA = "a" * 40
NEW_SHA = "b" * 40


def proof() -> dict:
    return {
        "schema_version": 1,
        "campaign_id": "campaign-001",
        "target_repository": "owner/target",
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "task": {
            "task_id": "task-001",
            "merge_commit": MERGE_SHA,
        },
        "runtime_verification": {
            "workspace_source_sha": MERGE_SHA,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "contract": {
                "source_sha": MERGE_SHA,
                "target_repository": "owner/target",
                "required_probe_ids": ["offline-cli-smoke", "production-import-smoke"],
            },
            "receipt": {
                "status": "VERIFIED",
                "source_sha": MERGE_SHA,
                "target_repository": "owner/target",
                "task_id": "task-001",
            },
            "report": {
                "disposition": "VERIFIED",
                "source_sha": MERGE_SHA,
                "results": [
                    {
                        "probe_id": "offline-cli-smoke",
                        "status": "PASS",
                        "source_sha": MERGE_SHA,
                    },
                    {
                        "probe_id": "production-import-smoke",
                        "status": "PASS",
                        "source_sha": MERGE_SHA,
                    },
                ],
            },
        },
        "terminal_snapshot": {
            "campaign": {
                "campaign_id": "campaign-001",
                "status": "COMPLETED",
                "task_ids": ["task-001"],
                "completed_task_ids": ["task-001"],
            },
            "state": {
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
            },
        },
    }


class DevelopmentMemoryPlanningTests(unittest.TestCase):
    def test_current_clean_proof_becomes_bounded_advisory_planner_memory(self) -> None:
        bundle = build_planning_memory_bundle(
            evidence_path=".autodev/campaign-evidence/proof.json",
            evidence_payload=proof(),
            repository="owner/target",
            current_source_sha=MERGE_SHA,
        )
        self.assertEqual(bundle.extracted_record_count, 2)
        self.assertEqual(bundle.retrieved_record_count, 2)
        self.assertTrue(bundle.evidence_dict()["used"])
        self.assertEqual(bundle.context.payload["authority"], "advisory-data-only")
        self.assertFalse(bundle.context.payload["execution_authority"])
        self.assertFalse(bundle.context.payload["memory_may_expand_scope"])
        self.assertFalse(bundle.context.payload["memory_may_override_acceptance"])
        self.assertLessEqual(len(bundle.context.serialized), 4000)

    def test_source_advance_makes_verified_memories_stale_and_unretrieved(self) -> None:
        bundle = build_planning_memory_bundle(
            evidence_path=".autodev/campaign-evidence/proof.json",
            evidence_payload=proof(),
            repository="owner/target",
            current_source_sha=NEW_SHA,
        )
        self.assertEqual(bundle.extracted_record_count, 2)
        self.assertEqual(bundle.retrieved_record_count, 0)
        self.assertFalse(bundle.evidence_dict()["used"])
        self.assertEqual(bundle.context.payload["records"], [])

    def test_repository_mismatch_fails_closed(self) -> None:
        with self.assertRaises(DevelopmentMemoryError):
            build_planning_memory_bundle(
                evidence_path=".autodev/campaign-evidence/proof.json",
                evidence_payload=proof(),
                repository="other/target",
                current_source_sha=MERGE_SHA,
            )


if __name__ == "__main__":
    unittest.main()

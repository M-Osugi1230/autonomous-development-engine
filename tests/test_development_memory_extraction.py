from __future__ import annotations

import copy
import unittest

from ade.development_memory import DevelopmentMemoryError, MemoryKind
from ade.development_memory_extraction import (
    evidence_fingerprint,
    extract_completed_campaign_memory,
    extract_recovery_memory,
    extract_resolved_decision_memory,
    extract_trusted_memories,
    extract_verified_runtime_memory,
)


MERGE_SHA = "a" * 40
SOURCE_SHA = "b" * 40


def campaign_evidence() -> dict:
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
                "required_probe_ids": ["probe-a", "probe-b"],
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
                    {"probe_id": "probe-a", "status": "PASS", "source_sha": MERGE_SHA},
                    {"probe_id": "probe-b", "status": "PASS", "source_sha": MERGE_SHA},
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


def recovery_evidence() -> dict:
    return {
        "schema_version": 1,
        "task_id": "task-001",
        "failure": "CI_FAILURE",
        "action": "REPAIR",
        "fingerprint": "c" * 64,
        "progress": {
            "retries": 0,
            "repairs": 1,
            "rebases": 0,
            "replans": 0,
            "repeated_failures": 1,
        },
    }


def decision_store() -> dict:
    return {
        "schema_version": 1,
        "decisions": [
            {
                "request": {
                    "decision_id": "decision-001",
                    "question": "Proceed?",
                    "options": ["ACTIVATE", "CANCEL"],
                    "priority": "P0",
                    "blocking_task_id": "task-001",
                    "context": {},
                },
                "status": "RESOLVED",
                "response": {
                    "decision_id": "decision-001",
                    "text": "ACTIVATE",
                    "selected_option": "ACTIVATE",
                },
            }
        ],
    }


class DevelopmentMemoryExtractionTests(unittest.TestCase):
    def test_campaign_and_runtime_extraction_are_deterministic_and_fixed_text(self) -> None:
        payload = campaign_evidence()
        campaign = extract_completed_campaign_memory(
            evidence_path=".autodev/campaign-evidence/proof.json",
            evidence_payload=payload,
        )
        runtime = extract_verified_runtime_memory(
            evidence_path=".autodev/campaign-evidence/proof.json",
            evidence_payload=payload,
        )
        self.assertEqual(campaign.kind, MemoryKind.VERIFIED_OUTCOME)
        self.assertEqual(runtime.kind, MemoryKind.VERIFIED_OUTCOME)
        self.assertEqual(campaign.source_sha, MERGE_SHA)
        self.assertEqual(runtime.source_sha, MERGE_SHA)
        self.assertEqual(
            campaign.evidence_fingerprints,
            (evidence_fingerprint(payload),),
        )
        self.assertNotIn("Proceed?", campaign.statement)
        self.assertIn("exact trusted merge SHA", runtime.statement)

        again = extract_verified_runtime_memory(
            evidence_path=".autodev/campaign-evidence/proof.json",
            evidence_payload=copy.deepcopy(payload),
        )
        self.assertEqual(runtime, again)

    def test_campaign_extraction_rejects_non_terminal_or_failed_state(self) -> None:
        payload = campaign_evidence()
        payload["failed_tasks"] = 1
        with self.assertRaisesRegex(DevelopmentMemoryError, "failed tasks"):
            extract_completed_campaign_memory(
                evidence_path=".autodev/campaign-evidence/proof.json",
                evidence_payload=payload,
            )

        payload = campaign_evidence()
        payload["terminal_snapshot"]["state"]["status"] = "HUMAN_WAIT"
        with self.assertRaisesRegex(DevelopmentMemoryError, "not READY"):
            extract_completed_campaign_memory(
                evidence_path=".autodev/campaign-evidence/proof.json",
                evidence_payload=payload,
            )

    def test_runtime_extraction_rejects_source_drift_failure_and_recovery(self) -> None:
        payload = campaign_evidence()
        payload["runtime_verification"]["receipt"]["source_sha"] = SOURCE_SHA
        with self.assertRaisesRegex(DevelopmentMemoryError, "SHA binding"):
            extract_verified_runtime_memory(
                evidence_path=".autodev/campaign-evidence/proof.json",
                evidence_payload=payload,
            )

        payload = campaign_evidence()
        payload["runtime_verification"]["report"]["results"][0]["status"] = "FAIL"
        with self.assertRaisesRegex(DevelopmentMemoryError, "non-PASS"):
            extract_verified_runtime_memory(
                evidence_path=".autodev/campaign-evidence/proof.json",
                evidence_payload=payload,
            )

        payload = campaign_evidence()
        payload["runtime_verification"]["recovery_triggered"] = True
        with self.assertRaisesRegex(DevelopmentMemoryError, "used recovery"):
            extract_verified_runtime_memory(
                evidence_path=".autodev/campaign-evidence/proof.json",
                evidence_payload=payload,
            )

    def test_recovery_memory_uses_only_structured_failure_and_action(self) -> None:
        record = extract_recovery_memory(
            evidence_path=".autodev/runtime/recovery.json",
            recovery_payload=recovery_evidence(),
            repository="owner/target",
            source_sha=SOURCE_SHA,
        )
        self.assertEqual(record.kind, MemoryKind.REMEDIATION)
        self.assertEqual(record.task_id, "task-001")
        self.assertEqual(
            record.statement,
            "Trusted recovery classified CI_FAILURE and selected REPAIR under bounded recovery policy.",
        )

        failed = recovery_evidence()
        failed["action"] = "HUMAN_WAIT"
        human_wait = extract_recovery_memory(
            evidence_path=".autodev/runtime/recovery.json",
            recovery_payload=failed,
            repository="owner/target",
            source_sha=SOURCE_SHA,
        )
        self.assertEqual(human_wait.kind, MemoryKind.FAILURE)

    def test_resolved_decision_uses_selected_option_but_not_free_text(self) -> None:
        record = extract_resolved_decision_memory(
            evidence_path=".autodev/decisions.json",
            decision_store_payload=decision_store(),
            decision_id="decision-001",
            repository="owner/target",
            source_sha=SOURCE_SHA,
        )
        self.assertEqual(record.kind, MemoryKind.DECISION)
        self.assertIn("selected option ACTIVATE", record.statement)
        self.assertNotIn("Proceed?", record.statement)

        free_text = decision_store()
        free_text["decisions"][0]["response"]["selected_option"] = None
        free_text["decisions"][0]["response"]["text"] = "free form answer"
        with self.assertRaisesRegex(DevelopmentMemoryError, "free-text"):
            extract_resolved_decision_memory(
                evidence_path=".autodev/decisions.json",
                decision_store_payload=free_text,
                decision_id="decision-001",
                repository="owner/target",
                source_sha=SOURCE_SHA,
            )

    def test_combined_extraction_is_complete_and_input_bounded(self) -> None:
        records = extract_trusted_memories(
            campaign_evidence_path=".autodev/campaign-evidence/proof.json",
            campaign_evidence_payload=campaign_evidence(),
            recovery_evidence_path=".autodev/runtime/recovery.json",
            recovery_payload=recovery_evidence(),
            recovery_repository="owner/target",
            recovery_source_sha=SOURCE_SHA,
            decision_evidence_path=".autodev/decisions.json",
            decision_store_payload=decision_store(),
            decision_id="decision-001",
            decision_repository="owner/target",
            decision_source_sha=SOURCE_SHA,
        )
        self.assertEqual(len(records), 4)
        self.assertEqual(
            {record.kind for record in records},
            {
                MemoryKind.VERIFIED_OUTCOME,
                MemoryKind.REMEDIATION,
                MemoryKind.DECISION,
            },
        )

        with self.assertRaisesRegex(DevelopmentMemoryError, "inputs must be complete"):
            extract_trusted_memories(
                campaign_evidence_path=".autodev/campaign-evidence/proof.json",
                campaign_evidence_payload=campaign_evidence(),
                recovery_evidence_path=".autodev/runtime/recovery.json",
            )


if __name__ == "__main__":
    unittest.main()

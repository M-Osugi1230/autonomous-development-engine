from __future__ import annotations

import unittest

from ade.development_memory_feedback import build_verified_runtime_feedback_record
from ade.development_memory_store import DevelopmentMemoryStore, merge_memory_records
from ade.development_memory_successor import (
    BOOTSTRAP_EVIDENCE_PATH,
    PROOF002_REQUEST_ID,
    build_bootstrap_evidence,
    evaluate_v1_5_bootstrap_successor,
    proof002_planning_goal,
)
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


SHA = "a" * 40
HASH_B = "2" * 64
HASH_C = "3" * 64
TARGET = "M-Osugi1230/one-minute-thought-experiments"
CONTRACT_PATH = ".autodev/runtime-verification/v15mem1-001/contract.json"
RECEIPT_PATH = ".autodev/runtime-verification/v15mem1-001/receipt.json"
REPORT_PATH = ".autodev/runtime-verification/v15mem1-001/report.json"


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + SHA,
        target_repository=TARGET,
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )


def receipt() -> RuntimeVerificationReceipt:
    c = contract()
    return RuntimeVerificationReceipt(
        verification_id=c.verification_id,
        task_id="v15mem1-001",
        target_repository=TARGET,
        source_sha=SHA,
        contract_fingerprint=c.fingerprint(),
        registry_fingerprint=HASH_B,
        policy_fingerprint=HASH_C,
        status="VERIFIED",
        dispatch_count=1,
    )


def report():
    c = contract()
    return evaluate_runtime_verification(
        c,
        (
            RuntimeProbeResult(
                probe_id="offline-cli-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
                attempt=1,
                detail_code="offline-cli-pass",
            ),
            RuntimeProbeResult(
                probe_id="production-import-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
                attempt=1,
                detail_code="production-import-pass",
            ),
        ),
    )


def report_wrapper() -> dict:
    r = report()
    return {
        "schema_version": 1,
        "report": r.canonical_dict(),
        "report_fingerprint": r.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }


def planner_evidence() -> dict:
    return {
        "schema_version": 1,
        "campaign_id": "v1.5-development-memory-campaign-001",
        "request": {
            "request_id": "v1.5-development-memory-proof-001",
        },
        "planning_only": True,
        "development_memory": {
            "schema_version": 1,
            "used": True,
            "authority": "advisory-data-only",
            "execution_authority": False,
            "memory_may_expand_scope": False,
            "memory_may_override_acceptance": False,
            "source_evidence_path": (
                ".autodev/campaign-evidence/"
                "v1.4-runtime-verification-proof-003.json"
            ),
            "source_evidence_fingerprint": "4" * 64,
            "memory_ids": ["mem-" + "1" * 24, "mem-" + "2" * 24],
            "current_source_sha": "b" * 40,
            "repository": TARGET,
        },
    }


def state() -> dict:
    return {
        "schema_version": 1,
        "project_id": "autonomous-development-engine",
        "status": "READY",
        "current_task_id": None,
        "failed_task_ids": [],
        "metadata": {
            "phase": "v1.5-development-memory",
            "planning_request_id": "v1.5-development-memory-proof-001",
        },
    }


def campaign() -> dict:
    return {
        "schema_version": 1,
        "campaign_id": "v1.5-development-memory-campaign-001",
        "status": "COMPLETED",
        "task_ids": ["v15mem1-001"],
        "completed_task_ids": ["v15mem1-001"],
    }


def remote() -> dict:
    return {
        "schema_version": 1,
        "status": "MERGED",
        "task_id": "v15mem1-001",
        "target_repository": TARGET,
        "pull_request_url": (
            "https://github.com/M-Osugi1230/"
            "one-minute-thought-experiments/pull/18"
        ),
    }


def store() -> DevelopmentMemoryStore:
    expected = build_verified_runtime_feedback_record(
        contract=contract(),
        receipt=receipt(),
        report=report(),
        contract_path=CONTRACT_PATH,
        receipt_path=RECEIPT_PATH,
        report_path=REPORT_PATH,
    )
    return merge_memory_records(DevelopmentMemoryStore(), (expected,)).store


class DevelopmentMemorySuccessorTests(unittest.TestCase):
    def test_verified_bootstrap_with_durable_feedback_is_eligible(self) -> None:
        decision = evaluate_v1_5_bootstrap_successor(
            state_payload=state(),
            campaign_payload=campaign(),
            planner_evidence_payload=planner_evidence(),
            remote_execution_payload=remote(),
            contract_payload=contract().canonical_dict(),
            receipt_payload=receipt().canonical_dict(),
            report_wrapper_payload=report_wrapper(),
            memory_store_payload=store().canonical_dict(),
        )
        self.assertTrue(decision.eligible, decision)
        self.assertEqual(decision.source_sha, SHA)
        self.assertIsNotNone(decision.memory_id)
        self.assertEqual(decision.store_record_count, 1)

        evidence = build_bootstrap_evidence(
            decision=decision,
            planner_evidence_payload=planner_evidence(),
            remote_execution_payload=remote(),
            receipt_payload=receipt().canonical_dict(),
        )
        self.assertEqual(evidence["version"], "v1.5-bootstrap")
        self.assertFalse(evidence["graduation_eligible"])
        self.assertEqual(evidence["successor_request_id"], PROOF002_REQUEST_ID)
        self.assertTrue(BOOTSTRAP_EVIDENCE_PATH.endswith("-bootstrap.json"))

        goal = proof002_planning_goal()
        self.assertEqual(goal["request_id"], PROOF002_REQUEST_ID)
        self.assertEqual(goal["allowed_path_prefixes"], ["tests"])
        self.assertIn("U+2002", goal["goal"])
        self.assertIn("U+200A", goal["goal"])

    def test_missing_feedback_record_blocks_successor(self) -> None:
        decision = evaluate_v1_5_bootstrap_successor(
            state_payload=state(),
            campaign_payload=campaign(),
            planner_evidence_payload=planner_evidence(),
            remote_execution_payload=remote(),
            contract_payload=contract().canonical_dict(),
            receipt_payload=receipt().canonical_dict(),
            report_wrapper_payload=report_wrapper(),
            memory_store_payload=DevelopmentMemoryStore().canonical_dict(),
        )
        self.assertFalse(decision.eligible)
        self.assertIn("durable store", decision.reason)

    def test_nonadvisory_memory_or_nonready_state_blocks_successor(self) -> None:
        bad_planner = planner_evidence()
        bad_planner["development_memory"]["execution_authority"] = True
        decision = evaluate_v1_5_bootstrap_successor(
            state_payload=state(),
            campaign_payload=campaign(),
            planner_evidence_payload=bad_planner,
            remote_execution_payload=remote(),
            contract_payload=contract().canonical_dict(),
            receipt_payload=receipt().canonical_dict(),
            report_wrapper_payload=report_wrapper(),
            memory_store_payload=store().canonical_dict(),
        )
        self.assertFalse(decision.eligible)
        self.assertIn("execution authority", decision.reason)

        bad_state = state()
        bad_state["status"] = "HUMAN_WAIT"
        decision = evaluate_v1_5_bootstrap_successor(
            state_payload=bad_state,
            campaign_payload=campaign(),
            planner_evidence_payload=planner_evidence(),
            remote_execution_payload=remote(),
            contract_payload=contract().canonical_dict(),
            receipt_payload=receipt().canonical_dict(),
            report_wrapper_payload=report_wrapper(),
            memory_store_payload=store().canonical_dict(),
        )
        self.assertFalse(decision.eligible)
        self.assertIn("READY", decision.reason)

    def test_runtime_failure_blocks_successor(self) -> None:
        bad_receipt = receipt().canonical_dict()
        bad_receipt["status"] = "FAILED"
        decision = evaluate_v1_5_bootstrap_successor(
            state_payload=state(),
            campaign_payload=campaign(),
            planner_evidence_payload=planner_evidence(),
            remote_execution_payload=remote(),
            contract_payload=contract().canonical_dict(),
            receipt_payload=bad_receipt,
            report_wrapper_payload=report_wrapper(),
            memory_store_payload=store().canonical_dict(),
        )
        self.assertFalse(decision.eligible)
        self.assertIn("VERIFIED", decision.reason)


if __name__ == "__main__":
    unittest.main()

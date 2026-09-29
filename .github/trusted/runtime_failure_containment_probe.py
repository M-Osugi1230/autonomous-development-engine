from __future__ import annotations

import json

from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_recovery import (
    contain_runtime_verification_failure,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


SHA = "a" * 40


def main() -> int:
    contract = RuntimeVerificationContract(
        verification_id="runtime-failure-containment-proof",
        target_repository="example/target",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("runtime-smoke",),
        max_attempts=1,
        timeout_seconds=30,
    )
    report = evaluate_runtime_verification(
        contract,
        [
            RuntimeProbeResult(
                probe_id="runtime-smoke",
                status=RuntimeProbeStatus.FAIL,
                source_sha=SHA,
                detail_code="runtime-failed",
            )
        ],
    )
    receipt = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id="task-final",
        target_repository=contract.target_repository,
        source_sha=contract.source_sha,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="b" * 64,
        policy_fingerprint="c" * 64,
        status="FAILED",
        dispatch_count=1,
    )
    transition = contain_runtime_verification_failure(
        receipt=receipt,
        report=report,
        state_payload={
            "schema_version": 1,
            "status": "READY",
            "current_task_id": None,
            "failed_task_ids": [],
            "metadata": {"target_repository": "example/target"},
        },
        campaign_payload={
            "schema_version": 1,
            "campaign_id": "campaign-proof",
            "goal": "prove containment",
            "task_ids": ["task-final"],
            "completed_task_ids": ["task-final"],
            "status": "COMPLETED",
        },
    )

    assert transition.receipt.status == "HUMAN_WAIT"
    assert transition.state["status"] == "HUMAN_WAIT"
    assert transition.state["current_task_id"] == "task-final"
    assert transition.campaign["status"] == "HUMAN_WAIT"
    assert transition.recovery.action.value == "HUMAN_WAIT"
    assert transition.recovery.failure.value == "RUNTIME_VERIFICATION"
    assert transition.state["metadata"]["next_system_action"] is None
    assert (
        transition.state["metadata"]["next_required_human_action"]
        == "review-runtime-verification-failure"
    )

    print(json.dumps({
        "ok": True,
        "runtime_failure_cannot_remain_campaign_completed": True,
        "runtime_failure_enters_human_wait": True,
        "runtime_receipt_enters_human_wait": True,
        "recovery_evidence_recorded": True,
        "automatic_reexecution_not_granted": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json

from ade.development_memory_feedback import build_verified_runtime_feedback_record
from ade.development_memory_store import DevelopmentMemoryStore, merge_memory_records
from ade.development_memory_successor import evaluate_v1_5_bootstrap_successor
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


SHA = "a" * 40
TARGET = "M-Osugi1230/one-minute-thought-experiments"
CONTRACT_PATH = ".autodev/runtime-verification/v15mem1-001/contract.json"
RECEIPT_PATH = ".autodev/runtime-verification/v15mem1-001/receipt.json"
REPORT_PATH = ".autodev/runtime-verification/v15mem1-001/report.json"


def main() -> int:
    contract = RuntimeVerificationContract(
        verification_id="rv-" + SHA,
        target_repository=TARGET,
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )
    receipt = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id="v15mem1-001",
        target_repository=TARGET,
        source_sha=SHA,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="b" * 64,
        policy_fingerprint="c" * 64,
        status="VERIFIED",
        dispatch_count=1,
    )
    report = evaluate_runtime_verification(
        contract,
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
    wrapper = {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }
    expected = build_verified_runtime_feedback_record(
        contract=contract,
        receipt=receipt,
        report=report,
        contract_path=CONTRACT_PATH,
        receipt_path=RECEIPT_PATH,
        report_path=REPORT_PATH,
    )
    store = merge_memory_records(
        DevelopmentMemoryStore(),
        (expected,),
    ).store

    state = {
        "status": "READY",
        "current_task_id": None,
        "failed_task_ids": [],
        "metadata": {
            "phase": "v1.5-development-memory",
            "planning_request_id": "v1.5-development-memory-proof-001",
        },
    }
    campaign = {
        "campaign_id": "v1.5-development-memory-campaign-001",
        "status": "COMPLETED",
        "task_ids": ["v15mem1-001"],
        "completed_task_ids": ["v15mem1-001"],
    }
    planner = {
        "campaign_id": "v1.5-development-memory-campaign-001",
        "request": {"request_id": "v1.5-development-memory-proof-001"},
        "planning_only": True,
        "development_memory": {
            "used": True,
            "authority": "advisory-data-only",
            "execution_authority": False,
            "memory_may_expand_scope": False,
            "memory_may_override_acceptance": False,
            "source_evidence_path": (
                ".autodev/campaign-evidence/"
                "v1.4-runtime-verification-proof-003.json"
            ),
            "memory_ids": ["mem-source-001"],
            "repository": TARGET,
        },
    }
    remote = {
        "status": "MERGED",
        "task_id": "v15mem1-001",
        "target_repository": TARGET,
        "pull_request_url": (
            "https://github.com/M-Osugi1230/"
            "one-minute-thought-experiments/pull/18"
        ),
    }

    eligible = evaluate_v1_5_bootstrap_successor(
        state_payload=state,
        campaign_payload=campaign,
        planner_evidence_payload=planner,
        remote_execution_payload=remote,
        contract_payload=contract.canonical_dict(),
        receipt_payload=receipt.canonical_dict(),
        report_wrapper_payload=wrapper,
        memory_store_payload=store.canonical_dict(),
    )
    assert eligible.eligible

    missing_store = evaluate_v1_5_bootstrap_successor(
        state_payload=state,
        campaign_payload=campaign,
        planner_evidence_payload=planner,
        remote_execution_payload=remote,
        contract_payload=contract.canonical_dict(),
        receipt_payload=receipt.canonical_dict(),
        report_wrapper_payload=wrapper,
        memory_store_payload=DevelopmentMemoryStore().canonical_dict(),
    )
    assert not missing_store.eligible

    unsafe_planner = dict(planner)
    unsafe_memory = dict(planner["development_memory"])
    unsafe_memory["execution_authority"] = True
    unsafe_planner["development_memory"] = unsafe_memory
    unsafe = evaluate_v1_5_bootstrap_successor(
        state_payload=state,
        campaign_payload=campaign,
        planner_evidence_payload=unsafe_planner,
        remote_execution_payload=remote,
        contract_payload=contract.canonical_dict(),
        receipt_payload=receipt.canonical_dict(),
        report_wrapper_payload=wrapper,
        memory_store_payload=store.canonical_dict(),
    )
    assert not unsafe.eligible

    print(
        json.dumps(
            {
                "ok": True,
                "requires_runtime_verified": True,
                "requires_durable_feedback_record": True,
                "requires_terminal_campaign_and_state": True,
                "rejects_memory_execution_authority": True,
                "successor_memory_id": eligible.memory_id,
                "store_record_count": eligible.store_record_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

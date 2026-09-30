from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_backlog_extraction import (
    extract_recovery_candidate,
    extract_runtime_gap_candidate,
)
from ade.recovery import RecoveryAction, RecoveryFailure, RecoveryProgress
from ade.recovery_runtime import RecoveryRecord
from ade.runtime_verification import RuntimeVerificationContract
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "a" * 40


def main() -> int:
    recovery = RecoveryRecord(
        task_id="task-001",
        failure=RecoveryFailure.CI_FAILURE,
        action=RecoveryAction.REPAIR,
        progress=RecoveryProgress(repairs=1, repeated_failures=1),
        fingerprint="b" * 64,
    )
    recovery_candidate = extract_recovery_candidate(
        evidence_path=".autodev/runtime/recovery.json",
        recovery_payload=recovery.to_dict(),
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        source_phase="v1.6-autonomous-backlog",
    )
    assert recovery_candidate.human_only is False
    assert recovery_candidate.canonical_dict()["execution_authority"] is False

    contract = RuntimeVerificationContract(
        verification_id="rv-" + SOURCE_SHA,
        target_repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke",),
        max_attempts=2,
        timeout_seconds=300,
    )
    receipt = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id="task-002",
        target_repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="c" * 64,
        policy_fingerprint="d" * 64,
        status="HUMAN_WAIT",
        dispatch_count=1,
    )
    runtime_candidate = extract_runtime_gap_candidate(
        contract_path=".autodev/runtime-verification/task-002/contract.json",
        contract_payload=contract.canonical_dict(),
        receipt_path=".autodev/runtime-verification/task-002/receipt.json",
        receipt_payload=receipt.canonical_dict(),
        source_phase="v1.6-autonomous-backlog",
    )
    assert runtime_candidate.human_only is True
    assert runtime_candidate.canonical_dict()["auto_dispatch"] is False

    print(json.dumps({
        "ok": True,
        "recovery_candidate_id": recovery_candidate.candidate_id,
        "runtime_candidate_id": runtime_candidate.candidate_id,
        "controller_owned_templates": True,
        "provider_freeform_surface": False,
        "runtime_failure_human_only": True,
        "execution_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

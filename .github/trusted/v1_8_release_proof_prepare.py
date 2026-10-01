from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.accepted_plan import AcceptedPlan
from ade.campaign import AutonomousCampaign
from ade.decision_store import DecisionStore
from ade.development_memory_feedback import runtime_report_from_wrapper
from ade.human_interrupt import HumanInterruptCoordinator
from ade.release_approval import (
    ReleaseApprovalDisposition,
    build_release_approval_request,
    evaluate_release_approval,
    request_release_approval,
)
from ade.release_candidate import ReleaseEnvironment
from ade.release_observability import build_release_observability_snapshot
from ade.release_policy import plan_release_transition
from ade.release_readiness import derive_release_readiness
from ade.runtime_verification import RuntimeVerificationContract
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


PROOF_ID = "v1.8-autonomous-release-proof-001"
SOURCE_VERSION = "v1.7"
SOURCE_TASK_ID = "v17ma1-001"
TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
TARGET_ENVIRONMENT = ReleaseEnvironment.PREVIEW

FROZEN_ACCEPTED_PLAN_PATH = Path(
    ".autodev/multi-agent/proof/accepted-plan.json"
)
FROZEN_CAMPAIGN_PATH = Path(
    ".autodev/multi-agent/proof/campaign.json"
)
FROZEN_V17_EVIDENCE_PATH = Path(
    ".autodev/campaign-evidence/v1.7-multi-agent-proof-001.json"
)
LIVE_ACCEPTED_PLAN_PATH = Path(".autodev/accepted-plan.json")
LIVE_CAMPAIGN_PATH = Path(".autodev/campaign.json")
RUNTIME_CONTRACT_PATH = Path(
    ".autodev/runtime-verification/v17ma1-001/contract.json"
)
RUNTIME_RECEIPT_PATH = Path(
    ".autodev/runtime-verification/v17ma1-001/receipt.json"
)
RUNTIME_REPORT_PATH = Path(
    ".autodev/runtime-verification/v17ma1-001/report.json"
)
DECISION_STORE_PATH = Path(".autodev/decisions.json")
PROOF_DIR = Path(".autodev/release/proof")
MISSION_CONTROL_PATH = Path(".autodev/release/mission-control.json")
RESULT_PATH = Path(
    ".autodev/runtime/v1-8-release-proof-prepare-result.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        existing = _load_json(path)
        if existing != payload:
            raise ValueError(
                f"immutable v1.8 release proof artifact drift: {path}"
            )
        return
    _write_json(path, payload)


def _validate_source_evidence(
    *,
    frozen_accepted_payload: dict[str, Any],
    frozen_campaign_payload: dict[str, Any],
    v17_evidence: dict[str, Any],
    runtime_contract: RuntimeVerificationContract,
    runtime_receipt: RuntimeVerificationReceipt,
    runtime_report_fingerprint: str,
) -> None:
    live_accepted = _load_json(LIVE_ACCEPTED_PLAN_PATH)
    live_campaign = _load_json(LIVE_CAMPAIGN_PATH)
    if live_accepted != frozen_accepted_payload:
        raise ValueError(
            "live AcceptedPlan drifted from frozen v1.7 proof"
        )
    if live_campaign != frozen_campaign_payload:
        raise ValueError(
            "live Campaign drifted from frozen v1.7 proof"
        )

    if v17_evidence.get("schema_version") != 1:
        raise ValueError("v1.7 graduation evidence schema_version drift")
    if v17_evidence.get("version") != SOURCE_VERSION:
        raise ValueError("v1.7 graduation evidence version drift")
    if v17_evidence.get("target_repository") != TARGET_REPOSITORY:
        raise ValueError("v1.7 target repository drift")

    task = v17_evidence.get("task")
    runtime = v17_evidence.get("runtime_verification")
    planning = v17_evidence.get("planning")
    if not isinstance(task, dict):
        raise ValueError("v1.7 task evidence is invalid")
    if not isinstance(runtime, dict):
        raise ValueError("v1.7 runtime evidence is invalid")
    if not isinstance(planning, dict):
        raise ValueError("v1.7 planning evidence is invalid")

    if task.get("task_id") != SOURCE_TASK_ID:
        raise ValueError("v1.7 source task drift")
    if task.get("merge_sha") != runtime_contract.source_sha:
        raise ValueError("v1.7 merge SHA does not match runtime source")
    if runtime.get("verification_id") != runtime_contract.verification_id:
        raise ValueError("v1.7 verification id drift")
    if runtime.get("report_fingerprint") != runtime_report_fingerprint:
        raise ValueError("v1.7 runtime report fingerprint drift")
    if runtime_receipt.status != "VERIFIED":
        raise ValueError("v1.7 source runtime receipt is not VERIFIED")
    if runtime_receipt.task_id != SOURCE_TASK_ID:
        raise ValueError("v1.7 runtime receipt task drift")
    if planning.get("campaign_id") is None:
        raise ValueError("v1.7 campaign id is missing")


def build_release_proof(
    *,
    decision_store_path: Path = DECISION_STORE_PATH,
) -> dict[str, Any]:
    frozen_accepted_payload = _load_json(
        FROZEN_ACCEPTED_PLAN_PATH
    )
    frozen_campaign_payload = _load_json(
        FROZEN_CAMPAIGN_PATH
    )
    v17_evidence = _load_json(FROZEN_V17_EVIDENCE_PATH)
    runtime_contract_payload = _load_json(
        RUNTIME_CONTRACT_PATH
    )
    runtime_receipt_payload = _load_json(
        RUNTIME_RECEIPT_PATH
    )
    runtime_report_wrapper = _load_json(RUNTIME_REPORT_PATH)

    accepted_plan = AcceptedPlan.from_dict(
        frozen_accepted_payload
    )
    campaign = AutonomousCampaign.from_dict(
        frozen_campaign_payload
    )
    runtime_contract = RuntimeVerificationContract.from_dict(
        runtime_contract_payload
    )
    runtime_receipt = RuntimeVerificationReceipt.from_dict(
        runtime_receipt_payload
    )
    runtime_report = runtime_report_from_wrapper(
        runtime_report_wrapper
    )

    _validate_source_evidence(
        frozen_accepted_payload=frozen_accepted_payload,
        frozen_campaign_payload=frozen_campaign_payload,
        v17_evidence=v17_evidence,
        runtime_contract=runtime_contract,
        runtime_receipt=runtime_receipt,
        runtime_report_fingerprint=runtime_report.fingerprint(),
    )

    readiness = derive_release_readiness(
        accepted_plan=accepted_plan,
        campaign=campaign,
        runtime_contract=runtime_contract,
        runtime_receipt=runtime_receipt,
        runtime_report=runtime_report,
        target_environment=TARGET_ENVIRONMENT,
    )
    candidate = readiness.candidate
    if candidate.repository != TARGET_REPOSITORY:
        raise ValueError("derived release candidate repository drift")
    if candidate.source_sha != runtime_contract.source_sha:
        raise ValueError("derived release candidate source SHA drift")
    if candidate.target_environment is not TARGET_ENVIRONMENT:
        raise ValueError(
            "derived release candidate target environment drift"
        )

    transition = plan_release_transition(
        candidate=candidate,
        current_verified_environment=None,
    )
    if transition.from_environment is not None:
        raise ValueError(
            "v1.8 proof must begin from unreleased -> preview"
        )
    if transition.to_environment is not TARGET_ENVIRONMENT:
        raise ValueError("v1.8 proof transition is not preview")

    store = DecisionStore(decision_store_path)
    coordinator = HumanInterruptCoordinator(store)
    request = build_release_approval_request(transition)
    record = store.get(request.decision_id)
    if record is None:
        request_release_approval(
            coordinator=coordinator,
            transition=transition,
        )
        record = store.get(request.decision_id)
    if record is None:
        raise ValueError("release approval decision was not persisted")
    approval = evaluate_release_approval(
        transition=transition,
        record=record,
    )

    state = (
        "APPROVED"
        if approval.disposition
        is ReleaseApprovalDisposition.APPROVED
        else "REJECTED"
        if approval.disposition
        is ReleaseApprovalDisposition.REJECTED
        else "HUMAN_WAIT"
    )
    release_snapshot = build_release_observability_snapshot(
        candidate=candidate,
        transition=transition,
        approval=approval,
    )

    source_manifest = {
        "schema_version": 1,
        "proof_id": PROOF_ID,
        "source_version": SOURCE_VERSION,
        "source_task_id": SOURCE_TASK_ID,
        "target_repository": TARGET_REPOSITORY,
        "source_sha": candidate.source_sha,
        "runtime_verification_id": (
            runtime_contract.verification_id
        ),
        "accepted_plan_fingerprint": (
            accepted_plan.fingerprint
        ),
        "campaign_id": campaign.campaign_id,
        "runtime_report_fingerprint": (
            runtime_report.fingerprint()
        ),
        "v1_7_graduation_evidence_path": str(
            FROZEN_V17_EVIDENCE_PATH
        ),
        "manual_campaign_progress": False,
        "source_runtime_verified": True,
    }
    proof_state = {
        "schema_version": 1,
        "proof_id": PROOF_ID,
        "state": state,
        "target_repository": TARGET_REPOSITORY,
        "source_sha": candidate.source_sha,
        "target_environment": TARGET_ENVIRONMENT.value,
        "release_candidate_id": candidate.release_candidate_id,
        "release_candidate_fingerprint": candidate.fingerprint(),
        "readiness_fingerprint": readiness.fingerprint(),
        "transition_id": transition.transition_id,
        "transition_fingerprint": transition.fingerprint(),
        "decision_id": approval.decision_id,
        "approval_fingerprint": approval.fingerprint(),
        "approval_disposition": approval.disposition.value,
        "explicit_human_approval_required": True,
        "external_side_effect_executed": False,
        "deployment_authority": False,
        "promotion_authority": False,
        "auto_promote": False,
    }

    return {
        "source_manifest": source_manifest,
        "readiness": readiness.canonical_dict(),
        "candidate": candidate.canonical_dict(),
        "transition": transition.canonical_dict(),
        "decision_record": record.to_dict(),
        "approval": approval.canonical_dict(),
        "proof_state": proof_state,
        "mission_control": release_snapshot.canonical_dict(),
        "source_accepted_plan": frozen_accepted_payload,
        "source_campaign": frozen_campaign_payload,
        "source_runtime_contract": runtime_contract_payload,
        "source_runtime_receipt": runtime_receipt_payload,
        "source_runtime_report": runtime_report_wrapper,
        "source_v1_7_evidence": v17_evidence,
    }


def persist_release_proof(
    bundle: dict[str, Any],
) -> None:
    immutable = {
        PROOF_DIR / "source-manifest.json": bundle[
            "source_manifest"
        ],
        PROOF_DIR / "readiness.json": bundle["readiness"],
        PROOF_DIR / "candidate.json": bundle["candidate"],
        PROOF_DIR / "transition.json": bundle["transition"],
        PROOF_DIR / "source" / "accepted-plan.json": bundle[
            "source_accepted_plan"
        ],
        PROOF_DIR / "source" / "campaign.json": bundle[
            "source_campaign"
        ],
        PROOF_DIR / "source" / "runtime-contract.json": bundle[
            "source_runtime_contract"
        ],
        PROOF_DIR / "source" / "runtime-receipt.json": bundle[
            "source_runtime_receipt"
        ],
        PROOF_DIR / "source" / "runtime-report.json": bundle[
            "source_runtime_report"
        ],
        PROOF_DIR / "source" / "v1.7-evidence.json": bundle[
            "source_v1_7_evidence"
        ],
    }
    for path, payload in immutable.items():
        _write_once(path, payload)

    # Decision/approval/state are intentionally mutable only across the
    # explicit human-decision transition. Preparation writes the current
    # exact queue state without inventing approval.
    _write_json(
        PROOF_DIR / "decision-record.json",
        bundle["decision_record"],
    )
    _write_json(
        PROOF_DIR / "approval.json",
        bundle["approval"],
    )
    _write_json(
        PROOF_DIR / "state.json",
        bundle["proof_state"],
    )
    _write_json(
        MISSION_CONTROL_PATH,
        bundle["mission_control"],
    )


def main() -> int:
    try:
        bundle = build_release_proof()
        persist_release_proof(bundle)
        result = {
            "schema_version": 1,
            "proof_id": PROOF_ID,
            "state": bundle["proof_state"]["state"],
            "release_candidate_id": (
                bundle["proof_state"]["release_candidate_id"]
            ),
            "source_sha": bundle["proof_state"]["source_sha"],
            "target_environment": TARGET_ENVIRONMENT.value,
            "decision_id": bundle["proof_state"]["decision_id"],
            "explicit_human_approval_required": True,
            "external_side_effect_executed": False,
        }
        _write_json(RESULT_PATH, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        result = {
            "schema_version": 1,
            "proof_id": PROOF_ID,
            "state": "FAILED",
            "error": (
                str(exc).splitlines()[0][:256]
                if str(exc).strip()
                else type(exc).__name__
            ),
        }
        _write_json(RESULT_PATH, result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

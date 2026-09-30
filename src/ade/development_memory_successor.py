from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .development_memory import DevelopmentMemoryError
from .development_memory_feedback import (
    build_verified_runtime_feedback_record,
    runtime_report_from_wrapper,
)
from .development_memory_store import DevelopmentMemoryStore
from .runtime_verification import RuntimeVerificationContract
from .runtime_verification_trigger import RuntimeVerificationReceipt


TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
BOOTSTRAP_REQUEST_ID = "v1.5-development-memory-proof-001"
BOOTSTRAP_CAMPAIGN_ID = "v1.5-development-memory-campaign-001"
BOOTSTRAP_TASK_ID = "v15mem1-001"
BOOTSTRAP_MEMORY_SOURCE = (
    ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json"
)
BOOTSTRAP_EVIDENCE_PATH = (
    ".autodev/campaign-evidence/"
    "v1.5-development-memory-proof-001-bootstrap.json"
)
PROOF002_REQUEST_ID = "v1.5-development-memory-proof-002"
PROOF002_CAMPAIGN_ID = "v1.5-development-memory-campaign-002"
PROOF002_ID_PREFIX = "v15mem2"

CONTRACT_PATH = ".autodev/runtime-verification/v15mem1-001/contract.json"
RECEIPT_PATH = ".autodev/runtime-verification/v15mem1-001/receipt.json"
REPORT_PATH = ".autodev/runtime-verification/v15mem1-001/report.json"


@dataclass(frozen=True, slots=True)
class V15BootstrapSuccessorDecision:
    eligible: bool
    reason: str
    source_sha: str | None = None
    memory_id: str | None = None
    memory_fingerprint: str | None = None
    store_fingerprint: str | None = None
    store_record_count: int = 0
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "eligible": self.eligible,
            "reason": self.reason,
            "source_sha": self.source_sha,
            "memory_id": self.memory_id,
            "memory_fingerprint": self.memory_fingerprint,
            "store_fingerprint": self.store_fingerprint,
            "store_record_count": self.store_record_count,
        }


def _object(payload: object, *, field: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DevelopmentMemoryError(f"{field} must be a JSON object")
    return payload


def _ineligible(reason: str) -> V15BootstrapSuccessorDecision:
    return V15BootstrapSuccessorDecision(eligible=False, reason=reason)


def evaluate_v1_5_bootstrap_successor(
    *,
    state_payload: object,
    campaign_payload: object,
    planner_evidence_payload: object,
    remote_execution_payload: object,
    contract_payload: object,
    receipt_payload: object,
    report_wrapper_payload: object,
    memory_store_payload: object,
) -> V15BootstrapSuccessorDecision:
    state = _object(state_payload, field="project state")
    campaign = _object(campaign_payload, field="campaign")
    planner = _object(planner_evidence_payload, field="planner evidence")
    remote = _object(remote_execution_payload, field="remote execution")

    metadata = state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if metadata.get("phase") != "v1.5-development-memory":
        return _ineligible("project is not in v1.5 Development Memory")
    if metadata.get("planning_request_id") != BOOTSTRAP_REQUEST_ID:
        return _ineligible("project is not bound to the v1.5 bootstrap request")
    if state.get("status") != "READY":
        return _ineligible("project state is not READY")
    if state.get("current_task_id") is not None:
        return _ineligible("project still has an active task")
    if state.get("failed_task_ids") != []:
        return _ineligible("project contains failed tasks")

    if campaign.get("campaign_id") != BOOTSTRAP_CAMPAIGN_ID:
        return _ineligible("bootstrap campaign identity mismatch")
    if campaign.get("status") != "COMPLETED":
        return _ineligible("bootstrap campaign is not COMPLETED")
    if campaign.get("task_ids") != [BOOTSTRAP_TASK_ID]:
        return _ineligible("bootstrap campaign task set mismatch")
    if campaign.get("completed_task_ids") != [BOOTSTRAP_TASK_ID]:
        return _ineligible("bootstrap campaign task is not complete")

    if planner.get("campaign_id") != BOOTSTRAP_CAMPAIGN_ID:
        return _ineligible("planner evidence campaign mismatch")
    request = planner.get("request")
    request = request if isinstance(request, dict) else {}
    if request.get("request_id") != BOOTSTRAP_REQUEST_ID:
        return _ineligible("planner evidence request mismatch")
    if planner.get("planning_only") is not True:
        return _ineligible("planner crossed the planning-only boundary")
    memory = planner.get("development_memory")
    memory = memory if isinstance(memory, dict) else {}
    if memory.get("used") is not True:
        return _ineligible("bootstrap planner did not reuse Development Memory")
    if memory.get("authority") != "advisory-data-only":
        return _ineligible("bootstrap memory authority is invalid")
    if memory.get("execution_authority") is not False:
        return _ineligible("bootstrap memory gained execution authority")
    if memory.get("memory_may_expand_scope") is not False:
        return _ineligible("bootstrap memory gained scope authority")
    if memory.get("memory_may_override_acceptance") is not False:
        return _ineligible("bootstrap memory gained Acceptance authority")
    if memory.get("source_evidence_path") != BOOTSTRAP_MEMORY_SOURCE:
        return _ineligible("bootstrap memory did not come from trusted v1.4 evidence")
    if memory.get("repository") != TARGET_REPOSITORY:
        return _ineligible("bootstrap memory repository mismatch")
    if not isinstance(memory.get("memory_ids"), list) or not memory["memory_ids"]:
        return _ineligible("bootstrap planner has no reused memory IDs")

    expected_prefix = f"https://github.com/{TARGET_REPOSITORY}/pull/"
    pull_request_url = remote.get("pull_request_url")
    if remote.get("status") != "MERGED":
        return _ineligible("remote execution is not MERGED")
    if remote.get("task_id") != BOOTSTRAP_TASK_ID:
        return _ineligible("remote execution task mismatch")
    if remote.get("target_repository") != TARGET_REPOSITORY:
        return _ineligible("remote execution repository mismatch")
    if not isinstance(pull_request_url, str) or not pull_request_url.startswith(
        expected_prefix
    ):
        return _ineligible("remote execution pull request provenance is invalid")
    suffix = pull_request_url.removeprefix(expected_prefix)
    if not suffix.isdigit() or int(suffix) < 1:
        return _ineligible("remote execution pull request number is invalid")

    try:
        contract = RuntimeVerificationContract.from_dict(
            _object(contract_payload, field="runtime contract")
        )
        receipt = RuntimeVerificationReceipt.from_dict(
            _object(receipt_payload, field="runtime receipt")
        )
        report = runtime_report_from_wrapper(
            _object(report_wrapper_payload, field="runtime report wrapper")
        )
        store = DevelopmentMemoryStore.from_dict(
            _object(memory_store_payload, field="Development Memory store")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DevelopmentMemoryError("bootstrap runtime evidence is invalid") from exc

    if contract.target_repository != TARGET_REPOSITORY:
        return _ineligible("runtime contract repository mismatch")
    if receipt.task_id != BOOTSTRAP_TASK_ID:
        return _ineligible("runtime receipt task mismatch")
    if receipt.status != "VERIFIED":
        return _ineligible("runtime receipt is not VERIFIED")
    if receipt.verification_id != contract.verification_id:
        return _ineligible("runtime verification identity mismatch")
    if receipt.source_sha != contract.source_sha:
        return _ineligible("runtime receipt source mismatch")
    if report.source_sha != contract.source_sha:
        return _ineligible("runtime report source mismatch")

    try:
        expected_record = build_verified_runtime_feedback_record(
            contract=contract,
            receipt=receipt,
            report=report,
            contract_path=CONTRACT_PATH,
            receipt_path=RECEIPT_PATH,
            report_path=REPORT_PATH,
        )
    except DevelopmentMemoryError:
        return _ineligible("runtime evidence cannot reproduce trusted memory feedback")

    matches = [
        record
        for record in store.ledger.records
        if record.memory_id == expected_record.memory_id
    ]
    if len(matches) != 1:
        return _ineligible("durable store does not contain exactly one feedback record")
    if matches[0].canonical_dict() != expected_record.canonical_dict():
        return _ineligible("durable feedback record differs from trusted reconstruction")

    return V15BootstrapSuccessorDecision(
        eligible=True,
        reason="bootstrap-runtime-and-memory-feedback-verified",
        source_sha=contract.source_sha,
        memory_id=expected_record.memory_id,
        memory_fingerprint=expected_record.fingerprint(),
        store_fingerprint=store.fingerprint(),
        store_record_count=len(store.ledger.records),
    )


def proof002_planning_goal() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": PROOF002_REQUEST_ID,
        "campaign_id": PROOF002_CAMPAIGN_ID,
        "id_prefix": PROOF002_ID_PREFIX,
        "goal": (
            "Add a focused regression test confirming that the existing experiment "
            "variant label normalizer collapses EN SPACE (U+2002) and HAIR SPACE "
            "(U+200A) to single plain spaces in the display label while preserving "
            "its existing stable-key behavior. Use existing test files only. Do not "
            "change production behavior, package exports, CLI behavior, workflows, "
            "configuration, deployment, secrets, or irreversible behavior. Do not "
            "create new files."
        ),
        "target_repository": TARGET_REPOSITORY,
        "base_branch": "main",
        "allowed_path_prefixes": ["tests"],
        "min_tasks": 1,
        "max_tasks": 1,
    }


def build_bootstrap_evidence(
    *,
    decision: V15BootstrapSuccessorDecision,
    planner_evidence_payload: object,
    remote_execution_payload: object,
    receipt_payload: object,
) -> dict[str, Any]:
    if not decision.eligible:
        raise DevelopmentMemoryError(
            "ineligible bootstrap decision cannot become evidence"
        )
    planner = _object(planner_evidence_payload, field="planner evidence")
    memory = planner.get("development_memory")
    memory = memory if isinstance(memory, dict) else {}
    remote = _object(remote_execution_payload, field="remote execution")
    receipt = _object(receipt_payload, field="runtime receipt")
    return {
        "schema_version": 1,
        "version": "v1.5-bootstrap",
        "request_id": BOOTSTRAP_REQUEST_ID,
        "campaign_id": BOOTSTRAP_CAMPAIGN_ID,
        "task_id": BOOTSTRAP_TASK_ID,
        "target_repository": TARGET_REPOSITORY,
        "planner_memory": {
            "used": memory.get("used"),
            "authority": memory.get("authority"),
            "execution_authority": memory.get("execution_authority"),
            "memory_may_expand_scope": memory.get("memory_may_expand_scope"),
            "memory_may_override_acceptance": memory.get(
                "memory_may_override_acceptance"
            ),
            "source_evidence_path": memory.get("source_evidence_path"),
            "source_evidence_fingerprint": memory.get(
                "source_evidence_fingerprint"
            ),
            "memory_ids": memory.get("memory_ids"),
            "current_source_sha": memory.get("current_source_sha"),
        },
        "external_execution": {
            "status": remote.get("status"),
            "pull_request_url": remote.get("pull_request_url"),
        },
        "runtime_verification": {
            "verification_id": receipt.get("verification_id"),
            "source_sha": receipt.get("source_sha"),
            "status": receipt.get("status"),
            "dispatch_count": receipt.get("dispatch_count"),
        },
        "durable_memory_feedback": {
            "memory_id": decision.memory_id,
            "memory_fingerprint": decision.memory_fingerprint,
            "store_fingerprint": decision.store_fingerprint,
            "store_record_count": decision.store_record_count,
        },
        "successor_request_id": PROOF002_REQUEST_ID,
        "graduation_eligible": False,
        "evidence_policy": (
            "Proof001 is bootstrap evidence only. v1.5 graduation requires proof002 "
            "to reuse the durable Development Memory store directly."
        ),
    }

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ade.development_memory_feedback import runtime_report_from_wrapper
from ade.runtime_probe_executor import execute_runtime_verification_bounded
from ade.runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
)
from ade.runtime_verification_recovery import (
    contain_runtime_verification_failure,
    runtime_failure_fingerprint,
)
from ade.runtime_verification_trigger import (
    RuntimeVerificationReceipt,
    record_runtime_verification_dispatch,
    record_runtime_verification_report,
    runtime_verification_paths,
    runtime_verification_report_path,
    runtime_verification_target_path,
)
from development_memory_feedback import (
    feedback_failure,
    persist_recovery_feedback,
    persist_verified_runtime_feedback,
)
from github_client import GitHubClient, GitHubError
from recovery_controller import RECOVERY_PATH, load_recovery
from runtime_probes import build_runtime_probe_registry
from runtime_targets import build_runtime_target_registry
from runtime_workspace import prepare_repository_runtime_workspace

RESULT_PATH = Path(".autodev/runtime/runtime-verification-dispatch-result.json")
V1_5_FINALIZER_TASK_ID = "v15mem2-001"


def _runtime_provenance_path(task_id: str) -> str:
    return f".autodev/runtime-verification/{task_id}/provenance.json"


def _positive_run_id(value: object, *, field: str) -> int:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise ValueError(f"{field} must be a positive workflow run id")


def _write(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _event_payload() -> dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise ValueError("GITHUB_EVENT_PATH is required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow event must be a JSON object")
    client_payload = payload.get("client_payload")
    if not isinstance(client_payload, dict):
        raise ValueError("repository_dispatch client_payload is required")
    return client_payload


def _contain_failure(
    gh: GitHubClient,
    *,
    receipt_path: str,
    receipt: RuntimeVerificationReceipt,
    report=None,
    failure_detail: str | None = None,
) -> RuntimeVerificationReceipt:
    state_payload, _ = gh.get_json_file(".autodev/state.json")
    campaign_payload, _ = gh.get_json_file(".autodev/campaign.json")
    previous, _ = load_recovery(gh)
    if previous is not None and previous.task_id != receipt.task_id:
        previous = None

    transition = contain_runtime_verification_failure(
        receipt=receipt,
        state_payload=state_payload,
        campaign_payload=campaign_payload,
        report=report,
        failure_fingerprint=(
            runtime_failure_fingerprint(failure_detail)
            if failure_detail is not None
            else None
        ),
        previous_recovery=previous,
    )
    gh.upsert_json_file(
        RECOVERY_PATH,
        transition.recovery.to_dict(),
        message=f"recovery: runtime verification {receipt.task_id}",
    )
    gh.upsert_json_file(
        ".autodev/campaign.json",
        transition.campaign,
        message=f"campaign: runtime human wait {receipt.task_id}",
    )
    gh.upsert_json_file(
        ".autodev/state.json",
        transition.state,
        message=f"state: runtime human wait {receipt.task_id}",
    )
    gh.upsert_json_file(
        receipt_path,
        transition.receipt.canonical_dict(),
        message=f"runtime: human wait {receipt.verification_id}",
    )
    return transition.receipt


def _persist_verified_feedback_safely(
    gh: GitHubClient,
    *,
    contract: RuntimeVerificationContract,
    receipt: RuntimeVerificationReceipt,
    report,
    contract_path: str,
    receipt_path: str,
    report_path: str,
) -> dict[str, Any]:
    try:
        return persist_verified_runtime_feedback(
            gh,
            contract=contract,
            receipt=receipt,
            report=report,
            contract_path=contract_path,
            receipt_path=receipt_path,
            report_path=report_path,
        )
    except Exception as exc:
        return feedback_failure(exc)


def _persist_recovery_feedback_safely(
    gh: GitHubClient,
    *,
    receipt: RuntimeVerificationReceipt,
) -> dict[str, Any]:
    try:
        recovery, _ = load_recovery(gh)
        if recovery is None or recovery.task_id != receipt.task_id:
            raise ValueError("runtime recovery feedback record is unavailable")
        return persist_recovery_feedback(
            gh,
            recovery=recovery,
            repository=receipt.target_repository,
            source_sha=receipt.source_sha,
        )
    except Exception as exc:
        return feedback_failure(exc)


def _dispatch_development_memory_successor(
    gh: GitHubClient,
    *,
    receipt: RuntimeVerificationReceipt,
    memory_feedback: dict[str, Any],
) -> str:
    if receipt.status != "VERIFIED":
        return "NOT_APPLICABLE"
    if receipt.task_id != "v15mem1-001":
        return "NOT_APPLICABLE"
    if memory_feedback.get("state") not in {"ADDED", "UNCHANGED"}:
        return "WAITING_FOR_DURABLE_MEMORY"
    try:
        gh.dispatch(
            "ade_development_memory_successor",
            {
                "task_id": receipt.task_id,
                "verification_id": receipt.verification_id,
                "source_sha": receipt.source_sha,
                "source": "runtime-verification-memory-feedback",
            },
        )
    except GitHubError:
        return "SCHEDULED_FALLBACK"
    return "DISPATCHED"


def _persist_runtime_provenance(
    gh: GitHubClient,
    *,
    event_payload: dict[str, Any],
    contract: RuntimeVerificationContract,
    receipt: RuntimeVerificationReceipt,
    dependency_fingerprint: str,
    report_fingerprint: str,
    memory_feedback: dict[str, Any],
) -> dict[str, Any]:
    runtime_run_id = _positive_run_id(
        os.environ.get("GITHUB_RUN_ID"),
        field="GITHUB_RUN_ID",
    )
    remote_monitor_run_id = _positive_run_id(
        event_payload.get("remote_monitor_workflow_run_id"),
        field="remote_monitor_workflow_run_id",
    )
    pull_request_number = event_payload.get("pull_request_number")
    if type(pull_request_number) is not int or pull_request_number < 1:
        raise ValueError("pull_request_number must be positive")
    pull_request_head_sha = event_payload.get("pull_request_head_sha")
    trusted_merge_sha = event_payload.get("trusted_merge_sha")
    if pull_request_head_sha is None or not isinstance(pull_request_head_sha, str):
        raise ValueError("pull_request_head_sha is required")
    if trusted_merge_sha != contract.source_sha:
        raise ValueError("trusted_merge_sha does not match runtime source SHA")
    if memory_feedback.get("state") not in {"ADDED", "UNCHANGED"}:
        raise ValueError("durable memory feedback is not complete")

    state_payload, _ = gh.get_json_file(".autodev/state.json")
    metadata = state_payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    implementation_run_id = _positive_run_id(
        metadata.get("implementation_workflow_run_id"),
        field="implementation_workflow_run_id",
    )
    implementation_workflow_name = metadata.get("implementation_workflow_name")
    implementation_workflow_event = metadata.get("implementation_workflow_event")
    if not isinstance(implementation_workflow_name, str) or not implementation_workflow_name:
        raise ValueError("implementation workflow name is missing")
    if not isinstance(implementation_workflow_event, str) or not implementation_workflow_event:
        raise ValueError("implementation workflow event is missing")

    payload = {
        "schema_version": 1,
        "task_id": receipt.task_id,
        "verification_id": receipt.verification_id,
        "runtime_workflow_run_id": runtime_run_id,
        "runtime_workflow_event": os.environ.get("GITHUB_EVENT_NAME", ""),
        "remote_monitor_workflow_run_id": remote_monitor_run_id,
        "implementation_workflow_run_id": implementation_run_id,
        "implementation_workflow_name": implementation_workflow_name,
        "implementation_workflow_event": implementation_workflow_event,
        "pull_request_number": pull_request_number,
        "pull_request_head_sha": pull_request_head_sha,
        "trusted_merge_sha": trusted_merge_sha,
        "workspace_source_sha": contract.source_sha,
        "dependency_fingerprint": dependency_fingerprint,
        "report_fingerprint": report_fingerprint,
        "development_memory_feedback": memory_feedback,
    }
    gh.upsert_json_file(
        _runtime_provenance_path(receipt.task_id),
        payload,
        message=f"runtime: provenance {receipt.verification_id}",
    )
    return payload


def _dispatch_v1_5_graduation_finalizer(
    gh: GitHubClient,
    *,
    receipt: RuntimeVerificationReceipt,
    provenance: dict[str, Any],
) -> str:
    if receipt.status != "VERIFIED" or receipt.task_id != V1_5_FINALIZER_TASK_ID:
        return "NOT_APPLICABLE"
    try:
        gh.dispatch(
            "ade_v1_5_graduation_finalize",
            {
                "task_id": receipt.task_id,
                "verification_id": receipt.verification_id,
                "source_sha": receipt.source_sha,
                "runtime_workflow_run_id": provenance["runtime_workflow_run_id"],
                "source": "runtime-verification",
            },
        )
    except GitHubError:
        return "SCHEDULED_FALLBACK"
    return "DISPATCHED"


def validate_dispatch_payload(
    *,
    event_payload: dict[str, Any],
    contract: RuntimeVerificationContract,
    receipt: RuntimeVerificationReceipt,
) -> None:
    if event_payload.get("task_id") != receipt.task_id:
        raise ValueError("runtime verification dispatch task_id mismatch")
    if event_payload.get("verification_id") != receipt.verification_id:
        raise ValueError("runtime verification dispatch verification_id mismatch")
    if event_payload.get("source_sha") != receipt.source_sha:
        raise ValueError("runtime verification dispatch source_sha mismatch")
    if event_payload.get("target_repository") != receipt.target_repository:
        raise ValueError("runtime verification dispatch repository mismatch")
    if contract.verification_id != receipt.verification_id:
        raise ValueError("runtime verification contract/receipt id mismatch")
    if contract.source_sha != receipt.source_sha:
        raise ValueError("runtime verification contract/receipt source mismatch")
    if contract.target_repository != receipt.target_repository:
        raise ValueError("runtime verification contract/receipt repository mismatch")
    if contract.fingerprint() != receipt.contract_fingerprint:
        raise ValueError("runtime verification contract fingerprint mismatch")
    if event_payload.get("trusted_merge_sha") != receipt.source_sha:
        raise ValueError("runtime verification trusted merge SHA mismatch")
    head_sha = event_payload.get("pull_request_head_sha")
    if not isinstance(head_sha, str) or len(head_sha) != 40:
        raise ValueError("runtime verification pull request head SHA is invalid")
    _positive_run_id(
        event_payload.get("remote_monitor_workflow_run_id"),
        field="remote_monitor_workflow_run_id",
    )
    pull_request_number = event_payload.get("pull_request_number")
    if type(pull_request_number) is not int or pull_request_number < 1:
        raise ValueError("runtime verification pull request number is invalid")


def main() -> int:
    try:
        event = _event_payload()
        task_id = event.get("task_id")
        contract_path, receipt_path = runtime_verification_paths(task_id)

        gh = GitHubClient()
        contract_payload, _ = gh.get_json_file(contract_path)
        receipt_payload, _ = gh.get_json_file(receipt_path)
        contract = RuntimeVerificationContract.from_dict(contract_payload)
        receipt = RuntimeVerificationReceipt.from_dict(receipt_payload)
        validate_dispatch_payload(
            event_payload=event,
            contract=contract,
            receipt=receipt,
        )

        if receipt.status == "VERIFIED":
            report_path = runtime_verification_report_path(receipt.task_id)
            report_wrapper, _ = gh.get_json_file(report_path)
            report = runtime_report_from_wrapper(report_wrapper)
            memory_feedback = _persist_verified_feedback_safely(
                gh,
                contract=contract,
                receipt=receipt,
                report=report,
                contract_path=contract_path,
                receipt_path=receipt_path,
                report_path=report_path,
            )
            memory_successor = _dispatch_development_memory_successor(
                gh,
                receipt=receipt,
                memory_feedback=memory_feedback,
            )
            graduation_finalizer = "NOT_APPLICABLE"
            runtime_provenance = None
            if receipt.task_id == V1_5_FINALIZER_TASK_ID and memory_feedback.get("state") in {"ADDED", "UNCHANGED"}:
                try:
                    runtime_provenance, _ = gh.get_json_file(
                        _runtime_provenance_path(receipt.task_id)
                    )
                    graduation_finalizer = _dispatch_v1_5_graduation_finalizer(
                        gh,
                        receipt=receipt,
                        provenance=runtime_provenance,
                    )
                except GitHubError:
                    graduation_finalizer = "WAITING_FOR_PROVENANCE"
            result = {
                "schema_version": 1,
                "state": "VERIFIED",
                "receipt_changed": False,
                "task_id": receipt.task_id,
                "verification_id": receipt.verification_id,
                "target_repository": receipt.target_repository,
                "source_sha": receipt.source_sha,
                "dispatch_count": receipt.dispatch_count,
                "reason": "runtime-verification-already-verified",
                "development_memory_feedback": memory_feedback,
                "development_memory_successor": memory_successor,
                "runtime_provenance": runtime_provenance,
                "v1_5_graduation_finalizer": graduation_finalizer,
            }
            _write(result)
            print(json.dumps(result, sort_keys=True))
            return 0

        if receipt.status == "HUMAN_WAIT":
            memory_feedback = _persist_recovery_feedback_safely(
                gh,
                receipt=receipt,
            )
            result = {
                "schema_version": 1,
                "state": "HUMAN_WAIT",
                "receipt_changed": False,
                "task_id": receipt.task_id,
                "verification_id": receipt.verification_id,
                "target_repository": receipt.target_repository,
                "source_sha": receipt.source_sha,
                "dispatch_count": receipt.dispatch_count,
                "reason": "runtime-verification-already-human-wait",
                "development_memory_feedback": memory_feedback,
            }
            _write(result)
            print(json.dumps(result, sort_keys=True))
            return 2

        target_registry = build_runtime_target_registry(
            contract.target_repository,
        )
        target_resolution = target_registry.resolve(
            contract,
            now=datetime.now(UTC),
        )
        target_path = runtime_verification_target_path(receipt.task_id)
        gh.upsert_json_file(
            target_path,
            target_resolution.canonical_dict(),
            message=f"runtime: target {receipt.verification_id}",
        )

        workspace = prepare_repository_runtime_workspace(contract)
        dependency_fingerprint = workspace.dependency_fingerprint
        try:
            registry = build_runtime_probe_registry(workspace)
            dispatch_transition = record_runtime_verification_dispatch(
                contract=contract,
                registry=registry,
                receipt=receipt,
            )
            active_receipt = dispatch_transition.receipt
            if dispatch_transition.changed:
                gh.upsert_json_file(
                    receipt_path,
                    active_receipt.canonical_dict(),
                    message=f"runtime: dispatched {receipt.verification_id}",
                )

            execution = execute_runtime_verification_bounded(
                contract,
                registry,
            )
        finally:
            workspace.cleanup()
        report_path = runtime_verification_report_path(active_receipt.task_id)
        gh.upsert_json_file(
            report_path,
            execution.canonical_dict(),
            message=f"runtime: report {active_receipt.verification_id}",
        )
        completion = record_runtime_verification_report(
            contract=contract,
            receipt=active_receipt,
            report=execution.report,
        )
        if completion.changed:
            gh.upsert_json_file(
                receipt_path,
                completion.receipt.canonical_dict(),
                message=f"runtime: {completion.receipt.status.lower()} {completion.receipt.verification_id}",
            )

        final_receipt = completion.receipt
        if execution.report.disposition is RuntimeVerificationDisposition.FAILED:
            final_receipt = _contain_failure(
                gh,
                receipt_path=receipt_path,
                receipt=completion.receipt,
                report=execution.report,
            )

        runtime_provenance = None
        graduation_finalizer = "NOT_APPLICABLE"
        if final_receipt.status == "VERIFIED":
            memory_feedback = _persist_verified_feedback_safely(
                gh,
                contract=contract,
                receipt=final_receipt,
                report=execution.report,
                contract_path=contract_path,
                receipt_path=receipt_path,
                report_path=report_path,
            )
            memory_successor = _dispatch_development_memory_successor(
                gh,
                receipt=final_receipt,
                memory_feedback=memory_feedback,
            )
            if (
                final_receipt.task_id == V1_5_FINALIZER_TASK_ID
                and memory_feedback.get("state") in {"ADDED", "UNCHANGED"}
            ):
                runtime_provenance = _persist_runtime_provenance(
                    gh,
                    event_payload=event,
                    contract=contract,
                    receipt=final_receipt,
                    dependency_fingerprint=dependency_fingerprint,
                    report_fingerprint=execution.report.fingerprint(),
                    memory_feedback=memory_feedback,
                )
                graduation_finalizer = _dispatch_v1_5_graduation_finalizer(
                    gh,
                    receipt=final_receipt,
                    provenance=runtime_provenance,
                )
        else:
            memory_feedback = _persist_recovery_feedback_safely(
                gh,
                receipt=final_receipt,
            )
            memory_successor = "NOT_APPLICABLE"

        result = {
            "schema_version": 1,
            "state": final_receipt.status,
            "receipt_changed": dispatch_transition.changed or completion.changed or final_receipt != completion.receipt,
            "task_id": final_receipt.task_id,
            "verification_id": final_receipt.verification_id,
            "target_repository": final_receipt.target_repository,
            "source_sha": final_receipt.source_sha,
            "dispatch_count": final_receipt.dispatch_count,
            "probe_execution_enabled": True,
            "runtime_target_kind": target_resolution.evidence.kind.value,
            "runtime_target_id": target_resolution.evidence.target_id,
            "runtime_target_provenance_id": target_resolution.evidence.provenance_id,
            "runtime_target_deployment_id": target_resolution.evidence.deployment_id,
            "runtime_target_evidence_fingerprint": target_resolution.evidence.fingerprint(),
            "runtime_target_registry_fingerprint": target_resolution.registry_fingerprint,
            "runtime_dependency_fingerprint": dependency_fingerprint,
            "runtime_workspace_source_sha": contract.source_sha,
            "report_fingerprint": execution.report.fingerprint(),
            "attempts_by_probe": [
                {"probe_id": probe_id, "attempts": attempts}
                for probe_id, attempts in execution.attempts_by_probe
            ],
            "development_memory_feedback": memory_feedback,
            "development_memory_successor": memory_successor,
            "runtime_provenance": runtime_provenance,
            "v1_5_graduation_finalizer": graduation_finalizer,
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        if final_receipt.status == "HUMAN_WAIT":
            return 2
        return 0
    except (GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        detail = str(exc).splitlines()[0][:256]
        result = {
            "schema_version": 1,
            "state": "FAILED",
            "error": detail,
        }
        try:
            if "gh" in locals() and "receipt" in locals() and "receipt_path" in locals():
                active = receipt
                if active.status in {"ARMED", "DISPATCHED", "FAILED"}:
                    failed_receipt = RuntimeVerificationReceipt(
                        verification_id=active.verification_id,
                        task_id=active.task_id,
                        target_repository=active.target_repository,
                        source_sha=active.source_sha,
                        contract_fingerprint=active.contract_fingerprint,
                        registry_fingerprint=active.registry_fingerprint,
                        policy_fingerprint=active.policy_fingerprint,
                        status="FAILED",
                        dispatch_count=active.dispatch_count,
                    )
                    human_wait = _contain_failure(
                        gh,
                        receipt_path=receipt_path,
                        receipt=failed_receipt,
                        failure_detail=detail,
                    )
                    result["state"] = human_wait.status
                    result["task_id"] = human_wait.task_id
                    result["verification_id"] = human_wait.verification_id
        except Exception as containment_exc:
            result["containment_error"] = str(containment_exc).splitlines()[0][:256]
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 2 if result.get("state") == "HUMAN_WAIT" else 1


if __name__ == "__main__":
    raise SystemExit(main())

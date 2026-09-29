from __future__ import annotations

from datetime import UTC, datetime

from ade.recovery import RecoveryAction, RecoveryFailure
from ade.runtime_verification_control import build_runtime_failure_boundary
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from ade_pr_gate import advance_queue
from github_client import GitHubClient
from recovery_controller import plan_and_persist


def advance_after_runtime_verified(
    gh: GitHubClient,
    receipt: RuntimeVerificationReceipt,
) -> tuple[str | None, bool]:
    state, _ = gh.get_json_file(".autodev/state.json")
    completed = state.get("completed_task_ids", [])
    if not isinstance(completed, list):
        raise RuntimeError("project completed_task_ids must be a list")
    if receipt.task_id in completed:
        return None, False
    if state.get("current_task_id") != receipt.task_id:
        raise RuntimeError(
            "verified runtime task does not match current project task"
        )
    return advance_queue(
        gh,
        completed_task_id=receipt.task_id,
    ), True


def enter_runtime_human_wait(
    gh: GitHubClient,
    *,
    receipt: RuntimeVerificationReceipt,
    detail: str,
    report_fingerprint: str,
) -> str:
    state, state_sha = gh.get_json_file(".autodev/state.json")
    metadata = state.get("metadata")
    if (
        state.get("status") == "HUMAN_WAIT"
        and isinstance(metadata, dict)
        and metadata.get("runtime_verification_id") == receipt.verification_id
        and metadata.get("runtime_verification_report_fingerprint")
        == report_fingerprint
    ):
        decision_id = metadata.get("runtime_verification_decision_id")
        if not isinstance(decision_id, str) or not decision_id:
            raise RuntimeError("runtime HUMAN_WAIT has no decision_id")
        return decision_id

    campaign, campaign_sha = gh.get_json_file(".autodev/campaign.json")
    graph, graph_sha = gh.get_json_file(".autodev/task-graph.json")

    recovery = plan_and_persist(
        gh,
        task_id=receipt.task_id,
        failure=RecoveryFailure.HUMAN_REQUIRED,
        detail=detail,
    )
    if recovery.action is not RecoveryAction.HUMAN_WAIT:
        raise RuntimeError(
            "runtime verification failure did not resolve to HUMAN_WAIT"
        )

    boundary = build_runtime_failure_boundary(
        state_payload=state,
        campaign_payload=campaign,
        graph_payload=graph,
        task_id=receipt.task_id,
        verification_id=receipt.verification_id,
        report_fingerprint=report_fingerprint,
    )
    next_state = dict(boundary.state)
    next_state["updated_at"] = datetime.now(UTC).isoformat()
    next_metadata = dict(next_state.get("metadata", {}))
    next_metadata["recovery_action"] = recovery.action.value
    next_metadata["recovery_failure"] = recovery.failure.value
    next_state["metadata"] = next_metadata

    gh.put_json_file(
        ".autodev/task-graph.json",
        boundary.task_graph,
        sha=graph_sha,
        message=f"graph: runtime human-wait {receipt.task_id}",
    )
    gh.put_json_file(
        ".autodev/campaign.json",
        boundary.campaign,
        sha=campaign_sha,
        message=f"campaign: runtime human-wait {receipt.task_id}",
    )
    gh.put_json_file(
        ".autodev/state.json",
        next_state,
        sha=state_sha,
        message=f"state: runtime human-wait {receipt.task_id}",
    )
    return boundary.decision_id

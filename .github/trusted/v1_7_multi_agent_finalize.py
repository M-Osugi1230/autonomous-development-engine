from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.accepted_plan import AcceptedPlan
from ade.development_memory_feedback import runtime_report_from_wrapper
from ade.multi_agent import AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import AgentContribution, ContributionVerdict
from ade.multi_agent_reconciliation import (
    ReconciliationDisposition,
    reconcile_agent_contributions,
)
from ade.multi_agent_review_gate import ReviewClearance, build_review_clearance
from ade.multi_agent_session import RoleSession, RoleSessionState
from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from github_client import GitHubClient, GitHubError
from scripts.v1_7_multi_agent_audit import (
    ACCEPTED_PLAN_PATH,
    CAMPAIGN_PATH,
    CHECKPOINT_PATH,
    CLEARANCE_PATH,
    EVIDENCE_PATH,
    EXPECTED_PATH,
    PLAN_PATH,
    PLANNING_GOAL_PATH,
    PROVENANCE_PATH,
    RECONCILIATION_PATH,
    REMOTE_PATH,
    REVIEWER_CONTRIBUTION_PATH,
    REVIEWER_OBSERVATION_PATH,
    REVIEWER_SESSION_PATH,
    STATE_PATH,
    TARGET_REPOSITORY,
    TASK_ID,
    audit as audit_v1_7,
)
from v1_5_graduation_finalize import (
    _api_json,
    _get_controller_run,
    select_remote_gate_run,
    select_target_ci_run,
    validate_controller_run,
)


LIVE_PLANNING_GOAL_PATH = ".autodev/planning-goal.json"
LIVE_ACCEPTED_PLAN_PATH = ".autodev/accepted-plan.json"
LIVE_CAMPAIGN_PATH = ".autodev/campaign.json"
LIVE_STATE_PATH = ".autodev/state.json"
LIVE_REMOTE_PATH = ".autodev/runtime/remote-execution.json"
LIVE_CHECKPOINT_PATH = ".autodev/runtime/checkpoint.json"
ZERO_TOUCH_PATH = ".autodev/runtime/zero-touch-start.json"
LIVE_PLAN_PATH = ".autodev/multi-agent/plan.json"
LIVE_REVIEWER_SESSION_PATH = ".autodev/multi-agent/reviewer-session.json"
LIVE_REVIEWER_OBSERVATION_PATH = ".autodev/multi-agent/reviewer-observation.json"
LIVE_REVIEWER_CONTRIBUTION_PATH = ".autodev/multi-agent/reviewer-contribution.json"
LIVE_RECONCILIATION_PATH = ".autodev/multi-agent/reconciliation.json"
LIVE_CLEARANCE_PATH = ".autodev/multi-agent/review-clearance.json"
PLANNER_EVIDENCE_PATH = ".autodev/planner-evidence/v1.7-multi-agent-proof-001.json"
RECOVERY_PATH = ".autodev/runtime/recovery.json"
RESULT_PATH = Path(".autodev/runtime/v1-7-multi-agent-finalize-result.json")
PHASE = "v1.7-multi-agent"


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_local(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _optional_json(gh: GitHubClient, path: str) -> dict[str, Any] | None:
    try:
        payload, _ = gh.get_json_file(path)
        return payload
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise


def _write_once_json(
    gh: GitHubClient,
    path: str,
    payload: dict[str, Any],
    *,
    message: str,
) -> None:
    current = _optional_json(gh, path)
    if current is None:
        gh.put_json_file(path, payload, sha=None, message=message)
        return
    if current != payload:
        raise ValueError(f"immutable v1.7 proof artifact drift: {path}")


def _positive_int(value: object, *, field: str) -> int:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise ValueError(f"{field} must be a positive integer")


def _select_review_run(
    runs: list[dict[str, Any]],
    *,
    pr_created_at: str,
    merged_at: str,
) -> dict[str, Any]:
    from datetime import UTC, datetime

    def parse(value: object) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError("review workflow timestamp is missing")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("review workflow timestamp must be timezone-aware")
        return parsed.astimezone(UTC)

    start = parse(pr_created_at)
    end = parse(merged_at)
    candidates = [
        row
        for row in runs
        if isinstance(row, dict)
        and row.get("name") == "ADE Multi-Agent Review"
        and row.get("event") == "repository_dispatch"
        and row.get("conclusion") == "success"
        and start <= parse(row.get("created_at")) <= end
    ]
    if not candidates:
        raise ValueError("no successful independent review workflow is bound to PR window")
    return max(candidates, key=lambda row: _positive_int(row.get("id"), field="review run"))


def _target_observations(
    *,
    remote: RemoteExecutionReceipt,
    expected_base_sha: str,
    expected_head_sha: str,
) -> dict[str, Any]:
    number = remote.pull_request_number
    pr = _api_json(f"/repos/{TARGET_REPOSITORY}/pulls/{number}")
    if not isinstance(pr, dict):
        raise ValueError("target pull request response must be an object")
    if pr.get("state") != "closed" or not pr.get("merged_at"):
        raise ValueError("target pull request is not merged")
    if pr.get("html_url") != remote.pull_request_url:
        raise ValueError("target pull request URL does not match remote receipt")

    head = pr.get("head")
    base = pr.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ValueError("target pull request head/base metadata is missing")
    head_sha = head.get("sha")
    base_sha = base.get("sha")
    merge_sha = pr.get("merge_commit_sha")
    if base_sha != expected_base_sha:
        raise ValueError("target PR base SHA does not match Multi-Agent source")
    if head_sha != expected_head_sha:
        raise ValueError("target PR head SHA does not match reviewer clearance")
    if not isinstance(merge_sha, str) or len(merge_sha) != 40:
        raise ValueError("target pull request merge SHA is invalid")

    files = _api_json(
        f"/repos/{TARGET_REPOSITORY}/pulls/{number}/files?per_page=100"
    )
    if not isinstance(files, list):
        raise ValueError("target pull request files response must be a list")
    changed_paths = sorted(
        item.get("filename")
        for item in files
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    )
    if changed_paths != [EXPECTED_PATH]:
        raise ValueError(f"target pull request scope is not exact: {changed_paths}")

    target_runs_payload = _api_json(
        f"/repos/{TARGET_REPOSITORY}/actions/runs?per_page=100"
    )
    if (
        not isinstance(target_runs_payload, dict)
        or not isinstance(target_runs_payload.get("workflow_runs"), list)
    ):
        raise ValueError("target workflow runs response is invalid")
    target_runs = [
        row for row in target_runs_payload["workflow_runs"] if isinstance(row, dict)
    ]
    ci_run = select_target_ci_run(
        target_runs,
        head_sha=head_sha,
        pr_created_at=pr.get("created_at"),
        merged_at=pr.get("merged_at"),
    )
    gate_run = select_remote_gate_run(
        target_runs,
        ci_run=ci_run,
        merged_at=pr.get("merged_at"),
    )

    controller_runs_payload = _api_json(
        "/repos/M-Osugi1230/autonomous-development-engine/actions/runs?per_page=100"
    )
    if (
        not isinstance(controller_runs_payload, dict)
        or not isinstance(controller_runs_payload.get("workflow_runs"), list)
    ):
        raise ValueError("controller workflow runs response is invalid")
    controller_runs = [
        row
        for row in controller_runs_payload["workflow_runs"]
        if isinstance(row, dict)
    ]
    review_run = _select_review_run(
        controller_runs,
        pr_created_at=pr.get("created_at"),
        merged_at=pr.get("merged_at"),
    )

    return {
        "pull_request": number,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_sha": merge_sha,
        "changed_paths": changed_paths,
        "ci_run": _positive_int(ci_run.get("id"), field="target CI run"),
        "remote_gate_run": _positive_int(
            gate_run.get("id"),
            field="target gate run",
        ),
        "review_workflow_run": _positive_int(
            review_run.get("id"),
            field="review workflow run",
        ),
    }


def _validate_controller_provenance(
    *,
    planner_run: int,
    zero_touch_run: int,
    implementation_run: int,
    review_run: int,
    remote_monitor_run: int,
    runtime_run: int,
) -> None:
    expectations = (
        (planner_run, "ADE Autonomous Planner", ("push",)),
        (zero_touch_run, "ADE Zero-Touch Start", ("repository_dispatch",)),
        (implementation_run, "ADE Jules Cycle", ("repository_dispatch",)),
        (review_run, "ADE Multi-Agent Review", ("repository_dispatch",)),
        (remote_monitor_run, "ADE Remote PR Monitor", ("repository_dispatch",)),
        (runtime_run, "ADE Runtime Verification", ("repository_dispatch",)),
    )
    for run_id, name, events in expectations:
        validate_controller_run(
            _get_controller_run(run_id),
            expected_name=name,
            allow_events=events,
        )


def main() -> int:
    try:
        gh = GitHubClient()

        existing_evidence = _optional_json(gh, EVIDENCE_PATH)
        if existing_evidence is not None:
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.7-proof-evidence-already-frozen",
                "task_id": TASK_ID,
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0

        state, _ = gh.get_json_file(LIVE_STATE_PATH)
        metadata = state.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("phase") != PHASE:
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.7-proof-not-active",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0
        if (
            state.get("status") != "READY"
            or state.get("current_task_id") is not None
            or state.get("failed_task_ids") != []
            or TASK_ID not in state.get("completed_task_ids", [])
        ):
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.7-proof-not-terminal",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0

        goal, _ = gh.get_json_file(LIVE_PLANNING_GOAL_PATH)
        accepted_payload, _ = gh.get_json_file(LIVE_ACCEPTED_PLAN_PATH)
        campaign, _ = gh.get_json_file(LIVE_CAMPAIGN_PATH)
        remote_payload, _ = gh.get_json_file(LIVE_REMOTE_PATH)
        checkpoint, _ = gh.get_json_file(LIVE_CHECKPOINT_PATH)
        zero_touch, _ = gh.get_json_file(ZERO_TOUCH_PATH)
        planner_evidence, _ = gh.get_json_file(PLANNER_EVIDENCE_PATH)
        plan_payload, _ = gh.get_json_file(LIVE_PLAN_PATH)
        session_payload, _ = gh.get_json_file(LIVE_REVIEWER_SESSION_PATH)
        observation, _ = gh.get_json_file(LIVE_REVIEWER_OBSERVATION_PATH)
        contribution_payload, _ = gh.get_json_file(LIVE_REVIEWER_CONTRIBUTION_PATH)
        reconciliation_payload, _ = gh.get_json_file(LIVE_RECONCILIATION_PATH)
        clearance_payload, _ = gh.get_json_file(LIVE_CLEARANCE_PATH)

        accepted = AcceptedPlan.from_dict(accepted_payload)
        if accepted.status not in {"ACCEPTED", "RUNNING", "COMPLETED"}:
            raise ValueError("v1.7 AcceptedPlan status is invalid")
        if len(accepted.plan.tasks) != 1:
            raise ValueError("v1.7 proof requires exactly one task")
        task = accepted.plan.tasks[0]
        if task.task_id != TASK_ID or list(task.allowed_paths) != [EXPECTED_PATH]:
            raise ValueError("v1.7 AcceptedPlan scope is not exact")
        if campaign.get("status") != "COMPLETED":
            raise ValueError("v1.7 Campaign is not COMPLETED")
        if campaign.get("task_ids") != [TASK_ID] or campaign.get("completed_task_ids") != [TASK_ID]:
            raise ValueError("v1.7 Campaign task terminal set is invalid")

        plan = MultiAgentPlan.from_dict(plan_payload)
        session = RoleSession.from_dict(session_payload)
        contribution = AgentContribution.from_dict(contribution_payload)
        clearance = ReviewClearance.from_dict(clearance_payload)
        reviewer = next(
            (item for item in plan.assignments if item.role is AgentRole.REVIEWER),
            None,
        )
        implementer = next(
            (item for item in plan.assignments if item.role is AgentRole.IMPLEMENTER),
            None,
        )
        if reviewer is None or implementer is None or len(plan.assignments) != 2:
            raise ValueError("v1.7 proof requires implementer + reviewer assignments")
        if contribution.verdict is not ContributionVerdict.CLEAR:
            raise ValueError("v1.7 reviewer contribution is not CLEAR")
        if session.state is not RoleSessionState.COMPLETED:
            raise ValueError("v1.7 reviewer role session is not COMPLETED")
        implementer_session = checkpoint.get("provider_session_id")
        if (
            not isinstance(implementer_session, str)
            or not implementer_session
            or not isinstance(session.provider_session_id, str)
            or not session.provider_session_id
            or implementer_session == session.provider_session_id
        ):
            raise ValueError("v1.7 independent reviewer session proof is invalid")

        reconstructed_reconciliation = reconcile_agent_contributions(
            plan=plan,
            contributions=(contribution,),
        )
        if reconstructed_reconciliation.disposition is not ReconciliationDisposition.CLEAR:
            raise ValueError("v1.7 review reconciliation is not CLEAR")
        if reconciliation_payload != reconstructed_reconciliation.canonical_dict():
            raise ValueError("v1.7 stored reconciliation drift")

        reconstructed_clearance = build_review_clearance(
            accepted_plan=accepted,
            plan=plan,
            role_session=session,
            contribution=contribution,
            reconciliation=reconstructed_reconciliation,
            reviewed_head_sha=clearance.reviewed_head_sha,
            pull_request_number=clearance.pull_request_number,
        )
        if clearance_payload != reconstructed_clearance.canonical_dict():
            raise ValueError("v1.7 review clearance drift")

        remote = RemoteExecutionReceipt.from_dict(remote_payload)
        if (
            remote.status != "MERGED"
            or remote.task_id != TASK_ID
            or remote.target_repository != TARGET_REPOSITORY
        ):
            raise ValueError("v1.7 remote execution is not the trusted merged task")
        recovery = _optional_json(gh, RECOVERY_PATH)
        if isinstance(recovery, dict) and recovery.get("task_id") == TASK_ID:
            raise ValueError("v1.7 proof has a recovery record")

        contract_path = f".autodev/runtime-verification/{TASK_ID}/contract.json"
        receipt_path = f".autodev/runtime-verification/{TASK_ID}/receipt.json"
        report_path = f".autodev/runtime-verification/{TASK_ID}/report.json"
        runtime_provenance_path = (
            f".autodev/runtime-verification/{TASK_ID}/provenance.json"
        )
        contract_payload, _ = gh.get_json_file(contract_path)
        receipt_payload, _ = gh.get_json_file(receipt_path)
        report_wrapper, _ = gh.get_json_file(report_path)
        runtime_provenance, _ = gh.get_json_file(runtime_provenance_path)
        contract = RuntimeVerificationContract.from_dict(contract_payload)
        receipt = RuntimeVerificationReceipt.from_dict(receipt_payload)
        report = runtime_report_from_wrapper(report_wrapper)
        re_evaluated = evaluate_runtime_verification(contract, report.results)
        if (
            receipt.status != "VERIFIED"
            or receipt.dispatch_count != 1
            or receipt.task_id != TASK_ID
            or report.disposition is not RuntimeVerificationDisposition.VERIFIED
            or re_evaluated.canonical_dict() != report.canonical_dict()
        ):
            raise ValueError("v1.7 Runtime Verification is not exact VERIFIED evidence")

        observations = _target_observations(
            remote=remote,
            expected_base_sha=plan.source_sha,
            expected_head_sha=clearance.reviewed_head_sha,
        )
        if contract.source_sha != observations["merge_sha"]:
            raise ValueError("runtime contract does not bind target merge SHA")
        if receipt.source_sha != observations["merge_sha"]:
            raise ValueError("runtime receipt does not bind target merge SHA")
        if runtime_provenance.get("trusted_merge_sha") != observations["merge_sha"]:
            raise ValueError("runtime provenance does not bind target merge SHA")
        if runtime_provenance.get("pull_request_head_sha") != observations["head_sha"]:
            raise ValueError("runtime provenance does not bind reviewed PR head")

        planner_run = _positive_int(
            planner_evidence.get("workflow_run_id"),
            field="planner workflow run",
        )
        zero_touch_run = _positive_int(
            zero_touch.get("run_id"),
            field="zero-touch workflow run",
        )
        implementation_run = _positive_int(
            runtime_provenance.get("implementation_workflow_run_id"),
            field="implementation workflow run",
        )
        remote_monitor_run = _positive_int(
            runtime_provenance.get("remote_monitor_workflow_run_id"),
            field="remote monitor workflow run",
        )
        runtime_run = _positive_int(
            runtime_provenance.get("runtime_workflow_run_id"),
            field="runtime workflow run",
        )
        review_run = observations["review_workflow_run"]
        _validate_controller_provenance(
            planner_run=planner_run,
            zero_touch_run=zero_touch_run,
            implementation_run=implementation_run,
            review_run=review_run,
            remote_monitor_run=remote_monitor_run,
            runtime_run=runtime_run,
        )

        provenance_snapshot = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "planner_evidence": planner_evidence,
            "zero_touch_receipt": zero_touch,
            "runtime_provenance": runtime_provenance,
            "target_pull_request": observations,
        }
        evidence = {
            "schema_version": 1,
            "version": "v1.7",
            "target_repository": TARGET_REPOSITORY,
            "human_authored_per_task_work_items": False,
            "manual_campaign_progress_after_goal_submission": False,
            "execution_provenance_clean": True,
            "planning": {
                "request_id": goal.get("request_id"),
                "campaign_id": campaign.get("campaign_id"),
                "planner_workflow_run": planner_run,
                "accepted_plan_fingerprint": accepted.fingerprint,
                "source_sha": plan.source_sha,
            },
            "task": {
                "task_id": TASK_ID,
                "zero_touch_run": zero_touch_run,
                "implementation_run": implementation_run,
                "pull_request": observations["pull_request"],
                "ci_run": observations["ci_run"],
                "remote_gate_run": observations["remote_gate_run"],
                "remote_monitor_run": remote_monitor_run,
                "head_sha": observations["head_sha"],
                "merge_sha": observations["merge_sha"],
                "changed_paths": observations["changed_paths"],
            },
            "multi_agent_review": {
                "review_workflow_run": review_run,
                "plan_fingerprint": plan.fingerprint(),
                "reviewer_assignment_id": reviewer.assignment_id,
                "reviewer_assignment_fingerprint": reviewer.fingerprint(),
                "reviewer_role_session_fingerprint": session.fingerprint(),
                "reviewer_provider_id": reviewer.provider_id,
                "contribution_fingerprint": contribution.fingerprint(),
                "reconciliation_fingerprint": reconstructed_reconciliation.fingerprint(),
                "clearance_fingerprint": clearance.fingerprint(),
                "verdict": "CLEAR",
                "correction_rounds": 0,
            },
            "runtime_verification": {
                "workflow_run": runtime_run,
                "manual_workflow_dispatch": False,
                "verification_id": receipt.verification_id,
                "contract_path": contract_path,
                "receipt_path": receipt_path,
                "report_path": report_path,
                "report_fingerprint": report.fingerprint(),
            },
        }

        proof_artifacts = (
            (PLANNING_GOAL_PATH, dict(goal)),
            (ACCEPTED_PLAN_PATH, dict(accepted_payload)),
            (CAMPAIGN_PATH, dict(campaign)),
            (STATE_PATH, dict(state)),
            (REMOTE_PATH, dict(remote_payload)),
            (CHECKPOINT_PATH, dict(checkpoint)),
            (PLAN_PATH, dict(plan_payload)),
            (REVIEWER_SESSION_PATH, dict(session_payload)),
            (REVIEWER_OBSERVATION_PATH, dict(observation)),
            (REVIEWER_CONTRIBUTION_PATH, dict(contribution_payload)),
            (RECONCILIATION_PATH, dict(reconciliation_payload)),
            (CLEARANCE_PATH, dict(clearance_payload)),
            (PROVENANCE_PATH, provenance_snapshot),
            (EVIDENCE_PATH, evidence),
        )
        for path, payload in proof_artifacts:
            _write_local(path, payload)

        audit_result = audit_v1_7(Path("."))
        if not audit_result.get("v1_7_multi_agent_graduated"):
            raise ValueError("v1.7 Graduation audit rejected assembled proof evidence")

        for path, payload in proof_artifacts:
            _write_once_json(
                gh,
                path,
                payload,
                message=f"v1.7: freeze proof artifact {Path(path).name}",
            )

        result = {
            "schema_version": 1,
            "state": "EVIDENCE_FROZEN",
            "task_id": TASK_ID,
            "pull_request": observations["pull_request"],
            "merge_sha": observations["merge_sha"],
            "review_workflow_run": review_run,
            "runtime_workflow_run": runtime_run,
            "clearance_fingerprint": clearance.fingerprint(),
            "audit": audit_result,
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        GitHubError,
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        result = {
            "schema_version": 1,
            "state": "FAILED",
            "reason": str(exc).splitlines()[0][:256],
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

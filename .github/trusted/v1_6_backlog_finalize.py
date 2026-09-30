from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_extraction import extract_verified_memory_followup_candidate
from ade.autonomous_backlog_feedback import build_verified_backlog_retirement
from ade.autonomous_backlog_goal import BacklogPlanningPolicy, build_planning_goal_handoff
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.development_memory import MemoryKind
from ade.development_memory_store import DevelopmentMemoryStore
from ade.remote_execution import RemoteExecutionReceipt
from github_client import GitHubClient, GitHubError
from scripts.v1_6_autonomous_backlog_audit import (
    ACCEPTED_PLAN_PATH,
    BACKLOG_PATH,
    CAMPAIGN_PATH,
    EVIDENCE_PATH,
    HANDOFF_PATH,
    PLANNING_GOAL_PATH,
    POLICY_PATH,
    POST_RESOLUTION_PATH,
    POST_SELECTION_PATH,
    REMOTE_PATH,
    RESOLUTION_PATH,
    RETIREMENT_PATH,
    SELECTION_PATH,
    SOURCE_STORE_PATH,
    STATE_PATH,
    TARGET_REPOSITORY,
    audit as audit_v1_6,
)
from v1_5_graduation_finalize import (
    _api_json,
    select_remote_gate_run,
    select_target_ci_run,
)

LIVE_PLANNING_GOAL_PATH = ".autodev/planning-goal.json"
LIVE_ACCEPTED_PLAN_PATH = ".autodev/accepted-plan.json"
LIVE_CAMPAIGN_PATH = ".autodev/campaign.json"
LIVE_STATE_PATH = ".autodev/state.json"
LIVE_REMOTE_PATH = ".autodev/runtime/remote-execution.json"
ZERO_TOUCH_PATH = ".autodev/runtime/zero-touch-start.json"
RECOVERY_PATH = ".autodev/runtime/recovery.json"
PROOF_PROVENANCE_PATH = ".autodev/autonomous-backlog/proof/provenance.json"
RESULT_PATH = Path(".autodev/runtime/v1-6-backlog-finalize-result.json")
SOURCE_TASK_ID = "v15mem2-001"
PHASE = "v1.6-autonomous-backlog"


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _proof_policy() -> BacklogPlanningPolicy:
    return BacklogPlanningPolicy(
        repository=TARGET_REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        request_prefix="abgproof",
        min_tasks=1,
        max_tasks=1,
    )


def _load_local(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_local(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_once_json(
    gh: GitHubClient,
    path: str,
    payload: dict[str, Any],
    *,
    message: str,
) -> None:
    try:
        existing, _ = gh.get_json_file(path)
    except GitHubError as exc:
        if "GitHub HTTP 404:" not in str(exc):
            raise
        gh.put_json_file(path, payload, sha=None, message=message)
        return
    if existing != payload:
        raise ValueError(f"immutable v1.6 proof artifact drift: {path}")


def _v1_6_already_graduated(state_payload: object) -> bool:
    if not isinstance(state_payload, dict):
        raise ValueError("ProjectState must be a JSON object")
    metadata = state_payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return metadata.get("v1_6_graduated") is True


def _positive_int(value: object, *, field: str) -> int:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise ValueError(f"{field} must be a positive integer")


def _reconstruct_chain(
    *,
    source_store_payload: dict[str, Any],
) -> dict[str, Any]:
    source_store = DevelopmentMemoryStore.from_dict(source_store_payload)
    source_records = [
        record
        for record in source_store.ledger.records
        if record.task_id == SOURCE_TASK_ID
        and record.repository == TARGET_REPOSITORY
        and record.kind is MemoryKind.VERIFIED_OUTCOME
    ]
    if len(source_records) != 1:
        raise ValueError("v1.6 proof source memory is not uniquely bound to proof002")
    source_record = source_records[0]

    candidate = extract_verified_memory_followup_candidate(
        store_path=SOURCE_STORE_PATH,
        store_payload=source_store.canonical_dict(),
        memory_id=source_record.memory_id,
        source_phase=PHASE,
    )
    backlog = AutonomousBacklog(candidates=(candidate,))
    resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={TARGET_REPOSITORY: source_record.source_sha},
    )
    selection = select_next_backlog_candidate(
        backlog,
        resolution,
        repository=TARGET_REPOSITORY,
        source_sha=source_record.source_sha,
    )
    policy = _proof_policy()
    handoff = build_planning_goal_handoff(
        backlog,
        resolution,
        selection,
        policy=policy,
    )
    return {
        "source_store": source_store,
        "source_record": source_record,
        "candidate": candidate,
        "backlog": backlog,
        "resolution": resolution,
        "selection": selection,
        "policy": policy,
        "handoff": handoff,
    }


def _target_observations(
    *,
    remote: RemoteExecutionReceipt,
    expected_base_sha: str,
    expected_changed_paths: tuple[str, ...],
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
        raise ValueError("target pull request base SHA does not match backlog source SHA")
    if not isinstance(head_sha, str) or len(head_sha) != 40:
        raise ValueError("target pull request head SHA is invalid")
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
    if changed_paths != sorted(expected_changed_paths):
        raise ValueError(f"target pull request scope is not exact: {changed_paths}")

    runs_payload = _api_json(
        f"/repos/{TARGET_REPOSITORY}/actions/runs?per_page=100"
    )
    if (
        not isinstance(runs_payload, dict)
        or not isinstance(runs_payload.get("workflow_runs"), list)
    ):
        raise ValueError("target workflow runs response is invalid")
    runs = [
        row for row in runs_payload["workflow_runs"] if isinstance(row, dict)
    ]
    ci_run = select_target_ci_run(
        runs,
        head_sha=head_sha,
        pr_created_at=pr.get("created_at"),
        merged_at=pr.get("merged_at"),
    )
    gate_run = select_remote_gate_run(
        runs,
        ci_run=ci_run,
        merged_at=pr.get("merged_at"),
    )
    return {
        "pull_request": number,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_sha": merge_sha,
        "changed_paths": changed_paths,
        "ci_run": _positive_int(ci_run.get("id"), field="target CI run id"),
        "remote_gate_run": _positive_int(
            gate_run.get("id"),
            field="remote gate run id",
        ),
    }


def _optional_json(
    gh: GitHubClient,
    path: str,
) -> dict[str, Any] | None:
    try:
        payload, _ = gh.get_json_file(path)
        return payload
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise


def _optional_remote_recovery(gh: GitHubClient) -> dict[str, Any] | None:
    try:
        payload, _ = gh.get_json_file(RECOVERY_PATH)
        return payload
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise


def main() -> int:
    try:
        gh = GitHubClient()
        live_state, _ = gh.get_json_file(LIVE_STATE_PATH)
        metadata = live_state.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if _v1_6_already_graduated(live_state):
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.6-already-graduated",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if metadata.get("phase") != PHASE:
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.6-proof-not-active",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if (
            live_state.get("status") != "READY"
            or live_state.get("current_task_id") is not None
            or live_state.get("failed_task_ids") != []
        ):
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.6-proof-not-terminal",
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        source_store_payload, _ = gh.get_json_file(SOURCE_STORE_PATH)
        chain = _reconstruct_chain(source_store_payload=source_store_payload)
        candidate = chain["candidate"]
        handoff = chain["handoff"]

        stored_expectations = (
            (BACKLOG_PATH, chain["backlog"].canonical_dict()),
            (RESOLUTION_PATH, chain["resolution"].canonical_dict()),
            (SELECTION_PATH, chain["selection"].canonical_dict()),
            (POLICY_PATH, chain["policy"].canonical_dict()),
            (HANDOFF_PATH, handoff.canonical_dict()),
        )
        for path, expected in stored_expectations:
            stored, _ = gh.get_json_file(path)
            if stored != expected:
                raise ValueError(f"stored v1.6 artifact drift: {path}")

        live_goal, _ = gh.get_json_file(LIVE_PLANNING_GOAL_PATH)
        live_accepted, _ = gh.get_json_file(LIVE_ACCEPTED_PLAN_PATH)
        live_campaign, _ = gh.get_json_file(LIVE_CAMPAIGN_PATH)
        live_remote_payload, _ = gh.get_json_file(LIVE_REMOTE_PATH)
        zero_touch, _ = gh.get_json_file(ZERO_TOUCH_PATH)

        if live_goal != handoff.request.to_dict():
            raise ValueError("live PlanningGoal does not match trusted backlog handoff")
        if live_campaign.get("campaign_id") != handoff.request.campaign_id:
            raise ValueError("live Campaign does not match backlog handoff")
        if live_campaign.get("status") != "COMPLETED":
            raise ValueError("v1.6 Campaign is not COMPLETED")

        plan = live_accepted.get("plan")
        plan = plan if isinstance(plan, dict) else {}
        tasks = plan.get("tasks")
        tasks = tasks if isinstance(tasks, list) else []
        if live_accepted.get("status") != "ACCEPTED" or len(tasks) != 1:
            raise ValueError("v1.6 AcceptedPlan is not a one-task accepted plan")
        task = tasks[0] if isinstance(tasks[0], dict) else {}
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("v1.6 task identity is missing")
        allowed_paths = task.get("allowed_paths")
        if (
            not isinstance(allowed_paths, list)
            or len(allowed_paths) != 1
            or not isinstance(allowed_paths[0], str)
            or not allowed_paths[0].startswith("tests/")
            or ".." in allowed_paths[0].split("/")
            or "\\" in allowed_paths[0]
        ):
            raise ValueError("v1.6 AcceptedPlan must allow exactly one normalized tests/ path")
        new_paths = task.get("new_paths", [])
        human_only = task.get("human_only", False)
        if new_paths != [] or human_only is not False:
            raise ValueError("v1.6 AcceptedPlan violates bounded execution contract")

        if zero_touch.get("campaign_id") != handoff.request.campaign_id:
            raise ValueError("Zero-Touch receipt Campaign mismatch")
        if zero_touch.get("task_id") != task_id:
            raise ValueError("Zero-Touch receipt task mismatch")
        if zero_touch.get("status") != "DISPATCHED":
            raise ValueError("Zero-Touch receipt is not DISPATCHED")
        if zero_touch.get("dispatch_count") != 1:
            raise ValueError("Zero-Touch dispatch count is not one")
        if zero_touch.get("source") != "repository_dispatch":
            raise ValueError("Zero-Touch proof was not repository-dispatch started")
        zero_touch_run = _positive_int(
            zero_touch.get("run_id"),
            field="Zero-Touch workflow run",
        )

        remote = RemoteExecutionReceipt.from_dict(live_remote_payload)
        if (
            remote.status != "MERGED"
            or remote.task_id != task_id
            or remote.target_repository != TARGET_REPOSITORY
        ):
            raise ValueError("v1.6 remote execution is not the trusted merged task")

        recovery = _optional_remote_recovery(gh)
        if isinstance(recovery, dict) and recovery.get("task_id") == task_id:
            raise ValueError("v1.6 proof has a recovery record and cannot retire cleanly")

        contract_path = f".autodev/runtime-verification/{task_id}/contract.json"
        receipt_path = f".autodev/runtime-verification/{task_id}/receipt.json"
        report_path = f".autodev/runtime-verification/{task_id}/report.json"
        runtime_provenance_path = (
            f".autodev/runtime-verification/{task_id}/provenance.json"
        )
        contract = _optional_json(gh, contract_path)
        receipt = _optional_json(gh, receipt_path)
        report_wrapper = _optional_json(gh, report_path)
        runtime_provenance = _optional_json(gh, runtime_provenance_path)
        missing_runtime = [
            path
            for path, payload in (
                (contract_path, contract),
                (receipt_path, receipt),
                (report_path, report_wrapper),
                (runtime_provenance_path, runtime_provenance),
            )
            if payload is None
        ]
        if missing_runtime:
            payload = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "runtime-evidence-not-ready",
                "missing_paths": missing_runtime,
            }
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        assert contract is not None
        assert receipt is not None
        assert report_wrapper is not None
        assert runtime_provenance is not None
        if receipt.get("status") != "VERIFIED":
            raise ValueError("v1.6 Runtime Verification is not VERIFIED")
        if receipt.get("task_id") != task_id or receipt.get("dispatch_count") != 1:
            raise ValueError("v1.6 runtime receipt task/dispatch binding is invalid")

        observations = _target_observations(
            remote=remote,
            expected_base_sha=candidate.source_sha,
            expected_changed_paths=tuple(allowed_paths),
        )
        if contract.get("source_sha") != observations["merge_sha"]:
            raise ValueError("runtime contract does not bind trusted merge SHA")
        if receipt.get("source_sha") != observations["merge_sha"]:
            raise ValueError("runtime receipt does not bind trusted merge SHA")
        if runtime_provenance.get("task_id") != task_id:
            raise ValueError("runtime provenance task mismatch")
        if runtime_provenance.get("pull_request_number") != observations["pull_request"]:
            raise ValueError("runtime provenance PR number mismatch")
        if runtime_provenance.get("pull_request_head_sha") != observations["head_sha"]:
            raise ValueError("runtime provenance PR head SHA mismatch")
        if runtime_provenance.get("trusted_merge_sha") != observations["merge_sha"]:
            raise ValueError("runtime provenance merge SHA mismatch")

        planner_path = (
            f".autodev/planner-evidence/{handoff.request.request_id}.json"
        )
        planner_evidence, _ = gh.get_json_file(planner_path)
        if planner_evidence.get("request") != handoff.request.to_dict():
            raise ValueError("Planner evidence request does not match backlog Goal")
        if planner_evidence.get("campaign_id") != handoff.request.campaign_id:
            raise ValueError("Planner evidence Campaign mismatch")
        if planner_evidence.get("planning_only") is not True:
            raise ValueError("Planner crossed the planning-only boundary")
        if (
            planner_evidence.get("accepted_plan_fingerprint")
            != live_accepted.get("fingerprint")
        ):
            raise ValueError("Planner/AcceptedPlan fingerprint mismatch")
        planner_run = _positive_int(
            planner_evidence.get("workflow_run_id"),
            field="Planner workflow run",
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

        proof_goal = dict(live_goal)
        proof_accepted = dict(live_accepted)
        proof_campaign = dict(live_campaign)
        proof_state = dict(live_state)
        proof_remote = dict(live_remote_payload)

        retirement = build_verified_backlog_retirement(
            backlog=chain["backlog"],
            handoff=handoff,
            campaign_payload=proof_campaign,
            state_payload=proof_state,
            remote_execution_payload=proof_remote,
            runtime_contract_payload=contract,
            runtime_receipt_payload=receipt,
            runtime_report_wrapper_payload=report_wrapper,
            handoff_path=HANDOFF_PATH,
            campaign_path=CAMPAIGN_PATH,
            state_path=STATE_PATH,
            remote_execution_path=REMOTE_PATH,
            runtime_contract_path=contract_path,
            runtime_receipt_path=receipt_path,
            runtime_report_path=report_path,
        )
        post_resolution = resolve_autonomous_backlog(
            chain["backlog"],
            current_sources={
                TARGET_REPOSITORY: retirement.verified_source_sha
            },
            retirements=(retirement,),
        )
        post_selection = select_next_backlog_candidate(
            chain["backlog"],
            post_resolution,
            repository=TARGET_REPOSITORY,
            source_sha=retirement.verified_source_sha,
        )
        if post_selection.selected_candidate_id is not None:
            raise ValueError("retired backlog candidate remains selectable")

        provenance_snapshot = {
            "schema_version": 1,
            "task_id": task_id,
            "planner_workflow_run": planner_run,
            "zero_touch_receipt": zero_touch,
            "runtime_provenance": runtime_provenance,
            "target_pull_request": observations,
        }

        evidence = {
            "schema_version": 1,
            "version": "v1.6",
            "target_repository": TARGET_REPOSITORY,
            "human_authored_per_task_work_items": False,
            "manual_campaign_progress_after_goal_submission": False,
            "execution_provenance_clean": True,
            "source_memory": {
                "path": SOURCE_STORE_PATH,
                "memory_id": chain["source_record"].memory_id,
                "memory_fingerprint": chain["source_record"].fingerprint(),
                "store_fingerprint": chain["source_store"].fingerprint(),
            },
            "candidate": {
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.fingerprint(),
                "backlog_fingerprint": chain["backlog"].fingerprint(),
            },
            "planning": {
                "resolution_fingerprint": chain["resolution"].fingerprint(),
                "selection_fingerprint": chain["selection"].fingerprint(),
                "policy_fingerprint": chain["policy"].fingerprint(),
                "handoff_fingerprint": handoff.fingerprint(),
                "request_id": handoff.request.request_id,
                "campaign_id": handoff.request.campaign_id,
                "planner_workflow_run": planner_run,
            },
            "task": {
                "task_id": task_id,
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
            "runtime_verification": {
                "workflow_run": runtime_run,
                "manual_workflow_dispatch": False,
                "contract_path": contract_path,
                "receipt_path": receipt_path,
                "report_path": report_path,
                "report_fingerprint": report_wrapper.get("report_fingerprint"),
            },
            "retirement": {
                "retirement_id": retirement.retirement_id,
                "retirement_fingerprint": retirement.fingerprint(),
                "candidate_id": candidate.candidate_id,
            },
            "post_retirement": {
                "resolution_fingerprint": post_resolution.fingerprint(),
                "selection_fingerprint": post_selection.fingerprint(),
                "selected_candidate_id": None,
            },
        }

        local_artifacts = (
            (PLANNING_GOAL_PATH, proof_goal),
            (ACCEPTED_PLAN_PATH, proof_accepted),
            (CAMPAIGN_PATH, proof_campaign),
            (STATE_PATH, proof_state),
            (REMOTE_PATH, proof_remote),
            (PROOF_PROVENANCE_PATH, provenance_snapshot),
            (RETIREMENT_PATH, retirement.canonical_dict()),
            (POST_RESOLUTION_PATH, post_resolution.canonical_dict()),
            (POST_SELECTION_PATH, post_selection.canonical_dict()),
            (EVIDENCE_PATH, evidence),
        )
        for path, payload in local_artifacts:
            _write_local(path, payload)

        audit_result = audit_v1_6(Path("."))
        if not audit_result.get("v1_6_autonomous_backlog_graduated"):
            raise ValueError("v1.6 Graduation audit rejected assembled proof evidence")

        for path, payload in local_artifacts:
            _write_once_json(
                gh,
                path,
                payload,
                message=f"v1.6: freeze proof artifact {Path(path).name}",
            )

        result = {
            "schema_version": 1,
            "state": "EVIDENCE_FROZEN",
            "task_id": task_id,
            "candidate_id": candidate.candidate_id,
            "retirement_id": retirement.retirement_id,
            "pull_request": observations["pull_request"],
            "merge_sha": observations["merge_sha"],
            "audit": audit_result,
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    except (GitHubError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
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

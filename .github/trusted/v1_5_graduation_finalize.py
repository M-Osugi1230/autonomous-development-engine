from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.development_memory_store import DevelopmentMemoryStore
from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import RuntimeVerificationContract
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from github_client import GitHubClient, GitHubError
from scripts.v1_5_development_memory_audit import audit

RESULT_PATH = Path(".autodev/runtime/v1-5-graduation-finalize-result.json")
EVIDENCE_PATH = ".autodev/campaign-evidence/v1.5-development-memory-proof-002.json"
BOOTSTRAP_PATH = ".autodev/campaign-evidence/v1.5-development-memory-proof-001-bootstrap.json"
PLANNER_PATH = ".autodev/planner-evidence/v1.5-development-memory-proof-002.json"
ZERO_TOUCH_PATH = ".autodev/runtime/zero-touch-start.json"
CHECKPOINT_PATH = ".autodev/runtime/checkpoint.json"
REMOTE_PATH = ".autodev/runtime/remote-execution.json"
STATE_PATH = ".autodev/state.json"
CAMPAIGN_PATH = ".autodev/campaign.json"
ACCEPTED_PLAN_PATH = ".autodev/accepted-plan.json"
STORE_PATH = ".autodev/development-memory.json"
CONTRACT_PATH = ".autodev/runtime-verification/v15mem2-001/contract.json"
RECEIPT_PATH = ".autodev/runtime-verification/v15mem2-001/receipt.json"
TARGET_PATH = ".autodev/runtime-verification/v15mem2-001/target.json"
REPORT_PATH = ".autodev/runtime-verification/v15mem2-001/report.json"
PROVENANCE_PATH = ".autodev/runtime-verification/v15mem2-001/provenance.json"
RECOVERY_PATH = ".autodev/runtime/recovery.json"

TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
CONTROLLER_REPOSITORY = "M-Osugi1230/autonomous-development-engine"
REQUEST_ID = "v1.5-development-memory-proof-002"
CAMPAIGN_ID = "v1.5-development-memory-campaign-002"
TASK_ID = "v15mem2-001"
BOOTSTRAP_MEMORY_ID = "mem-3d6660d55ad11cf3941ee9fb"
BOOTSTRAP_MEMORY_FINGERPRINT = "72a5c70e6eed1f6af559c3182a2f8ccffea6c340eeb5163aba549cde38456e99"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _optional_json(path: str) -> dict[str, Any] | None:
    file = Path(path)
    if not file.exists():
        return None
    return _load_json(path)


def _api_json(path: str) -> Any:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ADE-v1.5-Graduation-Finalizer/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
        "Cache-Control": "no-cache",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request("https://api.github.com" + path, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"GitHub network error: {exc.reason}") from exc
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _positive_int(value: object, field: str) -> int:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise ValueError(f"{field} must be a positive integer")


def select_target_ci_run(
    runs: list[dict[str, Any]],
    *,
    head_sha: str,
    pr_created_at: str,
    merged_at: str,
) -> dict[str, Any]:
    start = _parse_time(pr_created_at) - timedelta(seconds=30)
    end = _parse_time(merged_at) + timedelta(seconds=30)
    candidates: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("name") != "Phase 1 and 2 checks":
            continue
        if run.get("event") != "pull_request" or run.get("conclusion") != "success":
            continue
        if run.get("head_sha") != head_sha:
            continue
        created = _parse_time(run.get("created_at"))
        if start <= created <= end:
            candidates.append(run)
    if not candidates:
        raise ValueError("no successful target pull-request CI run is bound to the PR head SHA")
    return max(candidates, key=lambda row: _positive_int(row.get("id"), "target CI run id"))


def select_remote_gate_run(
    runs: list[dict[str, Any]],
    *,
    ci_run: dict[str, Any],
    merged_at: str,
) -> dict[str, Any]:
    start = _parse_time(ci_run.get("updated_at")) - timedelta(seconds=10)
    merge_time = _parse_time(merged_at)
    end = merge_time + timedelta(minutes=2)
    candidates: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("name") != "ADE Remote PR Gate":
            continue
        if run.get("event") != "workflow_run" or run.get("conclusion") != "success":
            continue
        created = _parse_time(run.get("created_at"))
        if start <= created <= end:
            candidates.append(run)
    if not candidates:
        raise ValueError("no successful trusted remote gate run is bound to the CI/merge window")
    return min(
        candidates,
        key=lambda row: (
            abs((_parse_time(row.get("created_at")) - merge_time).total_seconds()),
            -_positive_int(row.get("id"), "remote gate run id"),
        ),
    )


def validate_controller_run(
    run: dict[str, Any],
    *,
    expected_name: str | tuple[str, ...],
    allow_events: tuple[str, ...],
) -> None:
    names = (expected_name,) if isinstance(expected_name, str) else expected_name
    if run.get("name") not in names:
        raise ValueError(f"controller workflow name mismatch: {run.get('name')}")
    if run.get("event") not in allow_events:
        raise ValueError(f"controller workflow event is not trusted: {run.get('event')}")
    if run.get("event") == "workflow_dispatch":
        raise ValueError("manual workflow_dispatch is not allowed in graduation proof")
    if run.get("conclusion") != "success":
        raise ValueError(f"controller workflow did not succeed: {run.get('name')}")


def _get_controller_run(run_id: int) -> dict[str, Any]:
    payload = _api_json(f"/repos/{CONTROLLER_REPOSITORY}/actions/runs/{run_id}")
    if not isinstance(payload, dict):
        raise ValueError("controller workflow run response must be an object")
    return payload


def _target_observations(remote: RemoteExecutionReceipt) -> dict[str, Any]:
    number = remote.pull_request_number
    pr = _api_json(f"/repos/{TARGET_REPOSITORY}/pulls/{number}")
    if not isinstance(pr, dict):
        raise ValueError("target pull request response must be an object")
    files = _api_json(f"/repos/{TARGET_REPOSITORY}/pulls/{number}/files?per_page=100")
    if not isinstance(files, list):
        raise ValueError("target pull request files response must be a list")
    changed_paths = [
        item.get("filename")
        for item in files
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    ]
    if changed_paths != ["tests/test_models.py"]:
        raise ValueError(f"target pull request scope is not exact: {changed_paths}")

    head = pr.get("head")
    base = pr.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ValueError("target pull request head/base metadata is missing")
    head_sha = head.get("sha")
    base_sha = base.get("sha")
    merge_sha = pr.get("merge_commit_sha")
    if not isinstance(head_sha, str) or SHA40.fullmatch(head_sha) is None:
        raise ValueError("target pull request head SHA is invalid")
    if not isinstance(base_sha, str) or SHA40.fullmatch(base_sha) is None:
        raise ValueError("target pull request base SHA is invalid")
    if not isinstance(merge_sha, str) or SHA40.fullmatch(merge_sha) is None:
        raise ValueError("target pull request merge SHA is invalid")
    if not pr.get("merged_at") or pr.get("state") != "closed":
        raise ValueError("target pull request is not merged")
    if pr.get("html_url") != remote.pull_request_url:
        raise ValueError("target pull request URL does not match durable remote receipt")

    runs_payload = _api_json(f"/repos/{TARGET_REPOSITORY}/actions/runs?per_page=100")
    if not isinstance(runs_payload, dict) or not isinstance(runs_payload.get("workflow_runs"), list):
        raise ValueError("target workflow runs response is invalid")
    runs = [row for row in runs_payload["workflow_runs"] if isinstance(row, dict)]
    ci_run = select_target_ci_run(
        runs,
        head_sha=head_sha,
        pr_created_at=pr.get("created_at"),
        merged_at=pr.get("merged_at"),
    )
    gate_run = select_remote_gate_run(runs, ci_run=ci_run, merged_at=pr.get("merged_at"))
    return {
        "pull_request": number,
        "pr": pr,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_sha": merge_sha,
        "changed_paths": changed_paths,
        "ci_run": _positive_int(ci_run.get("id"), "target CI run id"),
        "remote_gate_run": _positive_int(gate_run.get("id"), "remote gate run id"),
    }


def build_candidate_evidence(
    *,
    state: dict[str, Any],
    campaign: dict[str, Any],
    planner: dict[str, Any],
    zero_touch: dict[str, Any],
    checkpoint: dict[str, Any],
    remote: RemoteExecutionReceipt,
    contract: dict[str, Any],
    receipt: dict[str, Any],
    target: dict[str, Any],
    report_wrapper: dict[str, Any],
    provenance: dict[str, Any],
    target_observations: dict[str, Any],
) -> dict[str, Any]:
    memory = planner.get("development_memory")
    if not isinstance(memory, dict):
        raise ValueError("planner Development Memory evidence is missing")
    ids = memory.get("memory_ids")
    fingerprints = memory.get("memory_fingerprints")
    if not isinstance(ids, list) or not isinstance(fingerprints, list):
        raise ValueError("planner memory IDs/fingerprints are missing")
    if BOOTSTRAP_MEMORY_ID not in ids:
        raise ValueError("proof001 durable memory ID was not reused")
    bootstrap_index = ids.index(BOOTSTRAP_MEMORY_ID)
    if bootstrap_index >= len(fingerprints) or fingerprints[bootstrap_index] != BOOTSTRAP_MEMORY_FINGERPRINT:
        raise ValueError("proof001 durable memory fingerprint was not reused exactly")
    if memory.get("source_evidence_path") != STORE_PATH:
        raise ValueError("planner did not source memory from the durable store")
    if memory.get("authority") != "advisory-data-only":
        raise ValueError("planner memory authority is not advisory-only")
    for key in ("execution_authority", "memory_may_expand_scope", "memory_may_override_acceptance"):
        if memory.get(key) is not False:
            raise ValueError(f"planner memory boundary violated: {key}")

    if state.get("status") != "READY" or state.get("current_task_id") is not None or state.get("failed_task_ids") != []:
        raise ValueError("ProjectState is not cleanly terminal")
    if campaign.get("campaign_id") != CAMPAIGN_ID or campaign.get("status") != "COMPLETED":
        raise ValueError("proof002 Campaign is not COMPLETED")
    if campaign.get("task_ids") != [TASK_ID] or campaign.get("completed_task_ids") != [TASK_ID]:
        raise ValueError("proof002 Campaign task completion does not reconcile")
    if checkpoint.get("task_id") != TASK_ID or checkpoint.get("state") != "COMPLETED":
        raise ValueError("proof002 provider checkpoint is not COMPLETED")
    session_id = checkpoint.get("provider_session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("proof002 provider session binding is missing")
    body = target_observations["pr"].get("body")
    if not isinstance(body, str) or f"https://jules.google.com/task/{session_id}" not in body:
        raise ValueError("target PR is not bound to the final provider session")

    if remote.task_id != TASK_ID or remote.status != "MERGED" or remote.target_repository != TARGET_REPOSITORY:
        raise ValueError("remote execution receipt is not the merged proof002 task")

    raw_contract = RuntimeVerificationContract.from_dict(contract)
    raw_receipt = RuntimeVerificationReceipt.from_dict(receipt)
    if raw_receipt.status != "VERIFIED" or raw_receipt.dispatch_count != 1:
        raise ValueError("runtime receipt is not a single-dispatch VERIFIED result")
    if raw_contract.source_sha != target_observations["merge_sha"] or raw_receipt.source_sha != target_observations["merge_sha"]:
        raise ValueError("runtime evidence is not bound to the trusted merge SHA")
    report = report_wrapper.get("report")
    if not isinstance(report, dict) or report.get("disposition") != "VERIFIED":
        raise ValueError("runtime report is not VERIFIED")

    if provenance.get("schema_version") != 1 or provenance.get("task_id") != TASK_ID:
        raise ValueError("runtime provenance is not bound to proof002")
    if provenance.get("trusted_merge_sha") != target_observations["merge_sha"]:
        raise ValueError("runtime provenance merge SHA mismatch")
    if provenance.get("pull_request_head_sha") != target_observations["head_sha"]:
        raise ValueError("runtime provenance PR head SHA mismatch")
    if provenance.get("pull_request_number") != target_observations["pull_request"]:
        raise ValueError("runtime provenance PR number mismatch")
    dependency_fingerprint = provenance.get("dependency_fingerprint")
    if not isinstance(dependency_fingerprint, str) or SHA256.fullmatch(dependency_fingerprint) is None:
        raise ValueError("runtime dependency fingerprint is invalid")

    planner_run = _positive_int(planner.get("workflow_run_id"), "planner workflow run")
    zero_touch_run = _positive_int(zero_touch.get("run_id"), "zero-touch workflow run")
    implementation_run = _positive_int(provenance.get("implementation_workflow_run_id"), "implementation workflow run")
    remote_monitor_run = _positive_int(provenance.get("remote_monitor_workflow_run_id"), "remote monitor workflow run")
    runtime_run = _positive_int(provenance.get("runtime_workflow_run_id"), "runtime workflow run")

    feedback = provenance.get("development_memory_feedback")
    if not isinstance(feedback, dict) or feedback.get("state") not in {"ADDED", "UNCHANGED"}:
        raise ValueError("runtime durable memory feedback is incomplete")

    return {
        "schema_version": 1,
        "version": "v1.5",
        "request_id": REQUEST_ID,
        "campaign_id": CAMPAIGN_ID,
        "target_repository": TARGET_REPOSITORY,
        "human_authored_per_task_work_items": False,
        "execution_provenance_clean": True,
        "planner": {
            "provider": planner.get("provider"),
            "workflow_run": planner_run,
            "planning_only": planner.get("planning_only"),
            "accepted_plan_fingerprint": planner.get("accepted_plan_fingerprint"),
            "proposal_fingerprint": planner.get("proposal_fingerprint"),
            "request_fingerprint": planner.get("request_fingerprint"),
            "repository_source_sha": planner.get("repository_source_sha"),
            "development_memory": memory,
        },
        "task": {
            "task_id": TASK_ID,
            "base_sha": target_observations["base_sha"],
            "zero_touch_run": zero_touch_run,
            "jules_cycle_run": implementation_run,
            "pull_request": target_observations["pull_request"],
            "ci_run": target_observations["ci_run"],
            "remote_gate_run": target_observations["remote_gate_run"],
            "remote_monitor_run": remote_monitor_run,
            "head_sha": target_observations["head_sha"],
            "merge_commit": target_observations["merge_sha"],
            "changed_paths": target_observations["changed_paths"],
            "provider_session_id_fingerprint": "checkpoint-and-pr-url-bound",
        },
        "runtime_verification": {
            "workflow_run": runtime_run,
            "trigger_source": provenance.get("runtime_workflow_event"),
            "manual_workflow_dispatch": False,
            "workspace_source_sha": provenance.get("workspace_source_sha"),
            "dependency_fingerprint": dependency_fingerprint,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "contract": contract,
            "receipt": receipt,
            "target": target,
            "report": report,
            "report_fingerprint": report_wrapper.get("report_fingerprint"),
            "attempts_by_probe": report_wrapper.get("attempts_by_probe"),
            "development_memory_feedback": feedback,
        },
        "provenance_observations": {
            "zero_touch_dispatch_count": zero_touch.get("dispatch_count"),
            "target_pr_base_sha": target_observations["base_sha"],
            "target_pr_scope_exact": target_observations["changed_paths"],
            "target_pr_jules_session_matches_checkpoint": True,
            "implementation_workflow_name": provenance.get("implementation_workflow_name"),
            "implementation_workflow_event": provenance.get("implementation_workflow_event"),
            "runtime_source_matches_trusted_merge": True,
        },
        "manual_campaign_progress_after_goal_submission": False,
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "terminal_snapshot": {
            "campaign": campaign,
            "state": {
                "status": state.get("status"),
                "current_task_id": state.get("current_task_id"),
                "failed_task_ids": state.get("failed_task_ids"),
            },
            "remote_execution_receipt": remote.to_dict(),
        },
    }


def main() -> int:
    try:
        state = _load_json(STATE_PATH)
        metadata = state.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("planning_request_id") != REQUEST_ID:
            payload = {"schema_version": 1, "state": "NOOP", "reason": "proof002-not-current"}
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if state.get("status") != "READY" or state.get("current_task_id") is not None:
            payload = {"schema_version": 1, "state": "NOOP", "reason": "proof002-not-terminal"}
            _write_result(payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        recovery = _optional_json(RECOVERY_PATH)
        if isinstance(recovery, dict) and recovery.get("task_id") == TASK_ID:
            raise ValueError("proof002 has a recovery record and cannot graduate cleanly")

        campaign = _load_json(CAMPAIGN_PATH)
        planner = _load_json(PLANNER_PATH)
        zero_touch = _load_json(ZERO_TOUCH_PATH)
        checkpoint = _load_json(CHECKPOINT_PATH)
        accepted = _load_json(ACCEPTED_PLAN_PATH)
        remote = RemoteExecutionReceipt.from_dict(_load_json(REMOTE_PATH))
        contract = _load_json(CONTRACT_PATH)
        receipt = _load_json(RECEIPT_PATH)
        target = _load_json(TARGET_PATH)
        report_wrapper = _load_json(REPORT_PATH)
        provenance = _load_json(PROVENANCE_PATH)
        bootstrap = _load_json(BOOTSTRAP_PATH)
        store = DevelopmentMemoryStore.from_dict(_load_json(STORE_PATH))

        plan = accepted.get("plan")
        tasks = plan.get("tasks") if isinstance(plan, dict) else None
        if accepted.get("status") != "ACCEPTED" or not isinstance(tasks, list) or len(tasks) != 1:
            raise ValueError("AcceptedPlan is not the one-task proof002 plan")
        accepted_task = tasks[0]
        if not isinstance(accepted_task, dict) or accepted_task.get("task_id") != TASK_ID:
            raise ValueError("AcceptedPlan task identity mismatch")
        if accepted_task.get("allowed_paths") != ["tests/test_models.py"]:
            raise ValueError("AcceptedPlan scope expanded beyond the proof contract")

        if bootstrap.get("durable_memory_feedback", {}).get("memory_id") != BOOTSTRAP_MEMORY_ID:
            raise ValueError("bootstrap durable memory ID changed")
        if bootstrap.get("durable_memory_feedback", {}).get("memory_fingerprint") != BOOTSTRAP_MEMORY_FINGERPRINT:
            raise ValueError("bootstrap durable memory fingerprint changed")
        if len(store.ledger.records) < 2:
            raise ValueError("final Development Memory store does not contain proof002 feedback")

        observations = _target_observations(remote)
        if observations["base_sha"] != planner.get("repository_source_sha"):
            raise ValueError("target PR base SHA does not match Planner repository source SHA")

        evidence = build_candidate_evidence(
            state=state,
            campaign=campaign,
            planner=planner,
            zero_touch=zero_touch,
            checkpoint=checkpoint,
            remote=remote,
            contract=contract,
            receipt=receipt,
            target=target,
            report_wrapper=report_wrapper,
            provenance=provenance,
            target_observations=observations,
        )

        run_specs = (
            (evidence["planner"]["workflow_run"], "ADE Autonomous Planner", ("repository_dispatch",)),
            (evidence["task"]["zero_touch_run"], "ADE Zero-Touch Start", ("repository_dispatch", "push", "schedule")),
            (
                evidence["task"]["jules_cycle_run"],
                ("ADE Jules Cycle", "ADE Resume Watch"),
                ("repository_dispatch", "push", "schedule", "workflow_run"),
            ),
            (
                evidence["task"]["remote_monitor_run"],
                "ADE Remote PR Monitor",
                ("repository_dispatch", "push", "schedule"),
            ),
            (
                evidence["runtime_verification"]["workflow_run"],
                "ADE Runtime Verification",
                ("repository_dispatch",),
            ),
        )
        for run_id, name, events in run_specs:
            validate_controller_run(
                _get_controller_run(run_id),
                expected_name=name,
                allow_events=events,
            )

        path = Path(EVIDENCE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        audit_result = audit(Path("."))
        if not audit_result.get("v1_5_development_memory_graduated"):
            raise ValueError("v1.5 Graduation audit rejected assembled proof evidence")

        gh = GitHubClient()
        gh.upsert_json_file(
            EVIDENCE_PATH,
            evidence,
            message="v1.5: freeze Development Memory proof002 graduation evidence",
        )

        payload = {
            "schema_version": 1,
            "state": "EVIDENCE_FROZEN",
            "request_id": REQUEST_ID,
            "campaign_id": CAMPAIGN_ID,
            "task_id": TASK_ID,
            "pull_request": observations["pull_request"],
            "merge_sha": observations["merge_sha"],
            "reused_memory_id": BOOTSTRAP_MEMORY_ID,
            "final_store_fingerprint": store.fingerprint(),
            "audit": audit_result,
        }
        _write_result(payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (GitHubError, RuntimeError, ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        payload = {
            "schema_version": 1,
            "state": "FAILED",
            "reason": str(exc).splitlines()[0][:256],
        }
        _write_result(payload)
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

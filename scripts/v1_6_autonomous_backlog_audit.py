from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_extraction import (
    extract_verified_memory_followup_candidate,
)
from ade.autonomous_backlog_feedback import (
    BacklogRetirementRecord,
    build_verified_backlog_retirement,
)
from ade.autonomous_backlog_goal import (
    BacklogPlanningPolicy,
    build_planning_goal_handoff,
)
from ade.autonomous_backlog_resolution import (
    BacklogResolutionState,
    resolve_autonomous_backlog,
)
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.development_memory import MemoryKind
from ade.development_memory_store import DevelopmentMemoryStore
from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from ade.development_memory_feedback import runtime_report_from_wrapper


EVIDENCE_PATH = ".autodev/campaign-evidence/v1.6-autonomous-backlog-proof-001.json"
SOURCE_STORE_PATH = ".autodev/autonomous-backlog/source-memory-store.json"
BACKLOG_PATH = ".autodev/autonomous-backlog/backlog.json"
RESOLUTION_PATH = ".autodev/autonomous-backlog/resolution.json"
SELECTION_PATH = ".autodev/autonomous-backlog/selection.json"
POLICY_PATH = ".autodev/autonomous-backlog/policy.json"
HANDOFF_PATH = ".autodev/autonomous-backlog/handoff.json"
PLANNING_GOAL_PATH = ".autodev/autonomous-backlog/proof/planning-goal.json"
ACCEPTED_PLAN_PATH = ".autodev/autonomous-backlog/proof/accepted-plan.json"
CAMPAIGN_PATH = ".autodev/autonomous-backlog/proof/campaign.json"
STATE_PATH = ".autodev/autonomous-backlog/proof/state.json"
REMOTE_PATH = ".autodev/autonomous-backlog/proof/remote-execution.json"
RETIREMENT_PATH = ".autodev/autonomous-backlog/retirement.json"
POST_RESOLUTION_PATH = ".autodev/autonomous-backlog/post-retirement-resolution.json"
POST_SELECTION_PATH = ".autodev/autonomous-backlog/post-retirement-selection.json"
PROOF_PROVENANCE_PATH = ".autodev/autonomous-backlog/proof/provenance.json"

TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CI_PROOFS = (
    "Autonomous Backlog proof",
    "Autonomous Backlog trusted extraction proof",
    "Autonomous Backlog resolution proof",
    "Autonomous Backlog selection proof",
    "Autonomous Backlog PlanningGoal handoff proof",
    "Autonomous Backlog verified retirement proof",
    "Autonomous Backlog successor gate proof",
    "Autonomous Planner proof",
    "Repository Intelligence proof",
    "Development Memory proof",
    "Development Memory feedback lifecycle proof",
    "Runtime Verification post-merge trigger proof",
    "Runtime Verification bounded execution proof",
    "Runtime Verification real repository probe proof",
    "Remote Repository Loop proof",
    "Human decision boundary proof",
    "ADE v1.5 Development Memory Graduation audit",
)


def _load(root: Path, relative: str) -> dict[str, Any]:
    payload = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return payload


def _load_derived(root: Path, relative: str) -> dict[str, Any]:
    if not relative:
        return {}
    path = root / relative
    if not path.is_file():
        return {}
    return _load(root, relative)


def _sha40(value: object) -> bool:
    return isinstance(value, str) and SHA40.fullmatch(value) is not None


def _sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _run_id(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _proof_policy() -> BacklogPlanningPolicy:
    return BacklogPlanningPolicy(
        repository=TARGET_REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        request_prefix="abgproof",
        min_tasks=1,
        max_tasks=1,
    )


def audit(
    root: Path,
    *,
    evidence_path: str = EVIDENCE_PATH,
) -> dict[str, object]:
    evidence = _load(root, evidence_path)
    source_store = DevelopmentMemoryStore.from_dict(
        _load(root, SOURCE_STORE_PATH)
    )
    backlog = AutonomousBacklog.from_dict(_load(root, BACKLOG_PATH))
    stored_resolution = _load(root, RESOLUTION_PATH)
    stored_selection = _load(root, SELECTION_PATH)
    stored_policy = _load(root, POLICY_PATH)
    stored_handoff = _load(root, HANDOFF_PATH)
    planning_goal = _load(root, PLANNING_GOAL_PATH)
    accepted_plan = _load(root, ACCEPTED_PLAN_PATH)
    campaign = _load(root, CAMPAIGN_PATH)
    state = _load(root, STATE_PATH)
    remote_payload = _load(root, REMOTE_PATH)
    stored_retirement = _load(root, RETIREMENT_PATH)
    stored_post_resolution = _load(root, POST_RESOLUTION_PATH)
    stored_post_selection = _load(root, POST_SELECTION_PATH)
    proof_provenance = _load(root, PROOF_PROVENANCE_PATH)

    source = evidence.get("source_memory")
    source = source if isinstance(source, dict) else {}
    candidate_summary = evidence.get("candidate")
    candidate_summary = (
        candidate_summary if isinstance(candidate_summary, dict) else {}
    )
    planning = evidence.get("planning")
    planning = planning if isinstance(planning, dict) else {}
    task = evidence.get("task")
    task = task if isinstance(task, dict) else {}
    runtime = evidence.get("runtime_verification")
    runtime = runtime if isinstance(runtime, dict) else {}
    retirement_summary = evidence.get("retirement")
    retirement_summary = (
        retirement_summary if isinstance(retirement_summary, dict) else {}
    )
    post = evidence.get("post_retirement")
    post = post if isinstance(post, dict) else {}

    source_memory_id = source.get("memory_id")
    source_records = [
        record
        for record in source_store.ledger.records
        if record.memory_id == source_memory_id
    ]
    source_record = source_records[0] if len(source_records) == 1 else None

    candidate = None
    if isinstance(source_memory_id, str):
        candidate = extract_verified_memory_followup_candidate(
            store_path=SOURCE_STORE_PATH,
            store_payload=source_store.canonical_dict(),
            memory_id=source_memory_id,
            source_phase="v1.6-autonomous-backlog",
        )

    initial_resolution = None
    initial_selection = None
    handoff = None
    if candidate is not None:
        initial_resolution = resolve_autonomous_backlog(
            backlog,
            current_sources={TARGET_REPOSITORY: candidate.source_sha},
        )
        initial_selection = select_next_backlog_candidate(
            backlog,
            initial_resolution,
            repository=TARGET_REPOSITORY,
            source_sha=candidate.source_sha,
        )
        handoff = build_planning_goal_handoff(
            backlog,
            initial_resolution,
            initial_selection,
            policy=_proof_policy(),
        )

    request_id = handoff.request.request_id if handoff is not None else None
    planner_path = (
        f".autodev/planner-evidence/{request_id}.json"
        if isinstance(request_id, str)
        else ""
    )
    planner_evidence = _load_derived(root, planner_path)

    plan = accepted_plan.get("plan")
    plan = plan if isinstance(plan, dict) else {}
    plan_tasks = plan.get("tasks")
    plan_tasks = plan_tasks if isinstance(plan_tasks, list) else []
    accepted_task = (
        plan_tasks[0]
        if len(plan_tasks) == 1 and isinstance(plan_tasks[0], dict)
        else {}
    )
    task_id = accepted_task.get("task_id")
    contract_path = (
        f".autodev/runtime-verification/{task_id}/contract.json"
        if isinstance(task_id, str)
        else ""
    )
    receipt_path = (
        f".autodev/runtime-verification/{task_id}/receipt.json"
        if isinstance(task_id, str)
        else ""
    )
    report_path = (
        f".autodev/runtime-verification/{task_id}/report.json"
        if isinstance(task_id, str)
        else ""
    )
    contract_payload = _load_derived(root, contract_path)
    receipt_payload = _load_derived(root, receipt_path)
    report_wrapper = _load_derived(root, report_path)

    remote = None
    contract = None
    receipt = None
    report = None
    runtime_re_evaluated = None
    try:
        remote = RemoteExecutionReceipt.from_dict(remote_payload)
        contract = RuntimeVerificationContract.from_dict(contract_payload)
        receipt = RuntimeVerificationReceipt.from_dict(receipt_payload)
        report = runtime_report_from_wrapper(report_wrapper)
        runtime_re_evaluated = evaluate_runtime_verification(
            contract,
            report.results,
        )
    except (KeyError, TypeError, ValueError):
        pass

    expected_retirement = None
    post_resolution = None
    post_selection = None
    if (
        handoff is not None
        and contract is not None
        and receipt is not None
        and report is not None
    ):
        try:
            expected_retirement = build_verified_backlog_retirement(
                backlog=backlog,
                handoff=handoff,
                campaign_payload=campaign,
                state_payload=state,
                remote_execution_payload=remote_payload,
                runtime_contract_payload=contract_payload,
                runtime_receipt_payload=receipt_payload,
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
                backlog,
                current_sources={
                    TARGET_REPOSITORY: expected_retirement.verified_source_sha
                },
                retirements=(expected_retirement,),
            )
            post_selection = select_next_backlog_candidate(
                backlog,
                post_resolution,
                repository=TARGET_REPOSITORY,
                source_sha=expected_retirement.verified_source_sha,
            )
        except (KeyError, TypeError, ValueError):
            expected_retirement = None
            post_resolution = None
            post_selection = None

    zero_touch_provenance = proof_provenance.get("zero_touch_receipt")
    zero_touch_provenance = (
        zero_touch_provenance
        if isinstance(zero_touch_provenance, dict)
        else {}
    )
    runtime_provenance = proof_provenance.get("runtime_provenance")
    runtime_provenance = (
        runtime_provenance if isinstance(runtime_provenance, dict) else {}
    )
    target_provenance = proof_provenance.get("target_pull_request")
    target_provenance = (
        target_provenance if isinstance(target_provenance, dict) else {}
    )

    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    missing_proofs = [name for name in REQUIRED_CI_PROOFS if name not in ci]

    checks = {
        "evidence_schema": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.6",
        "target_repository": evidence.get("target_repository")
        == TARGET_REPOSITORY,
        "no_manual_per_task_authoring": evidence.get(
            "human_authored_per_task_work_items"
        )
        is False
        and evidence.get("manual_campaign_progress_after_goal_submission")
        is False,
        "source_store_bound": source.get("path") == SOURCE_STORE_PATH
        and source.get("store_fingerprint") == source_store.fingerprint()
        and len(source_records) == 1
        and source_record is not None
        and source_record.repository == TARGET_REPOSITORY
        and source_record.kind is MemoryKind.VERIFIED_OUTCOME
        and {"feedback", "runtime", "verified"}.issubset(
            set(source_record.tags)
        )
        and source.get("memory_fingerprint") == source_record.fingerprint(),
        "candidate_reconstructed": candidate is not None
        and backlog.candidate_count == 1
        and backlog.candidates[0].canonical_dict() == candidate.canonical_dict()
        and candidate_summary.get("candidate_id") == candidate.candidate_id
        and candidate_summary.get("candidate_fingerprint")
        == candidate.fingerprint()
        and candidate_summary.get("backlog_fingerprint")
        == backlog.fingerprint()
        and candidate.canonical_dict()["execution_authority"] is False
        and candidate.canonical_dict()["auto_dispatch"] is False,
        "initial_resolution_reconstructed": initial_resolution is not None
        and stored_resolution == initial_resolution.canonical_dict()
        and planning.get("resolution_fingerprint")
        == initial_resolution.fingerprint()
        and initial_resolution.entry_for(candidate.candidate_id).state
        is BacklogResolutionState.CURRENT,
        "selection_reconstructed": initial_selection is not None
        and stored_selection == initial_selection.canonical_dict()
        and initial_selection.selected_candidate_id
        == candidate.candidate_id
        and planning.get("selection_fingerprint")
        == initial_selection.fingerprint(),
        "trusted_policy_bound": stored_policy == _proof_policy().canonical_dict()
        and planning.get("policy_fingerprint") == _proof_policy().fingerprint(),
        "goal_handoff_reconstructed": handoff is not None
        and stored_handoff == handoff.canonical_dict()
        and planning_goal == handoff.request.to_dict()
        and planning.get("handoff_fingerprint") == handoff.fingerprint()
        and planning.get("request_id") == handoff.request.request_id
        and planning.get("campaign_id") == handoff.request.campaign_id
        and stored_handoff.get("execution_authority") is False
        and stored_handoff.get("accepted_plan_authority") is False
        and stored_handoff.get("auto_dispatch") is False,
        "planner_evidence_bound": planner_evidence.get("schema_version") == 1
        and planner_evidence.get("request") == handoff.request.to_dict()
        and planner_evidence.get("campaign_id")
        == handoff.request.campaign_id
        and planner_evidence.get("planning_only") is True
        and planner_evidence.get("repository_source_sha")
        == candidate.source_sha
        and _positive_int(planner_evidence.get("workflow_run_id"))
        and planning.get("planner_workflow_run")
        == planner_evidence.get("workflow_run_id"),
        "accepted_plan_bounded": accepted_plan.get("status") == "ACCEPTED"
        and accepted_plan.get("fingerprint")
        == planner_evidence.get("accepted_plan_fingerprint")
        and len(plan_tasks) == 1
        and isinstance(task_id, str)
        and accepted_task.get("allowed_paths") == ["tests/test_models.py"]
        and accepted_task.get("new_paths") == []
        and accepted_task.get("human_only") is False
        and task.get("task_id") == task_id
        and task.get("changed_paths") == ["tests/test_models.py"]
        and _positive_int(task.get("zero_touch_run"))
        and _positive_int(task.get("implementation_run"))
        and _positive_int(task.get("pull_request"))
        and _positive_int(task.get("ci_run"))
        and _positive_int(task.get("remote_gate_run"))
        and _positive_int(task.get("remote_monitor_run"))
        and _sha40(task.get("head_sha"))
        and _sha40(task.get("merge_sha")),
        "campaign_terminal": campaign.get("campaign_id")
        == handoff.request.campaign_id
        and campaign.get("status") == "COMPLETED"
        and campaign.get("task_ids") == [task_id]
        and campaign.get("completed_task_ids") == [task_id]
        and state.get("status") == "READY"
        and state.get("current_task_id") is None
        and state.get("failed_task_ids") == []
        and task_id in state.get("completed_task_ids", []),
        "remote_execution_bound": remote is not None
        and remote.status == "MERGED"
        and remote.task_id == task_id
        and remote.target_repository == TARGET_REPOSITORY
        and remote.pull_request_number == task.get("pull_request"),
        "runtime_verified": contract is not None
        and receipt is not None
        and report is not None
        and runtime_re_evaluated is not None
        and receipt.status == "VERIFIED"
        and receipt.dispatch_count == 1
        and receipt.task_id == task_id
        and contract.target_repository == TARGET_REPOSITORY
        and contract.source_sha == task.get("merge_sha")
        and receipt.source_sha == task.get("merge_sha")
        and report.source_sha == task.get("merge_sha")
        and runtime_re_evaluated.canonical_dict() == report.canonical_dict()
        and report.disposition is RuntimeVerificationDisposition.VERIFIED
        and runtime.get("contract_path") == contract_path
        and runtime.get("receipt_path") == receipt_path
        and runtime.get("report_path") == report_path
        and runtime.get("report_fingerprint") == report.fingerprint()
        and _positive_int(runtime.get("workflow_run"))
        and runtime.get("manual_workflow_dispatch") is False,
        "retirement_reconstructed": expected_retirement is not None
        and stored_retirement == expected_retirement.canonical_dict()
        and retirement_summary.get("retirement_id")
        == expected_retirement.retirement_id
        and retirement_summary.get("retirement_fingerprint")
        == expected_retirement.fingerprint()
        and retirement_summary.get("candidate_id")
        == candidate.candidate_id,
        "post_retirement_resolution": post_resolution is not None
        and stored_post_resolution == post_resolution.canonical_dict()
        and post.get("resolution_fingerprint")
        == post_resolution.fingerprint()
        and post_resolution.entry_for(candidate.candidate_id).state
        is BacklogResolutionState.RETIRED,
        "post_retirement_no_reselection": post_selection is not None
        and stored_post_selection == post_selection.canonical_dict()
        and post_selection.selected_candidate_id is None
        and post_selection.eligible_candidate_ids == ()
        and post.get("selection_fingerprint")
        == post_selection.fingerprint()
        and post.get("selected_candidate_id") is None,
        "provenance_snapshot_bound": proof_provenance.get("schema_version") == 1
        and proof_provenance.get("task_id") == task_id
        and _run_id(proof_provenance.get("planner_workflow_run"))
        == planner_evidence.get("workflow_run_id")
        and _run_id(proof_provenance.get("planner_workflow_run"))
        == planning.get("planner_workflow_run")
        and zero_touch_provenance.get("campaign_id")
        == handoff.request.campaign_id
        and zero_touch_provenance.get("task_id") == task_id
        and zero_touch_provenance.get("status") == "DISPATCHED"
        and zero_touch_provenance.get("dispatch_count") == 1
        and zero_touch_provenance.get("source") == "repository_dispatch"
        and _run_id(zero_touch_provenance.get("run_id"))
        == task.get("zero_touch_run")
        and runtime_provenance.get("task_id") == task_id
        and runtime_provenance.get("pull_request_number")
        == task.get("pull_request")
        and runtime_provenance.get("pull_request_head_sha")
        == task.get("head_sha")
        and runtime_provenance.get("trusted_merge_sha")
        == task.get("merge_sha")
        and _run_id(runtime_provenance.get("implementation_workflow_run_id"))
        == task.get("implementation_run")
        and _run_id(runtime_provenance.get("remote_monitor_workflow_run_id"))
        == task.get("remote_monitor_run")
        and _run_id(runtime_provenance.get("runtime_workflow_run_id"))
        == runtime.get("workflow_run")
        and runtime_provenance.get("runtime_workflow_event")
        == "repository_dispatch"
        and target_provenance.get("pull_request")
        == task.get("pull_request")
        and target_provenance.get("base_sha") == candidate.source_sha
        and target_provenance.get("head_sha") == task.get("head_sha")
        and target_provenance.get("merge_sha") == task.get("merge_sha")
        and target_provenance.get("changed_paths")
        == task.get("changed_paths")
        and target_provenance.get("ci_run") == task.get("ci_run")
        and target_provenance.get("remote_gate_run")
        == task.get("remote_gate_run"),
        "execution_provenance_clean": evidence.get(
            "execution_provenance_clean"
        )
        is True,
        "required_ci_proofs": not missing_proofs,
    }

    return {
        "schema_version": 1,
        "checks": checks,
        "missing_proofs": missing_proofs,
        "source_memory_id": source_memory_id,
        "candidate_id": candidate.candidate_id if candidate is not None else None,
        "retirement_id": (
            expected_retirement.retirement_id
            if expected_retirement is not None
            else None
        ),
        "v1_6_autonomous_backlog_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_6_autonomous_backlog_graduated"]:
        raise SystemExit(1)

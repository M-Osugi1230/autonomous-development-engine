from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

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


EVIDENCE_PATH = ".autodev/campaign-evidence/v1.7-multi-agent-proof-001.json"
PROOF_ROOT = ".autodev/multi-agent/proof"
PLANNING_GOAL_PATH = f"{PROOF_ROOT}/planning-goal.json"
ACCEPTED_PLAN_PATH = f"{PROOF_ROOT}/accepted-plan.json"
CAMPAIGN_PATH = f"{PROOF_ROOT}/campaign.json"
STATE_PATH = f"{PROOF_ROOT}/state.json"
REMOTE_PATH = f"{PROOF_ROOT}/remote-execution.json"
CHECKPOINT_PATH = f"{PROOF_ROOT}/checkpoint.json"
PLAN_PATH = f"{PROOF_ROOT}/multi-agent-plan.json"
REVIEWER_SESSION_PATH = f"{PROOF_ROOT}/reviewer-session.json"
REVIEWER_OBSERVATION_PATH = f"{PROOF_ROOT}/reviewer-observation.json"
REVIEWER_CONTRIBUTION_PATH = f"{PROOF_ROOT}/reviewer-contribution.json"
RECONCILIATION_PATH = f"{PROOF_ROOT}/reconciliation.json"
CLEARANCE_PATH = f"{PROOF_ROOT}/review-clearance.json"
PROVENANCE_PATH = f"{PROOF_ROOT}/provenance.json"

LIVE_REVIEWER_OBSERVATION_PATH = ".autodev/multi-agent/reviewer-observation.json"
TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
REQUEST_ID = "v1.7-multi-agent-proof-001"
CAMPAIGN_ID = "v1.7-multi-agent-campaign-001"
TASK_ID = "v17ma1-001"
EXPECTED_PATH = "tests/test_models.py"

REQUIRED_CI_PROOFS = (
    "Autonomous Planner proof",
    "Repository Intelligence proof",
    "Development Memory proof",
    "Autonomous Backlog proof",
    "Runtime Verification post-merge trigger proof",
    "Runtime Verification bounded execution proof",
    "Runtime Verification real repository probe proof",
    "Remote Repository Loop proof",
    "Multi-Agent foundation proof",
    "Multi-Agent trusted derivation proof",
    "Multi-Agent contribution evidence proof",
    "Multi-Agent deterministic reconciliation proof",
    "Multi-Agent role session lifecycle proof",
    "Multi-Agent bounded correction loop proof",
    "Multi-Agent reviewer clearance proof",
    "Human decision boundary proof",
    "ADE v1.6 Autonomous Backlog Graduation audit",
)


def _load(root: Path, relative: str) -> dict[str, Any]:
    payload = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return payload


def _fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _positive_int(value: object) -> bool:
    if type(value) is int:
        return value > 0
    return isinstance(value, str) and value.isdigit() and int(value) > 0


def _authority_free(payload: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return all(payload.get(field, False) is False for field in fields)


def audit(
    root: Path,
    *,
    evidence_path: str = EVIDENCE_PATH,
) -> dict[str, object]:
    evidence = _load(root, evidence_path)
    goal = _load(root, PLANNING_GOAL_PATH)
    accepted_payload = _load(root, ACCEPTED_PLAN_PATH)
    campaign = _load(root, CAMPAIGN_PATH)
    state = _load(root, STATE_PATH)
    remote_payload = _load(root, REMOTE_PATH)
    checkpoint = _load(root, CHECKPOINT_PATH)
    plan_payload = _load(root, PLAN_PATH)
    session_payload = _load(root, REVIEWER_SESSION_PATH)
    observation = _load(root, REVIEWER_OBSERVATION_PATH)
    contribution_payload = _load(root, REVIEWER_CONTRIBUTION_PATH)
    reconciliation_payload = _load(root, RECONCILIATION_PATH)
    clearance_payload = _load(root, CLEARANCE_PATH)
    provenance = _load(root, PROVENANCE_PATH)

    accepted = AcceptedPlan.from_dict(accepted_payload)
    plan = MultiAgentPlan.from_dict(plan_payload)
    session = RoleSession.from_dict(session_payload)
    contribution = AgentContribution.from_dict(contribution_payload)
    clearance = ReviewClearance.from_dict(clearance_payload)
    remote = RemoteExecutionReceipt.from_dict(remote_payload)

    reconstructed_reconciliation = reconcile_agent_contributions(
        plan=plan,
        contributions=(contribution,),
    )
    reconstructed_clearance = build_review_clearance(
        accepted_plan=accepted,
        plan=plan,
        role_session=session,
        contribution=contribution,
        reconciliation=reconstructed_reconciliation,
        reviewed_head_sha=clearance.reviewed_head_sha,
        pull_request_number=clearance.pull_request_number,
    )

    target = provenance.get("target_pull_request")
    target = target if isinstance(target, dict) else {}
    zero_touch = provenance.get("zero_touch_receipt")
    zero_touch = zero_touch if isinstance(zero_touch, dict) else {}
    runtime_provenance = provenance.get("runtime_provenance")
    runtime_provenance = (
        runtime_provenance if isinstance(runtime_provenance, dict) else {}
    )
    planner_evidence = provenance.get("planner_evidence")
    planner_evidence = planner_evidence if isinstance(planner_evidence, dict) else {}

    task = accepted.plan.tasks[0] if len(accepted.plan.tasks) == 1 else None
    reviewer = next(
        (item for item in plan.assignments if item.role is AgentRole.REVIEWER),
        None,
    )
    implementer = next(
        (item for item in plan.assignments if item.role is AgentRole.IMPLEMENTER),
        None,
    )

    contract_path = f".autodev/runtime-verification/{TASK_ID}/contract.json"
    receipt_path = f".autodev/runtime-verification/{TASK_ID}/receipt.json"
    report_path = f".autodev/runtime-verification/{TASK_ID}/report.json"
    contract = RuntimeVerificationContract.from_dict(_load(root, contract_path))
    receipt = RuntimeVerificationReceipt.from_dict(_load(root, receipt_path))
    report_wrapper = _load(root, report_path)
    report = runtime_report_from_wrapper(report_wrapper)
    re_evaluated = evaluate_runtime_verification(contract, report.results)

    metadata = state.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    task_summary = evidence.get("task")
    task_summary = task_summary if isinstance(task_summary, dict) else {}
    review_summary = evidence.get("multi_agent_review")
    review_summary = review_summary if isinstance(review_summary, dict) else {}
    runtime_summary = evidence.get("runtime_verification")
    runtime_summary = runtime_summary if isinstance(runtime_summary, dict) else {}

    ci_text = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    missing_proofs = [name for name in REQUIRED_CI_PROOFS if name not in ci_text]

    observation_fp = _fingerprint(observation)
    provider_session_id = session.provider_session_id
    implementer_session_id = checkpoint.get("provider_session_id")

    checks = {
        "proof_identity": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.7"
        and evidence.get("target_repository") == TARGET_REPOSITORY
        and evidence.get("human_authored_per_task_work_items") is False
        and evidence.get("manual_campaign_progress_after_goal_submission") is False,
        "planning_goal_bounded": goal.get("request_id") == REQUEST_ID
        and goal.get("campaign_id") == CAMPAIGN_ID
        and goal.get("target_repository") == TARGET_REPOSITORY
        and goal.get("base_branch") == "main"
        and goal.get("allowed_path_prefixes") == ["tests"]
        and goal.get("min_tasks", 1) == 1
        and goal.get("max_tasks") == 1,
        "accepted_plan_bounded": accepted.status in {"ACCEPTED", "RUNNING", "COMPLETED"}
        and task is not None
        and task.task_id == TASK_ID
        and list(task.allowed_paths) == [EXPECTED_PATH]
        and len(accepted.plan.tasks) == 1,
        "planner_evidence_bound": planner_evidence.get("schema_version") == 1
        and planner_evidence.get("request") == goal
        and planner_evidence.get("campaign_id") == CAMPAIGN_ID
        and planner_evidence.get("planning_only") is True
        and planner_evidence.get("provider_execution_boundary_crossed") is False
        and planner_evidence.get("accepted_plan_fingerprint") == accepted.fingerprint
        and planner_evidence.get("repository_source_sha") == plan.source_sha
        and planner_evidence.get("task_ids") == [TASK_ID]
        and _positive_int(planner_evidence.get("workflow_run_id")),
        "campaign_terminal": campaign.get("campaign_id") == CAMPAIGN_ID
        and campaign.get("status") == "COMPLETED"
        and campaign.get("task_ids") == [TASK_ID]
        and campaign.get("completed_task_ids") == [TASK_ID]
        and state.get("status") == "READY"
        and state.get("current_task_id") is None
        and state.get("failed_task_ids") == []
        and TASK_ID in state.get("completed_task_ids", [])
        and metadata.get("phase") == "v1.7-multi-agent",
        "remote_execution_bound": remote.status == "MERGED"
        and remote.task_id == TASK_ID
        and remote.target_repository == TARGET_REPOSITORY
        and remote.pull_request_number == target.get("pull_request"),
        "multi_agent_plan_bound": plan.repository == TARGET_REPOSITORY
        and plan.source_sha == planner_evidence.get("repository_source_sha")
        and plan.campaign_id == CAMPAIGN_ID
        and plan.task_id == TASK_ID
        and plan.accepted_plan_fingerprint == accepted.fingerprint
        and reviewer is not None
        and implementer is not None
        and len(plan.assignments) == 2,
        "independent_reviewer_session": reviewer is not None
        and session.state is RoleSessionState.COMPLETED
        and session.role == AgentRole.REVIEWER.value
        and session.plan_fingerprint == plan.fingerprint()
        and session.assignment_id == reviewer.assignment_id
        and session.assignment_fingerprint == reviewer.fingerprint()
        and session.provider_id == reviewer.provider_id
        and isinstance(provider_session_id, str)
        and bool(provider_session_id)
        and checkpoint.get("task_id") == TASK_ID
        and checkpoint.get("state") == "COMPLETED"
        and isinstance(implementer_session_id, str)
        and bool(implementer_session_id)
        and provider_session_id != implementer_session_id,
        "review_observation_clear": observation.get("schema_version") == 1
        and observation.get("task_id") == TASK_ID
        and observation.get("pull_request_number") == target.get("pull_request")
        and observation.get("reviewed_head_sha") == target.get("head_sha")
        and observation.get("reviewer_role_session_fingerprint") == session.fingerprint()
        and observation.get("provider_state") == "COMPLETED"
        and observation.get("verdict") == "CLEAR"
        and observation.get("verdict_marker_count") == 1
        and observation.get("raw_activity_text_persisted") is False
        and _authority_free(
            observation,
            ("execution_authority", "merge_authority"),
        ),
        "review_contribution_clear": contribution.role is AgentRole.REVIEWER
        and contribution.verdict is ContributionVerdict.CLEAR
        and contribution.multi_agent_plan_fingerprint == plan.fingerprint()
        and contribution.assignment_id == reviewer.assignment_id
        and contribution.assignment_fingerprint == reviewer.fingerprint()
        and contribution.evidence_paths == (LIVE_REVIEWER_OBSERVATION_PATH,)
        and contribution.evidence_fingerprints == (observation_fp,),
        "reconciliation_reconstructed": (
            reconciliation_payload
            == reconstructed_reconciliation.canonical_dict()
        )
        and reconstructed_reconciliation.disposition
        is ReconciliationDisposition.CLEAR
        and reconstructed_reconciliation.human_decision_id is None,
        "review_clearance_reconstructed": (
            clearance_payload == reconstructed_clearance.canonical_dict()
        )
        and clearance_payload.get("verdict") == "CLEAR"
        and clearance.task_id == TASK_ID
        and clearance.target_repository == TARGET_REPOSITORY
        and clearance.reviewed_head_sha == target.get("head_sha")
        and clearance.pull_request_number == target.get("pull_request"),
        "target_merge_exact": target.get("base_sha") == plan.source_sha
        and target.get("head_sha") == clearance.reviewed_head_sha
        and isinstance(target.get("merge_sha"), str)
        and len(target.get("merge_sha")) == 40
        and target.get("changed_paths") == [EXPECTED_PATH]
        and _positive_int(target.get("ci_run"))
        and _positive_int(target.get("remote_gate_run")),
        "zero_touch_bound": zero_touch.get("campaign_id") == CAMPAIGN_ID
        and zero_touch.get("task_id") == TASK_ID
        and zero_touch.get("plan_fingerprint") == accepted.fingerprint
        and zero_touch.get("status") == "DISPATCHED"
        and zero_touch.get("dispatch_count") == 1
        and zero_touch.get("source") == "repository_dispatch"
        and _positive_int(zero_touch.get("run_id")),
        "runtime_verified": receipt.status == "VERIFIED"
        and receipt.dispatch_count == 1
        and receipt.task_id == TASK_ID
        and receipt.target_repository == TARGET_REPOSITORY
        and contract.source_sha == target.get("merge_sha")
        and receipt.source_sha == target.get("merge_sha")
        and report.source_sha == target.get("merge_sha")
        and re_evaluated.canonical_dict() == report.canonical_dict()
        and report.disposition is RuntimeVerificationDisposition.VERIFIED
        and runtime_summary.get("contract_path") == contract_path
        and runtime_summary.get("receipt_path") == receipt_path
        and runtime_summary.get("report_path") == report_path
        and runtime_summary.get("report_fingerprint") == report.fingerprint()
        and _positive_int(runtime_summary.get("workflow_run"))
        and runtime_summary.get("manual_workflow_dispatch") is False,
        "runtime_provenance_bound": runtime_provenance.get("task_id") == TASK_ID
        and runtime_provenance.get("verification_id") == receipt.verification_id
        and runtime_provenance.get("pull_request_number") == target.get("pull_request")
        and runtime_provenance.get("pull_request_head_sha") == target.get("head_sha")
        and runtime_provenance.get("trusted_merge_sha") == target.get("merge_sha")
        and runtime_provenance.get("workspace_source_sha") == target.get("merge_sha")
        and runtime_provenance.get("runtime_workflow_event") == "repository_dispatch"
        and _positive_int(runtime_provenance.get("implementation_workflow_run_id"))
        and _positive_int(runtime_provenance.get("remote_monitor_workflow_run_id"))
        and _positive_int(runtime_provenance.get("runtime_workflow_run_id")),
        "evidence_summary_bound": task_summary.get("task_id") == TASK_ID
        and task_summary.get("pull_request") == target.get("pull_request")
        and task_summary.get("head_sha") == target.get("head_sha")
        and task_summary.get("merge_sha") == target.get("merge_sha")
        and task_summary.get("changed_paths") == [EXPECTED_PATH]
        and review_summary.get("plan_fingerprint") == plan.fingerprint()
        and review_summary.get("reviewer_assignment_fingerprint")
        == reviewer.fingerprint()
        and review_summary.get("reviewer_role_session_fingerprint")
        == session.fingerprint()
        and review_summary.get("contribution_fingerprint")
        == contribution.fingerprint()
        and review_summary.get("reconciliation_fingerprint")
        == reconstructed_reconciliation.fingerprint()
        and review_summary.get("clearance_fingerprint")
        == clearance.fingerprint()
        and review_summary.get("verdict") == "CLEAR"
        and review_summary.get("correction_rounds") == 0,
        "execution_provenance_clean": evidence.get("execution_provenance_clean") is True,
        "required_ci_proofs": not missing_proofs,
    }

    return {
        "schema_version": 1,
        "checks": checks,
        "missing_proofs": missing_proofs,
        "task_id": TASK_ID,
        "pull_request": target.get("pull_request"),
        "merge_sha": target.get("merge_sha"),
        "v1_7_multi_agent_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_7_multi_agent_graduated"]:
        raise SystemExit(1)

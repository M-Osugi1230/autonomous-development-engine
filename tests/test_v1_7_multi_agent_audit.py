from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.multi_agent import AgentAssignment, AgentRole, MultiAgentPlan
from ade.multi_agent_contribution import (
    ContributionVerdict,
    build_agent_contribution,
)
from ade.multi_agent_reconciliation import reconcile_agent_contributions
from ade.multi_agent_review_gate import build_review_clearance
from ade.multi_agent_session import (
    complete_role_session,
    role_session_for_assignment,
    start_role_session,
)
from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from scripts.v1_7_multi_agent_audit import (
    ACCEPTED_PLAN_PATH,
    CAMPAIGN_PATH,
    CHECKPOINT_PATH,
    CLEARANCE_PATH,
    EVIDENCE_PATH,
    PLAN_PATH,
    PLANNING_GOAL_PATH,
    PROVENANCE_PATH,
    RECONCILIATION_PATH,
    REMOTE_PATH,
    REQUIRED_CI_PROOFS,
    REVIEWER_CONTRIBUTION_PATH,
    REVIEWER_OBSERVATION_PATH,
    REVIEWER_SESSION_PATH,
    STATE_PATH,
    TARGET_REPOSITORY,
    audit,
)


SOURCE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_SHA = "c" * 40
REQUEST_ID = "v1.7-multi-agent-proof-001"
CAMPAIGN_ID = "v1.7-multi-agent-campaign-001"
TASK_ID = "v17ma1-001"
OBSERVATION_LIVE_PATH = ".autodev/multi-agent/reviewer-observation.json"


def fp(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_json(root: Path, path: str, payload: dict) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_fixture(root: Path) -> None:
    task = PlannedTask(
        task_id=TASK_ID,
        title="Add whitespace normalization regression coverage",
        prompt="Add only the focused regression test.",
        depends_on=(),
        allowed_paths=("tests/test_models.py",),
        acceptance=("Repository CI remains green",),
    )
    accepted = AcceptedPlan.accept(
        DevelopmentPlan(
            goal="Add focused regression coverage.",
            tasks=(task,),
            human_boundaries=(
                "destructive or irreversible operation",
                "credential or secret access",
                "externally consequential side effect",
            ),
        )
    )
    evidence_paths = (
        ".autodev/accepted-plan.json",
        ".autodev/multi-agent/provider-availability.json",
    )
    evidence_fps = ("1" * 64, "2" * 64)
    implementer = AgentAssignment(
        assignment_id="agent-implementer-test",
        role=AgentRole.IMPLEMENTER,
        provider_id="jules",
        repository=TARGET_REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id=CAMPAIGN_ID,
        task_id=TASK_ID,
        accepted_plan_fingerprint=accepted.fingerprint,
        objective="Implement the accepted test-only task.",
        evidence_paths=evidence_paths,
        evidence_fingerprints=evidence_fps,
    )
    reviewer = AgentAssignment(
        assignment_id="agent-reviewer-test",
        role=AgentRole.REVIEWER,
        provider_id="jules",
        repository=TARGET_REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id=CAMPAIGN_ID,
        task_id=TASK_ID,
        accepted_plan_fingerprint=accepted.fingerprint,
        objective="Review the accepted task against frozen criteria.",
        evidence_paths=evidence_paths,
        evidence_fingerprints=evidence_fps,
    )
    plan = MultiAgentPlan(
        plan_id="multi-agent-test",
        repository=TARGET_REPOSITORY,
        source_sha=SOURCE_SHA,
        campaign_id=CAMPAIGN_ID,
        task_id=TASK_ID,
        accepted_plan_fingerprint=accepted.fingerprint,
        assignments=(implementer, reviewer),
    )
    session = complete_role_session(
        start_role_session(
            role_session_for_assignment(plan, reviewer),
            provider_id="jules",
            provider_session_id="review-session-001",
        )
    )
    observation = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "pull_request_number": 22,
        "reviewed_head_sha": HEAD_SHA,
        "reviewer_role_session_fingerprint": session.fingerprint(),
        "provider_session_fingerprint": "3" * 64,
        "provider_state": "COMPLETED",
        "activity_fingerprint": "4" * 64,
        "agent_message_count": 1,
        "verdict_marker_count": 1,
        "verdict": "CLEAR",
        "raw_activity_text_persisted": False,
        "execution_authority": False,
        "merge_authority": False,
    }
    contribution = build_agent_contribution(
        plan=plan,
        assignment_id=reviewer.assignment_id,
        verdict=ContributionVerdict.CLEAR,
        summary="Independent reviewer found the bounded change clear.",
        evidence_paths=(OBSERVATION_LIVE_PATH,),
        evidence_fingerprints=(fp(observation),),
    )
    reconciliation = reconcile_agent_contributions(
        plan=plan,
        contributions=(contribution,),
    )
    clearance = build_review_clearance(
        accepted_plan=accepted,
        plan=plan,
        role_session=session,
        contribution=contribution,
        reconciliation=reconciliation,
        reviewed_head_sha=HEAD_SHA,
        pull_request_number=22,
    )

    goal = {
        "schema_version": 1,
        "request_id": REQUEST_ID,
        "campaign_id": CAMPAIGN_ID,
        "id_prefix": "v17ma1",
        "goal": "Add focused regression coverage.",
        "target_repository": TARGET_REPOSITORY,
        "base_branch": "main",
        "allowed_path_prefixes": ["tests"],
        "min_tasks": 1,
        "max_tasks": 1,
    }
    planner = {
        "schema_version": 1,
        "request": goal,
        "campaign_id": CAMPAIGN_ID,
        "planning_only": True,
        "provider_execution_boundary_crossed": False,
        "accepted_plan_fingerprint": accepted.fingerprint,
        "repository_source_sha": SOURCE_SHA,
        "task_ids": [TASK_ID],
        "workflow_run_id": 101,
    }
    zero_touch = {
        "schema_version": 1,
        "campaign_id": CAMPAIGN_ID,
        "task_id": TASK_ID,
        "plan_fingerprint": accepted.fingerprint,
        "status": "DISPATCHED",
        "dispatch_count": 1,
        "source": "repository_dispatch",
        "run_id": "102",
    }
    target = {
        "pull_request": 22,
        "base_sha": SOURCE_SHA,
        "head_sha": HEAD_SHA,
        "merge_sha": MERGE_SHA,
        "changed_paths": ["tests/test_models.py"],
        "ci_run": 103,
        "remote_gate_run": 104,
        "review_workflow_run": 105,
    }
    runtime_provenance = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "verification_id": f"rv-{MERGE_SHA}",
        "runtime_workflow_run_id": 108,
        "runtime_workflow_event": "repository_dispatch",
        "remote_monitor_workflow_run_id": 107,
        "implementation_workflow_run_id": 106,
        "implementation_workflow_name": "ADE Jules Cycle",
        "implementation_workflow_event": "repository_dispatch",
        "pull_request_number": 22,
        "pull_request_head_sha": HEAD_SHA,
        "trusted_merge_sha": MERGE_SHA,
        "workspace_source_sha": MERGE_SHA,
        "dependency_fingerprint": "5" * 64,
        "report_fingerprint": "0" * 64,
        "development_memory_feedback": {"state": "UNCHANGED"},
    }
    provenance = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "planner_evidence": planner,
        "zero_touch_receipt": zero_touch,
        "runtime_provenance": runtime_provenance,
        "target_pull_request": target,
    }

    contract = RuntimeVerificationContract(
        verification_id=f"rv-{MERGE_SHA}",
        target_repository=TARGET_REPOSITORY,
        source_sha=MERGE_SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke",),
        max_attempts=1,
        timeout_seconds=300,
    )
    probe = RuntimeProbeResult(
        probe_id="offline-cli-smoke",
        status=RuntimeProbeStatus.PASS,
        source_sha=MERGE_SHA,
        attempt=1,
    )
    report = evaluate_runtime_verification(contract, (probe,))
    report_wrapper = {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1}
        ],
    }
    receipt = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id=TASK_ID,
        target_repository=TARGET_REPOSITORY,
        source_sha=MERGE_SHA,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="6" * 64,
        policy_fingerprint="7" * 64,
        status="VERIFIED",
        dispatch_count=1,
    )
    runtime_provenance["report_fingerprint"] = report.fingerprint()

    campaign = {
        "schema_version": 1,
        "campaign_id": CAMPAIGN_ID,
        "goal": "Add focused regression coverage.",
        "status": "COMPLETED",
        "task_ids": [TASK_ID],
        "completed_task_ids": [TASK_ID],
    }
    state = {
        "schema_version": 1,
        "project_id": "autonomous-development-engine",
        "provider": "jules",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": [TASK_ID],
        "failed_task_ids": [],
        "iteration": 1,
        "metadata": {"phase": "v1.7-multi-agent"},
    }
    remote = RemoteExecutionReceipt(
        task_id=TASK_ID,
        target_repository=TARGET_REPOSITORY,
        pull_request_url=(
            "https://github.com/"
            "M-Osugi1230/one-minute-thought-experiments/pull/22"
        ),
        recorded_at="2026-10-01T00:00:00+00:00",
        status="MERGED",
    )
    checkpoint = {
        "attempt": 0,
        "last_error": None,
        "last_failure_kind": None,
        "provider_session_id": "implementer-session-001",
        "replan_count": 0,
        "resume_after": None,
        "state": "COMPLETED",
        "task_id": TASK_ID,
    }
    evidence = {
        "schema_version": 1,
        "version": "v1.7",
        "target_repository": TARGET_REPOSITORY,
        "human_authored_per_task_work_items": False,
        "manual_campaign_progress_after_goal_submission": False,
        "execution_provenance_clean": True,
        "planning": {
            "request_id": REQUEST_ID,
            "campaign_id": CAMPAIGN_ID,
            "planner_workflow_run": 101,
            "accepted_plan_fingerprint": accepted.fingerprint,
            "source_sha": SOURCE_SHA,
        },
        "task": {
            "task_id": TASK_ID,
            "zero_touch_run": 102,
            "implementation_run": 106,
            "pull_request": 22,
            "ci_run": 103,
            "remote_gate_run": 104,
            "remote_monitor_run": 107,
            "head_sha": HEAD_SHA,
            "merge_sha": MERGE_SHA,
            "changed_paths": ["tests/test_models.py"],
        },
        "multi_agent_review": {
            "review_workflow_run": 105,
            "plan_fingerprint": plan.fingerprint(),
            "reviewer_assignment_id": reviewer.assignment_id,
            "reviewer_assignment_fingerprint": reviewer.fingerprint(),
            "reviewer_role_session_fingerprint": session.fingerprint(),
            "reviewer_provider_id": reviewer.provider_id,
            "contribution_fingerprint": contribution.fingerprint(),
            "reconciliation_fingerprint": reconciliation.fingerprint(),
            "clearance_fingerprint": clearance.fingerprint(),
            "verdict": "CLEAR",
            "correction_rounds": 0,
        },
        "runtime_verification": {
            "workflow_run": 108,
            "manual_workflow_dispatch": False,
            "verification_id": receipt.verification_id,
            "contract_path": f".autodev/runtime-verification/{TASK_ID}/contract.json",
            "receipt_path": f".autodev/runtime-verification/{TASK_ID}/receipt.json",
            "report_path": f".autodev/runtime-verification/{TASK_ID}/report.json",
            "report_fingerprint": report.fingerprint(),
        },
    }

    for path, payload in (
        (PLANNING_GOAL_PATH, goal),
        (ACCEPTED_PLAN_PATH, accepted.to_dict()),
        (CAMPAIGN_PATH, campaign),
        (STATE_PATH, state),
        (REMOTE_PATH, remote.to_dict()),
        (CHECKPOINT_PATH, checkpoint),
        (PLAN_PATH, plan.canonical_dict()),
        (REVIEWER_SESSION_PATH, session.canonical_dict()),
        (REVIEWER_OBSERVATION_PATH, observation),
        (REVIEWER_CONTRIBUTION_PATH, contribution.canonical_dict()),
        (RECONCILIATION_PATH, reconciliation.canonical_dict()),
        (CLEARANCE_PATH, clearance.canonical_dict()),
        (PROVENANCE_PATH, provenance),
        (EVIDENCE_PATH, evidence),
        (f".autodev/runtime-verification/{TASK_ID}/contract.json", contract.canonical_dict()),
        (f".autodev/runtime-verification/{TASK_ID}/receipt.json", receipt.canonical_dict()),
        (f".autodev/runtime-verification/{TASK_ID}/report.json", report_wrapper),
    ):
        write_json(root, path, payload)

    ci = root / ".github/workflows/ci.yml"
    ci.parent.mkdir(parents=True, exist_ok=True)
    ci.write_text(
        "\n".join(f"- name: {name}" for name in REQUIRED_CI_PROOFS) + "\n",
        encoding="utf-8",
    )


class V17MultiAgentAuditTests(unittest.TestCase):
    def test_complete_independent_review_chain_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fixture(root)
            result = audit(root)
            self.assertTrue(result["v1_7_multi_agent_graduated"])
            self.assertTrue(all(result["checks"].values()))

    def test_same_provider_session_fails_independence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fixture(root)
            session = json.loads(
                (root / REVIEWER_SESSION_PATH).read_text(encoding="utf-8")
            )
            checkpoint_path = root / CHECKPOINT_PATH
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["provider_session_id"] = session["provider_session_id"]
            write_json(root, CHECKPOINT_PATH, checkpoint)
            result = audit(root)
            self.assertFalse(result["checks"]["independent_reviewer_session"])
            self.assertFalse(result["v1_7_multi_agent_graduated"])

    def test_stale_clearance_head_fails_exact_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fixture(root)
            provenance_path = root / PROVENANCE_PATH
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["target_pull_request"]["head_sha"] = "d" * 40
            write_json(root, PROVENANCE_PATH, provenance)
            result = audit(root)
            self.assertFalse(result["checks"]["review_clearance_reconstructed"]
                             and result["checks"]["target_merge_exact"])
            self.assertFalse(result["v1_7_multi_agent_graduated"])


if __name__ == "__main__":
    unittest.main()

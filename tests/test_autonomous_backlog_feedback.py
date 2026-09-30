from __future__ import annotations

import unittest

from ade.autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
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
from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


REPO = "M-Osugi1230/one-minute-thought-experiments"
BASE_SHA = "a" * 40
MERGE_SHA = "b" * 40
TASK_ID = "abg-task-001"


def candidate() -> BacklogCandidate:
    return BacklogCandidate(
        candidate_id="backlog-runtime-followup",
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPO,
        source_sha=BASE_SHA,
        statement="Trusted evidence identifies a bounded test follow-up.",
        evidence_paths=(".autodev/runtime/recovery.json",),
        evidence_fingerprints=("1" * 64,),
        tags=("repair",),
    )


def chain():
    item = candidate()
    backlog = AutonomousBacklog(candidates=(item,))
    resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={REPO: BASE_SHA},
    )
    selection = select_next_backlog_candidate(
        backlog,
        resolution,
        repository=REPO,
        source_sha=BASE_SHA,
    )
    handoff = build_planning_goal_handoff(
        backlog,
        resolution,
        selection,
        policy=BacklogPlanningPolicy(
            repository=REPO,
            base_branch="main",
            allowed_path_prefixes=("tests",),
            min_tasks=1,
            max_tasks=1,
        ),
    )
    return backlog, handoff


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + MERGE_SHA,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )


def receipt(*, status: str = "VERIFIED") -> RuntimeVerificationReceipt:
    value = contract()
    return RuntimeVerificationReceipt(
        verification_id=value.verification_id,
        task_id=TASK_ID,
        target_repository=REPO,
        source_sha=MERGE_SHA,
        contract_fingerprint=value.fingerprint(),
        registry_fingerprint="2" * 64,
        policy_fingerprint="3" * 64,
        status=status,
        dispatch_count=1,
    )


def report_wrapper(*, fail: bool = False) -> dict:
    value = contract()
    results = (
        RuntimeProbeResult(
            probe_id="offline-cli-smoke",
            status=RuntimeProbeStatus.FAIL if fail else RuntimeProbeStatus.PASS,
            source_sha=MERGE_SHA,
            attempt=1,
            detail_code="offline-cli-fail" if fail else "offline-cli-pass",
        ),
        RuntimeProbeResult(
            probe_id="production-import-smoke",
            status=RuntimeProbeStatus.PASS,
            source_sha=MERGE_SHA,
            attempt=1,
            detail_code="production-import-pass",
        ),
    )
    report = evaluate_runtime_verification(value, results)
    return {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }


def campaign(handoff) -> dict:
    return {
        "schema_version": 1,
        "campaign_id": handoff.request.campaign_id,
        "status": "COMPLETED",
        "task_ids": [TASK_ID],
        "completed_task_ids": [TASK_ID],
        "goal": handoff.request.goal,
    }


def state() -> dict:
    return {
        "schema_version": 1,
        "project_id": "ade-test",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": [TASK_ID],
        "failed_task_ids": [],
        "metadata": {},
    }


def remote() -> dict:
    return RemoteExecutionReceipt(
        task_id=TASK_ID,
        target_repository=REPO,
        pull_request_url=f"https://github.com/{REPO}/pull/21",
        recorded_at="2026-10-01T01:00:00+00:00",
        status="MERGED",
    ).to_dict()


def retirement(**overrides) -> BacklogRetirementRecord:
    backlog, handoff = chain()
    kwargs = {
        "backlog": backlog,
        "handoff": handoff,
        "campaign_payload": campaign(handoff),
        "state_payload": state(),
        "remote_execution_payload": remote(),
        "runtime_contract_payload": contract().canonical_dict(),
        "runtime_receipt_payload": receipt().canonical_dict(),
        "runtime_report_wrapper_payload": report_wrapper(),
        "handoff_path": ".autodev/autonomous-backlog/handoff.json",
        "campaign_path": ".autodev/campaign.json",
        "state_path": ".autodev/state.json",
        "remote_execution_path": ".autodev/runtime/remote-execution.json",
        "runtime_contract_path": ".autodev/runtime-verification/abg-task-001/contract.json",
        "runtime_receipt_path": ".autodev/runtime-verification/abg-task-001/receipt.json",
        "runtime_report_path": ".autodev/runtime-verification/abg-task-001/report.json",
    }
    kwargs.update(overrides)
    return build_verified_backlog_retirement(**kwargs)


class AutonomousBacklogFeedbackTests(unittest.TestCase):
    def test_verified_terminal_outcome_builds_retirement(self) -> None:
        backlog, handoff = chain()
        value = retirement()
        self.assertEqual(value.candidate_id, candidate().candidate_id)
        self.assertEqual(value.candidate_fingerprint, candidate().fingerprint())
        self.assertEqual(value.goal_handoff_fingerprint, handoff.fingerprint())
        self.assertEqual(value.campaign_id, handoff.request.campaign_id)
        self.assertEqual(value.original_source_sha, BASE_SHA)
        self.assertEqual(value.verified_source_sha, MERGE_SHA)
        self.assertEqual(value.final_task_id, TASK_ID)
        payload = value.canonical_dict()
        self.assertEqual(
            payload["retirement_authority"],
            "trusted-verified-completion-v1",
        )
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertEqual(BacklogRetirementRecord.from_dict(payload), value)

        resolved = resolve_autonomous_backlog(
            backlog,
            current_sources={REPO: MERGE_SHA},
            retirements=(value,),
        )
        entry = resolved.entry_for(value.candidate_id)
        self.assertIs(entry.state, BacklogResolutionState.RETIRED)
        self.assertEqual(
            resolved.canonical_dict()["retirements"],
            [value.canonical_dict()],
        )

    def test_runtime_verified_is_required(self) -> None:
        with self.assertRaisesRegex(
            AutonomousBacklogError,
            "requires VERIFIED runtime receipt",
        ):
            retirement(
                runtime_receipt_payload=receipt(status="FAILED").canonical_dict()
            )

    def test_runtime_report_must_re_evaluate_to_verified(self) -> None:
        failed = report_wrapper(fail=True)
        failed_receipt = receipt(status="VERIFIED").canonical_dict()
        with self.assertRaisesRegex(
            AutonomousBacklogError,
            "report differs|not VERIFIED",
        ):
            retirement(
                runtime_receipt_payload=failed_receipt,
                runtime_report_wrapper_payload=failed,
            )

    def test_campaign_and_project_must_be_cleanly_terminal(self) -> None:
        backlog, handoff = chain()
        active_campaign = campaign(handoff)
        active_campaign["status"] = "RUNNING"
        with self.assertRaisesRegex(AutonomousBacklogError, "COMPLETED"):
            retirement(campaign_payload=active_campaign)

        bad_state = state()
        bad_state["failed_task_ids"] = [TASK_ID]
        with self.assertRaisesRegex(AutonomousBacklogError, "clean terminal"):
            retirement(state_payload=bad_state)

    def test_trusted_merge_receipt_and_runtime_task_must_bind_campaign(self) -> None:
        not_merged = remote()
        not_merged["status"] = "PR_CREATED"
        with self.assertRaisesRegex(AutonomousBacklogError, "trusted merged"):
            retirement(remote_execution_payload=not_merged)

        other = receipt().canonical_dict()
        other["task_id"] = "other-task"
        with self.assertRaisesRegex(AutonomousBacklogError, "runtime task"):
            retirement(runtime_receipt_payload=other)

    def test_retirement_fingerprint_is_evidence_sensitive(self) -> None:
        first = retirement()
        changed_state = state()
        changed_state["iteration"] = 99
        second = retirement(state_payload=changed_state)
        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertNotEqual(first.fingerprint(), second.fingerprint())

    def test_retirement_record_does_not_grant_authority(self) -> None:
        payload = retirement().canonical_dict()
        payload["execution_authority"] = True
        with self.assertRaisesRegex(AutonomousBacklogError, "execution"):
            BacklogRetirementRecord.from_dict(payload)

    def test_unknown_or_mismatched_retirement_fails_closed_in_resolution(self) -> None:
        backlog, _ = chain()
        value = retirement()
        changed = value.canonical_dict()
        changed["candidate_fingerprint"] = "f" * 64
        bad = BacklogRetirementRecord.from_dict(changed)
        with self.assertRaisesRegex(AutonomousBacklogError, "fingerprint"):
            resolve_autonomous_backlog(
                backlog,
                current_sources={REPO: MERGE_SHA},
                retirements=(bad,),
            )

    def test_retired_candidate_is_not_eligible_for_reselection(self) -> None:
        backlog, _ = chain()
        value = retirement()
        resolved = resolve_autonomous_backlog(
            backlog,
            current_sources={REPO: MERGE_SHA},
            retirements=(value,),
        )
        selected = select_next_backlog_candidate(
            backlog,
            resolved,
            repository=REPO,
            source_sha=MERGE_SHA,
        )
        self.assertIsNone(selected.selected_candidate_id)
        self.assertEqual(selected.eligible_candidate_ids, ())


if __name__ == "__main__":
    unittest.main()

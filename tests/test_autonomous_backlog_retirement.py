from __future__ import annotations

import copy
import unittest

from ade.autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
)
from ade.autonomous_backlog_goal import (
    BacklogPlanningPolicy,
    build_planning_goal_handoff,
)
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_retirement import (
    BacklogRetirementLedger,
    retire_from_verified_campaign,
)
from ade.autonomous_backlog_selection import select_next_backlog_candidate


REPO = "M-Osugi1230/one-minute-thought-experiments"
BASE_SHA = "a" * 40
MERGE_SHA = "b" * 40


def candidate() -> BacklogCandidate:
    return BacklogCandidate(
        candidate_id="backlog-followup",
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPO,
        source_sha=BASE_SHA,
        statement="Trusted evidence identifies a bounded test follow-up.",
        evidence_paths=(".autodev/runtime/recovery.json",),
        evidence_fingerprints=("c" * 64,),
        tags=("repair",),
    )


def handoff():
    value = candidate()
    backlog = AutonomousBacklog(candidates=(value,))
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
    return value, build_planning_goal_handoff(
        backlog,
        resolution,
        selection,
        policy=BacklogPlanningPolicy(
            repository=REPO,
            base_branch="main",
            allowed_path_prefixes=("tests",),
            max_tasks=2,
        ),
    )


def evidence() -> dict:
    value, goal_handoff = handoff()
    return {
        "schema_version": 1,
        "target_repository": REPO,
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "manual_campaign_progress_after_goal_submission": False,
        "autonomous_backlog": {
            "candidate_id": value.candidate_id,
            "candidate_fingerprint": value.fingerprint(),
            "handoff_fingerprint": goal_handoff.fingerprint(),
            "planning_request_fingerprint": goal_handoff.request.fingerprint(),
        },
        "task": {
            "task_id": "task-001",
            "base_sha": BASE_SHA,
            "merge_commit": MERGE_SHA,
        },
        "runtime_verification": {
            "workspace_source_sha": MERGE_SHA,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "receipt": {
                "status": "VERIFIED",
                "source_sha": MERGE_SHA,
                "target_repository": REPO,
            },
            "report": {
                "disposition": "VERIFIED",
                "source_sha": MERGE_SHA,
            },
        },
        "terminal_snapshot": {
            "campaign": {
                "status": "COMPLETED",
                "task_ids": ["task-001"],
                "completed_task_ids": ["task-001"],
            },
            "state": {
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
            },
        },
    }


class AutonomousBacklogRetirementTests(unittest.TestCase):
    def test_verified_campaign_creates_immutable_retirement(self) -> None:
        value, goal_handoff = handoff()
        retirement = retire_from_verified_campaign(
            value,
            goal_handoff,
            evidence_path=".autodev/campaign-evidence/backlog-proof.json",
            evidence_payload=evidence(),
        )
        self.assertEqual(retirement.candidate_id, value.candidate_id)
        self.assertEqual(retirement.base_source_sha, BASE_SHA)
        self.assertEqual(retirement.verified_merge_sha, MERGE_SHA)
        self.assertEqual(retirement.canonical_dict()["state"], "RETIRED_VERIFIED")
        self.assertFalse(retirement.canonical_dict()["execution_authority"])

        ledger = BacklogRetirementLedger(retirements=(retirement,))
        self.assertEqual(ledger.retired_candidate_ids, (value.candidate_id,))
        self.assertEqual(ledger.append, ledger.append)

    def test_non_verified_runtime_cannot_retire_candidate(self) -> None:
        value, goal_handoff = handoff()
        for field, replacement in (
            (("runtime_verification", "receipt", "status"), "FAILED"),
            (("runtime_verification", "report", "disposition"), "FAILED"),
            (("runtime_verification", "workspace_source_sha"), "d" * 40),
        ):
            payload = evidence()
            target = payload
            for key in field[:-1]:
                target = target[key]
            target[field[-1]] = replacement
            with self.subTest(field=field):
                with self.assertRaises(AutonomousBacklogError):
                    retire_from_verified_campaign(
                        value,
                        goal_handoff,
                        evidence_path=".autodev/campaign-evidence/backlog-proof.json",
                        evidence_payload=payload,
                    )

    def test_recovery_human_wait_or_manual_progress_blocks_retirement(self) -> None:
        value, goal_handoff = handoff()
        for mutation in ("recovery", "human_wait", "manual"):
            payload = evidence()
            if mutation == "recovery":
                payload["runtime_verification"]["recovery_triggered"] = True
            elif mutation == "human_wait":
                payload["runtime_verification"]["human_wait_triggered"] = True
            else:
                payload["manual_campaign_progress_after_goal_submission"] = True
            with self.subTest(mutation=mutation):
                with self.assertRaises(AutonomousBacklogError):
                    retire_from_verified_campaign(
                        value,
                        goal_handoff,
                        evidence_path=".autodev/campaign-evidence/backlog-proof.json",
                        evidence_payload=payload,
                    )

    def test_candidate_handoff_and_base_sha_must_bind_exactly(self) -> None:
        value, goal_handoff = handoff()
        payload = evidence()
        payload["autonomous_backlog"]["candidate_id"] = "backlog-other"
        with self.assertRaisesRegex(AutonomousBacklogError, "selected backlog"):
            retire_from_verified_campaign(
                value,
                goal_handoff,
                evidence_path=".autodev/campaign-evidence/backlog-proof.json",
                evidence_payload=payload,
            )

        payload = evidence()
        payload["task"]["base_sha"] = "e" * 40
        with self.assertRaisesRegex(AutonomousBacklogError, "base SHA"):
            retire_from_verified_campaign(
                value,
                goal_handoff,
                evidence_path=".autodev/campaign-evidence/backlog-proof.json",
                evidence_payload=payload,
            )

    def test_conflicting_duplicate_retirement_fails_closed(self) -> None:
        value, goal_handoff = handoff()
        first = retire_from_verified_campaign(
            value,
            goal_handoff,
            evidence_path=".autodev/campaign-evidence/backlog-proof.json",
            evidence_payload=evidence(),
        )
        payload = evidence()
        payload["extra_observation"] = "trusted extra evidence changes the evidence fingerprint"
        second = retire_from_verified_campaign(
            value,
            goal_handoff,
            evidence_path=".autodev/campaign-evidence/backlog-proof-2.json",
            evidence_payload=payload,
        )
        with self.assertRaisesRegex(AutonomousBacklogError, "conflicting retirements"):
            BacklogRetirementLedger(retirements=(first, second))


if __name__ == "__main__":
    unittest.main()

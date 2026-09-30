from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_backlog import AutonomousBacklog, BacklogCandidate, BacklogCandidateKind
from ade.autonomous_backlog_goal import BacklogPlanningPolicy, build_planning_goal_handoff
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_retirement import BacklogRetirementLedger, retire_from_verified_campaign
from ade.autonomous_backlog_selection import select_next_backlog_candidate


REPO = "M-Osugi1230/one-minute-thought-experiments"
BASE_SHA = "a" * 40
MERGE_SHA = "b" * 40


def main() -> int:
    candidate = BacklogCandidate(
        candidate_id="backlog-followup",
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPO,
        source_sha=BASE_SHA,
        statement="Trusted evidence identifies a bounded test follow-up.",
        evidence_paths=(".autodev/runtime/recovery.json",),
        evidence_fingerprints=("c" * 64,),
        tags=("repair",),
    )
    backlog = AutonomousBacklog(candidates=(candidate,))
    resolution = resolve_autonomous_backlog(backlog, current_sources={REPO: BASE_SHA})
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
            max_tasks=2,
        ),
    )
    evidence = {
        "schema_version": 1,
        "target_repository": REPO,
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "manual_campaign_progress_after_goal_submission": False,
        "autonomous_backlog": {
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.fingerprint(),
            "handoff_fingerprint": handoff.fingerprint(),
            "planning_request_fingerprint": handoff.request.fingerprint(),
        },
        "task": {"base_sha": BASE_SHA, "merge_commit": MERGE_SHA},
        "runtime_verification": {
            "workspace_source_sha": MERGE_SHA,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "receipt": {
                "status": "VERIFIED",
                "source_sha": MERGE_SHA,
                "target_repository": REPO,
            },
            "report": {"disposition": "VERIFIED", "source_sha": MERGE_SHA},
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
    retirement = retire_from_verified_campaign(
        candidate,
        handoff,
        evidence_path=".autodev/campaign-evidence/backlog-proof.json",
        evidence_payload=evidence,
    )
    ledger = BacklogRetirementLedger(retirements=(retirement,))
    assert ledger.retired_candidate_ids == (candidate.candidate_id,)
    assert retirement.verified_merge_sha == MERGE_SHA
    assert retirement.canonical_dict()["execution_authority"] is False

    print(json.dumps({
        "ok": True,
        "candidate_id": candidate.candidate_id,
        "state": "RETIRED_VERIFIED",
        "base_source_sha": BASE_SHA,
        "verified_merge_sha": MERGE_SHA,
        "requires_campaign_completed": True,
        "requires_runtime_verified": True,
        "requires_clean_terminal_state": True,
        "retirement_fingerprint": retirement.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

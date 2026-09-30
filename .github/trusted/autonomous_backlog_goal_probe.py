from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_backlog import AutonomousBacklog, BacklogCandidate, BacklogCandidateKind
from ade.autonomous_backlog_goal import BacklogPlanningPolicy, build_planning_goal_handoff
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40


def main() -> int:
    candidate = BacklogCandidate(
        candidate_id="backlog-followup",
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPO,
        source_sha=SHA,
        statement="Trusted evidence identifies a bounded test follow-up.",
        evidence_paths=(".autodev/runtime/recovery.json",),
        evidence_fingerprints=("b" * 64,),
        tags=("repair",),
    )
    backlog = AutonomousBacklog(candidates=(candidate,))
    resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={REPO: SHA},
    )
    selection = select_next_backlog_candidate(
        backlog,
        resolution,
        repository=REPO,
        source_sha=SHA,
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
    payload = handoff.canonical_dict()
    assert payload["handoff_target"] == "AutonomousPlanner"
    assert payload["execution_authority"] is False
    assert payload["accepted_plan_authority"] is False
    assert payload["auto_dispatch"] is False
    assert "tasks" not in payload["planning_goal_request"]
    assert payload["planning_goal_request"]["allowed_path_prefixes"] == ["tests"]

    print(json.dumps({
        "ok": True,
        "candidate_id": candidate.candidate_id,
        "planning_request_id": handoff.request.request_id,
        "handoff_target": "AutonomousPlanner",
        "scope_source": "trusted-backlog-planning-policy-v1",
        "contains_tasks": False,
        "execution_authority": False,
        "accepted_plan_authority": False,
        "handoff_fingerprint": handoff.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

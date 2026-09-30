from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_backlog import AutonomousBacklog, BacklogCandidate, BacklogCandidateKind
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
HASH = "b" * 64


def make(candidate_id: str, kind: BacklogCandidateKind, *, human_only: bool = False) -> BacklogCandidate:
    return BacklogCandidate(
        candidate_id=candidate_id,
        kind=kind,
        repository=REPO,
        source_sha=SHA,
        statement=f"Trusted evidence identifies bounded {candidate_id} work.",
        evidence_paths=(".autodev/campaign-evidence/example.json",),
        evidence_fingerprints=(HASH,),
        tags=(candidate_id,),
        human_only=human_only,
    )


def main() -> int:
    backlog = AutonomousBacklog(
        candidates=(
            make("backlog-remediation", BacklogCandidateKind.VERIFIED_REMEDIATION),
            make("backlog-acceptance", BacklogCandidateKind.ACCEPTANCE_GAP),
            make("backlog-human", BacklogCandidateKind.RUNTIME_GAP, human_only=True),
        )
    )
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
    assert selection.selected_candidate_id == "backlog-acceptance"
    assert "backlog-human" not in selection.eligible_candidate_ids
    payload = selection.canonical_dict()
    assert payload["execution_authority"] is False
    assert payload["planning_goal_authority"] is False
    assert payload["auto_dispatch"] is False

    print(json.dumps({
        "ok": True,
        "selected_candidate_id": selection.selected_candidate_id,
        "eligible_count": len(selection.eligible_candidate_ids),
        "human_only_excluded": True,
        "source_sha_bound": True,
        "single_selection": True,
        "execution_authority": False,
        "planning_goal_authority": False,
        "selection_fingerprint": selection.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
    build_candidate_id,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "a" * 40
EVIDENCE_FINGERPRINT = "b" * 64


def main() -> int:
    statement = "Trusted verified evidence identifies one bounded follow-up candidate."
    candidate_id = build_candidate_id(
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        statement=statement,
        evidence_fingerprints=(EVIDENCE_FINGERPRINT,),
    )
    candidate = BacklogCandidate(
        candidate_id=candidate_id,
        kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        statement=statement,
        evidence_paths=(".autodev/campaign-evidence/example.json",),
        evidence_fingerprints=(EVIDENCE_FINGERPRINT,),
        tags=("evidence", "verified"),
        source_phase="v1.6-autonomous-backlog",
    )
    backlog = AutonomousBacklog(candidates=(candidate,))
    round_trip = AutonomousBacklog.from_dict(backlog.canonical_dict())
    assert round_trip == backlog
    assert round_trip.fingerprint() == backlog.fingerprint()
    assert round_trip.canonical_dict()["execution_authority"] is False
    assert round_trip.canonical_dict()["auto_dispatch"] is False
    assert candidate.canonical_dict()["may_expand_scope"] is False

    rejected = False
    escalated = candidate.canonical_dict()
    escalated["execution_authority"] = True
    try:
        BacklogCandidate.from_dict(escalated)
    except AutonomousBacklogError:
        rejected = True
    assert rejected

    print(
        json.dumps(
            {
                "ok": True,
                "candidate_id": candidate_id,
                "candidate_fingerprint": candidate.fingerprint(),
                "backlog_fingerprint": backlog.fingerprint(),
                "evidence_bound": True,
                "immutable_round_trip": True,
                "execution_authority": False,
                "auto_dispatch": False,
                "scope_expansion_authority": False,
                "authority_escalation_rejected": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

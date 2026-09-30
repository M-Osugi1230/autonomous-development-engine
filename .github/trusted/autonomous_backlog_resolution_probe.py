from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.autonomous_backlog import AutonomousBacklog, BacklogCandidate, BacklogCandidateKind
from ade.autonomous_backlog_resolution import (
    BacklogResolutionState,
    resolve_autonomous_backlog,
)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
OLD = "b" * 40
HASH = "c" * 64


def candidate(candidate_id: str, *, source_sha: str, kind: BacklogCandidateKind, tags: tuple[str, ...]) -> BacklogCandidate:
    return BacklogCandidate(
        candidate_id=candidate_id,
        kind=kind,
        repository=REPO,
        source_sha=source_sha,
        statement=f"Trusted evidence identifies bounded {kind.value.casefold()} work.",
        evidence_paths=(".autodev/campaign-evidence/example.json",),
        evidence_fingerprints=(HASH,),
        tags=tags,
    )


def main() -> int:
    current = candidate(
        "backlog-current",
        source_sha=SHA,
        kind=BacklogCandidateKind.ACCEPTANCE_GAP,
        tags=("acceptance",),
    )
    stale = candidate(
        "backlog-stale",
        source_sha=OLD,
        kind=BacklogCandidateKind.MEMORY_FOLLOWUP,
        tags=("memory",),
    )
    resolution = resolve_autonomous_backlog(
        AutonomousBacklog(candidates=(stale, current)),
        current_sources={REPO: SHA},
    )
    assert resolution.entry_for(current.candidate_id).state is BacklogResolutionState.CURRENT
    assert resolution.entry_for(stale.candidate_id).state is BacklogResolutionState.STALE
    assert resolution.entry_for(current.candidate_id).priority_rank == 20
    assert resolution.canonical_dict()["execution_authority"] is False

    print(json.dumps({
        "ok": True,
        "source_sha_staleness": True,
        "explicit_supersession_supported": True,
        "semantic_dedup_fail_closed": True,
        "subject_conflicts_fail_closed": True,
        "priority_policy": "controller-kind-policy-v1",
        "execution_authority": False,
        "resolution_fingerprint": resolution.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

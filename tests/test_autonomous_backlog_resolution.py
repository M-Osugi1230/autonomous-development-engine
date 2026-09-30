from __future__ import annotations

import unittest

from ade.autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
)
from ade.autonomous_backlog_resolution import (
    BacklogResolutionReason,
    BacklogResolutionState,
    BacklogSupersession,
    candidate_priority,
    resolve_autonomous_backlog,
)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
OLD = "b" * 40
HASH = "c" * 64


def item(
    candidate_id: str,
    *,
    kind: BacklogCandidateKind = BacklogCandidateKind.VERIFIED_REMEDIATION,
    source_sha: str = SHA,
    statement: str = "Trusted evidence identifies a bounded repair.",
    tags: tuple[str, ...] = ("repair",),
    human_only: bool = False,
) -> BacklogCandidate:
    return BacklogCandidate(
        candidate_id=candidate_id,
        kind=kind,
        repository=REPO,
        source_sha=source_sha,
        statement=statement,
        evidence_paths=(".autodev/runtime/recovery.json",),
        evidence_fingerprints=(HASH,),
        tags=tags,
        human_only=human_only,
    )


class AutonomousBacklogResolutionTests(unittest.TestCase):
    def test_current_and_stale_are_source_sha_bound(self) -> None:
        current = item("backlog-current")
        stale = item("backlog-stale", source_sha=OLD)
        resolution = resolve_autonomous_backlog(
            AutonomousBacklog(candidates=(stale, current)),
            current_sources={REPO: SHA},
        )
        self.assertEqual(
            resolution.entry_for("backlog-current").state,
            BacklogResolutionState.CURRENT,
        )
        self.assertEqual(
            resolution.entry_for("backlog-stale").state,
            BacklogResolutionState.STALE,
        )

    def test_explicit_supersession_requires_same_repository_and_has_precedence(self) -> None:
        old = item("backlog-old", source_sha=OLD)
        new = item("backlog-new")
        link = BacklogSupersession(
            prior_candidate_id=old.candidate_id,
            successor_candidate_id=new.candidate_id,
            evidence_path=".autodev/campaign-evidence/supersession.json",
            evidence_fingerprint="d" * 64,
        )
        resolution = resolve_autonomous_backlog(
            AutonomousBacklog(candidates=(old, new)),
            current_sources={REPO: SHA},
            supersessions=(link,),
        )
        entry = resolution.entry_for(old.candidate_id)
        self.assertEqual(entry.state, BacklogResolutionState.SUPERSEDED)
        self.assertEqual(entry.reason, BacklogResolutionReason.EXPLICIT_SUPERSESSION)

    def test_semantic_duplicates_are_deduplicated_deterministically(self) -> None:
        a = item("backlog-a")
        b = item("backlog-b")
        resolution = resolve_autonomous_backlog(
            AutonomousBacklog(candidates=(b, a)),
            current_sources={REPO: SHA},
        )
        self.assertEqual(
            resolution.entry_for("backlog-a").state,
            BacklogResolutionState.CURRENT,
        )
        duplicate = resolution.entry_for("backlog-b")
        self.assertEqual(duplicate.state, BacklogResolutionState.SUPERSEDED)
        self.assertEqual(duplicate.reason, BacklogResolutionReason.SEMANTIC_DUPLICATE)

    def test_conflicting_current_subjects_fail_closed_to_conflicted(self) -> None:
        a = item("backlog-a", statement="Trusted evidence identifies repair alpha.")
        b = item("backlog-b", statement="Trusted evidence identifies repair beta.")
        resolution = resolve_autonomous_backlog(
            AutonomousBacklog(candidates=(a, b)),
            current_sources={REPO: SHA},
        )
        self.assertEqual(
            resolution.entry_for("backlog-a").state,
            BacklogResolutionState.CONFLICTED,
        )
        self.assertEqual(
            resolution.entry_for("backlog-b").reason,
            BacklogResolutionReason.SUBJECT_CONFLICT,
        )

    def test_priority_is_controller_owned_by_kind(self) -> None:
        expected = {
            BacklogCandidateKind.RUNTIME_GAP: 10,
            BacklogCandidateKind.ACCEPTANCE_GAP: 20,
            BacklogCandidateKind.VERIFIED_REMEDIATION: 30,
            BacklogCandidateKind.REPOSITORY_HYGIENE: 40,
            BacklogCandidateKind.MEMORY_FOLLOWUP: 50,
        }
        for kind, rank in expected.items():
            with self.subTest(kind=kind):
                self.assertEqual(
                    candidate_priority(
                        item(
                            "backlog-" + kind.value.casefold().replace("_", "-"),
                            kind=kind,
                            tags=(kind.value.casefold().replace("_", "-"),),
                        )
                    ),
                    rank,
                )

    def test_missing_current_source_and_supersession_cycles_fail_closed(self) -> None:
        a = item("backlog-a")
        b = item("backlog-b", tags=("other",))
        backlog = AutonomousBacklog(candidates=(a, b))
        with self.assertRaisesRegex(AutonomousBacklogError, "current_sources"):
            resolve_autonomous_backlog(backlog, current_sources={})

        links = (
            BacklogSupersession(
                "backlog-a",
                "backlog-b",
                ".autodev/campaign-evidence/a.json",
                "d" * 64,
            ),
            BacklogSupersession(
                "backlog-b",
                "backlog-a",
                ".autodev/campaign-evidence/b.json",
                "e" * 64,
            ),
        )
        with self.assertRaisesRegex(AutonomousBacklogError, "cycle"):
            resolve_autonomous_backlog(
                backlog,
                current_sources={REPO: SHA},
                supersessions=links,
            )

    def test_resolution_is_order_deterministic(self) -> None:
        a = item("backlog-a")
        b = item(
            "backlog-b",
            kind=BacklogCandidateKind.REPOSITORY_HYGIENE,
            tags=("hygiene",),
        )
        left = resolve_autonomous_backlog(
            AutonomousBacklog(candidates=(a, b)),
            current_sources={REPO: SHA},
        )
        right = resolve_autonomous_backlog(
            AutonomousBacklog(candidates=(b, a)),
            current_sources={REPO: SHA},
        )
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())
        self.assertFalse(left.canonical_dict()["execution_authority"])


if __name__ == "__main__":
    unittest.main()

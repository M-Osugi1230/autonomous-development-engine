from __future__ import annotations

import unittest

from ade.autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
)
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
OLD = "b" * 40
HASH = "c" * 64


def item(
    candidate_id: str,
    *,
    kind: BacklogCandidateKind,
    source_sha: str = SHA,
    human_only: bool = False,
    tags: tuple[str, ...],
) -> BacklogCandidate:
    return BacklogCandidate(
        candidate_id=candidate_id,
        kind=kind,
        repository=REPO,
        source_sha=source_sha,
        statement=f"Trusted evidence identifies bounded {candidate_id} work.",
        evidence_paths=(".autodev/campaign-evidence/example.json",),
        evidence_fingerprints=(HASH,),
        tags=tags,
        human_only=human_only,
    )


class AutonomousBacklogSelectionTests(unittest.TestCase):
    def test_selects_at_most_one_by_controller_priority_then_id(self) -> None:
        acceptance = item(
            "backlog-acceptance",
            kind=BacklogCandidateKind.ACCEPTANCE_GAP,
            tags=("acceptance",),
        )
        remediation = item(
            "backlog-remediation",
            kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
            tags=("remediation",),
        )
        backlog = AutonomousBacklog(candidates=(remediation, acceptance))
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
        self.assertEqual(selection.selected_candidate_id, "backlog-acceptance")
        self.assertEqual(
            selection.eligible_candidate_ids,
            ("backlog-acceptance", "backlog-remediation"),
        )
        self.assertFalse(selection.canonical_dict()["execution_authority"])
        self.assertFalse(selection.canonical_dict()["planning_goal_authority"])

    def test_human_only_stale_and_conflicted_candidates_are_excluded(self) -> None:
        human = item(
            "backlog-human",
            kind=BacklogCandidateKind.RUNTIME_GAP,
            human_only=True,
            tags=("runtime",),
        )
        stale = item(
            "backlog-stale",
            kind=BacklogCandidateKind.ACCEPTANCE_GAP,
            source_sha=OLD,
            tags=("stale",),
        )
        conflict_a = item(
            "backlog-conflict-a",
            kind=BacklogCandidateKind.REPOSITORY_HYGIENE,
            tags=("same",),
        )
        conflict_b = BacklogCandidate(
            candidate_id="backlog-conflict-b",
            kind=BacklogCandidateKind.REPOSITORY_HYGIENE,
            repository=REPO,
            source_sha=SHA,
            statement="Trusted evidence identifies contradictory bounded work.",
            evidence_paths=(".autodev/campaign-evidence/other.json",),
            evidence_fingerprints=("d" * 64,),
            tags=("same",),
        )
        backlog = AutonomousBacklog(
            candidates=(human, stale, conflict_a, conflict_b)
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
        self.assertIsNone(selection.selected_candidate_id)
        self.assertEqual(selection.eligible_candidate_ids, ())

    def test_retired_candidates_are_excluded_from_future_selection(self) -> None:
        acceptance = item(
            "backlog-acceptance",
            kind=BacklogCandidateKind.ACCEPTANCE_GAP,
            tags=("acceptance",),
        )
        remediation = item(
            "backlog-remediation",
            kind=BacklogCandidateKind.VERIFIED_REMEDIATION,
            tags=("remediation",),
        )
        backlog = AutonomousBacklog(candidates=(acceptance, remediation))
        resolution = resolve_autonomous_backlog(
            backlog,
            current_sources={REPO: SHA},
        )
        selection = select_next_backlog_candidate(
            backlog,
            resolution,
            repository=REPO,
            source_sha=SHA,
            retired_candidate_ids=("backlog-acceptance",),
        )
        self.assertEqual(selection.selected_candidate_id, "backlog-remediation")
        self.assertEqual(selection.retired_candidate_ids, ("backlog-acceptance",))
        self.assertNotIn("backlog-acceptance", selection.eligible_candidate_ids)

    def test_unknown_retirement_fails_closed(self) -> None:
        value = item(
            "backlog-one",
            kind=BacklogCandidateKind.ACCEPTANCE_GAP,
            tags=("acceptance",),
        )
        backlog = AutonomousBacklog(candidates=(value,))
        resolution = resolve_autonomous_backlog(
            backlog,
            current_sources={REPO: SHA},
        )
        with self.assertRaisesRegex(AutonomousBacklogError, "unknown"):
            select_next_backlog_candidate(
                backlog,
                resolution,
                repository=REPO,
                source_sha=SHA,
                retired_candidate_ids=("backlog-missing",),
            )

    def test_selection_rejects_wrong_source_or_mismatched_resolution(self) -> None:
        value = item(
            "backlog-one",
            kind=BacklogCandidateKind.ACCEPTANCE_GAP,
            tags=("acceptance",),
        )
        backlog = AutonomousBacklog(candidates=(value,))
        resolution = resolve_autonomous_backlog(
            backlog,
            current_sources={REPO: SHA},
        )
        with self.assertRaisesRegex(AutonomousBacklogError, "source SHA"):
            select_next_backlog_candidate(
                backlog,
                resolution,
                repository=REPO,
                source_sha=OLD,
            )

        other = AutonomousBacklog(
            candidates=(
                item(
                    "backlog-other",
                    kind=BacklogCandidateKind.REPOSITORY_HYGIENE,
                    tags=("other",),
                ),
            )
        )
        with self.assertRaisesRegex(AutonomousBacklogError, "does not bind"):
            select_next_backlog_candidate(
                other,
                resolution,
                repository=REPO,
                source_sha=SHA,
            )


if __name__ == "__main__":
    unittest.main()

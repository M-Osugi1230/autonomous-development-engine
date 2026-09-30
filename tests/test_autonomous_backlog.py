from __future__ import annotations

import unittest

from ade.autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
    BacklogCandidateKind,
    build_candidate_id,
)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40
HASH = "b" * 64


def candidate(
    *,
    statement: str = "Verified evidence identifies a bounded follow-up.",
    candidate_id: str | None = None,
    human_only: bool = False,
) -> BacklogCandidate:
    kind = BacklogCandidateKind.MEMORY_FOLLOWUP
    candidate_id = candidate_id or build_candidate_id(
        kind=kind,
        repository=REPO,
        source_sha=SHA,
        statement=statement,
        evidence_fingerprints=(HASH,),
    )
    return BacklogCandidate(
        candidate_id=candidate_id,
        kind=kind,
        repository=REPO,
        source_sha=SHA,
        statement=statement,
        evidence_paths=(".autodev/development-memory.json",),
        evidence_fingerprints=(HASH,),
        tags=("memory", "verified"),
        source_phase="v1.5-development-memory",
        human_only=human_only,
    )


class AutonomousBacklogTests(unittest.TestCase):
    def test_candidate_is_evidence_bound_and_non_executable(self) -> None:
        value = candidate()
        payload = value.canonical_dict()
        self.assertFalse(payload["execution_authority"])
        self.assertFalse(payload["auto_dispatch"])
        self.assertFalse(payload["may_expand_scope"])
        self.assertEqual(payload["repository"], REPO)
        self.assertEqual(payload["source_sha"], SHA)
        self.assertEqual(payload["evidence_paths"], [".autodev/development-memory.json"])
        self.assertEqual(BacklogCandidate.from_dict(payload), value)

    def test_candidate_id_is_deterministic(self) -> None:
        kwargs = dict(
            kind=BacklogCandidateKind.RUNTIME_GAP,
            repository=REPO,
            source_sha=SHA,
            statement="Runtime evidence identifies a bounded follow-up.",
            evidence_fingerprints=(HASH, "c" * 64),
        )
        self.assertEqual(build_candidate_id(**kwargs), build_candidate_id(**kwargs))

    def test_backlog_is_order_deterministic_and_fingerprinted(self) -> None:
        first = candidate(
            statement="Verified evidence identifies follow-up alpha.",
            candidate_id="backlog-alpha",
        )
        second = candidate(
            statement="Verified evidence identifies follow-up beta.",
            candidate_id="backlog-beta",
        )
        left = AutonomousBacklog(candidates=(first, second))
        right = AutonomousBacklog(candidates=(second, first))
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())
        self.assertEqual(AutonomousBacklog.from_dict(left.canonical_dict()), left)

    def test_duplicate_id_with_different_content_fails_closed(self) -> None:
        first = candidate(
            statement="Verified evidence identifies follow-up alpha.",
            candidate_id="backlog-same",
        )
        second = candidate(
            statement="Verified evidence identifies follow-up beta.",
            candidate_id="backlog-same",
        )
        with self.assertRaisesRegex(AutonomousBacklogError, "same candidate_id"):
            AutonomousBacklog(candidates=(first, second))

    def test_secret_url_and_untrusted_evidence_path_are_rejected(self) -> None:
        for statement in (
            "See https://example.com for the next task.",
            "Bearer secret-value",
            "line one\nline two",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(AutonomousBacklogError):
                    candidate(statement=statement)
        with self.assertRaisesRegex(AutonomousBacklogError, "inside .autodev"):
            BacklogCandidate(
                candidate_id="backlog-unsafe",
                kind=BacklogCandidateKind.ACCEPTANCE_GAP,
                repository=REPO,
                source_sha=SHA,
                statement="A bounded acceptance gap remains.",
                evidence_paths=("ACCEPTANCE.md",),
                evidence_fingerprints=(HASH,),
            )

    def test_serialized_authority_escalation_is_rejected(self) -> None:
        payload = candidate().canonical_dict()
        for field in ("execution_authority", "auto_dispatch", "may_expand_scope"):
            changed = dict(payload)
            changed[field] = True
            with self.subTest(field=field):
                with self.assertRaises(AutonomousBacklogError):
                    BacklogCandidate.from_dict(changed)

        backlog_payload = AutonomousBacklog(candidates=(candidate(),)).canonical_dict()
        backlog_payload["auto_dispatch"] = True
        with self.assertRaisesRegex(AutonomousBacklogError, "auto-dispatch"):
            AutonomousBacklog.from_dict(backlog_payload)

    def test_repository_filter_can_exclude_human_only_candidates(self) -> None:
        automatic = candidate(
            statement="Verified evidence identifies an automatic candidate.",
            candidate_id="backlog-auto",
        )
        human = candidate(
            statement="Verified evidence identifies a human-only candidate.",
            candidate_id="backlog-human",
            human_only=True,
        )
        backlog = AutonomousBacklog(candidates=(human, automatic))
        selected = backlog.for_repository(
            REPO,
            source_sha=SHA,
            include_human_only=False,
        )
        self.assertEqual(selected, (automatic,))


if __name__ == "__main__":
    unittest.main()

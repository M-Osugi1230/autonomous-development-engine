from __future__ import annotations

import unittest

from ade.development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_resolution import (
    MemoryResolutionStatus,
    MemorySupersession,
    MemorySupersessionReason,
    resolve_development_memory,
)


CURRENT_SHA = "a" * 40
OLD_SHA = "b" * 40
HASH_A = "1" * 64
HASH_B = "2" * 64


def memory(
    memory_id: str,
    *,
    kind: MemoryKind,
    source_sha: str,
    statement: str,
    tags: tuple[str, ...],
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=kind,
        repository="owner/repo",
        source_sha=source_sha,
        statement=statement,
        evidence_paths=(f".autodev/evidence/{memory_id}.json",),
        evidence_fingerprints=(HASH_A if memory_id.endswith("1") else HASH_B,),
        tags=tags,
        task_id="task-001",
    )


class DevelopmentMemoryResolutionTests(unittest.TestCase):
    def test_current_verified_and_historical_lessons_are_eligible(self) -> None:
        verified = memory(
            "memory-001",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT_SHA,
            statement="Runtime verification passed at the current source SHA.",
            tags=("runtime", "verified"),
        )
        failure = memory(
            "memory-002",
            kind=MemoryKind.FAILURE,
            source_sha=OLD_SHA,
            statement="A runtime verification attempt previously failed closed.",
            tags=("runtime", "failure"),
        )
        result = resolve_development_memory(
            DevelopmentMemoryLedger(records=(failure, verified)),
            current_source_shas={"owner/repo": CURRENT_SHA},
        )
        by_id = {item.record.memory_id: item for item in result.records}
        self.assertEqual(
            by_id["memory-001"].status,
            MemoryResolutionStatus.CURRENT,
        )
        self.assertEqual(
            by_id["memory-002"].status,
            MemoryResolutionStatus.HISTORICAL,
        )
        self.assertEqual(
            {record.memory_id for record in result.eligible_ledger().records},
            {"memory-001", "memory-002"},
        )

    def test_old_verified_outcome_is_stale_and_excluded(self) -> None:
        stale = memory(
            "memory-001",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=OLD_SHA,
            statement="Runtime verification passed at an older source SHA.",
            tags=("runtime", "verified"),
        )
        result = resolve_development_memory(
            DevelopmentMemoryLedger(records=(stale,)),
            current_source_shas={"owner/repo": CURRENT_SHA},
        )
        self.assertEqual(
            result.records[0].status,
            MemoryResolutionStatus.STALE,
        )
        self.assertEqual(result.eligible_ledger().records, ())

    def test_explicit_supersession_excludes_old_memory(self) -> None:
        old = memory(
            "memory-001",
            kind=MemoryKind.REMEDIATION,
            source_sha=OLD_SHA,
            statement="An earlier remediation rule was used.",
            tags=("recovery", "rule"),
        )
        new = memory(
            "memory-002",
            kind=MemoryKind.REMEDIATION,
            source_sha=CURRENT_SHA,
            statement="A stricter remediation rule replaced the earlier rule.",
            tags=("recovery", "rule"),
        )
        link = MemorySupersession(
            superseded_memory_id="memory-001",
            successor_memory_id="memory-002",
            reason=MemorySupersessionReason.CORRECTED,
            evidence_path=".autodev/evidence/supersession.json",
            evidence_fingerprint="3" * 64,
        )
        result = resolve_development_memory(
            DevelopmentMemoryLedger(records=(old, new)),
            current_source_shas={"owner/repo": CURRENT_SHA},
            supersessions=(link,),
        )
        by_id = {item.record.memory_id: item for item in result.records}
        self.assertEqual(
            by_id["memory-001"].status,
            MemoryResolutionStatus.SUPERSEDED,
        )
        self.assertEqual(
            by_id["memory-002"].status,
            MemoryResolutionStatus.HISTORICAL,
        )
        self.assertEqual(
            [record.memory_id for record in result.eligible_ledger().records],
            ["memory-002"],
        )

    def test_conflicting_current_verified_memories_fail_closed_from_eligibility(self) -> None:
        first = memory(
            "memory-001",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT_SHA,
            statement="Runtime target is verified.",
            tags=("runtime", "status"),
        )
        second = memory(
            "memory-002",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT_SHA,
            statement="Runtime target is not verified.",
            tags=("runtime", "status"),
        )
        result = resolve_development_memory(
            DevelopmentMemoryLedger(records=(first, second)),
            current_source_shas={"owner/repo": CURRENT_SHA},
        )
        self.assertEqual(len(result.conflicted), 2)
        self.assertEqual(result.eligible_ledger().records, ())

    def test_identical_current_statements_are_not_false_conflicts(self) -> None:
        first = memory(
            "memory-001",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT_SHA,
            statement="Runtime target is verified.",
            tags=("runtime", "status"),
        )
        second = memory(
            "memory-002",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT_SHA,
            statement="Runtime target is verified.",
            tags=("runtime", "status"),
        )
        result = resolve_development_memory(
            DevelopmentMemoryLedger(records=(first, second)),
            current_source_shas={"owner/repo": CURRENT_SHA},
        )
        self.assertFalse(result.conflicted)
        self.assertEqual(len(result.eligible_ledger().records), 2)


    def test_supersession_requires_trusted_evidence_and_same_subject(self) -> None:
        old = memory(
            "memory-001",
            kind=MemoryKind.REMEDIATION,
            source_sha=OLD_SHA,
            statement="Earlier recovery lesson.",
            tags=("recovery", "rule"),
        )
        different_subject = DevelopmentMemoryRecord(
            memory_id="memory-002",
            kind=MemoryKind.REMEDIATION,
            repository="owner/repo",
            source_sha=CURRENT_SHA,
            statement="Different task recovery lesson.",
            evidence_paths=(".autodev/evidence/memory-002.json",),
            evidence_fingerprints=(HASH_B,),
            tags=("recovery", "rule"),
            task_id="task-002",
        )
        ledger = DevelopmentMemoryLedger(records=(old, different_subject))

        with self.assertRaisesRegex(DevelopmentMemoryError, "inside .autodev"):
            MemorySupersession(
                superseded_memory_id="memory-001",
                successor_memory_id="memory-002",
                reason=MemorySupersessionReason.CORRECTED,
                evidence_path="README.md",
                evidence_fingerprint="3" * 64,
            )

        link = MemorySupersession(
            superseded_memory_id="memory-001",
            successor_memory_id="memory-002",
            reason=MemorySupersessionReason.CORRECTED,
            evidence_path=".autodev/evidence/supersession.json",
            evidence_fingerprint="3" * 64,
        )
        with self.assertRaisesRegex(DevelopmentMemoryError, "memory subjects"):
            resolve_development_memory(
                ledger,
                current_source_shas={"owner/repo": CURRENT_SHA},
                supersessions=(link,),
            )

    def test_missing_current_source_and_bad_supersession_fail_closed(self) -> None:
        first = memory(
            "memory-001",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT_SHA,
            statement="Current outcome.",
            tags=("runtime", "verified"),
        )
        second = memory(
            "memory-002",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT_SHA,
            statement="Corrected current outcome.",
            tags=("runtime", "verified"),
        )
        ledger = DevelopmentMemoryLedger(records=(first, second))

        with self.assertRaisesRegex(DevelopmentMemoryError, "current source SHA"):
            resolve_development_memory(ledger, current_source_shas={})

        cycle = (
            MemorySupersession(
                "memory-001",
                "memory-002",
                MemorySupersessionReason.RETIRED,
                ".autodev/evidence/supersession-a.json",
                "3" * 64,
            ),
            MemorySupersession(
                "memory-002",
                "memory-001",
                MemorySupersessionReason.RETIRED,
                ".autodev/evidence/supersession-b.json",
                "4" * 64,
            ),
        )
        with self.assertRaisesRegex(DevelopmentMemoryError, "cycle"):
            resolve_development_memory(
                ledger,
                current_source_shas={"owner/repo": CURRENT_SHA},
                supersessions=cycle,
            )


if __name__ == "__main__":
    unittest.main()

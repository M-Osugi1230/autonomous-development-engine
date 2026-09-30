from __future__ import annotations

import unittest

from ade.development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
    build_planner_memory_context,
)


SHA_A = "a" * 40
SHA_B = "b" * 40
HASH_A = "1" * 64
HASH_B = "2" * 64


def record(
    memory_id: str,
    *,
    kind: MemoryKind = MemoryKind.VERIFIED_OUTCOME,
    repository: str = "owner/repo",
    source_sha: str = SHA_A,
    statement: str = "Runtime verification passed against the exact trusted merge SHA.",
    evidence_paths: tuple[str, ...] = (
        ".autodev/campaign-evidence/proof.json",
    ),
    evidence_fingerprints: tuple[str, ...] = (HASH_A,),
    tags: tuple[str, ...] = ("runtime", "verified"),
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=kind,
        repository=repository,
        source_sha=source_sha,
        statement=statement,
        evidence_paths=evidence_paths,
        evidence_fingerprints=evidence_fingerprints,
        tags=tags,
        campaign_id="campaign-001",
        task_id="task-001",
    )


class DevelopmentMemoryTests(unittest.TestCase):
    def test_record_canonicalization_and_fingerprint_are_deterministic(self) -> None:
        first = record(
            "memory-001",
            evidence_paths=(
                ".autodev/runtime/report.json",
                ".autodev/campaign-evidence/proof.json",
            ),
            evidence_fingerprints=(HASH_B, HASH_A),
            tags=("verified", "runtime"),
        )
        second = record(
            "memory-001",
            evidence_paths=(
                ".autodev/campaign-evidence/proof.json",
                ".autodev/runtime/report.json",
            ),
            evidence_fingerprints=(HASH_A, HASH_B),
            tags=("runtime", "verified"),
        )
        self.assertEqual(first.canonical_dict(), second.canonical_dict())
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_ledger_is_order_independent_and_duplicate_safe(self) -> None:
        first = record("memory-001")
        second = record(
            "memory-002",
            kind=MemoryKind.FAILURE,
            source_sha=SHA_B,
            statement="A runtime evidence write failed closed before target evidence existed.",
            evidence_fingerprints=(HASH_B,),
            tags=("failure", "runtime"),
        )
        left = DevelopmentMemoryLedger(records=(first, second))
        right = DevelopmentMemoryLedger(records=(second, first))
        self.assertEqual(left.canonical_dict(), right.canonical_dict())
        self.assertEqual(left.fingerprint(), right.fingerprint())

        with self.assertRaisesRegex(DevelopmentMemoryError, "duplicate"):
            DevelopmentMemoryLedger(records=(first, first))

    def test_append_returns_new_immutable_ledger(self) -> None:
        empty = DevelopmentMemoryLedger()
        item = record("memory-001")
        updated = empty.append(item)
        self.assertEqual(empty.records, ())
        self.assertEqual(updated.records, (item,))

    def test_evidence_and_secret_boundaries_fail_closed(self) -> None:
        with self.assertRaisesRegex(DevelopmentMemoryError, "evidence"):
            DevelopmentMemoryRecord(
                memory_id="memory-001",
                kind=MemoryKind.FAILURE,
                repository="owner/repo",
                source_sha=SHA_A,
                statement="A deterministic failure was observed.",
                evidence_paths=(),
                evidence_fingerprints=(HASH_A,),
            )

        with self.assertRaisesRegex(DevelopmentMemoryError, "inside .autodev"):
            record(
                "memory-001",
                evidence_paths=("README.md",),
            )

        with self.assertRaisesRegex(DevelopmentMemoryError, "secret-like"):
            record(
                "memory-001",
                statement="Observed github_pat_example during a provider failure.",
            )

        with self.assertRaisesRegex(DevelopmentMemoryError, "URLs"):
            record(
                "memory-001",
                statement="See https://example.com for the result.",
            )

    def test_planner_context_is_bounded_repository_filtered_and_advisory_only(self) -> None:
        records = [
            record("memory-001"),
            record(
                "memory-002",
                kind=MemoryKind.REMEDIATION,
                statement="Concurrent unrelated branch movement is retried without overwriting same-path mutations.",
                evidence_fingerprints=(HASH_B,),
                tags=("github", "remediation"),
            ),
            record(
                "memory-other",
                repository="other/repo",
                statement="This repository-specific fact must not leak into another target context.",
            ),
        ]
        context = build_planner_memory_context(
            DevelopmentMemoryLedger(records=tuple(records)),
            repository="owner/repo",
            max_records=20,
            max_chars=6000,
        )
        self.assertEqual(context.payload["authority"], "advisory-data-only")
        self.assertFalse(context.payload["execution_authority"])
        self.assertFalse(context.payload["memory_may_expand_scope"])
        self.assertFalse(context.payload["memory_may_override_acceptance"])
        self.assertEqual(
            [item["memory_id"] for item in context.payload["records"]],
            ["memory-002", "memory-001"],
        )
        self.assertNotIn("other/repo", context.serialized)
        self.assertLessEqual(len(context.serialized), 6000)

        context_again = build_planner_memory_context(
            DevelopmentMemoryLedger(records=tuple(reversed(records))),
            repository="owner/repo",
        )
        self.assertEqual(context.fingerprint, context_again.fingerprint)

    def test_context_can_filter_kinds_without_expanding_authority(self) -> None:
        ledger = DevelopmentMemoryLedger(
            records=(
                record("memory-001", kind=MemoryKind.VERIFIED_OUTCOME),
                record(
                    "memory-002",
                    kind=MemoryKind.FAILURE,
                    statement="The first runtime proof failed closed.",
                ),
            )
        )
        context = build_planner_memory_context(
            ledger,
            repository="owner/repo",
            kinds=(MemoryKind.FAILURE,),
        )
        self.assertEqual(len(context.payload["records"]), 1)
        self.assertEqual(context.payload["records"][0]["kind"], "FAILURE")
        self.assertFalse(context.payload["execution_authority"])


if __name__ == "__main__":
    unittest.main()

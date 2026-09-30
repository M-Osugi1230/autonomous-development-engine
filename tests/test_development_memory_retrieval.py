from __future__ import annotations

import unittest

from ade.development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_resolution import resolve_development_memory
from ade.development_memory_retrieval import (
    DevelopmentMemoryQuery,
    build_retrieved_memory_context,
    retrieve_development_memory,
)


CURRENT = "a" * 40
OLD = "b" * 40


def record(
    memory_id: str,
    *,
    kind: MemoryKind,
    source_sha: str,
    tags: tuple[str, ...],
    task_id: str | None = None,
    campaign_id: str | None = None,
    repository: str = "owner/repo",
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=kind,
        repository=repository,
        source_sha=source_sha,
        statement=f"Fixed controller statement for {memory_id}.",
        evidence_paths=(f".autodev/evidence/{memory_id}.json",),
        evidence_fingerprints=((memory_id[-1] if memory_id[-1].isdigit() else "1") * 64,),
        tags=tags,
        task_id=task_id,
        campaign_id=campaign_id,
    )


class DevelopmentMemoryRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current = record(
            "memory-001",
            kind=MemoryKind.VERIFIED_OUTCOME,
            source_sha=CURRENT,
            tags=("runtime", "verified"),
            task_id="task-001",
            campaign_id="campaign-001",
        )
        self.failure = record(
            "memory-002",
            kind=MemoryKind.FAILURE,
            source_sha=OLD,
            tags=("runtime", "failure"),
            task_id="task-001",
        )
        self.unrelated = record(
            "memory-003",
            kind=MemoryKind.REMEDIATION,
            source_sha=OLD,
            tags=("github", "recovery"),
        )
        self.other_repo = record(
            "memory-004",
            kind=MemoryKind.FAILURE,
            source_sha=CURRENT,
            tags=("runtime", "failure"),
            repository="other/repo",
        )
        self.resolution = resolve_development_memory(
            DevelopmentMemoryLedger(
                records=(
                    self.current,
                    self.failure,
                    self.unrelated,
                    self.other_repo,
                )
            ),
            current_source_shas={
                "owner/repo": CURRENT,
                "other/repo": CURRENT,
            },
        )

    def test_current_memory_and_relevant_historical_lessons_rank_deterministically(self) -> None:
        query = DevelopmentMemoryQuery(
            repository="owner/repo",
            current_source_sha=CURRENT,
            tags=("runtime",),
            task_id="task-001",
            max_results=10,
        )
        retrieval = retrieve_development_memory(self.resolution, query)
        self.assertEqual(
            [hit.record.memory_id for hit in retrieval.hits],
            ["memory-001", "memory-002"],
        )
        self.assertGreater(retrieval.hits[0].score, retrieval.hits[1].score)
        self.assertIn("current-source-verified", retrieval.hits[0].reasons)
        self.assertIn("task-match", retrieval.hits[0].reasons)

        again = retrieve_development_memory(
            self.resolution,
            DevelopmentMemoryQuery(
                repository="owner/repo",
                current_source_sha=CURRENT,
                tags=("runtime",),
                task_id="task-001",
                max_results=10,
            ),
        )
        self.assertEqual(retrieval.canonical_dict(), again.canonical_dict())
        self.assertEqual(retrieval.fingerprint(), again.fingerprint())

    def test_unrelated_historical_memory_is_not_returned_without_relevance_signal(self) -> None:
        retrieval = retrieve_development_memory(
            self.resolution,
            DevelopmentMemoryQuery(
                repository="owner/repo",
                current_source_sha=CURRENT,
                tags=("runtime",),
            ),
        )
        ids = [hit.record.memory_id for hit in retrieval.hits]
        self.assertIn("memory-001", ids)
        self.assertIn("memory-002", ids)
        self.assertNotIn("memory-003", ids)

    def test_repository_filter_and_source_binding_fail_closed(self) -> None:
        retrieval = retrieve_development_memory(
            self.resolution,
            DevelopmentMemoryQuery(
                repository="owner/repo",
                current_source_sha=CURRENT,
                tags=("failure",),
            ),
        )
        self.assertNotIn(
            "memory-004",
            [hit.record.memory_id for hit in retrieval.hits],
        )

        with self.assertRaisesRegex(DevelopmentMemoryError, "does not match"):
            retrieve_development_memory(
                self.resolution,
                DevelopmentMemoryQuery(
                    repository="owner/repo",
                    current_source_sha=OLD,
                    tags=("runtime",),
                ),
            )

    def test_result_budget_and_tie_break_are_stable(self) -> None:
        extra = record(
            "memory-005",
            kind=MemoryKind.FAILURE,
            source_sha=OLD,
            tags=("runtime", "failure"),
        )
        resolution = resolve_development_memory(
            DevelopmentMemoryLedger(
                records=(
                    self.current,
                    self.failure,
                    extra,
                    self.unrelated,
                )
            ),
            current_source_shas={"owner/repo": CURRENT},
        )
        retrieval = retrieve_development_memory(
            resolution,
            DevelopmentMemoryQuery(
                repository="owner/repo",
                current_source_sha=CURRENT,
                tags=("runtime",),
                max_results=2,
            ),
        )
        self.assertEqual(len(retrieval.hits), 2)
        self.assertEqual(retrieval.hits[0].record.memory_id, "memory-001")
        self.assertEqual(retrieval.hits[1].record.memory_id, "memory-002")

    def test_retrieved_context_keeps_advisory_authority_boundary(self) -> None:
        retrieval = retrieve_development_memory(
            self.resolution,
            DevelopmentMemoryQuery(
                repository="owner/repo",
                current_source_sha=CURRENT,
                tags=("runtime",),
            ),
        )
        context = build_retrieved_memory_context(retrieval)
        self.assertEqual(context.payload["authority"], "advisory-data-only")
        self.assertFalse(context.payload["execution_authority"])
        self.assertFalse(context.payload["memory_may_expand_scope"])
        self.assertFalse(context.payload["memory_may_override_acceptance"])
        self.assertNotIn("other/repo", context.serialized)

    def test_query_has_no_free_text_surface(self) -> None:
        query = DevelopmentMemoryQuery(
            repository="owner/repo",
            current_source_sha=CURRENT,
            tags=("runtime",),
        )
        self.assertEqual(
            set(query.canonical_dict()),
            {
                "schema_version",
                "repository",
                "current_source_sha",
                "tags",
                "task_id",
                "campaign_id",
                "max_results",
            },
        )


if __name__ == "__main__":
    unittest.main()

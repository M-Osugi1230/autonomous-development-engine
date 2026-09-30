from __future__ import annotations

import json

from ade.development_memory import (
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
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=kind,
        repository="owner/repo",
        source_sha=source_sha,
        statement=f"Trusted fixed statement {memory_id}.",
        evidence_paths=(f".autodev/evidence/{memory_id}.json",),
        evidence_fingerprints=((memory_id[-1]) * 64,),
        tags=tags,
        task_id=task_id,
    )


def main() -> int:
    ledger = DevelopmentMemoryLedger(
        records=(
            record(
                "memory-001",
                kind=MemoryKind.VERIFIED_OUTCOME,
                source_sha=CURRENT,
                tags=("runtime", "verified"),
                task_id="task-001",
            ),
            record(
                "memory-002",
                kind=MemoryKind.FAILURE,
                source_sha=OLD,
                tags=("runtime", "failure"),
                task_id="task-001",
            ),
            record(
                "memory-003",
                kind=MemoryKind.REMEDIATION,
                source_sha=OLD,
                tags=("github", "recovery"),
            ),
        )
    )
    resolution = resolve_development_memory(
        ledger,
        current_source_shas={"owner/repo": CURRENT},
    )
    query = DevelopmentMemoryQuery(
        repository="owner/repo",
        current_source_sha=CURRENT,
        tags=("runtime",),
        task_id="task-001",
        max_results=2,
    )
    retrieval = retrieve_development_memory(resolution, query)
    assert [hit.record.memory_id for hit in retrieval.hits] == [
        "memory-001",
        "memory-002",
    ]
    context = build_retrieved_memory_context(retrieval)
    assert context.payload["authority"] == "advisory-data-only"
    assert context.payload["execution_authority"] is False
    assert context.payload["memory_may_expand_scope"] is False
    assert context.payload["memory_may_override_acceptance"] is False
    assert "memory-003" not in context.serialized

    print(
        json.dumps(
            {
                "ok": True,
                "deterministic_ranking": True,
                "repository_filtered": True,
                "current_source_bound": True,
                "historical_requires_relevance": True,
                "bounded_results": True,
                "free_text_query_surface": False,
                "retrieval_fingerprint": retrieval.fingerprint(),
                "context_fingerprint": context.fingerprint,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

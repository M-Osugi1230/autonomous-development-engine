from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .development_memory import (
    DevelopmentMemoryLedger,
    DevelopmentMemoryPlannerContext,
)
from .development_memory_extraction import (
    evidence_fingerprint,
    extract_completed_campaign_memory,
    extract_verified_runtime_memory,
)
from .development_memory_resolution import resolve_development_memory
from .development_memory_store import DevelopmentMemoryStore
from .development_memory_retrieval import (
    DevelopmentMemoryQuery,
    DevelopmentMemoryRetrieval,
    build_retrieved_memory_context,
    retrieve_development_memory,
)


_DEFAULT_QUERY_TAGS = ("campaign", "completed", "runtime", "verified")


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryPlanningBundle:
    context: DevelopmentMemoryPlannerContext
    retrieval: DevelopmentMemoryRetrieval
    resolution_fingerprint: str
    source_evidence_path: str
    source_evidence_fingerprint: str
    extracted_record_count: int
    schema_version: int = 1

    @property
    def retrieved_record_count(self) -> int:
        return len(self.retrieval.hits)

    @property
    def memory_ids(self) -> tuple[str, ...]:
        return tuple(hit.record.memory_id for hit in self.retrieval.hits)

    def evidence_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "used": self.retrieved_record_count > 0,
            "authority": "advisory-data-only",
            "execution_authority": False,
            "memory_may_expand_scope": False,
            "memory_may_override_acceptance": False,
            "source_evidence_path": self.source_evidence_path,
            "source_evidence_fingerprint": self.source_evidence_fingerprint,
            "resolution_fingerprint": self.resolution_fingerprint,
            "retrieval_fingerprint": self.retrieval.fingerprint(),
            "context_fingerprint": self.context.fingerprint,
            "extracted_record_count": self.extracted_record_count,
            "retrieved_record_count": self.retrieved_record_count,
            "memory_ids": list(self.memory_ids),
            "current_source_sha": self.retrieval.query.current_source_sha,
            "repository": self.retrieval.query.repository,
        }


def build_planning_memory_bundle_from_store(
    *,
    store: DevelopmentMemoryStore,
    store_path: str,
    repository: str,
    current_source_sha: str,
    max_results: int = 8,
    max_chars: int = 4000,
) -> DevelopmentMemoryPlanningBundle | None:
    matching_records = tuple(
        record
        for record in store.ledger.records
        if record.repository == repository
    )
    if not matching_records:
        return None

    ledger = DevelopmentMemoryLedger(records=matching_records)
    resolution = resolve_development_memory(
        ledger,
        current_source_shas={repository: current_source_sha},
    )
    retrieval = retrieve_development_memory(
        resolution,
        DevelopmentMemoryQuery(
            repository=repository,
            current_source_sha=current_source_sha,
            tags=_DEFAULT_QUERY_TAGS,
            max_results=max_results,
        ),
    )
    context = build_retrieved_memory_context(
        retrieval,
        max_chars=max_chars,
    )
    return DevelopmentMemoryPlanningBundle(
        context=context,
        retrieval=retrieval,
        resolution_fingerprint=resolution.fingerprint(),
        source_evidence_path=store_path,
        source_evidence_fingerprint=store.fingerprint(),
        extracted_record_count=len(matching_records),
    )


def build_planning_memory_bundle(
    *,
    evidence_path: str,
    evidence_payload: object,
    repository: str,
    current_source_sha: str,
    max_results: int = 8,
    max_chars: int = 4000,
) -> DevelopmentMemoryPlanningBundle:
    records = (
        extract_completed_campaign_memory(
            evidence_path=evidence_path,
            evidence_payload=evidence_payload,
        ),
        extract_verified_runtime_memory(
            evidence_path=evidence_path,
            evidence_payload=evidence_payload,
        ),
    )
    ledger = DevelopmentMemoryLedger(records=records)
    resolution = resolve_development_memory(
        ledger,
        current_source_shas={repository: current_source_sha},
    )
    retrieval = retrieve_development_memory(
        resolution,
        DevelopmentMemoryQuery(
            repository=repository,
            current_source_sha=current_source_sha,
            tags=_DEFAULT_QUERY_TAGS,
            max_results=max_results,
        ),
    )
    context = build_retrieved_memory_context(
        retrieval,
        max_chars=max_chars,
    )
    return DevelopmentMemoryPlanningBundle(
        context=context,
        retrieval=retrieval,
        resolution_fingerprint=resolution.fingerprint(),
        source_evidence_path=evidence_path,
        source_evidence_fingerprint=evidence_fingerprint(evidence_payload),
        extracted_record_count=len(records),
    )

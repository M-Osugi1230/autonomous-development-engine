from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryPlannerContext,
    DevelopmentMemoryRecord,
    build_planner_memory_context,
)
from .development_memory_resolution import (
    DevelopmentMemoryResolution,
    MemoryResolutionStatus,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryQuery:
    repository: str
    current_source_sha: str
    tags: tuple[str, ...] = ()
    task_id: str | None = None
    campaign_id: str | None = None
    max_results: int = 10
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise DevelopmentMemoryError("unsupported memory query schema version")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise DevelopmentMemoryError("query repository must be owner/name")
        if not isinstance(self.current_source_sha, str) or _SHA40.fullmatch(self.current_source_sha) is None:
            raise DevelopmentMemoryError("query current_source_sha must be a lowercase SHA40")
        if type(self.max_results) is not int or not 1 <= self.max_results <= 50:
            raise DevelopmentMemoryError("query max_results must be between 1 and 50")

        normalized_tags = tuple(sorted(set(self.tags)))
        if len(normalized_tags) > 20:
            raise DevelopmentMemoryError("query contains too many tags")
        if any(not isinstance(tag, str) or _TAG.fullmatch(tag) is None for tag in normalized_tags):
            raise DevelopmentMemoryError("query tag is invalid")
        object.__setattr__(self, "tags", normalized_tags)

        for field_name in ("task_id", "campaign_id"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str) or _ID.fullmatch(value) is None
            ):
                raise DevelopmentMemoryError(f"query {field_name} is invalid")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repository": self.repository,
            "current_source_sha": self.current_source_sha,
            "tags": list(self.tags),
            "task_id": self.task_id,
            "campaign_id": self.campaign_id,
            "max_results": self.max_results,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryHit:
    record: DevelopmentMemoryRecord
    resolution_status: MemoryResolutionStatus
    score: int
    reasons: tuple[str, ...]

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.record.memory_id,
            "resolution_status": self.resolution_status.value,
            "score": self.score,
            "reasons": list(self.reasons),
            "record": self.record.canonical_dict(),
        }


@dataclass(frozen=True, slots=True)
class DevelopmentMemoryRetrieval:
    query: DevelopmentMemoryQuery
    resolution_fingerprint: str
    hits: tuple[DevelopmentMemoryHit, ...]
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "query": self.query.canonical_dict(),
            "resolution_fingerprint": self.resolution_fingerprint,
            "hit_count": len(self.hits),
            "hits": [hit.canonical_dict() for hit in self.hits],
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def eligible_ledger(self) -> DevelopmentMemoryLedger:
        return DevelopmentMemoryLedger(records=tuple(hit.record for hit in self.hits))


def _score(
    record: DevelopmentMemoryRecord,
    status: MemoryResolutionStatus,
    query: DevelopmentMemoryQuery,
) -> tuple[int, tuple[str, ...], bool]:
    score = 0
    reasons: list[str] = []
    relevance = False

    if status is MemoryResolutionStatus.CURRENT:
        score += 100
        reasons.append("current-source-verified")
        relevance = True
    elif status is MemoryResolutionStatus.HISTORICAL:
        score += 20
        reasons.append("historical-lesson")
    else:
        raise DevelopmentMemoryError("non-eligible memory reached retrieval scoring")

    overlap = tuple(sorted(set(record.tags).intersection(query.tags)))
    if overlap:
        score += 15 * len(overlap)
        reasons.extend(f"tag:{tag}" for tag in overlap)
        relevance = True

    if query.task_id is not None and record.task_id == query.task_id:
        score += 30
        reasons.append("task-match")
        relevance = True

    if query.campaign_id is not None and record.campaign_id == query.campaign_id:
        score += 25
        reasons.append("campaign-match")
        relevance = True

    if record.source_sha == query.current_source_sha:
        score += 10
        reasons.append("source-sha-match")

    return score, tuple(reasons), relevance


def retrieve_development_memory(
    resolution: DevelopmentMemoryResolution,
    query: DevelopmentMemoryQuery,
) -> DevelopmentMemoryRetrieval:
    if not isinstance(resolution, DevelopmentMemoryResolution):
        raise DevelopmentMemoryError("resolution must be DevelopmentMemoryResolution")
    if not isinstance(query, DevelopmentMemoryQuery):
        raise DevelopmentMemoryError("query must be DevelopmentMemoryQuery")

    resolved_sources = dict(resolution.current_source_shas)
    if query.repository not in resolved_sources:
        raise DevelopmentMemoryError("query repository is absent from memory resolution")
    if resolved_sources[query.repository] != query.current_source_sha:
        raise DevelopmentMemoryError(
            "query current source SHA does not match memory resolution"
        )

    candidates: list[DevelopmentMemoryHit] = []
    for item in resolution.records:
        if item.record.repository != query.repository:
            continue
        if item.status not in {
            MemoryResolutionStatus.CURRENT,
            MemoryResolutionStatus.HISTORICAL,
        }:
            continue
        score, reasons, relevant = _score(item.record, item.status, query)
        if not relevant:
            continue
        candidates.append(
            DevelopmentMemoryHit(
                record=item.record,
                resolution_status=item.status,
                score=score,
                reasons=reasons,
            )
        )

    ordered = tuple(
        sorted(
            candidates,
            key=lambda hit: (-hit.score, hit.record.memory_id),
        )[: query.max_results]
    )
    return DevelopmentMemoryRetrieval(
        query=query,
        resolution_fingerprint=resolution.fingerprint(),
        hits=ordered,
    )


def build_retrieved_memory_context(
    retrieval: DevelopmentMemoryRetrieval,
    *,
    max_chars: int = 6000,
) -> DevelopmentMemoryPlannerContext:
    if not isinstance(retrieval, DevelopmentMemoryRetrieval):
        raise DevelopmentMemoryError("retrieval must be DevelopmentMemoryRetrieval")
    return build_planner_memory_context(
        retrieval.eligible_ledger(),
        repository=retrieval.query.repository,
        max_records=retrieval.query.max_results,
        max_chars=max_chars,
    )

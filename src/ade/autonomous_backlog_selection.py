from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .autonomous_backlog import AutonomousBacklog, AutonomousBacklogError
from .autonomous_backlog_resolution import (
    AutonomousBacklogResolution,
    BacklogResolutionState,
)


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise AutonomousBacklogError("selection repository must be owner/name")
    return value


def _sha(value: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise AutonomousBacklogError("selection source_sha must be lowercase SHA40")
    return value


@dataclass(frozen=True, slots=True)
class BacklogSelection:
    repository: str
    source_sha: str
    backlog_fingerprint: str
    resolution_fingerprint: str
    selected_candidate_id: str | None
    eligible_candidate_ids: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported selection schema version")
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(self, "source_sha", _sha(self.source_sha))
        if len(self.backlog_fingerprint) != 64 or len(self.resolution_fingerprint) != 64:
            raise AutonomousBacklogError("selection fingerprints must be sha256")
        eligible = tuple(sorted(set(self.eligible_candidate_ids)))
        if len(eligible) != len(self.eligible_candidate_ids):
            raise AutonomousBacklogError("eligible candidate IDs must be unique")
        if self.selected_candidate_id is not None and self.selected_candidate_id not in eligible:
            raise AutonomousBacklogError("selected candidate must be eligible")
        if self.selected_candidate_id is None and eligible:
            raise AutonomousBacklogError("eligible candidates require one deterministic selection")
        object.__setattr__(self, "eligible_candidate_ids", eligible)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "backlog_fingerprint": self.backlog_fingerprint,
            "resolution_fingerprint": self.resolution_fingerprint,
            "selected_candidate_id": self.selected_candidate_id,
            "eligible_candidate_ids": list(self.eligible_candidate_ids),
            "selection_policy": "current-source-nonhuman-priority-v1",
            "execution_authority": False,
            "planning_goal_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def select_next_backlog_candidate(
    backlog: AutonomousBacklog,
    resolution: AutonomousBacklogResolution,
    *,
    repository: str,
    source_sha: str,
) -> BacklogSelection:
    if not isinstance(backlog, AutonomousBacklog):
        raise AutonomousBacklogError("backlog must be AutonomousBacklog")
    if not isinstance(resolution, AutonomousBacklogResolution):
        raise AutonomousBacklogError("resolution must be AutonomousBacklogResolution")
    repository = _repository(repository)
    source_sha = _sha(source_sha)
    if resolution.backlog_fingerprint != backlog.fingerprint():
        raise AutonomousBacklogError("resolution does not bind the supplied backlog")

    source_map = dict(resolution.current_sources)
    if source_map.get(repository) != source_sha:
        raise AutonomousBacklogError("selection source SHA does not match resolution")
    by_id = {candidate.candidate_id: candidate for candidate in backlog.candidates}
    entry_by_id = {entry.candidate_id: entry for entry in resolution.entries}
    if set(by_id) != set(entry_by_id):
        raise AutonomousBacklogError("resolution candidate set does not match backlog")

    ranked: list[tuple[int, str]] = []
    for candidate_id, candidate in by_id.items():
        entry = entry_by_id[candidate_id]
        if candidate.repository != repository or candidate.source_sha != source_sha:
            continue
        if candidate.human_only:
            continue
        if entry.state is not BacklogResolutionState.CURRENT:
            continue
        ranked.append((entry.priority_rank, candidate_id))

    ranked.sort()
    eligible = tuple(candidate_id for _, candidate_id in ranked)
    selected = eligible[0] if eligible else None
    return BacklogSelection(
        repository=repository,
        source_sha=source_sha,
        backlog_fingerprint=backlog.fingerprint(),
        resolution_fingerprint=resolution.fingerprint(),
        selected_candidate_id=selected,
        eligible_candidate_ids=eligible,
    )

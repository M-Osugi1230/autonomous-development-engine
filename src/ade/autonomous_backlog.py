from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Iterable


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_MARKERS = (
    "-----begin private key-----",
    "-----begin rsa private key-----",
    "github_pat_",
    "ghp_",
    "gho_",
    "ghs_",
    "akia",
    "bearer ",
)
MAX_BACKLOG_CANDIDATES = 500


class AutonomousBacklogError(ValueError):
    """Trusted Autonomous Backlog validation failed."""


class BacklogCandidateKind(StrEnum):
    ACCEPTANCE_GAP = "ACCEPTANCE_GAP"
    VERIFIED_REMEDIATION = "VERIFIED_REMEDIATION"
    RUNTIME_GAP = "RUNTIME_GAP"
    MEMORY_FOLLOWUP = "MEMORY_FOLLOWUP"
    REPOSITORY_HYGIENE = "REPOSITORY_HYGIENE"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise AutonomousBacklogError("repository must be owner/name")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise AutonomousBacklogError("repository must be owner/name")
    return value


def _source_sha(value: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise AutonomousBacklogError("source_sha must be a lowercase 40-char SHA")
    return value


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise AutonomousBacklogError(f"{field} is invalid")
    return value


def _bounded_text(value: str, *, field: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise AutonomousBacklogError(f"{field} must be text")
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > max_chars or _CONTROL.search(normalized):
        raise AutonomousBacklogError(f"{field} must be bounded printable text")
    folded = normalized.casefold()
    if any(marker in folded for marker in _SECRET_MARKERS):
        raise AutonomousBacklogError(f"{field} contains a secret-like marker")
    if "http://" in folded or "https://" in folded:
        raise AutonomousBacklogError(f"{field} must not contain URLs")
    return normalized


def _evidence_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise AutonomousBacklogError("evidence path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise AutonomousBacklogError("evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise AutonomousBacklogError("evidence path must be normalized")
    if not value.startswith(".autodev/"):
        raise AutonomousBacklogError("evidence path must remain inside .autodev/")
    return value


def _evidence_fingerprint(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AutonomousBacklogError("evidence fingerprint must be sha256")
    return value


def _tag(value: str) -> str:
    if not isinstance(value, str) or _TAG.fullmatch(value) is None:
        raise AutonomousBacklogError("backlog tag is invalid")
    return value


@dataclass(frozen=True, slots=True)
class BacklogCandidate:
    candidate_id: str
    kind: BacklogCandidateKind
    repository: str
    source_sha: str
    statement: str
    evidence_paths: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    tags: tuple[str, ...] = ()
    source_phase: str | None = None
    human_only: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported candidate schema version")
        object.__setattr__(
            self,
            "candidate_id",
            _identifier(self.candidate_id, field="candidate_id"),
        )
        if not isinstance(self.kind, BacklogCandidateKind):
            raise AutonomousBacklogError("kind must be BacklogCandidateKind")
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(self, "source_sha", _source_sha(self.source_sha))
        object.__setattr__(
            self,
            "statement",
            _bounded_text(self.statement, field="statement", max_chars=500),
        )
        if type(self.human_only) is not bool:
            raise AutonomousBacklogError("human_only must be a bool")
        if self.source_phase is not None:
            object.__setattr__(
                self,
                "source_phase",
                _identifier(self.source_phase, field="source_phase"),
            )

        paths = tuple(sorted({_evidence_path(path) for path in self.evidence_paths}))
        fingerprints = tuple(
            sorted({_evidence_fingerprint(value) for value in self.evidence_fingerprints})
        )
        tags = tuple(sorted({_tag(value) for value in self.tags}))
        if not paths:
            raise AutonomousBacklogError("at least one trusted evidence path is required")
        if not fingerprints:
            raise AutonomousBacklogError("at least one evidence fingerprint is required")
        if len(paths) > 8 or len(fingerprints) > 8:
            raise AutonomousBacklogError("backlog evidence exceeds trusted budget")
        if len(tags) > 12:
            raise AutonomousBacklogError("too many backlog tags")
        object.__setattr__(self, "evidence_paths", paths)
        object.__setattr__(self, "evidence_fingerprints", fingerprints)
        object.__setattr__(self, "tags", tags)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "kind": self.kind.value,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "statement": self.statement,
            "evidence_paths": list(self.evidence_paths),
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "tags": list(self.tags),
            "source_phase": self.source_phase,
            "human_only": self.human_only,
            "execution_authority": False,
            "auto_dispatch": False,
            "may_expand_scope": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BacklogCandidate":
        if not isinstance(payload, dict):
            raise AutonomousBacklogError("candidate must be a JSON object")
        allowed = {
            "schema_version",
            "candidate_id",
            "kind",
            "repository",
            "source_sha",
            "statement",
            "evidence_paths",
            "evidence_fingerprints",
            "tags",
            "source_phase",
            "human_only",
            "execution_authority",
            "auto_dispatch",
            "may_expand_scope",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise AutonomousBacklogError(
                f"unknown candidate fields: {sorted(unknown)}"
            )
        for key in ("execution_authority", "auto_dispatch", "may_expand_scope"):
            if payload.get(key, False) is not False:
                raise AutonomousBacklogError(
                    f"candidate cannot grant {key.replace('_', ' ')}"
                )
        try:
            kind = BacklogCandidateKind(payload.get("kind"))
        except ValueError as exc:
            raise AutonomousBacklogError("candidate kind is invalid") from exc

        raw_paths = payload.get("evidence_paths")
        raw_fingerprints = payload.get("evidence_fingerprints")
        raw_tags = payload.get("tags", [])
        if not isinstance(raw_paths, list):
            raise AutonomousBacklogError("evidence_paths must be a list")
        if not isinstance(raw_fingerprints, list):
            raise AutonomousBacklogError("evidence_fingerprints must be a list")
        if not isinstance(raw_tags, list):
            raise AutonomousBacklogError("tags must be a list")
        return cls(
            schema_version=payload.get("schema_version", 0),
            candidate_id=payload.get("candidate_id", ""),
            kind=kind,
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            statement=payload.get("statement", ""),
            evidence_paths=tuple(raw_paths),
            evidence_fingerprints=tuple(raw_fingerprints),
            tags=tuple(raw_tags),
            source_phase=payload.get("source_phase"),
            human_only=payload.get("human_only", False),
        )


@dataclass(frozen=True, slots=True)
class AutonomousBacklog:
    candidates: tuple[BacklogCandidate, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported backlog schema version")
        if len(self.candidates) > MAX_BACKLOG_CANDIDATES:
            raise AutonomousBacklogError("backlog candidate budget exceeded")

        by_id: dict[str, BacklogCandidate] = {}
        for candidate in self.candidates:
            if not isinstance(candidate, BacklogCandidate):
                raise AutonomousBacklogError("backlog contains an invalid candidate")
            existing = by_id.get(candidate.candidate_id)
            if existing is not None:
                if existing.canonical_dict() != candidate.canonical_dict():
                    raise AutonomousBacklogError(
                        "same candidate_id cannot refer to different content"
                    )
                raise AutonomousBacklogError(
                    f"duplicate backlog candidate id: {candidate.candidate_id}"
                )
            by_id[candidate.candidate_id] = candidate

        object.__setattr__(
            self,
            "candidates",
            tuple(
                sorted(
                    by_id.values(),
                    key=lambda item: (
                        item.repository,
                        item.source_sha,
                        item.kind.value,
                        item.candidate_id,
                    ),
                )
            ),
        )

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "candidate_count": self.candidate_count,
            "execution_authority": False,
            "auto_dispatch": False,
            "candidates": [candidate.canonical_dict() for candidate in self.candidates],
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    def append(self, candidate: BacklogCandidate) -> "AutonomousBacklog":
        if not isinstance(candidate, BacklogCandidate):
            raise AutonomousBacklogError("candidate must be BacklogCandidate")
        return AutonomousBacklog(candidates=(*self.candidates, candidate))

    def for_repository(
        self,
        repository: str,
        *,
        source_sha: str | None = None,
        include_human_only: bool = True,
    ) -> tuple[BacklogCandidate, ...]:
        repository = _repository(repository)
        if source_sha is not None:
            source_sha = _source_sha(source_sha)
        if type(include_human_only) is not bool:
            raise AutonomousBacklogError("include_human_only must be a bool")
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.repository == repository
            and (source_sha is None or candidate.source_sha == source_sha)
            and (include_human_only or not candidate.human_only)
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutonomousBacklog":
        if not isinstance(payload, dict):
            raise AutonomousBacklogError("backlog must be a JSON object")
        allowed = {
            "schema_version",
            "candidate_count",
            "execution_authority",
            "auto_dispatch",
            "candidates",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise AutonomousBacklogError(f"unknown backlog fields: {sorted(unknown)}")
        if payload.get("execution_authority", False) is not False:
            raise AutonomousBacklogError("backlog cannot grant execution authority")
        if payload.get("auto_dispatch", False) is not False:
            raise AutonomousBacklogError("backlog cannot auto-dispatch")
        raw = payload.get("candidates")
        if not isinstance(raw, list):
            raise AutonomousBacklogError("candidates must be a list")
        candidates = tuple(BacklogCandidate.from_dict(item) for item in raw)
        backlog = cls(
            schema_version=payload.get("schema_version", 0),
            candidates=candidates,
        )
        if payload.get("candidate_count") != backlog.candidate_count:
            raise AutonomousBacklogError("candidate_count does not match candidates")
        return backlog


def build_candidate_id(
    *,
    kind: BacklogCandidateKind,
    repository: str,
    source_sha: str,
    statement: str,
    evidence_fingerprints: Iterable[str],
) -> str:
    repository = _repository(repository)
    source_sha = _source_sha(source_sha)
    statement = _bounded_text(statement, field="statement", max_chars=500)
    fingerprints = tuple(
        sorted({_evidence_fingerprint(value) for value in evidence_fingerprints})
    )
    if not fingerprints:
        raise AutonomousBacklogError("at least one evidence fingerprint is required")
    digest = _fingerprint(
        {
            "kind": kind.value,
            "repository": repository,
            "source_sha": source_sha,
            "statement": statement,
            "evidence_fingerprints": list(fingerprints),
        }
    )
    return "backlog-" + digest[:24]

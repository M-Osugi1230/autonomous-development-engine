from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
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
MAX_IMPROVEMENT_EVIDENCE_REFS = 8
MAX_IMPROVEMENT_TAGS = 8
MAX_IMPROVEMENT_GENERATION = 16
MAX_IMPROVEMENT_STATEMENT_CHARS = 360


class ImprovementSignalError(ValueError):
    """Trusted Continuous Improvement signal validation failed."""


class ImprovementSignalKind(StrEnum):
    RELEASE_FOLLOWUP = "RELEASE_FOLLOWUP"
    RUNTIME_GAP = "RUNTIME_GAP"
    QUALITY_GAP = "QUALITY_GAP"
    RELIABILITY_GAP = "RELIABILITY_GAP"
    PERFORMANCE_GAP = "PERFORMANCE_GAP"
    OPERABILITY_GAP = "OPERABILITY_GAP"


class ImprovementEvidenceKind(StrEnum):
    RELEASE_EVIDENCE = "RELEASE_EVIDENCE"
    POST_VERIFICATION = "POST_VERIFICATION"
    RUNTIME_TARGET = "RUNTIME_TARGET"
    RECOVERY = "RECOVERY"
    HUMAN_DECISION = "HUMAN_DECISION"
    TELEMETRY = "TELEMETRY"


_REQUIRED_EVIDENCE_KINDS = frozenset(
    {
        ImprovementEvidenceKind.RELEASE_EVIDENCE,
        ImprovementEvidenceKind.POST_VERIFICATION,
    }
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _repository(value: str) -> str:
    if (
        not isinstance(value, str)
        or _REPOSITORY.fullmatch(value) is None
    ):
        raise ImprovementSignalError(
            "repository must be owner/name"
        )
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ImprovementSignalError(
            "repository must be owner/name"
        )
    return value


def _sha40(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA40.fullmatch(value) is None
    ):
        raise ImprovementSignalError(
            f"{field} must be a lowercase 40-char SHA"
        )
    return value


def _sha256(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA256.fullmatch(value) is None
    ):
        raise ImprovementSignalError(f"{field} must be sha256")
    return value


def _identifier(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _ID.fullmatch(value) is None
    ):
        raise ImprovementSignalError(f"{field} is invalid")
    return value


def _tag(value: str) -> str:
    if not isinstance(value, str) or _TAG.fullmatch(value) is None:
        raise ImprovementSignalError("improvement tag is invalid")
    return value


def _bounded_statement(value: str) -> str:
    if not isinstance(value, str):
        raise ImprovementSignalError("statement must be text")
    if _CONTROL.search(value):
        raise ImprovementSignalError(
            "statement must be bounded printable text"
        )
    normalized = " ".join(value.strip().split())
    if (
        not normalized
        or len(normalized) > MAX_IMPROVEMENT_STATEMENT_CHARS
    ):
        raise ImprovementSignalError(
            "statement must be bounded printable text"
        )
    folded = normalized.casefold()
    if any(marker in folded for marker in _SECRET_MARKERS):
        raise ImprovementSignalError(
            "statement contains a secret-like marker"
        )
    if "http://" in folded or "https://" in folded:
        raise ImprovementSignalError(
            "statement must not contain URLs"
        )
    return normalized


def _evidence_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 240
    ):
        raise ImprovementSignalError("evidence path is invalid")
    if (
        value.startswith("/")
        or "\\" in value
        or _CONTROL.search(value)
    ):
        raise ImprovementSignalError("evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise ImprovementSignalError(
            "evidence path must be normalized"
        )
    if not value.startswith(".autodev/"):
        raise ImprovementSignalError(
            "evidence path must remain inside .autodev/"
        )
    return value


def _authority_false(
    payload: dict[str, Any],
    field: str,
) -> None:
    if payload.get(field, False) is not False:
        raise ImprovementSignalError(
            "improvement signal cannot grant "
            + field.replace("_", " ")
        )


@dataclass(frozen=True, slots=True)
class ImprovementEvidenceRef:
    kind: ImprovementEvidenceKind
    path: str
    fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementSignalError(
                "unsupported improvement evidence schema version"
            )
        if not isinstance(self.kind, ImprovementEvidenceKind):
            raise ImprovementSignalError(
                "kind must be ImprovementEvidenceKind"
            )
        object.__setattr__(
            self,
            "path",
            _evidence_path(self.path),
        )
        object.__setattr__(
            self,
            "fingerprint",
            _sha256(
                self.fingerprint,
                field="evidence fingerprint",
            ),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "path": self.path,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "ImprovementEvidenceRef":
        if not isinstance(payload, dict):
            raise ImprovementSignalError(
                "improvement evidence must be a JSON object"
            )
        allowed = {
            "schema_version",
            "kind",
            "path",
            "fingerprint",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ImprovementSignalError(
                "unknown improvement evidence fields: "
                + str(sorted(unknown))
            )
        try:
            kind = ImprovementEvidenceKind(payload.get("kind"))
        except (TypeError, ValueError) as exc:
            raise ImprovementSignalError(
                "improvement evidence kind is invalid"
            ) from exc
        return cls(
            schema_version=payload.get("schema_version", 0),
            kind=kind,
            path=payload.get("path", ""),
            fingerprint=payload.get("fingerprint", ""),
        )


def build_improvement_signal_id(
    *,
    repository: str,
    source_sha: str,
    release_candidate_id: str,
    release_environment: str,
    kind: ImprovementSignalKind,
    statement: str,
    evidence_refs: Iterable[ImprovementEvidenceRef],
    parent_signal_id: str | None,
    generation: int,
    tags: Iterable[str] = (),
) -> str:
    repository = _repository(repository)
    source_sha = _sha40(source_sha, field="source_sha")
    release_candidate_id = _identifier(
        release_candidate_id,
        field="release_candidate_id",
    )
    if (
        not isinstance(release_environment, str)
        or release_environment
        not in {"preview", "staging", "production"}
    ):
        raise ImprovementSignalError(
            "release_environment is invalid"
        )
    if not isinstance(kind, ImprovementSignalKind):
        raise ImprovementSignalError(
            "kind must be ImprovementSignalKind"
        )
    statement = _bounded_statement(statement)
    if type(generation) is not int or not (
        0 <= generation <= MAX_IMPROVEMENT_GENERATION
    ):
        raise ImprovementSignalError(
            "generation is outside trusted budget"
        )
    if parent_signal_id is not None:
        parent_signal_id = _identifier(
            parent_signal_id,
            field="parent_signal_id",
        )
    if generation == 0 and parent_signal_id is not None:
        raise ImprovementSignalError(
            "root improvement signal cannot have parent_signal_id"
        )
    if generation > 0 and parent_signal_id is None:
        raise ImprovementSignalError(
            "successor improvement signal requires parent_signal_id"
        )

    refs = tuple(
        sorted(
            evidence_refs,
            key=lambda item: (
                item.kind.value,
                item.path,
                item.fingerprint,
            ),
        )
    )
    if (
        not refs
        or any(
            not isinstance(item, ImprovementEvidenceRef)
            for item in refs
        )
    ):
        raise ImprovementSignalError(
            "evidence_refs must contain ImprovementEvidenceRef values"
        )

    normalized_tags = tuple(sorted(_tag(item) for item in tags))
    if (
        len(normalized_tags) > MAX_IMPROVEMENT_TAGS
        or len(set(normalized_tags)) != len(normalized_tags)
    ):
        raise ImprovementSignalError(
            "improvement tags exceed trusted budget or contain duplicates"
        )

    digest = _fingerprint(
        {
            "repository": repository,
            "source_sha": source_sha,
            "release_candidate_id": release_candidate_id,
            "release_environment": release_environment,
            "kind": kind.value,
            "statement": statement,
            "evidence_refs": [
                item.canonical_dict() for item in refs
            ],
            "parent_signal_id": parent_signal_id,
            "generation": generation,
            "tags": list(normalized_tags),
        }
    )
    return "improve-" + digest[:24]


@dataclass(frozen=True, slots=True)
class ImprovementSignal:
    signal_id: str
    repository: str
    source_sha: str
    release_candidate_id: str
    release_environment: str
    kind: ImprovementSignalKind
    statement: str
    evidence_refs: tuple[ImprovementEvidenceRef, ...]
    parent_signal_id: str | None = None
    generation: int = 0
    tags: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementSignalError(
                "unsupported improvement signal schema version"
            )
        object.__setattr__(
            self,
            "signal_id",
            _identifier(self.signal_id, field="signal_id"),
        )
        object.__setattr__(
            self,
            "repository",
            _repository(self.repository),
        )
        object.__setattr__(
            self,
            "source_sha",
            _sha40(self.source_sha, field="source_sha"),
        )
        object.__setattr__(
            self,
            "release_candidate_id",
            _identifier(
                self.release_candidate_id,
                field="release_candidate_id",
            ),
        )
        if self.release_environment not in {
            "preview",
            "staging",
            "production",
        }:
            raise ImprovementSignalError(
                "release_environment is invalid"
            )
        if not isinstance(self.kind, ImprovementSignalKind):
            raise ImprovementSignalError(
                "kind must be ImprovementSignalKind"
            )
        object.__setattr__(
            self,
            "statement",
            _bounded_statement(self.statement),
        )

        refs = tuple(self.evidence_refs)
        if not 1 <= len(refs) <= MAX_IMPROVEMENT_EVIDENCE_REFS:
            raise ImprovementSignalError(
                "improvement evidence exceeds trusted budget"
            )
        if any(
            not isinstance(item, ImprovementEvidenceRef)
            for item in refs
        ):
            raise ImprovementSignalError(
                "evidence_refs must contain ImprovementEvidenceRef values"
            )
        by_kind: dict[
            ImprovementEvidenceKind,
            ImprovementEvidenceRef,
        ] = {}
        for item in refs:
            if item.kind in by_kind:
                raise ImprovementSignalError(
                    "duplicate improvement evidence kind: "
                    + item.kind.value
                )
            by_kind[item.kind] = item
        missing = _REQUIRED_EVIDENCE_KINDS - set(by_kind)
        if missing:
            raise ImprovementSignalError(
                "improvement signal is missing required evidence: "
                + ", ".join(
                    sorted(kind.value for kind in missing)
                )
            )
        normalized_refs = tuple(
            sorted(
                refs,
                key=lambda item: (
                    item.kind.value,
                    item.path,
                    item.fingerprint,
                ),
            )
        )
        object.__setattr__(
            self,
            "evidence_refs",
            normalized_refs,
        )

        if type(self.generation) is not int or not (
            0 <= self.generation <= MAX_IMPROVEMENT_GENERATION
        ):
            raise ImprovementSignalError(
                "generation is outside trusted budget"
            )
        parent = self.parent_signal_id
        if parent is not None:
            parent = _identifier(
                parent,
                field="parent_signal_id",
            )
            object.__setattr__(
                self,
                "parent_signal_id",
                parent,
            )
        if self.generation == 0 and parent is not None:
            raise ImprovementSignalError(
                "root improvement signal cannot have parent_signal_id"
            )
        if self.generation > 0 and parent is None:
            raise ImprovementSignalError(
                "successor improvement signal requires parent_signal_id"
            )
        if parent == self.signal_id:
            raise ImprovementSignalError(
                "improvement signal cannot reference itself as parent"
            )

        normalized_tags = tuple(
            sorted(_tag(item) for item in self.tags)
        )
        if (
            len(normalized_tags) > MAX_IMPROVEMENT_TAGS
            or len(set(normalized_tags)) != len(normalized_tags)
        ):
            raise ImprovementSignalError(
                "improvement tags exceed trusted budget or contain duplicates"
            )
        object.__setattr__(self, "tags", normalized_tags)

        expected_id = build_improvement_signal_id(
            repository=self.repository,
            source_sha=self.source_sha,
            release_candidate_id=self.release_candidate_id,
            release_environment=self.release_environment,
            kind=self.kind,
            statement=self.statement,
            evidence_refs=self.evidence_refs,
            parent_signal_id=self.parent_signal_id,
            generation=self.generation,
            tags=self.tags,
        )
        if self.signal_id != expected_id:
            raise ImprovementSignalError(
                "signal_id does not match trusted content"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "signal_id": self.signal_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "release_candidate_id": self.release_candidate_id,
            "release_environment": self.release_environment,
            "kind": self.kind.value,
            "statement": self.statement,
            "evidence_refs": [
                item.canonical_dict()
                for item in self.evidence_refs
            ],
            "parent_signal_id": self.parent_signal_id,
            "generation": self.generation,
            "tags": list(self.tags),
            "planning_authority": False,
            "execution_authority": False,
            "auto_dispatch": False,
            "release_authority": False,
            "scope_expansion_authority": False,
            "acceptance_mutation_authority": False,
            "human_decision_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "ImprovementSignal":
        if not isinstance(payload, dict):
            raise ImprovementSignalError(
                "improvement signal must be a JSON object"
            )
        allowed = {
            "schema_version",
            "signal_id",
            "repository",
            "source_sha",
            "release_candidate_id",
            "release_environment",
            "kind",
            "statement",
            "evidence_refs",
            "parent_signal_id",
            "generation",
            "tags",
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "release_authority",
            "scope_expansion_authority",
            "acceptance_mutation_authority",
            "human_decision_authority",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ImprovementSignalError(
                "unknown improvement signal fields: "
                + str(sorted(unknown))
            )
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "release_authority",
            "scope_expansion_authority",
            "acceptance_mutation_authority",
            "human_decision_authority",
        ):
            _authority_false(payload, field)

        try:
            kind = ImprovementSignalKind(payload.get("kind"))
        except (TypeError, ValueError) as exc:
            raise ImprovementSignalError(
                "improvement signal kind is invalid"
            ) from exc

        raw_refs = payload.get("evidence_refs")
        if not isinstance(raw_refs, list):
            raise ImprovementSignalError(
                "evidence_refs must be a list"
            )
        raw_tags = payload.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ImprovementSignalError("tags must be a list")

        return cls(
            schema_version=payload.get("schema_version", 0),
            signal_id=payload.get("signal_id", ""),
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            release_candidate_id=payload.get(
                "release_candidate_id",
                "",
            ),
            release_environment=payload.get(
                "release_environment",
                "",
            ),
            kind=kind,
            statement=payload.get("statement", ""),
            evidence_refs=tuple(
                ImprovementEvidenceRef.from_dict(item)
                for item in raw_refs
            ),
            parent_signal_id=payload.get("parent_signal_id"),
            generation=payload.get("generation", -1),
            tags=tuple(str(item) for item in raw_tags),
        )


def build_improvement_signal(
    *,
    repository: str,
    source_sha: str,
    release_candidate_id: str,
    release_environment: str,
    kind: ImprovementSignalKind,
    statement: str,
    evidence_refs: Iterable[ImprovementEvidenceRef],
    parent_signal_id: str | None = None,
    generation: int = 0,
    tags: Iterable[str] = (),
) -> ImprovementSignal:
    refs = tuple(evidence_refs)
    tag_values = tuple(tags)
    signal_id = build_improvement_signal_id(
        repository=repository,
        source_sha=source_sha,
        release_candidate_id=release_candidate_id,
        release_environment=release_environment,
        kind=kind,
        statement=statement,
        evidence_refs=refs,
        parent_signal_id=parent_signal_id,
        generation=generation,
        tags=tag_values,
    )
    return ImprovementSignal(
        signal_id=signal_id,
        repository=repository,
        source_sha=source_sha,
        release_candidate_id=release_candidate_id,
        release_environment=release_environment,
        kind=kind,
        statement=statement,
        evidence_refs=refs,
        parent_signal_id=parent_signal_id,
        generation=generation,
        tags=tag_values,
    )


def improvement_signal_subject_fingerprint(
    signal: ImprovementSignal,
) -> str:
    if not isinstance(signal, ImprovementSignal):
        raise ImprovementSignalError(
            "signal must be ImprovementSignal"
        )
    return _fingerprint(
        {
            "repository": signal.repository,
            "source_sha": signal.source_sha,
            "release_candidate_id": signal.release_candidate_id,
            "release_environment": signal.release_environment,
            "kind": signal.kind.value,
            "statement": signal.statement,
        }
    )

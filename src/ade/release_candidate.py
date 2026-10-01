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
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_RELEASE_EVIDENCE_REFS = 8


class ReleaseCandidateError(ValueError):
    """Trusted release-candidate validation failed."""


class ReleaseEnvironment(StrEnum):
    PREVIEW = "preview"
    STAGING = "staging"
    PRODUCTION = "production"


class ReleaseEvidenceKind(StrEnum):
    ACCEPTED_PLAN = "ACCEPTED_PLAN"
    CAMPAIGN = "CAMPAIGN"
    RUNTIME_VERIFICATION = "RUNTIME_VERIFICATION"
    REVIEW_CLEARANCE = "REVIEW_CLEARANCE"


_REQUIRED_EVIDENCE_KINDS = frozenset(
    {
        ReleaseEvidenceKind.ACCEPTED_PLAN,
        ReleaseEvidenceKind.CAMPAIGN,
        ReleaseEvidenceKind.RUNTIME_VERIFICATION,
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
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise ReleaseCandidateError("repository must be owner/name")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ReleaseCandidateError("repository must be owner/name")
    return value


def _sha40(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ReleaseCandidateError(f"{field} must be a lowercase 40-char SHA")
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReleaseCandidateError(f"{field} must be sha256")
    return value


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ReleaseCandidateError(f"{field} is invalid")
    return value


def _evidence_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ReleaseCandidateError("evidence path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise ReleaseCandidateError("evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise ReleaseCandidateError("evidence path must be normalized")
    if not value.startswith(".autodev/"):
        raise ReleaseCandidateError("evidence path must remain inside .autodev/")
    return value


def _authority_false(payload: dict[str, Any], field: str) -> None:
    if payload.get(field, False) is not False:
        raise ReleaseCandidateError(
            f"release candidate cannot grant {field.replace('_', ' ')}"
        )


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceRef:
    kind: ReleaseEvidenceKind
    path: str
    fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseCandidateError("unsupported release evidence schema version")
        if not isinstance(self.kind, ReleaseEvidenceKind):
            raise ReleaseCandidateError("kind must be ReleaseEvidenceKind")
        object.__setattr__(self, "path", _evidence_path(self.path))
        object.__setattr__(
            self,
            "fingerprint",
            _sha256(self.fingerprint, field="evidence fingerprint"),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "path": self.path,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReleaseEvidenceRef":
        if not isinstance(payload, dict):
            raise ReleaseCandidateError("release evidence must be a JSON object")
        allowed = {"schema_version", "kind", "path", "fingerprint"}
        unknown = set(payload) - allowed
        if unknown:
            raise ReleaseCandidateError(
                f"unknown release evidence fields: {sorted(unknown)}"
            )
        try:
            kind = ReleaseEvidenceKind(payload.get("kind"))
        except ValueError as exc:
            raise ReleaseCandidateError("release evidence kind is invalid") from exc
        return cls(
            schema_version=payload.get("schema_version", 0),
            kind=kind,
            path=payload.get("path", ""),
            fingerprint=payload.get("fingerprint", ""),
        )


def build_release_candidate_id(
    *,
    repository: str,
    source_sha: str,
    campaign_id: str,
    accepted_plan_fingerprint: str,
    runtime_verification_id: str,
    target_environment: ReleaseEnvironment,
    evidence_refs: Iterable[ReleaseEvidenceRef],
) -> str:
    repository = _repository(repository)
    source_sha = _sha40(source_sha, field="source_sha")
    campaign_id = _identifier(campaign_id, field="campaign_id")
    accepted_plan_fingerprint = _sha256(
        accepted_plan_fingerprint,
        field="accepted_plan_fingerprint",
    )
    runtime_verification_id = _identifier(
        runtime_verification_id,
        field="runtime_verification_id",
    )
    if not isinstance(target_environment, ReleaseEnvironment):
        raise ReleaseCandidateError(
            "target_environment must be ReleaseEnvironment"
        )
    refs = tuple(
        sorted(
            evidence_refs,
            key=lambda item: (item.kind.value, item.path, item.fingerprint),
        )
    )
    if not refs or any(not isinstance(item, ReleaseEvidenceRef) for item in refs):
        raise ReleaseCandidateError(
            "evidence_refs must contain ReleaseEvidenceRef values"
        )
    digest = _fingerprint(
        {
            "repository": repository,
            "source_sha": source_sha,
            "campaign_id": campaign_id,
            "accepted_plan_fingerprint": accepted_plan_fingerprint,
            "runtime_verification_id": runtime_verification_id,
            "target_environment": target_environment.value,
            "evidence_refs": [item.canonical_dict() for item in refs],
        }
    )
    return "release-" + digest[:24]


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    release_candidate_id: str
    repository: str
    source_sha: str
    campaign_id: str
    accepted_plan_fingerprint: str
    runtime_verification_id: str
    target_environment: ReleaseEnvironment
    evidence_refs: tuple[ReleaseEvidenceRef, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseCandidateError("unsupported release candidate schema version")
        object.__setattr__(
            self,
            "release_candidate_id",
            _identifier(self.release_candidate_id, field="release_candidate_id"),
        )
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(
            self,
            "source_sha",
            _sha40(self.source_sha, field="source_sha"),
        )
        object.__setattr__(
            self,
            "campaign_id",
            _identifier(self.campaign_id, field="campaign_id"),
        )
        object.__setattr__(
            self,
            "accepted_plan_fingerprint",
            _sha256(
                self.accepted_plan_fingerprint,
                field="accepted_plan_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "runtime_verification_id",
            _identifier(
                self.runtime_verification_id,
                field="runtime_verification_id",
            ),
        )
        if not isinstance(self.target_environment, ReleaseEnvironment):
            raise ReleaseCandidateError(
                "target_environment must be ReleaseEnvironment"
            )

        refs = tuple(self.evidence_refs)
        if not 1 <= len(refs) <= MAX_RELEASE_EVIDENCE_REFS:
            raise ReleaseCandidateError(
                "release evidence exceeds trusted budget"
            )
        if any(not isinstance(item, ReleaseEvidenceRef) for item in refs):
            raise ReleaseCandidateError(
                "evidence_refs must contain ReleaseEvidenceRef values"
            )
        by_kind: dict[ReleaseEvidenceKind, ReleaseEvidenceRef] = {}
        for item in refs:
            if item.kind in by_kind:
                raise ReleaseCandidateError(
                    f"duplicate release evidence kind: {item.kind.value}"
                )
            by_kind[item.kind] = item
        missing = _REQUIRED_EVIDENCE_KINDS - set(by_kind)
        if missing:
            raise ReleaseCandidateError(
                "release candidate is missing required evidence: "
                + ", ".join(sorted(kind.value for kind in missing))
            )
        normalized = tuple(
            sorted(
                refs,
                key=lambda item: (item.kind.value, item.path, item.fingerprint),
            )
        )
        object.__setattr__(self, "evidence_refs", normalized)

        expected_id = build_release_candidate_id(
            repository=self.repository,
            source_sha=self.source_sha,
            campaign_id=self.campaign_id,
            accepted_plan_fingerprint=self.accepted_plan_fingerprint,
            runtime_verification_id=self.runtime_verification_id,
            target_environment=self.target_environment,
            evidence_refs=self.evidence_refs,
        )
        if self.release_candidate_id != expected_id:
            raise ReleaseCandidateError(
                "release_candidate_id does not match trusted content"
            )

    @property
    def requires_human_approval(self) -> bool:
        # Deployment/promotion is an externally consequential side effect under
        # the current ADE safety contract. Slice 001 therefore grants no
        # autonomous promotion authority for any release environment.
        return True

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "release_candidate_id": self.release_candidate_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "campaign_id": self.campaign_id,
            "accepted_plan_fingerprint": self.accepted_plan_fingerprint,
            "runtime_verification_id": self.runtime_verification_id,
            "target_environment": self.target_environment.value,
            "evidence_refs": [item.canonical_dict() for item in self.evidence_refs],
            "requires_human_approval": self.requires_human_approval,
            "deployment_authority": False,
            "promotion_authority": False,
            "auto_promote": False,
            "may_expand_scope": False,
            "may_mutate_acceptance": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReleaseCandidate":
        if not isinstance(payload, dict):
            raise ReleaseCandidateError("release candidate must be a JSON object")
        allowed = {
            "schema_version",
            "release_candidate_id",
            "repository",
            "source_sha",
            "campaign_id",
            "accepted_plan_fingerprint",
            "runtime_verification_id",
            "target_environment",
            "evidence_refs",
            "requires_human_approval",
            "deployment_authority",
            "promotion_authority",
            "auto_promote",
            "may_expand_scope",
            "may_mutate_acceptance",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ReleaseCandidateError(
                f"unknown release candidate fields: {sorted(unknown)}"
            )
        for field in (
            "deployment_authority",
            "promotion_authority",
            "auto_promote",
            "may_expand_scope",
            "may_mutate_acceptance",
        ):
            _authority_false(payload, field)
        if payload.get("requires_human_approval") is not True:
            raise ReleaseCandidateError(
                "release candidate must require human approval"
            )
        try:
            target_environment = ReleaseEnvironment(
                payload.get("target_environment")
            )
        except ValueError as exc:
            raise ReleaseCandidateError(
                "target_environment is invalid"
            ) from exc
        raw_refs = payload.get("evidence_refs")
        if not isinstance(raw_refs, list):
            raise ReleaseCandidateError("evidence_refs must be a list")
        return cls(
            schema_version=payload.get("schema_version", 0),
            release_candidate_id=payload.get("release_candidate_id", ""),
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            campaign_id=payload.get("campaign_id", ""),
            accepted_plan_fingerprint=payload.get(
                "accepted_plan_fingerprint",
                "",
            ),
            runtime_verification_id=payload.get(
                "runtime_verification_id",
                "",
            ),
            target_environment=target_environment,
            evidence_refs=tuple(
                ReleaseEvidenceRef.from_dict(item) for item in raw_refs
            ),
        )


def build_release_candidate(
    *,
    repository: str,
    source_sha: str,
    campaign_id: str,
    accepted_plan_fingerprint: str,
    runtime_verification_id: str,
    target_environment: ReleaseEnvironment,
    evidence_refs: Iterable[ReleaseEvidenceRef],
) -> ReleaseCandidate:
    refs = tuple(evidence_refs)
    candidate_id = build_release_candidate_id(
        repository=repository,
        source_sha=source_sha,
        campaign_id=campaign_id,
        accepted_plan_fingerprint=accepted_plan_fingerprint,
        runtime_verification_id=runtime_verification_id,
        target_environment=target_environment,
        evidence_refs=refs,
    )
    return ReleaseCandidate(
        release_candidate_id=candidate_id,
        repository=repository,
        source_sha=source_sha,
        campaign_id=campaign_id,
        accepted_plan_fingerprint=accepted_plan_fingerprint,
        runtime_verification_id=runtime_verification_id,
        target_environment=target_environment,
        evidence_refs=refs,
    )

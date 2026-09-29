from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationError,
)


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class RuntimeTargetKind(StrEnum):
    REPOSITORY = "repository"
    PREVIEW = "preview"
    STAGING = "staging"
    PRODUCTION = "production"


def _safe_id(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise RuntimeVerificationError(f"{label} must be a safe identifier")
    return value


def _sha40(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise RuntimeVerificationError(
            f"{label} must be a lowercase 40-char SHA"
        )
    return value


def _aware_utc(value: datetime, *, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RuntimeVerificationError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RuntimeTargetSpec:
    target_id: str
    environment: str
    kind: RuntimeTargetKind
    max_age_seconds: int = 900
    max_future_skew_seconds: int = 60
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RuntimeVerificationError(
                "runtime target spec schema_version must be 1"
            )
        _safe_id(self.target_id, label="runtime target_id")
        _safe_id(self.environment, label="runtime target environment")
        if not isinstance(self.kind, RuntimeTargetKind):
            object.__setattr__(self, "kind", RuntimeTargetKind(self.kind))
        if (
            type(self.max_age_seconds) is not int
            or not 1 <= self.max_age_seconds <= 86400
        ):
            raise RuntimeVerificationError(
                "runtime target max_age_seconds must be between 1 and 86400"
            )
        if (
            type(self.max_future_skew_seconds) is not int
            or not 0 <= self.max_future_skew_seconds <= 300
        ):
            raise RuntimeVerificationError(
                "runtime target max_future_skew_seconds must be between 0 and 300"
            )

    @property
    def deployment_required(self) -> bool:
        return self.kind is not RuntimeTargetKind.REPOSITORY

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "target_id": self.target_id,
            "environment": self.environment,
            "kind": self.kind.value,
            "deployment_required": self.deployment_required,
            "max_age_seconds": self.max_age_seconds,
            "max_future_skew_seconds": self.max_future_skew_seconds,
        }


@dataclass(frozen=True, slots=True)
class RuntimeTargetInvocation:
    target_repository: str
    source_sha: str
    environment: str
    target_id: str
    kind: RuntimeTargetKind


@dataclass(frozen=True, slots=True)
class RuntimeTargetObservation:
    source_sha: str
    observed_at: datetime
    deployment_id: str | None = None

    def __post_init__(self) -> None:
        _sha40(self.source_sha, label="runtime target observed source_sha")
        object.__setattr__(
            self,
            "observed_at",
            _aware_utc(self.observed_at, label="runtime target observed_at"),
        )
        if self.deployment_id is not None:
            _safe_id(self.deployment_id, label="runtime deployment_id")


RuntimeTargetObserver = Callable[[RuntimeTargetInvocation], RuntimeTargetObservation]


@dataclass(frozen=True, slots=True)
class RuntimeTargetRegistration:
    target_repository: str
    spec: RuntimeTargetSpec
    implementation_id: str
    observer: RuntimeTargetObserver

    def __post_init__(self) -> None:
        # Reuse the runtime contract's strict repository validation.
        RuntimeVerificationContract(
            verification_id="runtime-target-registration",
            target_repository=self.target_repository,
            source_sha="a" * 40,
            environment=self.spec.environment,
            required_probe_ids=("registration-check",),
        )
        _safe_id(
            self.implementation_id,
            label="runtime target implementation_id",
        )
        if not callable(self.observer):
            raise RuntimeVerificationError(
                "runtime target observer must be callable"
            )

    @property
    def key(self) -> tuple[str, str]:
        return (self.target_repository, self.spec.environment)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "target_repository": self.target_repository,
            "spec": self.spec.canonical_dict(),
            "implementation_id": self.implementation_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeTargetEvidence:
    target_id: str
    kind: RuntimeTargetKind
    target_repository: str
    environment: str
    source_sha: str
    observed_at: str
    provenance_id: str
    deployment_id: str | None
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "target_id": self.target_id,
            "kind": self.kind.value,
            "target_repository": self.target_repository,
            "environment": self.environment,
            "source_sha": self.source_sha,
            "observed_at": self.observed_at,
            "provenance_id": self.provenance_id,
            "deployment_id": self.deployment_id,
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeTargetResolution:
    spec: RuntimeTargetSpec
    evidence: RuntimeTargetEvidence
    registry_fingerprint: str

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "spec": self.spec.canonical_dict(),
            "evidence": self.evidence.canonical_dict(),
            "evidence_fingerprint": self.evidence.fingerprint(),
            "registry_fingerprint": self.registry_fingerprint,
        }


class TrustedRuntimeTargetRegistry:
    def __init__(
        self,
        registrations: Iterable[RuntimeTargetRegistration],
    ) -> None:
        items = list(registrations)
        if not items:
            raise RuntimeVerificationError(
                "trusted runtime target registry must not be empty"
            )
        by_key: dict[tuple[str, str], RuntimeTargetRegistration] = {}
        for registration in items:
            if not isinstance(registration, RuntimeTargetRegistration):
                raise RuntimeVerificationError(
                    "runtime target registry entries must be RuntimeTargetRegistration"
                )
            if registration.key in by_key:
                raise RuntimeVerificationError(
                    "duplicate trusted runtime target registration"
                )
            by_key[registration.key] = registration
        self._registrations: Mapping[
            tuple[str, str],
            RuntimeTargetRegistration,
        ] = MappingProxyType(dict(sorted(by_key.items())))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "registrations": [
                self._registrations[key].canonical_dict()
                for key in sorted(self._registrations)
            ],
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def resolve(
        self,
        contract: RuntimeVerificationContract,
        *,
        now: datetime,
    ) -> RuntimeTargetResolution:
        if not isinstance(contract, RuntimeVerificationContract):
            raise RuntimeVerificationError(
                "contract must be a RuntimeVerificationContract"
            )
        now_utc = _aware_utc(now, label="runtime target resolution now")
        key = (contract.target_repository, contract.environment)
        registration = self._registrations.get(key)
        if registration is None:
            raise RuntimeVerificationError(
                "no trusted runtime target adapter for contract environment"
            )

        invocation = RuntimeTargetInvocation(
            target_repository=contract.target_repository,
            source_sha=contract.source_sha,
            environment=contract.environment,
            target_id=registration.spec.target_id,
            kind=registration.spec.kind,
        )
        try:
            observation = registration.observer(invocation)
        except Exception as exc:
            raise RuntimeVerificationError(
                "trusted runtime target observer failed"
            ) from exc
        if not isinstance(observation, RuntimeTargetObservation):
            raise RuntimeVerificationError(
                "runtime target observer returned invalid observation"
            )
        if observation.source_sha != contract.source_sha:
            raise RuntimeVerificationError(
                "runtime target source SHA does not match contract"
            )

        age_seconds = (now_utc - observation.observed_at).total_seconds()
        if age_seconds > registration.spec.max_age_seconds:
            raise RuntimeVerificationError(
                "runtime target observation is stale"
            )
        if age_seconds < -registration.spec.max_future_skew_seconds:
            raise RuntimeVerificationError(
                "runtime target observation is from the future"
            )

        if registration.spec.deployment_required:
            if observation.deployment_id is None:
                raise RuntimeVerificationError(
                    "deployment-backed runtime target requires deployment_id"
                )
        elif observation.deployment_id is not None:
            raise RuntimeVerificationError(
                "repository runtime target must not claim deployment_id"
            )

        evidence = RuntimeTargetEvidence(
            target_id=registration.spec.target_id,
            kind=registration.spec.kind,
            target_repository=contract.target_repository,
            environment=contract.environment,
            source_sha=contract.source_sha,
            observed_at=observation.observed_at.isoformat(),
            provenance_id=registration.implementation_id,
            deployment_id=observation.deployment_id,
        )
        return RuntimeTargetResolution(
            spec=registration.spec,
            evidence=evidence,
            registry_fingerprint=self.fingerprint(),
        )

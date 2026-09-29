from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class RuntimeVerificationError(ValueError):
    """Trusted runtime-verification contract or evidence is invalid."""


class RuntimeProbeStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class RuntimeVerificationDisposition(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


def _safe_id(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise RuntimeVerificationError(f"{label} must be a safe identifier")
    return value


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise RuntimeVerificationError("target_repository must be owner/name")
    return value


def _sha40(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise RuntimeVerificationError(f"{label} must be a lowercase 40-char SHA")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeVerificationContract:
    verification_id: str
    target_repository: str
    source_sha: str
    environment: str
    required_probe_ids: tuple[str, ...]
    max_attempts: int = 1
    timeout_seconds: int = 300
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RuntimeVerificationError("runtime verification schema_version must be 1")
        _safe_id(self.verification_id, label="verification_id")
        _repository(self.target_repository)
        _sha40(self.source_sha, label="source_sha")
        _safe_id(self.environment, label="environment")
        if not self.required_probe_ids:
            raise RuntimeVerificationError("required_probe_ids must not be empty")
        normalized: list[str] = []
        for probe_id in self.required_probe_ids:
            normalized.append(_safe_id(probe_id, label="probe_id"))
        if len(set(normalized)) != len(normalized):
            raise RuntimeVerificationError("required_probe_ids must be unique")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise RuntimeVerificationError("max_attempts must be between 1 and 5")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 900:
            raise RuntimeVerificationError("timeout_seconds must be between 1 and 900")
        object.__setattr__(self, "required_probe_ids", tuple(sorted(normalized)))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "verification_id": self.verification_id,
            "target_repository": self.target_repository,
            "source_sha": self.source_sha,
            "environment": self.environment,
            "required_probe_ids": list(self.required_probe_ids),
            "max_attempts": self.max_attempts,
            "timeout_seconds": self.timeout_seconds,
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeProbeResult:
    probe_id: str
    status: RuntimeProbeStatus
    source_sha: str
    attempt: int = 1
    detail_code: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RuntimeVerificationError("runtime probe result schema_version must be 1")
        _safe_id(self.probe_id, label="probe_id")
        _sha40(self.source_sha, label="source_sha")
        if not isinstance(self.status, RuntimeProbeStatus):
            object.__setattr__(self, "status", RuntimeProbeStatus(self.status))
        if type(self.attempt) is not int or self.attempt < 1:
            raise RuntimeVerificationError("probe attempt must be a positive integer")
        if self.detail_code is not None:
            _safe_id(self.detail_code, label="detail_code")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "probe_id": self.probe_id,
            "status": self.status.value,
            "source_sha": self.source_sha,
            "attempt": self.attempt,
            "detail_code": self.detail_code,
        }


@dataclass(frozen=True, slots=True)
class RuntimeVerificationReport:
    verification_id: str
    contract_fingerprint: str
    source_sha: str
    disposition: RuntimeVerificationDisposition
    results: tuple[RuntimeProbeResult, ...]
    missing_probe_ids: tuple[str, ...]
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "verification_id": self.verification_id,
            "contract_fingerprint": self.contract_fingerprint,
            "source_sha": self.source_sha,
            "disposition": self.disposition.value,
            "results": [result.canonical_dict() for result in self.results],
            "missing_probe_ids": list(self.missing_probe_ids),
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evaluate_runtime_verification(
    contract: RuntimeVerificationContract,
    results: Iterable[RuntimeProbeResult],
) -> RuntimeVerificationReport:
    if not isinstance(contract, RuntimeVerificationContract):
        raise RuntimeVerificationError(
            "contract must be a RuntimeVerificationContract"
        )

    required = set(contract.required_probe_ids)
    by_probe: dict[str, RuntimeProbeResult] = {}
    for result in results:
        if not isinstance(result, RuntimeProbeResult):
            raise RuntimeVerificationError(
                "results must contain RuntimeProbeResult values"
            )
        if result.probe_id not in required:
            raise RuntimeVerificationError(
                f"unexpected runtime probe result: {result.probe_id}"
            )
        if result.probe_id in by_probe:
            raise RuntimeVerificationError(
                f"duplicate runtime probe result: {result.probe_id}"
            )
        if result.source_sha != contract.source_sha:
            raise RuntimeVerificationError(
                f"runtime probe source SHA mismatch: {result.probe_id}"
            )
        if result.attempt > contract.max_attempts:
            raise RuntimeVerificationError(
                f"runtime probe exceeds trusted attempt budget: {result.probe_id}"
            )
        by_probe[result.probe_id] = result

    ordered = tuple(by_probe[key] for key in sorted(by_probe))
    missing = tuple(sorted(required - set(by_probe)))
    if missing:
        disposition = RuntimeVerificationDisposition.PENDING
    elif all(result.status is RuntimeProbeStatus.PASS for result in ordered):
        disposition = RuntimeVerificationDisposition.VERIFIED
    else:
        disposition = RuntimeVerificationDisposition.FAILED

    return RuntimeVerificationReport(
        verification_id=contract.verification_id,
        contract_fingerprint=contract.fingerprint(),
        source_sha=contract.source_sha,
        disposition=disposition,
        results=ordered,
        missing_probe_ids=missing,
    )

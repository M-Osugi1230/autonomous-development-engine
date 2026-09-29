from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationError,
)


@dataclass(frozen=True, slots=True)
class RuntimeProbeInvocation:
    target_repository: str
    source_sha: str
    environment: str


@dataclass(frozen=True, slots=True)
class RuntimeProbeObservation:
    status: RuntimeProbeStatus
    detail_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, RuntimeProbeStatus):
            object.__setattr__(self, "status", RuntimeProbeStatus(self.status))
        if self.detail_code is not None:
            # Reuse RuntimeProbeResult validation without allowing the runner
            # to choose probe identity, source SHA, or attempt.
            RuntimeProbeResult(
                probe_id="observation-check",
                status=self.status,
                source_sha="a" * 40,
                detail_code=self.detail_code,
            )


RuntimeProbeRunner = Callable[[RuntimeProbeInvocation], RuntimeProbeObservation]


@dataclass(frozen=True, slots=True)
class RuntimeProbeRegistration:
    probe_id: str
    implementation_id: str
    runner: RuntimeProbeRunner

    def __post_init__(self) -> None:
        if not callable(self.runner):
            raise RuntimeVerificationError("runtime probe runner must be callable")
        RuntimeVerificationContract(
            verification_id="registration-check",
            target_repository="example/target",
            source_sha="a" * 40,
            environment="test",
            required_probe_ids=(self.probe_id,),
        )
        RuntimeProbeResult(
            probe_id=self.implementation_id,
            status=RuntimeProbeStatus.PASS,
            source_sha="a" * 40,
        )

    def canonical_dict(self) -> dict[str, str]:
        return {
            "probe_id": self.probe_id,
            "implementation_id": self.implementation_id,
        }


class TrustedRuntimeProbeRegistry:
    def __init__(self, registrations: Iterable[RuntimeProbeRegistration]) -> None:
        items = list(registrations)
        if not items:
            raise RuntimeVerificationError(
                "trusted runtime probe registry must not be empty"
            )
        by_id: dict[str, RuntimeProbeRegistration] = {}
        for registration in items:
            if not isinstance(registration, RuntimeProbeRegistration):
                raise RuntimeVerificationError(
                    "registry entries must be RuntimeProbeRegistration values"
                )
            if registration.probe_id in by_id:
                raise RuntimeVerificationError(
                    f"duplicate trusted runtime probe: {registration.probe_id}"
                )
            by_id[registration.probe_id] = registration
        self._registrations: Mapping[str, RuntimeProbeRegistration] = (
            MappingProxyType(dict(sorted(by_id.items())))
        )

    @property
    def probe_ids(self) -> tuple[str, ...]:
        return tuple(self._registrations)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "registrations": [
                self._registrations[probe_id].canonical_dict()
                for probe_id in self.probe_ids
            ],
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def ensure_contract_supported(
        self,
        contract: RuntimeVerificationContract,
    ) -> None:
        if not isinstance(contract, RuntimeVerificationContract):
            raise RuntimeVerificationError(
                "contract must be a RuntimeVerificationContract"
            )
        missing = sorted(set(contract.required_probe_ids) - set(self.probe_ids))
        if missing:
            raise RuntimeVerificationError(
                f"contract requires unregistered runtime probes: {missing}"
            )

    def execute(
        self,
        contract: RuntimeVerificationContract,
        *,
        probe_id: str,
        attempt: int = 1,
    ) -> RuntimeProbeResult:
        self.ensure_contract_supported(contract)
        if probe_id not in contract.required_probe_ids:
            raise RuntimeVerificationError(
                f"runtime probe is not required by contract: {probe_id}"
            )
        if type(attempt) is not int or not 1 <= attempt <= contract.max_attempts:
            raise RuntimeVerificationError(
                f"runtime probe attempt exceeds trusted budget: {probe_id}"
            )

        registration = self._registrations[probe_id]
        invocation = RuntimeProbeInvocation(
            target_repository=contract.target_repository,
            source_sha=contract.source_sha,
            environment=contract.environment,
        )
        try:
            observation = registration.runner(invocation)
        except Exception:
            observation = RuntimeProbeObservation(
                status=RuntimeProbeStatus.ERROR,
                detail_code="runner-exception",
            )
        if not isinstance(observation, RuntimeProbeObservation):
            raise RuntimeVerificationError(
                f"runtime probe returned invalid observation: {probe_id}"
            )

        return RuntimeProbeResult(
            probe_id=probe_id,
            status=observation.status,
            source_sha=contract.source_sha,
            attempt=attempt,
            detail_code=observation.detail_code,
        )

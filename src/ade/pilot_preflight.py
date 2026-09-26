from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping

from .pilot import PilotContract
from .provider_router import ProviderAvailability, ProviderAvailabilitySnapshot


class PreflightCheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class PreflightCheckKind(StrEnum):
    REPOSITORY = "REPOSITORY"
    BASE_BRANCH = "BASE_BRANCH"
    BASELINE_SHA = "BASELINE_SHA"
    PROVIDER_AVAILABILITY = "PROVIDER_AVAILABILITY"
    ACCEPTANCE_COMMAND = "ACCEPTANCE_COMMAND"


@dataclass(frozen=True, slots=True)
class PilotPreflightCheck:
    check_id: str
    kind: PreflightCheckKind
    status: PreflightCheckStatus
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, str) or not self.check_id.strip():
            raise ValueError("check_id must be a non-empty string")
        try:
            kind = PreflightCheckKind(self.kind)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid preflight check kind: {self.kind!r}") from exc
        object.__setattr__(self, "kind", kind)
        try:
            status = PreflightCheckStatus(self.status)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid preflight check status: {self.status!r}") from exc
        object.__setattr__(self, "status", status)
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {
            "check_id": self.check_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class PilotPreflightReport:
    pilot_id: str
    passed: bool
    checks: tuple[PilotPreflightCheck, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.pilot_id, str) or not self.pilot_id.strip():
            raise ValueError("pilot_id must be a non-empty string")
        if type(self.passed) is not bool:
            raise ValueError("passed must be a boolean")
        raw = self.checks
        if not isinstance(raw, tuple):
            try:
                raw = tuple(raw)
            except TypeError as exc:
                raise ValueError("checks must be iterable") from exc
        if not raw:
            raise ValueError("checks must not be empty")
        for check in raw:
            if not isinstance(check, PilotPreflightCheck):
                raise ValueError("checks must contain PilotPreflightCheck values")
        expected = all(check.status is PreflightCheckStatus.PASS for check in raw)
        if expected is not self.passed:
            raise ValueError("passed must exactly match the aggregate check result")
        object.__setattr__(self, "checks", raw)

    def to_dict(self) -> dict[str, object]:
        return {
            "pilot_id": self.pilot_id,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }


def _availability_map(
    availability: Iterable[ProviderAvailabilitySnapshot],
) -> dict[str, ProviderAvailabilitySnapshot]:
    if isinstance(availability, (str, bytes)):
        raise ValueError("availability must be an iterable of ProviderAvailabilitySnapshot")
    result: dict[str, ProviderAvailabilitySnapshot] = {}
    try:
        iterator = iter(availability)
    except TypeError as exc:
        raise ValueError(
            "availability must be an iterable of ProviderAvailabilitySnapshot"
        ) from exc
    for item in iterator:
        if not isinstance(item, ProviderAvailabilitySnapshot):
            raise ValueError(
                "availability must contain ProviderAvailabilitySnapshot values"
            )
        if item.provider_id in result:
            raise ValueError(f"duplicate provider availability: {item.provider_id}")
        result[item.provider_id] = item
    return result


def run_pilot_preflight(
    contract: PilotContract,
    *,
    observed_repository: str | None,
    observed_base_branch: str | None,
    observed_baseline_sha: str | None,
    provider_availability: Iterable[ProviderAvailabilitySnapshot],
    acceptance_command_readiness: Mapping[str, bool],
) -> PilotPreflightReport:
    if not isinstance(contract, PilotContract):
        raise ValueError("contract must be a PilotContract")
    if not isinstance(acceptance_command_readiness, Mapping):
        raise ValueError("acceptance_command_readiness must be a mapping")

    checks: list[PilotPreflightCheck] = []

    repository_ok = observed_repository == contract.target.repository
    checks.append(
        PilotPreflightCheck(
            check_id="target-repository",
            kind=PreflightCheckKind.REPOSITORY,
            status=(
                PreflightCheckStatus.PASS
                if repository_ok
                else PreflightCheckStatus.FAIL
            ),
            message=(
                f"target repository verified: {contract.target.repository}"
                if repository_ok
                else "target repository does not match the pilot contract"
            ),
        )
    )

    branch_ok = observed_base_branch == contract.target.base_branch
    checks.append(
        PilotPreflightCheck(
            check_id="base-branch",
            kind=PreflightCheckKind.BASE_BRANCH,
            status=PreflightCheckStatus.PASS if branch_ok else PreflightCheckStatus.FAIL,
            message=(
                f"base branch verified: {contract.target.base_branch}"
                if branch_ok
                else "base branch does not match the pilot contract"
            ),
        )
    )

    observed_sha = (
        observed_baseline_sha.lower()
        if isinstance(observed_baseline_sha, str)
        else None
    )
    baseline_ok = observed_sha == contract.target.baseline_sha
    checks.append(
        PilotPreflightCheck(
            check_id="baseline-sha",
            kind=PreflightCheckKind.BASELINE_SHA,
            status=(
                PreflightCheckStatus.PASS if baseline_ok else PreflightCheckStatus.FAIL
            ),
            message=(
                f"baseline SHA verified: {contract.target.baseline_sha}"
                if baseline_ok
                else "baseline SHA does not match the pilot contract"
            ),
        )
    )

    availability = _availability_map(provider_availability)
    eligible_provider_ids = (
        contract.provider_policy.allowed_provider_ids
        if contract.provider_policy.allow_fallback_before_session
        else contract.provider_policy.preferred_provider_ids
    )
    available_allowed = [
        provider_id
        for provider_id in eligible_provider_ids
        if (
            provider_id in availability
            and availability[provider_id].availability is ProviderAvailability.AVAILABLE
        )
    ]
    provider_ok = bool(available_allowed)
    checks.append(
        PilotPreflightCheck(
            check_id="provider-availability",
            kind=PreflightCheckKind.PROVIDER_AVAILABILITY,
            status=(
                PreflightCheckStatus.PASS if provider_ok else PreflightCheckStatus.FAIL
            ),
            message=(
                "available allowed provider(s): " + ", ".join(available_allowed)
                if provider_ok
                else "no allowed provider is currently available"
            ),
        )
    )

    expected_check_ids = {check.check_id for check in contract.acceptance_checks}
    provided_check_ids = set(acceptance_command_readiness.keys())
    unknown = provided_check_ids - expected_check_ids
    if unknown:
        raise ValueError(
            f"acceptance_command_readiness contains unknown check IDs: {sorted(unknown)}"
        )

    for acceptance in contract.acceptance_checks:
        ready = acceptance_command_readiness.get(acceptance.check_id)
        checks.append(
            PilotPreflightCheck(
                check_id=f"acceptance:{acceptance.check_id}",
                kind=PreflightCheckKind.ACCEPTANCE_COMMAND,
                status=(
                    PreflightCheckStatus.PASS
                    if ready is True
                    else PreflightCheckStatus.FAIL
                ),
                message=(
                    f"acceptance command ready: {acceptance.check_id}"
                    if ready is True
                    else f"acceptance command not ready: {acceptance.check_id}"
                ),
            )
        )

    result = tuple(checks)
    return PilotPreflightReport(
        pilot_id=contract.pilot_id,
        passed=all(check.status is PreflightCheckStatus.PASS for check in result),
        checks=result,
    )

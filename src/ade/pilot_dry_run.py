from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from .pilot import PilotAction, PilotContract
from .pilot_activation import (
    PilotActivation,
    pilot_contract_fingerprint,
    pilot_target_writes_allowed,
)
from .pilot_preflight import PilotPreflightReport


class DryRunCheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class PilotDryRunOperation:
    operation_id: str
    action: PilotAction
    path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise ValueError("operation_id must be a non-empty string")
        try:
            action = PilotAction(self.action)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid pilot action: {self.action!r}") from exc
        object.__setattr__(self, "action", action)
        if self.path is not None:
            if not isinstance(self.path, str) or not self.path.strip():
                raise ValueError("path must be a non-empty string or None")
            object.__setattr__(self, "path", self.path.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "action": self.action.value,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class PilotDryRunOperationResult:
    operation_id: str
    action: PilotAction
    path: str | None
    status: DryRunCheckStatus
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise ValueError("operation_id must be a non-empty string")
        try:
            action = PilotAction(self.action)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid pilot action: {self.action!r}") from exc
        object.__setattr__(self, "action", action)
        try:
            status = DryRunCheckStatus(self.status)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid dry-run status: {self.status!r}") from exc
        object.__setattr__(self, "status", status)
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "action": self.action.value,
            "path": self.path,
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PilotDryRunReport:
    pilot_id: str
    contract_fingerprint: str
    target_repository: str
    baseline_sha: str
    preflight_passed: bool
    activation_satisfied: bool
    passed: bool
    operations: tuple[PilotDryRunOperationResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.pilot_id, str) or not self.pilot_id.strip():
            raise ValueError("pilot_id must be a non-empty string")
        for name in ("preflight_passed", "activation_satisfied", "passed"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        raw = self.operations
        if not isinstance(raw, tuple):
            try:
                raw = tuple(raw)
            except TypeError as exc:
                raise ValueError("operations must be iterable") from exc
        if not raw:
            raise ValueError("operations must not be empty")
        if any(not isinstance(item, PilotDryRunOperationResult) for item in raw):
            raise ValueError(
                "operations must contain PilotDryRunOperationResult values"
            )
        expected = (
            self.preflight_passed
            and self.activation_satisfied
            and all(item.status is DryRunCheckStatus.PASS for item in raw)
        )
        if expected is not self.passed:
            raise ValueError("passed must exactly match dry-run aggregate status")
        object.__setattr__(self, "operations", raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pilot_id": self.pilot_id,
            "contract_fingerprint": self.contract_fingerprint,
            "target_repository": self.target_repository,
            "baseline_sha": self.baseline_sha,
            "preflight_passed": self.preflight_passed,
            "activation_satisfied": self.activation_satisfied,
            "passed": self.passed,
            "operations": [item.to_dict() for item in self.operations],
        }


_PATH_SCOPED_ACTIONS = {
    PilotAction.READ,
    PilotAction.MODIFY_FILES,
}


def _normalize_operations(
    operations: Iterable[PilotDryRunOperation],
) -> tuple[PilotDryRunOperation, ...]:
    if isinstance(operations, (str, bytes)):
        raise ValueError("operations must be an iterable of PilotDryRunOperation")
    try:
        iterator = iter(operations)
    except TypeError as exc:
        raise ValueError(
            "operations must be an iterable of PilotDryRunOperation"
        ) from exc

    normalized: list[PilotDryRunOperation] = []
    seen: set[str] = set()
    for item in iterator:
        if not isinstance(item, PilotDryRunOperation):
            raise ValueError("operations must contain PilotDryRunOperation values")
        if item.operation_id in seen:
            raise ValueError(f"duplicate operation_id: {item.operation_id}")
        seen.add(item.operation_id)
        normalized.append(item)
    if not normalized:
        raise ValueError("operations must not be empty")
    return tuple(normalized)


def run_pilot_dry_run(
    contract: PilotContract,
    *,
    preflight: PilotPreflightReport,
    activation: PilotActivation | None,
    operations: Iterable[PilotDryRunOperation],
) -> PilotDryRunReport:
    if not isinstance(contract, PilotContract):
        raise TypeError("contract must be a PilotContract")
    if not isinstance(preflight, PilotPreflightReport):
        raise TypeError("preflight must be a PilotPreflightReport")
    if preflight.pilot_id != contract.pilot_id:
        raise ValueError("preflight pilot_id does not match the pilot contract")

    normalized = _normalize_operations(operations)
    activation_ok = pilot_target_writes_allowed(contract, activation)
    results: list[PilotDryRunOperationResult] = []

    for operation in normalized:
        if not preflight.passed:
            status = DryRunCheckStatus.FAIL
            reason = "preflight has not passed"
        elif not activation_ok:
            status = DryRunCheckStatus.FAIL
            reason = "required human activation is not satisfied"
        elif not contract.safety.action_allowed(operation.action):
            status = DryRunCheckStatus.FAIL
            reason = f"action is outside the safety envelope: {operation.action.value}"
        elif operation.action in _PATH_SCOPED_ACTIONS and operation.path is None:
            status = DryRunCheckStatus.FAIL
            reason = f"{operation.action.value} requires an explicit repository path"
        elif operation.path is not None and not contract.safety.path_allowed(operation.path):
            status = DryRunCheckStatus.FAIL
            reason = f"path is outside the safety envelope: {operation.path}"
        else:
            status = DryRunCheckStatus.PASS
            reason = "operation is permitted by the pilot safety envelope"

        results.append(
            PilotDryRunOperationResult(
                operation_id=operation.operation_id,
                action=operation.action,
                path=operation.path,
                status=status,
                reason=reason,
            )
        )

    result_tuple = tuple(results)
    return PilotDryRunReport(
        pilot_id=contract.pilot_id,
        contract_fingerprint=pilot_contract_fingerprint(contract),
        target_repository=contract.target.repository,
        baseline_sha=contract.target.baseline_sha,
        preflight_passed=preflight.passed,
        activation_satisfied=activation_ok,
        passed=(
            preflight.passed
            and activation_ok
            and all(item.status is DryRunCheckStatus.PASS for item in result_tuple)
        ),
        operations=result_tuple,
    )

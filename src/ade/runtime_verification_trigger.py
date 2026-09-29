from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .runtime_probe_registry import TrustedRuntimeProbeRegistry
from .runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    RuntimeVerificationError,
    RuntimeVerificationReport,
)


def runtime_verification_paths(task_id: str) -> tuple[str, str]:
    if (
        not isinstance(task_id, str)
        or not task_id
        or len(task_id) > 80
        or any(
            ch
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
            for ch in task_id
        )
    ):
        raise RuntimeVerificationError("task_id must be a safe identifier")
    prefix = f".autodev/runtime-verification/{task_id}"
    return f"{prefix}/contract.json", f"{prefix}/receipt.json"


def runtime_verification_report_path(task_id: str) -> str:
    contract_path, _ = runtime_verification_paths(task_id)
    prefix = contract_path.removesuffix("/contract.json")
    return f"{prefix}/report.json"


def runtime_verification_target_path(task_id: str) -> str:
    contract_path, _ = runtime_verification_paths(task_id)
    prefix = contract_path.removesuffix("/contract.json")
    return f"{prefix}/target.json"


@dataclass(frozen=True, slots=True)
class RuntimeVerificationPolicy:
    target_repository: str
    environment: str
    required_probe_ids: tuple[str, ...]
    max_attempts: int = 1
    timeout_seconds: int = 300
    schema_version: int = 1

    def __post_init__(self) -> None:
        # Reuse the contract's trusted validation with a fixed synthetic SHA.
        validated = RuntimeVerificationContract(
            verification_id="policy-validation",
            target_repository=self.target_repository,
            source_sha="a" * 40,
            environment=self.environment,
            required_probe_ids=self.required_probe_ids,
            max_attempts=self.max_attempts,
            timeout_seconds=self.timeout_seconds,
        )
        object.__setattr__(
            self,
            "required_probe_ids",
            validated.required_probe_ids,
        )
        if self.schema_version != 1:
            raise RuntimeVerificationError(
                "runtime verification policy schema_version must be 1"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "target_repository": self.target_repository,
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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeVerificationPolicy":
        if not isinstance(payload, dict):
            raise RuntimeVerificationError(
                "runtime verification policy must be a JSON object"
            )
        allowed = {
            "schema_version",
            "target_repository",
            "environment",
            "required_probe_ids",
            "max_attempts",
            "timeout_seconds",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise RuntimeVerificationError(
                f"unknown runtime verification policy fields: {sorted(unknown)}"
            )
        raw_probe_ids = payload.get("required_probe_ids")
        if not isinstance(raw_probe_ids, list):
            raise RuntimeVerificationError(
                "runtime verification required_probe_ids must be a list"
            )
        return cls(
            schema_version=payload.get("schema_version", 0),
            target_repository=str(payload.get("target_repository", "")),
            environment=str(payload.get("environment", "")),
            required_probe_ids=tuple(str(item) for item in raw_probe_ids),
            max_attempts=int(payload.get("max_attempts", 1)),
            timeout_seconds=int(payload.get("timeout_seconds", 300)),
        )


@dataclass(frozen=True, slots=True)
class RuntimeVerificationReceipt:
    verification_id: str
    task_id: str
    target_repository: str
    source_sha: str
    contract_fingerprint: str
    registry_fingerprint: str
    policy_fingerprint: str
    status: str = "ARMED"
    dispatch_count: int = 0
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RuntimeVerificationError(
                "runtime verification receipt schema_version must be 1"
            )
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise RuntimeVerificationError(
                "runtime verification receipt task_id must be non-empty"
            )
        if self.status not in {"ARMED", "DISPATCHED", "VERIFIED", "FAILED", "HUMAN_WAIT"}:
            raise RuntimeVerificationError(
                "runtime verification receipt status is invalid"
            )
        if type(self.dispatch_count) is not int or self.dispatch_count < 0:
            raise RuntimeVerificationError(
                "runtime verification receipt dispatch_count must be non-negative"
            )
        # Reuse trusted contract validation for identity/repository/SHA.
        RuntimeVerificationContract(
            verification_id=self.verification_id,
            target_repository=self.target_repository,
            source_sha=self.source_sha,
            environment="receipt-validation",
            required_probe_ids=("receipt-validation",),
        )
        for label, value in (
            ("contract_fingerprint", self.contract_fingerprint),
            ("registry_fingerprint", self.registry_fingerprint),
            ("policy_fingerprint", self.policy_fingerprint),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise RuntimeVerificationError(
                    f"{label} must be a lowercase SHA-256 hex digest"
                )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "verification_id": self.verification_id,
            "task_id": self.task_id,
            "target_repository": self.target_repository,
            "source_sha": self.source_sha,
            "contract_fingerprint": self.contract_fingerprint,
            "registry_fingerprint": self.registry_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "status": self.status,
            "dispatch_count": self.dispatch_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeVerificationReceipt":
        if not isinstance(payload, dict):
            raise RuntimeVerificationError(
                "runtime verification receipt must be a JSON object"
            )
        allowed = {
            "schema_version",
            "verification_id",
            "task_id",
            "target_repository",
            "source_sha",
            "contract_fingerprint",
            "registry_fingerprint",
            "policy_fingerprint",
            "status",
            "dispatch_count",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise RuntimeVerificationError(
                f"unknown runtime verification receipt fields: {sorted(unknown)}"
            )
        return cls(
            schema_version=payload.get("schema_version", 0),
            verification_id=str(payload.get("verification_id", "")),
            task_id=str(payload.get("task_id", "")),
            target_repository=str(payload.get("target_repository", "")),
            source_sha=str(payload.get("source_sha", "")),
            contract_fingerprint=str(payload.get("contract_fingerprint", "")),
            registry_fingerprint=str(payload.get("registry_fingerprint", "")),
            policy_fingerprint=str(payload.get("policy_fingerprint", "")),
            status=str(payload.get("status", "")),
            dispatch_count=payload.get("dispatch_count", -1),
        )


@dataclass(frozen=True, slots=True)
class RuntimeVerificationActivation:
    contract: RuntimeVerificationContract
    receipt: RuntimeVerificationReceipt
    should_dispatch: bool


def arm_post_merge_runtime_verification(
    *,
    policy: RuntimeVerificationPolicy,
    registry: TrustedRuntimeProbeRegistry,
    task_id: str,
    target_repository: str,
    trusted_merge_sha: str,
    existing_receipt: RuntimeVerificationReceipt | None = None,
) -> RuntimeVerificationActivation:
    if not isinstance(policy, RuntimeVerificationPolicy):
        raise RuntimeVerificationError(
            "policy must be a RuntimeVerificationPolicy"
        )
    if not isinstance(registry, TrustedRuntimeProbeRegistry):
        raise RuntimeVerificationError(
            "registry must be a TrustedRuntimeProbeRegistry"
        )
    if target_repository != policy.target_repository:
        raise RuntimeVerificationError(
            "trusted merge repository does not match runtime verification policy"
        )
    if not isinstance(task_id, str) or not task_id.strip():
        raise RuntimeVerificationError("task_id must be non-empty")

    contract = RuntimeVerificationContract(
        verification_id=f"rv-{trusted_merge_sha}",
        target_repository=target_repository,
        source_sha=trusted_merge_sha,
        environment=policy.environment,
        required_probe_ids=policy.required_probe_ids,
        max_attempts=policy.max_attempts,
        timeout_seconds=policy.timeout_seconds,
    )
    registry.ensure_contract_supported(contract)

    expected = RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id=task_id,
        target_repository=target_repository,
        source_sha=trusted_merge_sha,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint=registry.fingerprint(),
        policy_fingerprint=policy.fingerprint(),
        status="ARMED",
        dispatch_count=0,
    )

    if existing_receipt is None:
        return RuntimeVerificationActivation(
            contract=contract,
            receipt=expected,
            should_dispatch=True,
        )
    if not isinstance(existing_receipt, RuntimeVerificationReceipt):
        raise RuntimeVerificationError(
            "existing_receipt must be a RuntimeVerificationReceipt or null"
        )

    identity = (
        existing_receipt.verification_id == expected.verification_id
        and existing_receipt.task_id == expected.task_id
        and existing_receipt.target_repository == expected.target_repository
        and existing_receipt.source_sha == expected.source_sha
        and existing_receipt.contract_fingerprint == expected.contract_fingerprint
        and existing_receipt.registry_fingerprint == expected.registry_fingerprint
        and existing_receipt.policy_fingerprint == expected.policy_fingerprint
    )
    if identity:
        return RuntimeVerificationActivation(
            contract=contract,
            receipt=existing_receipt,
            should_dispatch=existing_receipt.status == "ARMED",
        )

    return RuntimeVerificationActivation(
        contract=contract,
        receipt=expected,
        should_dispatch=True,
    )

@dataclass(frozen=True, slots=True)
class RuntimeVerificationDispatch:
    receipt: RuntimeVerificationReceipt
    changed: bool


def record_runtime_verification_dispatch(
    *,
    contract: RuntimeVerificationContract,
    registry: TrustedRuntimeProbeRegistry,
    receipt: RuntimeVerificationReceipt,
) -> RuntimeVerificationDispatch:
    if not isinstance(contract, RuntimeVerificationContract):
        raise RuntimeVerificationError(
            "contract must be a RuntimeVerificationContract"
        )
    if not isinstance(registry, TrustedRuntimeProbeRegistry):
        raise RuntimeVerificationError(
            "registry must be a TrustedRuntimeProbeRegistry"
        )
    if not isinstance(receipt, RuntimeVerificationReceipt):
        raise RuntimeVerificationError(
            "receipt must be a RuntimeVerificationReceipt"
        )
    registry.ensure_contract_supported(contract)
    if receipt.verification_id != contract.verification_id:
        raise RuntimeVerificationError("runtime verification id drift")
    if receipt.target_repository != contract.target_repository:
        raise RuntimeVerificationError("runtime verification repository drift")
    if receipt.source_sha != contract.source_sha:
        raise RuntimeVerificationError("runtime verification source SHA drift")
    if receipt.contract_fingerprint != contract.fingerprint():
        raise RuntimeVerificationError("runtime verification contract drift")
    if receipt.registry_fingerprint != registry.fingerprint():
        raise RuntimeVerificationError("runtime verification registry drift")

    if receipt.status == "ARMED":
        return RuntimeVerificationDispatch(
            receipt=RuntimeVerificationReceipt(
                verification_id=receipt.verification_id,
                task_id=receipt.task_id,
                target_repository=receipt.target_repository,
                source_sha=receipt.source_sha,
                contract_fingerprint=receipt.contract_fingerprint,
                registry_fingerprint=receipt.registry_fingerprint,
                policy_fingerprint=receipt.policy_fingerprint,
                status="DISPATCHED",
                dispatch_count=receipt.dispatch_count + 1,
            ),
            changed=True,
        )

    return RuntimeVerificationDispatch(
        receipt=receipt,
        changed=False,
    )

@dataclass(frozen=True, slots=True)
class RuntimeVerificationCompletion:
    receipt: RuntimeVerificationReceipt
    changed: bool


def record_runtime_verification_report(
    *,
    contract: RuntimeVerificationContract,
    receipt: RuntimeVerificationReceipt,
    report: RuntimeVerificationReport,
) -> RuntimeVerificationCompletion:
    if not isinstance(contract, RuntimeVerificationContract):
        raise RuntimeVerificationError(
            "contract must be a RuntimeVerificationContract"
        )
    if not isinstance(receipt, RuntimeVerificationReceipt):
        raise RuntimeVerificationError(
            "receipt must be a RuntimeVerificationReceipt"
        )
    if not isinstance(report, RuntimeVerificationReport):
        raise RuntimeVerificationError(
            "report must be a RuntimeVerificationReport"
        )
    if receipt.verification_id != contract.verification_id:
        raise RuntimeVerificationError("runtime verification id drift")
    if receipt.source_sha != contract.source_sha:
        raise RuntimeVerificationError("runtime verification source SHA drift")
    if receipt.contract_fingerprint != contract.fingerprint():
        raise RuntimeVerificationError("runtime verification contract drift")
    if report.verification_id != contract.verification_id:
        raise RuntimeVerificationError("runtime verification report id drift")
    if report.source_sha != contract.source_sha:
        raise RuntimeVerificationError("runtime verification report source SHA drift")
    if report.contract_fingerprint != contract.fingerprint():
        raise RuntimeVerificationError(
            "runtime verification report contract drift"
        )

    if receipt.status in {"VERIFIED", "FAILED", "HUMAN_WAIT"}:
        return RuntimeVerificationCompletion(receipt=receipt, changed=False)
    if receipt.status != "DISPATCHED":
        raise RuntimeVerificationError(
            "runtime verification report requires DISPATCHED receipt"
        )

    if report.disposition is RuntimeVerificationDisposition.VERIFIED:
        status = "VERIFIED"
    elif report.disposition is RuntimeVerificationDisposition.FAILED:
        status = "FAILED"
    else:
        return RuntimeVerificationCompletion(receipt=receipt, changed=False)

    completed = RuntimeVerificationReceipt(
        verification_id=receipt.verification_id,
        task_id=receipt.task_id,
        target_repository=receipt.target_repository,
        source_sha=receipt.source_sha,
        contract_fingerprint=receipt.contract_fingerprint,
        registry_fingerprint=receipt.registry_fingerprint,
        policy_fingerprint=receipt.policy_fingerprint,
        status=status,
        dispatch_count=receipt.dispatch_count,
    )
    return RuntimeVerificationCompletion(receipt=completed, changed=True)

def record_runtime_verification_human_wait(
    receipt: RuntimeVerificationReceipt,
) -> RuntimeVerificationCompletion:
    if not isinstance(receipt, RuntimeVerificationReceipt):
        raise RuntimeVerificationError(
            "receipt must be a RuntimeVerificationReceipt"
        )
    if receipt.status == "HUMAN_WAIT":
        return RuntimeVerificationCompletion(receipt=receipt, changed=False)
    if receipt.status != "FAILED":
        raise RuntimeVerificationError(
            "runtime HUMAN_WAIT transition requires FAILED receipt"
        )
    waiting = RuntimeVerificationReceipt(
        verification_id=receipt.verification_id,
        task_id=receipt.task_id,
        target_repository=receipt.target_repository,
        source_sha=receipt.source_sha,
        contract_fingerprint=receipt.contract_fingerprint,
        registry_fingerprint=receipt.registry_fingerprint,
        policy_fingerprint=receipt.policy_fingerprint,
        status="HUMAN_WAIT",
        dispatch_count=receipt.dispatch_count,
    )
    return RuntimeVerificationCompletion(receipt=waiting, changed=True)


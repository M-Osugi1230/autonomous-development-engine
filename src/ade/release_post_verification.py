from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable

from .release_candidate import ReleaseEnvironment
from .release_deployment import (
    ReleaseDeploymentReceipt,
    ReleaseDeploymentStatus,
)
from .runtime_target_registry import (
    RuntimeTargetKind,
    RuntimeTargetResolution,
)
from .runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    RuntimeVerificationReport,
)


class ReleasePostVerificationError(ValueError):
    """Trusted post-promotion Runtime Verification validation failed."""


class ReleasePostVerificationDisposition(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    HUMAN_WAIT = "HUMAN_WAIT"


_ENVIRONMENT_KIND = {
    ReleaseEnvironment.PREVIEW: RuntimeTargetKind.PREVIEW,
    ReleaseEnvironment.STAGING: RuntimeTargetKind.STAGING,
    ReleaseEnvironment.PRODUCTION: RuntimeTargetKind.PRODUCTION,
}


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ReleasePostVerificationError(f"{field} must be sha256")
    return value


@dataclass(frozen=True, slots=True)
class ReleasePostVerificationBinding:
    deployment_request_id: str
    deployment_receipt_fingerprint: str
    deployment_id: str
    repository: str
    source_sha: str
    environment: ReleaseEnvironment
    runtime_contract: RuntimeVerificationContract
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleasePostVerificationError(
                "unsupported release post-verification schema version"
            )
        if (
            not isinstance(self.deployment_request_id, str)
            or not self.deployment_request_id
        ):
            raise ReleasePostVerificationError(
                "deployment_request_id must be non-empty"
            )
        object.__setattr__(
            self,
            "deployment_receipt_fingerprint",
            _sha256(
                self.deployment_receipt_fingerprint,
                field="deployment_receipt_fingerprint",
            ),
        )
        if not isinstance(self.deployment_id, str) or not self.deployment_id:
            raise ReleasePostVerificationError(
                "deployment_id must be non-empty"
            )
        if not isinstance(self.environment, ReleaseEnvironment):
            raise ReleasePostVerificationError(
                "environment must be ReleaseEnvironment"
            )
        if not isinstance(
            self.runtime_contract,
            RuntimeVerificationContract,
        ):
            raise ReleasePostVerificationError(
                "runtime_contract must be RuntimeVerificationContract"
            )
        if self.runtime_contract.target_repository != self.repository:
            raise ReleasePostVerificationError(
                "runtime contract repository drift"
            )
        if self.runtime_contract.source_sha != self.source_sha:
            raise ReleasePostVerificationError(
                "runtime contract source SHA drift"
            )
        if self.runtime_contract.environment != self.environment.value:
            raise ReleasePostVerificationError(
                "runtime contract environment drift"
            )

    @property
    def expected_target_kind(self) -> RuntimeTargetKind:
        return _ENVIRONMENT_KIND[self.environment]

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "deployment_request_id": self.deployment_request_id,
            "deployment_receipt_fingerprint": (
                self.deployment_receipt_fingerprint
            ),
            "deployment_id": self.deployment_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "environment": self.environment.value,
            "expected_target_kind": self.expected_target_kind.value,
            "runtime_contract": self.runtime_contract.canonical_dict(),
            "runtime_contract_fingerprint": (
                self.runtime_contract.fingerprint()
            ),
            "deployment_identity_required": True,
            "ci_success_is_not_runtime_success": True,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def build_release_post_verification_binding(
    *,
    deployment_receipt: ReleaseDeploymentReceipt,
    required_probe_ids: Iterable[str],
    max_attempts: int = 1,
    timeout_seconds: int = 300,
) -> ReleasePostVerificationBinding:
    if not isinstance(deployment_receipt, ReleaseDeploymentReceipt):
        raise ReleasePostVerificationError(
            "deployment_receipt must be ReleaseDeploymentReceipt"
        )
    if (
        deployment_receipt.status
        is not ReleaseDeploymentStatus.DEPLOYED
    ):
        raise ReleasePostVerificationError(
            "post-promotion verification requires DEPLOYED receipt"
        )
    if deployment_receipt.dispatch_count != 1:
        raise ReleasePostVerificationError(
            "post-promotion verification requires single deployment dispatch"
        )
    if deployment_receipt.deployment_id is None:
        raise ReleasePostVerificationError(
            "post-promotion verification requires deployment_id"
        )

    probes = tuple(required_probe_ids)
    seed = {
        "deployment_request_id": deployment_receipt.deployment_request_id,
        "deployment_receipt_fingerprint": deployment_receipt.fingerprint(),
        "deployment_id": deployment_receipt.deployment_id,
        "repository": deployment_receipt.repository,
        "source_sha": deployment_receipt.source_sha,
        "environment": deployment_receipt.environment.value,
        "required_probe_ids": sorted(probes),
        "max_attempts": max_attempts,
        "timeout_seconds": timeout_seconds,
    }
    verification_id = "release-rv-" + _fingerprint(seed)[:24]
    contract = RuntimeVerificationContract(
        verification_id=verification_id,
        target_repository=deployment_receipt.repository,
        source_sha=deployment_receipt.source_sha,
        environment=deployment_receipt.environment.value,
        required_probe_ids=probes,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )
    return ReleasePostVerificationBinding(
        deployment_request_id=deployment_receipt.deployment_request_id,
        deployment_receipt_fingerprint=deployment_receipt.fingerprint(),
        deployment_id=deployment_receipt.deployment_id,
        repository=deployment_receipt.repository,
        source_sha=deployment_receipt.source_sha,
        environment=deployment_receipt.environment,
        runtime_contract=contract,
    )


def _validate_target_resolution(
    *,
    binding: ReleasePostVerificationBinding,
    target: RuntimeTargetResolution,
) -> None:
    if not isinstance(target, RuntimeTargetResolution):
        raise ReleasePostVerificationError(
            "target must be RuntimeTargetResolution"
        )
    if target.spec.kind is not binding.expected_target_kind:
        raise ReleasePostVerificationError(
            "runtime target kind does not match release environment"
        )
    if not target.spec.deployment_required:
        raise ReleasePostVerificationError(
            "release runtime target must require deployment identity"
        )
    evidence = target.evidence
    if evidence.target_repository != binding.repository:
        raise ReleasePostVerificationError(
            "runtime target repository drift"
        )
    if evidence.source_sha != binding.source_sha:
        raise ReleasePostVerificationError(
            "runtime target source SHA drift"
        )
    if evidence.environment != binding.environment.value:
        raise ReleasePostVerificationError(
            "runtime target environment drift"
        )
    if evidence.deployment_id != binding.deployment_id:
        raise ReleasePostVerificationError(
            "runtime target deployment_id does not match completed deployment"
        )


@dataclass(frozen=True, slots=True)
class ReleasePostVerificationOutcome:
    binding_fingerprint: str
    target_evidence_fingerprint: str
    runtime_report_fingerprint: str
    disposition: ReleasePostVerificationDisposition
    deployment_id: str
    environment: ReleaseEnvironment
    failure_fingerprint: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleasePostVerificationError(
                "unsupported release verification outcome schema version"
            )
        for field_name in (
            "binding_fingerprint",
            "target_evidence_fingerprint",
            "runtime_report_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field=field_name),
            )
        if not isinstance(
            self.disposition,
            ReleasePostVerificationDisposition,
        ):
            object.__setattr__(
                self,
                "disposition",
                ReleasePostVerificationDisposition(self.disposition),
            )
        if not isinstance(self.environment, ReleaseEnvironment):
            raise ReleasePostVerificationError(
                "environment must be ReleaseEnvironment"
            )
        if not isinstance(self.deployment_id, str) or not self.deployment_id:
            raise ReleasePostVerificationError(
                "deployment_id must be non-empty"
            )
        if self.failure_fingerprint is not None:
            object.__setattr__(
                self,
                "failure_fingerprint",
                _sha256(
                    self.failure_fingerprint,
                    field="failure_fingerprint",
                ),
            )
        if (
            self.disposition
            is ReleasePostVerificationDisposition.HUMAN_WAIT
            and self.failure_fingerprint is None
        ):
            raise ReleasePostVerificationError(
                "HUMAN_WAIT release verification requires failure fingerprint"
            )
        if (
            self.disposition
            is not ReleasePostVerificationDisposition.HUMAN_WAIT
            and self.failure_fingerprint is not None
        ):
            raise ReleasePostVerificationError(
                "failure fingerprint is valid only for HUMAN_WAIT"
            )

    @property
    def promotion_verified(self) -> bool:
        return (
            self.disposition
            is ReleasePostVerificationDisposition.VERIFIED
        )

    @property
    def next_required_human_action(self) -> str | None:
        if (
            self.disposition
            is ReleasePostVerificationDisposition.HUMAN_WAIT
        ):
            return "review-release-runtime-verification-failure"
        return None

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "binding_fingerprint": self.binding_fingerprint,
            "target_evidence_fingerprint": (
                self.target_evidence_fingerprint
            ),
            "runtime_report_fingerprint": (
                self.runtime_report_fingerprint
            ),
            "disposition": self.disposition.value,
            "deployment_id": self.deployment_id,
            "environment": self.environment.value,
            "failure_fingerprint": self.failure_fingerprint,
            "promotion_verified": self.promotion_verified,
            "next_required_human_action": (
                self.next_required_human_action
            ),
            "rollback_authority": False,
            "auto_promote_next_environment": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def evaluate_release_post_verification(
    *,
    binding: ReleasePostVerificationBinding,
    target: RuntimeTargetResolution,
    report: RuntimeVerificationReport,
) -> ReleasePostVerificationOutcome:
    if not isinstance(binding, ReleasePostVerificationBinding):
        raise ReleasePostVerificationError(
            "binding must be ReleasePostVerificationBinding"
        )
    _validate_target_resolution(binding=binding, target=target)
    if not isinstance(report, RuntimeVerificationReport):
        raise ReleasePostVerificationError(
            "report must be RuntimeVerificationReport"
        )
    contract = binding.runtime_contract
    if report.verification_id != contract.verification_id:
        raise ReleasePostVerificationError(
            "runtime report verification_id drift"
        )
    if report.contract_fingerprint != contract.fingerprint():
        raise ReleasePostVerificationError(
            "runtime report contract fingerprint drift"
        )
    if report.source_sha != contract.source_sha:
        raise ReleasePostVerificationError(
            "runtime report source SHA drift"
        )

    if report.disposition is RuntimeVerificationDisposition.VERIFIED:
        disposition = ReleasePostVerificationDisposition.VERIFIED
        failure_fingerprint = None
    elif report.disposition is RuntimeVerificationDisposition.PENDING:
        disposition = ReleasePostVerificationDisposition.PENDING
        failure_fingerprint = None
    else:
        disposition = ReleasePostVerificationDisposition.HUMAN_WAIT
        failure_fingerprint = report.fingerprint()

    return ReleasePostVerificationOutcome(
        binding_fingerprint=binding.fingerprint(),
        target_evidence_fingerprint=target.evidence.fingerprint(),
        runtime_report_fingerprint=report.fingerprint(),
        disposition=disposition,
        deployment_id=binding.deployment_id,
        environment=binding.environment,
        failure_fingerprint=failure_fingerprint,
    )
